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
    """
    Inject global variables into all templates.
    Includes NEW permission system with effective_permissions calculation.
    """
    cu = current_user()
    elevated = False
    
    if cu:
        # Convert to mutable dict
        cu = dict(cu)
        
        # Get user's permission level
        cu["permission_level"] = get_user_permission_level(cu) or ""
        
        # Get NEW permission system effective permissions
        effective_perms = PermissionManager.get_effective_permissions(cu)
        
        # Merge effective permissions into cu object for template access
        cu.update(effective_perms)
        
        # Add permission level description
        cu["permission_level_desc"] = PermissionManager.get_permission_description(
            cu.get("permission_level", "")
        )
        
        # Set elevated flag (anyone with L1+ admin level)
        elevated = cu.get("permission_level", "") in ["L1", "L2", "L3", "S1"]
        
        # Legacy compatibility - keep old flags for existing templates
        if not elevated:
            elevated = cu.get("is_admin", False) or cu.get("is_sysadmin", False)
        
        # Add system flag
        cu["is_system"] = cu.get("is_system", False) or cu.get("username") in ("AppAdmin", "system")
    
    return {
        "cu": cu,
        "elevated": elevated,
        "APP_VERSION": APP_VERSION,
        "BRAND_TEAL": BRAND_TEAL,
    }