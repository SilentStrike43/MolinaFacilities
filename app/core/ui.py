# app/core/ui.py
import os
from flask import g
from .auth import current_user

APP_VERSION = os.environ.get("APP_VERSION", "0.4.0")
BRAND_TEAL   = os.environ.get("BRAND_TEAL", "#00A3AD")

def inject_globals():
    # available to templates
    return {
        "cu": current_user(),
        "APP_VERSION": APP_VERSION,
        "BRAND_TEAL": BRAND_TEAL,
    }
