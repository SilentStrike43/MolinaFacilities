"""
Interface Module - Core UI Components
Provides centralized CSS, JavaScript, and UI components for all modules.
"""
from flask import Blueprint

# Create blueprint with static folder
interface_bp = Blueprint(
    'interface',
    __name__,
    static_folder='static',
    static_url_path='/static/interface'
)

# No routes needed - this blueprint is only for serving static files