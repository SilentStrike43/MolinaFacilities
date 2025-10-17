import os, sqlite3
# app/modules/inventory/storage.py
# Thin compatibility layer so older imports like "from .storage import inventory_db"
# keep working after the module-local refactor.
from .models import (
    _conn, ensure_schema, inventory_db,
    next_inventory_id, peek_next_inventory_id,
    list_assets, get_asset, record_movement, list_movements,
)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, "inventory.sqlite")
INSIGHTS_DB = DB  # keep single file; separate file if you wish later

def _conn(path=DB):
    con = sqlite3.connect(path); con.row_factory = sqlite3.Row; return con

def ensure_schema():
    con = _conn()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS inventory_reports(
      id INTEGER PRIMARY KEY,
      ts_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
      checkin_date TEXT,
      inventory_id INTEGER,
      item_type TEXT, manufacturer TEXT, product_name TEXT,
      submitter_name TEXT, pii TEXT, notes TEXT,
      part_number TEXT, serial_number TEXT, count INTEGER, location TEXT,
      template TEXT, printer TEXT, status TEXT, payload TEXT
    );
    """)
    con.commit(); con.close()

def insights_db(): ensure_schema(); return _conn(INSIGHTS_DB)
def inventory_db(): ensure_schema(); return _conn(DB)