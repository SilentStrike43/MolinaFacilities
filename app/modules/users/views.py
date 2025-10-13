# app/modules/users/views.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from ...common.security import login_required, require_admin, require_sysadmin, current_user
from ...common.users import (
    list_users, get_user_by_id, get_user_by_username,
    create_user, update_user, delete_user, record_audit
)

users_bp = Blueprint("users", __name__, template_folder="../../templates")

@users_bp.route("/")
@login_required
def index():
    return redirect(url_for("users.user_list"))

# ---------- User List ----------
@users_bp.route("/list")
@login_required
def user_list():
    rows = list_users(include_system=False)
    return render_template("users/list.html", active="users", tab="list", rows=rows)

@users_bp.route("/view/<int:uid>")
@login_required
def view_user(uid: int):
    row = get_user_by_id(uid)
    if not row or row["is_system"]:
        flash("User not found.", "warning")
        return redirect(url_for("users.user_list"))
    return render_template("users/view.html", active="users", tab="list", row=row)

# ---------- Modify Users (Admin) ----------
@users_bp.route("/manage", methods=["GET","POST"])
@require_admin
def manage():
    rows = list_users(include_system=False)
    return render_template("users/manage.html", active="users", tab="manage", rows=rows)

@users_bp.route("/create", methods=["POST"])
@require_admin
def create():
    data = {
        "username": (request.form.get("username") or "").strip(),
        "password": (request.form.get("password") or "").strip(),
        "email": request.form.get("email"),
        "first_name": request.form.get("first_name"),
        "last_name": request.form.get("last_name"),
        "department": request.form.get("department"),
        "position": request.form.get("position"),
        "phone": request.form.get("phone"),
        "can_send": int(bool(request.form.get("can_send"))),
        "can_asset": int(bool(request.form.get("can_asset"))),
        "can_insights": int(bool(request.form.get("can_insights"))),
        "can_users": int(bool(request.form.get("can_users"))),
        "is_admin": int(bool(request.form.get("is_admin"))),
        "is_sysadmin": 0  # cannot grant sysadmin here
    }
    if not data["username"] or not data["password"] or not data["email"] or not data["first_name"] or not data["last_name"] or not data["department"] or not data["position"]:
        flash("Please fill all required fields.", "danger")
        return redirect(url_for("users.manage"))
    # uniqueness check
    if get_user_by_username(data["username"]):
        flash("Username already exists.", "danger")
        return redirect(url_for("users.manage"))
    create_user(data)
    record_audit(current_user(), "create_user", "users", f"Created user {data['username']}")
    flash("User created.", "success")
    return redirect(url_for("users.manage"))

@users_bp.route("/edit/<int:uid>", methods=["GET","POST"])
@require_admin
def edit(uid: int):
    row = get_user_by_id(uid)
    if not row or row["is_system"]:
        flash("User not found.", "warning")
        return redirect(url_for("users.manage"))
    if request.method == "POST":
        data = {
            "email": request.form.get("email"),
            "first_name": request.form.get("first_name"),
            "last_name": request.form.get("last_name"),
            "department": request.form.get("department"),
            "position": request.form.get("position"),
            "phone": request.form.get("phone"),
            "can_send": int(bool(request.form.get("can_send"))),
            "can_asset": int(bool(request.form.get("can_asset"))),
            "can_insights": int(bool(request.form.get("can_insights"))),
            "can_users": int(bool(request.form.get("can_users"))),
            "is_admin": int(bool(request.form.get("is_admin"))),
            "is_sysadmin": row["is_sysadmin"],  # unchanged here
        }
        if request.form.get("password"):
            data["password"] = request.form.get("password")
        update_user(uid, data)
        record_audit(current_user(), "edit_user", "users", f"Edited user id={uid}")
        flash("User updated.", "success")
        return redirect(url_for("users.manage"))
    return render_template("users/edit.html", row=row, active="users", tab="manage")

@users_bp.route("/delete/<int:uid>", methods=["POST"])
@require_admin
def remove(uid: int):
    row = get_user_by_id(uid)
    if not row or row["is_system"]:
        flash("User not found.", "warning")
        return redirect(url_for("users.manage"))
    delete_user(uid)
    record_audit(current_user(), "delete_user", "users", f"Deleted user id={uid} ({row['username']})")
    flash("User deleted.", "success")
    return redirect(url_for("users.manage"))

# ---------- System Admin: grant/revoke is_sysadmin ----------
@users_bp.route("/sysadmin/<int:uid>/grant", methods=["POST"])
@require_sysadmin
def grant_sysadmin(uid: int):
    row = get_user_by_id(uid)
    if not row or row["is_system"]:
        flash("User not found.", "warning")
        return redirect(url_for("users.manage"))
    from ...common.users import update_user
    update_user(uid, {"is_sysadmin": 1})
    record_audit(current_user(), "grant_sysadmin", "users", f"Granted sysadmin to {row['username']}")
    flash("Granted Systems Administrator.", "success")
    return redirect(url_for("users.manage"))

@users_bp.route("/sysadmin/<int:uid>/revoke", methods=["POST"])
@require_sysadmin
def revoke_sysadmin(uid: int):
    row = get_user_by_id(uid)
    if not row or row["is_system"]:
        flash("User not found.", "warning")
        return redirect(url_for("users.manage"))
    from ...common.users import update_user
    update_user(uid, {"is_sysadmin": 0})
    record_audit(current_user(), "revoke_sysadmin", "users", f"Revoked sysadmin from {row['username']}")
    flash("Revoked Systems Administrator.", "success")
    return redirect(url_for("users.manage"))