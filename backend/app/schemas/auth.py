from pydantic import BaseModel, EmailStr, Field
from typing import Optional


class UserBase(BaseModel):
    """Base user model with common attributes"""
    email: EmailStr  # User's email address for authentication and communication
    full_name: str    # User's display name for the system


class UserCreate(UserBase):
    """Model for user registration data"""
    password: str = Field(..., min_length=8)  # Password with minimum 8 characters


class UserLogin(BaseModel):
    """Model for user login credentials"""
    email: EmailStr  # Email for authentication
    password: str    # Password for verification


class UserInDB(UserBase):
    """Model representing user as stored in database"""
    id: int          # Unique user identifier
    is_active: bool  # Whether user account is active
    is_admin: bool   # Whether user has admin privileges

    class Config:
        orm_mode = True  # Enables ORM mode for SQLAlchemy models


class User(UserInDB):
    """User response model - excludes sensitive information"""
    pass


class Token(BaseModel):
    """Model for authentication tokens returned to client"""
    access_token: str   # JWT token for API authorization
    refresh_token: str  # Token to obtain new access tokens when expired
    token_type: str = "bearer"  # Token type (always "bearer")

class TokenRefresh(BaseModel):
    """Model for token refresh requests"""
    refresh_token: str  

class TokenPayload(BaseModel):
    """Model for JWT token payload data"""
    sub: Optional[str] = None  # Subject (typically user email)
    exp: Optional[int] = None  # Expiration timestamp