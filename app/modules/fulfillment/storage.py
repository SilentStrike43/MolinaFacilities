# app/modules/fulfillment/storage.py
import os, sqlite3, json, datetime
from typing import Optional, List, Dict, Any, Tuple

from ...common.storage import DATA_DIR

FULFILL_DB = os.path.join(DATA_DIR, "fulfillment.sqlite")
UPLOAD_DIR = os.path.join(DATA_DIR, "fulfillment_files")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(FULFILL_DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.execute("PRAGMA busy_timeout=3000;")
    return con

def ensure_schema():
    con = _conn()
    # main requests table
    con.execute("""
    CREATE TABLE IF NOT EXISTS fulfillment_requests(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts_utc TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
      date_submitted TEXT DEFAULT (date('now')),
      date_due TEXT,
      requester_id INTEGER,
      requester_name TEXT,
      description TEXT,
      total_pages INTEGER,
      status TEXT DEFAULT 'Received',
      is_archived INTEGER DEFAULT 0,
      completed_at TEXT,
      assigned_staff_id INTEGER,
      assigned_staff_name TEXT,
      options_json TEXT,      -- stores dropdown selections (paper type/size/etc.)
      notes TEXT              -- "Additional Details"
    )""")
    # uploaded files table
    con.execute("""
    CREATE TABLE IF NOT EXISTS fulfillment_files(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      request_id INTEGER NOT NULL,
      ts_utc TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
      orig_name TEXT,
      stored_name TEXT,
      ext TEXT,
      bytes INTEGER,
      ok INTEGER DEFAULT 1,
      FOREIGN KEY(request_id) REFERENCES fulfillment_requests(id) ON DELETE CASCADE
    )""")
    # legacy add-columns safety
    for ddl in (
        "ALTER TABLE fulfillment_requests ADD COLUMN assigned_staff_id INTEGER",
        "ALTER TABLE fulfillment_requests ADD COLUMN assigned_staff_name TEXT",
        "ALTER TABLE fulfillment_requests ADD COLUMN options_json TEXT",
        "ALTER TABLE fulfillment_requests ADD COLUMN notes TEXT",
        "ALTER TABLE fulfillment_requests ADD COLUMN total_pages INTEGER",
        "ALTER TABLE fulfillment_requests ADD COLUMN date_due TEXT",
    ):
        try: con.execute(ddl)
        except Exception: pass

    con.execute("CREATE INDEX IF NOT EXISTS idx_f_requests_status ON fulfillment_requests(status)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_f_requests_arch ON fulfillment_requests(is_archived)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_f_files_req ON fulfillment_files(request_id)")
    con.commit()
    con.close()

# ---------- CRUD helpers ----------
def create_request(payload: Dict[str, Any]) -> int:
    """
    payload keys:
      requester_id, requester_name, description, date_due, total_pages,
      status, assigned_staff_id, assigned_staff_name, options_json(str), notes
    """
    ensure_schema()
    con = _conn()
    cur = con.execute("""
        INSERT INTO fulfillment_requests(
          requester_id, requester_name, description, date_due, total_pages,
          status, assigned_staff_id, assigned_staff_name, options_json, notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        payload.get("requester_id"),
        payload.get("requester_name"),
        payload.get("description"),
        payload.get("date_due"),
        payload.get("total_pages"),
        payload.get("status","Received"),
        payload.get("assigned_staff_id"),
        payload.get("assigned_staff_name"),
        payload.get("options_json"),
        payload.get("notes"),
    ))
    rid = cur.lastrowid
    con.commit(); con.close()
    return rid

def list_queue() -> List[sqlite3.Row]:
    ensure_schema()
    con = _conn()
    rows = con.execute("""
      SELECT * FROM fulfillment_requests
      WHERE is_archived=0
      ORDER BY ts_utc DESC
    """).fetchall()
    con.close()
    return rows

def list_archive() -> List[sqlite3.Row]:
    ensure_schema()
    con = _conn()
    rows = con.execute("""
      SELECT * FROM fulfillment_requests
      WHERE is_archived=1
      ORDER BY ts_utc DESC
    """).fetchall()
    con.close()
    return rows

def get_request(rid: int) -> Optional[sqlite3.Row]:
    ensure_schema()
    con = _conn()
    row = con.execute("SELECT * FROM fulfillment_requests WHERE id=?", (rid,)).fetchone()
    con.close()
    return row

def update_status(rid: int, status: str, *, archive: bool = False, staff_id=None, staff_name=None):
    ensure_schema()
    con = _conn()
    completed_at = None
    is_archived = 1 if archive else 0
    if status == "Completed":
        completed_at = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    con.execute("""
      UPDATE fulfillment_requests
      SET status=?, is_archived=?, completed_at=COALESCE(?, completed_at),
          assigned_staff_id=COALESCE(?, assigned_staff_id),
          assigned_staff_name=COALESCE(?, assigned_staff_name)
      WHERE id=?
    """, (status, is_archived, completed_at, staff_id, staff_name, rid))
    con.commit(); con.close()

def set_archive(rid: int, archive: int):
    ensure_schema()
    con = _conn()
    con.execute("UPDATE fulfillment_requests SET is_archived=? WHERE id=?", (1 if archive else 0, rid))
    con.commit(); con.close()

def list_files(rid: int) -> List[sqlite3.Row]:
    ensure_schema()
    con = _conn()
    rows = con.execute("SELECT * FROM fulfillment_files WHERE request_id=? ORDER BY id", (rid,)).fetchall()
    con.close()
    return rows

def add_file(rid: int, orig_name: str, stored_name: str, ext: str, size: int, ok: int = 1) -> int:
    ensure_schema()
    con = _conn()
    cur = con.execute("""
      INSERT INTO fulfillment_files(request_id, orig_name, stored_name, ext, bytes, ok)
      VALUES (?,?,?,?,?,?)
    """, (rid, orig_name, stored_name, ext, size, int(bool(ok))))
    fid = cur.lastrowid
    con.commit(); con.close()
    return fid