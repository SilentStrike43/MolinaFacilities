# app/modules/fulfillment/storage.py
"""
Fulfillment storage - PostgreSQL Edition
"""
# app/modules/fulfillment/storage.py
from app.core.database import get_db_connection

def ensure_schema():
    """Ensure fulfillment database schema exists."""
    
    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()
        
        # Create service_requests table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS service_requests (
                id SERIAL PRIMARY KEY,
                instance_id INTEGER,
                title VARCHAR(500),
                description TEXT,
                request_type VARCHAR(100),
                requester_id INTEGER NOT NULL,
                requester_name VARCHAR(255),
                location VARCHAR(50),
                status VARCHAR(50) DEFAULT 'pending',
                is_archived BOOLEAN DEFAULT FALSE,
                completed_at TIMESTAMP NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Create fulfillment_requests table with ALL columns
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fulfillment_requests (
                id SERIAL PRIMARY KEY,
                instance_id INTEGER,
                service_request_id INTEGER,
                description TEXT,
                date_submitted TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                date_due DATE,
                total_pages INTEGER DEFAULT 0,
                status VARCHAR(50) DEFAULT 'Received',
                options_json TEXT,
                notes TEXT,
                is_archived BOOLEAN DEFAULT FALSE,
                completed_at TIMESTAMP NULL,
                created_by_id INTEGER,
                created_by_name VARCHAR(255),
                completed_by_id INTEGER,
                completed_by_name VARCHAR(255),
                ts_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Create fulfillment_files table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fulfillment_files (
                id SERIAL PRIMARY KEY,
                request_id INTEGER NOT NULL,
                orig_name VARCHAR(255) NOT NULL,
                stored_name VARCHAR(255) NOT NULL,
                ext VARCHAR(50),
                bytes BIGINT DEFAULT 0,
                ok BOOLEAN DEFAULT TRUE,
                ts_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Add any missing columns to existing tables
        
        # service_requests missing columns
        cursor.execute("ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS instance_id INTEGER;")
        cursor.execute("ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS is_archived BOOLEAN DEFAULT FALSE;")
        cursor.execute("ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP NULL;")
        
        # fulfillment_requests missing columns
        cursor.execute("ALTER TABLE fulfillment_requests ADD COLUMN IF NOT EXISTS instance_id INTEGER;")
        cursor.execute("ALTER TABLE fulfillment_requests ADD COLUMN IF NOT EXISTS service_request_id INTEGER;")
        cursor.execute("ALTER TABLE fulfillment_requests ADD COLUMN IF NOT EXISTS options_json TEXT;")
        cursor.execute("ALTER TABLE fulfillment_requests ADD COLUMN IF NOT EXISTS notes TEXT;")
        cursor.execute("ALTER TABLE fulfillment_requests ADD COLUMN IF NOT EXISTS created_by_id INTEGER;")
        cursor.execute("ALTER TABLE fulfillment_requests ADD COLUMN IF NOT EXISTS created_by_name VARCHAR(255);")
        cursor.execute("ALTER TABLE fulfillment_requests ADD COLUMN IF NOT EXISTS completed_by_id INTEGER;")
        cursor.execute("ALTER TABLE fulfillment_requests ADD COLUMN IF NOT EXISTS completed_by_name VARCHAR(255);")
        cursor.execute("ALTER TABLE fulfillment_requests ADD COLUMN IF NOT EXISTS date_due DATE;")
        cursor.execute("ALTER TABLE fulfillment_requests ADD COLUMN IF NOT EXISTS total_pages INTEGER DEFAULT 0;")
        
        # Add foreign key constraints if they don't exist
        cursor.execute("""
            DO $$ 
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint 
                    WHERE conname = 'fk_fulfillment_service_request'
                ) THEN
                    ALTER TABLE fulfillment_requests
                    ADD CONSTRAINT fk_fulfillment_service_request 
                    FOREIGN KEY (service_request_id) 
                    REFERENCES service_requests(id) 
                    ON DELETE CASCADE;
                END IF;
            END $$;
        """)
        
        cursor.execute("""
            DO $$ 
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint 
                    WHERE conname = 'fk_fulfillment_files_request'
                ) THEN
                    ALTER TABLE fulfillment_files
                    ADD CONSTRAINT fk_fulfillment_files_request 
                    FOREIGN KEY (request_id) 
                    REFERENCES fulfillment_requests(id) 
                    ON DELETE CASCADE;
                END IF;
            END $$;
        """)
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_service_requests_archived ON service_requests(is_archived);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_service_requests_instance ON service_requests(instance_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fulfillment_requests_archived ON fulfillment_requests(is_archived);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fulfillment_files_request ON fulfillment_files(request_id);")
        
        conn.commit()
        cursor.close()
