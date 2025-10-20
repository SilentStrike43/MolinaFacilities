# app/modules/inventory/assets.py - UPDATED SCHEMA
import os, sqlite3
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, "assets.sqlite")

def _conn():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def ensure_schema():
    con = _conn()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS assets(
      id INTEGER PRIMARY KEY,
      sku TEXT UNIQUE NOT NULL,
      product TEXT NOT NULL,
      manufacturer TEXT,
      part_number TEXT,
      serial_number TEXT,
      uom TEXT DEFAULT 'EA',
      location TEXT,
      qty_on_hand INTEGER NOT NULL DEFAULT 0,
      pii TEXT,
      notes TEXT,
      status TEXT DEFAULT 'active',
      created_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    );
    
    CREATE INDEX IF NOT EXISTS idx_assets_sku ON assets(sku);
    CREATE INDEX IF NOT EXISTS idx_assets_status ON assets(status);
    
    CREATE TABLE IF NOT EXISTS asset_ledger(
      id INTEGER PRIMARY KEY,
      ts_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
      asset_id INTEGER NOT NULL,
      action TEXT NOT NULL,
      qty INTEGER NOT NULL,
      username TEXT,
      note TEXT,
      FOREIGN KEY(asset_id) REFERENCES assets(id)
    );
    
    CREATE INDEX IF NOT EXISTS idx_ledger_asset ON asset_ledger(asset_id);
    """)
    con.commit()
    con.close()

def db():
    ensure_schema()
    return _conn()
