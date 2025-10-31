# wsgi.py
"""
WSGI entry point for production deployment
"""
import sys
import os
import logging

# Setup logging first
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info("Importing Flask application...")

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(__file__))

try:
    from app.app import create_app
    
    # Create the Flask application instance
    app = create_app()
    
    logger.info("✅ Flask application imported successfully")
    
except Exception as e:
    logger.error(f"❌ Failed to import Flask application: {e}", exc_info=True)
    raise

# This is what Gunicorn looks for
if __name__ == "__main__":
    app.run()