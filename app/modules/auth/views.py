# app/modules/auth/views.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.core.auth import login_user, logout_user, current_user, ensure_user_schema, ensure_first_sysadmin

bp = Blueprint("auth", __name__, template_folder="../templates/auth")

@bp.before_app_request
def _bootstrap_auth():
    ensure_user_schema()
    ensure_first_sysadmin()

@bp.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username","").strip()
        p = request.form.get("password","")
        if login_user(u,p):
            return redirect(url_for("home"))
        flash("Invalid credentials.", "danger")
    return render_template("auth/login.html")

@bp.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
