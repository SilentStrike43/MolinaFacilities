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
        SESSION_COOKIE_SECURE=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=604800,
        MAX_CONTENT_LENGTH=50 * 1024 * 1024,
        UPLOAD_FOLDER=os.environ.get('UPLOAD_FOLDER', os.path.join(os.path.dirname(__file__), 'data', 'uploads')),
        ENV=os.environ.get('FLASK_ENV', 'development'),
        LOG_LEVEL=os.environ.get('LOG_LEVEL', 'INFO'),
        
        # ==================== CARRIER API CONFIG ====================
        # USPS (OAuth 2.0)
        USPS_CONSUMER_KEY=os.environ.get('USPS_CONSUMER_KEY'),
        USPS_CONSUMER_SECRET=os.environ.get('USPS_CONSUMER_SECRET'),
        USPS_API_URL=os.environ.get('USPS_API_URL', 'https://api.usps.com'),
        
        # UPS (OAuth 2.0)
        UPS_CLIENT_ID=os.environ.get('UPS_CLIENT_ID'),
        UPS_CLIENT_SECRET=os.environ.get('UPS_CLIENT_SECRET'),
        UPS_ACCOUNT_NUMBER=os.environ.get('UPS_ACCOUNT_NUMBER'),
        UPS_API_URL=os.environ.get('UPS_API_URL', 'https://onlinetools.ups.com/api'),
        
        # FedEx - Ship API (for auto-sync and address validation)
        FEDEX_SHIP_API_KEY=os.environ.get('FEDEX_SHIP_API_KEY'),
        FEDEX_SHIP_SECRET_KEY=os.environ.get('FEDEX_SHIP_SECRET_KEY'),
        FEDEX_ACCOUNT_NUMBER=os.environ.get('FEDEX_ACCOUNT_NUMBER'),
        
        # FedEx - Track API (for tracking)
        FEDEX_TRACK_API_KEY=os.environ.get('FEDEX_TRACK_API_KEY'),
        FEDEX_TRACK_SECRET_KEY=os.environ.get('FEDEX_TRACK_SECRET_KEY'),
        
        # FedEx API URL
        FEDEX_API_URL=os.environ.get('FEDEX_API_URL', 'https://apis.fedex.com'),
        
        # ==================== TRACKING SETTINGS ====================
        TRACKING_UPDATE_INTERVAL=int(os.environ.get('TRACKING_UPDATE_INTERVAL', 4)),  # hours
        TRACKING_CACHE_DURATION=int(os.environ.get('TRACKING_CACHE_DURATION', 30)),   # minutes
        FEDEX_SYNC_ENABLED=os.environ.get('FEDEX_SYNC_ENABLED', 'false').lower() == 'true',
        FEDEX_SYNC_INTERVAL=int(os.environ.get('FEDEX_SYNC_INTERVAL', 30)),  # minutes
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
        from app.core.permissions import PermissionManager
        from app.core.module_access import get_user_available_modules
        from app.core.database import get_db_connection
        import os
        from app.core.instance_access import get_user_instances
    
        cu = current_user()
    
        context = {
            'user': cu,
            'is_sandbox': False,
            'accessible_instances': []
        }
        
        if cu:
            # Add accessible instances for L3/S1 users
            if cu.get('permission_level') in ['L3', 'S1']:
                context['accessible_instances'] = get_user_instances(cu)
            
            # Check if in sandbox instance
            try:
                from app.core.instance_context import get_current_instance
                current_instance_id = get_current_instance()
                context['is_sandbox'] = (current_instance_id == 4)
            except RuntimeError:
                # Not in any instance (Horizon mode)
                pass

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

        # For S1/L3 without explicit instance_id, assume Sandbox
        cu = current_user()
        if cu and not instance_id:
            perm_level = cu.get('permission_level', '')
            if perm_level in ['S1', 'L3']:
                instance_id = 4  # Default to Sandbox
                is_sandbox = True

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
                    elif inst:
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
    
    @app.context_processor
    def utility_processor():
        """Add utility functions to all templates"""
        def get_instance_id():
            """Get current instance ID from session or user"""
            from flask import session, g
            return session.get('active_instance_id') or (g.cu.instance_id if hasattr(g, 'cu') and g.cu else None)
        
        return dict(get_instance_id=get_instance_id)
    
    @app.before_request
    def set_request_instance_context():
        """Set instance context at start of every request"""
        from app.core.instance_context import set_current_instance, clear_current_instance
        from app.modules.auth.security import current_user
        from flask import request, session
        
        # Clear any previous context
        clear_current_instance()
        
        cu = current_user()
        if not cu:
            return
        
        # PRIORITY 1: Check URL query params for explicit instance_id
        instance_id = request.args.get('instance_id', type=int)
        
        # PRIORITY 2: Check session for persisted instance_id (for POST/redirects)
        if not instance_id and 'active_instance_id' in session:
            instance_id = session.get('active_instance_id')
            logger.debug(f"📦 Using session instance_id: {instance_id}")
        
        # PRIORITY 3: For S1/L3 users without explicit instance_id, default to Sandbox
        if not instance_id:
            perm_level = cu.get('permission_level', '')
            if perm_level in ['S1', 'L3']:
                # S1/L3 default to Sandbox (instance_id=4)
                instance_id = 4
                logger.debug(f"🧪 Defaulting S1/L3 to Sandbox: {instance_id}")
            else:
                # Other users use their assigned instance
                instance_id = cu.get('instance_id')
                logger.debug(f"👤 Using user's assigned instance: {instance_id}")
        
        # Set the context
        if instance_id:
            set_current_instance(instance_id)
            # PERSIST to session for subsequent requests
            session['active_instance_id'] = instance_id
            logger.debug(f"✅ Request instance context set: {instance_id}")
        else:
            logger.warning(f"⚠️ No instance context for user {cu.get('username')}")


    @app.after_request  
    def clear_request_instance_context(response):
        """Clear instance context after request"""
        from app.core.instance_context import clear_current_instance
        clear_current_instance()
        return response
    
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
        # CSS Blueprint (PRIORITY ZERO)
        from app.core.interface import interface_bp
        app.register_blueprint(interface_bp)

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
    
    # ==================== Initialize Background Scheduler ====================
    try:
        from app.scheduler import init_scheduler
        init_scheduler(app)
        logger.info("Background scheduler initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize scheduler: {e}")
        # Don't crash the app if scheduler fails

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
    
    # Setup signal handlers for graceful shutdown
    def shutdown_handler(signum, frame):
        logger.info("Application shutting down...")
        # Clean up resources
        try:
            from app.core.database import cleanup_all_pools
            cleanup_all_pools()
            
            # Shutdown scheduler
            from app.scheduler import shutdown_scheduler
            shutdown_scheduler()
            
            logger.info("Cleanup complete")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
        sys.exit(0)
    
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
