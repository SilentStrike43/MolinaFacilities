# app/modules/send/tracking.py  (if your package is "mail", keep the same path but this code)
from flask import render_template, request
from . import bp
from app.core.auth import require_cap
from .storage import jobs_db  # module-local DB, no common.storage

@bp.route("/tracking")
@require_cap("can_send")
def tracking():
    q = (request.args.get("q") or "").strip()
    rows = []
    if q:
        con = jobs_db()
        like = f"%{q}%"
        # NOTE: the column is tracking_number in the Send print_jobs table
        rows = con.execute("""
            SELECT id, ts_utc, checkin_date, checkin_id, package_type, package_id,
                   recipient_name, tracking_number, status, printer, template
            FROM print_jobs
            WHERE tracking_number LIKE ?
            ORDER BY ts_utc DESC
            LIMIT 200
        """, (like,)).fetchall()
        con.close()

    # If your templates live under app/modules/mail/templates/mail/, change to "mail/tracking.html"
    return render_template("send/tracking.html", active="send", rows=rows, q=q)