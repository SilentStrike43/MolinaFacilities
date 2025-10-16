# app/modules/inventory/models.py
import os, sqlite3
from app.common.storage import DATA_DIR

INV_DB = os.path.join(DATA_DIR, "inventory.sqlite")

def _conn():
    con = sqlite3.connect(INV_DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON;")
    return con

def ensure_inventory_schema():
    con = _conn()
    con.execute("""
      CREATE TABLE IF NOT EXISTS assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inventory_id TEXT UNIQUE,
        product_name TEXT,
        manufacturer TEXT,
        item_type TEXT,
        pii INTEGER DEFAULT 0,
        created_utc TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
      )
    """)
    con.execute("""
      CREATE TABLE IF NOT EXISTS asset_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inventory_id TEXT NOT NULL,
        action TEXT CHECK(action IN ('checkin','checkout')) NOT NULL,
        qty INTEGER DEFAULT 1,
        actor TEXT,
        note TEXT,
        ts_utc TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
      )
    """)
    con.execute("""
      CREATE TABLE IF NOT EXISTS inventory_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_utc TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        inventory_id TEXT,
        submitter_name TEXT,
        product_name TEXT,
        manufacturer TEXT,
        item_type TEXT,
        pii INTEGER DEFAULT 0
      )
    """)
    con.commit(); con.close()