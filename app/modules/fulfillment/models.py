# app/modules/fulfillment/models.py
import os, sqlite3
from app.common.storage import DATA_DIR

FUL_DB = os.path.join(DATA_DIR, "fulfillment.sqlite")

def _conn():
    con = sqlite3.connect(FUL_DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON;")
    return con

def ensure_fulfillment_schema():
    con = _conn()
    con.execute("""
      CREATE TABLE IF NOT EXISTS fulfillment_requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_id TEXT,
        requester TEXT,
        date_submitted TEXT DEFAULT (date('now')),
        status TEXT DEFAULT 'new',
        staff TEXT,
        completed_utc TEXT,
        ts_utc TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
      )
    """)
    con.commit(); con.close()
