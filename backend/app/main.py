from fastapi import FastAPI
from app.core.config import settings
from app.core.database import engine
from app.models import models
from app.routers import auth, inventory, order

# Create all tables in the database
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

@app.get("/")
def root():
    return {"message": "Welcome to FINESSE Inventory Management System"}


# Include routers
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(inventory.router, prefix=settings.API_V1_STR)
app.include_router(order.router, prefix=settings.API_V1_STR)

