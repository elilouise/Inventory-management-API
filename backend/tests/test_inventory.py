# tests/test_inventory.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from app.models.models import Inventory, Product, User, OrderStatus
from app.core.utils import get_current_user
from app.core.cache import get_inventory_cache_key


# GET inventory tests
def test_get_inventory(client, test_user, test_product, db_session, monkeypatch):
    """Test retrieving all inventory"""
    # Mock the cache functions to avoid issues with Redis
    monkeypatch.setattr("app.routers.inventory.get_cache", lambda key: None)
    monkeypatch.setattr("app.routers.inventory.set_cache", lambda key, data, ttl: None)
    
    # Make request with authentication
    response = client.get(
        "/api/v1/inventory",
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1  # One inventory item from test_product fixture
    assert data[0]["product_id"] == test_product.id
    assert "product_name" in data[0]
    assert "product_sku" in data[0]


def test_get_inventory_with_filters(client, test_user, test_product, db_session, monkeypatch):
    """Test retrieving inventory with filters"""
    # Mock cache functions
    monkeypatch.setattr("app.routers.inventory.get_cache", lambda key: None)
    monkeypatch.setattr("app.routers.inventory.set_cache", lambda key, data, ttl: None)
    
    # Create another product and inventory with different stock levels
    product2 = Product(
        name="Low Stock Product",
        description="A test product with low stock",
        sku="TEST-002",
        price=19.99,
        category="Clothing"
    )
    db_session.add(product2)
    db_session.commit()
    
    inventory2 = Inventory(
        product_id=product2.id,
        quantity_in_stock=5,
        quantity_reserved=0,
        reorder_level=10  # This makes it low stock
    )
    db_session.add(inventory2)
    db_session.commit()
    
    # Test product_id filter
    response = client.get(
        f"/api/v1/inventory?product_id={test_product.id}",
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["product_id"] == test_product.id
    
    # Test low_stock filter
    response = client.get(
        "/api/v1/inventory?low_stock=true",
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["product_id"] == product2.id


def test_get_inventory_item(client, test_user, test_product, db_session, monkeypatch):
    """Test retrieving a specific inventory item by ID"""
    # Mock cache functions
    monkeypatch.setattr("app.routers.inventory.get_cache", lambda key: None)
    monkeypatch.setattr("app.routers.inventory.set_cache", lambda key, data, ttl: None)
    
    # Get the inventory ID
    inventory = db_session.query(Inventory).filter(Inventory.product_id == test_product.id).first()
    
    # Make request
    response = client.get(
        f"/api/v1/inventory/{inventory.id}",
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == inventory.id
    assert data["product_id"] == test_product.id
    assert "product_name" in data
    assert "product_sku" in data


def test_get_nonexistent_inventory_item(client, test_user, db_session):
    """Test retrieving an inventory item that doesn't exist"""
    response = client.get(
        "/api/v1/inventory/999",
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


# CREATE inventory tests
def test_create_inventory(client, test_user, db_session, monkeypatch):
    """Test creating a new inventory record (admin only)"""
    # Make test_user an admin
    test_user.is_admin = True
    db_session.commit()
    
    # Mock cache functions
    monkeypatch.setattr("app.routers.inventory.invalidate_inventory_cache", lambda product_id: None)
    monkeypatch.setattr("app.routers.inventory.delete_cache", lambda key: None)
    
    # Create a product without inventory
    product = Product(
        name="New Product",
        description="A product with no inventory yet",
        sku="NEW-001",
        price=39.99,
        category="Accessories"
    )
    db_session.add(product)
    db_session.commit()
    
    # Prepare inventory data
    inventory_data = {
        "product_id": product.id,
        "quantity_in_stock": 50,
        "quantity_reserved": 0,
        "reorder_level": 10,
        "reorder_quantity": 25
    }
    
    # Make request
    response = client.post(
        "/api/v1/inventory",
        json=inventory_data,
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response
    assert response.status_code == 201
    data = response.json()
    assert data["product_id"] == product.id
    assert data["quantity_in_stock"] == 50
    assert "last_restock_date" in data  # Should be set automatically
    
    # Verify database state
    inventory = db_session.query(Inventory).filter(Inventory.product_id == product.id).first()
    assert inventory is not None


def test_create_inventory_nonexistent_product(client, test_user, db_session):
    """Test creating inventory for a product that doesn't exist"""
    # Make test_user an admin
    test_user.is_admin = True
    db_session.commit()
    
    # Prepare data with non-existent product ID
    inventory_data = {
        "product_id": 9999,
        "quantity_in_stock": 50,
        "reorder_level": 10
    }
    
    # Make request
    response = client.post(
        "/api/v1/inventory",
        json=inventory_data,
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_create_inventory_duplicate_product(client, test_user, test_product, db_session):
    """Test creating duplicate inventory for a product"""
    # Make test_user an admin
    test_user.is_admin = True
    db_session.commit()
    
    # Prepare data for product that already has inventory
    inventory_data = {
        "product_id": test_product.id,
        "quantity_in_stock": 50,
        "reorder_level": 10
    }
    
    # Make request
    response = client.post(
        "/api/v1/inventory",
        json=inventory_data,
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


def test_create_inventory_non_admin(client, test_user, db_session):
    """Test that non-admin users cannot create inventory"""
    # Ensure test_user is not admin
    test_user.is_admin = False
    db_session.commit()
    
    # Create a product
    product = Product(
        name="Another Product",
        description="A test product",
        sku="TEST-003",
        price=39.99,
        category="Accessories"
    )
    db_session.add(product)
    db_session.commit()
    
    # Prepare data
    inventory_data = {
        "product_id": product.id,
        "quantity_in_stock": 50,
        "reorder_level": 10
    }
    
    # Make request
    response = client.post(
        "/api/v1/inventory",
        json=inventory_data,
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response - should be forbidden
    assert response.status_code == 403


# UPDATE inventory tests
def test_update_inventory(client, test_user, test_product, db_session, monkeypatch):
    """Test updating inventory details"""
    # Make test_user an admin
    test_user.is_admin = True
    db_session.commit()
    
    # Mock cache function
    monkeypatch.setattr("app.routers.inventory.invalidate_inventory_cache", lambda product_id: None)
    
    # Get inventory ID
    inventory = db_session.query(Inventory).filter(Inventory.product_id == test_product.id).first()
    
    # Prepare update data
    update_data = {
        "quantity_in_stock": 200,
        "reorder_level": 20
    }
    
    # Make request
    response = client.put(
        f"/api/v1/inventory/{inventory.id}",
        json=update_data,
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response
    assert response.status_code == 200
    data = response.json()
    assert data["quantity_in_stock"] == 200
    assert data["reorder_level"] == 20
    
    # Verify database was updated
    db_session.refresh(inventory)
    assert inventory.quantity_in_stock == 200
    assert inventory.reorder_level == 20


def test_adjust_stock(client, test_user, test_product, db_session, monkeypatch):
    """Test adjusting stock quantities"""
    # Make test_user an admin
    test_user.is_admin = True
    db_session.commit()
    
    # Mock cache function
    monkeypatch.setattr("app.routers.inventory.invalidate_inventory_cache", lambda product_id: None)
    
    # Get inventory and initial quantity
    inventory = db_session.query(Inventory).filter(Inventory.product_id == test_product.id).first()
    initial_quantity = inventory.quantity_in_stock
    
    # Prepare adjustment data (add 50 units)
    adjust_data = {
        "quantity": 50,
        "reason": "Received new shipment"
    }
    
    # Make request
    response = client.post(
        f"/api/v1/inventory/{inventory.id}/adjust",
        json=adjust_data,
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response
    assert response.status_code == 200
    data = response.json()
    assert data["quantity_in_stock"] == initial_quantity + 50
    
    # Verify database was updated
    db_session.refresh(inventory)
    assert inventory.quantity_in_stock == initial_quantity + 50
    assert inventory.last_restock_date is not None  # Should be updated for increases





def test_adjust_stock_negative(client, test_user, test_product, db_session, monkeypatch):
    """Test removing stock"""
    # Make test_user an admin
    test_user.is_admin = True
    db_session.commit()
    
    # Mock cache function
    monkeypatch.setattr("app.routers.inventory.invalidate_inventory_cache", lambda product_id: None)
    
    # Get inventory and set quantity
    inventory = db_session.query(Inventory).filter(Inventory.product_id == test_product.id).first()
    inventory.quantity_in_stock = 100
    db_session.commit()
    
    # Prepare adjustment data (remove 30 units)
    adjust_data = {
        "quantity": -30,  
        "reason": "Damaged stock removal"
    }
    
    # Make request
    response = client.post(
        f"/api/v1/inventory/{inventory.id}/adjust",
        json=adjust_data,
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response
    assert response.status_code == 200
    data = response.json()
    assert data["quantity_in_stock"] == 70  
    
    # Verify database was updated
    db_session.refresh(inventory)
    assert inventory.quantity_in_stock == 70




def test_adjust_stock_below_zero(client, test_user, test_product, db_session):
    """Test attempting to adjust stock below zero"""
    # Make test_user an admin
    test_user.is_admin = True
    db_session.commit()
    
    # Get inventory and set quantity
    inventory = db_session.query(Inventory).filter(Inventory.product_id == test_product.id).first()
    inventory.quantity_in_stock = 10
    db_session.commit()
    
    # Prepare adjustment data (try to remove 20 units)
    adjust_data = {
        "quantity": -20,
        "reason": "This should fail"
    }
    
    # Make request
    response = client.post(
        f"/api/v1/inventory/{inventory.id}/adjust",
        json=adjust_data,
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response - should fail
    assert response.status_code == 400
    assert "Cannot reduce stock below zero" in response.json()["detail"]
    
    # Verify database was not updated
    db_session.refresh(inventory)
    assert inventory.quantity_in_stock == 10


# GET product inventory test
def test_get_product_inventory(client, test_user, test_product, db_session, monkeypatch):
    """Test getting inventory for a specific product"""
    # Mock cache functions
    monkeypatch.setattr("app.routers.inventory.get_cache", lambda key: None)
    monkeypatch.setattr("app.routers.inventory.set_cache", lambda key, data, ttl: None)
    
    # Make request
    response = client.get(
        f"/api/v1/inventory/product/{test_product.id}",
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response
    assert response.status_code == 200
    data = response.json()
    assert data["product_id"] == test_product.id


# GET low stock items test
def test_get_low_stock_items(client, test_user, db_session, monkeypatch):
    """Test retrieving items with low stock"""
    # Make test_user an admin
    test_user.is_admin = True
    db_session.commit()
    
    # Mock cache functions
    monkeypatch.setattr("app.routers.inventory.get_cache", lambda key: None)
    monkeypatch.setattr("app.routers.inventory.set_cache", lambda key, data, ttl: None)
    
    # Create product with low stock
    product = Product(
        name="Low Stock Item",
        description="A product with low stock",
        sku="LOW-001",
        price=15.99,
        category="Accessories"
    )
    db_session.add(product)
    db_session.commit()
    
    # Create inventory with stock at reorder level
    inventory = Inventory(
        product_id=product.id,
        quantity_in_stock=10,
        quantity_reserved=0,
        reorder_level=10  # At reorder level
    )
    db_session.add(inventory)
    db_session.commit()
    
    # Make request
    response = client.get(
        "/api/v1/inventory/status/low-stock",
        headers={"Authorization": f"Bearer {get_test_token(client, test_user)}"}
    )
    
    # Check response
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert any(item["product_id"] == product.id for item in data)


# Helper function for getting authentication token
def get_test_token(client, user):
    """Get a valid authentication token for testing"""
    response = client.post(
        "/api/v1/auth/login",
        data={"username": user.email, "password": "password"}
    )
    return response.json()["access_token"]