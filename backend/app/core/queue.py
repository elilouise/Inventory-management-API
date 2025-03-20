"""
Redis Queue configuration for background task processing.
"""
import redis
from rq import Queue
from app.core.config import settings

# Connect to Redis server
redis_conn = redis.Redis.from_url(
    settings.REDIS_QUEUE_URL, 
    decode_responses=False,  # Keep binary data as is
    socket_connect_timeout=10
)

# Create queues with different priorities
default_queue = Queue('default', connection=redis_conn)  # Regular priority tasks
high_queue = Queue('high', connection=redis_conn)        # High priority tasks
low_queue = Queue('low', connection=redis_conn)          # Low priority tasks

# Dictionary of available queues
queues = {
    'default': default_queue,
    'high': high_queue,
    'low': low_queue
}

def enqueue_task(func, *args, queue_name='default', **kwargs):
    """
    Enqueue a task to be processed by a worker.
    
    Args:
        func: The function to be executed
        *args: Arguments to pass to the function
        queue_name: Which queue to use ('default', 'high', or 'low')
        **kwargs: Keyword arguments to pass to the function
        
    Returns:
        The job instance
    """
    queue = queues.get(queue_name, default_queue)
    return queue.enqueue(func, *args, **kwargs)