"""
Instance Context Management
Ensures all requests are scoped to a specific instance
"""

from contextvars import ContextVar
from functools import wraps
import logging

logger = logging.getLogger(__name__)

# Thread-safe instance context
_current_instance_id = ContextVar('current_instance_id', default=None)


def set_current_instance(instance_id: int):
    """Set the current instance for this request"""
    _current_instance_id.set(instance_id)
    logger.debug(f"Instance context set: {instance_id}")


def get_current_instance() -> int:
    """Get the current instance ID - raises if not set"""
    instance_id = _current_instance_id.get()
    if instance_id is None:
        raise RuntimeError("No instance context! Must call set_current_instance() first")
    return instance_id


def get_current_instance_safe() -> int:
    """Get current instance ID - returns None if not set"""
    return _current_instance_id.get()


def clear_current_instance():
    """Clear the instance context"""
    _current_instance_id.set(None)


def require_instance(f):
    """Decorator that ensures instance context is set"""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if _current_instance_id.get() is None:
            raise RuntimeError(f"{f.__name__} requires instance context")
        return f(*args, **kwargs)
    return wrapped