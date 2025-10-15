# app/common/storage.py
from __future__ import annotations
import os, sqlite3
from typing import Optional

# ---------- Legacy-friendly constants (some modules import these) ----------
# Keep empty by default so IDs stay numeric; change if you want visible prefixes.
PACKAGE_PREFIX = ""
CHECKIN_PREFIX = ""

# ---------- Paths ----------
APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(APP_ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)

USERS_DB     = os.path.join(DATA_DIR, "users.sqlite")
MAIL_DB      = os.path.join(DATA_DIR, "mail.sqlite")         # print_jobs
INVENTORY_DB = os.path.join(DATA_DIR, "inventory.sqlite")    # inventory_reports, counters
FULFILL_DB   = os.path.join(DATA_DIR, "fulfillment.sqlite")  # fulfillment_requests
INSIGHTS_DB  = os.path.join(DATA_DIR, "insights.sqlite")     # some modules import insights_db
CACHE_DB     = os.path.join(DATA_DIR, "cache.sqlite")        # harmless scratch

def _connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.execute("PRAGMA busy_timeout=3000;")
    return con

# ---------- DB getters (legacy-friendly) ----------
def users_db() -> sqlite3.Connection:      return _connect(USERS_DB)
def jobs_db() -> sqlite3.Connection:       return _connect(MAIL_DB)
def inventory_db() -> sqlite3.Connection:  return _connect(INVENTORY_DB)
def fulfillment_db() -> sqlite3.Connection:return _connect(FULFILL_DB)
def insights_db() -> sqlite3.Connection:   return _connect(INSIGHTS_DB)
def cache_db() -> sqlite3.Connection:      return _connect(CACHE_DB)

def get_db(name: Optional[str] = None) -> sqlite3.Connection:
    n = (name or "").lower()
    if n in ("users","user"):             return users_db()
    if n in ("mail","jobs","print"):      return jobs_db()
    if n in ("inventory","inv"):          return inventory_db()
    if n in ("fulfillment","fulfill"):    return fulfillment_db()
    if n in ("insights",):                return insights_db()
    if n in ("cache",):                   return cache_db()
    return users_db()

# ---------- Schemas ----------
def ensure_mail_schema():
    con = jobs_db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS print_jobs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts_utc         TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
          tracking       TEXT,
          submitter_name TEXT,
          job_type       TEXT,
          status         TEXT,
          notes          TEXT
        )
    """)
    con.commit(); con.close()

# Legacy aliases expected by old modules
def ensure_jobs_schema():  return ensure_mail_schema()
def ensure_print_schema(): return ensure_mail_schema()

def ensure_inventory_schema():
    con = inventory_db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS inventory_reports(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts_utc         TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
          inventory_id   TEXT,
          product_name   TEXT,
          manufacturer   TEXT,
          item_type      TEXT,
          submitter_name TEXT,
          pii            INTEGER DEFAULT 0
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS counters(
          k TEXT PRIMARY KEY,
          v INTEGER NOT NULL
        )
    """)
    if not con.execute("SELECT 1 FROM counters WHERE k='BASE_CHECKIN'").fetchone():
        con.execute("INSERT INTO counters(k,v) VALUES('BASE_CHECKIN', 10000000000)")
    if not con.execute("SELECT 1 FROM counters WHERE k='BASE_PACKAGE'").fetchone():
        con.execute("INSERT INTO counters(k,v) VALUES('BASE_PACKAGE', 10000000000)")
    con.commit(); con.close()

def ensure_fulfillment_schema():
    con = fulfillment_db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS fulfillment_requests(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          service_id     TEXT,
          requester      TEXT,
          date_submitted TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
          status         TEXT,
          staff_member   TEXT,
          completed_utc  TEXT
        )
    """)
    con.commit(); con.close()

def ensure_insights_schema():
    con = insights_db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS notes(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts_utc TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
          scope  TEXT,
          body   TEXT
        )
    """)
    con.commit(); con.close()

def ensure_cache_schema():
    con = cache_db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS kv(
          k TEXT PRIMARY KEY,
          v TEXT,
          ts_utc TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
    """)
    con.commit(); con.close()

# ---------- ID helpers (backward compatible) ----------
def _counter_next(key: str) -> int:
    con = inventory_db()
    row = con.execute("SELECT v FROM counters WHERE k=?", (key,)).fetchone()
    v = (row["v"] if row else 0) + 1
    if row:
        con.execute("UPDATE counters SET v=? WHERE k=?", (v, key))
    else:
        con.execute("INSERT INTO counters(k,v) VALUES(?,?)", (key, v))
    con.commit(); con.close()
    return v

def _counter_peek(key: str) -> int:
    con = inventory_db()
    row = con.execute("SELECT v FROM counters WHERE k=?", (key,)).fetchone()
    v = row["v"] if row else 0
    con.close()
    return v

# Accept *args, **kwargs so old calls that pass a "type" param don't crash.
def next_checkin_id(*_args, **_kwargs) -> int:   return _counter_next("BASE_CHECKIN")
def next_package_id(*_args, **_kwargs) -> int:   return _counter_next("BASE_PACKAGE")
def peek_next_checkin_id(*_args, **_kwargs) -> int: return _counter_peek("BASE_CHECKIN") + 1
def peek_next_package_id(*_args, **_kwargs) -> int: return _counter_peek("BASE_PACKAGE") + 1

# ---------- One-shot initializer ----------
def init_all_dbs():
    ensure_mail_schema()
    ensure_inventory_schema()
    ensure_fulfillment_schema()
    ensure_insights_schema()
    ensure_cache_schema()

__all__ = [
    # constants
    "PACKAGE_PREFIX","CHECKIN_PREFIX",
    # paths
    "DATA_DIR","USERS_DB","MAIL_DB","INVENTORY_DB","FULFILL_DB","INSIGHTS_DB","CACHE_DB",
    # connections
    "get_db","users_db","jobs_db","inventory_db","fulfillment_db","insights_db","cache_db",
    # schema helpers
    "ensure_mail_schema","ensure_jobs_schema","ensure_print_schema",
    "ensure_inventory_schema","ensure_fulfillment_schema","ensure_insights_schema","ensure_cache_schema",
    # ids
    "next_checkin_id","next_package_id","peek_next_checkin_id","peek_next_package_id",
    # boot
    "init_all_dbs",
]