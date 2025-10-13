# app/common/security.py
import functools, hashlib, time
from flask import session, redirect, url_for, request, flash, g

from .users import get_user_by_id, get_user_by_username, record_audit

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    if getattr(g, "_cu", None) and g._cu.get("id") == uid:
        return g._cu
    user = get_user_by_id(uid)
    g._cu = user
    return user

def login_user(user_row):
    session["uid"] = user_row["id"]
    # record login audit
    record_audit(user_row, "login", "auth", f"User {user_row['username']} logged in")

def logout_user():
    u = current_user()
    if u:
        record_audit(u, "logout", "auth", f"User {u['username']} logged out")
    session.clear()

def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Please log in.", "warning")
            return redirect(url_for("auth.login", next=request.full_path))
        return view(*args, **kwargs)
    return wrapped

def _has_perm(u, perm: str) -> bool:
    if not u: return False
    if u["is_admin"] or u["is_sysadmin"]:
        return True
    return bool(u.get(perm))

def require_perm(perm: str):
    def deco(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            u = current_user()
            if not u:
                flash("Please log in.", "warning")
                return redirect(url_for("auth.login", next=request.full_path))
            if not _has_perm(u, perm):
                flash("You do not have permission to access this area.", "danger")
                return redirect(url_for("home"))
            return view(*args, **kwargs)
        return wrapped
    return deco

def require_admin(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        u = current_user()
        if not u:
            flash("Please log in.", "warning")
            return redirect(url_for("auth.login", next=request.full_path))
        if not (u["is_admin"] or u["is_sysadmin"]):
            flash("Administrator permission required.", "danger")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped

def require_sysadmin(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        u = current_user()
        if not u:
            flash("Please log in.", "warning")
            return redirect(url_for("auth.login", next=request.full_path))
        if not u["is_sysadmin"]:
            flash("Systems Administrator permission required.", "danger")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped



