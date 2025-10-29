"""
Initialize all Azure SQL database schemas
Run this once to create all required tables
"""
# Load environment variables FIRST
from dotenv import load_dotenv
load_dotenv()

from app.core.database import get_db_connection

def init_user_schema():
    """Initialize or update users database schema"""
    print("\n🔧 Checking/Updating USERS database schema...")
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        # Create deletion_requests table
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'deletion_requests')
            BEGIN
                CREATE TABLE deletion_requests (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    user_id INT NOT NULL,
                    reason NVARCHAR(MAX),
                    status NVARCHAR(50) DEFAULT 'pending',
                    requested_at DATETIME2 DEFAULT GETUTCDATE(),
                    approved_by INT,
                    approved_at DATETIME2,
                    rejection_reason NVARCHAR(MAX),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
                CREATE INDEX idx_deletion_requests_status ON deletion_requests(status, requested_at DESC)
            END
        """)
        conn.commit()
        print("  ✓ Created/verified deletion_requests table")
        
        # Create user_elevation_history table
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'user_elevation_history')
            BEGIN
                CREATE TABLE user_elevation_history (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    user_id INT NOT NULL,
                    elevated_by INT NOT NULL,
                    old_level NVARCHAR(50),
                    new_level NVARCHAR(50) NOT NULL,
                    old_permissions NVARCHAR(MAX),
                    new_permissions NVARCHAR(MAX),
                    reason NVARCHAR(MAX),
                    elevated_at DATETIME2 DEFAULT GETUTCDATE(),
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (elevated_by) REFERENCES users(id)
                )
                CREATE INDEX idx_elevation_history_user ON user_elevation_history(user_id, elevated_at DESC)
            END
        """)
        conn.commit()
        print("  ✓ Created/verified user_elevation_history table")
        
        # Check if audit_logs exists and has the right columns
        cursor.execute("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_NAME = 'audit_logs' AND COLUMN_NAME = 'ts_utc'
        """)
        has_ts_utc = cursor.fetchone()[0] > 0
        
        if not has_ts_utc:
            print("  ⚠️ Recreating audit_logs table with correct schema...")
            
            # Drop and recreate
            cursor.execute("IF OBJECT_ID('audit_logs', 'U') IS NOT NULL DROP TABLE audit_logs")
            conn.commit()
            
            cursor.execute("""
                CREATE TABLE audit_logs (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    user_id INT NOT NULL,
                    username NVARCHAR(255) NOT NULL,
                    action NVARCHAR(255) NOT NULL,
                    module NVARCHAR(255) NOT NULL,
                    details NVARCHAR(MAX),
                    target_user_id INT,
                    target_username NVARCHAR(255),
                    permission_level NVARCHAR(50),
                    ip_address NVARCHAR(50),
                    user_agent NVARCHAR(MAX),
                    session_id NVARCHAR(255),
                    ts_utc DATETIME2 DEFAULT GETUTCDATE()
                )
                CREATE INDEX idx_audit_logs_user ON audit_logs(user_id, ts_utc DESC)
                CREATE INDEX idx_audit_logs_action ON audit_logs(action, ts_utc DESC)
                CREATE INDEX idx_audit_logs_module ON audit_logs(module, ts_utc DESC)
            """)
            conn.commit()
            print("  ✓ Recreated audit_logs table")
        else:
            print("  ✓ audit_logs table schema is correct")
        
        cursor.close()
        print("✓ USERS database schema updated")

def init_send_schema():
    """Initialize send database schema"""
    print("\n🔧 Initializing SEND database...")
    
    with get_db_connection("send") as conn:
        cursor = conn.cursor()
        
        # Counters table
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'counters')
            BEGIN
                CREATE TABLE counters (
                    name NVARCHAR(255) PRIMARY KEY,
                    value INT NOT NULL DEFAULT 0
                )
            END
        """)
        conn.commit()
        print("  ✓ Created/verified counters table")
        
        # Package manifest table - THE MAIN TABLE FOR INSIGHTS
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'package_manifest')
            BEGIN
                CREATE TABLE package_manifest (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    checkin_date DATE,
                    checkin_id NVARCHAR(50),
                    package_type NVARCHAR(50),
                    package_id NVARCHAR(50),
                    recipient_name NVARCHAR(255),
                    recipient_address NVARCHAR(MAX),
                    tracking_number NVARCHAR(255),
                    submitter_name NVARCHAR(255),
                    location NVARCHAR(10),
                    status NVARCHAR(50) DEFAULT 'queued',
                    ts_utc DATETIME2 DEFAULT GETUTCDATE()
                )
                CREATE INDEX idx_package_manifest_date ON package_manifest(checkin_date DESC)
                CREATE INDEX idx_package_manifest_location ON package_manifest(location)
            END
        """)
        conn.commit()
        print("  ✓ Created/verified package_manifest table")
        
        # Print jobs table (legacy)
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'print_jobs')
            BEGIN
                CREATE TABLE print_jobs (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    ts_utc DATETIME2 DEFAULT GETUTCDATE(),
                    module NVARCHAR(50),
                    job_type NVARCHAR(50),
                    payload NVARCHAR(MAX),
                    checkin_date DATE,
                    checkin_id NVARCHAR(50),
                    package_type NVARCHAR(50),
                    package_id NVARCHAR(50),
                    recipient_name NVARCHAR(255),
                    tracking_number NVARCHAR(255),
                    status NVARCHAR(50),
                    printer NVARCHAR(255),
                    template NVARCHAR(255)
                )
            END
        """)
        conn.commit()
        print("  ✓ Created/verified print_jobs table")
        
        # Cache table for tracking
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'cache')
            BEGIN
                CREATE TABLE cache (
                    tracking NVARCHAR(255) PRIMARY KEY,
                    carrier NVARCHAR(50),
                    payload NVARCHAR(MAX),
                    updated DATETIME2 DEFAULT GETUTCDATE()
                )
            END
        """)
        conn.commit()
        print("  ✓ Created/verified cache table")
        
        cursor.close()
        print("✓ SEND database initialized")


def init_inventory_schema():
    """Initialize inventory database schema"""
    print("\n🔧 Initializing INVENTORY database...")
    
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        
        # Get all foreign key constraints referencing assets table
        cursor.execute("""
            SELECT fk.name, OBJECT_NAME(fk.parent_object_id) AS table_name
            FROM sys.foreign_keys fk
            WHERE fk.referenced_object_id = OBJECT_ID('assets')
        """)
        fk_constraints = cursor.fetchall()
        
        # Drop all foreign key constraints
        for fk in fk_constraints:
            fk_name = fk[0]
            table_name = fk[1]
            print(f"  Dropping FK constraint: {fk_name} on {table_name}")
            cursor.execute(f"ALTER TABLE {table_name} DROP CONSTRAINT {fk_name}")
            conn.commit()
        
        # Now drop tables in order
        cursor.execute("IF OBJECT_ID('asset_ledger', 'U') IS NOT NULL DROP TABLE asset_ledger")
        conn.commit()
        
        cursor.execute("IF OBJECT_ID('assets', 'U') IS NOT NULL DROP TABLE assets")
        conn.commit()
        
        # Recreate assets table with CORRECT column names
        cursor.execute("""
            CREATE TABLE assets (
                id INT IDENTITY(1,1) PRIMARY KEY,
                sku NVARCHAR(50) UNIQUE,
                product NVARCHAR(500),
                manufacturer NVARCHAR(255),
                part_number NVARCHAR(255),
                serial_number NVARCHAR(255),
                uom NVARCHAR(20) DEFAULT 'EA',
                location NVARCHAR(255),
                qty_on_hand INT DEFAULT 0,
                pii NVARCHAR(MAX),
                notes NVARCHAR(MAX),
                status NVARCHAR(50) DEFAULT 'active',
                created_at DATETIME2 DEFAULT GETUTCDATE()
            )
        """)
        conn.commit()
        print("  ✓ Created assets table")
        
        # Recreate asset ledger table
        cursor.execute("""
            CREATE TABLE asset_ledger (
                id INT IDENTITY(1,1) PRIMARY KEY,
                asset_id INT NOT NULL,
                action NVARCHAR(50) NOT NULL,
                qty INT NOT NULL,
                username NVARCHAR(255),
                note NVARCHAR(MAX),
                ts_utc DATETIME2 DEFAULT GETUTCDATE(),
                FOREIGN KEY (asset_id) REFERENCES assets(id)
            )
        """)
        conn.commit()
        print("  ✓ Created asset_ledger table")
        
        # Inventory reports table (don't drop this one - it might have data)
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'inventory_reports')
            BEGIN
                CREATE TABLE inventory_reports (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    checkin_date DATE,
                    inventory_id INT,
                    item_type NVARCHAR(255),
                    manufacturer NVARCHAR(255),
                    product_name NVARCHAR(500),
                    submitter_name NVARCHAR(255),
                    notes NVARCHAR(MAX),
                    part_number NVARCHAR(255),
                    serial_number NVARCHAR(255),
                    count INT,
                    location NVARCHAR(255),
                    status NVARCHAR(50) DEFAULT 'completed',
                    ts_utc DATETIME2 DEFAULT GETUTCDATE()
                )
            END
        """)
        conn.commit()
        print("  ✓ Created/verified inventory_reports table")
        
        cursor.close()
        print("✓ INVENTORY database initialized")


def init_fulfillment_schema():
    """Initialize fulfillment database schema"""
    print("\n🔧 Initializing FULFILLMENT database...")
    
    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()
        
        # Check if service_requests has is_archived column
        cursor.execute("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_NAME = 'service_requests' AND COLUMN_NAME = 'is_archived'
        """)
        has_is_archived = cursor.fetchone()[0] > 0
        
        if not has_is_archived:
            print("  ⚠️ Adding missing columns to service_requests...")
            
            # Add missing columns
            try:
                cursor.execute("ALTER TABLE service_requests ADD is_archived BIT DEFAULT 0")
                conn.commit()
                print("  ✓ Added is_archived column")
            except:
                pass
            
            try:
                cursor.execute("ALTER TABLE service_requests ADD completed_at DATETIME2")
                conn.commit()
                print("  ✓ Added completed_at column")
            except:
                pass
        
        # Service requests table (ensure it exists with all columns)
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'service_requests')
            BEGIN
                CREATE TABLE service_requests (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    requester_id INT,
                    requester_name NVARCHAR(255),
                    title NVARCHAR(500),
                    description NVARCHAR(MAX),
                    request_type NVARCHAR(50) DEFAULT 'general',
                    status NVARCHAR(50) DEFAULT 'pending',
                    location NVARCHAR(10) DEFAULT 'NY',
                    is_archived BIT DEFAULT 0,
                    created_at DATETIME2 DEFAULT GETUTCDATE(),
                    completed_at DATETIME2
                )
            END
        """)
        conn.commit()
        print("  ✓ Created/verified service_requests table")
        
        # Fulfillment requests table (legacy)
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'fulfillment_requests')
            BEGIN
                CREATE TABLE fulfillment_requests (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    requester_id INT,
                    requester_name NVARCHAR(255),
                    description NVARCHAR(MAX),
                    date_submitted DATE DEFAULT CAST(GETDATE() AS DATE),
                    date_due DATE,
                    total_pages INT,
                    status NVARCHAR(50) DEFAULT 'Received',
                    assigned_staff_id INT,
                    assigned_staff_name NVARCHAR(255),
                    options_json NVARCHAR(MAX),
                    notes NVARCHAR(MAX),
                    is_archived BIT DEFAULT 0,
                    completed_at DATETIME2,
                    ts_utc DATETIME2 DEFAULT GETUTCDATE()
                )
            END
        """)
        conn.commit()
        print("  ✓ Created/verified fulfillment_requests table")
        
        # Fulfillment files table
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'fulfillment_files')
            BEGIN
                CREATE TABLE fulfillment_files (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    request_id INT NOT NULL,
                    orig_name NVARCHAR(255),
                    stored_name NVARCHAR(255),
                    ext NVARCHAR(50),
                    bytes INT,
                    ok BIT DEFAULT 1,
                    ts_utc DATETIME2 DEFAULT GETUTCDATE(),
                    FOREIGN KEY(request_id) REFERENCES fulfillment_requests(id)
                )
            END
        """)
        conn.commit()
        print("  ✓ Created/verified fulfillment_files table")
        
        cursor.close()
        print("✓ FULFILLMENT database initialized")

if __name__ == "__main__":
    print("=" * 70)
    print("INITIALIZING AZURE SQL DATABASE SCHEMAS")
    print("=" * 70)
    
    try:
        init_user_schema()  # ADD THIS LINE
        init_send_schema()
        init_inventory_schema()
        init_fulfillment_schema()
        
        print("\n" + "=" * 70)
        print("✅ ALL SCHEMAS INITIALIZED SUCCESSFULLY!")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()