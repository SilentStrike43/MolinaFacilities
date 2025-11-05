# app/modules/send/models.py
"""
Send/Mail module models - PostgreSQL Edition
"""
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
    """Get database connection."""
    return get_db_connection("send").__enter__()


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
        
        # Create package_manifest table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS package_manifest (
                id SERIAL PRIMARY KEY,
                instance_id INTEGER,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                tracking_number VARCHAR(255),
                recipient VARCHAR(255),
                sender VARCHAR(255),
                package_type VARCHAR(100),
                location VARCHAR(50),
                status VARCHAR(50) DEFAULT 'received',
                notes TEXT,
                picked_up_at TIMESTAMP,
                picked_up_by VARCHAR(255),
                ts_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                checkin_id VARCHAR(50),
                package_id VARCHAR(50),
                recipient_name VARCHAR(255),
                recipient_address TEXT,
                submitter_name VARCHAR(255),
                checkin_date DATE
            )
        """)
        
        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_package_tracking 
            ON package_manifest(tracking_number)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_package_recipient 
            ON package_manifest(recipient)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_package_status 
            ON package_manifest(status)
        """)
        
        cursor.close()
        print("✓ Send schema initialized")


def jobs_db():
    """Get mail database connection."""
    return _conn()


# --- ID generators for packages ---
def _bump(conn, name: str) -> int:
    """Increment a counter."""
    cursor = conn.cursor()
    
    # Try to get current value
    cursor.execute("SELECT value FROM counters WHERE name = %s", (name,))
    row = cursor.fetchone()
    
    if row:
        val = row['value'] + 1
        cursor.execute("UPDATE counters SET value = %s WHERE name = %s", (val, name))
    else:
        val = 1
        cursor.execute("INSERT INTO counters(name, value) VALUES(%s, %s)", (name, val))
    
    conn.commit()
    cursor.close()
    return val


def _peek(conn, name: str) -> int:
    """Peek at next counter value without incrementing."""
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM counters WHERE name = %s", (name,))
    row = cursor.fetchone()
    cursor.close()
    return (row['value'] + 1) if row else 1


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