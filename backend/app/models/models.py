from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Float, Text, Enum, Table
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base
import uuid


class OrderStatus(str, enum.Enum):
    """Enum for order status"""
    PENDING = "pending"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class User(Base):
    """User model for authentication and authorization"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)                       # Unique identifier for the user
    email = Column(String, unique=True, index=True, nullable=False)          # User's email for login and communication
    full_name = Column(String, index=True, nullable=False)       # User's display name for identification
    hashed_password = Column(String, nullable=False)                         # Securely stored password (never store plaintext)
    is_active = Column(Boolean, default=True)                                # Flag to indicate if user account is active or disabled
    is_admin = Column(Boolean, default=False)                                # Flag to grant administrative privileges
    created_at = Column(DateTime(timezone=True), server_default=func.now())  # Timestamp when user was created
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())        # Timestamp when user was last updated

    # Relationships
    orders = relationship("Order", back_populates="user")


class Product(Base):
    """Product model for storing product information"""
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)                        # Unique identifier for the product
    sku = Column(String, unique=True, index=True, nullable=False)             # Stock Keeping Unit - unique product code
    name = Column(String, index=True, nullable=False)                         # Product display name
    description = Column(Text)                                                # Detailed product description
    price = Column(Float, nullable=False)                                     # Current selling price of the product
    weight = Column(Float)                                                    # Physical weight in kg, useful for shipping calculations
    dimensions = Column(String)                                               # Physical dimensions in "LxWxH" format (cm), for shipping
    category = Column(String, index=True)                                     # Product category for filtering and organization
    image_url = Column(String)                                                # URL to product image
    created_at = Column(DateTime(timezone=True), server_default=func.now())   # Timestamp when product was added
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())         # Timestamp when product was last modified

    # Relationships
    inventory = relationship("Inventory", back_populates="product", uselist=False)
    order_items = relationship("OrderItem", back_populates="product")


class Inventory(Base):
    """Inventory model for tracking stock levels"""
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, index=True)                                     # Unique identifier for inventory record
    product_id = Column(Integer, ForeignKey("products.id"), unique=True, nullable=False)   # Reference to associated product
    quantity_in_stock = Column(Integer, default=0, nullable=False)                         # Total physical units currently in stock
    quantity_reserved = Column(Integer, default=0, nullable=False)                         # Units allocated to processing orders
    reorder_level = Column(Integer, default=10)                                            # Threshold at which to reorder more inventory
    reorder_quantity = Column(Integer, default=50)                                         # Recommended quantity to purchase when reordering
    last_restock_date = Column(DateTime(timezone=True))                                    # Date when inventory was last replenished
    last_stock_count_date = Column(DateTime(timezone=True))                                # Date of last physical inventory count
    created_at = Column(DateTime(timezone=True), server_default=func.now())                # Timestamp when record was created
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())                      # Timestamp when record was last updated

    # Relationships
    product = relationship("Product", back_populates="inventory")

    @property
    def available_quantity(self):
        """Returns the actual available quantity (in stock minus reserved)"""
        return self.quantity_in_stock - self.quantity_reserved

    @property
    def needs_reorder(self):
        """Returns True if the available quantity is below or equal to the reorder level"""
        return self.available_quantity <= self.reorder_level


class Order(Base):
    """Order model for storing order information"""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)                                     # Unique identifier for the order 
    order_number = Column(String, unique=True, index=True, nullable=False)                 # Human-readable unique order identifier
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)                      # Reference to customer who placed the order
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING, nullable=False)        # Current state in order lifecycle
    total_amount = Column(Float, nullable=False)                                           # Total monetary value of the order
    shipping_address = Column(Text, nullable=False)                                        # Delivery destination address
    shipping_method = Column(String)                                                       # Selected shipping service (standard, express, etc.)
    tracking_number = Column(String)                                                       # Reference number for shipping tracking
    notes = Column(Text)                                                                   # Additional comments or special instructions
    created_at = Column(DateTime(timezone=True), server_default=func.now())                # Timestamp when order was placed
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())                      # Timestamp when order was last modified
    
    # Relationships
    user = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

    def generate_order_number(self):
        """Generate a unique order number"""
        # Simple implementation - could be enhanced for production
        return f"ORD-{uuid.uuid4().hex[:8].upper()}"


class OrderItem(Base):
    """OrderItem model for storing items in an order"""
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)                             # Unique identifier for the order item
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)            # Reference to parent order
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)        # Reference to purchased product
    quantity = Column(Integer, nullable=False)                                     # Number of units ordered
    unit_price = Column(Float, nullable=False)                                     # Price per unit at time of order (captures historical price)
    created_at = Column(DateTime(timezone=True), server_default=func.now())        # Timestamp when item was added to order
    
    # Relationships
    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")