# app/core/cache.py
"""
Simple Redis-backed cache utilities.

All functions degrade silently to no-op / None when Redis is unavailable,
so callers never need to handle cache errors.

Usage:
    from app.core.cache import cache_get, cache_set, cache_delete, make_key

    key = make_key("addr", street, city, state, postal, country)
    result = cache_get(key)
    if result is None:
        result = expensive_call(...)
        cache_set(key, result, ttl=86400)
"""
import json
import hashlib
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Default TTLs (seconds)
TTL_ADDRESS   = 86_400   # 24 h  — address validation results
TTL_SHORT     =  3_600   #  1 h  — general lightweight results
TTL_SESSION   =    300   #  5 min — per-request dedup


def make_key(*parts) -> str:
    """Build a short, safe Redis key from arbitrary string parts."""
    raw = ":".join(str(p).lower().strip() for p in parts)
    return "gl:" + hashlib.md5(raw.encode()).hexdigest()


def cache_get(key: str) -> Optional[Any]:
    """Return the cached value for *key*, or None on miss / unavailability."""
    from app.core.redis_client import get_redis
    r = get_redis()
    if r is None:
        return None
    try:
        raw = r.get(key)
        return json.loads(raw) if raw is not None else None
    except Exception as exc:
        logger.debug("cache_get failed for key=%s: %s", key, exc)
        return None


def cache_set(key: str, value: Any, ttl: int = TTL_SHORT) -> None:
    """Write *value* to the cache with the given TTL (seconds)."""
    from app.core.redis_client import get_redis
    r = get_redis()
    if r is None:
        return
    try:
        r.setex(key, ttl, json.dumps(value, default=str))
    except Exception as exc:
        logger.debug("cache_set failed for key=%s: %s", key, exc)


def cache_delete(key: str) -> None:
    """Evict a key from the cache."""
    from app.core.redis_client import get_redis
    r = get_redis()
    if r is None:
        return
    try:
        r.delete(key)
    except Exception as exc:
        logger.debug("cache_delete failed for key=%s: %s", key, exc)


def cache_stats() -> dict:
    """Return basic Redis info for the health dashboard."""
    from app.core.redis_client import get_redis
    r = get_redis()
    if r is None:
        return {"connected": False}
    try:
        info = r.info("stats")
        return {
            "connected":       True,
            "hits":            info.get("keyspace_hits", 0),
            "misses":          info.get("keyspace_misses", 0),
            "commands_total":  info.get("total_commands_processed", 0),
        }
    except Exception as exc:
        return {"connected": False, "error": str(exc)}
