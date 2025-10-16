# app/modules/mail/tracking.py
from flask import render_template, request
from . import bp
from .models import _conn
from app.common.security import require_cap

@bp.route("/tracking")
@require_cap("can_send")
def tracking():
    q = request.args.get("q","").strip()
    rows = []
    if q:
        con = _conn()
        rows = con.execute("""SELECT * FROM print_jobs
                              WHERE tracking LIKE ?
                              ORDER BY ts_utc DESC LIMIT 200""", (f"%{q}%",)).fetchall()
        con.close()
    return render_template("mail/tracking.html", active="send", rows=rows, q=q)
