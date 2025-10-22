# app/modules/admin/views.py
# COMPLETE FIXED VERSION with all routes

import os
import json
import io
import csv
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, send_file

from app.modules.auth.security import (
    login_required, 
    require_admin, 
    current_user,
    record_audit
)
from app.modules.users.models import get_user_by_id

admin_bp = Blueprint("admin", __name__, url_prefix="/admin", template_folder="templates")
bp = admin_bp

# ----------------------------
# Config (kept on disk)
# ----------------------------
CONFIG_PATH = r"C:\BTManifest\config.json"

def _load_cfg() -> dict:
    try:
        if os.path.isfile(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_cfg(cfg: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)

# ----------------------------
# Database helpers
# ----------------------------
def get_db():
    from app.modules.users.models import users_db
    return users_db()

def list_users(include_system=True):
    """List all users from auth database."""
    con = get_db()
    if include_system:
        rows = con.execute("SELECT * FROM users ORDER BY username").fetchall()
    else:
        rows = con.execute("SELECT * FROM users WHERE username != 'system' ORDER BY username").fetchall()
    con.close()
    return rows

def set_elevated_flags_partial(uid: int, is_admin: int, is_sysadmin: int):
    """Update only admin/sysadmin flags without touching other fields."""
    con = get_db()
    con.execute("""
        UPDATE users 
        SET is_admin = ?, is_sysadmin = ?
        WHERE id = ?
    """, (is_admin, is_sysadmin, uid))
    con.commit()
    con.close()

def query_audit(q="", username="", action="", date_from="", date_to="", limit=2000):
    """Query audit logs with filters."""
    # TODO: Create audit table in users database
    # For now, return empty results
    return []
    
    # When audit table is ready, uncomment this:
    # con = get_db()
    # sql = "SELECT * FROM audit WHERE 1=1"
    # params = []
    # 
    # if q:
    #     like_q = f"%{q}%"
    #     sql += " AND (username LIKE ? OR action LIKE ? OR details LIKE ?)"
    #     params.extend([like_q, like_q, like_q])
    # 
    # if username:
    #     sql += " AND username LIKE ?"
    #     params.append(f"%{username}%")
    # 
    # if action:
    #     sql += " AND action LIKE ?"
    #     params.append(f"%{action}%")
    # 
    # if date_from:
    #     sql += " AND date(ts_utc) >= date(?)"
    #     params.append(date_from)
    # 
    # if date_to:
    #     sql += " AND date(ts_utc) <= date(?)"
    #     params.append(date_to)
    # 
    # sql += f" ORDER BY ts_utc DESC LIMIT {limit}"
    # rows = con.execute(sql, params).fetchall()
    # con.close()
    # return rows

# ----------------------------
# Helpers - Check is_system from caps JSON
# ----------------------------
def _is_system(u) -> bool:
    """Check if user has the special 'is_system' flag (App Developer)."""
    if not u:
        return False
    
    # Check caps JSON for is_system flag
    try:
        caps = json.loads(u.get("caps", "{}") or "{}")
        if caps.get("is_system"):
            return True
    except:
        pass
    
    # Fallback: check if username is AppAdmin or system
    return u.get("username") in ("AppAdmin", "system")

# ----------------------------
# Routes
# ----------------------------
@admin_bp.route("/")
@login_required
@require_admin
def root():
    return redirect(url_for("admin.modify_fields"))

# --- Elevated users (Admin/Sysadmin toggles only) ---
@admin_bp.route("/elevated", methods=["GET", "POST"])
@login_required
@require_admin
def elevated():
    """
    - Only App Developer (system) can grant/revoke SysAdmin.
    - Admins can toggle 'Administrator' flag.
    """
    cu = current_user()
    rows_raw = list_users(include_system=False)
    
    # Convert to dicts and add is_system flag for display
    rows = []
    for r in rows_raw:
        row_dict = dict(r)
        # Check if this user is App Developer
        try:
            caps = json.loads(row_dict.get("caps", "{}") or "{}")
            row_dict["is_system"] = caps.get("is_system", False)
        except:
            row_dict["is_system"] = False
        rows.append(row_dict)

    if request.method == "POST":
        uid = int(request.form.get("uid") or 0)
        u = get_user_by_id(uid)
        if not u:
            flash("User not found.", "warning")
            return redirect(url_for("admin.elevated"))

        make_admin = 1 if request.form.get("is_admin") else 0
        make_sys   = 1 if request.form.get("is_sysadmin") else 0

        # Only App Developer (system) can modify SysAdmin
        if not _is_system(cu):
            make_sys = u["is_sysadmin"]
            flash("Only App Developer can grant System Administrator privileges.", "warning")

        set_elevated_flags_partial(uid, is_admin=make_admin, is_sysadmin=make_sys)

        record_audit(cu, "elevated_change", "admin",
                     f"{u['username']}: set admin={make_admin}, sysadmin={make_sys}")
        flash("Elevated privileges updated.", "success")
        return redirect(url_for("admin.elevated"))

    return render_template("admin/elevated.html", active="admin", page="elevated", rows=rows, cu=cu)

# --- Fields / Settings (BASE_* seeds, etc.) ---
@admin_bp.route("/fields", methods=["GET", "POST"])
@login_required
@require_admin
def modify_fields():
    msg = None
    cfg = _load_cfg()
    if request.method == "POST":
        try:
            cfg["BASE_CHECKIN"] = int(request.form.get("BASE_CHECKIN") or cfg.get("BASE_CHECKIN", 10000000000))
            cfg["BASE_PACKAGE"] = int(request.form.get("BASE_PACKAGE") or cfg.get("BASE_PACKAGE", 10000000000))
            _save_cfg(cfg)
            msg = "Settings saved."
        except Exception as e:
            msg = f"Error: {e}"
    return render_template("admin/fields.html", active="admin", page="fields", cfg=cfg, msg=msg)

# --- Audit Logs ---
@admin_bp.route("/audit")
@login_required
@require_admin
def audit():
    """View audit logs with filters."""
    # Get filter parameters
    q = request.args.get("q", "")
    username = request.args.get("username", "")
    action = request.args.get("action", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    
    # Query audit logs
    rows = query_audit(q=q, username=username, action=action, 
                       date_from=date_from, date_to=date_to)
    
    return render_template("admin/audit.html", 
                          active="admin", 
                          page="audit", 
                          rows=rows,
                          q=q,
                          username=username,
                          action=action,
                          date_from=date_from,
                          date_to=date_to)

@admin_bp.route("/audit/export")
@login_required
@require_admin
def audit_csv():
    """Export audit logs as CSV."""
    # Get filter parameters
    q = request.args.get("q", "")
    username = request.args.get("username", "")
    action = request.args.get("action", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    
    # Query audit logs
    rows = query_audit(q=q, username=username, action=action, 
                       date_from=date_from, date_to=date_to)
    
    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Timestamp", "Username", "Action", "Source", "Details"])
    
    if rows:
        for row in rows:
            writer.writerow([
                row.get("ts_utc", ""),
                row.get("username", ""),
                row.get("action", ""),
                row.get("source", ""),
                row.get("details", "")
            ])
    else:
        # Add a note if audit logging is not yet implemented
        writer.writerow(["Note:", "No audit logs available", "", "", ""])
        writer.writerow(["", "Audit logging may not be fully implemented yet", "", "", ""])
    
    # Convert to bytes for download
    mem = io.BytesIO(output.getvalue().encode("utf-8"))
    mem.seek(0)
    
    return send_file(
        mem,
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"audit_log_{datetime.now():%Y%m%d_%H%M%S}.csv"
    )