"""
Send storage - AZURE SQL ONLY
"""
from app.core.database import get_db_connection

PACKAGE_PREFIX = {
    "Box": "PACK", "Envelope": "ENV",
    "Packs": "PACK", "Tubes": "TUBE",
    "Certified": "CERT", "Sensitive": "SENS", "Critical": "CRIT",
}


def ensure_schema():
    """Schema is managed by Azure SQL migrations, not application code."""
    pass


# Counter functions
def _bump(name: str) -> int:
    """Increment and return counter value."""
    with get_db_connection("send") as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT value FROM counters WHERE name=?", (name,))
        r = cursor.fetchone()
        val = (r[0] if r else 0) + 1
        
        if r:
            cursor.execute("UPDATE counters SET value=? WHERE name=?", (val, name))
        else:
            cursor.execute("INSERT INTO counters(name, value) VALUES(?,?)", (name, val))
        
        conn.commit()
        cursor.close()
        return val


def _peek(name: str) -> int:
    """Peek at next counter value without incrementing."""
    with get_db_connection("send") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM counters WHERE name=?", (name,))
        r = cursor.fetchone()
        cursor.close()
        val = (r[0] if r else 0) + 1
        return val


def next_checkin_id() -> int:
    """Get next check-in ID."""
    return _bump("checkin_id")


def peek_next_checkin_id() -> int:
    """Peek at next check-in ID."""
    return _peek("checkin_id")


def next_package_id(pkg_type: str) -> str:
    """Generate next package ID with prefix."""
    prefix = PACKAGE_PREFIX.get(pkg_type, "PACK")
    num = _bump(f"pkg_{prefix}")
    return f"{prefix}{num:08d}"


def peek_next_package_id(pkg_type: str) -> str:
    """Peek at next package ID."""
    prefix = PACKAGE_PREFIX.get(pkg_type, "PACK")
    num = _peek(f"pkg_{prefix}")
    return f"{prefix}{num:08d}"


# Cache helpers for tracking page
def cache_get(tracking: str):
    """Get cached tracking data."""
    with get_db_connection("send") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT carrier, payload, updated FROM cache WHERE tracking=?", (tracking,))
        r = cursor.fetchone()
        cursor.close()
        return r


def cache_set(tracking: str, carrier: str, payload_json: str):
    """Set cached tracking data."""
    with get_db_connection("send") as conn:
        cursor = conn.cursor()
        
        # Check if exists
        cursor.execute("SELECT 1 FROM cache WHERE tracking=?", (tracking,))
        exists = cursor.fetchone()
        
        if exists:
            cursor.execute("""
                UPDATE cache 
                SET carrier=?, payload=?, updated=GETUTCDATE() 
                WHERE tracking=?
            """, (carrier, payload_json, tracking))
        else:
            cursor.execute("""
                INSERT INTO cache(tracking, carrier, payload, updated) 
                VALUES (?,?,?,GETUTCDATE())
            """, (tracking, carrier, payload_json))
        
        conn.commit()
        cursor.close()