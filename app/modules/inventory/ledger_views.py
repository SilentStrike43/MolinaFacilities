# app/modules/inventory/ledger_views.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from app.core.auth import login_required, require_asset, current_user, record_audit

# asset ledger keeps its own DB
from app.modules.inventory.assets import db as assets_db, ensure_schema as ensure_assets_schema

asset_ledger_bp = Blueprint("asset_ledger", __name__, url_prefix="/asset-ledger",
                            template_folder="templates")
bp = asset_ledger_bp

# Make sure tables exist
ensure_assets_schema()

# ---------- Database helpers ----------
def list_assets():
    """List all assets."""
    con = assets_db()
    rows = con.execute("SELECT * FROM assets ORDER BY product, sku").fetchall()
    con.close()
    return rows

def get_asset(asset_id: int):
    """Get single asset by ID."""
    con = assets_db()
    row = con.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
    con.close()
    return row

def ledger_for_asset(asset_id: int, limit: int = 500):
    """Get ledger entries for an asset."""
    con = assets_db()
    rows = con.execute("""
        SELECT * FROM asset_ledger 
        WHERE asset_id=? 
        ORDER BY ts_utc DESC 
        LIMIT ?
    """, (asset_id, limit)).fetchall()
    con.close()
    return rows

def adjust_qty(asset_id: int, delta: int, user_id: int = None, username: str = "", note: str = ""):
    """
    Adjust asset quantity (positive for checkin, negative for checkout).
    Records movement in ledger and updates qty_on_hand.
    """
    con = assets_db()
    
    # Determine action
    if delta > 0:
        action = "CHECKIN"
    elif delta < 0:
        action = "CHECKOUT"
    else:
        action = "ADJUST"
    
    # Record movement
    con.execute("""
        INSERT INTO asset_ledger(asset_id, action, qty, username, note)
        VALUES (?,?,?,?,?)
    """, (asset_id, action, abs(delta), username, note))
    
    # Update quantity
    con.execute("""
        UPDATE assets 
        SET qty_on_hand = MAX(0, qty_on_hand + ?) 
        WHERE id=?
    """, (delta, asset_id))
    
    con.commit()
    con.close()
    return True

# ---------- Routes ----------
@asset_ledger_bp.route("/", methods=["GET"])
@login_required
@require_asset
def ledger_home():
    assets = list_assets()
    asset = None
    rows = []
    asset_id = request.args.get("asset_id", type=int)
    
    if asset_id:
        asset = get_asset(asset_id)
        if asset:
            rows = ledger_for_asset(asset_id, limit=500)
    
    return render_template("inventory/inventory_ledger.html",
                           active="asset",
                           assets=assets, asset=asset, rows=rows)

@asset_ledger_bp.route("/checkin", methods=["POST"])
@login_required
@require_asset
def ledger_checkin():
    asset_id = request.form.get("asset_id", type=int)
    qty = request.form.get("qty", type=int)
    note = (request.form.get("note") or "").strip()
    
    if not asset_id or not qty:
        flash("Asset and quantity are required.", "warning")
        return redirect(url_for("asset_ledger.ledger_home"))
    
    user = current_user() or {}
    ok = adjust_qty(asset_id, abs(qty),
                    user_id=user.get("id"), username=user.get("username"), note=note)
    
    flash("Checked in." if ok else "Unable to check in.", "success" if ok else "danger")
    return redirect(url_for("asset_ledger.ledger_home", asset_id=asset_id))

@asset_ledger_bp.route("/checkout", methods=["POST"])
@login_required
@require_asset
def ledger_checkout():
    asset_id = request.form.get("asset_id", type=int)
    qty = request.form.get("qty", type=int)
    note = (request.form.get("note") or "").strip()
    
    if not asset_id or not qty:
        flash("Asset and quantity are required.", "warning")
        return redirect(url_for("asset_ledger.ledger_home"))
    
    user = current_user() or {}
    ok = adjust_qty(asset_id, -abs(qty),
                    user_id=user.get("id"), username=user.get("username"), note=note)
    
    flash("Checked out." if ok else "Unable to check out.", "success" if ok else "danger")
    return redirect(url_for("asset_ledger.ledger_home", asset_id=asset_id))