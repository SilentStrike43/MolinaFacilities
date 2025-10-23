# app/app.py
"""
Main application file with Flask application factory pattern.
"""

import os
import sys
import signal
import logging
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, g

# Import core modules
from app.core.logging_config import setup_flask_logging
from app.core.errors import register_error_handlers

from app.modules.users.models import ensure_user_schema, ensure_first_sysadmin
from app.modules.auth.security import current_user

from app.core.ui import inject_globals


logger = logging.getLogger(__name__)



def create_app():
    """
    Application factory function.
    Creates and configures the Flask application.
    """
    app = Flask(__name__)
    
    # ==================== Configuration ====================
    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production'),
        SESSION_COOKIE_SECURE=True,  # Azure uses HTTPS by default
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=3600 * 24 * 7,
        MAX_CONTENT_LENGTH=50 * 1024 * 1024,
        UPLOAD_FOLDER=os.environ.get('UPLOAD_FOLDER', os.path.join(os.path.dirname(__file__), 'data', 'uploads')),
        ENV=os.environ.get('FLASK_ENV', 'production'),
        LOG_LEVEL=os.environ.get('LOG_LEVEL', 'INFO')
    )
    
    logger.info("Application starting up...")
    
    # Create upload folder if it doesn't exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # ==================== Setup Logging ====================
    setup_flask_logging(app)
    
    # ==================== Setup Database ====================
    # Initialize user authentication schema
    ensure_user_schema()
    ensure_first_sysadmin()
    
    # ==================== Register Error Handlers ====================
    register_error_handlers(app)
    
    # ==================== Context Processors ====================
    app.context_processor(inject_globals)
    
    # ==================== Custom Jinja2 Filters ====================
    @app.template_filter('format_datetime')
    def format_datetime_filter(value, format='%Y-%m-%d %H:%M'):
        """Format datetime strings in templates"""
        if value == 'now':
            return datetime.now().strftime(format)
        if not value:
            return ''
        try:
            if isinstance(value, str):
                # Try parsing ISO format
                dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            else:
                dt = value
            return dt.strftime(format)
        except:
            return value
    
    # ==================== Register Blueprints ====================
    try:
        # Auth module
        from app.modules.auth.views import bp as auth_bp
        app.register_blueprint(auth_bp)
        
        # Users module
        from app.modules.users.views import bp as users_bp
        app.register_blueprint(users_bp)
        
        # Admin module
        from app.modules.admin.views import bp as admin_bp
        app.register_blueprint(admin_bp)
        
        # Send/Shipping module
        from app.modules.send import bp as send_bp
        app.register_blueprint(send_bp)
        
        # Fulfillment module
        from app.modules.fulfillment.views import bp as fulfillment_bp
        app.register_blueprint(fulfillment_bp)
        
        # Inventory module
        from app.modules.inventory import bp as inventory_bp
        app.register_blueprint(inventory_bp)
        
        # Asset Ledger module
        from app.modules.inventory.ledger import bp as asset_ledger_bp
        app.register_blueprint(asset_ledger_bp, url_prefix='/asset-ledger')
        
        logger.info("All blueprints registered successfully")
    except Exception as e:
        logger.critical(f"Failed to register blueprints: {e}", exc_info=True)
        raise
    
    # ==================== Initialize Module Schemas ====================
    try:
        # Initialize all database schemas
        from app.modules.send.storage import ensure_schema as ensure_send_schema
        from app.modules.fulfillment.storage import ensure_schema as ensure_fulfillment_schema
        from app.modules.inventory.storage import ensure_schema as ensure_inventory_schema
        from app.modules.inventory.assets import ensure_schema as ensure_assets_schema
        
        ensure_send_schema()
        ensure_fulfillment_schema()
        ensure_inventory_schema()
        ensure_assets_schema()
        
        logger.info("Database schemas initialized")
    except Exception as e:
        logger.error(f"Failed to initialize schemas: {e}", exc_info=True)
    
    # ==================== Home Route ====================
    @app.route("/")
    def home():
        """Home dashboard with metrics"""
        if not current_user():
            return redirect(url_for("auth.login"))
        
        user = current_user()
        elevated = user.get('is_admin') or user.get('is_sysadmin')
        
        # Initialize dashboard data
        dashboard_data = {
            'total_assets': 0,
            'pending_requests': 0,
            'shipments_this_month': 0,
            'completed_tasks': 0,
            'recent_activities': [],
            'my_tasks': [],
            'asset_trend': 0,
            'request_trend': 0,
        }
        
        # Get asset count if user has permission
        if user.get('can_asset') or elevated:
            try:
                from app.modules.inventory.assets import db as assets_db
                con = assets_db()
                result = con.execute("SELECT COUNT(*) as count FROM assets WHERE status='active'").fetchone()
                dashboard_data['total_assets'] = result['count'] if result else 0
                con.close()
            except Exception as e:
                logger.error(f"Error loading asset data: {e}")
        
        # Get fulfillment requests if user has permission
        if user.get('can_fulfillment_staff') or user.get('can_fulfillment_customer') or elevated:
            try:
                from app.modules.fulfillment.storage import fulfillment_db
                con = fulfillment_db()
                result = con.execute("SELECT COUNT(*) as count FROM requests WHERE status='pending'").fetchone()
                dashboard_data['pending_requests'] = result['count'] if result else 0
                con.close()
            except Exception as e:
                logger.error(f"Error loading fulfillment data: {e}")
        
        # Get shipment count if user has permission
        if user.get('can_send') or elevated:
            try:
                from app.modules.send.storage import jobs_db
                con = jobs_db()
                result = con.execute("""
                    SELECT COUNT(*) as count FROM print_jobs
                    WHERE date(ts_utc) >= date('now', 'start of month')
                """).fetchone()
                dashboard_data['shipments_this_month'] = result['count'] if result else 0
                con.close()
            except Exception as e:
                logger.error(f"Error loading shipment data: {e}")
        
        return render_template('dashboard.html', 
                             active='home', 
                             dashboard_data=dashboard_data,
                             cu=user,
                             elevated=elevated)
    
    # ==================== Health Check ====================
    @app.route("/health")
    def health():
        """Health check endpoint"""
        return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
    
    logger.info("Application initialization complete")
    
    return app


# ==================== Application Entry Point ====================
if __name__ == '__main__':
    # Create the application
    application = create_app()
    
    # Setup signal handlers for graceful shutdown
    def shutdown_handler(signum, frame):
        logger.info("Application shutting down...")
        # Clean up resources
        try:
            from app.core.database import cleanup_all_pools
            cleanup_all_pools()
            logger.info("Cleanup complete")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    
    # Run the application
    # Azure provides PORT environment variable, default to 5000 for local dev
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '127.0.0.1')
    debug = os.environ.get('FLASK_ENV') == 'development'
    
    logger.info(f"Starting server on {host}:{port}")
    application.run(
        host=host,
        port=port,
        debug=debug,
        use_reloader=debug
    )
# Create application instance for WSGI servers (gunicorn, Azure)
application = create_app()
