# app/core/cache.py
import json
import logging
from typing import Optional, Dict, Any, List
from redis import Redis
from app.core.config import settings

# Configure logging
logger = logging.getLogger(__name__)

# Initialize Redis connection
redis_client = Redis.from_url(
    settings.REDIS_CACHE_URL,
    socket_connect_timeout=2,
    socket_timeout=2,
    decode_responses=False
)

# Cache prefixes and TTLs
INVENTORY_PREFIX = "inv:"
INVENTORY_LIST_KEY = "inv:all"
LOW_STOCK_KEY = "inv:low_stock"

# Default TTLs (in seconds)
DEFAULT_TTL = 300  # 5 minutes
INVENTORY_TTL = 600  # 10 minutes
LOW_STOCK_TTL = 180  # 3 minutes

def get_inventory_cache_key(product_id: int) -> str:
    """Generate cache key for a specific inventory item"""
    return f"{INVENTORY_PREFIX}{product_id}"

def set_cache(key: str, data: Any, ttl: int = DEFAULT_TTL) -> bool:
    """Set data in cache with expiration"""
    try:
        serialized = json.dumps(data)
        return redis_client.setex(key, ttl, serialized)
    except Exception as e:
        logger.error(f"Cache set error for {key}: {str(e)}")
        return False

def get_cache(key: str) -> Optional[Any]:
    """Get data from cache"""
    try:
        data = redis_client.get(key)
        if data:
            return json.loads(data)
        return None
    except Exception as e:
        logger.error(f"Cache get error for {key}: {str(e)}")
        return None

def delete_cache(key: str) -> bool:
    """Delete a cache entry"""
    try:
        return redis_client.delete(key) > 0
    except Exception as e:
        logger.error(f"Cache delete error for {key}: {str(e)}")
        return False

def invalidate_inventory_cache(product_id: int) -> None:
    """Invalidate cache for a specific inventory item and related collections"""
    try:
        # Delete specific inventory cache
        delete_cache(get_inventory_cache_key(product_id))
        # Delete collection caches that might contain this inventory
        delete_cache(INVENTORY_LIST_KEY)
        delete_cache(LOW_STOCK_KEY)
    except Exception as e:
        logger.error(f"Cache invalidation error for product {product_id}: {str(e)}")