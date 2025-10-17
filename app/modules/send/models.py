# app/modules/send/models.py
import os, sqlite3
from typing import Dict

# module-local data dir → app/modules/send/data/send.sqlite
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, "send.sqlite")

PACKAGE_PREFIX: Dict[str, str] = {
    "Box": "PACK",
    "Envelope": "ENV",
    "Packs": "PACK",
    "Tubes": "TUBE",
    "Certified": "CERT",
    "Sensitive": "SENS",
    "Critical": "CRIT",
}

def _conn():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def ensure_schema():
    con = _conn()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS print_jobs(
      id INTEGER PRIMARY KEY,
      ts_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
      module TEXT, job_type TEXT, payload TEXT,
      checkin_date TEXT, checkin_id TEXT,
      package_type TEXT, package_id TEXT,
      recipient_name TEXT, tracking_number TEXT,
      status TEXT, printer TEXT, template TEXT
    );

    CREATE TABLE IF NOT EXISTS counters(
      name TEXT PRIMARY KEY,
      val  INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS cache(
      tracking TEXT PRIMARY KEY,
      carrier  TEXT,
      payload  TEXT,
      updated  TEXT
    );
    """)
    con.commit()
    con.close()

# compatibility helpers (drop-in for “jobs_db()”)
def jobs_db():
    ensure_schema()
    return _conn()

# --- id generators -----------------------------------------------------------
def _bump(name: str) -> int:
    con = _conn()
    row = con.execute("SELECT val FROM counters WHERE name=?", (name,)).fetchone()
    if row:
        val = row["val"] + 1
        con.execute("UPDATE counters SET val=? WHERE name=?", (val, name))
    else:
        val = 1
        con.execute("INSERT INTO counters(name, val) VALUES(?,?)", (name, val))
    con.commit(); con.close()
    return val

def _peek(name: str) -> int:
    con = _conn()
    row = con.execute("SELECT val FROM counters WHERE name=?", (name,)).fetchone()
    con.close()
    return (row["val"] + 1) if row else 1

def next_checkin_id() -> int:
    ensure_schema()
    return _bump("checkin_seq")

def peek_next_checkin_id() -> int:
    ensure_schema()
    return _peek("checkin_seq")

def _pkg_key(t: str) -> str:
    return f"pkg_{(t or 'Box').strip()}"

def next_package_id(pkg_type: str) -> str:
    ensure_schema()
    n = _bump(_pkg_key(pkg_type))
    return f"{PACKAGE_PREFIX.get(pkg_type, 'PACK')}{n:08d}"

def peek_next_package_id(pkg_type: str) -> str:
    ensure_schema()
    n = _peek(_pkg_key(pkg_type))
    return f"{PACKAGE_PREFIX.get(pkg_type, 'PACK')}{n:08d}"