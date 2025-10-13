from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory
import os, json, datetime
from ...common.security import require_perm, current_user, login_required
from ...common.storage import jobs_db, next_service_id
from ...common.paths import UPLOAD_DIR
from werkzeug.utils import secure_filename

fulfillment_bp = Blueprint("fulfillment", __name__, template_folder="../../templates")

# Status set + display colors
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

def _user_name(u):  # convenience
    if not u: return ""
    return f"{u.get('first_name','')} {u.get('last_name','')}".strip()

# ---------- Request Fulfillment (Customer) ----------
@fulfillment_bp.route("/request", methods=["GET","POST"])
@login_required
def request_form():
    u = current_user()
    if not (u["can_fulfillment_customer"] or u["can_fulfillment_staff"]):
        flash("Access denied.", "danger"); return redirect(url_for("home"))

    msg = None
    if request.method == "POST":
        desc = (request.form.get("Description") or "").strip()
        date_due = (request.form.get("DateDue") or "").strip()  # YYYY-MM-DD or ""
        pages = int(request.form.get("PageCount") or 0) or None

        # print options
        payload = {
            "print_type": request.form.get("PrintType") or "Black and White",
            "paper_size": request.form.get("PaperSize") or "8.5x11",
            "paper_stock": request.form.get("PaperStock") or "#20 White Paper",
            "paper_color": request.form.get("PaperColor") or "White",
            "paper_sides": request.form.get("PaperSides") or "Single Sided",
            "binding": request.form.get("Binding") or "None",
            "covers": request.form.get("Covers") or "None",
            "tabs": request.form.get("Tabs") or "None",
            "finishing": request.form.get("Finishing") or "None",
            "additional_details": request.form.get("AdditionalDetails") or "",
        }

        if not desc:
            msg=("Description is required.", False)
        else:
            con = jobs_db(); cur = con.cursor()
            service_id = next_service_id()
            requester = _user_name(u) or u["username"]
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

            # handle multi-file upload (no limit)
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
            msg=(f"Request submitted: {service_id}", True)
            flash(msg[0], "success")
            return redirect(url_for("fulfillment.request_form"))

    return render_template("fulfillment/request.html", active="fulfillment", flashmsg=msg, statuses=STATUSES)

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
        if new_status not in [s for s,_ in STATUSES]:
            flash("Invalid status.", "danger")
        else:
            cur.execute("UPDATE fulfillment_requests SET status=? WHERE id=?", (new_status, rid))
            # archive move is a logical status; we keep the record and show in archive view
            con.commit()

    rows = cur.execute("""
        SELECT id, service_id, description, requester_name, date_submitted, date_due, status
        FROM fulfillment_requests
        WHERE status IN ('Received','Hold','In-Progress','Suspended','Cancelled','Completed')
        ORDER BY ts_utc DESC
    """).fetchall()
    con.close()
    return render_template("fulfillment/queue.html", active="fulfillment", rows=rows, statuses=STATUSES, as_badge=_as_badge)

# ---------- Service Archive (Staff) ----------
@fulfillment_bp.route("/archive")
@login_required
def archive():
    u = current_user()
    if not u["can_fulfillment_staff"]:
        flash("Staff permission required.", "danger"); return redirect(url_for("home"))

    con = jobs_db()
    rows = con.execute("""
        SELECT * FROM fulfillment_requests
        WHERE status IN ('Archive','Cancelled','Completed')
        ORDER BY ts_utc DESC
    """).fetchall()
    files = {}
    for r in rows:
        files[r["id"]] = con.execute("SELECT * FROM fulfillment_files WHERE request_id=? ORDER BY id", (r["id"],)).fetchall()
    con.close()
    return render_template("fulfillment/archive.html", active="fulfillment", rows=rows, files=files)
