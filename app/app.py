# app/app.py
"""
Main application file with Flask application factory pattern.
"""

import os
import sys
import signal
import logging
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, g, session

# Import core modules
from app.core.logging_config import setup_flask_logging
from app.core.errors import register_error_handlers

from app.modules.users.models import ensure_user_schema, ensure_first_sysadmin
from app.modules.auth.security import current_user, login_required

logger = logging.getLogger(__name__)



def create_app():
    """
    Application factory function.
    Creates and configures the Flask application.
    """
    app = Flask(__name__)
    
    # ==================== Configuration ====================
    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-secret-key-PLEASE-change-in-production-12345'),
        SESSION_COOKIE_SECURE=False,  # Set to True only when using HTTPS
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=604800,  # 7 days in seconds
        MAX_CONTENT_LENGTH=50 * 1024 * 1024,
        UPLOAD_FOLDER=os.environ.get('UPLOAD_FOLDER', os.path.join(os.path.dirname(__file__), 'data', 'uploads')),
        ENV=os.environ.get('FLASK_ENV', 'development'),  # ← Changed default to development
        LOG_LEVEL=os.environ.get('LOG_LEVEL', 'INFO')
    )
    
    logger.info("Application starting up...")
    
    # Create upload folder if it doesn't exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # ==================== Setup Logging ====================
    setup_flask_logging(app)
    
    # ==================== Initialize Module Schemas ====================
    try:
        logger.info("Initializing database schemas...")
        
        # Then ensure base schemas exist
        from app.modules.send.storage import ensure_schema as ensure_send_schema
        from app.modules.fulfillment.storage import ensure_schema as ensure_fulfillment_schema
        from app.modules.inventory.storage import ensure_schema as ensure_inventory_schema
        from app.modules.inventory.assets import ensure_schema as ensure_assets_schema
        
        ensure_send_schema()
        ensure_fulfillment_schema()
        ensure_inventory_schema()
        ensure_assets_schema()
        
        logger.info("✅ Database schemas initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize schemas: {e}", exc_info=True)
    
    # ==================== Register Error Handlers ====================
    register_error_handlers(app)
    
    # ==================== Context Processors ====================
    @app.context_processor
    def inject_user_context():
        """Inject common user context AND sandbox detection into all templates."""
        from flask import request
        from app.modules.auth.security import current_user
        from app.modules.users.permissions import PermissionManager
        from app.core.module_access import get_user_available_modules
        from app.core.database import get_db_connection
        import os
        
        # App version and branding
        APP_VERSION = os.environ.get("APP_VERSION", "0.4.0")
        BRAND_TEAL = os.environ.get("BRAND_TEAL", "#00A3AD")
        
        # Default Gridline Services branding
        default_settings = {
            'instance_name': 'Gridline Services',
            'instance_subtitle': 'Enterprise Platform',
            'logo_url': None,
            'favicon_url': None,
            'primary_color': '#0066cc',
            'secondary_color': '#00b4d8',
            'sidebar_bg_start': '#1a1d2e',
            'sidebar_bg_end': '#2d3142',
            'topbar_bg': '#ffffff'
        }
        
        # DETECT SANDBOX MODE
        instance_id = request.args.get('instance_id', type=int)
        is_sandbox = False
        sandbox_instance_name = None
        
        if instance_id:
            try:
                with get_db_connection("core") as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT is_sandbox, name, display_name 
                        FROM instances 
                        WHERE id = %s
                    """, (instance_id,))
                    inst = cursor.fetchone()
                    cursor.close()
                    
                    if inst and inst.get('is_sandbox'):
                        is_sandbox = True
                        sandbox_instance_name = inst.get('display_name') or inst.get('name')
            except Exception as e:
                logger.warning(f"Failed to check sandbox status: {e}")
        
        cu = current_user()
        if not cu:
            return {
                'cu': None,
                'current_user': None,
                'can_send': False,
                'can_inventory': False,
                'can_asset': False,
                'can_fulfillment_customer': False,
                'can_fulfillment_service': False,
                'can_fulfillment_manager': False,
                'can_admin_users': False,
                'elevated': False,
                'is_sandbox': is_sandbox,
                'instance_id': instance_id,
                'instance_name': sandbox_instance_name if is_sandbox else default_settings['instance_name'],
                'instance_subtitle': 'SANDBOX MODE' if is_sandbox else default_settings['instance_subtitle'],
                'instance_logo': default_settings['logo_url'],
                'instance_favicon': default_settings['favicon_url'],
                'instance_colors': {
                    'primary': default_settings['primary_color'],
                    'secondary': default_settings['secondary_color'],
                    'sidebar_bg_start': default_settings['sidebar_bg_start'],
                    'sidebar_bg_end': default_settings['sidebar_bg_end'],
                    'topbar_bg': default_settings['topbar_bg']
                },
                'APP_VERSION': APP_VERSION,
                'BRAND_TEAL': BRAND_TEAL
            }
        
        # Get effective permissions
        effective_perms = PermissionManager.get_effective_permissions(cu)
        permission_level = cu.get('permission_level', '')
        is_elevated = permission_level in ['L1', 'L2', 'L3', 'S1']
        
        # OVERRIDE PERMISSIONS FOR SANDBOX
        if is_sandbox and permission_level in ['L3', 'S1']:
            # L3/S1 users get full permissions in sandbox
            effective_perms = {
                'can_send': True,
                'can_inventory': True,
                'can_asset': True,
                'can_fulfillment_customer': True,
                'can_fulfillment_service': True,
                'can_fulfillment_manager': True,
            }
        
        return {
            'cu': cu,
            'current_user': cu,
            'can_send': effective_perms.get('can_send', False) or is_elevated,
            'can_inventory': effective_perms.get('can_inventory', False) or is_elevated,
            'can_asset': effective_perms.get('can_asset', False) or is_elevated,
            'can_fulfillment_customer': effective_perms.get('can_fulfillment_customer', False) or is_elevated,
            'can_fulfillment_service': effective_perms.get('can_fulfillment_service', False) or is_elevated,
            'can_fulfillment_manager': effective_perms.get('can_fulfillment_manager', False) or is_elevated,
            'can_admin_users': is_elevated and permission_level in ['L1', 'L2', 'L3', 'S1'],
            'elevated': is_elevated,
            'available_modules': get_user_available_modules(cu) if cu else [],
            'is_sandbox': is_sandbox,
            'instance_id': instance_id,
            'instance_name': sandbox_instance_name if is_sandbox else default_settings['instance_name'],
            'instance_subtitle': 'SANDBOX MODE' if is_sandbox else default_settings['instance_subtitle'],
            'instance_logo': default_settings['logo_url'],
            'instance_favicon': default_settings['favicon_url'],
            'instance_colors': {
                'primary': default_settings['primary_color'],
                'secondary': default_settings['secondary_color'],
                'sidebar_bg_start': default_settings['sidebar_bg_start'],
                'sidebar_bg_end': default_settings['sidebar_bg_end'],
                'topbar_bg': default_settings['topbar_bg']
            },
            'APP_VERSION': APP_VERSION,
            'BRAND_TEAL': BRAND_TEAL
        }
    
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
        # Home module (PRIORITY ONE - must be first)
        from app.modules.home.views import bp as home_bp
        app.register_blueprint(home_bp)
        
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

        # Horizon - Global Admin Module (L3/S1 only)
        from app.modules.horizon import bp as horizon_bp
        app.register_blueprint(horizon_bp, url_prefix='/horizon')

        # Register Horizon filters
        from app.modules.horizon.filters import register_filters
        register_filters(app)

        # Register Horizon middleware
        from app.modules.horizon.middleware import inject_permission_context
        app.context_processor(inject_permission_context)
        
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
    @login_required
    def index():
        """Root route - redirect to home module."""
        return redirect(url_for('home.index'))
    
    # ==================== Health Check ====================
    @app.route("/health")
    def health():
        """Health check endpoint"""
        return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
    
    logger.info("Application initialization complete")
    
    # ==================== Cleanup on Shutdown ====================
    @app.teardown_appcontext
    def shutdown_session(exception=None):
        """Cleanup database connections on app shutdown."""
        from app.core.database import cleanup_all_pools
        cleanup_all_pools()
    
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
