"""
Test configuration module for pytest.

This module sets up the test environment, database fixtures, and test data
for running automated tests on the FastAPI application. It uses an in-memory
SQLite database to isolate tests from the production environment.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import Base, get_db
from app.models.models import User, Product, Inventory, Order
from app.core.utils import hash_password


# Used an in-memory SQLite database for faster, isolated tests
# SQLite's in-memory mode is perfect for testing as it doesn't persist between test runs
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

# Create a test database engine with SQLite-specific connect args
# The check_same_thread arg is needed because SQLite doesn't support multi-threading by default
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})

# Create a sessionmaker for test database sessions
# autocommit=False ensures transactions must be explicitly committed
# autoflush=False prevents SQLAlchemy from automatically flushing changes
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """
    Create a fresh database session for each test function.
    
    This fixture creates all database tables before each test,
    provides a database session for the test to use, and then
    drops all tables after the test completes to ensure isolation.
    
    Yields:
        SQLAlchemy session: A database session for test operations
    """
    # Create all database tables defined in the models
    Base.metadata.create_all(bind=engine)
    
    # Create a new session for the test
    db = TestingSessionLocal()
    try:
        yield db  # This is where the test function will execute
    finally:
        # Clean up the session after the test completes
        db.close()
        # Drop all tables to ensure complete test isolation
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """
    Create a FastAPI TestClient with a dependency override for the database.
    
    This fixture overrides the get_db dependency in the application to use
    our test database session, allowing API endpoint tests to use the test database.
    
    Args:
        db_session: The database session fixture
        
    Yields:
        TestClient: A FastAPI test client configured to use the test database
    """
    # Override the standard get_db dependency with our test database session
    def override_get_db():
        try:
            yield db_session
        finally:
            pass  # We handle cleanup in the db_session fixture
    
    # Apply the dependency override to the FastAPI app
    app.dependency_overrides[get_db] = override_get_db
    
    # Create a TestClient using the modified app
    with TestClient(app) as c:
        yield c
    
    # Reset dependency overrides after the test to avoid affecting other tests
    app.dependency_overrides = {}


@pytest.fixture
def test_user(db_session):
    """
    Create a test user in the database.
    
    This fixture adds a standard test user to the database that can be used
    for testing authentication and user-related endpoints.
    
    Args:
        db_session: The database session fixture
        
    Returns:
        User: The created test user object
    """

    # Create a test user with hashed password

    hashed_password = hash_password("password")
    user = User(
        email="test@example.com",
        full_name="Test User",
        hashed_password=hashed_password,
        is_active=True,
        is_admin=False
    )
    
    # Add the user to the database and commit the changes
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)  # Refresh to ensure we have the latest data including the assigned ID
    return user


@pytest.fixture
def test_product(db_session):
    """
    Create a test product with associated inventory in the database.
    
    This fixture creates a product and its inventory record for testing
    product-related endpoints and order functionality.
    
    Args:
        db_session: The database session fixture
        
    Returns:
        Product: The created test product object
    """

    # Create a test product with standard details
    product = Product(
        name="Test T-Shirt",
        description="A test product",
        sku="TEST-001",  # Stock Keeping Unit - unique product identifier
        price=29.99,
        category="Clothing"
    )
    # Add the product to the database
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)  # Refresh to get the assigned product ID
    
    # Create inventory record for the product with initial stock
    inventory = Inventory(
        product_id=product.id,
        quantity_in_stock=100,  # Initial stock quantity
        quantity_reserved=0,    # No reserved units initially
        reorder_level=10        # Alert level for low stock
    )
    # Add the inventory to the database
    db_session.add(inventory)
    db_session.commit()
    
    return product