# app/modules/inventory/reports.py
from flask import render_template, request, send_file
import csv, io
from . import bp
from .models import _conn
from app.common.security import require_cap

@bp.route("/insights")
@require_cap("can_asset")
def insights():
    # simple filters
    f = request.args
    q  = f.get("q","").strip()
    con = _conn()
    sql = "SELECT * FROM inventory_reports WHERE 1=1"
    params = []
    if q:
        sql += " AND (inventory_id LIKE ? OR product_name LIKE ? OR manufacturer LIKE ?)"
        like = f"%{q}%"; params += [like, like, like]
    sql += " ORDER BY ts_utc DESC LIMIT 1000"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return render_template("inventory/insights.html", active="insights", rows=rows, q=q)

@bp.get("/insights/export")
@require_cap("can_asset")
def export_insights():
    con = _conn()
    rows = con.execute("SELECT * FROM inventory_reports ORDER BY ts_utc DESC LIMIT 5000").fetchall()
    con.close()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(rows[0].keys() if rows else ["id","ts_utc","inventory_id","submitter_name","product_name","manufacturer","item_type","pii"])
    for r in rows:
        w.writerow([r[k] for k in r.keys()])
    data = io.BytesIO(buf.getvalue().encode("utf-8"))
    return send_file(data, mimetype="text/csv", as_attachment=True, download_name="inventory_insights.csv")