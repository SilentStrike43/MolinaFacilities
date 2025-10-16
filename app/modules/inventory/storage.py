# app/modules/inventory/storage.py
import os, sqlite3
from typing import Optional, Dict, Any, List

# Data folder (local to the app, but separate DB for module isolation)
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "inventory.sqlite")

def _db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=3000")
    return con

def ensure_schema() -> None:
    con = _db()

    # simple config (for sequences, flags, etc.)
    con.execute("""
      CREATE TABLE IF NOT EXISTS inv_config(
        key TEXT PRIMARY KEY,
        value TEXT
      )
    """)

    # inventory id sequence (text to keep it simple/portable)
    if not con.execute("SELECT 1 FROM inv_config WHERE key='inventory_next'").fetchone():
        con.execute("INSERT INTO inv_config(key,value) VALUES('inventory_next','100000')")

    # main asset table
    con.execute("""
      CREATE TABLE IF NOT EXISTS assets(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        status      TEXT DEFAULT 'active',            -- active / archived

        -- business fields
        inventory_id   TEXT UNIQUE,                  -- human ID
        item_type      TEXT,
        manufacturer   TEXT,
        product_name   TEXT,
        part_number    TEXT,
        serial_number  TEXT,
        location       TEXT,
        count          INTEGER DEFAULT 0,
        pii            TEXT,                         -- yes/no or details
        notes          TEXT
      )
    """)

    # transactional ledger for check-in/out/adjust
    con.execute("""
      CREATE TABLE IF NOT EXISTS asset_ledger(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_utc    TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        asset_id  INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
        action    TEXT,                 -- check_in / check_out / adjust
        qty       INTEGER NOT NULL,
        actor     TEXT,
        notes     TEXT
      )
    """)

    # insights table — module-local, used by /inventory/insights + CSV
    con.execute("""
      CREATE TABLE IF NOT EXISTS inventory_reports(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_utc          TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        inventory_id    TEXT,
        product_name    TEXT,
        manufacturer    TEXT,
        item_type       TEXT,
        submitter_name  TEXT,
        pii             TEXT,
        notes           TEXT
      )
    """)

    con.execute("CREATE INDEX IF NOT EXISTS ix_assets_inventory_id ON assets(inventory_id)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_assets_status ON assets(status)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_ledger_asset ON asset_ledger(asset_id)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_reports_ts ON inventory_reports(ts_utc)")

    con.commit()
    con.close()

# ------- sequences -------
def peek_next_inventory_id() -> str:
    con = _db()
    row = con.execute("SELECT value FROM inv_config WHERE key='inventory_next'").fetchone()
    con.close()
    n = int(row["value"]) if row else 100000
    return f"INV{n:06d}"

def next_inventory_id() -> str:
    con = _db()
    row = con.execute("SELECT value FROM inv_config WHERE key='inventory_next'").fetchone()
    n = int(row["value"]) if row else 100000
    nxt = n + 1
    con.execute("REPLACE INTO inv_config(key,value) VALUES('inventory_next',?)", (str(nxt),))
    con.commit(); con.close()
    return f"INV{n:06d}"

# ------- assets -------
def list_assets(q: str = "", status: str = "active"):
    con = _db()
    sql = "SELECT * FROM assets WHERE 1=1"
    params: List[Any] = []
    if status:
        sql += " AND status = ?"; params.append(status)
    if q:
        like = f"%{q}%"
        sql += " AND (inventory_id LIKE ? OR product_name LIKE ? OR manufacturer LIKE ? OR serial_number LIKE ?)"
        params += [like, like, like, like]
    sql += " ORDER BY updated_at DESC, id DESC LIMIT 2000"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return rows

def get_asset(aid: int):
    con = _db()
    row = con.execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone()
    con.close()
    return row

def create_asset(data: Dict[str, Any]) -> int:
    con = _db()
    inv_id = data.get("inventory_id") or next_inventory_id()
    con.execute("""
      INSERT INTO assets(inventory_id,item_type,manufacturer,product_name,part_number,serial_number,
                         location,count,pii,notes)
      VALUES(?,?,?,?,?,?,?,?,?,?)
    """, (
      inv_id, data.get("item_type"), data.get("manufacturer"), data.get("product_name"),
      data.get("part_number"), data.get("serial_number"), data.get("location"),
      int(data.get("count") or 0), data.get("pii"), data.get("notes")
    ))
    new_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    con.commit(); con.close()
    return new_id

def update_asset(aid: int, data: Dict[str, Any]):
    con = _db()
    con.execute("""
      UPDATE assets SET
        item_type=?, manufacturer=?, product_name=?, part_number=?, serial_number=?,
        location=?, count=?, pii=?, notes=?, status=?,
        updated_at=(strftime('%Y-%m-%dT%H:%M:%SZ','now'))
      WHERE id=?
    """, (
      data.get("item_type"), data.get("manufacturer"), data.get("product_name"), data.get("part_number"),
      data.get("serial_number"), data.get("location"), int(data.get("count") or 0),
      data.get("pii"), data.get("notes"), data.get("status","active"),
      aid
    ))
    con.commit(); con.close()

# ------- ledger -------
def add_ledger(asset_id: int, action: str, qty: int, actor: str, notes: str = ""):
    con = _db()
    con.execute("""
      INSERT INTO asset_ledger(asset_id, action, qty, actor, notes)
      VALUES(?,?,?,?,?)
    """, (asset_id, action, int(qty), actor, notes))
    # update asset count
    delta = int(qty) if action == "check_in" else (-int(qty) if action == "check_out" else int(qty))
    con.execute("UPDATE assets SET count = MAX(0, count + ?), updated_at=(strftime('%Y-%m-%dT%H:%M:%SZ','now')) WHERE id=?",
                (delta, asset_id))
    con.commit(); con.close()

def query_ledger(filters: Dict[str, str], limit: int = 2000):
    con = _db()
    sql = """
      SELECT l.*, a.inventory_id, a.product_name, a.manufacturer
      FROM asset_ledger l
      JOIN assets a ON a.id = l.asset_id
      WHERE 1=1
    """
    params: List[Any] = []
    if filters.get("q"):
        like = f"%{filters['q']}%"
        sql += " AND (a.inventory_id LIKE ? OR a.product_name LIKE ? OR a.manufacturer LIKE ? OR l.actor LIKE ?)"
        params += [like, like, like, like]
    if filters.get("date_from"):
        sql += " AND date(l.ts_utc) >= date(?)"; params.append(filters["date_from"])
    if filters.get("date_to"):
        sql += " AND date(l.ts_utc) <= date(?)"; params.append(filters["date_to"])
    sql += " ORDER BY l.ts_utc DESC LIMIT ?"; params.append(limit)
    rows = con.execute(sql, params).fetchall()
    con.close()
    return rows

# ------- insights -------
def insert_insight(row: Dict[str, Any]) -> None:
    con = _db()
    con.execute("""
      INSERT INTO inventory_reports(inventory_id, product_name, manufacturer, item_type, submitter_name, pii, notes)
      VALUES(?,?,?,?,?,?,?)
    """, (
      row.get("inventory_id"), row.get("product_name"), row.get("manufacturer"),
      row.get("item_type"), row.get("submitter_name"), row.get("pii"), row.get("notes")
    ))
    con.commit(); con.close()

def query_insights(f: Dict[str, str], limit: int = 2000):
    con = _db()
    sql = "SELECT * FROM inventory_reports WHERE 1=1"
    params: List[Any] = []
    def like(field: str, val: str):
        nonlocal sql, params
        if val:
            sql += f" AND {field} LIKE ?"; params.append(f"%{val}%")

    like("submitter_name", f.get("submitter_name",""))
    like("product_name",   f.get("product_name",""))
    like("manufacturer",   f.get("manufacturer",""))
    like("item_type",      f.get("item_type",""))

    if f.get("inventory_id"):
        sql += " AND inventory_id = ?"; params.append(f["inventory_id"])
    if f.get("pii"):
        sql += " AND pii = ?"; params.append(f["pii"])
    if f.get("q"):
        like("(notes || ' ' || product_name || ' ' || manufacturer)", f["q"])
    if f.get("date_from"):
        sql += " AND date(ts_utc) >= date(?)"; params.append(f["date_from"])
    if f.get("date_to"):
        sql += " AND date(ts_utc) <= date(?)"; params.append(f["date_to"])

    sql += " ORDER BY ts_utc DESC LIMIT ?"; params.append(limit)
    rows = con.execute(sql, params).fetchall()
    con.close()
    return rows