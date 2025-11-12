# app/core/__init__.py
"""
Core utilities package.
Import specific modules directly to avoid circular dependencies.
"""

# Stub for backward compatibility
def record_audit(user, action, source, details=""):
    """Deprecated - use admin module's record_audit instead"""
    pass

def login_user(username, password):
    """Deprecated - use /auth/login route instead"""
    raise NotImplementedError("Use the /auth/login route instead")

def logout_user():
    """Deprecated - use /auth/logout route instead"""
    raise NotImplementedError("Use the /auth/logout route instead")