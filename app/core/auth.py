# app/core/auth.py
from __future__ import annotations
import json, os, sqlite3, functools, datetime
from typing import Optional, Dict, Any
from flask import session, g, redirect, url_for, request, flash
from werkzeug.security import generate_password_hash, check_password_hash

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)
AUTH_DB  = os.path.join(DATA_DIR, "auth.sqlite")

def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(AUTH_DB)
    con.row_factory = sqlite3.Row
    return con

# ---------- schema & bootstrap ----------
def ensure_user_schema():
    con = _conn()
    con.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            caps TEXT NOT NULL DEFAULT '{}', -- JSON string of capability flags
            is_admin INTEGER NOT NULL DEFAULT 0,
            is_sysadmin INTEGER NOT NULL DEFAULT 0,
            created_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS audit(
            id INTEGER PRIMARY KEY,
            ts_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            username TEXT, source TEXT, action TEXT, details TEXT
        )
    """)
    con.commit(); con.close()

def ensure_first_sysadmin():
    con = _conn()
    n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if n == 0:
        pw = generate_password_hash("changeme")
        con.execute("INSERT INTO users(username,password_hash,caps,is_admin,is_sysadmin) VALUES(?,?,?,?,?)",
                    ("sysadmin", pw, json.dumps({}), 1, 1))
        con.commit()
    con.close()

# ---------- user helpers ----------
def _row_to_user(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if not row: return None
    caps = {}
    try:
        caps = json.loads(row["caps"] or "{}")
    except Exception:
        caps = {}
    return {
        "id": row["id"], "username": row["username"],
        "is_admin": bool(row["is_admin"]), "is_sysadmin": bool(row["is_sysadmin"]),
        "caps": caps,
    }

def get_user_by_id(uid: int) -> Optional[Dict[str, Any]]:
    con = _conn(); r = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone(); con.close()
    return _row_to_user(r)

def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    con = _conn(); r = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone(); con.close()
    return _row_to_user(r)

def create_user(username: str, password: str, *, is_admin=False, is_sysadmin=False, caps: Optional[Dict[str, bool]]=None):
    ensure_user_schema()
    con = _conn()
    con.execute("INSERT INTO users(username,password_hash,caps,is_admin,is_sysadmin) VALUES(?,?,?,?,?)",
                (username, generate_password_hash(password), json.dumps(caps or {}),
                 1 if is_admin else 0, 1 if is_sysadmin else 0))
    con.commit(); con.close()

def set_password(username: str, new_password: str):
    con = _conn()
    con.execute("UPDATE users SET password_hash=? WHERE username=?",
                (generate_password_hash(new_password), username))
    con.commit(); con.close()

# ---------- session / auth ----------
def current_user():
    if hasattr(g, "_cu"):  # cached per-request
        return g._cu
    uid = session.get("uid")
    g._cu = get_user_by_id(uid) if uid else None
    return g._cu

def login_user(username: str, password: str) -> bool:
    con = _conn(); r = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone(); con.close()
    if not r: return False
    ok = check_password_hash(r["password_hash"], password)
    if ok:
        session["uid"] = r["id"]
        g._cu = _row_to_user(r)
    return ok

def logout_user():
    session.pop("uid", None)
    if hasattr(g, "_cu"): delattr(g, "_cu")

# ---------- capability checks ----------
def _as_bool(user: Optional[Dict[str,Any]], key: str) -> bool:
    return bool(user and user.get(key))

def _has_cap(user: Optional[Dict[str, Any]], cap: str) -> bool:
    # Admins/sysadmins bypass.
    if _as_bool(user, "is_admin") or _as_bool(user, "is_sysadmin"):
        return True
    if not user: return False
    caps = user.get("caps") or {}
    # synonyms
    if cap in ("inventory", "asset"):   # treat as same in your app
        return bool(caps.get("inventory") or caps.get("asset"))
    return bool(caps.get(cap))

def require_cap(cap: str):
    def deco(view):
        @functools.wraps(view)
        def wrapped(*a, **kw):
            u = current_user()
            if not u:
                return redirect(url_for("auth.login"))
            if not _has_cap(u, cap):
                flash(f"{cap.replace('_',' ').title()} access required.", "danger")
                return redirect(url_for("home"))
            return view(*a, **kw)
        return wrapped
    return deco
# convenience wrappers (keep old names working)
def login_required(view):    # any authenticated user
    @functools.wraps(view)
    def wrapped(*a, **kw):
        if not current_user():
            return redirect(url_for("auth.login"))
        return view(*a, **kw)
    return wrapped

require_asset              = require_cap("asset")
require_inventory          = require_cap("inventory")
require_insights           = require_cap("insights")
require_admin              = require_cap("admin")
require_sysadmin           = require_cap("sysadmin")
require_fulfillment_staff  = require_cap("fulfillment_staff")
require_fulfillment_customer = require_cap("fulfillment_customer")
require_fulfillment_any    = require_cap("fulfillment_any")

# ---------- audit ----------
def record_audit(user: Optional[Dict[str,Any]], action: str, source: str, details: str=""):
    try:
        con = _conn()
        con.execute("INSERT INTO audit(username, source, action, details) VALUES (?,?,?,?)",
                    ((user or {}).get("username"), source, action, details))
        con.commit(); con.close()
    except Exception:
        pass
