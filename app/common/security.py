# app/common/security.py
from __future__ import annotations
from functools import wraps
from typing import Any, Dict, Optional, Mapping

from flask import session, redirect, url_for, flash

# -------------------------------------------------------------------
# Session helpers + compatibility shims for legacy imports
# -------------------------------------------------------------------

# We store a slim user dict in the session after auth.
SESSION_KEY = "user"

def _row_to_user_dict(row: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Legacy-compatible serializer. Accepts a sqlite3.Row or plain dict
    and returns the minimal user payload we keep in session.
    """
    g = row.get if hasattr(row, "get") else (lambda k, d=None: row[k] if k in row else d)
    return {
        "id":                g("id"),
        "username":          g("username"),
        "email":             g("email"),
        "first_name":        g("first_name"),
        "last_name":         g("last_name"),
        "department":        g("department"),
        "position":          g("position"),
        "phone":             g("phone"),
        # perms
        "can_send":              int(bool(g("can_send", 0))),
        "can_asset":             int(bool(g("can_asset", 0))),
        "can_insights":          int(bool(g("can_insights", 0))),
        "can_users":             int(bool(g("can_users", 0))),
        "can_fulfillment_staff": int(bool(g("can_fulfillment_staff", 0))),
        "can_fulfillment_customer": int(bool(g("can_fulfillment_customer", 0))),
        # elevated
        "is_admin":    int(bool(g("is_admin", 0))),
        "is_sysadmin": int(bool(g("is_sysadmin", 0))),
        "is_system":   int(bool(g("is_system", 0))),
        "active":      int(bool(g("active", 1))),
    }

def login_user(user_row_or_dict: Mapping[str, Any]) -> None:
    """
    Legacy API expected by auth module.
    Serializes the DB row/dict into a safe session payload.
    """
    session[SESSION_KEY] = _row_to_user_dict(user_row_or_dict)

def logout_user() -> None:
    """Legacy API expected by auth module."""
    session.pop(SESSION_KEY, None)

def current_user() -> Optional[Dict[str, Any]]:
    """Return None if not logged in."""
    return session.get(SESSION_KEY) or None


# -------------------------------------------------------------------
# Role/permission helpers
# -------------------------------------------------------------------

def _is_elevated(u: Optional[Dict]) -> bool:
    return bool(u and (u.get("is_admin") or u.get("is_sysadmin") or u.get("is_system")))

def _has_insights(u: Optional[Dict]) -> bool:
    return bool(u and (u.get("can_insights") or _is_elevated(u)))

def _has_fulfillment_any(u: Optional[Dict]) -> bool:
    return bool(u and (_is_elevated(u) or u.get("can_fulfillment_staff") or u.get("can_fulfillment_customer")))

def _has_fulfillment_staff(u: Optional[Dict]) -> bool:
    return bool(u and (_is_elevated(u) or u.get("can_fulfillment_staff")))


# -------------------------------------------------------------------
# Decorators
# -------------------------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped

def require_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        u = current_user()
        if not u or not (u.get("is_admin") or u.get("is_sysadmin") or u.get("is_system")):
            flash("Administrator access required.", "danger")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped

def require_sysadmin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        u = current_user()
        if not u or not (u.get("is_sysadmin") or u.get("is_system")):
            flash("Systems Administrator access required.", "danger")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped

def require_insights(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        u = current_user()
        if not _has_insights(u):
            flash("Insights access required.", "danger")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped

def require_fulfillment_any(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        u = current_user()
        if not _has_fulfillment_any(u):
            flash("Fulfillment access required.", "danger")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped

def require_fulfillment_staff(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        u = current_user()
        if not _has_fulfillment_staff(u):
            flash("Fulfillment access required.", "danger")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped


# Explicit re-exports for legacy imports elsewhere
__all__ = [
    "login_user", "logout_user", "current_user",
    "login_required", "require_admin", "require_sysadmin",
    "require_insights", "require_fulfillment_any", "require_fulfillment_staff",
]