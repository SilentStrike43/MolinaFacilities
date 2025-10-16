# app/modules/admin/views.py
from __future__ import annotations
import os, io, csv, json
from flask import Blueprint, render_template, request, send_file, flash, redirect, url_for
from ...common.security import login_required, require_admin, current_user
from ...common.users import (
    list_users, get_user_by_id, record_audit, query_audit,
    set_elevated_flags_partial,
)
from ...common.storage import get_db

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
# Helpers
# ----------------------------
def _is_system(u) -> bool:
    return bool(u and u.get("is_system"))

# ----------------------------
# Routes
# ----------------------------
@admin_bp.route("/")
@login_required
@require_admin
def root():
    # Keep old behavior: land on fields/settings
    return redirect(url_for("admin.modify_fields"))

# --- Elevated users (Admin/Sysadmin toggles only) ---
@admin_bp.route("/elevated", methods=["GET", "POST"])
@login_required
@require_admin
def elevated():
    """
    - Only System account can grant/revoke SysAdmin.
    - Admins can toggle 'Administrator' flag.
    - Uses set_elevated_flags_partial to avoid wiping user profile fields.
    """
    cu = current_user()
    rows = list_users(include_system=False)

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

        set_elevated_flags_partial(uid, is_admin=make_admin, is_sysadmin=make_sys)

        record_audit(cu, "elevated_change", "admin",
                     f"{u['username']}: set admin={make_admin}, sysadmin={make_sys}")
        flash("Elevated privileges updated.", "success")
        return redirect(url_for("admin.elevated"))

    return render_template("admin/elevated.html", active="admin", page="elevated", rows=rows)

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
            record_audit(current_user(), "save_settings", "admin", "Modified fields/settings")
            flash(msg, "success")
        except Exception as e:
            flash(f"Save failed: {e}", "danger")
    return render_template("admin/fields.html", active="admin", page="fields", cfg=cfg, msg=msg)

# --- Audit (view + CSV export) ---
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
    return render_template("admin/audit.html", active="admin", page="audit",
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

    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["ts_utc","user_id","username","action","module","details","ip"])
    for r in rows:
        w.writerow([r["ts_utc"], r["user_id"], r["username"], r["action"], r["module"], r["details"], r["ip"]])
    mem = io.BytesIO(out.getvalue().encode("utf-8")); mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="audit_logs.csv")

# --- Permissions (module flags; no profile overwrite) ---
@admin_bp.route("/permissions", methods=["GET", "POST"])
@login_required
@require_admin
def permissions():
    """
    Updates ONLY permission columns to prevent overwriting names/emails, etc.
    """
    rows = list_users(include_system=False)

    if request.method == "POST":
        uid = int(request.form.get("uid") or 0)
        u = get_user_by_id(uid)
        if not u:
            flash("User not found.", "warning")
            return redirect(url_for("admin.permissions"))

        flags = {
            "can_send":                 1 if request.form.get("can_send") else 0,
            "can_asset":                1 if request.form.get("can_asset") else 0,
            "can_insights":             1 if request.form.get("can_insights") else 0,
            "can_users":                1 if request.form.get("can_users") else 0,
            "is_admin":                 1 if request.form.get("is_admin") else 0,
            "can_fulfillment_staff":    1 if request.form.get("can_fulfillment_staff") else 0,
            "can_fulfillment_customer": 1 if request.form.get("can_fulfillment_customer") else 0,
        }

        # Update only these columns
        db = get_db()
        db.execute(f"""
            UPDATE users SET
              can_send=?,
              can_asset=?,
              can_insights=?,
              can_users=?,
              is_admin=?,
              can_fulfillment_staff=?,
              can_fulfillment_customer=?,
              updated_at=(strftime('%Y-%m-%dT%H:%M:%SZ','now'))
            WHERE id=?
        """, (
            flags["can_send"], flags["can_asset"], flags["can_insights"], flags["can_users"],
            flags["is_admin"], flags["can_fulfillment_staff"], flags["can_fulfillment_customer"],
            uid
        ))
        db.commit()

        record_audit(current_user(), "update_permissions", "admin", f"Updated permissions for {u['username']}")
        flash("Permissions updated.", "success")
        return redirect(url_for("admin.permissions"))

    return render_template("admin/permissions.html", active="admin", page="permissions", rows=rows)