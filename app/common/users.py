# app/common/users.py
import os, sqlite3, hashlib, datetime
from typing import Optional, Dict

from .storage import DATA_DIR

USERS_DB = os.path.join(DATA_DIR, "users.sqlite")
os.makedirs(DATA_DIR, exist_ok=True)

def _conn():
    con = sqlite3.connect(USERS_DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.execute("PRAGMA busy_timeout=3000;")
    return con

def ensure_user_schema():
    con = _conn()
    con.execute("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username      TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          email         TEXT,
          first_name    TEXT,
          last_name     TEXT,
          department    TEXT,
          position      TEXT,
          phone         TEXT,
          can_send      INTEGER DEFAULT 0,
          can_asset     INTEGER DEFAULT 0,
          can_insights  INTEGER DEFAULT 0,
          can_users     INTEGER DEFAULT 0,
          is_admin      INTEGER DEFAULT 0,
          is_sysadmin   INTEGER DEFAULT 0,
          is_system     INTEGER DEFAULT 0,
          active        INTEGER DEFAULT 1,
          last_login_at TEXT,
          created_at    TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
          updated_at    TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
          can_fulfillment_staff    INTEGER DEFAULT 0,
          can_fulfillment_customer INTEGER DEFAULT 0
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts_utc   TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
          user_id  INTEGER,
          username TEXT,
          action   TEXT,
          module   TEXT,
          details  TEXT,
          ip       TEXT
        )
    """)
    # Legacy add columns if missing
    for ddl in (
        "ALTER TABLE users ADD COLUMN can_fulfillment_staff INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN can_fulfillment_customer INTEGER DEFAULT 0",
    ):
        try: con.execute(ddl)
        except Exception: pass
    con.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_logs(ts_utc)")
    con.commit(); con.close()

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def ensure_first_sysadmin():
    con = _conn()
    row = con.execute("SELECT id FROM users WHERE username=?", ("App Administrator",)).fetchone()
    if not row:
        con.execute("""
            INSERT INTO users(username, password_hash, email, first_name, last_name,
                              can_send, can_asset, can_insights, can_users,
                              is_admin, is_sysadmin, is_system, active)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            "App Administrator", _sha256("admin"), "owner@localhost",
            "App", "Administrator",
            1,1,1,1, 1,1,1, 1
        ))
        con.commit()
    con.close()

# -------- CRUD / lookups --------
def get_user_by_id(uid: int):
    con = _conn()
    row = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    con.close()
    return row

def get_user_by_username(username: str):
    con = _conn()
    row = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    con.close()
    return row

def list_users(include_system=False):
    con = _conn()
    if include_system:
        rows = con.execute("SELECT * FROM users WHERE active=1 ORDER BY username").fetchall()
    else:
        rows = con.execute("SELECT * FROM users WHERE active=1 AND is_system=0 ORDER BY username").fetchall()
    con.close()
    return rows

def create_user(data: Dict):
    con = _conn()
    con.execute("""
        INSERT INTO users(username, password_hash, email, first_name, last_name,
                          department, position, phone,
                          can_send, can_asset, can_insights, can_users, is_admin, is_sysadmin,
                          is_system, active, can_fulfillment_staff, can_fulfillment_customer)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        data["username"], _sha256(data["password"]),
        data.get("email"), data.get("first_name"), data.get("last_name"),
        data.get("department"), data.get("position"), data.get("phone"),
        int(data.get("can_send",0)), int(data.get("can_asset",0)), int(data.get("can_insights",0)), int(data.get("can_users",0)),
        int(data.get("is_admin",0)), int(data.get("is_sysadmin",0)),
        int(data.get("is_system",0)), 1,
        int(data.get("can_fulfillment_staff",0)), int(data.get("can_fulfillment_customer",0))
    ))
    con.commit(); con.close()

def update_user(uid: int, data: Dict):
    con = _conn()
    sets = ["email=?","first_name=?","last_name=?","department=?","position=?","phone=?",
            "can_send=?","can_asset=?","can_insights=?","can_users=?","is_admin=?","is_sysadmin=?",
            "can_fulfillment_staff=?","can_fulfillment_customer=?",
            "updated_at=(strftime('%Y-%m-%dT%H:%M:%SZ','now'))"]
    params = [
        data.get("email"), data.get("first_name"), data.get("last_name"), data.get("department"),
        data.get("position"), data.get("phone"),
        int(data.get("can_send",0)), int(data.get("can_asset",0)), int(data.get("can_insights",0)), int(data.get("can_users",0)),
        int(data.get("is_admin",0)), int(data.get("is_sysadmin",0)),
        int(data.get("can_fulfillment_staff",0)), int(data.get("can_fulfillment_customer",0))
    ]
    if data.get("password"):
        sets.append("password_hash=?")
        params.append(_sha256(data["password"]))
    params.append(uid)
    con.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", params)
    con.commit(); con.close()

def delete_user(uid: int):
    con = _conn()
    con.execute("UPDATE users SET active=0 WHERE id=?", (uid,))
    con.commit(); con.close()

# -------- audit --------
def record_audit(user_row, action: str, module: str, details: str, ip: str = None):
    con = _conn()
    con.execute("""
        INSERT INTO audit_logs(user_id, username, action, module, details, ip)
        VALUES(?,?,?,?,?,?)
    """, (
        user_row["id"] if user_row else None,
        user_row["username"] if user_row else None,
        action, module, details, ip
    ))
    con.commit(); con.close()

def query_audit(q: str = "", username: str = "", action: str = "", date_from: str = "", date_to: str = "", limit: int = 1000):
    con = _conn()
    sql = "SELECT * FROM audit_logs WHERE 1=1"
    params = []
    if q:
        like = f"%{q}%"
        sql += " AND (details LIKE ? OR module LIKE ? OR username LIKE ?)"
        params += [like, like, like]
    if username:
        sql += " AND username = ?"; params.append(username)
    if action:
        sql += " AND action = ?"; params.append(action)
    if date_from:
        sql += " AND date(ts_utc) >= date(?)"; params.append(date_from)
    if date_to:
        sql += " AND date(ts_utc) <= date(?)"; params.append(date_to)
    sql += " ORDER BY ts_utc DESC LIMIT ?"; params.append(limit)
    rows = con.execute(sql, params).fetchall()
    con.close()
    return rows
