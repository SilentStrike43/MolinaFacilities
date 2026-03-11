# app/core/health_checks.py
"""
Module health check registrations.

Imported once during startup (app/core/startup.py).
Each check is a lightweight probe — DB query, table row count, or
connectivity test.  Failures raise exceptions; the registry catches them.
"""

from app.core.health import register_check


# ── App Factory / Core ───────────────────────────────────────────────────────

@register_check("core", "DB: Core Connection")
def _core_db():
    from app.core.database import get_db_connection
    with get_db_connection("core") as conn:
        conn.cursor().execute("SELECT 1")
    return "OK"


@register_check("core", "Table: users")
def _core_users():
    from app.core.database import get_db_connection
    with get_db_connection("core") as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM users WHERE deleted_at IS NULL")
        n = cur.fetchone()["n"]
        cur.close()
    return f"{n} active user(s)"


@register_check("core", "Table: audit_logs")
def _core_audit():
    from app.core.database import get_db_connection
    with get_db_connection("core") as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM audit_logs WHERE ts_utc > NOW() - INTERVAL '24 hours'")
        n = cur.fetchone()["n"]
        cur.close()
    return f"{n} event(s) in last 24h"


@register_check("core", "Table: health_check_results")
def _core_health_table():
    from app.core.database import get_db_connection
    with get_db_connection("core") as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM health_check_results WHERE checked_at > NOW() - INTERVAL '2 hours'")
        n = cur.fetchone()["n"]
        cur.close()
    return f"{n} result(s) stored in last 2h"


# ── Auth ─────────────────────────────────────────────────────────────────────

@register_check("auth", "Session Config: SECRET_KEY set")
def _auth_secret_key():
    import os
    key = os.environ.get("SECRET_KEY", "")
    if not key or key == "dev-only-insecure-key-NOT-for-production":
        raise RuntimeError("SECRET_KEY is not set or is using the dev fallback")
    return f"Set ({len(key)} chars)"


@register_check("auth", "Account Lockout Columns")
def _auth_lockout_columns():
    from app.core.database import get_db_connection
    with get_db_connection("core") as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'users'
              AND column_name IN ('failed_login_attempts', 'locked_until')
        """)
        cols = {r["column_name"] for r in cur.fetchall()}
        cur.close()
    missing = {"failed_login_attempts", "locked_until"} - cols
    if missing:
        raise RuntimeError(f"Missing columns: {missing}")
    return "Both columns present"


# ── Send ─────────────────────────────────────────────────────────────────────

@register_check("send", "DB: Send Connection")
def _send_db():
    from app.core.database import get_db_connection
    with get_db_connection("send") as conn:
        conn.cursor().execute("SELECT 1")
    return "OK"


@register_check("send", "Table: package_manifest")
def _send_manifest():
    from app.core.database import get_db_connection
    with get_db_connection("send") as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM package_manifest WHERE deleted_at IS NULL")
        n = cur.fetchone()["n"]
        cur.close()
    return f"{n} active package(s)"


# ── Flow (Inventory) ─────────────────────────────────────────────────────────

@register_check("flow", "DB: Inventory Connection")
def _inventory_db():
    from app.core.database import get_db_connection
    with get_db_connection("inventory") as conn:
        conn.cursor().execute("SELECT 1")
    return "OK"


@register_check("flow", "Table: inventory_transactions")
def _inventory_transactions():
    from app.core.database import get_db_connection
    with get_db_connection("inventory") as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM inventory_transactions")
        n = cur.fetchone()["n"]
        cur.close()
    return f"{n} transaction(s)"


# ── Fulfillment ───────────────────────────────────────────────────────────────

@register_check("fulfillment", "DB: Fulfillment Connection")
def _fulfillment_db():
    from app.core.database import get_db_connection
    with get_db_connection("fulfillment") as conn:
        conn.cursor().execute("SELECT 1")
    return "OK"


@register_check("fulfillment", "Table: fulfillment_requests")
def _fulfillment_requests():
    from app.core.database import get_db_connection
    with get_db_connection("fulfillment") as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM fulfillment_requests WHERE is_archived = FALSE")
        n = cur.fetchone()["n"]
        cur.close()
    return f"{n} active request(s)"


@register_check("fulfillment", "S3: Bucket Reachable")
def _fulfillment_s3():
    from app.core.s3 import s3_configured, _client, _BUCKET
    if not s3_configured():
        raise RuntimeError("S3_FULFILLMENT_BUCKET env var not set")
    _client().head_bucket(Bucket=_BUCKET)
    return f"s3://{_BUCKET} reachable"
