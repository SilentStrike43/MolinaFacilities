# app/modules/users/models.py
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

from werkzeug.security import generate_password_hash, check_password_hash

# --- DB location (module-local, no cross-module deps) -------------------
DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "users.sqlite"

def users_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

# --- schema --------------------------------------------------------------
def ensure_user_schema() -> None:
    con = users_db()
    con.executescript(
        """
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS users(
          id           INTEGER PRIMARY KEY AUTOINCREMENT,
          username     TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          caps         TEXT,               -- JSON (dict or list of strings)
          is_admin     INTEGER DEFAULT 0,  -- boolean flags still supported
          is_sysadmin  INTEGER DEFAULT 0,
          created_utc  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        );
        """
    )
    con.commit()
    con.close()

def ensure_first_sysadmin() -> None:
    """
    If the table is empty, create an initial sysadmin account so you can log in.
    Username: admin
    Password: MF_BOOT_ADMIN_PASS env var (default: 'admin')
    """
    con = users_db()
    n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if n == 0:
        pw = os.getenv("MF_BOOT_ADMIN_PASS", "admin")
        caps = {"is_sysadmin": True, "is_admin": True, "insights": True, "users": True}
        con.execute(
            "INSERT INTO users(username, password_hash, caps, is_admin, is_sysadmin) "
            "VALUES (?,?,?,?,?)",
            ("admin", generate_password_hash(pw), json.dumps(caps), 1, 1),
        )
        con.commit()
    con.close()

# --- helpers used by auth.security --------------------------------------
def get_user_by_id(user_id: int) -> Optional[sqlite3.Row]:
    con = users_db()
    row = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    con.close()
    return row

def get_user_by_username(username: str) -> Optional[sqlite3.Row]:
    con = users_db()
    row = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    con.close()
    return row

# --- optional utilities (handy for admin screens / seeds) ---------------
def create_user(username: str, password: str, *, caps=None, is_admin=False, is_sysadmin=False) -> int:
    ensure_user_schema()
    con = users_db()
    cur = con.execute(
        "INSERT INTO users(username, password_hash, caps, is_admin, is_sysadmin) "
        "VALUES (?,?,?,?,?)",
        (username, generate_password_hash(password), json.dumps(caps or {}), int(is_admin), int(is_sysadmin)),
    )
    con.commit()
    uid = cur.lastrowid
    con.close()
    return uid

def set_password(user_id: int, new_password: str) -> None:
    con = users_db()
    con.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new_password), user_id))
    con.commit()
    con.close()

def verify_password(row: sqlite3.Row, password: str) -> bool:
    return check_password_hash(row["password_hash"], password)

# Initialize on import so auth can call into us immediately.
try:
    ensure_user_schema()
    ensure_first_sysadmin()
except Exception:
    # Keep import robust during first boot/migrations.
    pass

if __name__ == "__main__":
    print(f"Users DB: {DB_PATH}")