# app/modules/fulfillment/reports.py
from flask import Blueprint, render_template, request, send_file
import io, csv
from . import bp
from app.core.database import get_db_connection
from app.modules.auth.security import require_any

@bp.route("/insights")
@require_any(["can_fulfillment_staff", "can_fulfillment_customer"])
def insights():
    q = request.args.get("q", "").strip()
    
    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()
        
        sql = "SELECT * FROM fulfillment_requests WHERE 1=1"
        params = []
        
        if q:
            like = f"%{q}%"
            sql += " AND (requester_name LIKE ? OR description LIKE ? OR status LIKE ?)"
            params += [like, like, like]
        
        sql += " ORDER BY ts_utc DESC"
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()
    
    return render_template("fulfillment/insights.html", active="insights", rows=rows, q=q)

@bp.get("/insights/export")
@require_any(["can_fulfillment_staff", "can_fulfillment_customer"])
def export():
    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM fulfillment_requests ORDER BY ts_utc DESC")
        rows = cursor.fetchall()
        cursor.close()
    
    buf = io.StringIO()
    w = csv.writer(buf)
    
    # Write header
    if rows:
        w.writerow([col[0] for col in rows[0].cursor_description])
        # Write data
        for r in rows:
            w.writerow(list(r))
    else:
        w.writerow(["id","requester_name","description","date_submitted","status","completed_at","ts_utc"])
    
    data = io.BytesIO(buf.getvalue().encode("utf-8"))
    return send_file(data, mimetype="text/csv", as_attachment=True, download_name="fulfillment_insights.csv")