# Inventory Management System

This is a robust, scalable RESTful API-based inventory management and order processing system built with FastAPI, Redis, and PostgreSQL. 


## Overview

This project is a inventory management solution designed with e-commerce platforms in mind. It provides a comprehensive set of features for managing products, inventory, and orders with a focus on performance and reliability.

Key capabilities include:
- **Real-time inventory tracking** with reserved vs. available distinction
- **Asynchronous order processing** via Redis queue
- **Multi-tier caching strategy** for optimized performance
- **JWT-based authentication and authorization**
- **Complete API for inventory and order management**

## 🏗️ System Architecture

### Database Schema
The system is built around five core models:
- **User Model**: Authentication and authorization
- **Product Model**: Core product information with unique SKUs
- **Inventory Model**: Stock levels, reservation, and reorder metrics
- **Order Model**: Customer order tracking with status progression
- **OrderItem Model**: Individual items within orders

### API Components
- **Authentication API**: JWT-based token system with refresh capability
- **Inventory Management API**: Stock tracking, adjustments, and reporting
- **Order Processing API**: Order creation, status updates, and cancellation

### Background Processing
- Redis Queue-based job system with priority queues (high, default, low)
- Asynchronous order processing to improve API responsiveness
- Transaction-safe operations for inventory adjustments

### Caching Strategy
- Time-To-Live (TTL) Redis caching with active invalidation
- Different cache durations based on data volatility
- Write-through caching to maintain data consistency

## 🚀 Features

### Inventory Management
- Get inventory with optional filtering (low stock, by product)
- Create and update inventory records
- Adjust stock levels with reason tracking
- Low-stock reporting and alerts
- Automatic restock date tracking

### Order Processing
- Create multi-item orders with inventory validation
- View orders with proper authorization controls
- Update order status with corresponding inventory adjustments
- Cancel orders with inventory release
- Complete order lifecycle management

### Security & Performance
- Robust JWT authentication with refresh tokens
- Role-based access control for admin functions
- Redis caching for frequently accessed data
- Background job processing for time-consuming operations
- Proper error handling with meaningful HTTP status codes

## 🛠️ Technology Stack

- **FastAPI**
- **PostgreSQL**
- **SQLAlchemy** (ORM for database interactions)
- **Redis** (In-memory data store for caching and job queues)
- **RQ (Redis Queue)** (Background job processing)
- **Pydantic** (Data validation and settings management)


## 🔧 Installation & Setup

### Prerequisites
- Python 3.9+
- PostgreSQL
- Redis

### Setup Steps
```
# Clone the repository
git clone https://github.com/elilouise/finesse-inventory.git
cd finesse-inventory

# Set up virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env

# Run database migrations
alembic upgrade head

# Start the API server
uvicorn app.main:app --reload

# In a separate terminal, start the worker
python worker.py
```

## 🔄 API Endpoints

The API documentation is available at `/docs` when running the server locally.

Key endpoints include:
- `/api/auth/token`: Get authentication tokens
- `/api/inventory/`: Manage inventory records
- `/api/orders/`: Process and manage orders

## 🌐 Scalability Considerations

The system is designed with scaling in mind:
- **Stateless Authentication**: JWT-based auth for horizontal scaling
- **Background Processing**: Offloading heavy tasks to worker processes
- **Caching Strategy**: Reducing database load for read-heavy operations
- **Clean Architecture**: Separation of concerns for maintainability

## 📊 Performance Optimizations

Several strategies are implemented to maximize performance:
- **Prioritized Job Queues**: Critical operations take precedence
- **Selective Caching**: Frequently accessed data is cached with appropriate TTLs
- **Efficient Database Queries**: Optimized queries with proper indexing
- **Asynchronous Processing**: Non-blocking operations for improved throughput

## 🔒 Security Features

- **JWT Authentication**: Secure, token-based authentication
- **Role-Based Access**: Admin vs regular user permissions
- **Data Validation**: Input validation on all endpoints
- **Proper Error Handling**: Secure error responses

## ✅ Testing

The project includes comprehensive test coverage:
- Unit tests for core business logic
- Mocked dependencies for isolated testing
- Integration tests for API endpoints (coming soon...)

Run tests with:
```
pytest
```

## 👨‍💻 Development

Contributions are welcome! Please feel free to submit a Pull Request.
