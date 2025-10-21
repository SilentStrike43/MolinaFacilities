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
from app.core.auth import (
    ensure_user_schema, ensure_first_sysadmin, current_user
)
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
        SESSION_COOKIE_SECURE=False,  # Set to True in production with HTTPS
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=3600 * 24 * 7,  # 7 days
        MAX_CONTENT_LENGTH=50 * 1024 * 1024,  # 50MB max upload
        UPLOAD_FOLDER=os.path.join(os.path.dirname(__file__), 'data', 'uploads'),
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
        """Home page - dynamic dashboard with real data"""
        if not current_user():
            return redirect(url_for("auth.login"))
        
        user = current_user()
        
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
        if user.get('can_asset') or user.get('is_admin') or user.get('is_sysadmin'):
            try:
                from app.modules.inventory.assets import db as assets_db
                con = assets_db()
                
                # Total assets
                result = con.execute("SELECT COUNT(*) as count FROM assets WHERE status='active'").fetchone()
                dashboard_data['total_assets'] = result['count'] if result else 0
                
                # Asset trend (compare to last month)
                result = con.execute("""
                    SELECT COUNT(*) as count FROM asset_ledger 
                    WHERE ts_utc >= date('now', '-30 days')
                """).fetchone()
                last_month = result['count'] if result else 0
                
                result = con.execute("""
                    SELECT COUNT(*) as count FROM asset_ledger 
                    WHERE ts_utc >= date('now', '-60 days') AND ts_utc < date('now', '-30 days')
                """).fetchone()
                prev_month = result['count'] if result else 1
                
                if prev_month > 0:
                    dashboard_data['asset_trend'] = int(((last_month - prev_month) / prev_month) * 100)
                
                # Recent asset activities
                recent_assets = con.execute("""
                    SELECT al.ts_utc, al.action, a.product, al.username, al.qty
                    FROM asset_ledger al
                    JOIN assets a ON al.asset_id = a.id
                    ORDER BY al.ts_utc DESC
                    LIMIT 5
                """).fetchall()
                
                for row in recent_assets:
                    dashboard_data['recent_activities'].append({
                        'icon': 'box-seam',
                        'icon_bg': 'rgba(102, 126, 234, 0.1)',
                        'icon_color': '#667eea',
                        'title': f"{row['action'].title()} - {row['product']}",
                        'description': f"{row['qty']} unit(s) by {row['username']}",
                        'time': row['ts_utc'],
                        'type': 'asset'
                    })
                
                con.close()
            except Exception as e:
                app.logger.error(f"Failed to load asset data: {e}")
        
        # Get fulfillment data if user has permission
        if user.get('can_fulfillment_staff') or user.get('can_fulfillment_customer') or user.get('is_admin') or user.get('is_sysadmin'):
            try:
                from app.modules.fulfillment.storage import queue_db
                con = queue_db()
                
                # Pending requests
                if user.get('can_fulfillment_staff') or user.get('is_admin') or user.get('is_sysadmin'):
                    result = con.execute("""
                        SELECT COUNT(*) as count FROM fulfillment_requests 
                        WHERE is_archived=0 AND status NOT IN ('Completed', 'Cancelled')
                    """).fetchone()
                    dashboard_data['pending_requests'] = result['count'] if result else 0
                    
                    # My assigned tasks
                    tasks = con.execute("""
                        SELECT id, description, status, date_submitted
                        FROM fulfillment_requests
                        WHERE is_archived=0 
                        AND (assigned_staff_name=? OR status='Received')
                        ORDER BY date_submitted DESC
                        LIMIT 5
                    """, (user['username'],)).fetchall()
                    
                    for task in tasks:
                        dashboard_data['my_tasks'].append({
                            'id': task['id'],
                            'description': task['description'],
                            'status': task['status'],
                            'date': task['date_submitted']
                        })
                else:
                    # Customer view
                    result = con.execute("""
                        SELECT COUNT(*) as count FROM fulfillment_requests 
                        WHERE requester_name=? AND is_archived=0
                    """, (user['username'],)).fetchone()
                    dashboard_data['pending_requests'] = result['count'] if result else 0
                
                # Completed this month
                result = con.execute("""
                    SELECT COUNT(*) as count FROM fulfillment_requests
                    WHERE status='Completed' 
                    AND date(completed_at) >= date('now', 'start of month')
                """).fetchone()
                dashboard_data['completed_tasks'] = result['count'] if result else 0
                
                con.close()
            except Exception as e:
                app.logger.error(f"Failed to load fulfillment data: {e}")
        
        # Get shipping data if user has permission
        if user.get('can_send') or user.get('is_admin') or user.get('is_sysadmin'):
            try:
                from app.modules.send.storage import send_db
                con = send_db()
                
                # Shipments this month
                result = con.execute("""
                    SELECT COUNT(*) as count FROM send_log
                    WHERE date(ts_utc) >= date('now', 'start of month')
                """).fetchone()
                dashboard_data['shipments_this_month'] = result['count'] if result else 0
                
                con.close()
            except Exception as e:
                app.logger.error(f"Failed to load shipping data: {e}")
        
        # Sort activities by time
        dashboard_data['recent_activities'].sort(
            key=lambda x: x.get('time', ''), 
            reverse=True
        )
        dashboard_data['recent_activities'] = dashboard_data['recent_activities'][:10]
        
        return render_template(
            "dashboard.html",
            title="Dashboard",
            data=dashboard_data
        )
    
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
    logger.info("Starting development server on 127.0.0.1:5000")
    application.run(
        host='127.0.0.1',
        port=5000,
        debug=True,
        use_reloader=True
    )