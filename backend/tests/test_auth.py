# tests/test_auth.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models.models import User
from app.core.utils import verify_password, hash_password


def test_register_user_success(client):
    """Test successful user registration"""
    # Prepare test data
    user_data = {
        "email": "newuser@example.com",
        "full_name": "New Test User",
        "password": "securepassword123"
    }
    
    # Make request
    response = client.post("/api/v1/auth/register", json=user_data)
    
    # Check response
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == user_data["email"]
    assert data["full_name"] == user_data["full_name"]
    assert "id" in data
    assert data["is_active"] is True
    assert data["is_admin"] is False
    assert "hashed_password" not in data  # Ensure password is not returned
    
def test_register_existing_email(client, test_user):
    """Test registration with an email that already exists"""
    # Prepare test data with existing email
    user_data = {
        "email": "test@example.com",  # Same as test_user fixture
        "full_name": "Another Name",
        "password": "password123"
    }
    
    # Make request
    response = client.post("/api/v1/auth/register", json=user_data)
    
    # Check response
    assert response.status_code == 400
    assert "Email already registered" in response.json()["detail"]

def test_register_invalid_email(client):
    """Test registration with invalid email format"""
    # Prepare test data with invalid email
    user_data = {
        "email": "not-an-email",
        "full_name": "Invalid Email User",
        "password": "password123"
    }
    
    # Make request
    response = client.post("/api/v1/auth/register", json=user_data)
    
    # Check response (validation error)
    assert response.status_code == 422
    
def test_register_short_password(client):
    """Test registration with password that's too short"""
    # Prepare test data with short password
    user_data = {
        "email": "valid@example.com",
        "full_name": "Short Password User",
        "password": "short"  # Less than 8 characters
    }
    
    # Make request
    response = client.post("/api/v1/auth/register", json=user_data)
    
    # Check response (validation error)
    assert response.status_code == 422
    
def test_login_success(client, test_user, db_session):
    """Test successful login"""
    # Prepare login data
    login_data = {
        "username": "test@example.com",  # OAuth2 uses 'username' field
        "password": "password"
    }
    
    # Make request
    response = client.post("/api/v1/auth/login", data=login_data)  # Use data= for form data
    
    # Check response
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    
def test_login_wrong_email(client):
    """Test login with non-existent email"""
    # Prepare login data
    login_data = {
        "username": "nonexistent@example.com",
        "password": "password"
    }
    
    # Make request
    response = client.post("/api/v1/auth/login", data=login_data)
    
    # Check response
    assert response.status_code == 401
    assert "Incorrect email or password" in response.json()["detail"]
    
def test_login_wrong_password(client, test_user):
    """Test login with wrong password"""
    # Prepare login data
    login_data = {
        "username": "test@example.com",
        "password": "wrongpassword"
    }
    
    # Make request
    response = client.post("/api/v1/auth/login", data=login_data)
    
    # Check response
    assert response.status_code == 401
    assert "Incorrect email or password" in response.json()["detail"]

def test_login_inactive_user(client, db_session):
    """Test login with inactive user account"""

    hashed_password = hash_password("password")

    # Create inactive user
    inactive_user = User(
        email="inactive@example.com",
        full_name="Inactive User",
        hashed_password=hashed_password,  # "password"
        is_active=False,
        is_admin=False
    )
    db_session.add(inactive_user)
    db_session.commit()
    
    # Prepare login data
    login_data = {
        "username": "inactive@example.com",
        "password": "password"
    }
    
    # Make request
    response = client.post("/api/v1/auth/login", data=login_data)
    
    # Check response
    assert response.status_code == 400
    assert "Inactive user account" in response.json()["detail"]

def test_refresh_token_success(client, test_user):
    """Test successful token refresh"""
    # First get a token by logging in
    login_response = client.post("/api/v1/auth/login", data={
        "username": "test@example.com",
        "password": "password"
    })

    refresh_token = login_response.json()["refresh_token"]
    
    # Use refresh token to get a new token pair
    refresh_response = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    
    # Check response
    assert refresh_response.status_code == 200
    data = refresh_response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    
def test_refresh_invalid_token(client, test_user):
    """Test refresh with invalid token"""
    # Use an invalid token
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": "invalid-token"})
    
    # Check response
    assert response.status_code == 401
    assert "Could not validate credentials" in response.json()["detail"]

def test_password_verification_in_db(db_session, test_user):
    """Test that passwords are properly hashed and can be verified"""
    # Retrieve the test user from database
    user = db_session.query(User).filter(User.email == "test@example.com").first()
    
    # Verify the correct password works
    assert verify_password("password", user.hashed_password) is True
    
    # Verify wrong password fails
    assert verify_password("wrongpassword", user.hashed_password) is False

def test_new_user_in_database(client, db_session):
    """Test that a newly registered user actually exists in the database"""
    # Create a new user
    user_data = {
        "email": "dbcheck@example.com",
        "full_name": "Database Check User",
        "password": "checkpassword123"
    }
    
    # Register the user
    client.post("/api/v1/auth/register", json=user_data)
    
    # Check user exists in database
    user = db_session.query(User).filter(User.email == "dbcheck@example.com").first()
    
    # Verify user was created with correct data
    assert user is not None
    assert user.email == "dbcheck@example.com"
    assert user.full_name == "Database Check User"
    assert user.is_active is True
    assert user.is_admin is False
    assert verify_password("checkpassword123", user.hashed_password) is True