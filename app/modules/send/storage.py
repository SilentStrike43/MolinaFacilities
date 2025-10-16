# app/modules/send/storage.py
import os, sqlite3
from typing import Optional, Tuple, Dict

# Keep data under the main app data dir (no cross-module bleed)
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "send.sqlite")

PACKAGE_PREFIX: Dict[str, str] = {
    "Box": "BOX",
    "Envelope": "ENV",
    "Packs": "PACK",
    "Tubes": "TUBE",
    "Certified": "CERT",
    "Sensitive": "SENS",
    "Critical": "CRIT",
}

PACKAGE_TYPES = list(PACKAGE_PREFIX.keys())

def _db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=3000")
    return con

def ensure_schema() -> None:
    con = _db()
    # counters & config
    con.execute("""
      CREATE TABLE IF NOT EXISTS send_config(
        key TEXT PRIMARY KEY,
        value TEXT
      )
    """)
    con.execute("""
      CREATE TABLE IF NOT EXISTS package_counters(
        pkg_type TEXT PRIMARY KEY,
        next_num INTEGER NOT NULL
      )
    """)
    # default checkin base (10000000000)
    if not con.execute("SELECT 1 FROM send_config WHERE key='checkin_next'").fetchone():
        con.execute("INSERT INTO send_config(key,value) VALUES('checkin_next','10000000000')")

    # seed every package type with 1 if missing
    for t in PACKAGE_TYPES:
        if not con.execute("SELECT 1 FROM package_counters WHERE pkg_type=?", (t,)).fetchone():
            con.execute("INSERT INTO package_counters(pkg_type,next_num) VALUES(?,?)", (t, 1))

    # print jobs (Send)
    con.execute("""
      CREATE TABLE IF NOT EXISTS print_jobs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_utc   TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        module   TEXT,          -- 'send'
        job_type TEXT,          -- 'manifest' etc
        payload  TEXT,          -- original json payload

        -- Core fields for label
        checkin_date   TEXT,
        checkin_id     TEXT,
        package_type   TEXT,
        package_id     TEXT,
        recipient_name TEXT,
        tracking_number TEXT,
        status         TEXT,
        printer        TEXT,
        template       TEXT,

        -- Reporting-friendly fields (so this module is self-contained)
        submitter_name TEXT,
        item_type      TEXT,    -- e.g. 'Package'
        carrier        TEXT,
        to_name        TEXT
      )
    """)

    # tracking cache (carrier guess or status blobs)
    con.execute("""
      CREATE TABLE IF NOT EXISTS tracking_cache(
        tracking TEXT PRIMARY KEY,
        carrier  TEXT,
        payload  TEXT,
        updated  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
      )
    """)

    con.commit()
    con.close()

# ---------- Check-in IDs ----------
def peek_next_checkin_id() -> int:
    con = _db()
    row = con.execute("SELECT value FROM send_config WHERE key='checkin_next'").fetchone()
    con.close()
    return int(row["value"]) if row else 10000000000

def next_checkin_id() -> int:
    con = _db()
    cur = con.execute("SELECT value FROM send_config WHERE key='checkin_next'").fetchone()
    cur_val = int(cur["value"]) if cur else 10000000000
    nxt = cur_val + 1
    con.execute("REPLACE INTO send_config(key, value) VALUES('checkin_next', ?)", (str(nxt),))
    con.commit(); con.close()
    return cur_val

def set_checkin_base(new_base: int) -> None:
    con = _db()
    con.execute("REPLACE INTO send_config(key, value) VALUES('checkin_next', ?)", (str(new_base),))
    con.commit(); con.close()

# ---------- Package IDs ----------
def _prefix(pkg_type: str) -> str:
    return PACKAGE_PREFIX.get(pkg_type, "PACK")

def peek_next_package_id(pkg_type: str) -> str:
    con = _db()
    row = con.execute("SELECT next_num FROM package_counters WHERE pkg_type=?", (pkg_type,)).fetchone()
    con.close()
    n = int(row["next_num"]) if row else 1
    return f"{_prefix(pkg_type)}{n:08d}"

def next_package_id(pkg_type: str) -> str:
    con = _db()
    row = con.execute("SELECT next_num FROM package_counters WHERE pkg_type=?", (pkg_type,)).fetchone()
    n = int(row["next_num"]) if row else 1
    new_n = n + 1
    con.execute("REPLACE INTO package_counters(pkg_type,next_num) VALUES(?,?)", (pkg_type, new_n))
    con.commit(); con.close()
    return f"{_prefix(pkg_type)}{n:08d}"

# ---------- Tracking cache ----------
def cache_get(tracking: str):
    con = _db()
    row = con.execute("SELECT carrier, payload, updated FROM tracking_cache WHERE tracking=?", (tracking,)).fetchone()
    con.close()
    return row

def cache_set(tracking: str, carrier: str, payload_json: str):
    con = _db()
    con.execute("REPLACE INTO tracking_cache(tracking, carrier, payload, updated) VALUES (?,?,?, strftime('%Y-%m-%dT%H%M%SZ','now'))",
                (tracking, carrier, payload_json))
    con.commit(); con.close()

# ---------- Logging ----------
def insert_print_job(row: dict) -> None:
    con = _db()
    con.execute("""
      INSERT INTO print_jobs(
        module, job_type, payload,
        checkin_date, checkin_id, package_type, package_id, recipient_name,
        tracking_number, status, printer, template,
        submitter_name, item_type, carrier, to_name
      )
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        row.get("module"), row.get("job_type"), row.get("payload"),
        row.get("checkin_date"), row.get("checkin_id"), row.get("package_type"),
        row.get("package_id"), row.get("recipient_name"),
        row.get("tracking_number"), row.get("status"), row.get("printer"), row.get("template"),
        row.get("submitter_name"), row.get("item_type"), row.get("carrier"), row.get("to_name")
    ))
    con.commit(); con.close()

def query_print_jobs(filters: dict, limit: int = 2000):
    con = _db()
    sql = "SELECT * FROM print_jobs WHERE 1=1"
    params = []
    q = (filters.get("q") or "").strip()
    date_from = (filters.get("date_from") or "").strip()
    date_to   = (filters.get("date_to") or "").strip()
    carrier   = (filters.get("carrier") or "").strip()

    if q:
        like = f"%{q}%"
        sql += " AND (to_name LIKE ? OR submitter_name LIKE ? OR tracking_number LIKE ?)"
        params += [like, like, like]
    if date_from:
        sql += " AND date(ts_utc) >= date(?)"; params.append(date_from)
    if date_to:
        sql += " AND date(ts_utc) <= date(?)"; params.append(date_to)
    if carrier:
        sql += " AND carrier = ?"; params.append(carrier)
    sql += " ORDER BY ts_utc DESC LIMIT ?"; params.append(limit)

    rows = con.execute(sql, params).fetchall()
    con.close()
    return rows