from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.core.database import get_db
from app.core.utils import get_current_user, get_current_active_admin
from app.models.models import Inventory, Product, User
from app.schemas.inventory import (
    Inventory as InventorySchema,
    InventoryCreate,
    InventoryUpdate,
    InventoryStockUpdate,
    InventoryWithProduct
)

from app.core.cache import (
    get_cache, 
    set_cache, 
    delete_cache,
    invalidate_inventory_cache, 
    get_inventory_cache_key,
    INVENTORY_LIST_KEY,
    LOW_STOCK_KEY,
    INVENTORY_TTL,
    LOW_STOCK_TTL
)

router = APIRouter(prefix="/inventory", tags=["inventory"])

@router.get("", response_model=List[InventoryWithProduct])
def get_inventory(
    skip: int = 0,                                  # Pagination: Number of records to skip
    limit: int = 100,                               # Pagination: Maximum records to return
    product_id: Optional[int] = None,               # Filter: Optional specific product ID
    low_stock: Optional[bool] = None,               # Filter: If True, show only items with low stock
    db: Session = Depends(get_db),                  # Database session dependency
    current_user: User = Depends(get_current_user)  # Authentication: Ensure user is logged in
):
    """
    Get inventory items with optional filtering.
    
    Args:
        skip: Number of items to skip for pagination
        limit: Maximum number of items to return
        product_id: Filter by specific product ID
        low_stock: Filter for items below reorder level
        db: Database session
        current_user: Authenticated user
        
    Returns:
        List of inventory items with product details
    """
    # Determine if we can use cache based on query parameters
    cache_key = None
    cache_ttl = INVENTORY_TTL  # Default TTL
    
    # For standard queries (no filtering/pagination), check cache first
    if product_id is None and low_stock is None and skip == 0 and limit == 100:
        cache_key = INVENTORY_LIST_KEY  
        cached_data = get_cache(cache_key)
        if cached_data:
            return cached_data
    
    # For common low stock query, use dedicated cache
    if low_stock and product_id is None and skip == 0 and limit == 100:
        cache_key = LOW_STOCK_KEY 
        cache_ttl = LOW_STOCK_TTL  # Use shorter TTL for low stock data
        cached_data = get_cache(cache_key)
        if cached_data:
            return cached_data

    # Cache miss or custom query - get data from database
    query = db.query(
        Inventory,                                # Get all inventory fields
        Product.name.label("product_name"),       # Get product name with alias
        Product.sku.label("product_sku")          # Get product SKU with alias
    ).join(Product)                               # Join with Product table
    
    # Apply filters if provided
    if product_id:
        query = query.filter(Inventory.product_id == product_id)
    
    if low_stock:
        query = query.filter(
            (Inventory.quantity_in_stock - Inventory.quantity_reserved) <= Inventory.reorder_level
        )
    
    # Execute query with pagination
    result = query.offset(skip).limit(limit).all()
    
    # Convert SQLAlchemy objects to dictionaries
    inventory_list = []
    for inv, product_name, product_sku in result:


        # Build dictionary with all inventory fields
        # This line dynamically extracts ALL fields from the Inventory object by:
        # 1. Getting all columns from the table definition (__table__.columns)
        # 2. For each column, getting its name (c.name) and the corresponding value from the object (getattr(inv, c.name))
        # 3. Creating a dictionary with column names as keys and their values as values
        inv_dict = {c.name: getattr(inv, c.name) for c in inv.__table__.columns}
        
        # Add product information
        inv_dict["product_name"] = product_name
        inv_dict["product_sku"] = product_sku
        inventory_list.append(inv_dict)
    
    # Cache the result if it's a standard query pattern
    if cache_key:
        set_cache(cache_key, inventory_list, cache_ttl)
    
    return inventory_list




@router.get("/{inventory_id}", response_model=InventoryWithProduct)
def get_inventory_item(
    inventory_id: int,                             # Path parameter: ID of inventory to retrieve
    db: Session = Depends(get_db),                 # Database session dependency
    current_user: User = Depends(get_current_user) # Authentication: Ensure user is logged in
):
    """Get a specific inventory item by ID."""
    
    # Try to get from cache first - use inventory ID as part of the key
    cache_key = f"inventory:id:{inventory_id}"
    cached_data = get_cache(cache_key)
    
    if cached_data:
        # Return cached data if available
        return cached_data
    
    # Cache miss - query database
    result = db.query(
        Inventory,                                # Get the inventory record
        Product.name.label("product_name"),       # Get product name with alias
        Product.sku.label("product_sku")          # Get product SKU with alias
    ).join(Product).filter(Inventory.id == inventory_id).first()
    
    # Raise 404 if no inventory found with this ID
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inventory item with id {inventory_id} not found"
        )
    
    # Unpack the result tuple into separate variables
    inv, product_name, product_sku = result
    
    # Convert inventory SQLAlchemy object to dictionary with all column values
    inv_dict = {c.name: getattr(inv, c.name) for c in inv.__table__.columns}
    
    # Add product information to the response dictionary
    inv_dict["product_name"] = product_name
    inv_dict["product_sku"] = product_sku
    
    # Cache the result before returning
    set_cache(cache_key, inv_dict, INVENTORY_TTL)
    
    # Return combined inventory and product data
    return inv_dict


@router.post("", response_model=InventorySchema, status_code=status.HTTP_201_CREATED)
def create_inventory(
    inventory_data: InventoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_admin)
):
    """
    Create a new inventory record for a product.
    Admin only.
    
    Args:
        inventory_data: Inventory data to create
        db: Database session
        current_user: Admin user
        
    Returns:
        Created inventory record
        
    Raises:
        HTTPException: If product doesn't exist or already has inventory
    """
    # Check if product exists
    product = db.query(Product).filter(Product.id == inventory_data.product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with id {inventory_data.product_id} not found"
        )
    
    # Check if inventory already exists for this product
    existing_inventory = db.query(Inventory).filter(
        Inventory.product_id == inventory_data.product_id
    ).first()
    
    if existing_inventory:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Inventory already exists for product {inventory_data.product_id}"
        )
    
    # Create new inventory
    new_inventory = Inventory(**inventory_data.dict())
    
    # Set last_restock_date if adding initial stock
    if new_inventory.quantity_in_stock > 0:
        new_inventory.last_restock_date = datetime.utcnow()
    
    db.add(new_inventory)
    db.commit()
    db.refresh(new_inventory)

    # Invalidate cache after creating new inventory
    # 1. Invalidate by product ID
    invalidate_inventory_cache(new_inventory.product_id)

    # 2. Invalidate full inventory lists
    delete_cache(INVENTORY_LIST_KEY)
    
    return new_inventory


@router.put("/{inventory_id}", response_model=InventorySchema)
def update_inventory(
    inventory_id: int,                                     # Path parameter: ID of inventory to update
    update_data: InventoryUpdate,                          # Request body: Contains fields to update
    db: Session = Depends(get_db),                         # Database session dependency
    current_user: User = Depends(get_current_active_admin) # Auth: Ensures user is admin
):
    """
    Update an inventory record.
    Admin only.
    
    Args:
        inventory_id: ID of inventory to update
        update_data: Fields to update
        db: Database session
        current_user: Admin user
        
    Returns:
        Updated inventory record
        
    Raises:
        HTTPException: If inventory not found
    """

    # Find the inventory record to update
    inventory = db.query(Inventory).filter(Inventory.id == inventory_id).first()
    
    # Return 404 if inventory doesn't exist
    if not inventory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inventory with id {inventory_id} not found"
        )
    
    # Save product_id for cache invalidation
    product_id = inventory.product_id
    
    # Extract only fields that were actually provided in the request (ignores None values)
    update_dict = update_data.dict(exclude_unset=True)
    
    # If stock is being increased, automatically update the last_restock_date
    if "quantity_in_stock" in update_dict and update_dict["quantity_in_stock"] > inventory.quantity_in_stock:
        update_dict["last_restock_date"] = datetime.utcnow()
    
    # Apply each updated field to the inventory object
    for key, value in update_dict.items():
        setattr(inventory, key, value)
    
    # Save changes to database
    db.commit()
    
    # Reload the object with fresh data from database
    db.refresh(inventory)

    # Invalidate cache
    invalidate_inventory_cache(product_id)
    
    # Return updated inventory
    return inventory


@router.post("/{inventory_id}/adjust", response_model=InventorySchema)
def adjust_stock(
    inventory_id: int,                                    # Path parameter: ID of inventory to adjust
    stock_update: InventoryStockUpdate,                   # Request body: Contains quantity to adjust and reason
    db: Session = Depends(get_db),                        # Database session dependency
    current_user: User = Depends(get_current_active_admin) # Auth: Ensures user is admin
):
    """
    Adjust inventory stock quantity.
    Admin only.
    
    Args:
        inventory_id: ID of inventory to adjust
        stock_update: Amount to adjust (positive to add, negative to subtract)
        db: Database session
        current_user: Admin user
        
    Returns:
        Updated inventory record
        
    Raises:
        HTTPException: If inventory not found or insufficient stock
    """
    # Find the inventory record to adjust
    inventory = db.query(Inventory).filter(Inventory.id == inventory_id).first()
    
    # Return 404 if inventory doesn't exist
    if not inventory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inventory with id {inventory_id} not found"
        )
    
    # Prevent negative inventory - validate stock reduction doesn't exceed available quantity
    if stock_update.quantity < 0 and (inventory.quantity_in_stock + stock_update.quantity) < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot reduce stock below zero"
        )
    
    # Adjust the stock quantity (add or subtract based on sign of quantity)
    inventory.quantity_in_stock += stock_update.quantity
    
    # When adding new stock (positive quantity), update the last restock date
    if stock_update.quantity > 0:
        inventory.last_restock_date = datetime.utcnow()
    
    # Save changes to database
    db.commit()
    
    # Reload the object with fresh data from database
    db.refresh(inventory)
    
    # Invalidate cache after stock adjustment
    invalidate_inventory_cache(inventory.product_id)

    # Return updated inventory
    return inventory


@router.get("/product/{product_id}", response_model=InventorySchema)
def get_product_inventory(
    product_id: int,                              # Path parameter: ID of the product to look up
    db: Session = Depends(get_db),                # Database session dependency
    current_user: User = Depends(get_current_user) # Authentication: Ensure user is logged in
):
    """
    Get inventory for a specific product.
    
    Args:
        product_id: ID of the product
        db: Database session
        current_user: Authenticated user
        
    Returns:
        Inventory data for the product
        
    Raises:
        HTTPException: If inventory not found for product
    """


    # Try to get from cache first
    cache_key = get_inventory_cache_key(product_id)
    cached_inventory = get_cache(cache_key)
    
    if cached_inventory:
        return cached_inventory
    
    # Query inventory record associated with this product ID
    inventory = db.query(Inventory).filter(Inventory.product_id == product_id).first()
    
    # Return 404 if no inventory record exists for this product
    if not inventory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No inventory found for product with id {product_id}"
        )
    
    # Cache the result before returning
    inventory_dict = {c.name: getattr(inventory, c.name) for c in inventory.__table__.columns}
    set_cache(cache_key, inventory_dict, INVENTORY_TTL)
    
    # Return the inventory record directly (will be converted to Pydantic model)
    return inventory


@router.get("/status/low-stock", response_model=List[InventoryWithProduct])
def get_low_stock_items(
    db: Session = Depends(get_db),                          # Database session dependency
    current_user: User = Depends(get_current_active_admin)  # Auth: Ensures user is admin
):
    """
    Get inventory items with stock levels below or at reorder level.
    Admin only.
    
    Args:
        db: Database session
        current_user: Admin user
        
    Returns:
        List of low stock inventory items with product details
    """

    # Try to get from cache first
    cached_data = get_cache(LOW_STOCK_KEY)
    if cached_data:
        return cached_data
    
    # Query inventory items that need restocking, joining with products table
    result = db.query(
        Inventory,                                # Get all inventory fields
        Product.name.label("product_name"),       # Get product name with alias
        Product.sku.label("product_sku")          # Get product SKU with alias
    ).join(Product).filter(
        # Filter where available stock (in stock minus reserved) is at/below reorder level
        (Inventory.quantity_in_stock - Inventory.quantity_reserved) <= Inventory.reorder_level
    ).all()
    
    # Convert SQLAlchemy objects to dictionaries for response
    inventory_list = []
    for inv, product_name, product_sku in result:
        # Create dictionary with all inventory columns dynamically
        inv_dict = {c.name: getattr(inv, c.name) for c in inv.__table__.columns}
        # Add product details to each inventory item
        inv_dict["product_name"] = product_name
        inv_dict["product_sku"] = product_sku
        inventory_list.append(inv_dict)
    
    # Cache the result
    set_cache(LOW_STOCK_KEY, inventory_list, LOW_STOCK_TTL)
    
    # Return the list of low stock items
    return inventory_list