# app/modules/fulfillment/reports.py
from flask import Blueprint, render_template, request, send_file
import io, csv
from . import bp
from .storage import _conn
from app.modules.auth.security import require_any  # was app.common.security

@bp.route("/insights")
@require_any("can_fulfillment_staff", "can_fulfillment_customer")
def insights():
    f = request.args
    q  = f.get("q","").strip()
    con = _conn()
    sql = "SELECT * FROM fulfillment_requests WHERE 1=1"
    params = []
    if q:
        like = f"%{q}%"
        sql += " AND (service_id LIKE ? OR requester LIKE ? OR staff LIKE ? OR status LIKE ?)"
        params += [like, like, like, like]
    sql += " ORDER BY ts_utc DESC LIMIT 1000"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return render_template("fulfillment/insights.html", active="insights", rows=rows, q=q)

@bp.get("/insights/export")
@require_any("can_fulfillment_staff", "can_fulfillment_customer")
def export():
    con = _conn()
    rows = con.execute("SELECT * FROM fulfillment_requests ORDER BY ts_utc DESC").fetchall()
    con.close()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(rows[0].keys() if rows else ["id","service_id","requester","date_submitted","status","staff","completed_utc","ts_utc"])
    for r in rows:
        w.writerow([r[k] for k in r.keys()])
    data = io.BytesIO(buf.getvalue().encode("utf-8"))
    return send_file(data, mimetype="text/csv", as_attachment=True, download_name="fulfillment_insights.csv")