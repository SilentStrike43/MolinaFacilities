from flask import Blueprint, render_template, request, redirect, url_for, flash

from app.core.auth import (
    login_required,
    require_fulfillment_any,  # or staff/customer as needed
)

# module-local DB
from app.modules.fulfillment.storage import queue_db, ensure_schema as ensure_fulfillment_schema

fulfillment_bp = Blueprint("fulfillment", __name__, url_prefix="/fulfillment", template_folder="templates")

bp = fulfillment_bp

STATUS_CHOICES = [
    "Received", "Hold", "In-Progress", "Suspended",
    "Cancelled", "Completed", "Archive"
]
# Note: "Archive" means move to archive view (is_archived=1). "Completed" will also be green in UI.

# ---------- helpers ----------
def _user_can_staff(u) -> bool:
    return bool(u and (u.get("can_fulfillment_staff") or u.get("is_admin") or u.get("is_sysadmin") or u.get("is_system")))

def _user_can_customer(u) -> bool:
    return bool(u and (u.get("can_fulfillment_customer") or u.get("can_fulfillment_staff")
                       or u.get("is_admin") or u.get("is_sysadmin") or u.get("is_system")))

def _require_staff():
    u = current_user()
    if not _user_can_staff(u):
        flash("Fulfillment staff access required.", "danger")
        return None
    return u

def _require_customer():
    u = current_user()
    if not _user_can_customer(u):
        flash("Fulfillment access required.", "danger")
        return None
    return u

# ---------- Request Fulfillment (Customer) ----------
@fulfillment_bp.route("/request", methods=["GET","POST"])
@login_required
def request_form():
    u = _require_customer()
    if not u: return redirect(url_for("home"))

    if request.method == "POST":
        # core fields
        description  = (request.form.get("description") or "").strip()
        date_due     = (request.form.get("date_due") or "").strip()
        total_pages  = int(request.form.get("total_pages") or 0)

        # dropdown options (bundle into JSON)
        opts = {
            "print_type":     request.form.get("print_type") or "",
            "paper_size":     request.form.get("paper_size") or "",
            "paper_stock":    request.form.get("paper_stock") or "",
            "paper_color":    request.form.get("paper_color") or "",
            "paper_sides":    request.form.get("paper_sides") or "",
            "binding":        request.form.get("binding") or "",
            "covers":         request.form.get("covers") or "",
            "tabs":           request.form.get("tabs") or "",
            "finishing":      request.form.get("finishing") or "",
        }
        notes = (request.form.get("additional") or "").strip()

        if not description:
            flash("Description is required.", "danger")
            return redirect(url_for("fulfillment.request_form"))

        payload = {
            "requester_id": u["id"],
            "requester_name": f"{u.get('first_name') or ''} {u.get('last_name') or ''}".strip() or u["username"],
            "description": description,
            "date_due": date_due or None,
            "total_pages": total_pages or None,
            "status": "Received",
            "assigned_staff_id": None,
            "assigned_staff_name": None,
            "options_json": json.dumps(opts, ensure_ascii=False),
            "notes": notes,
        }
        rid = create_request(payload)

        # handle files
        for f in request.files.getlist("files"):
            if not f or not f.filename: continue
            orig = f.filename
            safe = secure_filename(orig)
            # ensure unique
            base, ext = os.path.splitext(safe)
            ext = ext.lower()
            i = 0
            stored = safe
            while os.path.exists(os.path.join(UPLOAD_DIR, stored)):
                i += 1
                stored = f"{base}_{i}{ext}"
            path = os.path.join(UPLOAD_DIR, stored)
            f.save(path)
            size = os.path.getsize(path) if os.path.exists(path) else 0
            add_file(rid, orig, stored, ext, size, ok=1)

        record_audit(u, "create_request", "fulfillment", f"rid={rid}")
        flash("Request submitted.", "success")
        return redirect(url_for("fulfillment.view_request", rid=rid))

    return render_template("fulfillment/request.html", active="fulfillment", page="request")

# ---------- Queue (Staff) ----------
@fulfillment_bp.route("/queue", methods=["GET","POST"])
@login_required
def queue():
    u = _require_staff()
    if not u: return redirect(url_for("home"))

    if request.method == "POST":
        rid = int(request.form.get("rid") or 0)
        status = request.form.get("status") or "Received"
        # archive rules
        archive = (status == "Archive") or (status == "Cancelled")
        update_status(
            rid, "Completed" if status == "Completed" else status,
            archive=archive,
            staff_id=u["id"],
            staff_name=u["username"]
        )
        record_audit(u, "update_status", "fulfillment", f"rid={rid}, status={status}")
        return redirect(url_for("fulfillment.queue"))

    rows = list_queue()
    return render_template("fulfillment/queue.html", active="fulfillment", page="queue",
                           rows=rows, statuses=STATUS_CHOICES)

# ---------- Archive (Staff) ----------
@fulfillment_bp.route("/archive")
@login_required
def archive():
    u = _require_staff()
    if not u: return redirect(url_for("home"))
    rows = list_archive()
    return render_template("fulfillment/archive.html", active="fulfillment", page="archive",
                           rows=rows)

# ---------- View/Download ----------
@fulfillment_bp.route("/view/<int:rid>")
@login_required
def view_request(rid: int):
    u = current_user()
    # viewer must be customer on their own request, or staff/elevated
    row = get_request(rid)
    if not row: abort(404)
    if not (_user_can_staff(u) or (u and (u["id"] == row["requester_id"]))):
        flash("Not authorized to view this request.", "danger")
        return redirect(url_for("home"))
    files = list_files(rid)
    try:
        opts = json.loads(row["options_json"] or "{}")
    except Exception:
        opts = {}
    return render_template("fulfillment/view.html", active="fulfillment",
                           page=("archive" if row["is_archived"] else "queue"),
                           row=row, files=files, opts=opts)

@fulfillment_bp.route("/file/<int:fid>/download")
@login_required
def download_file(fid: int):
    # limited lookup (id -> path)
    from sqlite3 import Row
    ensure_schema()
    import sqlite3
    con = sqlite3.connect(os.path.join(DATA_DIR, "fulfillment.sqlite"))
    con.row_factory = sqlite3.Row
    frow = con.execute("SELECT * FROM fulfillment_files WHERE id=?", (fid,)).fetchone()
    con.close()
    if not frow: abort(404)
    path = os.path.join(UPLOAD_DIR, frow["stored_name"])
    if not os.path.exists(path): abort(404)
    mimetype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return send_file(path, as_attachment=True, download_name=frow["orig_name"], mimetype=mimetype)