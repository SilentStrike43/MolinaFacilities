# app/modules/send/models.py
"""
Send/Mail module models - PostgreSQL Edition
"""
import logging
from typing import Dict
from app.core.database import get_db_connection

logger = logging.getLogger(__name__)

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
                carrier VARCHAR(100),
                recipient VARCHAR(255),
                recipient_name VARCHAR(255),
                recipient_dept VARCHAR(255),
                recipient_address TEXT,
                recipient_phone VARCHAR(50),
                recipient_email VARCHAR(255),
                recipient_company VARCHAR(255),
                sender VARCHAR(255),
                submitter_name VARCHAR(255),
                package_type VARCHAR(100),
                num_pieces INTEGER DEFAULT 1,
                location VARCHAR(50),
                status VARCHAR(50) DEFAULT 'received',
                notes TEXT,
                checkin_id VARCHAR(50),
                package_id VARCHAR(50),
                checkin_date DATE,
                received_at TIMESTAMP,
                received_by VARCHAR(255),
                picked_up_at TIMESTAMP,
                picked_up_by VARCHAR(255),
                address_book_id INTEGER,
                tracking_status VARCHAR(100),
                tracking_status_description TEXT,
                estimated_delivery_date DATE,
                service_type VARCHAR(100),
                shipping_method VARCHAR(100),
                package_weight NUMERIC(10,2),
                origin_location VARCHAR(255),
                destination_location VARCHAR(255),
                last_tracked_at TIMESTAMP,
                ts_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Migrations: add missing columns to existing package_manifest tables
        migrations = [
            "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS carrier VARCHAR(100)",
            "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS recipient_dept VARCHAR(255)",
            "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS recipient_phone VARCHAR(50)",
            "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS recipient_email VARCHAR(255)",
            "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS recipient_company VARCHAR(255)",
            "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS num_pieces INTEGER DEFAULT 1",
            "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS received_at TIMESTAMP",
            "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS received_by VARCHAR(255)",
            "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS address_book_id INTEGER",
            "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS tracking_status VARCHAR(100)",
            "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS tracking_status_description TEXT",
            "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS estimated_delivery_date DATE",
            "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS service_type VARCHAR(100)",
            "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS shipping_method VARCHAR(100)",
            "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS package_weight NUMERIC(10,2)",
            "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS origin_location VARCHAR(255)",
            "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS destination_location VARCHAR(255)",
            "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS last_tracked_at TIMESTAMP",
        ]
        # Soft-delete support
        migrations.append(
            "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP"
        )
        for sql in migrations:
            cursor.execute(sql)

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

    logger.info("Send schema initialized")


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


_CHECKIN_BASE = 10_000_000


def next_checkin_id() -> str:
    conn = _conn()
    n = _bump(conn, "checkin_seq")
    return str(_CHECKIN_BASE + n)


def peek_next_checkin_id() -> str:
    conn = _conn()
    n = _peek(conn, "checkin_seq")
    return str(_CHECKIN_BASE + n)


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