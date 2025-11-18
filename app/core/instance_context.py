"""
Instance Context Management
Ensures all requests are scoped to a specific instance
"""
from flask import g, session
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


def get_current_instance():
    """
    Get current instance ID from context.
    
    For L3/S1 users: Check session for manually selected instance
    For L2 users: Use their assigned instance
    For L1 and below: Use their single instance
    """
    # Check if already set in g (from middleware)
    if hasattr(g, 'instance_id'):
        return g.instance_id
    
    # Get current user
    from app.modules.auth.security import current_user
    cu = current_user()
    
    if not cu:
        raise RuntimeError("No user context - instance_id cannot be determined")
    
    permission_level = cu.get('permission_level', '')
    
    # L3/S1: Check session for selected instance
    if permission_level in ['L3', 'S1']:
        from flask import session
        selected_instance = session.get('active_instance_id')
        
        if selected_instance:
            g.instance_id = selected_instance
            return selected_instance
        
        # No instance selected - they're in Horizon mode
        # Return None or raise error depending on context
        raise RuntimeError("L3/S1 user must select an instance first")
    
    # L2/L1: Use their assigned instance
    instance_id = cu.get('instance_id')
    if not instance_id:
        raise RuntimeError(f"User {cu.get('username')} has no instance_id")
    
    g.instance_id = instance_id
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