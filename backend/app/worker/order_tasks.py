"""
Background tasks for order processing and fulfillment.
"""
import time
import logging
import uuid
import random

from sqlalchemy.orm import Session
from datetime import datetime
from app.core.database import SessionLocal
from app.models.models import Order, OrderStatus, Inventory

from app.core.cache import (
    invalidate_inventory_cache
)


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_db_session():
    """Get a fresh database session for the worker."""
    return SessionLocal()

def process_order(order_id: int, max_retries: int = 3, retry_delay: int = 5):
    """
    Process an order asynchronously after it's been created.
    
    This function:
    1. Updates the order status to PROCESSING
    2. Reserves inventory for the items
    3. Simulates payment processing
    4. Updates the order status based on success/failure
    
    Args:
        order_id: ID of the order to process
        max_retries: Maximum number of retry attempts for DB operations
        retry_delay: Delay in seconds between retries
    """
    db = get_db_session()
    logger.info(f"Processing order {order_id}")
    
    try:
        # Get the order
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            logger.error(f"Order {order_id} not found")
            db.close()
            return
        
        # Check if order is in PENDING state
        if order.status != OrderStatus.PENDING:
            logger.info(f"Order {order_id} is already in {order.status} state, skipping processing")
            db.close()
            return
        
        # Update order status to PROCESSING
        order.status = OrderStatus.PROCESSING
        db.commit()
        
        # Process each item and reserve inventory
        all_items_available = True
        for item in order.items:
            success = reserve_inventory(db, item.product_id, item.quantity, max_retries, retry_delay)
            if not success:
                all_items_available = False
                logger.error(f"Failed to reserve inventory for product {item.product_id} in order {order_id}")
                break
        
        # If any item is unavailable, cancel the order
        if not all_items_available:
            handle_order_failure(db, order_id, "Insufficient inventory")
            db.close()
            return
        
        # Simulate payment processing (in a real system, this would interact with a payment gateway)
        payment_success = simulate_payment_processing(order)
        
        if payment_success:
            # Payment successful, update order status
            logger.info(f"Payment processed successfully for order {order_id}")
            
            # In a real system, we might not immediately ship after payment
            # Instead, we might queue the order for fulfillment/shipping
            db.refresh(order)
            order.status = OrderStatus.PROCESSING  # Keep as processing until shipped
            db.commit()
            
            # Queue for shipping (would be a separate task in real system)
            # enqueue_task(prepare_for_shipping, order_id, queue_name='default')
        else:
            # Payment failed, handle failure
            handle_order_failure(db, order_id, "Payment processing failed")
    
    except Exception as e:
        logger.exception(f"Error processing order {order_id}: {str(e)}")
        db.rollback()
        
        # Try to handle the failure
        try:
            handle_order_failure(db, order_id, f"Processing error: {str(e)}")
        except Exception as inner_e:
            logger.exception(f"Error handling failure for order {order_id}: {str(inner_e)}")
    
    finally:
        db.close()


def reserve_inventory(db: Session, product_id: int, quantity: int, max_retries: int = 3, retry_delay: int = 5):
    """
    Reserve inventory for a product with retry logic for handling race conditions.
    
    Args:
        db: Database session
        product_id: ID of the product
        quantity: Quantity to reserve
        max_retries: Maximum retry attempts
        retry_delay: Delay between retries in seconds
        
    Returns:
        bool: True if reservation was successful, False otherwise
    """
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            # Get current inventory with fresh query
            inventory = db.query(Inventory).filter(Inventory.product_id == product_id).with_for_update().first()
            
            if not inventory:
                logger.error(f"No inventory record found for product {product_id}")
                return False
            
            # Check if sufficient stock is available
            available = inventory.quantity_in_stock - inventory.quantity_reserved
            if available < quantity:
                logger.error(f"Insufficient stock for product {product_id}. Requested: {quantity}, Available: {available}")
                return False
            
            # Reserve the inventory
            inventory.quantity_reserved += quantity
            db.commit()

            # Invalidate cache after successful commit
            invalidate_inventory_cache(product_id)
            
            logger.info(f"Reserved {quantity} units of product {product_id}")
            return True
        
        except Exception as e:
            db.rollback()
            retry_count += 1
            logger.warning(f"Retry {retry_count}/{max_retries} for product {product_id}: {str(e)}")
            
            if retry_count >= max_retries:
                logger.error(f"Failed to reserve inventory for product {product_id} after {max_retries} retries")
                return False
            
            # Wait before retrying
            time.sleep(retry_delay)
    
    return False


def handle_order_failure(db: Session, order_id: int, reason: str):
    """
    Handle an order failure by:
    1. Marking the order as cancelled
    2. Releasing any reserved inventory
    3. Logging the failure reason
    
    Args:
        db: Database session
        order_id: ID of the failed order
        reason: Reason for the failure
    """
    logger.info(f"Handling failure for order {order_id}: {reason}")
    
    # Get the order
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        logger.error(f"Failed order {order_id} not found")
        return
    
    # Update order status and add note
    order.status = OrderStatus.CANCELLED
    if order.notes:
        order.notes = f"{order.notes}\nCancelled due to: {reason}"
    else:
        order.notes = f"Cancelled due to: {reason}"
    
    # Release any reserved inventory
    for item in order.items:
        inventory = db.query(Inventory).filter(Inventory.product_id == item.product_id).first()
        if inventory and inventory.quantity_reserved > 0:
            # Safely decrease reserved quantity
            inventory.quantity_reserved = max(0, inventory.quantity_reserved - item.quantity)
            logger.info(f"Released {item.quantity} units of product {item.product_id}")
    
    db.commit()
    logger.info(f"Order {order_id} marked as cancelled")


def simulate_payment_processing(order: Order):
    """
    Simulate payment processing with a payment gateway.
    In a real application, this would integrate with a payment processor.
    
    Args:
        order: The order to process payment for
        
    Returns:
        bool: True if payment was successful, False otherwise
    """
    # Simulate processing time
    time.sleep(1)
    
    # In a real system, this would call a payment gateway API
    # For now, we'll simulate success with 95% probability
    return random.random() < 0.95


def prepare_for_shipping(order_id: int):
    """
    Prepare an order for shipping after successful payment.
    In a real system, this might:
    - Generate shipping labels
    - Notify warehouse staff
    - Update inventory from reserved to shipped
    - Generate tracking information
    
    Args:
        order_id: ID of the order to prepare for shipping
    """
    db = get_db_session()
    logger.info(f"Preparing order {order_id} for shipping")
    
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            logger.error(f"Order {order_id} not found")
            db.close()
            return
        
        # Only process orders in PROCESSING state
        if order.status != OrderStatus.PROCESSING:
            logger.info(f"Order {order_id} is in {order.status} state, not ready for shipping")
            db.close()
            return
        
        # Update order status to SHIPPED
        order.status = OrderStatus.SHIPPED
        
        # Generate a mock tracking number
        order.tracking_number = f"TRACK-{uuid.uuid4().hex[:12].upper()}"
        
        # Update inventory - Convert reserved items to shipped (deduct from stock)
        for item in order.items:
            inventory = db.query(Inventory).filter(Inventory.product_id == item.product_id).first()
            if inventory:
                inventory.quantity_in_stock -= item.quantity
                inventory.quantity_reserved -= item.quantity
                logger.info(f"Deducted {item.quantity} units of product {item.product_id} from inventory")
        
        db.commit()
        logger.info(f"Order {order_id} marked as shipped with tracking number {order.tracking_number}")
        
        # In a real system, here we would:
        # - Send shipping confirmation to customer
        # - Notify logistics/fulfillment team
        # - Update external systems
        
    except Exception as e:
        logger.exception(f"Error preparing order {order_id} for shipping: {str(e)}")
        db.rollback()
    
    finally:
        db.close()