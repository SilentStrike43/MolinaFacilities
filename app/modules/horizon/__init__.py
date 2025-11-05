# app/modules/horizon/__init__.py
"""
Horizon Module - Global Admin for L3/S1 users
Multi-Tenant Instance Management
"""

from flask import Blueprint

bp = Blueprint('horizon', __name__, 
               url_prefix='/horizon', 
               template_folder='templates')

# Import views after blueprint is created to avoid circular imports
from . import views

# Export the blueprint
horizon_bp = bp