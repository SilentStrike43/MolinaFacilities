# app/core/blueprints.py
"""
Blueprint registration.
Extracted from app.py to keep the factory lean.
"""
import logging

logger = logging.getLogger(__name__)


def register_blueprints(app):
    # ── Redis + rate limiter (must be before any blueprint that imports limiter) ──
    from app.core.redis_client import init_redis
    from app.core.rate_limit import init_limiter
    init_redis(app)
    init_limiter(app)
    """Register all application blueprints."""
    try:
        # CSS / static assets (highest priority)
        from app.core.interface import interface_bp
        app.register_blueprint(interface_bp)

        # Home module (must be first among page blueprints)
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

        # Send / Shipping module
        from app.modules.send import bp as send_bp
        app.register_blueprint(send_bp)

        # Fulfillment module
        from app.modules.fulfillment.views import bp as fulfillment_bp
        app.register_blueprint(fulfillment_bp)

        # Inventory (Flow) module
        from app.modules.inventory import bp as inventory_bp
        app.register_blueprint(inventory_bp)

        # Settings module
        from app.modules.settings import bp as settings_bp
        app.register_blueprint(settings_bp)

        # Horizon — Global Admin (L3/S1 only)
        from app.modules.horizon import bp as horizon_bp
        app.register_blueprint(horizon_bp, url_prefix='/horizon')

        # Horizon extras
        from app.modules.horizon.filters import register_filters
        register_filters(app)

        from app.modules.horizon.middleware import inject_permission_context
        app.context_processor(inject_permission_context)

        logger.info("All blueprints registered successfully")
    except Exception as e:
        logger.critical(f"Failed to register blueprints: {e}", exc_info=True)
        raise
