# app/core/rate_limit.py
"""
Flask-Limiter setup — Redis-backed when available, memory fallback otherwise.

Import the `limiter` singleton in routes:
    from app.core.rate_limit import limiter

    @bp.route("/api/heavy")
    @login_required
    @limiter.limit("10 per minute")
    def heavy_endpoint(): ...

init_limiter(app) is called from blueprints.py after configure_app().
"""
import logging
from flask import session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

logger = logging.getLogger(__name__)


def _rate_key() -> str:
    """
    Key function: use authenticated user ID when available so that all
    workers behind the same office NAT don't share a single rate bucket.
    Falls back to remote IP for unauthenticated requests.
    """
    user_id = session.get("user_id")
    if user_id:
        return f"user:{user_id}"
    return get_remote_address()


# Module-level singleton — decorated routes reference this object at import
# time.  init_app() wires it to the actual storage backend later.
limiter = Limiter(
    key_func=_rate_key,
    # Conservative global defaults; individual routes override as needed.
    default_limits=["300 per minute", "3000 per hour"],
    # If Redis goes down mid-flight, fall back to in-process memory so the
    # app keeps running (limits are per-worker in that case, but it's safe).
    in_memory_fallback_enabled=True,
    swallow_errors=True,
)


def init_limiter(app):
    """
    Wire Flask-Limiter to the app.  Must be called after configure_app()
    so REDIS_URL is already in app.config.
    """
    redis_url = app.config.get("REDIS_URL", "")

    if redis_url:
        app.config["RATELIMIT_STORAGE_URI"] = redis_url
        if redis_url.startswith("rediss://"):
            # ElastiCache — skip hostname cert check
            app.config["RATELIMIT_STORAGE_OPTIONS"] = {"ssl_cert_reqs": None}
        logger.info("Rate limiter: Redis backend (%s)", redis_url.split("@")[-1])
    else:
        app.config["RATELIMIT_STORAGE_URI"] = "memory://"
        logger.warning(
            "Rate limiter: in-memory storage (limits not shared across workers). "
            "Set REDIS_URL to enable shared limiting."
        )

    # Expose X-RateLimit-* headers so clients can see their remaining budget
    app.config.setdefault("RATELIMIT_HEADERS_ENABLED", True)

    limiter.init_app(app)
    logger.info("Rate limiter initialised")
