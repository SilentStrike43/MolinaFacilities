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


# ── Redis ─────────────────────────────────────────────────────────────────────

@register_check("core", "Redis: Connection")
def _redis_connection():
    from app.core.redis_client import get_redis
    r = get_redis()
    if r is None:
        raise RuntimeError("Redis client not initialised (REDIS_URL not set or connection failed)")
    r.ping()
    from app.core.cache import cache_stats
    stats = cache_stats()
    hits   = stats.get("hits", 0)
    misses = stats.get("misses", 0)
    total  = hits + misses
    ratio  = f"{hits/total*100:.0f}% hit rate" if total else "no traffic yet"
    return f"OK — {ratio} ({hits} hits / {misses} misses)"


# ── Fulfillment ───────────────────────────────────────────────────────────────

@register_check("fulfillment", "S3: Bucket Reachable")
def _fulfillment_s3():
    from app.core.s3 import s3_configured, _client, _BUCKET
    if not s3_configured():
        raise RuntimeError("S3_FULFILLMENT_BUCKET env var not set")
    _client().get_bucket_location(Bucket=_BUCKET)
    return f"s3://{_BUCKET} reachable"


# ── Carrier APIs ──────────────────────────────────────────────────────────────

@register_check("carriers", "USPS: OAuth Token")
def _usps_auth():
    import os, time, requests
    key    = os.environ.get("USPS_CONSUMER_KEY")
    secret = os.environ.get("USPS_CONSUMER_SECRET")
    if not key or not secret:
        raise RuntimeError("USPS_CONSUMER_KEY / USPS_CONSUMER_SECRET not configured")
    base = os.environ.get("USPS_API_URL", "https://apis.usps.com")
    t0   = time.monotonic()
    resp = requests.post(
        f"{base}/oauth2/v3/token",
        data={"grant_type": "client_credentials", "client_id": key, "client_secret": secret},
        timeout=10,
    )
    ms = int((time.monotonic() - t0) * 1000)
    resp.raise_for_status()
    token_type = resp.json().get("token_type", "bearer")
    return f"Token obtained ({token_type}) — {ms}ms"


@register_check("carriers", "USPS: Tracking Endpoint")
def _usps_tracking():
    import os, time, requests
    key    = os.environ.get("USPS_CONSUMER_KEY")
    secret = os.environ.get("USPS_CONSUMER_SECRET")
    if not key or not secret:
        raise RuntimeError("USPS credentials not configured")
    base = os.environ.get("USPS_API_URL", "https://apis.usps.com")
    tok = requests.post(
        f"{base}/oauth2/v3/token",
        data={"grant_type": "client_credentials", "client_id": key, "client_secret": secret},
        timeout=10,
    ).json().get("access_token")
    if not tok:
        raise RuntimeError("Could not obtain access token")
    # Any HTTP response from the tracking endpoint (200/400/404) proves it is reachable.
    # USPS returns 400 for unknown numbers rather than 404.
    t0   = time.monotonic()
    resp = requests.get(
        f"{base}/tracking/v3/tracking/9400111899223398369910",
        headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"},
        timeout=10,
    )
    ms = int((time.monotonic() - t0) * 1000)
    if resp.status_code in (200, 400, 404):
        return f"Endpoint reachable (HTTP {resp.status_code}) — {ms}ms"
    resp.raise_for_status()


@register_check("carriers", "UPS: OAuth Token")
def _ups_auth():
    import os, time, requests
    from requests.auth import HTTPBasicAuth
    client_id     = os.environ.get("UPS_CLIENT_ID")
    client_secret = os.environ.get("UPS_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("UPS_CLIENT_ID / UPS_CLIENT_SECRET not configured")
    t0   = time.monotonic()
    resp = requests.post(
        "https://onlinetools.ups.com/security/v1/oauth/token",
        auth=HTTPBasicAuth(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    ms = int((time.monotonic() - t0) * 1000)
    resp.raise_for_status()
    token_type = resp.json().get("token_type", "Bearer")
    return f"Token obtained ({token_type}) — {ms}ms"


@register_check("carriers", "UPS: Tracking Endpoint")
def _ups_tracking():
    import os, uuid, time, requests
    from requests.auth import HTTPBasicAuth
    client_id     = os.environ.get("UPS_CLIENT_ID")
    client_secret = os.environ.get("UPS_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("UPS credentials not configured")
    tok = requests.post(
        "https://onlinetools.ups.com/security/v1/oauth/token",
        auth=HTTPBasicAuth(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    ).json().get("access_token")
    if not tok:
        raise RuntimeError("Could not obtain access token")
    t0   = time.monotonic()
    resp = requests.get(
        "https://onlinetools.ups.com/api/track/v1/details/1Z8E757E0398644523",
        headers={
            "Authorization": f"Bearer {tok}",
            "transId": str(uuid.uuid4()),
            "transactionSrc": "GridlineService",
        },
        params={"locale": "en_US", "returnSignature": "false"},
        timeout=10,
    )
    ms = int((time.monotonic() - t0) * 1000)
    if resp.status_code in (200, 404):
        return f"Endpoint reachable (HTTP {resp.status_code}) — {ms}ms"
    resp.raise_for_status()


@register_check("carriers", "FedEx: OAuth Token")
def _fedex_auth():
    import os, time, requests
    api_key    = os.environ.get("FEDEX_TRACK_API_KEY")
    secret_key = os.environ.get("FEDEX_TRACK_SECRET_KEY")
    if not api_key or not secret_key:
        raise RuntimeError("FEDEX_TRACK_API_KEY / FEDEX_TRACK_SECRET_KEY not configured")
    base = os.environ.get("FEDEX_API_URL", "https://apis.fedex.com")
    t0   = time.monotonic()
    resp = requests.post(
        f"{base}/oauth/token",
        data={"grant_type": "client_credentials", "client_id": api_key, "client_secret": secret_key},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    ms = int((time.monotonic() - t0) * 1000)
    resp.raise_for_status()
    token_type = resp.json().get("token_type", "bearer")
    return f"Token obtained ({token_type}) — {ms}ms"


@register_check("carriers", "FedEx: Tracking Endpoint")
def _fedex_tracking():
    import os, time, requests
    api_key    = os.environ.get("FEDEX_TRACK_API_KEY")
    secret_key = os.environ.get("FEDEX_TRACK_SECRET_KEY")
    if not api_key or not secret_key:
        raise RuntimeError("FedEx credentials not configured")
    base = os.environ.get("FEDEX_API_URL", "https://apis.fedex.com")
    tok = requests.post(
        f"{base}/oauth/token",
        data={"grant_type": "client_credentials", "client_id": api_key, "client_secret": secret_key},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    ).json().get("access_token")
    if not tok:
        raise RuntimeError("Could not obtain access token")
    t0   = time.monotonic()
    resp = requests.post(
        f"{base}/track/v1/trackingnumbers",
        json={"includeDetailedScans": False, "trackingInfo": [{"trackingNumberInfo": {"trackingNumber": "123456789012"}}]},
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json", "X-locale": "en_US"},
        timeout=10,
    )
    ms = int((time.monotonic() - t0) * 1000)
    if resp.status_code in (200, 400, 404):
        return f"Endpoint reachable (HTTP {resp.status_code}) — {ms}ms"
    resp.raise_for_status()


@register_check("carriers", "OpenStreetMap: Nominatim")
def _osm_nominatim():
    import time, requests
    t0   = time.monotonic()
    resp = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": "New York, NY, USA", "format": "json", "limit": "1"},
        headers={"User-Agent": "GridlineService/1.0 (health-check)"},
        timeout=10,
    )
    ms = int((time.monotonic() - t0) * 1000)
    resp.raise_for_status()
    results = resp.json()
    if not results:
        raise RuntimeError("Nominatim returned empty results")
    top = results[0]
    return f"Reachable — '{top.get('display_name','?')[:40]}…' in {ms}ms"


@register_check("carriers", "OpenStreetMap: Reverse Geocode")
def _osm_reverse():
    import time, requests
    # Times Square, NYC
    t0   = time.monotonic()
    resp = requests.get(
        "https://nominatim.openstreetmap.org/reverse",
        params={"lat": "40.7580", "lon": "-73.9855", "format": "json"},
        headers={"User-Agent": "GridlineService/1.0 (health-check)"},
        timeout=10,
    )
    ms = int((time.monotonic() - t0) * 1000)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    addr = data.get("address", {})
    city = addr.get("city") or addr.get("town") or addr.get("county", "?")
    return f"Reachable — resolved to {city} in {ms}ms"
