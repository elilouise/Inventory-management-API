from app.core.database import Base, engine
from app.models import User, Product, Inventory, Order, OrderItem

def recreate_tables():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

if __name__ == "__main__":
    recreate_tables()
    print("Tables recreated successfully.")
