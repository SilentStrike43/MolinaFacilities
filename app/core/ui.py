# app/core/ui.py - FIXED VERSION
import os
import json
from flask import g

# FIX: Import from NEW auth system, not old one
from app.modules.auth.security import current_user

APP_VERSION = os.environ.get("APP_VERSION", "0.4.0")
BRAND_TEAL   = os.environ.get("BRAND_TEAL", "#00A3AD")

def inject_globals():
    """Available to templates - includes properly parsed user with ALL capabilities exposed."""
    cu = current_user()
    elevated = False
    
    if cu:
        # Parse caps JSON and expose ALL capabilities directly on the user object
        try:
            caps = json.loads(cu.get("caps", "{}") or "{}")
            # Convert to mutable dict
            cu = dict(cu)
            
            # Add is_system flag
            cu["is_system"] = caps.get("is_system", False) or cu.get("username") in ("AppAdmin", "system")
            
            # Expose ALL capabilities directly (so templates can check cu.can_send, etc.)
            cu["can_send"] = caps.get("can_send", False)
            cu["can_asset"] = caps.get("can_asset", False) or caps.get("inventory", False)  # Support both names
            cu["can_insights"] = caps.get("can_insights", False) or caps.get("insights", False)  # Support both names
            cu["can_users"] = caps.get("can_users", False) or caps.get("users", False)  # Support both names
            cu["can_fulfillment_staff"] = caps.get("can_fulfillment_staff", False) or caps.get("fulfillment_staff", False)
            cu["can_fulfillment_customer"] = caps.get("can_fulfillment_customer", False) or caps.get("fulfillment_customer", False)
            cu["can_inventory"] = caps.get("can_inventory", False) or caps.get("inventory", False)
            
        except:
            if isinstance(cu, dict):
                cu["is_system"] = cu.get("username") in ("AppAdmin", "system")
        
        # Set elevated flag for template
        elevated = cu.get("is_admin", False) or cu.get("is_sysadmin", False)
    
    return {
        "cu": cu,
        "elevated": elevated,  # Add this for the badge!
        "APP_VERSION": APP_VERSION,
        "BRAND_TEAL": BRAND_TEAL,
    }