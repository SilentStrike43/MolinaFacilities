# app/core/ui.py
import os
import json
from flask import g
from .auth import current_user

APP_VERSION = os.environ.get("APP_VERSION", "0.4.0")
BRAND_TEAL   = os.environ.get("BRAND_TEAL", "#00A3AD")

def inject_globals():
    """Available to templates - includes properly parsed user with is_system flag."""
    cu = current_user()
    
    if cu:
        # Parse caps JSON to expose is_system flag
        try:
            caps = json.loads(cu.get("caps", "{}") or "{}")
            # Add is_system to the user dict for easy template access
            cu = dict(cu)  # Convert to mutable dict
            cu["is_system"] = caps.get("is_system", False) or cu.get("username") in ("AppAdmin", "system")
        except:
            if isinstance(cu, dict):
                cu["is_system"] = cu.get("username") in ("AppAdmin", "system")
    
    return {
        "cu": cu,
        "APP_VERSION": APP_VERSION,
        "BRAND_TEAL": BRAND_TEAL,
    }