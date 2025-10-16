# app/common/users.py
from __future__ import annotations
import sqlite3, json
from typing import Optional, Dict, Any
from werkzeug.security import generate_password_hash, check_password_hash
from .storage import insights_db

# ---------- schema ------------------------------------------------------------
def ensure_user_schema() -> None:
    con = insights_db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        username     TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        caps         TEXT NOT NULL DEFAULT '{}', -- JSON map of capabilities
        is_admin     INTEGER NOT NULL DEFAULT 0,
        is_sysadmin  INTEGER NOT NULL DEFAULT 0,
        disabled     INTEGER NOT NULL DEFAULT 0,
        created_utc  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    );

    CREATE TABLE IF NOT EXISTS audit (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_utc    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        username  TEXT,
        action    TEXT,
        source    TEXT,
        extra     TEXT
    );
    """)
    con.commit(); con.close()

def ensure_first_sysadmin() -> None:
    """If there is no sysadmin, create a default one (sysadmin / admin)."""
    con = insights_db()
    row = con.execute("SELECT 1 FROM users WHERE is_sysadmin=1 LIMIT 1").fetchone()
    if not row:
        con.execute(
            "INSERT INTO users(username,password_hash,caps,is_admin,is_sysadmin) VALUES(?,?,?,?,?)",
            ("sysadmin", generate_password_hash("admin"), json.dumps({}), 1, 1),
        )
        con.commit()
    con.close()

# ---------- queries / CRUD ----------------------------------------------------
def get_user_by_username(username: str) -> Optional[sqlite3.Row]:
    con = insights_db()
    row = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    con.close()
    return row

# compat alias used in some places
find_user_by_username = get_user_by_username

def create_user(username: str, password: str, *, is_admin=False, is_sysadmin=False, caps: Optional[Dict[str, Any]]=None) -> int:
    ensure_user_schema()
    con = insights_db()
    cur = con.execute(
        "INSERT INTO users(username,password_hash,caps,is_admin,is_sysadmin) VALUES(?,?,?,?,?)",
        (username, generate_password_hash(password), json.dumps(caps or {}), int(is_admin), int(is_sysadmin)),
    )
    con.commit(); uid = cur.lastrowid; con.close()
    return int(uid)

def set_password(username: str, new_password: str) -> None:
    con = insights_db()
    con.execute("UPDATE users SET password_hash=? WHERE username=?",
                (generate_password_hash(new_password), username))
    con.commit(); con.close()

def update_caps(username: str, caps: Dict[str, Any]) -> None:
    con = insights_db()
    con.execute("UPDATE users SET caps=? WHERE username=?",
                (json.dumps(caps or {}), username))
    con.commit(); con.close()

def verify_password(user_row: sqlite3.Row, password: str) -> bool:
    return bool(user_row) and check_password_hash(user_row["password_hash"], password)

# ---------- audit -------------------------------------------------------------
def record_audit(username: str, action: str, source: str = "", extra: str = "") -> None:
    try:
        con = insights_db()
        con.execute(
            "INSERT INTO audit(username, action, source, extra) VALUES(?,?,?,?)",
            (username, action, source, extra),
        )
        con.commit(); con.close()
    except Exception:
        # don't break the request path if auditing fails
        pass