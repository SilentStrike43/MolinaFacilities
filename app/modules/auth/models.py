# app/modules/auth/models.py
from __future__ import annotations
import os, sqlite3
from pathlib import Path
from typing import Optional, Dict, Any
from werkzeug.security import generate_password_hash, check_password_hash

# ---- module-local database ---------------------------------------------------
APP_ROOT  = Path(__file__).resolve().parents[2]  # .../app
DATA_DIR  = APP_ROOT / "data"
DB_PATH   = DATA_DIR / "auth.sqlite"

def _conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con

# ---- schema / bootstrap ------------------------------------------------------
def ensure_user_schema() -> None:
    con = _conn()
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT NOT NULL UNIQUE,
            pw_hash      TEXT NOT NULL,
            is_admin     INTEGER NOT NULL DEFAULT 0,
            is_sysadmin  INTEGER NOT NULL DEFAULT 0,
            caps         TEXT NOT NULL DEFAULT '{}',
            created_utc  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        );
        CREATE INDEX IF NOT EXISTS ix_users_username ON users(username);
        """
    )
    con.commit()
    con.close()

def ensure_first_sysadmin() -> None:
    """If no sysadmin exists, create one from env or a safe default."""
    ensure_user_schema()
    con = _conn()
    cnt = con.execute("SELECT COUNT(*) AS c FROM users WHERE is_sysadmin=1").fetchone()["c"]
    if cnt == 0:
        username = os.environ.get("ADMIN_USERNAME", "admin")
        password = os.environ.get("ADMIN_PASSWORD", "changeme")
        create_user(username, password, is_admin=True, is_sysadmin=True)
        print(f"[auth] Created initial sysadmin user '{username}'")
    con.close()

def force_admin_from_env_if_present() -> None:
    """If ADMIN_USERNAME/PASSWORD are set, upsert that user (useful in dev)."""
    u = os.environ.get("ADMIN_USERNAME")
    p = os.environ.get("ADMIN_PASSWORD")
    if not u or not p:
        return
    row = get_user_by_username(u)
    if row:
        set_user_password(row["id"], p)
    else:
        create_user(u, p, is_admin=True, is_sysadmin=True)
    print(f"[auth] Ensured admin user '{u}' from environment")

# ---- CRUD --------------------------------------------------------------------
def create_user(username: str, plain_password: str,
                *, is_admin: bool=False, is_sysadmin: bool=False,
                caps_json: str | None=None) -> int:
    ensure_user_schema()
    con = _conn()
    pw_hash = generate_password_hash(plain_password)
    caps = caps_json if caps_json is not None else "{}"
    cur = con.execute(
        "INSERT INTO users(username, pw_hash, is_admin, is_sysadmin, caps) VALUES (?,?,?,?,?)",
        (username, pw_hash, int(is_admin), int(is_sysadmin), caps),
    )
    con.commit()
    uid = cur.lastrowid
    con.close()
    return uid

def get_user_by_id(user_id: int) -> Optional[sqlite3.Row]:
    con = _conn()
    row = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    con.close()
    return row

def get_user_by_username(username: str) -> Optional[sqlite3.Row]:
    con = _conn()
    row = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    con.close()
    return row

def set_user_password(user_id: int, new_plain: str) -> None:
    con = _conn()
    con.execute("UPDATE users SET pw_hash=? WHERE id=?",
                (generate_password_hash(new_plain), user_id))
    con.commit()
    con.close()

# (optionally handy in login view)
def verify_password(row: sqlite3.Row, plain: str) -> bool:
    return bool(row and check_password_hash(row["pw_hash"], plain))