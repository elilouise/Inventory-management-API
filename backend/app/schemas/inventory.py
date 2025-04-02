from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class InventoryBase(BaseModel):
    """Base inventory model with common attributes"""
    product_id: int              # Reference to the associated product
    quantity_in_stock: int       # Total physical units currently in stock
    quantity_reserved: int = 0   # Units allocated to processing orders
    reorder_level: int = 10      # Threshold at which to reorder more inventory
    reorder_quantity: int = 50   # Recommended quantity to purchase when reordering


class InventoryCreate(InventoryBase):
    """Model for creating new inventory records"""
    pass


class InventoryUpdate(BaseModel):
    """Model for updating inventory records - all fields optional"""
    quantity_in_stock: Optional[int] = None     # New total stock quantity
    quantity_reserved: Optional[int] = None     # New reserved quantity
    reorder_level: Optional[int] = None         # New reorder threshold
    reorder_quantity: Optional[int] = None      # New reorder quantity


class InventoryStockUpdate(BaseModel):
    """Model for updating only the stock quantity"""
    quantity: int = Field(...)  # Quantity to add (positive) or remove (negative)
    reason: Optional[str] = None      # Reason for the stock adjustment


class Inventory(InventoryBase):
    """Complete inventory model with all fields"""
    id: int                                      # Unique identifier
    last_restock_date: Optional[datetime] = None # Date when inventory was last replenished
    last_stock_count_date: Optional[datetime] = None # Date of last physical inventory count
    created_at: datetime                         # Record creation timestamp
    updated_at: Optional[datetime] = None        # Record update timestamp

    class Config:
        orm_mode = True
        
    @property
    def available_quantity(self) -> int:
        """Calculate available quantity (in stock minus reserved)"""
        return self.quantity_in_stock - self.quantity_reserved


class InventoryWithProduct(Inventory):
    """Inventory model with product information"""
    product_name: str    # Name of the associated product
    product_sku: str     # SKU of the associated product