# app/core/redis_client.py
"""
Redis client — ElastiCache Serverless (TLS).

Usage:
    from app.core.redis_client import init_redis, get_redis

    # In app factory:
    init_redis(app)

    # In request context:
    r = get_redis()   # returns redis.Redis or None (graceful degradation)
"""
import logging
from flask import current_app

logger = logging.getLogger(__name__)


def init_redis(app):
    """
    Connect to Redis and attach the client to app.extensions['redis'].
    Called once from the app factory.  On any failure the extension is set
    to None so the rest of the app degrades gracefully.
    """
    redis_url = app.config.get("REDIS_URL", "")

    if not redis_url:
        logger.info("REDIS_URL not set — Redis disabled (in-memory fallbacks active)")
        app.extensions["redis"] = None
        return

    try:
        import redis as _redis

        opts = {
            "socket_connect_timeout": 2,
            "socket_timeout": 2,
            "decode_responses": True,
            "health_check_interval": 30,
        }
        # ElastiCache Serverless requires TLS (rediss://)
        if redis_url.startswith("rediss://"):
            opts["ssl_cert_reqs"] = None   # AWS-managed cert — skip hostname verify

        client = _redis.from_url(redis_url, **opts)
        client.ping()
        app.extensions["redis"] = client
        logger.info("Redis connected: %s", redis_url.split("@")[-1])

    except Exception as exc:
        logger.warning("Redis unavailable — continuing without cache/shared rate-limit: %s", exc)
        app.extensions["redis"] = None


def get_redis():
    """
    Return the Redis client for the current app, or None if unavailable.
    Must be called inside a Flask application context.
    """
    return current_app.extensions.get("redis")
