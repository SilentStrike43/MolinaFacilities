import os, sqlite3
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, "fulfillment.sqlite")

def _conn():
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row; return con

def ensure_schema():
    con = _conn()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS service_queue(
      id INTEGER PRIMARY KEY,
      ts_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
      requester TEXT, item TEXT, qty INTEGER, notes TEXT, status TEXT
    );
    CREATE TABLE IF NOT EXISTS service_archive(
      id INTEGER PRIMARY KEY,
      ts_utc TEXT NOT NULL,
      completed_utc TEXT NOT NULL,
      requester TEXT, item TEXT, qty INTEGER, notes TEXT, status TEXT
    );
    """)
    con.commit(); con.close()

def queue_db(): ensure_schema(); return _conn()