# app/common/storage.py
from __future__ import annotations
import os, sqlite3
from typing import Optional

# --- paths --------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(__file__))  # app/
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

INSIGHTS_PATH = os.path.join(DATA_DIR, "insights.db")
CACHE_PATH    = os.path.join(DATA_DIR, "cache.db")

def db_conn(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con

# Public DB accessors expected by modules
def insights_db() -> sqlite3.Connection:   return db_conn(INSIGHTS_PATH)
def jobs_db() -> sqlite3.Connection:       return insights_db()
def inventory_db() -> sqlite3.Connection:  return insights_db()     # compat alias
def cache_db() -> sqlite3.Connection:      return db_conn(CACHE_PATH)

# ---- legacy-name COMPAT ALIASES (keep modules happy without edits) ----------
# Some older code still imports these symbols. Keep them pointing at the new impls.
def core_db() -> sqlite3.Connection:       return insights_db()
get_db   = insights_db
get_conn = db_conn

def init_all_dbs() -> None:
    """Boot-time initializer kept for compat with old app boot code."""
    ensure_jobs_schema()
    ensure_inventory_schema()
    ensure_cache_schema()

# --- schemas ------------------------------------------------------------------
def ensure_jobs_schema() -> None:
    con = insights_db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS print_jobs (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_utc          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        module          TEXT,
        job_type        TEXT,
        payload         TEXT,

        -- legacy mail fields (some reports read these)
        checkin_date    TEXT,
        checkin_id      TEXT,
        package_type    TEXT,
        package_id      TEXT,
        recipient_name  TEXT,
        tracking_number TEXT,
        status          TEXT,
        printer         TEXT,
        template        TEXT,

        -- fields used by older insights pages
        submitter_name  TEXT,
        item_type       TEXT,
        carrier         TEXT,
        tracking        TEXT,
        to_name         TEXT
    );
    """)
    con.commit(); con.close()

def ensure_inventory_schema() -> None:
    con = insights_db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS inventory_reports (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_utc          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        checkin_date    TEXT,
        inventory_id    INTEGER,
        item_type       TEXT,
        manufacturer    TEXT,
        product_name    TEXT,
        submitter_name  TEXT,
        notes           TEXT,
        part_number     TEXT,
        serial_number   TEXT,
        count           INTEGER,
        location        TEXT,
        template        TEXT,
        printer         TEXT,
        status          TEXT,
        payload         TEXT
    );
    """)
    con.commit(); con.close()

def ensure_cache_schema() -> None:
    con = cache_db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS cache (
        tracking TEXT PRIMARY KEY,
        carrier  TEXT,
        payload  TEXT,
        updated  TEXT
    );
    """)
    con.commit(); con.close()

# For very old callers that referenced this name:
ensure_mail_schema = ensure_jobs_schema

# --- simple counters for IDs --------------------------------------------------
def _ensure_counters_schema() -> None:
    con = insights_db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS counters (
            key TEXT PRIMARY KEY,
            val INTEGER NOT NULL
        )
    """)
    con.commit(); con.close()

def _get_counter(key: str, seed: int) -> int:
    _ensure_counters_schema()
    con = insights_db()
    row = con.execute("SELECT val FROM counters WHERE key=?", (key,)).fetchone()
    if not row:
        con.execute("INSERT OR REPLACE INTO counters(key,val) VALUES(?,?)", (key, seed))
        con.commit()
        val = seed
    else:
        val = int(row["val"])
    con.close()
    return val

def _set_counter(key: str, val: int) -> None:
    _ensure_counters_schema()
    con = insights_db()
    con.execute("INSERT OR REPLACE INTO counters(key,val) VALUES(?,?)", (key, val))
    con.commit(); con.close()

# Public helpers used by Send/Inventory pages
def peek_next_checkin_id() -> int:
    return _get_counter("checkin_id", seed=100000) + 1

def next_checkin_id() -> int:
    cur = _get_counter("checkin_id", seed=100000) + 1
    _set_counter("checkin_id", cur)
    return cur

PACKAGE_PREFIX = {
    "Box":        "PACK",
    "Envelope":   "ENV",
    "Packs":      "PKS",
    "Tubes":      "TUBE",
    "Certified":  "CERT",
    "Sensitive":  "SENS",
    "Critical":   "CRIT",
}

def _pkg_counter_key(pkg_type: str) -> str:
    return f"pkg_{(pkg_type or 'Box').lower()}"

def _format_pkg(prefix: str, n: int) -> str:
    return f"{prefix}{n:08d}"

def peek_next_package_id(pkg_type: str) -> str:
    pref = PACKAGE_PREFIX.get(pkg_type, "PACK")
    n = _get_counter(_pkg_counter_key(pkg_type), seed=0) + 1
    return _format_pkg(pref, n)

def next_package_id(pkg_type: str) -> str:
    pref = PACKAGE_PREFIX.get(pkg_type, "PACK")
    key  = _pkg_counter_key(pkg_type)
    n = _get_counter(key, seed=0) + 1
    _set_counter(key, n)
    return _format_pkg(pref, n)