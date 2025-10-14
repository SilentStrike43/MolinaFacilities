# app/modules/admin/views.py
from flask import Blueprint, render_template, request, send_file, flash, redirect, url_for
import os, json, io, csv

from ...common.security import login_required, current_user, require_admin
from ...common.users import (
    list_users, update_user, get_user_by_id,
    record_audit, query_audit
)

admin_bp = Blueprint("admin", __name__, template_folder="../../templates")

# -----------------------------------------------------------------------------
# Config helpers (Fields page)
# -----------------------------------------------------------------------------
CONFIG_PATH = r"C:\BTManifest\config.json"

def _load_cfg():
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_cfg(cfg: dict):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

# -----------------------------------------------------------------------------
# Access helper for Elevated User Actions
# -----------------------------------------------------------------------------
def _require_elevated():
    u = current_user()
    # Only Systems Admins or the App Developer (system account) may access the page
    if not u or not (u.get("is_sysadmin") or u.get("is_system")):
        flash("Elevated access required.", "danger")
        return False
    return True

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@admin_bp.route("/")
@login_required
def root():
    # Keep the default landing on Fields
    return redirect(url_for("admin.modify_fields"))

@admin_bp.route("/fields", methods=["GET", "POST"])
@require_admin  # Standard Admins can manage fields/settings
def modify_fields():
    msg = None
    cfg = _load_cfg()
    if request.method == "POST":
        cfg["BASE_CHECKIN"] = int(request.form.get("BASE_CHECKIN", cfg.get("BASE_CHECKIN", 10000000000)))
        cfg["BASE_PACKAGE"] = int(request.form.get("BASE_PACKAGE", cfg.get("BASE_PACKAGE", 10000000000)))
        _save_cfg(cfg)
        msg = "Settings saved."
        record_audit(current_user(), "save_settings", "admin", "Modified fields/settings")
    return render_template("admin/fields.html", active="admin", msg=msg, cfg=cfg)

@admin_bp.route("/audit")
@require_admin  # Admins can view audits
def audit():
    q = (request.args.get("q") or "").strip()
    username = (request.args.get("username") or "").strip()
    action = (request.args.get("action") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to   = (request.args.get("date_to") or "").strip()
    rows = query_audit(q, username, action, date_from, date_to, limit=2000)
    return render_template("admin/audit.html", active="admin", rows=rows,
                           q=q, username=username, action=action, date_from=date_from, date_to=date_to)

@admin_bp.route("/audit.csv")
@require_admin
def audit_csv():
    q = (request.args.get("q") or "").strip()
    username = (request.args.get("username") or "").strip()
    action = (request.args.get("action") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to   = (request.args.get("date_to") or "").strip()
    rows = query_audit(q, username, action, date_from, date_to, limit=100000)

    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["ts_utc","user_id","username","action","module","details","ip"])
    for r in rows:
        w.writerow([r["ts_utc"], r["user_id"], r["username"], r["action"], r["module"], r["details"], r["ip"]])
    mem = io.BytesIO(out.getvalue().encode("utf-8")); mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="audit_logs.csv")

@admin_bp.route("/permissions")
@require_admin
def permissions_legacy():
    # Old "User Permissions" page was retired.
    flash("“User Permissions” moved: use Users → Modify Users for module perms, and Admin → Elevated User Actions for Admin/SysAdmin.", "info")
    return redirect(url_for("admin.elevated"))


# -----------------------------------------------------------------------------
# Elevated User Actions (Admin/SysAdmin viewable, but only App Developer grants SysAdmin)
# -----------------------------------------------------------------------------
@admin_bp.route("/elevated", methods=["GET", "POST"])
@login_required
def elevated():
    if not _require_elevated():
        return redirect(url_for("home"))

    rows = list_users(include_system=False)

    if request.method == "POST":
        uid = int(request.form.get("uid"))
        u = get_user_by_id(uid)
        if not u:
            flash("User not found.", "warning")
            return redirect(url_for("admin.elevated"))

        cu = current_user()
        make_admin = int(bool(request.form.get("is_admin")))
        make_sys   = int(bool(request.form.get("is_sysadmin")))

        # Only App Developer (system) can change SysAdmin; SysAdmins may view but not grant it
        if not cu.get("is_system"):
            make_sys = u["is_sysadmin"]

        data = {"is_admin": make_admin, "is_sysadmin": make_sys}
        update_user(uid, data)

        who = f"{u['username']}"
        what = f"set admin={make_admin}, sysadmin={make_sys}"
        record_audit(cu, "elevated_change", "admin", f"{who}: {what}")
        flash("Elevated privileges updated.", "success")
        return redirect(url_for("admin.elevated"))

    return render_template("admin/elevated.html", active="admin", rows=rows)
