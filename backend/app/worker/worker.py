"""
Worker script to process background jobs from Redis Queue.

Run this script to start the worker:
    python worker.py

For multiple workers, run multiple instances of this script.
"""

import os
import logging
import redis
from rq import Worker, Connection, Queue
from app.core.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)

# Listen to all queues - adjust as needed
listen = ['high', 'default', 'low']

def start_worker():
    """Start a worker process listening to the specified queues."""
    redis_url = settings.REDIS_QUEUE_URL  
    conn = redis.from_url(redis_url)
    with Connection(conn):
        worker = Worker(list(map(Queue, listen)))
        logging.info(f"Worker started, listening to queues: {', '.join(listen)}")
        worker.work()


if __name__ == '__main__':
    start_worker()