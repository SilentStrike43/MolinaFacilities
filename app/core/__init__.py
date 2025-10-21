# app/core/__init__.py
# Re-export from new auth system for backward compatibility
from app.modules.auth.security import (
    current_user, login_required, require_cap,
    require_asset, require_inventory, require_insights,
    require_admin, require_sysadmin,
    require_fulfillment_staff, require_fulfillment_customer, require_fulfillment_any,
)
from app.modules.users.models import ensure_user_schema, ensure_first_sysadmin

from .ui import inject_globals

# Stub for record_audit
def record_audit(user, action, source, details=""):
    pass

# Re-export login functions (these don't exist in new system, stub them out)
def login_user(username, password):
    """Deprecated - use views.py login route instead"""
    raise NotImplementedError("Use the /auth/login route instead")

def logout_user():
    """Deprecated - use views.py logout route instead"""
    raise NotImplementedError("Use the /auth/logout route instead")