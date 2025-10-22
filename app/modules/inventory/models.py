# app/modules/inventory/models.py - FIXED
import os, sqlite3

# Point to the ASSETS database, not inventory
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, "assets.sqlite")  # ← CHANGED FROM inventory.sqlite

def _conn():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def ensure_schema():
    """Ensure asset tables exist (should already be created by assets.py)"""
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
    """)
    con.commit(); con.close()

def inventory_db():
    ensure_schema()
    return _conn()

# ---- asset helpers (used by ledger.py) --------------------------------------
def list_assets():
    """Get all assets from the assets database"""
    con = _conn()
    rows = con.execute("""
        SELECT * FROM assets 
        WHERE status != 'deleted'
        ORDER BY product, sku
    """).fetchall()
    con.close()
    return rows

def get_asset(asset_id: int):
    """Get a single asset by ID"""
    con = _conn()
    row = con.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
    con.close()
    return row

def record_movement(asset_id: int, action: str, qty: int, username: str, note: str = ""):
    """Record asset movement in ledger"""
    con = _conn()
    
    # Insert movement
    con.execute("""
        INSERT INTO asset_ledger(asset_id, action, qty, username, note)
        VALUES (?, ?, ?, ?, ?)
    """, (asset_id, action, qty, username, note))
    
    # Update asset quantity
    if action == "CHECKIN":
        con.execute("UPDATE assets SET qty_on_hand = qty_on_hand + ? WHERE id = ?", (qty, asset_id))
    elif action == "CHECKOUT":
        con.execute("UPDATE assets SET qty_on_hand = qty_on_hand - ? WHERE id = ?", (qty, asset_id))
    elif action == "ADJUST":
        con.execute("UPDATE assets SET qty_on_hand = ? WHERE id = ?", (qty, asset_id))
    
    con.commit()
    con.close()

def list_movements(asset_id: int = None):
    """Get ledger movements, optionally filtered by asset_id"""
    con = _conn()
    if asset_id:
        rows = con.execute("""
            SELECT * FROM asset_ledger 
            WHERE asset_id = ? 
            ORDER BY ts_utc DESC
        """, (asset_id,)).fetchall()
    else:
        rows = con.execute("SELECT * FROM asset_ledger ORDER BY ts_utc DESC LIMIT 100").fetchall()
    con.close()
    return rows

# Backward compatibility
next_inventory_id = lambda: 1
peek_next_inventory_id = lambda: 1