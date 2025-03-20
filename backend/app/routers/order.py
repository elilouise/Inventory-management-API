from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import uuid

from app.core.database import get_db
from app.core.utils import get_current_user, get_current_active_admin
from app.models.models import Order, OrderItem, Product, Inventory, User, OrderStatus
from app.schemas.order import (
    Order as OrderSchema,
    OrderCreate,
    OrderUpdate,
    OrderWithUser
)
from app.schemas.order import OrderStatus as OrderStatusSchema
from app.core.queue import enqueue_task
from app.worker.order_tasks import process_order

from app.core.cache import (
    get_cache, 
    set_cache, 
    get_inventory_cache_key,
    invalidate_inventory_cache,
    INVENTORY_TTL
)

router = APIRouter(prefix="/orders", tags=["orders"])

@router.post("", response_model=OrderSchema, status_code=status.HTTP_201_CREATED)
def create_order(
    order_data: OrderCreate,                      # Order data from request body
    db: Session = Depends(get_db),                # Database connection
    current_user: User = Depends(get_current_user) # Authenticated user
):
    """
    Create a new order.
    
    Args:
        order_data: Order data including items
        db: Database session
        current_user: Authenticated user
        
    Returns:
        Created order
        
    Raises:
        HTTPException: If products don't exist or are out of stock
    """
    # Initialize variables to track order total and validated items
    total_amount = 0
    items_data = []
    
    # Validate each requested item
    for item in order_data.items:
        # Ensure product exists in database
        product = db.query(Product).filter(Product.id == item.product_id).first()
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product with id {item.product_id} not found"
            )
        
        # Check inventory availability - try cache first for performance
        available_quantity = None
        
        # Attempt to get inventory data from cache to avoid database query
        cache_key = get_inventory_cache_key(item.product_id)
        cached_inventory = get_cache(cache_key)
        
        if cached_inventory:
            # Cache hit: Calculate available quantity from cached data
            available_quantity = cached_inventory["quantity_in_stock"] - cached_inventory["quantity_reserved"]
        else:
            # Cache miss: Get inventory from database
            inventory = db.query(Inventory).filter(Inventory.product_id == item.product_id).first()
            if not inventory:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"No inventory found for product {product.name}"
                )
            
            # Calculate available quantity from database record
            available_quantity = inventory.quantity_in_stock - inventory.quantity_reserved
            
            # Cache inventory data for future requests
            inventory_dict = {c.name: getattr(inventory, c.name) for c in inventory.__table__.columns}
            set_cache(cache_key, inventory_dict, INVENTORY_TTL)
        
        # Verify requested quantity doesn't exceed available stock
        if available_quantity < item.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient stock for product {product.name}. Available: {available_quantity}"
            )
        
        # Add item price to order total
        item_price = product.price * item.quantity
        total_amount += item_price
        
        # Store validated item for database insertion
        items_data.append({
            "product_id": item.product_id,
            "quantity": item.quantity,
            "unit_price": product.price
        })
    
    # Create main order record
    new_order = Order(
        order_number=f"ORD-{uuid.uuid4().hex[:8].upper()}",  # Generate unique order ID
        user_id=current_user.id,
        status=OrderStatus.PENDING,  # All orders start as pending
        total_amount=total_amount,
        shipping_address=order_data.shipping_address,
        shipping_method=order_data.shipping_method,
        notes=order_data.notes
    )
    
    # Get order ID without committing transaction yet
    db.add(new_order)
    db.flush()  
    
    # Create individual order items
    for item_data in items_data:
        new_item = OrderItem(
            order_id=new_order.id,
            **item_data
        )
        db.add(new_item)
    
    # Save everything to database
    db.commit()
    db.refresh(new_order)
    
    # Queue background task for async processing
    job = enqueue_task(
        process_order, 
        new_order.id,
        queue_name='high'  # Process orders with high priority
    )
    
    return new_order


@router.get("", response_model=List[OrderSchema])
def get_orders(
    skip: int = 0,
    limit: int = 100,
    status: Optional[OrderStatusSchema] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get orders for the current user.
    
    Args:
        skip: Number of items to skip for pagination
        limit: Maximum number of items to return
        status: Filter by order status
        db: Database session
        current_user: Authenticated user
        
    Returns:
        List of orders
    """
    query = db.query(Order).filter(Order.user_id == current_user.id)
    
    # Apply status filter if provided
    if status:
        query = query.filter(Order.status == status)
    
    # Apply pagination
    orders = query.order_by(Order.created_at.desc()).offset(skip).limit(limit).all()
    
    return orders


@router.get("/admin", response_model=List[OrderWithUser])
def get_all_orders(
    skip: int = 0,
    limit: int = 100,
    status: Optional[OrderStatusSchema] = None,
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_admin)
):
    """
    Get all orders with user details (admin only).
    
    Args:
        skip: Number of items to skip for pagination
        limit: Maximum number of items to return
        status: Filter by order status
        user_id: Filter by user ID
        db: Database session
        current_user: Admin user
        
    Returns:
        List of orders with user details
    """
    query = db.query(
        Order,
        User.email.label("user_email"),
        User.full_name.label("user_full_name")
    ).join(User)
    
    # Apply filters
    if status:
        query = query.filter(Order.status == status)
    
    if user_id:
        query = query.filter(Order.user_id == user_id)
    
    # Apply pagination
    result = query.order_by(Order.created_at.desc()).offset(skip).limit(limit).all()
    
    # Convert to response model format
    order_list = []
    for order, user_email, user_full_name in result:
        # Create a dict with all order attributes
        order_dict = {c.name: getattr(order, c.name) for c in order.__table__.columns}
        order_dict["user_email"] = user_email
        order_dict["user_full_name"] = user_full_name
        
        # Include items
        order_dict["items"] = []
        for item in order.items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            item_dict = {c.name: getattr(item, c.name) for c in item.__table__.columns}
            item_dict["product_name"] = product.name if product else "Unknown Product"
            item_dict["product_sku"] = product.sku if product else "Unknown SKU"
            order_dict["items"].append(item_dict)
            
        order_list.append(order_dict)
    
    return order_list


@router.get("/{order_id}", response_model=OrderSchema)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get a specific order by ID.
    
    Args:
        order_id: ID of the order
        db: Database session
        current_user: Authenticated user
        
    Returns:
        Order details
        
    Raises:
        HTTPException: If order not found or doesn't belong to user
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with id {order_id} not found"
        )
    
    # Regular users can only see their own orders, admins can see all
    if not current_user.is_admin and order.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this order"
        )
    
    return order


@router.put("/{order_id}", response_model=OrderSchema)
def update_order_status(
    order_id: int,
    order_update: OrderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_admin)
):
    """
    Update order status (admin only).
    
    Args:
        order_id: ID of the order to update
        order_update: New status and optional tracking info
        db: Database session
        current_user: Admin user
        
    Returns:
        Updated order
        
    Raises:
        HTTPException: If order not found or status transition invalid
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with id {order_id} not found"
        )
    
    # Handle status transitions with inventory updates
    old_status = order.status
    new_status = order_update.status
    
    # Validate status transitions
    if old_status == OrderStatus.DELIVERED and new_status != OrderStatus.DELIVERED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change status of a delivered order"
        )
    
    if old_status == OrderStatus.CANCELLED and new_status != OrderStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot reactivate a cancelled order"
        )
    
    # Handle inventory updates based on status changes
    if new_status == OrderStatus.CANCELLED:
        # Unreserve inventory for cancelled orders
        for item in order.items:
            inventory = db.query(Inventory).filter(Inventory.product_id == item.product_id).first()
            if inventory:
                # Decrease reserved quantity
                inventory.quantity_reserved = max(0, inventory.quantity_reserved - item.quantity)
    
    elif old_status == OrderStatus.PENDING and new_status == OrderStatus.PROCESSING:
        # Reserve inventory when moving to processing
        for item in order.items:
            inventory = db.query(Inventory).filter(Inventory.product_id == item.product_id).first()
            if inventory:
                inventory.quantity_reserved += item.quantity
    
    elif old_status == OrderStatus.PROCESSING and new_status == OrderStatus.SHIPPED:
        # Decrease actual inventory when shipping (items no longer just reserved)
        for item in order.items:
            inventory = db.query(Inventory).filter(Inventory.product_id == item.product_id).first()
            if inventory:
                inventory.quantity_in_stock -= item.quantity
                inventory.quantity_reserved -= item.quantity
    
    # Update order
    order.status = new_status
    if order_update.tracking_number:
        order.tracking_number = order_update.tracking_number
    if order_update.notes:
        order.notes = order_update.notes
    
    db.commit()
    db.refresh(order)

    # Invalidate inventory cache for affected products
    if new_status == OrderStatus.CANCELLED or old_status == OrderStatus.PROCESSING or new_status == OrderStatus.PROCESSING:
        for item in order.items:
            invalidate_inventory_cache(item.product_id)
    
    return order


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Cancel an order if it's still in PENDING or PROCESSING state.
    
    Args:
        order_id: ID of the order to cancel
        db: Database session
        current_user: Authenticated user
        
    Raises:
        HTTPException: If order not found, doesn't belong to user, or can't be cancelled
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with id {order_id} not found"
        )
    
    # Regular users can only cancel their own orders, admins can cancel any
    if not current_user.is_admin and order.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to cancel this order"
        )
    
    # Check if order can be cancelled
    if order.status not in [OrderStatus.PENDING, OrderStatus.PROCESSING]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel order in {order.status} status"
        )
    
    # Release reserved inventory
    for item in order.items:
        inventory = db.query(Inventory).filter(Inventory.product_id == item.product_id).first()
        if inventory and inventory.quantity_reserved > 0:
            inventory.quantity_reserved = max(0, inventory.quantity_reserved - item.quantity)
    
    # Update order status
    order.status = OrderStatus.CANCELLED
    
    db.commit()
    
    # Invalidate inventory cache for all items in the order
    for item in order.items:
        invalidate_inventory_cache(item.product_id)


    return None  # 204 No Content