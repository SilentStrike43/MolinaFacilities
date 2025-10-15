# app/common/assets.py
from typing import Optional
from .storage import get_conn

def list_assets():
    con = get_conn("assets")
    rows = con.execute("SELECT * FROM assets ORDER BY COALESCE(sku, product)").fetchall()
    con.close()
    return rows

def get_asset(asset_id:int):
    con = get_conn("assets")
    row = con.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
    con.close(); return row

def adjust_qty(asset_id:int, delta:int, *, user_id:int=None, username:str=None, note:str=""):
    """
    Positive delta = check-in, negative delta = check-out
    Writes ledger row and updates qty_on_hand atomically.
    """
    con = get_conn("assets")
    cur = con.cursor()
    cur.execute("SELECT qty_on_hand FROM assets WHERE id=?", (asset_id,))
    row = cur.fetchone()
    if not row:
        con.close(); return False
    new_qty = (row["qty_on_hand"] or 0) + int(delta)
    if new_qty < 0: new_qty = 0

    cur.execute("UPDATE assets SET qty_on_hand=?, updated_at=(strftime('%Y-%m-%dT%H:%M:%SZ','now')) WHERE id=?",
                (new_qty, asset_id))
    cur.execute("""
        INSERT INTO asset_ledger(action, asset_id, qty, user_id, username, note)
        VALUES(?,?,?,?,?,?)
    """, ("CHECKIN" if delta>0 else "CHECKOUT", asset_id, abs(int(delta)), user_id, username, note))
    con.commit(); con.close()
    return True

def ledger_for_asset(asset_id:int, limit:int=500):
    con = get_conn("assets")
    rows = con.execute("SELECT * FROM asset_ledger WHERE asset_id=? ORDER BY ts_utc DESC LIMIT ?",
                       (asset_id, limit)).fetchall()
    con.close(); return rows