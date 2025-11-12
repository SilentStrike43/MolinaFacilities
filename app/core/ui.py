# app/core/ui.py - FIXED VERSION
"""
UI context processor - injects global variables and user permissions into templates
"""

import os
import json
from flask import g

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