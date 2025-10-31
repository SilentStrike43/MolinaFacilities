# wsgi.py
"""
WSGI entry point for production deployment (Azure App Service)
"""
import sys
import os
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Importing Flask application...")

# Add the app directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

# Import and create the Flask app
try:
    from app.app import create_app
    
    # Create the application instance at module level
    # This is what Gunicorn will look for
    app = create_app()
    
    logger.info("✅ Flask application imported successfully")
    
except Exception as e:
    logger.error(f"❌ Failed to import Flask application: {e}", exc_info=True)
    # Don't raise - let Gunicorn handle the error
    # But create a dummy app so the import doesn't fail completely
    from flask import Flask
    app = Flask(__name__)
    
    @app.route("/")
    def error():
        return f"Application failed to load: {str(e)}", 500

# This allows running with `python wsgi.py` for testing
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)