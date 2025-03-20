from pydantic import BaseSettings, PostgresDsn
from typing import Optional


class Settings(BaseSettings):
    """Application settings"""
    PROJECT_NAME: str = "FINESSE Inventory Management System"
    API_V1_STR: str = "/api/v1"
    
    # Database
    DATABASE_URL: PostgresDsn = "postgresql://postgres:postgres@localhost:5432/finesse_inventory"
    
    # Security
    SECRET_KEY: str = "eli_secret_key"  # Should be overridden in production
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 180
    
    # REDIS_URL = "redis://localhost:6379/0"  # Default database

    # Redis configuration
    REDIS_QUEUE_URL: str = "redis://localhost:6379/0"  # Database 0 for queues
    REDIS_CACHE_URL: str = "redis://localhost:6379/1"  # Database 1 for caching
    #REDIS_QUEUE_TIMEOUT: int = 600  # 10 minutes
    #REDIS_CACHE_TTL: int = 3600  # 1 hour
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()