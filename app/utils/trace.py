import functools
import logging

logger = logging.getLogger("trace")

def trace(func):
    """Logs entry into a function with its name, for easy debugging."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger.info(f"ENTER: {func.__name__}")
        return func(*args, **kwargs)
    return wrapper

def trace_async(func):
    """Async version of trace()."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        logger.info(f"ENTER: {func.__name__}")
        return await func(*args, **kwargs)
    return wrapper