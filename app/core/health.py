# app/core/health.py
"""
System Health Check Registry

Each module registers one or more checks here.  The scheduler runs
run_all_checks() every hour and persists results to `health_check_results`
in the core DB so Horizon can display live status.

Usage (in any module):
    from app.core.health import register_check

    @register_check("send", "DB: Send Connection")
    def _():
        from app.core.database import get_db_connection
        with get_db_connection("send") as conn:
            conn.cursor().execute("SELECT 1")
        return "OK"
"""

import logging
import datetime
from typing import Callable

logger = logging.getLogger(__name__)

# ── Registry ────────────────────────────────────────────────────────────────
# List of (module, name, fn) tuples in registration order.
_CHECKS: list[tuple[str, str, Callable]] = []


def register_check(module: str, name: str):
    """
    Decorator to register a health check function.

    The function must:
      - Take no arguments
      - Return a short status string (e.g. "OK", "3 rows", "reachable")
      - Raise an exception on failure — the message becomes the error detail
    """
    def decorator(fn: Callable) -> Callable:
        _CHECKS.append((module, name, fn))
        return fn
    return decorator


# ── Schema ──────────────────────────────────────────────────────────────────
def ensure_health_schema():
    """Create the health_check_results table if it doesn't exist."""
    from app.core.database import get_db_connection
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS health_check_results (
                id          SERIAL PRIMARY KEY,
                module      VARCHAR(50)  NOT NULL,
                check_name  VARCHAR(100) NOT NULL,
                status      VARCHAR(10)  NOT NULL,   -- 'pass' | 'fail'
                detail      TEXT,
                duration_ms INTEGER,
                checked_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_health_module_time
                ON health_check_results(module, checked_at DESC)
        """)
        cursor.close()
    logger.info("Health check schema ready")


# ── Runner ──────────────────────────────────────────────────────────────────
def run_all_checks(app=None) -> list[dict]:
    """
    Execute every registered check, persist results, and return them.

    Args:
        app:  Flask app instance (for app context when called from scheduler).

    Returns:
        List of result dicts with keys:
            module, check_name, status ('pass'|'fail'), detail, duration_ms, checked_at
    """
    import time
    from app.core.database import get_db_connection

    ctx = app.app_context() if app else _null_context()
    results = []

    with ctx:
        for module, name, fn in _CHECKS:
            t0 = time.monotonic()
            try:
                detail = str(fn() or "OK")
                status = "pass"
            except Exception as exc:
                detail = str(exc)
                status = "fail"
                logger.warning(f"Health check FAILED [{module}] {name}: {exc}")

            duration_ms = int((time.monotonic() - t0) * 1000)
            checked_at = datetime.datetime.utcnow()

            result = {
                "module":      module,
                "check_name":  name,
                "status":      status,
                "detail":      detail,
                "duration_ms": duration_ms,
                "checked_at":  checked_at,
            }
            results.append(result)

            try:
                with get_db_connection("core") as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT INTO health_check_results
                            (module, check_name, status, detail, duration_ms, checked_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (module, name, status, detail, duration_ms, checked_at),
                    )
                    cursor.close()
            except Exception as db_exc:
                logger.error(f"Failed to persist health result for {name}: {db_exc}")

    return results


def get_latest_results() -> list[dict]:
    """
    Return the most recent result per check (for Horizon display).
    Returns results grouped by module, ordered by module then check_name.
    """
    from app.core.database import get_db_connection
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT ON (module, check_name)
                module, check_name, status, detail, duration_ms, checked_at
            FROM health_check_results
            ORDER BY module, check_name, checked_at DESC
        """)
        rows = cursor.fetchall()
        cursor.close()
    return [dict(r) for r in rows]


def get_check_history(module: str, check_name: str, limit: int = 24) -> list[dict]:
    """Return the last N results for a specific check (for sparkline/trend)."""
    from app.core.database import get_db_connection
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT status, detail, duration_ms, checked_at
            FROM health_check_results
            WHERE module = %s AND check_name = %s
            ORDER BY checked_at DESC
            LIMIT %s
        """, (module, check_name, limit))
        rows = cursor.fetchall()
        cursor.close()
    return [dict(r) for r in rows]


# ── Helpers ─────────────────────────────────────────────────────────────────
class _null_context:
    def __enter__(self): return self
    def __exit__(self, *_): pass
