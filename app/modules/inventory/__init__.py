# app/modules/inventory/__init__.py
"""
Inventory module initialization.
Create the blueprint HERE before importing views.
"""

from flask import Blueprint

# Create the blueprint FIRST
bp = Blueprint("inventory", __name__, url_prefix="/inventory", template_folder="templates")

# Now import views (which will use the blueprint)
from . import views  # noqa: F401

# Export for compatibility
inventory_bp = bp