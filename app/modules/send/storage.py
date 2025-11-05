# app/modules/send/storage.py
"""
Send storage - PostgreSQL Edition
"""
from app.core.database import get_db_connection

PACKAGE_PREFIX = {
    "Box": "PACK", "Envelope": "ENV",
    "Packs": "PACK", "Tubes": "TUBE",
    "Certified": "CERT", "Sensitive": "SENS", "Critical": "CRIT",
}


def ensure_schema():
    """Ensure send schema exists."""
    with get_db_connection("send") as conn:
        cursor = conn.cursor()
        
        # Create counters table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS counters (
                name VARCHAR(100) PRIMARY KEY,
                value INTEGER DEFAULT 0
            )
        """)
        
        # Create cache table for tracking lookups
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                tracking VARCHAR(255) PRIMARY KEY,
                carrier VARCHAR(50),
                payload TEXT,
                updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.close()


# Counter functions
def _bump(name: str) -> int:
    """Increment and return counter value."""
    with get_db_connection("send") as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT value FROM counters WHERE name=%s", (name,))
        r = cursor.fetchone()
        val = (r['value'] if r else 0) + 1
        
        if r:
            cursor.execute("UPDATE counters SET value=%s WHERE name=%s", (val, name))
        else:
            cursor.execute("INSERT INTO counters(name, value) VALUES(%s,%s)", (name, val))
        
        cursor.close()
        return val


def _peek(name: str) -> int:
    """Peek at next counter value without incrementing."""
    with get_db_connection("send") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM counters WHERE name=%s", (name,))
        r = cursor.fetchone()
        cursor.close()
        val = (r['value'] if r else 0) + 1
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
        cursor.execute("SELECT carrier, payload, updated FROM cache WHERE tracking=%s", (tracking,))
        r = cursor.fetchone()
        cursor.close()
        return r


def cache_set(tracking: str, carrier: str, payload_json: str):
    """Set cached tracking data."""
    with get_db_connection("send") as conn:
        cursor = conn.cursor()
        
        # Check if exists
        cursor.execute("SELECT 1 FROM cache WHERE tracking=%s", (tracking,))
        exists = cursor.fetchone()
        
        if exists:
            cursor.execute("""
                UPDATE cache 
                SET carrier=%s, payload=%s, updated=CURRENT_TIMESTAMP 
                WHERE tracking=%s
            """, (carrier, payload_json, tracking))
        else:
            cursor.execute("""
                INSERT INTO cache(tracking, carrier, payload, updated) 
                VALUES (%s,%s,%s,CURRENT_TIMESTAMP)
            """, (tracking, carrier, payload_json))
        
        cursor.close()