# app/modules/fulfillment/storage.py
"""
Fulfillment storage - PostgreSQL Edition
"""
from app.core.database import get_db_connection


def ensure_schema():
    """Ensure fulfillment schema exists."""
    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()
        
        # Create service_requests table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS service_requests (
                id SERIAL PRIMARY KEY,
                instance_id INTEGER,
                requester_id INTEGER,
                requester_name VARCHAR(255),
                title VARCHAR(500),
                description TEXT,
                request_type VARCHAR(100),
                priority VARCHAR(50) DEFAULT 'normal',
                status VARCHAR(50) DEFAULT 'pending',
                assigned_to INTEGER,
                location VARCHAR(50),
                due_date DATE,
                completed_at TIMESTAMP,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create fulfillment_requests table (legacy)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fulfillment_requests (
                id SERIAL PRIMARY KEY,
                instance_id INTEGER,
                service_id VARCHAR(100),
                requester TEXT,
                requester_name TEXT,
                date_submitted DATE DEFAULT CURRENT_DATE,
                status VARCHAR(50) DEFAULT 'new',
                staff VARCHAR(255),
                assigned_staff_name VARCHAR(255),
                completed_utc TIMESTAMP,
                completed_at TIMESTAMP,
                ts_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                description TEXT,
                total_pages INTEGER,
                date_due DATE,
                is_archived BOOLEAN DEFAULT FALSE,
                notes TEXT
            )
        """)
        
        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_service_status 
            ON service_requests(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_service_requester 
            ON service_requests(requester_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_service_assigned 
            ON service_requests(assigned_to)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_fulfillment_status 
            ON fulfillment_requests(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_fulfillment_archived 
            ON fulfillment_requests(is_archived)
        """)
        
        cursor.close()
        print("✓ Fulfillment schema initialized")


def inventory_db():
    """
    DEPRECATED: Legacy compatibility function.
    Returns a connection but caller must manage it properly.
    
    New code should use: with get_db_connection("fulfillment") as conn:
    """
    return get_db_connection("fulfillment").__enter__()


def insights_db():
    """
    DEPRECATED: Legacy compatibility function.
    Returns a connection but caller must manage it properly.
    
    New code should use: with get_db_connection("fulfillment") as conn:
    """
    return get_db_connection("fulfillment").__enter__()