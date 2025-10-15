# app/modules/admin/views.py
from flask import Blueprint, render_template, request, send_file, flash, redirect, url_for
from ...common.security import login_required, current_user, require_admin
from ...common.users import (
    list_users,
    get_user_by_id,
    record_audit,
    update_user,
    query_audit,                 # adjust if this lives elsewhere
    set_elevated_flags_partial,  # NEW helper in users.py
)
import os, json, io, csv

admin_bp = Blueprint("admin", __name__, template_folder="../../templates")

# -----------------------------
# Helper: Elevated access check
# -----------------------------
def _require_elevated():
    u = current_user()
    if not u or not (u.get("is_sysadmin") or u.get("is_system")):
        flash("Elevated access required.", "danger")
        return False
    return True

# ------------------------
# Elevated User Actions UI
# ------------------------
@admin_bp.route("/elevated", methods=["GET", "POST"])
@login_required
def elevated():
    # Only Systems Admins and App Developer (system account) can view this page
    if not _require_elevated():
        return redirect(url_for("home"))

    rows = list_users(include_system=False)

    if request.method == "POST":
        uid = int(request.form.get("uid") or 0)
        u = get_user_by_id(uid)
        if not u:
            flash("User not found.", "warning")
            return redirect(url_for("admin.elevated"))

        cu = current_user()

        # toggles from form
        make_admin = int(bool(request.form.get("is_admin")))
        make_sys   = int(bool(request.form.get("is_sysadmin")))

        # Rule: Only App Developer (system account) can grant/revoke SysAdmin
        if not cu.get("is_system"):
            make_sys = u["is_sysadmin"]  # keep existing value

        # FIX: partial update via users.py (no other columns touched)
        set_elevated_flags_partial(uid, is_admin=make_admin, is_sysadmin=make_sys)

        who  = f"{u['username']}"
        what = f"set admin={make_admin}, sysadmin={make_sys}"
        record_audit(cu, "elevated_change", "admin", f"{who}: {what}")
        flash("Elevated privileges updated.", "success")
        return redirect(url_for("admin.elevated"))

    return render_template("admin/elevated.html", active="admin", page="elevated", rows=rows)

# -----------------
# Config management
# -----------------
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

# -------------
# Admin landing
# -------------
@admin_bp.route("/")
@login_required
def root():
    return redirect(url_for("admin.modify_fields"))

# -------------
# Modify fields
# -------------
@admin_bp.route("/fields", methods=["GET", "POST"])
@login_required
@require_admin
def modify_fields():
    msg = None
    cfg = _load_cfg()
    if request.method == "POST":
        cfg["BASE_CHECKIN"] = int(request.form.get("BASE_CHECKIN", cfg.get("BASE_CHECKIN", 10000000000)))
        cfg["BASE_PACKAGE"] = int(request.form.get("BASE_PACKAGE", cfg.get("BASE_PACKAGE", 10000000000)))
        _save_cfg(cfg)
        msg = "Settings saved."
        record_audit(current_user(), "save_settings", "admin", "Modified fields/settings")
    return render_template("admin/fields.html", active="admin", page="fields", msg=msg, cfg=cfg)

# ----------
# Audit logs
# ----------
@admin_bp.route("/audit")
@login_required
@require_admin
def audit():
    q         = (request.args.get("q") or "").strip()
    username  = (request.args.get("username") or "").strip()
    action    = (request.args.get("action") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to   = (request.args.get("date_to") or "").strip()
    rows = query_audit(q, username, action, date_from, date_to, limit=2000)
    return render_template("admin/audit.html",
                           active="admin", page="audit",
                           rows=rows, q=q, username=username, action=action,
                           date_from=date_from, date_to=date_to)

@admin_bp.route("/audit.csv")
@login_required
@require_admin
def audit_csv():
    q         = (request.args.get("q") or "").strip()
    username  = (request.args.get("username") or "").strip()
    action    = (request.args.get("action") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to   = (request.args.get("date_to") or "").strip()
    rows = query_audit(q, username, action, date_from, date_to, limit=100000)

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["ts_utc","user_id","username","action","module","details","ip"])
    for r in rows:
        w.writerow([r["ts_utc"], r["user_id"], r["username"], r["action"], r["module"], r["details"], r["ip"]])
    mem = io.BytesIO(out.getvalue().encode("utf-8")); mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="audit_logs.csv")

# ---------------------------------------------------------
# Legacy Permissions page (module toggles) — still allowed
# ---------------------------------------------------------
@admin_bp.route("/permissions", methods=["GET","POST"], endpoint="permissions")
@login_required
@require_admin
def permissions_legacy():
    # This page manages module toggles only (not Admin/SysAdmin anymore)
    rows = list_users(include_system=False)
    if request.method == "POST":
        uid = int(request.form.get("uid") or 0)
        u = get_user_by_id(uid)
        if not u:
            flash("User not found.", "warning")
            return redirect(url_for("admin.permissions"))

        data = {
            "can_send":     int(bool(request.form.get("can_send"))),
            "can_asset":    int(bool(request.form.get("can_asset"))),
            "can_insights": int(bool(request.form.get("can_insights"))),
            "can_users":    int(bool(request.form.get("can_users"))),
            "can_fulfillment_staff":    int(bool(request.form.get("can_fulfillment_staff"))),
            "can_fulfillment_customer": int(bool(request.form.get("can_fulfillment_customer"))),
        }
        update_user(uid, data)  # safe: only these fields are changed
        record_audit(current_user(), "update_permissions", "admin", f"Updated permissions for {u['username']}")
        flash("Permissions updated.", "success")
        return redirect(url_for("admin.permissions"))
    return render_template("admin/permissions.html", active="admin", page="permissions", rows=rows)
