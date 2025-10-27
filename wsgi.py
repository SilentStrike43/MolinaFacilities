# wsgi.py
"""
WSGI entry point for production deployment.
Azure App Service will use this file to start the application.
"""
import os
import sys
import logging

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(__file__))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import and create the Flask application
try:
    from app.app import create_app
    
    logger.info("Creating Flask application...")
    app = create_app()
    logger.info("✅ Flask application created successfully")
    
except Exception as e:
    logger.error(f"❌ Failed to create Flask application: {e}")
    raise

if __name__ == "__main__":
    # For local testing
    app.run(host='0.0.0.0', port=8000)