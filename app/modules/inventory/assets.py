import os, sqlite3
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, "assets.sqlite")

def _conn():
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row; return con

def ensure_schema():
    con = _conn()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS assets(
      id INTEGER PRIMARY KEY, sku TEXT, product TEXT, uom TEXT,
      location TEXT, qty_on_hand INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS asset_ledger(
      id INTEGER PRIMARY KEY,
      ts_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
      asset_id INTEGER NOT NULL,
      action TEXT NOT NULL, -- CHECKIN / CHECKOUT
      qty INTEGER NOT NULL, username TEXT, note TEXT
    );
    """)
    con.commit(); con.close()

def db(): ensure_schema(); return _conn()
