# app/modules/fulfillment/views.py
from __future__ import annotations
from flask import Blueprint, render_template, request, redirect, url_for, flash
from ...common.security import login_required, require_fulfillment_any, require_fulfillment_staff, current_user
from ...common.storage import fulfillment_db
from ...common.users import record_audit

fulfillment_bp = Blueprint("fulfillment", __name__, template_folder="../../templates")

@fulfillment_bp.route("/request", methods=["GET","POST"])
@login_required
@require_fulfillment_any
def request_form():
    if request.method == "POST":
        con = fulfillment_db()
        cur = con.cursor()
        cur.execute("""
          INSERT INTO fulfillment_requests(service_id, requester_name, requester_username, description, status)
          VALUES(?,?,?,?,?)
        """, (
          (request.form.get("service_id") or "").strip(),
          (request.form.get("requester_name") or current_user().get("username")),
          current_user().get("username"),
          (request.form.get("description") or "").strip(),
          "Open"
        ))
        con.commit(); con.close()
        record_audit(current_user(), "create", "fulfillment", "new request")
        flash("Request submitted.", "success")
        return redirect(url_for("fulfillment.queue"))
    return render_template("fulfillment/request.html", active="fulfillment", page="request")

@fulfillment_bp.route("/queue")
@login_required
@require_fulfillment_any
def queue():
    con = fulfillment_db(); cur = con.cursor()
    rows = cur.execute("""
      SELECT id, service_id, requester_name, description, status, ts_utc
      FROM fulfillment_requests
      WHERE status IN ('Open','In-Progress')
      ORDER BY ts_utc DESC
    """).fetchall()
    con.close()
    return render_template("fulfillment/queue.html", active="fulfillment", page="queue", rows=rows)

@fulfillment_bp.route("/archive")
@login_required
@require_fulfillment_any
def archive():
    con = fulfillment_db()
    rows = con.execute("""
      SELECT id, service_id, requester_name, description, status, staff_username, ts_utc, completed_utc
      FROM fulfillment_requests
      WHERE status IN ('Completed','Cancelled')
      ORDER BY completed_utc DESC, ts_utc DESC
    """).fetchall()
    con.close()
    return render_template("fulfillment/archive.html", active="fulfillment", page="archive", rows=rows)