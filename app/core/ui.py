# app/core/ui.py - UPDATED FOR NEW PERMISSION SYSTEM
"""
UI context processor - injects global variables and user permissions into templates
"""

import os
import json
from flask import g

from app.modules.auth.security import current_user
from app.modules.users.permissions import PermissionManager

APP_VERSION = os.environ.get("APP_VERSION", "0.4.0")
BRAND_TEAL = os.environ.get("BRAND_TEAL", "#00A3AD")

def get_user_permission_level(user_data):
    """Get the effective permission level for a user - matches backend logic"""
    if not user_data:
        return None
    
    # Check for system flag first
    try:
        caps = json.loads(user_data.get("caps", "{}") or "{}")
        if caps.get("is_system"):
            return "S1"
    except:
        pass
    
    # Check explicit permission_level field
    if user_data.get("permission_level"):
        return user_data["permission_level"]
    
    # Legacy compatibility - map old flags to new levels
    if user_data.get("is_sysadmin"):
        return "L2"
    elif user_data.get("is_admin"):
        return "L1"
    
    return None

def inject_globals():
    """Inject global variables into all templates."""
    from flask import g
    from app.modules.auth.security import current_user
    from app.modules.users.permissions import PermissionManager
    
    # Get current user (will use cached version if available)
    cu = current_user()
    
    if cu:
        # User is logged in - add their permissions
        # Use already-computed effective_permissions from cached user
        effective_perms = cu.get('effective_permissions', {})
        
        return {
            'cu': cu,
            'current_user': cu,
            'elevated': cu.get('permission_level') in ['S1', 'L3', 'L2', 'L1'],
            'APP_VERSION': APP_VERSION,
            'BRAND_TEAL': BRAND_TEAL,
            **effective_perms
        }
    else:
        # User not logged in
        return {
            'cu': None,
            'current_user': None,
            'elevated': False,
            'can_send': False,
            'can_inventory': False,
            'can_asset': False,
            'can_fulfillment_customer': False,
            'can_fulfillment_service': False,
            'can_fulfillment_manager': False,
            'can_admin_users': False,
            'can_view_audit_logs': False,
            'can_manage_system': False,
            'APP_VERSION': APP_VERSION,
            'BRAND_TEAL': BRAND_TEAL,
        }
    
    return {
        "cu": cu,
        "elevated": elevated,
        "APP_VERSION": APP_VERSION,
        "BRAND_TEAL": BRAND_TEAL,
    }