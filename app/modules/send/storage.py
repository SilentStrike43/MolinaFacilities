import os, sqlite3, json
from typing import Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, "send.sqlite")

PACKAGE_PREFIX = {
    "Box": "PACK", "Envelope": "ENV",
    "Packs": "PACK", "Tubes": "TUBE",
    "Certified": "CERT", "Sensitive": "SENS", "Critical": "CRIT",
}

def _conn():
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row; return con

def ensure_schema():
    con = _conn()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS counters(
      name TEXT PRIMARY KEY, value INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS print_jobs(
      id INTEGER PRIMARY KEY,
      ts_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
      submitter_name TEXT,
      item_type TEXT, carrier TEXT, tracking TEXT, to_name TEXT,
      module TEXT, job_type TEXT, payload TEXT,
      checkin_date TEXT, checkin_id TEXT, package_type TEXT, package_id TEXT,
      recipient_name TEXT, tracking_number TEXT, status TEXT, printer TEXT, template TEXT
    );
    CREATE TABLE IF NOT EXISTS cache(
      tracking TEXT PRIMARY KEY, carrier TEXT, payload TEXT,
      updated TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    );
    """)
    con.commit(); con.close()

def _bump(name: str) -> int:
    con = _conn()
    r = con.execute("SELECT value FROM counters WHERE name=?", (name,)).fetchone()
    val = (r["value"] if r else 0) + 1
    con.execute("REPLACE INTO counters(name,value) VALUES(?,?)", (name, val))
    con.commit(); con.close()
    return val

def _peek(name: str) -> int:
    con = _conn()
    r = con.execute("SELECT value FROM counters WHERE name=?", (name,)).fetchone()
    val = (r["value"] if r else 0) + 1
    con.close()
    return val

def next_checkin_id() -> int:      return _bump("checkin_id")
def peek_next_checkin_id() -> int:  return _peek("checkin_id")

def next_package_id(pkg_type: str) -> str:
    prefix = PACKAGE_PREFIX.get(pkg_type, "PACK")
    num = _bump(f"pkg_{prefix}")
    return f"{prefix}{num:08d}"

def peek_next_package_id(pkg_type: str) -> str:
    prefix = PACKAGE_PREFIX.get(pkg_type, "PACK")
    num = _peek(f"pkg_{prefix}")
    return f"{prefix}{num:08d}"

# lightweight cache helpers for tracking page
def cache_get(tracking: str):
    con = _conn(); r = con.execute("SELECT carrier,payload,updated FROM cache WHERE tracking=?", (tracking,)).fetchone(); con.close()
    return r

def cache_set(tracking: str, carrier: str, payload_json: str):
    con = _conn()
    con.execute("REPLACE INTO cache(tracking, carrier, payload, updated) VALUES (?,?,?, strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
                (tracking, carrier, payload_json))
    con.commit(); con.close()

def jobs_db():  # kept only for your existing code paths
    ensure_schema(); return _conn()