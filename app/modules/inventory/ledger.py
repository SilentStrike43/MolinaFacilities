# app/modules/inventory/ledger.py
from flask import render_template, request, redirect, url_for, flash
from . import bp
from .models import _conn
from app.common.security import require_cap

@bp.route("/ledger")
@require_cap("can_asset")
def ledger_home():
    q = request.args.get("q","").strip()
    con = _conn()
    if q:
        rows = con.execute("""SELECT * FROM asset_ledger
                              WHERE inventory_id LIKE ?
                              ORDER BY ts_utc DESC LIMIT 500""", (f"%{q}%",)).fetchall()
    else:
        rows = con.execute("""SELECT * FROM asset_ledger ORDER BY ts_utc DESC LIMIT 200""").fetchall()
    con.close()
    return render_template("inventory/ledger.html", active="asset", tab="ledger", rows=rows, q=q)

@bp.post("/ledger/check")
@require_cap("can_asset")
def ledger_check():
    f = request.form
    con = _conn()
    con.execute("""INSERT INTO asset_ledger(inventory_id, action, qty, actor, note)
                   VALUES(?,?,?,?,?)""",
                (f.get("inventory_id"), f.get("action"), int(f.get("qty") or 1),
                 f.get("actor"), f.get("note")))
    con.commit(); con.close()
    flash("Ledger updated.", "success")
    return redirect(url_for("inventory.ledger_home", q=f.get("inventory_id")))
