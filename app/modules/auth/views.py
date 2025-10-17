# app/modules/auth/views.py
from __future__ import annotations
from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from .models import (
    ensure_user_schema,
    ensure_first_sysadmin,
    force_admin_from_env_if_present,
    get_user_by_username,
    get_user_by_id,
    set_user_password,
    verify_password,   # helper in models.py
)

# --- blueprint ---------------------------------------------------------------
bp = Blueprint("auth", __name__, template_folder="templates")

# bootstrap the tiny auth DB (module-local at app/data/auth.sqlite)
ensure_user_schema()
ensure_first_sysadmin()
force_admin_from_env_if_present()

# --- routes ------------------------------------------------------------------
@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        row = get_user_by_username(username)
        if row and verify_password(row, password):
            # keep keys compatible with core.current_user()
            session["uid"] = row["id"]
            session["username"] = row["username"]
            flash("Signed in.", "success")
            return redirect(request.args.get("next") or url_for("home"))
        flash("Invalid username or password.", "danger")
    return render_template("auth/login.html")

@bp.route("/logout")
def logout():
    session.clear()
    flash("Signed out.", "success")
    return redirect(url_for("auth.login"))

@bp.route("/change-password", methods=["GET", "POST"])
def change_password():
    uid = session.get("uid")
    if not uid:
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        p1 = request.form.get("new_password") or ""
        p2 = request.form.get("new_password2") or ""
        if not p1:
            flash("Enter a new password.", "danger")
        elif p1 != p2:
            flash("Passwords do not match.", "danger")
        else:
            set_user_password(uid, p1)
            flash("Password updated.", "success")
            return redirect(url_for("home"))

    return render_template("auth/change_password.html")
