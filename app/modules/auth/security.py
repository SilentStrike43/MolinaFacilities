# app/modules/auth/security.py
from __future__ import annotations

import json
from functools import wraps
from typing import Any, Iterable, Optional

from flask import session, redirect, url_for, request, flash

# Use the module-local users store (no cross-module/legacy imports).
# These names are intentionally tolerant: if your users.models exposes slightly
# different helpers, we fall back to simple SQL on the same DB.
try:
    from app.modules.users.models import users_db, get_user_by_id as _get_user_by_id, get_user_by_username as _get_user_by_username  # type: ignore
except Exception:  # pragma: no cover
    # If models didn’t export helpers yet, we still need the DB handle.
    from app.modules.users.models import users_db  # type: ignore
    _get_user_by_id = None
    _get_user_by_username = None


# ----------------------------- user lookup -----------------------------

def _row_to_dict(row: Any) -> dict:
    # sqlite3.Row -> dict, or pass through if already dict-like
    try:
        return dict(row)
    except Exception:
        return row or {}

def _fetch_user_by_id(uid: Any) -> Optional[dict]:
    if uid is None:
        return None
    if _get_user_by_id:
        row = _get_user_by_id(uid)
        return _row_to_dict(row) if row else None
    # fallback
    con = users_db()
    row = con.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    con.close()
    return _row_to_dict(row) if row else None

def _fetch_user_by_username(username: str) -> Optional[dict]:
    if not username:
        return None
    if _get_user_by_username:
        row = _get_user_by_username(username)
        return _row_to_dict(row) if row else None
    # fallback
    con = users_db()
    row = con.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    con.close()
    return _row_to_dict(row) if row else None

def record_audit(user, action, source, details=""):
    """Audit logging function"""
    import logging
    logger = logging.getLogger('app.security')
    logger.info(f"AUDIT: {action} by {user} | {source} | {details}")

# ------------------------------ session API ----------------------------

def current_user() -> Optional[dict]:
    """
    Resolve the logged-in user from session. We accept several keys so
    this works with both the new auth views and anything left from legacy.
    """
    uid = session.get("uid") or session.get("user_id")
    username = session.get("username")
    user = _fetch_user_by_id(uid) if uid else None
    if not user and username:
        user = _fetch_user_by_username(username)
    return user

# Handy alias some templates/code use
cu = current_user


# ------------------------------ capability logic -----------------------

def _parse_caps(u: dict) -> dict:
    """
    Caps can be stored as JSON text, a dict, or a list of strings.
    Return a dict-like view with booleans.
    """
    raw = u.get("caps")
    caps_dict: dict[str, bool] = {}

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}

    if isinstance(raw, dict):
        caps_dict.update({str(k): bool(v) for k, v in raw.items()})
    elif isinstance(raw, (list, tuple, set)):
        for k in raw:
            caps_dict[str(k)] = True

    # Also honor explicit boolean columns if they exist
    for k in ("is_admin", "is_sysadmin"):
        if k in u:
            caps_dict[k] = bool(u[k])

    return caps_dict

# synonyms / compound capabilities used around the app
_CAP_SYNONYMS = {
    "asset": "can_asset",
    "inventory": "can_inventory",
    "can_asset": "can_asset",
    "can_inventory": "can_inventory",
    "send": "can_send",
    "can_send": "can_send",
    "insights": "can_insights",
    "can_insights": "can_insights",
    "users": "can_users",
    "can_users": "can_users",
    "admin": "is_admin",
    "sysadmin": "is_sysadmin",
    "fulfillment_staff": "can_fulfillment_staff",
    "can_fulfillment_staff": "can_fulfillment_staff",
    "fulfillment_customer": "can_fulfillment_customer",
    "can_fulfillment_customer": "can_fulfillment_customer",
    "fulfillment_any": "fulfillment_any",
}

def has_cap(user_row: Optional[dict], cap: str) -> bool:
    """
    Central capability check.
    - sysadmins/admins always pass
    - understands both JSON caps and boolean columns
    - supports synonyms and the special 'fulfillment_any'
    """
    if not user_row:
        return False
    u = _row_to_dict(user_row)
    caps = _parse_caps(u)

    # admin/sysadmin bypass
    if caps.get("is_sysadmin") or caps.get("is_admin"):
        return True

    key = _CAP_SYNONYMS.get(cap, cap)

    if key == "fulfillment_any":
        return bool(caps.get("fulfillment_staff") or caps.get("fulfillment_customer"))

    return bool(caps.get(key))


# ------------------------------- decorators ----------------------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("auth.login", next=request.full_path or request.path))
        return view(*args, **kwargs)
    return wrapped

def require_cap(cap: str):
    def deco(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            u = current_user()
            if not u:
                flash("Please sign in to continue.", "warning")
                return redirect(url_for("auth.login", next=request.full_path or request.path))
            if not has_cap(u, cap):
                # Consistent message but you can tune per module if needed
                flash("Access denied for this feature.", "danger")
                return redirect(url_for("home"))
            return view(*args, **kwargs)
        return wrapped
    return deco

def require_any(caps: Iterable[str]):
    caps = list(caps)
    def deco(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            u = current_user()
            if not u:
                flash("Please sign in to continue.", "warning")
                return redirect(url_for("auth.login", next=request.full_path or request.path))
            if not any(has_cap(u, c) for c in caps):
                flash("Access denied for this feature.", "danger")
                return redirect(url_for("home"))
            return view(*args, **kwargs)
        return wrapped
    return deco


# --------- convenience shims (let old names continue to work) ----------

# Common single-cap wrappers used throughout the codebase.
require_inventory     = require_cap("inventory")
require_asset         = require_cap("inventory")
require_send          = require_cap("can_send")
require_insights      = require_cap("insights")
require_users         = require_cap("users")
require_admin         = require_cap("admin")
require_sysadmin      = require_cap("sysadmin")
require_fulfillment_staff    = require_cap("fulfillment_staff")
require_fulfillment_customer = require_cap("fulfillment_customer")
require_fulfillment_any      = require_cap("fulfillment_any")
