"""
Send/Mail module models - AZURE SQL ONLY
"""
import os
from typing import Dict
from app.core.database import get_db_connection

PACKAGE_PREFIX: Dict[str, str] = {
    "Box": "PACK",
    "Envelope": "ENV",
    "Packs": "PACK",
    "Tubes": "TUBE",
    "Certified": "CERT",
    "Sensitive": "SENS",
    "Critical": "CRIT",
}


def _conn():
    """Get database connection - Azure SQL only."""
    return get_db_connection("send").__enter__()


def ensure_schema():
    """Schema is managed by Azure SQL migrations, not application code."""
    pass  # No-op for Azure SQL


def jobs_db():
    """Get mail database connection."""
    return _conn()


# --- ID generators for packages ---
def _bump(conn, name: str) -> int:
    """Increment a counter."""
    cursor = conn.cursor()
    
    # Try to get current value
    cursor.execute("SELECT value FROM counters WHERE name = ?", (name,))
    row = cursor.fetchone()
    
    if row:
        val = row[0] + 1
        cursor.execute("UPDATE counters SET value = ? WHERE name = ?", (val, name))
    else:
        val = 1
        cursor.execute("INSERT INTO counters(name, value) VALUES(?, ?)", (name, val))
    
    conn.commit()
    cursor.close()
    return val


def _peek(conn, name: str) -> int:
    """Peek at next counter value without incrementing."""
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM counters WHERE name = ?", (name,))
    row = cursor.fetchone()
    cursor.close()
    return (row[0] + 1) if row else 1


def next_checkin_id() -> int:
    conn = _conn()
    return _bump(conn, "checkin_seq")


def peek_next_checkin_id() -> int:
    conn = _conn()
    return _peek(conn, "checkin_seq")


def _pkg_key(t: str) -> str:
    return f"pkg_{(t or 'Box').strip()}"


def next_package_id(pkg_type: str) -> str:
    conn = _conn()
    n = _bump(conn, _pkg_key(pkg_type))
    return f"{PACKAGE_PREFIX.get(pkg_type, 'PACK')}{n:08d}"


def peek_next_package_id(pkg_type: str) -> str:
    conn = _conn()
    n = _peek(conn, _pkg_key(pkg_type))
    return f"{PACKAGE_PREFIX.get(pkg_type, 'PACK')}{n:08d}"