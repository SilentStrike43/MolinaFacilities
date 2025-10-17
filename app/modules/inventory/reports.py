# app/modules/inventory/reports.py
from flask import Blueprint, render_template, request, send_file
import io, csv
from app.modules.auth.security import login_required, require_cap
from .models import _conn, ensure_schema

bp = Blueprint("inventory_reports", __name__, template_folder="../templates")

@bp.route("/insights")
@login_required
@require_cap("can_insights")
def insights():
    ensure_schema()
    f = {k:(request.args.get(k) or "").strip() for k in
         ["q","inventory_id","product_name","manufacturer","item_type",
          "submitter_name","pii","date_from","date_to"]}
    con = _conn()
    sql = "SELECT * FROM inventory_reports WHERE 1=1"
    params = []
    def like(field, val):
        nonlocal sql, params
        if val:
            sql += f" AND {field} LIKE ?"; params.append(f"%{val}%")
    like("submitter_name", f["submitter_name"])
    like("product_name", f["product_name"])
    like("manufacturer", f["manufacturer"])
    like("item_type", f["item_type"])
    if f["inventory_id"]:
        sql += " AND inventory_id = ?"; params.append(f["inventory_id"])
    if f["pii"]:
        sql += " AND 1=1"  # keep arg for template parity
    if f["q"]:
        like("(notes || ' ' || product_name || ' ' || manufacturer)", f["q"])
    if f["date_from"]:
        sql += " AND date(ts_utc) >= date(?)"; params.append(f["date_from"])
    if f["date_to"]:
        sql += " AND date(ts_utc) <= date(?)"; params.append(f["date_to"])
    sql += " ORDER BY ts_utc DESC LIMIT 2000"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return render_template("reports_inventory.html", active="insights", tab="inventory", rows=rows, **f)

@bp.route("/insights/export")
@login_required
@require_cap("can_insights")
def export():
    ensure_schema()
    con = _conn()
    rows = con.execute("SELECT * FROM inventory_reports ORDER BY ts_utc DESC").fetchall()
    con.close()
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["ts_utc","inventory_id","product_name","manufacturer","item_type","submitter_name","pii","notes"])
    for r in rows:
        w.writerow([r["ts_utc"], r["inventory_id"], r["product_name"], r["manufacturer"],
                    r["item_type"], r["submitter_name"], "", r["notes"]])
    mem = io.BytesIO(out.getvalue().encode("utf-8")); mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="insights_inventory.csv")