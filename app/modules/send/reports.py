# app/modules/send/reports.py
from flask import render_template, request, send_file
import csv, io
from . import bp
from .models import _conn
from app.modules.auth.security import require_cap

@bp.route("/insights", endpoint="reports")   # endpoint = send.reports
@require_cap("can_send")
def reports():
    q = request.args.get("q","").strip()
    sql = "SELECT * FROM print_jobs WHERE 1=1"
    params = []
    if q:
        like = f"%{q}%"
        sql += " AND (tracking_number LIKE ? OR status LIKE ?)"
        params += [like, like]
    sql += " ORDER BY ts_utc DESC LIMIT 1000"

    con = _conn()
    rows = con.execute(sql, params).fetchall()
    con.close()
    
    # FIXED: Changed template path from "mail/insights.html" to "send/insights.html"
    return render_template("send/insights.html", active="send-insights", rows=rows, q=q)

@bp.get("/insights/export")
@require_cap("can_send")
def export():
    con = _conn()
    rows = con.execute("SELECT * FROM print_jobs ORDER BY ts_utc DESC LIMIT 5000").fetchall()
    con.close()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(rows[0].keys() if rows else ["id","ts_utc","tracking_number","status"])
    for r in rows:
        w.writerow([r[k] for k in r.keys()])
    data = io.BytesIO(buf.getvalue().encode("utf-8"))
    return send_file(data, mimetype="text/csv", as_attachment=True, download_name="send_insights.csv")