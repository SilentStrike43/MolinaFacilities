# app/common/security.py
from functools import wraps
from flask import g, session, redirect, url_for, flash, request
from .users import get_user_by_id, record_audit

# ---- helpers ----

def _row_to_dict(row):
    if row is None:
        return None
    if isinstance(row, dict):
        d = row.copy()
    else:
        # sqlite3.Row is mapping-like: convert to plain dict
        d = {k: row[k] for k in row.keys()}
    # normalize truthy flags to bool
    for k in (
        "can_send","can_asset","can_insights","can_users",
        "is_admin","is_sysadmin","is_system","active",
        "can_fulfillment_staff","can_fulfillment_customer",
    ):
        if k in d:
            d[k] = bool(d[k])
        else:
            d[k] = False
    # permission inheritance:
    # Admins / SysAdmins (and the built-in system account) implicitly have all can_* permissions.
    if d.get("is_admin") or d.get("is_sysadmin") or d.get("is_system"):
        d["can_send"] = True
        d["can_asset"] = True
        d["can_insights"] = True
        d["can_users"] = True
        d["can_fulfillment_staff"] = True
        d["can_fulfillment_customer"] = True
    return d

def current_user():
    """Return the current user as a dict with normalized boolean flags and inherited permissions."""
    uid = session.get("uid")
    # fast path: cached and matches
    if getattr(g, "_cu", None) and g._cu.get("id") == uid:
        return g._cu
    if not uid:
        g._cu = None
        return None
    row = get_user_by_id(uid)
    user = _row_to_dict(row)
    g._cu = user
    return user

def login_user(user_row):
    """Accepts either a sqlite row or a dict; stores session + caches normalized user dict."""
    d = _row_to_dict(user_row)
    session["uid"] = d["id"]
    g._cu = d
    try:
        record_audit(d, "login", "auth", f"Login from {request.remote_addr}", request.remote_addr)
    except Exception:
        pass
    return d

def logout_user():
    u = current_user()
    try:
        record_audit(u, "logout", "auth", f"Logout from {request.remote_addr}", request.remote_addr)
    except Exception:
        pass
    session.pop("uid", None)
    g._cu = None

# ---- decorators ----

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Please sign in.", "warning")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped

def require_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        u = current_user()
        if not u or not (u.get("is_admin") or u.get("is_sysadmin")):
            flash("Administrator access required.", "danger")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped

def require_sysadmin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        u = current_user()
        if not u or not u.get("is_sysadmin"):
            flash("Systems Administrator access required.", "danger")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped

def require_perm(flag_name):
    """Gate a view by a specific can_* flag; Admin/SysAdmin inherit all perms via _row_to_dict."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            u = current_user()
            if not u or not u.get(flag_name):
                flash("Access denied.", "danger")
                return redirect(url_for("home"))
            return view(*args, **kwargs)
        return wrapped
    return decorator
