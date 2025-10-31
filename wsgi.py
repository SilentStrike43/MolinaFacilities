# wsgi.py
"""
WSGI entry point for production deployment.
"""
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    logger.info("Importing Flask application...")
    from app.app import application  # ← Import directly!
    logger.info("✅ Flask application imported successfully")
except Exception as e:
    logger.error(f"❌ Failed to import Flask application: {e}")
    raise

if __name__ == "__main__":
    application.run(host='0.0.0.0', port=8000)