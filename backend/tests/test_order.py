# tests/test_order.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.models import Order, OrderItem, OrderStatus, Inventory, Product, User
from app.core.utils import get_current_user
from unittest.mock import MagicMock, patch
from app.worker.order_tasks import process_order, reserve_inventory
from app.core.queue import enqueue_task
from app.worker import order_tasks



# Added patch decorator 
@patch('app.core.queue.redis_conn')
@patch('app.core.cache.redis_client')
def test_create_order_success(mock_cache_redis, mock_queue_redis, client, test_user, test_product, db_session, monkeypatch):
    """Test successful order creation with sufficient inventory"""

    # Mock Redis objects
    mock_queue_redis.return_value = MagicMock()
    mock_cache_redis.return_value = MagicMock()
    
    # Mock the enqueue_task function directly
    mock_job_id = "mock-job-12345"
    monkeypatch.setattr("app.routers.order.enqueue_task", lambda func, *args, **kwargs: mock_job_id)
    
    # Mock cache functions
    monkeypatch.setattr("app.routers.order.get_cache", lambda key: None)  # Force cache miss
    monkeypatch.setattr("app.routers.order.set_cache", lambda key, data, ttl: True)  # Successful cache set

    
    # Prepare order data
    order_data = {
        "shipping_address": "123 Test St, Test City, 12345",
        "shipping_method": "Standard Shipping",
        "notes": "Please leave at the door",
        "items": [
            {
                "product_id": test_product.id,
                "quantity": 2
            }
        ]
    }
    
    # Make request with authentication
    response = client.post(
        "/api/v1/orders",
        json=order_data,
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response
    assert response.status_code == 201
    data = response.json()
    assert data["shipping_address"] == order_data["shipping_address"]
    assert data["shipping_method"] == order_data["shipping_method"]
    assert data["notes"] == order_data["notes"]
    assert data["status"] == "pending"
    assert len(data["items"]) == 1
    assert data["items"][0]["product_id"] == test_product.id
    assert data["items"][0]["quantity"] == 2
    assert data["total_amount"] == test_product.price * 2
    
    # Verify the order was created in the database
    db_order = db_session.query(Order).filter(Order.id == data["id"]).first()
    assert db_order is not None
    assert db_order.status == OrderStatus.PENDING
    assert db_order.user_id == test_user.id


def test_create_order_insufficient_stock(client, test_user, test_product, db_session):
    """Test order creation with insufficient inventory"""
    # Modify inventory to have only 1 unit available
    inventory = db_session.query(Inventory).filter(Inventory.product_id == test_product.id).first()
    inventory.quantity_in_stock = 1
    db_session.commit()
    
    # Prepare order data requesting 2 units
    order_data = {
        "shipping_address": "123 Test St, Test City, 12345",
        "shipping_method": "Standard Shipping",
        "items": [
            {
                "product_id": test_product.id,
                "quantity": 2
            }
        ]
    }
    
    # Make request
    response = client.post(
        "/api/v1/orders",
        json=order_data,
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response - should return 400 Bad Request
    assert response.status_code == 400
    assert "Insufficient stock" in response.json()["detail"]
    
    # Verify no order was created
    db_orders = db_session.query(Order).all()
    assert len(db_orders) == 0


def test_create_order_nonexistent_product(client, test_user, db_session):
    """Test order creation with a product that doesn't exist"""
    # Prepare order data with non-existent product ID
    order_data = {
        "shipping_address": "123 Test St, Test City, 12345",
        "shipping_method": "Standard Shipping",
        "items": [
            {
                "product_id": 9999,  # Non-existent product ID
                "quantity": 1
            }
        ]
    }
    
    # Make request
    response = client.post(
        "/api/v1/orders",
        json=order_data,
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response - should return 404 Not Found
    assert response.status_code == 404
    assert "Product with id 9999 not found" in response.json()["detail"]


# Test order retrieval
def test_get_user_orders(client, test_user, test_product, db_session):
    """Test retrieving a user's orders"""
    # Create a test order in the database
    create_test_order(db_session, test_user, test_product)
    
    # Make request
    response = client.get(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["user_id"] == test_user.id
    assert data[0]["status"] == "pending"
    assert len(data[0]["items"]) == 1
    assert data[0]["items"][0]["product_id"] == test_product.id


def test_get_order_detail(client, test_user, test_product, db_session):
    """Test retrieving a specific order by ID"""
    # Create a test order
    order = create_test_order(db_session, test_user, test_product)
    
    # Make request
    response = client.get(
        f"/api/v1/orders/{order.id}",
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == order.id
    assert data["order_number"] == order.order_number
    assert data["status"] == "pending"
    assert data["user_id"] == test_user.id
    assert len(data["items"]) == 1


def test_get_order_unauthorized(client, test_user, test_product, db_session):
    """Test that a user cannot access another user's order"""
    # Create another user
    other_user = User(
        email="other@example.com",
        full_name="Other User",
        hashed_password="$2b$12$IKEQb00u5ecp6/hCJTvIleP48tQSX6jOAf0oFiNNusVD8Uxir7lRS",  # "password"
        is_active=True,
        is_admin=False
    )
    db_session.add(other_user)
    db_session.commit()
    
    # Create an order for the other user
    order = create_test_order(db_session, other_user, test_product)
    
    # Try to access the order as test_user
    response = client.get(
        f"/api/v1/orders/{order.id}",
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response - should be forbidden
    assert response.status_code == 403
    assert "Not authorized" in response.json()["detail"]


# Test admin functionality
def test_admin_get_all_orders(client, test_user, test_product, db_session):
    """Test that an admin can retrieve all orders"""
    # Make test_user an admin
    test_user.is_admin = True
    db_session.commit()
    
    # Create an order
    create_test_order(db_session, test_user, test_product)
    
    # Make request as admin
    response = client.get(
        "/api/v1/orders/admin",
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert "user_email" in data[0]
    assert "user_full_name" in data[0]
    assert data[0]["user_email"] == test_user.email


def test_non_admin_cannot_access_all_orders(client, test_user, db_session):
    """Test that non-admin users cannot access the admin endpoints"""
    # Ensure test_user is not an admin
    test_user.is_admin = False
    db_session.commit()
    
    # Make request
    response = client.get(
        "/api/v1/orders/admin",
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response - should be forbidden
    assert response.status_code == 403


# Test order status updates
def test_admin_update_order_status(client, test_user, test_product, db_session, monkeypatch):
    """Test that an admin can update an order's status"""
    # Make test_user an admin
    test_user.is_admin = True
    db_session.commit()
    
    # Mock Redis and cache functions
    monkeypatch.setattr("app.routers.order.invalidate_inventory_cache", lambda product_id: None)
    
    # Create an order AFTER getting the initial inventory state
    inventory = db_session.query(Inventory).filter(Inventory.product_id == test_product.id).first()
    initial_reserved = inventory.quantity_reserved
    
    order = create_test_order(db_session, test_user, test_product)
    
    # Prepare update data
    update_data = {
        "status": "processing",
        "tracking_number": "TRACK123456",
        "notes": "Processing has begun"
    }
    
    # Make request
    response = client.put(
        f"/api/v1/orders/{order.id}",
        json=update_data,
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processing"
    assert data["tracking_number"] == "TRACK123456"
    
    # Verify inventory was updated correctly
    inventory = db_session.query(Inventory).filter(Inventory.product_id == test_product.id).first()
    # The create_test_order already reserves 1 unit, and the status update reserves another
    assert inventory.quantity_reserved == initial_reserved + 2


def test_order_cancellation(client, test_user, test_product, db_session):
    """Test that a user can cancel their own order"""
    # Create an order
    order = create_test_order(db_session, test_user, test_product)
    
    # Get initial inventory state
    inventory = db_session.query(Inventory).filter(Inventory.product_id == test_product.id).first()
    initial_reserved = inventory.quantity_reserved
    
    # Make request to cancel
    response = client.delete(
        f"/api/v1/orders/{order.id}",
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response
    assert response.status_code == 204
    
    # Verify order was cancelled in database
    db_order = db_session.query(Order).filter(Order.id == order.id).first()
    assert db_order.status == OrderStatus.CANCELLED
    
    # Verify inventory was released
    inventory = db_session.query(Inventory).filter(Inventory.product_id == test_product.id).first()
    assert inventory.quantity_reserved == initial_reserved - 1


def test_cannot_cancel_shipped_order(client, test_user, test_product, db_session):
    """Test that shipped orders cannot be cancelled"""
    # Create an order and mark as shipped
    order = create_test_order(db_session, test_user, test_product)
    order.status = OrderStatus.SHIPPED
    db_session.commit()
    
    # Make request to cancel
    response = client.delete(
        f"/api/v1/orders/{order.id}",
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response - should fail
    assert response.status_code == 400
    assert f"Cannot cancel order in {OrderStatus.SHIPPED} status" in response.json()["detail"]


def test_process_order_background(test_user, test_product, db_session, monkeypatch):
    """Test the background order processing function"""
    # Get product ID before creating the order
    product_id = test_product.id
    
    # Get initial inventory state
    inventory = db_session.query(Inventory).filter(Inventory.product_id == product_id).first()
    initial_reserved = inventory.quantity_reserved
    
    # Create an order without reserving inventory
    order = Order(
        order_number=f"TEST-ORDER-123",
        user_id=test_user.id,
        status=OrderStatus.PENDING,
        total_amount=test_product.price,
        shipping_address="123 Test St, Test City",
        shipping_method="Standard Shipping"
    )
    db_session.add(order)
    db_session.flush()
    
    # Store the order ID for later
    order_id = order.id
    
    # Add order item
    order_item = OrderItem(
        order_id=order_id,
        product_id=product_id,
        quantity=1,
        unit_price=test_product.price
    )
    db_session.add(order_item)
    db_session.commit()
    
    # Mock the database session
    monkeypatch.setattr("app.worker.order_tasks.get_db_session", lambda: db_session)
    
    # Mock payment processing to always succeed
    monkeypatch.setattr("app.worker.order_tasks.simulate_payment_processing", lambda order: True)
    
    # Mock cache functions
    monkeypatch.setattr("app.worker.order_tasks.invalidate_inventory_cache", lambda product_id: None)
    
    # Call the process_order function directly
    process_order(order_id)
    
    # Query the order again 
    updated_order = db_session.query(Order).filter(Order.id == order_id).first()
    assert updated_order.status == OrderStatus.PROCESSING
    
    # Get updated inventory
    updated_inventory = db_session.query(Inventory).filter(Inventory.product_id == product_id).first()
    assert updated_inventory.quantity_reserved == initial_reserved + 1



#def test_process_order_payment_failure(test_user, test_product, db_session, monkeypatch):
#    """Test order processing with payment failure"""
#    # Create an order
#    order = create_test_order(db_session, test_user, test_product)
#    
#    # Mock payment processing to always fail
#    monkeypatch.setattr("app.worker.order_tasks.simulate_payment_processing", lambda order: False)
#    
#    # Call the process_order function directly
#    process_order(order.id)
#    
#    # Verify order was cancelled
#    db_session.refresh(order)
#    assert order.status == OrderStatus.CANCELLED
#    assert "Payment processing failed" in order.notes
#    
#    # Verify inventory was released
#    inventory = db_session.query(Inventory).filter(Inventory.product_id == test_product.id).first()
#    assert inventory.quantity_reserved == 0

def test_process_order_payment_failure(test_user, test_product, db_session, monkeypatch):
    """Test order processing with payment failure"""
    # Get product ID
    product_id = test_product.id
    
    # Get initial inventory state
    inventory = db_session.query(Inventory).filter(Inventory.product_id == product_id).first()
    initial_reserved = inventory.quantity_reserved
    
    # Create an order without reserving inventory
    order = Order(
        order_number=f"TEST-ORDER-FAIL",
        user_id=test_user.id,
        status=OrderStatus.PENDING,
        total_amount=test_product.price,
        shipping_address="123 Test St, Test City",
        shipping_method="Standard Shipping"
    )
    db_session.add(order)
    db_session.flush()
    
    # Store the order ID for later
    order_id = order.id
    
    # Add order item
    order_item = OrderItem(
        order_id=order_id,
        product_id=product_id,
        quantity=1,
        unit_price=test_product.price
    )
    db_session.add(order_item)
    db_session.commit()
    
    # Mock database session
    monkeypatch.setattr("app.worker.order_tasks.get_db_session", lambda: db_session)
    
    # Mock payment processing to always fail
    monkeypatch.setattr("app.worker.order_tasks.simulate_payment_processing", lambda order: False)
    
    # Mock cache functions
    monkeypatch.setattr("app.worker.order_tasks.invalidate_inventory_cache", lambda product_id: None)
    
    # Call the process_order function directly
    process_order(order_id)
    
    # Query the order again
    updated_order = db_session.query(Order).filter(Order.id == order_id).first()
    assert updated_order.status == OrderStatus.CANCELLED
    assert "Payment processing failed" in updated_order.notes
    
    # Get updated inventory
    updated_inventory = db_session.query(Inventory).filter(Inventory.product_id == product_id).first()
    assert updated_inventory.quantity_reserved == initial_reserved


def test_reserve_inventory_race_condition(test_product, db_session):
    """Test that inventory reservation handles concurrent updates correctly"""
    # Get initial inventory state
    inventory = db_session.query(Inventory).filter(Inventory.product_id == test_product.id).first()
    initial_stock = inventory.quantity_in_stock
    
    # Test basic reservation
    success = reserve_inventory(db_session, test_product.id, 1)
    assert success is True
    
    # Verify inventory was updated
    db_session.refresh(inventory)
    assert inventory.quantity_reserved == 1
    
    # Test reservation with exact remaining quantity
    remaining = initial_stock - inventory.quantity_reserved
    success = reserve_inventory(db_session, test_product.id, remaining)
    assert success is True
    
    # Test reservation beyond available stock
    success = reserve_inventory(db_session, test_product.id, 1)
    assert success is False


# Helper functions
def get_test_token(client, user):
    """Get a valid authentication token for testing"""
    response = client.post(
        "/api/v1/auth/login",
        data={"username": user.email, "password": "password"}
    )
    return response.json()["access_token"]


def create_test_order(db_session, user, product, quantity=1):
    """Create a test order in the database"""
    # Create order
    order = Order(
        order_number=f"TEST-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        user_id=user.id,
        status=OrderStatus.PENDING,
        total_amount=product.price * quantity,
        shipping_address="123 Test St, Test City",
        shipping_method="Standard Shipping"
    )
    db_session.add(order)
    db_session.flush()
    
    # Add order item
    order_item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        quantity=quantity,
        unit_price=product.price
    )
    db_session.add(order_item)
    
    # Reserve inventory 
    inventory = db_session.query(Inventory).filter(Inventory.product_id == product.id).first()
    if inventory:
        inventory.quantity_reserved += quantity
        
    db_session.commit()
    db_session.refresh(order)
    return order