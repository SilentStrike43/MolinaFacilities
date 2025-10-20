# app/modules/inventory/__init__.py
"""
Inventory module initialization.
Import the blueprint from views.py (where it's already created).
"""

# Import the blueprint that's already created in views.py
from .views import inventory_bp as bp

# Also export as inventory_bp for compatibility
inventory_bp = bp

# That's it! No need to create the blueprint here since views.py already does it