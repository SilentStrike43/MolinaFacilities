# app/modules/auth/models.py - WORKING VERSION
"""
User authentication models - Compatible with your existing app structure
"""

from __future__ import annotations
import os
import sqlite3
import json
from pathlib import Path
from typing import Optional, Dict, Any
from werkzeug.security import generate_password_hash, check_password_hash

# ---- Database Configuration ----
APP_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = APP_ROOT / "data"
DB_PATH = DATA_DIR / "auth.sqlite"

def _conn() -> sqlite3.Connection:
    """Get database connection"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con

# ---- Schema Setup ----

def ensure_user_schema() -> None:
    """Create user and audit tables if they don't exist"""
    con = _conn()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_admin     INTEGER NOT NULL DEFAULT 0,
            is_sysadmin  INTEGER NOT NULL DEFAULT 0,
            caps         TEXT NOT NULL DEFAULT '{}',
            created_utc  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        );
        
        CREATE INDEX IF NOT EXISTS ix_users_username ON users(username);
        
        CREATE TABLE IF NOT EXISTS audit (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            username     TEXT,
            action       TEXT NOT NULL,
            source       TEXT,
            details      TEXT
        );
    """)
    con.commit()
    con.close()

def ensure_first_sysadmin() -> None:
    """Create initial sysadmin user if no users exist"""
    ensure_user_schema()
    con = _conn()
    count = con.execute("SELECT COUNT(*) as c FROM users WHERE is_sysadmin=1").fetchone()['c']
    
    if count == 0:
        username = os.environ.get("ADMIN_USERNAME", "admin")
        password = os.environ.get("ADMIN_PASSWORD", "changeme")
        
        create_user(username, password, is_admin=True, is_sysadmin=True)
        print(f"[auth] Created initial sysadmin user '{username}'")
        
        if password == "changeme":
            print("[auth] WARNING: Using default password! Change it immediately!")
    
    con.close()

# ---- User CRUD Operations ----

def create_user(
    username: str,
    plain_password: str,
    *,
    is_admin: bool = False,
    is_sysadmin: bool = False,
    caps_json: str = None
) -> int:
    """
    Create a new user.
    
    Args:
        username: Username
        plain_password: Plain text password (will be hashed)
        is_admin: Admin flag
        is_sysadmin: Sysadmin flag
        caps_json: JSON string of capabilities
    
    Returns:
        User ID
    """
    ensure_user_schema()
    con = _conn()
    
    password_hash = generate_password_hash(plain_password)
    caps = caps_json if caps_json is not None else "{}"
    
    cur = con.execute(
        "INSERT INTO users(username, password_hash, is_admin, is_sysadmin, caps) VALUES (?,?,?,?,?)",
        (username, password_hash, int(is_admin), int(is_sysadmin), caps)
    )
    con.commit()
    user_id = cur.lastrowid
    con.close()
    
    return user_id

def get_user_by_id(user_id: int) -> Optional[sqlite3.Row]:
    """Get user by ID"""
    con = _conn()
    row = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    con.close()
    return row

def get_user_by_username(username: str) -> Optional[sqlite3.Row]:
    """Get user by username"""
    con = _conn()
    row = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    con.close()
    return row

def set_user_password(user_id: int, new_plain: str) -> None:
    """
    Update user password.
    
    Args:
        user_id: User ID
        new_plain: New plain text password
    """
    con = _conn()
    password_hash = generate_password_hash(new_plain)
    con.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, user_id))
    con.commit()
    con.close()

def verify_password(row: sqlite3.Row, plain: str) -> bool:
    """
    Verify password against stored hash.
    
    Args:
        row: User row from database
        plain: Plain text password to verify
    
    Returns:
        True if password matches
    """
    if not row:
        return False
    return check_password_hash(row["password_hash"], plain)

def record_audit(user: Optional[Dict[str, Any]], action: str, source: str, details: str = "") -> None:
    """
    Record an audit log entry.
    
    Args:
        user: User dictionary (can be None)
        action: Action performed
        source: Source module
        details: Additional details
    """
    try:
        con = _conn()
        username = user.get('username') if user else 'system'
        con.execute(
            "INSERT INTO audit (username, action, source, details) VALUES (?, ?, ?, ?)",
            (username, action, source, details)
        )
        con.commit()
        con.close()
    except Exception:
        # Don't fail the main operation if audit logging fails
        pass

# ---- Initialize on Import ----
try:
    ensure_user_schema()
    ensure_first_sysadmin()
except Exception as e:
    print(f"[auth] Warning: Failed to initialize: {e}")