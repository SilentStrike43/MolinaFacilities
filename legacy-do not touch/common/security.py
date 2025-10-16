# app/common/security.py
from __future__ import annotations
from functools import wraps
from typing import Any, Callable, Iterable, Optional
from flask import session, redirect, url_for, flash, g, request
import json

# We only depend on the current users module — no legacy imports.
# Expect one of these helpers to exist; fall back safely if not.
try:
    from app.common.users import find_user_by_username as _find_user
except Exception:
    _find_user = None

try:
    from app.common.users import get_user_by_username as _get_user
except Exception:
    _get_user = None


# ------------- user helpers ---------------------------------------------------

def _load_user(username: Optional[str]) -> Optional[dict]:
    if not username:
        return None
    # Try preferred helpers; tolerate whichever exists.
    if _find_user:
        try:
            return _find_user(username)
        except Exception:
            pass
    if _get_user:
        try:
            return _get_user(username)
        except Exception:
            pass
    # Last resort: no user loader is available
    return None


def current_user() -> Optional[dict]:
    """Return the logged-in user row (dict-like) or None."""
    u = getattr(g, "_cached_user", None)
    if u is not None:
        return u
    username = session.get("username")
    u = _load_user(username)
    g._cached_user = u
    return u


def login_user(user_row: dict) -> None:
    """Persist minimal identity to the session."""
    if not user_row:
        return
    username = user_row.get("username") or user_row.get("user") or user_row.get("email")
    session["username"] = username


def logout_user() -> None:
    for k in ("username",):
        session.pop(k, None)
    g._cached_user = None


# ------------- capability checks ---------------------------------------------

def _as_bool(user_row: dict, key: str) -> bool:
    v = user_row.get(key)
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return bool(v)
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _caps_list(user_row: dict) -> set[str]:
    """
    Normalize 'caps' to a set of lowercase strings.
    Accepts JSON text, Python list, comma-separated string, or missing.
    """
    raw = user_row.get("caps") or user_row.get("capabilities") or []
    caps: Iterable[str]
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            caps = []
        else:
            # JSON array, or csv-ish
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    caps = parsed
                else:
                    caps = [str(parsed)]
            except Exception:
                caps = [c.strip() for c in raw.split(",") if c.strip()]
    elif isinstance(raw, (list, tuple, set)):
        caps = raw
    else:
        caps = []
    return {str(c).strip().lower() for c in caps}


# synonyms/roll-ups so modules can use friendly names
_SYNONYMS: dict[str, set[str]] = {
    # inventory/asset are equivalent throughout the UI
    "asset": {"asset", "inventory"},
    "inventory": {"asset", "inventory"},

    # fulfillment roles
    "fulfillment_any": {"fulfillment_any", "fulfillment", "fulfillment_staff", "fulfillment_customer"},
    "fulfillment_staff": {"fulfillment_staff", "fulfillment_any", "fulfillment"},
    "fulfillment_customer": {"fulfillment_customer", "fulfillment_any", "fulfillment"},

    # insights, users, admin
    "insights": {"insights"},
    "users": {"users", "user_admin"},
    "admin": {"admin"},
    "sysadmin": {"sysadmin"},
}

def has_cap(user_row: Optional[dict], cap: str) -> bool:
    """True if user has the capability (admins/sysadmins always pass)."""
    if not user_row:
        return False
    if _as_bool(user_row, "is_sysadmin") or _as_bool(user_row, "sysadmin"):
        return True
    if _as_bool(user_row, "is_admin") or _as_bool(user_row, "admin"):
        return True
    want = _SYNONYMS.get(cap.lower(), {cap.lower()})
    have = _caps_list(user_row)
    return bool(have.intersection(want))


# ------------- decorators -----------------------------------------------------

def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user():
            flash("Please sign in.", "warning")
            # remember where to go back
            session["after_login"] = request.path
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapper


def require_cap(cap: str, message: Optional[str] = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    msg = message or f"{cap.capitalize()} access required."
    def _decorator(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def _wrap(*args, **kwargs):
            u = current_user()
            if not u:
                flash("Please sign in.", "warning")
                session["after_login"] = request.path
                return redirect(url_for("auth.login"))
            if not has_cap(u, cap):
                flash(msg, "danger")
                # Send them somewhere safe they can always load
                return redirect(url_for("home"))
            return view(*args, **kwargs)
        return _wrap
    return _decorator


# Friendly, explicit gates the modules can import
require_inventory            = require_cap("inventory",            "Inventory access required.")
require_asset                = require_cap("asset",                "Asset access required.")
require_insights             = require_cap("insights",             "Insights access required.")
require_users                = require_cap("users",                "User admin access required.")
require_admin                = require_cap("admin",                "Administrator access required.")
require_sysadmin             = require_cap("sysadmin",             "System administrator access required.")
require_fulfillment_any      = require_cap("fulfillment_any",      "Fulfillment access required.")
require_fulfillment_staff    = require_cap("fulfillment_staff",    "Fulfillment staff access required.")
require_fulfillment_customer = require_cap("fulfillment_customer", "Fulfillment access required.")
