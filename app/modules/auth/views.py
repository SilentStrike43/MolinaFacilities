# app/modules/auth/views.py
from __future__ import annotations

from flask import Blueprint, render_template, request, redirect, url_for, flash
import hashlib

from app.common.security import login_user, logout_user, current_user, login_required
from app.common.users import get_user_by_username
# use users' connection helper to update only the password (avoid wiping other fields)
from app.common.users import _conn as _users_conn

# Place templates under: app/modules/auth/templates/auth/
auth_bp = Blueprint("auth", __name__, template_folder="templates/auth")
bp = auth_bp  # <-- standard export name used by app.py

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def _set_password(uid: int, raw: str) -> None:
    con = _users_conn()
    con.execute(
        "UPDATE users SET password_hash=?, updated_at=(strftime('%Y-%m-%dT%H:%M:%SZ','now')) WHERE id=?",
        (_sha256(raw), uid),
    )
    con.commit()
    con.close()

@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        row = get_user_by_username(username)
        if row and row.get("password_hash") == _sha256(password):
            login_user(row)
            flash("Signed in.", "success")
            nxt = request.args.get("next") or url_for("home")
            return redirect(nxt)
        flash("Invalid username or password.", "danger")
    return render_template("auth/login.html")

@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Signed out.", "info")
    return redirect(url_for("auth.login"))

@bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        cur = current_user()
        old = request.form.get("old_password") or ""
        new1 = request.form.get("new_password") or ""
        new2 = request.form.get("confirm_password") or ""
        if not cur:
            return redirect(url_for("auth.login"))
        if cur.get("password_hash") != _sha256(old):
            flash("Current password is incorrect.", "danger")
        elif not new1:
            flash("New password cannot be blank.", "danger")
        elif new1 != new2:
            flash("New password and confirmation do not match.", "danger")
        else:
            _set_password(int(cur["id"]), new1)
            flash("Password updated.", "success")
            return redirect(url_for("home"))
    return render_template("auth/change_password.html")
