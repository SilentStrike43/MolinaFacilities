# app/modules/inventory/models.py
import os, sqlite3

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, "inventory.sqlite")

def _conn():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def ensure_schema():
    con = _conn()
    con.executescript("""
    -- inventory label/report rows
    CREATE TABLE IF NOT EXISTS inventory_reports(
      id INTEGER PRIMARY KEY,
      ts_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
      checkin_date TEXT,
      inventory_id INTEGER,
      item_type TEXT,
      manufacturer TEXT,
      product_name TEXT,
      submitter_name TEXT,
      notes TEXT,
      part_number TEXT,
      serial_number TEXT,
      count INTEGER,
      location TEXT,
      template TEXT,
      printer TEXT,
      status TEXT,
      payload TEXT
    );

    -- simple counters
    CREATE TABLE IF NOT EXISTS counters(
      name TEXT PRIMARY KEY,
      val  INTEGER NOT NULL
    );

    -- asset master & movements (ledger)
    CREATE TABLE IF NOT EXISTS assets(
      id INTEGER PRIMARY KEY,
      sku TEXT, product TEXT, uom TEXT, location TEXT,
      qty_on_hand INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS asset_movements(
      id INTEGER PRIMARY KEY,
      ts_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
      asset_id INTEGER NOT NULL,
      action TEXT NOT NULL,   -- CHECKIN | CHECKOUT | ADJUST
      qty INTEGER NOT NULL,
      username TEXT,
      note TEXT
    );
    """)
    con.commit(); con.close()

def inventory_db():
    ensure_schema()
    return _conn()

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

def next_inventory_id() -> int:
    ensure_schema()
    return _bump("inventory_seq")

def peek_next_inventory_id() -> int:
    ensure_schema()
    return _peek("inventory_seq")

# ---- asset helpers (used by ledger.py) --------------------------------------
def list_assets():
    con = _conn()
    rows = con.execute("SELECT * FROM assets ORDER BY product, sku").fetchall()
    con.close()
    return rows

def get_asset(asset_id: int):
    con = _conn()
    row = con.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
    con.close()
    return row

def record_movement(asset_id: int, action: str, qty: int, username: str = "", note: str = ""):
    con = _conn()
    con.execute(
        "INSERT INTO asset_movements(asset_id, action, qty, username, note) VALUES (?,?,?,?,?)",
        (asset_id, action, int(qty), username, note)
    )
    # adjust on hand
    if action.upper() == "CHECKIN":
        con.execute("UPDATE assets SET qty_on_hand = qty_on_hand + ? WHERE id=?", (int(qty), asset_id))
    elif action.upper() == "CHECKOUT":
        con.execute("UPDATE assets SET qty_on_hand = MAX(qty_on_hand - ?, 0) WHERE id=?", (int(qty), asset_id))
    con.commit()
    con.close()

def list_movements(asset_id: int):
    con = _conn()
    rows = con.execute(
        "SELECT * FROM asset_movements WHERE asset_id=? ORDER BY ts_utc DESC",
        (asset_id,)
    ).fetchall()
    con.close()
    return rows
