# app/core/startup.py
"""
Background schema initialisation.
Runs all ensure_schema() calls in a daemon thread so the WSGI server
can answer Azure's startup health-check probe immediately.
"""
import threading
import logging

logger = logging.getLogger(__name__)


def _run_schema_init():
    """Execute every ensure_schema call. Runs in a background thread."""
    try:
        logger.info("Background schema init starting")

        # 1. Base table creation (CREATE TABLE IF NOT EXISTS)
        from app.modules.users.models import (
            ensure_user_schema,
            ensure_inquiry_schema,
            ensure_announcement_schema,
            ensure_reset_token_schema,
            ensure_support_ticket_schema,
        )
        ensure_user_schema()
        ensure_inquiry_schema()
        ensure_announcement_schema()
        ensure_reset_token_schema()
        ensure_support_ticket_schema()

        from app.modules.send.storage import ensure_schema as ensure_send_schema
        from app.modules.fulfillment.storage import ensure_schema as ensure_fulfillment_schema
        from app.modules.inventory.storage import ensure_schema as ensure_inventory_schema
        from app.modules.inventory.assets import ensure_schema as ensure_assets_schema

        ensure_send_schema()
        ensure_fulfillment_schema()
        ensure_inventory_schema()
        ensure_assets_schema()

        # 2. Column migrations (versioned, run-once)
        from app.core.migrations import run_migrations
        run_migrations()

        # 3. Health check infrastructure + check registration
        from app.core.health import ensure_health_schema
        ensure_health_schema()

        import app.core.health_checks  # noqa: F401  — registers all @register_check decorators

        logger.info("Background schema init complete")
    except Exception as exc:
        logger.error(f"Background schema init failed: {exc}", exc_info=True)


def register_startup(app):
    """
    Schedule schema initialisation to run once, in a daemon thread,
    after the WSGI server has started (first request or explicit call).
    """
    _thread = threading.Thread(target=_run_schema_init, daemon=True, name="schema-init")
    _thread.start()
    logger.info("Schema init thread launched")
