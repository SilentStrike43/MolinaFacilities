# app/modules/users/views.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from ...common.security import login_required, require_admin, current_user
from ...common.users import (
    list_users, get_user_by_id, create_user, update_user, record_audit
)

users_bp = Blueprint("users", __name__, template_folder="../../templates")

@users_bp.route("/users", endpoint="user_list")
@login_required
@require_admin
def user_list():
    rows = list_users(include_system=False)
    return render_template("users/list.html", active="users", tab="list", rows=rows)

@users_bp.route("/users/view/<int:uid>", endpoint="view_user")
@login_required
@require_admin
def view_user(uid):
    row = get_user_by_id(uid)
    if not row:
        flash("User not found.", "warning")
        return redirect(url_for("users.user_list"))
    return render_template("users/view.html", active="users", row=row)

@users_bp.route("/users/manage", methods=["GET","POST"], endpoint="manage")
@login_required
@require_admin
def manage():
    uid = request.args.get("uid", type=int)
    row = get_user_by_id(uid) if uid else None

    if request.method == "POST":
        form_uid = request.form.get("uid", type=int)
        data = {
            "first_name":  (request.form.get("first_name") or "").strip(),
            "last_name":   (request.form.get("last_name") or "").strip(),
            "email":       (request.form.get("email") or "").strip(),
            "department":  (request.form.get("department") or "").strip(),
            "position":    (request.form.get("position") or "").strip(),
            # Module permissions (incl. Fulfillment) managed here
            "can_send":     int(bool(request.form.get("can_send"))),
            "can_asset":    int(bool(request.form.get("can_asset"))),
            "can_insights": int(bool(request.form.get("can_insights"))),
            "can_users":    int(bool(request.form.get("can_users"))),
            "can_fulfillment_customer": int(bool(request.form.get("can_fulfillment_customer"))),
            "can_fulfillment_staff":    int(bool(request.form.get("can_fulfillment_staff"))),
        }

        if form_uid:  # update
            update_user(form_uid, data)
            record_audit(current_user(), "user_update", "users", f"Updated {form_uid}")
            flash("User updated.", "success")
            return redirect(url_for("users.manage", uid=form_uid))
        else:         # create
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            if not username or not password:
                flash("Username and initial password are required.", "warning")
                return redirect(url_for("users.manage"))
            new_id = create_user(username=username, password=password, **data)
            record_audit(current_user(), "user_create", "users", f"Created {username}({new_id})")
            flash("User created.", "success")
            return redirect(url_for("users.manage", uid=new_id))

    rows = list_users(include_system=False)
    return render_template("users/manage.html",
                           active="users", tab="manage",
                           row=row, rows=rows)