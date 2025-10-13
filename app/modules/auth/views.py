# app/modules/auth/views.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from ...common.users import get_user_by_username, update_user, record_audit
from ...common.security import login_user, logout_user, current_user
from ...common.users import _sha256  # reuse hasher

auth_bp = Blueprint("auth", __name__, template_folder="../../templates")

@auth_bp.route("/login", methods=["GET","POST"])
def login():
    nxt = request.args.get("next") or url_for("home")
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()
        user = get_user_by_username(username)
        if not user or user["active"] != 1:
            flash("Invalid credentials.", "danger")
        else:
            if user["password_hash"] == _sha256(password):
                login_user(user)
                flash("Welcome.", "success")
                return redirect(nxt)
            flash("Invalid credentials.", "danger")
    return render_template("auth/login.html")

@auth_bp.route("/logout")
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for("auth.login"))

@auth_bp.route("/password", methods=["GET","POST"])
def change_password():
    u = current_user()
    if not u:
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        old = request.form.get("old") or ""
        new1 = request.form.get("new1") or ""
        new2 = request.form.get("new2") or ""
        if _sha256(old) != u["password_hash"]:
            flash("Current password is incorrect.", "danger")
        elif not new1 or new1 != new2:
            flash("New passwords do not match.", "danger")
        else:
            update_user(u["id"], {"password": new1})
            flash("Password updated.", "success")
            record_audit(u, "change_password", "auth", "User changed own password")
            return redirect(url_for("home"))
    return render_template("auth/change_password.html", user=u)