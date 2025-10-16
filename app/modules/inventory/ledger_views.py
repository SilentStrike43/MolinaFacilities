# app/modules/inventory/ledger_views.py
from __future__ import annotations
from flask import Blueprint, render_template, request, redirect, url_for, flash, g
from ...common.security import login_required, require_asset
from ...common.assets import (
    ensure_assets_schema, list_assets, get_asset,
    ledger_for_asset, adjust_qty,
)

# Keep the old endpoint name so existing base.html links keep working:
asset_ledger_bp = Blueprint("asset_ledger", __name__, url_prefix="/inventory/ledger",
                            template_folder="../../templates")

# Make sure tables exist before any request
ensure_assets_schema()


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
    return render_template("inventory_ledger.html",
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
    user = getattr(g, "_cu", None) or {}
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
    user = getattr(g, "_cu", None) or {}
    ok = adjust_qty(asset_id, -abs(qty),
                    user_id=user.get("id"), username=user.get("username"), note=note)
    flash("Checked out." if ok else "Unable to check out.", "success" if ok else "danger")
    return redirect(url_for("asset_ledger.ledger_home", asset_id=asset_id))
