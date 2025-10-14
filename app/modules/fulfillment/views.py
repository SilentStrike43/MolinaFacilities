# app/modules/fulfillment/views.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, send_file
import os, json, datetime
from ...common.security import login_required, current_user
from ...common.storage import jobs_db, next_service_id
from ...common.paths import UPLOAD_DIR
from werkzeug.utils import secure_filename

fulfillment_bp = Blueprint("fulfillment", __name__, template_folder="../../templates")

STATUSES = [
    ("Received", None),
    ("Hold", None),
    ("In-Progress", None),
    ("Suspended", "warning"),
    ("Cancelled", None),
    ("Completed", "success"),
    ("Archive", None),
]

def _as_badge(status: str) -> str:
    color = dict(STATUSES).get(status)
    return f'<span class="badge bg-{color}">{status}</span>' if color else status

def _user_name(u):
    if not u: return ""
    return f"{u.get('first_name','')} {u.get('last_name','')}".strip() or u.get("username","")

# ---------- Request Fulfillment (Customer or Staff) ----------
@fulfillment_bp.route("/request", methods=["GET","POST"])
@login_required
def request_form():
    u = current_user()
    if not (u["can_fulfillment_customer"] or u["can_fulfillment_staff"]):
        flash("Access denied.", "danger"); return redirect(url_for("home"))

    if request.method == "POST":
        desc = (request.form.get("Description") or "").strip()
        date_due = (request.form.get("DateDue") or "").strip()
        pages = int(request.form.get("PageCount") or 0) or None

        payload = {
            "print_type":  request.form.get("PrintType")  or "Black and White",
            "paper_size":  request.form.get("PaperSize")  or "8.5x11",
            "paper_stock": request.form.get("PaperStock") or "#20 White Paper",
            "paper_color": request.form.get("PaperColor") or "White",
            "paper_sides": request.form.get("PaperSides") or "Single Sided",
            "binding":     request.form.get("Binding")    or "None",
            "covers":      request.form.get("Covers")     or "None",
            "tabs":        request.form.get("Tabs")       or "None",
            "finishing":   request.form.get("Finishing")  or "None",
            "additional_details": request.form.get("AdditionalDetails") or "",
        }
        if not desc:
            flash("Description is required.", "danger")
            return redirect(url_for("fulfillment.request_form"))

        con = jobs_db(); cur = con.cursor()
        service_id = next_service_id()
        requester = _user_name(u)
        cur.execute("""
            INSERT INTO fulfillment_requests(
              service_id, description, requester_user_id, requester_name,
              date_submitted, date_due, status, print_type, paper_size, paper_stock,
              paper_color, paper_sides, binding, covers, tabs, finishing, page_count, additional_details, meta_json
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            service_id, desc, u["id"], requester,
            datetime.date.today().isoformat(), date_due or None, "Received",
            payload["print_type"], payload["paper_size"], payload["paper_stock"],
            payload["paper_color"], payload["paper_sides"], payload["binding"],
            payload["covers"], payload["tabs"], payload["finishing"],
            pages, payload["additional_details"], json.dumps({})
        ))
        rid = cur.lastrowid

        files = request.files.getlist("Files")
        for f in files:
            if not f or not f.filename: continue
            name = secure_filename(f.filename)
            stored = os.path.join(UPLOAD_DIR, f"{service_id}_{name}")
            try:
                f.save(stored)
                size = os.path.getsize(stored)
                cur.execute("""INSERT INTO fulfillment_files(request_id, filename, stored_path, bytes, status, note)
                               VALUES (?,?,?,?,?,?)""", (rid, name, stored, size, "success", None))
            except Exception as e:
                cur.execute("""INSERT INTO fulfillment_files(request_id, filename, stored_path, bytes, status, note)
                               VALUES (?,?,?,?,?,?)""", (rid, name, "", 0, "failed", str(e)))
        con.commit(); con.close()
        flash(f"Request submitted: {service_id}", "success")
        return redirect(url_for("fulfillment.request_form"))

    return render_template("fulfillment/request.html", active="fulfillment", page="request", statuses=STATUSES)

# ---------- Service Queue (Staff) ----------
@fulfillment_bp.route("/queue", methods=["GET","POST"])
@login_required
def queue():
    u = current_user()
    if not u["can_fulfillment_staff"]:
        flash("Staff permission required.", "danger"); return redirect(url_for("home"))

    con = jobs_db(); cur = con.cursor()
    if request.method == "POST":
        rid = int(request.form.get("rid"))
        new_status = request.form.get("status")
        allowed = [s for s,_ in STATUSES]
        if new_status not in allowed:
            flash("Invalid status.", "danger")
        else:
            cur.execute("UPDATE fulfillment_requests SET status=? WHERE id=?", (new_status, rid))
            con.commit()

    rows = cur.execute("""
        SELECT id, service_id, description, requester_name, date_submitted, date_due, status
        FROM fulfillment_requests
        WHERE status IN ('Received','Hold','In-Progress','Suspended','Cancelled','Completed')
        ORDER BY ts_utc DESC
    """).fetchall()
    con.close()
    return render_template("fulfillment/queue.html", active="fulfillment", page="queue",
                           rows=rows, statuses=STATUSES, as_badge=_as_badge)

# ---------- Service Archive (Staff) ----------
@fulfillment_bp.route("/archive")
@login_required
def archive():
    u = current_user()
    if not u["can_fulfillment_staff"]:
        flash("Staff permission required.", "danger")
        return redirect(url_for("home"))

    con = jobs_db()
    rows = con.execute("""
        SELECT *
        FROM fulfillment_requests
        WHERE status IN ('Archive','Cancelled','Completed')
        ORDER BY ts_utc DESC
    """).fetchall()
    files = {}
    for r in rows:
        files[r["id"]] = con.execute(
            "SELECT * FROM fulfillment_files WHERE request_id=? ORDER BY id", (r["id"],)
        ).fetchall()
    con.close()

    return render_template(
        "fulfillment/archive.html",
        active="fulfillment", page="archive",
        rows=rows, files=files
    )
    
# ---------- Staff detail view (full form + files) ----------
@fulfillment_bp.route("/request/<int:rid>", methods=["GET","POST"])
@login_required
def view_request(rid: int):
    u = current_user()
    if not u["can_fulfillment_staff"]:
        flash("Staff permission required.", "danger"); return redirect(url_for("home"))

    con = jobs_db(); cur = con.cursor()
    if request.method == "POST":
        new_status = request.form.get("status")
        if new_status and new_status in [s for s,_ in STATUSES]:
            cur.execute("UPDATE fulfillment_requests SET status=? WHERE id=?", (new_status, rid))
            con.commit()
            flash("Status updated.", "success")
        return redirect(url_for("fulfillment.view_request", rid=rid))

    r = cur.execute("SELECT * FROM fulfillment_requests WHERE id=?", (rid,)).fetchone()
    if not r:
        con.close(); abort(404)
    files = cur.execute("SELECT * FROM fulfillment_files WHERE request_id=? ORDER BY id", (rid,)).fetchall()
    con.close()

    return render_template("fulfillment/view.html",
                           active="fulfillment", page="queue",
                           row=r, files=files, statuses=STATUSES, as_badge=_as_badge)

# ---------- File download ----------
@fulfillment_bp.route("/file/<int:file_id>/download")
@login_required
def download_file(file_id: int):
    u = current_user()
    con = jobs_db(); cur = con.cursor()
    f = cur.execute("SELECT f.*, r.requester_user_id FROM fulfillment_files f JOIN fulfillment_requests r ON r.id=f.request_id WHERE f.id=?", (file_id,)).fetchone()
    con.close()
    if not f or f["status"] != "success":
        abort(404)
    # allow staff, admins, or the original requester to download
    if not (u["can_fulfillment_staff"] or u["is_admin"] or u["is_sysadmin"] or (u["id"] == f["requester_user_id"])):
        flash("Access denied.", "danger")
        return redirect(url_for("home"))
    path = f["stored_path"]
    if not path or not os.path.isfile(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=f["filename"])