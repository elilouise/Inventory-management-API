from pydantic import BaseModel, Field, validator
from typing import List, Optional
from datetime import datetime
from enum import Enum


class OrderStatus(str, Enum):
    """Enum for order statuses"""
    PENDING = "pending"         # Order created but not yet processed
    PROCESSING = "processing"   # Order is being processed
    SHIPPED = "shipped"         # Order has been shipped
    DELIVERED = "delivered"     # Order has been delivered
    CANCELLED = "cancelled"     # Order has been cancelled


class OrderItemBase(BaseModel):
    """Base order item model with common attributes"""
    product_id: int             # Reference to product
    quantity: int = Field(..., gt=0)  # Quantity ordered (must be positive)


class OrderItemCreate(OrderItemBase):
    """Model for creating order items"""
    pass


class OrderItem(OrderItemBase):
    """Complete order item model with all fields"""
    id: int                     # Unique identifier
    order_id: int               # Reference to parent order
    unit_price: float           # Price per unit when ordered
    created_at: datetime        # Creation timestamp

    class Config:
        orm_mode = True


class OrderItemWithProduct(OrderItem):
    """Order item with product details"""
    product_name: str           # Name of the product
    product_sku: str            # SKU of the product


class OrderBase(BaseModel):
    """Base order model with common attributes"""
    shipping_address: str       # Delivery destination address
    shipping_method: Optional[str] = None  # Selected shipping service
    notes: Optional[str] = None  # Additional order comments


class OrderCreate(OrderBase):
    """Model for creating new orders"""
    items: List[OrderItemCreate]  # List of items in the order


class OrderUpdate(BaseModel):
    """Model for updating order status"""
    status: OrderStatus         # New order status
    tracking_number: Optional[str] = None  # Shipping tracking number
    notes: Optional[str] = None  # Additional notes about the update


class Order(OrderBase):
    """Complete order model with all fields"""
    id: int                     # Unique identifier
    order_number: str           # Human-readable unique order reference
    user_id: int                # Reference to customer who placed the order
    status: OrderStatus         # Current order status
    total_amount: float         # Total monetary value of the order
    tracking_number: Optional[str] = None  # Reference for shipping tracking
    created_at: datetime        # Order placement timestamp
    updated_at: Optional[datetime] = None  # Last update timestamp
    items: List[OrderItem] = []  # Items in this order

    class Config:
        orm_mode = True


class OrderWithUser(Order):
    """Order model with user details"""
    user_email: str             # Email of the ordering user
    user_full_name: str         # Full name of the ordering user
    items: List[OrderItemWithProduct] = []  # Items with product details