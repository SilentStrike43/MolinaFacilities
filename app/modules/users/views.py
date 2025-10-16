# app/modules/users/views.py
from __future__ import annotations
from flask import Blueprint, render_template, request, redirect, url_for, flash
from ...common.security import login_required, current_user
from ...common.users import (
    list_users, get_user_by_id, create_user, delete_user, record_audit
)
from ...common.storage import get_db

users_bp = Blueprint("users", __name__, url_prefix="/users", template_folder="templates")

bp = users_bp

# ---- helpers ---------------------------------------------------------------

def _can_view_users(u) -> bool:
    return bool(u and (u.get("can_users") or u.get("is_admin") or u.get("is_sysadmin") or u.get("is_system")))

def _can_edit_users(u) -> bool:
    # who can change profile/module flags (except elevated)
    return bool(u and (u.get("is_admin") or u.get("is_sysadmin") or u.get("is_system") or u.get("can_users")))

def _can_set_fulfillment(u) -> bool:
    # ONLY Admin / SysAdmin / App Developer can set Fulfillment flags
    return bool(u and (u.get("is_admin") or u.get("is_sysadmin") or u.get("is_system")))

def _update_user_partial(uid: int, data: dict):
    """
    Update only the columns we explicitly allow from Modify Users.
    Never touches Admin/SysAdmin/elevated/system fields.
    Avoids overwriting names/emails with NULLs by using COALESCE patterns.
    """
    allowed_cols = [
        "email","first_name","last_name","department","position","phone",
        "can_send","can_asset","can_insights","can_users",
        "can_fulfillment_staff","can_fulfillment_customer",
    ]
    sets, params = [], []
    for k in allowed_cols:
        if k in data:
            sets.append(f"{k}=?")
            params.append(data[k])

    if not sets:
        return

    sets.append("updated_at=(strftime('%Y-%m-%dT%H:%M:%SZ','now'))")
    params.append(uid)

    db = get_db()
    db.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", params)
    db.commit()

# ---- routes ----------------------------------------------------------------

@users_bp.route("/")
@login_required
def user_list():
    u = current_user()
    if not _can_view_users(u):
        flash("You don't have access to Users.", "danger")
        return redirect(url_for("home"))

    q = (request.args.get("q") or "").strip().lower()
    include_inactive = bool(request.args.get("all"))

    rows = list_users(include_system=False)
    # filter client-side for simplicity
    filtered = []
    for r in rows:
        if not include_inactive and int(r["active"]) != 1:
            continue
        if q:
            blob = " ".join([
                r["username"] or "", r["email"] or "",
                r["first_name"] or "", r["last_name"] or "",
                r["department"] or "", r["position"] or "", r["phone"] or ""
            ]).lower()
            if q not in blob:
                continue
        filtered.append(r)

    return render_template("users/list.html",
                           active="users", tab="list",
                           rows=filtered, q=q, show_all=include_inactive)

@users_bp.route("/manage", methods=["GET", "POST"])
@login_required
def manage():
    cu = current_user()
    if not _can_edit_users(cu):
        flash("You don't have permission to modify users.", "danger")
        return redirect(url_for("users.user_list"))

    if request.method == "POST":
        # Any form here submits only one user's changes
        uid = int(request.form.get("uid") or 0)
        target = get_user_by_id(uid)
        if not target:
            flash("User not found.", "warning")
            return redirect(url_for("users.manage"))

        # Profile fields (safe for can_users role to edit)
        payload = {
            "email":        (request.form.get("email") or target["email"]),
            "first_name":   (request.form.get("first_name") or target["first_name"]),
            "last_name":    (request.form.get("last_name") or target["last_name"]),
            "department":   (request.form.get("department") or target["department"]),
            "position":     (request.form.get("position") or target["position"]),
            "phone":        (request.form.get("phone") or target["phone"]),
            # Module flags
            "can_send":     1 if request.form.get("can_send") else 0,
            "can_asset":    1 if request.form.get("can_asset") else 0,
            "can_insights": 1 if request.form.get("can_insights") else 0,
            "can_users":    1 if request.form.get("can_users") else 0,
        }

        # Fulfillment flags only if Admin/SysAdmin/System
        if _can_set_fulfillment(cu):
            payload["can_fulfillment_staff"]    = 1 if request.form.get("can_fulfillment_staff") else 0
            payload["can_fulfillment_customer"] = 1 if request.form.get("can_fulfillment_customer") else 0
        else:
            # preserve existing if caller can't set them
            payload["can_fulfillment_staff"]    = target["can_fulfillment_staff"]
            payload["can_fulfillment_customer"] = target["can_fulfillment_customer"]

        # Never expose/touch elevated flags here:
        # - is_admin
        # - is_sysadmin
        # - is_system

        _update_user_partial(uid, payload)
        record_audit(cu, "update_user", "users", f"Updated user {target['username']}")
        flash("User saved.", "success")
        return redirect(url_for("users.manage"))

    rows = list_users(include_system=False)
    return render_template("users/manage.html",
                           active="users", tab="manage",
                           rows=rows,
                           can_set_fulfillment=_can_set_fulfillment(cu))

@users_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    cu = current_user()
    if not _can_edit_users(cu):
        flash("You don't have permission to create users.", "danger")
        return redirect(url_for("users.user_list"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()
        if not username or not password:
            flash("Username and password are required.", "danger")
            return redirect(url_for("users.create"))

        data = {
            "username": username,
            "password": password,
            "email": (request.form.get("email") or "").strip() or None,
            "first_name": (request.form.get("first_name") or "").strip() or None,
            "last_name": (request.form.get("last_name") or "").strip() or None,
            "department": (request.form.get("department") or "").strip() or None,
            "position": (request.form.get("position") or "").strip() or None,
            "phone": (request.form.get("phone") or "").strip() or None,
            # Module flags
            "can_send":     1 if request.form.get("can_send") else 0,
            "can_asset":    1 if request.form.get("can_asset") else 0,
            "can_insights": 1 if request.form.get("can_insights") else 0,
            "can_users":    1 if request.form.get("can_users") else 0,
            # Fulfillment flags (admin+ only)
            "can_fulfillment_staff":    1 if (_can_set_fulfillment(cu) and request.form.get("can_fulfillment_staff")) else 0,
            "can_fulfillment_customer": 1 if (_can_set_fulfillment(cu) and request.form.get("can_fulfillment_customer")) else 0,
        }
        create_user(data)
        record_audit(cu, "create_user", "users", f"Created user {username}")
        flash("User created.", "success")
        return redirect(url_for("users.manage"))

    return render_template("users/create.html", active="users", tab="manage")

@users_bp.route("/<int:uid>/delete", methods=["POST"])
@login_required
def delete(uid: int):
    cu = current_user()
    if not _can_edit_users(cu):
        flash("You don't have permission to deactivate users.", "danger")
        return redirect(url_for("users.user_list"))
    u = get_user_by_id(uid)
    if not u:
        flash("User not found.", "warning")
        return redirect(url_for("users.manage"))
    delete_user(uid)
    record_audit(cu, "delete_user", "users", f"Soft-deleted user {u['username']}")
    flash("User deactivated.", "success")
    return redirect(url_for("users.manage"))
