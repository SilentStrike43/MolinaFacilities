# app/modules/fulfillment/views.py
import os
import json
import datetime
import sqlite3
import mimetypes
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, send_file, abort
from werkzeug.utils import secure_filename

from app.core.auth import login_required, current_user, record_audit

# module-local DB
from app.modules.fulfillment.storage import queue_db, ensure_schema

fulfillment_bp = Blueprint("fulfillment", __name__, url_prefix="/fulfillment", template_folder="templates")
bp = fulfillment_bp

STATUS_CHOICES = [
    "Received", "Hold", "In-Progress", "Suspended",
    "Cancelled", "Completed", "Archive"
]

# Upload directory
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "fulfillment_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ---------- Schema setup ----------
ensure_schema()

# Extend schema for our needs
def _ensure_extended_schema():
    """Ensure fulfillment tables have all needed columns."""
    con = queue_db()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS fulfillment_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requester_id INTEGER,
            requester_name TEXT,
            description TEXT,
            date_submitted TEXT DEFAULT (date('now')),
            date_due TEXT,
            total_pages INTEGER,
            status TEXT DEFAULT 'Received',
            assigned_staff_id INTEGER,
            assigned_staff_name TEXT,
            options_json TEXT,
            notes TEXT,
            is_archived INTEGER DEFAULT 0,
            completed_at TEXT,
            ts_utc TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        );
        
        CREATE TABLE IF NOT EXISTS fulfillment_files(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            orig_name TEXT,
            stored_name TEXT,
            ext TEXT,
            bytes INTEGER,
            ok INTEGER DEFAULT 1,
            ts_utc TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            FOREIGN KEY(request_id) REFERENCES fulfillment_requests(id)
        );
    """)
    con.commit()
    con.close()

_ensure_extended_schema()

# ---------- Database helpers ----------
def create_request(data: dict) -> int:
    """Create a new fulfillment request."""
    con = queue_db()
    cur = con.execute("""
        INSERT INTO fulfillment_requests(
            requester_id, requester_name, description, date_due, total_pages,
            status, assigned_staff_id, assigned_staff_name, options_json, notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        data.get("requester_id"),
        data.get("requester_name"),
        data.get("description"),
        data.get("date_due"),
        data.get("total_pages"),
        data.get("status", "Received"),
        data.get("assigned_staff_id"),
        data.get("assigned_staff_name"),
        data.get("options_json", "{}"),
        data.get("notes", "")
    ))
    rid = cur.lastrowid
    con.commit()
    con.close()
    return rid

def add_file(request_id: int, orig_name: str, stored_name: str, ext: str, size: int, ok: int = 1):
    """Add a file record."""
    con = queue_db()
    con.execute("""
        INSERT INTO fulfillment_files(request_id, orig_name, stored_name, ext, bytes, ok)
        VALUES (?,?,?,?,?,?)
    """, (request_id, orig_name, stored_name, ext, size, ok))
    con.commit()
    con.close()

def update_status(request_id: int, status: str, archive: bool = False, staff_id: int = None, staff_name: str = None):
    """Update request status."""
    con = queue_db()
    if archive:
        con.execute("""
            UPDATE fulfillment_requests 
            SET status=?, is_archived=1, assigned_staff_id=?, assigned_staff_name=?,
                completed_at=(strftime('%Y-%m-%dT%H:%M:%SZ','now'))
            WHERE id=?
        """, (status, staff_id, staff_name, request_id))
    else:
        con.execute("""
            UPDATE fulfillment_requests 
            SET status=?, assigned_staff_id=?, assigned_staff_name=?
            WHERE id=?
        """, (status, staff_id, staff_name, request_id))
    con.commit()
    con.close()

def list_queue():
    """List non-archived requests."""
    con = queue_db()
    rows = con.execute("""
        SELECT * FROM fulfillment_requests 
        WHERE is_archived=0 
        ORDER BY ts_utc DESC
    """).fetchall()
    con.close()
    return rows

def list_archive():
    """List archived requests."""
    con = queue_db()
    rows = con.execute("""
        SELECT * FROM fulfillment_requests 
        WHERE is_archived=1 
        ORDER BY completed_at DESC, ts_utc DESC
    """).fetchall()
    con.close()
    return rows

def get_request(request_id: int):
    """Get a single request."""
    con = queue_db()
    row = con.execute("SELECT * FROM fulfillment_requests WHERE id=?", (request_id,)).fetchone()
    con.close()
    return row

def list_files(request_id: int):
    """List files for a request."""
    con = queue_db()
    rows = con.execute("""
        SELECT * FROM fulfillment_files 
        WHERE request_id=? 
        ORDER BY ts_utc
    """, (request_id,)).fetchall()
    con.close()
    return rows

# ---------- Permission helpers ----------
def _user_can_staff(u) -> bool:
    if not u:
        return False
    caps = {}
    try:
        caps = json.loads(u.get("caps") or "{}")
    except:
        pass
    return bool(
        caps.get("fulfillment_staff") or
        u.get("is_admin") or 
        u.get("is_sysadmin")
    )

def _user_can_customer(u) -> bool:
    if not u:
        return False
    caps = {}
    try:
        caps = json.loads(u.get("caps") or "{}")
    except:
        pass
    return bool(
        caps.get("fulfillment_customer") or 
        caps.get("fulfillment_staff") or
        u.get("is_admin") or 
        u.get("is_sysadmin")
    )

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
    if not u: 
        return redirect(url_for("home"))

    if request.method == "POST":
        description  = (request.form.get("description") or "").strip()
        date_due     = (request.form.get("date_due") or "").strip()
        total_pages  = int(request.form.get("total_pages") or 0)

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
            "requester_name": u.get("username", ""),
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
            if not f or not f.filename: 
                continue
            orig = f.filename
            safe = secure_filename(orig)
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
    if not u: 
        return redirect(url_for("home"))

    if request.method == "POST":
        rid = int(request.form.get("rid") or 0)
        status = request.form.get("status") or "Received"
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
    if not u: 
        return redirect(url_for("home"))
    rows = list_archive()
    return render_template("fulfillment/archive.html", active="fulfillment", page="archive", rows=rows)

# ---------- View/Download ----------
@fulfillment_bp.route("/view/<int:rid>")
@login_required
def view_request(rid: int):
    u = current_user()
    row = get_request(rid)
    if not row: 
        abort(404)
    
    # Check permissions
    if not (_user_can_staff(u) or (u and (u["id"] == row["requester_id"]))):
        flash("Not authorized to view this request.", "danger")
        return redirect(url_for("home"))
    
    files = list_files(rid)
    try:
        opts = json.loads(row["options_json"] or "{}")
    except:
        opts = {}
    
    return render_template("fulfillment/view.html", active="fulfillment",
                           page=("archive" if row["is_archived"] else "queue"),
                           row=row, files=files, opts=opts)

@fulfillment_bp.route("/file/<int:fid>/download")
@login_required
def download_file(fid: int):
    con = queue_db()
    frow = con.execute("SELECT * FROM fulfillment_files WHERE id=?", (fid,)).fetchone()
    con.close()
    
    if not frow: 
        abort(404)
    
    path = os.path.join(UPLOAD_DIR, frow["stored_name"])
    if not os.path.exists(path): 
        abort(404)
    
    mimetype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return send_file(path, as_attachment=True, download_name=frow["orig_name"], mimetype=mimetype)