# app/app.py
"""
Application factory — intentionally lean.
All heavy lifting lives in app/core/*.py so this file imports fast
and Azure App Service can answer its startup health-check probe
before the schemas and scheduler have finished initialising.
"""
import os
import logging
from datetime import datetime
from flask import Flask, redirect, url_for

from app.core.logging_config import setup_flask_logging
from app.core.errors import register_error_handlers
from app.core.config import configure_app
from app.core.context_processors import register_context_processors
from app.core.middleware import register_middleware
from app.core.template_filters import register_template_filters
from app.core.blueprints import register_blueprints
from app.core.startup import register_startup
from app.modules.auth.security import login_required

logger = logging.getLogger(__name__)


def create_app():
    app = Flask(__name__)

    # ── Proxy fix — must be first so request.scheme reflects HTTPS ─────────────
    # Trusts 1 proxy hop (nginx). Required for correct redirects behind
    # Cloudflare → nginx → gunicorn and for SESSION_COOKIE_SECURE to work.
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # ── Configuration ──────────────────────────────────────────────────────────
    configure_app(app)

    # ── Logging ────────────────────────────────────────────────────────────────
    setup_flask_logging(app)
    logger.info("Application starting up…")

    # ── Error handlers ─────────────────────────────────────────────────────────
    register_error_handlers(app)

    # ── Jinja2 context processors ──────────────────────────────────────────────
    register_context_processors(app)

    # ── Request lifecycle hooks ────────────────────────────────────────────────
    register_middleware(app)

    # ── Jinja2 template filters ────────────────────────────────────────────────
    register_template_filters(app)

    # ── Blueprints ─────────────────────────────────────────────────────────────
    register_blueprints(app)

    # ── Background scheduler ───────────────────────────────────────────────────
    try:
        from app.scheduler import init_scheduler
        init_scheduler(app)
        logger.info("Background scheduler initialised")
    except Exception as exc:
        logger.warning(f"Scheduler not available: {exc}")

    # ── Schema initialisation (daemon thread — non-blocking) ───────────────────
    register_startup(app)

    # ── Core routes ────────────────────────────────────────────────────────────
    @app.route("/")
    @login_required
    def index():
        return redirect(url_for('home.index'))

    @app.route("/health")
    def health():
        return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

    logger.info("Application factory complete")
    return app


# ── Direct execution (local dev) ───────────────────────────────────────────────
if __name__ == '__main__':
    application = create_app()
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    debug = os.environ.get('FLASK_ENV') == 'development'
    logger.info(f"Starting dev server on {host}:{port}")
    application.run(host=host, port=port, debug=debug, use_reloader=debug)

