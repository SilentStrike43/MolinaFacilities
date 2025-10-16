# app/modules/inventory/ledger_views.py
from __future__ import annotations
from flask import Blueprint, render_template, request
from ...common.security import login_required
from ...common.storage import assets_db

asset_ledger_bp = Blueprint("asset_ledger", __name__, template_folder="../../templates")

@asset_ledger_bp.route("/inventory/ledger", methods=["GET","POST"])
@login_required
def ledger_home():
    q = (request.args.get("q") or "").strip()
    con = assets_db()
    if q:
        rows = con.execute("SELECT * FROM assets WHERE name LIKE ? ORDER BY id DESC LIMIT 500", (f"%{q}%",)).fetchall()
    else:
        rows = con.execute("SELECT * FROM assets ORDER BY id DESC LIMIT 500").fetchall()
    con.close()
    return render_template("inventory_ledger.html", active="asset", tab="ledger", rows=rows, q=q)