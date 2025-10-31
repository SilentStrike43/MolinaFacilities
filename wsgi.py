# wsgi.py
"""
WSGI entry point for Azure App Service
CRITICAL: The 'app' variable MUST be at module level for Gunicorn
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

# Import the app factory
from app.app import create_app

# CREATE THE APP AT MODULE LEVEL - THIS IS CRITICAL
# Gunicorn looks for 'app' in this exact location
app = create_app()

# That's it - keep it simple
# Don't wrap in try/except, don't put in functions, just create it