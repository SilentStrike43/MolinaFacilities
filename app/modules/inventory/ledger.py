# app/modules/inventory/ledger.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.modules.auth.security import login_required, require_asset, current_user
from .models import ensure_schema, list_assets, get_asset, record_movement, list_movements

bp = Blueprint("asset_ledger", __name__, template_folder="../templates")

@bp.route("/ledger")
@login_required
@require_asset  # ← Using the pre-defined decorator
def ledger_home():
    ensure_schema()
    asset_id = request.args.get("asset_id", type=int)
    assets = list_assets()
    asset = get_asset(asset_id) if asset_id else None
    rows = list_movements(asset_id) if asset_id else []
    return render_template("inventory/inventory_ledger.html", active="asset-ledger", assets=assets, asset=asset, rows=rows)

@bp.post("/ledger/checkin")
@login_required
@require_asset  # ← Fixed
def ledger_checkin():
    asset_id = int(request.form["asset_id"])
    qty = int(request.form["qty"])
    note = (request.form.get("note") or "").strip()
    record_movement(asset_id, "CHECKIN", qty, (current_user() or {}).get("username",""), note)
    flash("Checked in.", "success")
    return redirect(url_for("asset_ledger.ledger_home", asset_id=asset_id))

@bp.post("/ledger/checkout")
@login_required
@require_asset  # ← Fixed
def ledger_checkout():
    asset_id = int(request.form["asset_id"])
    qty = int(request.form["qty"])
    note = (request.form.get("note") or "").strip()
    record_movement(asset_id, "CHECKOUT", qty, (current_user() or {}).get("username",""), note)
    flash("Checked out.", "success")
    return redirect(url_for("asset_ledger.ledger_home", asset_id=asset_id))