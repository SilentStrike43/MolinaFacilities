# app/core/__init__.py
from .auth import (
    current_user, login_required, require_cap,
    require_asset, require_inventory, require_insights,
    require_admin, require_sysadmin,
    require_fulfillment_staff, require_fulfillment_customer, require_fulfillment_any,
    login_user, logout_user, ensure_user_schema, ensure_first_sysadmin, record_audit,
)
from .ui import inject_globals