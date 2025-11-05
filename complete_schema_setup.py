# complete_schema_setup.py
"""
Complete database schema setup for PostgreSQL
Based on actual code usage from all modules
"""

from app.core.database import get_db_connection
import bcrypt

print("🔧 Creating COMPLETE database schema...\n")

# ========== CORE DATABASE ==========
print("📦 Setting up CORE database...")
with get_db_connection("core") as conn:
    cursor = conn.cursor()
    
    # USERS TABLE - Complete with all columns
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            instance_id INTEGER,
            username VARCHAR(255) UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            first_name VARCHAR(255),
            last_name VARCHAR(255),
            email VARCHAR(255),
            phone VARCHAR(50),
            department VARCHAR(255),
            position VARCHAR(255),
            permission_level VARCHAR(10) DEFAULT '',
            module_permissions TEXT DEFAULT '[]',
            location VARCHAR(50) DEFAULT 'NY',
            is_active BOOLEAN DEFAULT TRUE,
            caps TEXT DEFAULT '{}',
            elevated_by INTEGER,
            elevated_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by INTEGER,
            last_login_at TIMESTAMP,
            last_modified_at TIMESTAMP,
            last_modified_by INTEGER,
            deleted_at TIMESTAMP,
            deletion_approved_by INTEGER,
            deletion_requested_at TIMESTAMP,
            deletion_notes TEXT
        )
    """)
    
    # AUDIT_LOGS TABLE - Complete with all columns
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            username VARCHAR(255),
            action VARCHAR(255),
            module VARCHAR(100),
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ts_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            permission_level VARCHAR(10),
            ip_address VARCHAR(50),
            user_agent TEXT,
            session_id VARCHAR(255),
            instance_name VARCHAR(255),
            target_user_id INTEGER,
            target_username VARCHAR(255)
        )
    """)
    
    # DELETION_REQUESTS TABLE
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deletion_requests (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            requester_username VARCHAR(255),
            target_username VARCHAR(255),
            reason TEXT,
            status VARCHAR(50) DEFAULT 'pending',
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            approved_by INTEGER,
            approved_at TIMESTAMP,
            rejection_reason TEXT
        )
    """)
    
    # USER_ELEVATION_HISTORY TABLE
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_elevation_history (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            elevated_by INTEGER NOT NULL,
            old_level VARCHAR(10),
            new_level VARCHAR(10),
            from_level VARCHAR(10),
            to_level VARCHAR(10),
            old_permissions TEXT,
            new_permissions TEXT,
            reason TEXT,
            elevated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # INSTANCES TABLE (for Horizon multi-tenant)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS instances (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            subdomain VARCHAR(100) UNIQUE NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            features TEXT,
            settings TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_instance ON users(instance_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(ts_utc DESC)")
    
    cursor.close()
    print("✅ Core schema created!\n")

# ========== SEND DATABASE ==========
print("📦 Setting up SEND database...")
with get_db_connection("send") as conn:
    cursor = conn.cursor()
    
    # COUNTERS TABLE
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS counters (
            name VARCHAR(100) PRIMARY KEY,
            value INTEGER DEFAULT 0
        )
    """)
    
    # CACHE TABLE
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            tracking VARCHAR(255) PRIMARY KEY,
            carrier VARCHAR(50),
            payload TEXT,
            updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # PACKAGE_MANIFEST TABLE - Complete
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS package_manifest (
            id SERIAL PRIMARY KEY,
            instance_id INTEGER,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            tracking_number VARCHAR(255),
            recipient VARCHAR(255),
            recipient_name VARCHAR(255),
            recipient_dept VARCHAR(255),
            recipient_address TEXT,
            sender VARCHAR(255),
            submitter_name VARCHAR(255),
            package_type VARCHAR(100),
            carrier VARCHAR(100),
            num_pieces INTEGER DEFAULT 1,
            location VARCHAR(50) DEFAULT 'NY',
            status VARCHAR(50) DEFAULT 'received',
            notes TEXT,
            picked_up_at TIMESTAMP,
            picked_up_by VARCHAR(255),
            received_by VARCHAR(255),
            received_at TIMESTAMP,
            checked_in_by VARCHAR(255),
            checkin_date DATE,
            checkin_id VARCHAR(50),
            package_id VARCHAR(50),
            ts_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_package_tracking ON package_manifest(tracking_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_package_recipient ON package_manifest(recipient)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_package_status ON package_manifest(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_package_ts ON package_manifest(ts_utc DESC)")
    
    cursor.close()
    print("✅ Send schema created!\n")

# ========== INVENTORY DATABASE ==========
print("📦 Setting up INVENTORY database...")
with get_db_connection("inventory") as conn:
    cursor = conn.cursor()
    
    # ASSETS TABLE - Complete
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS assets (
            id SERIAL PRIMARY KEY,
            instance_id INTEGER,
            sku VARCHAR(255) UNIQUE NOT NULL,
            asset_name VARCHAR(255),
            product VARCHAR(255),
            category VARCHAR(100),
            uom VARCHAR(50) DEFAULT 'EA',
            quantity INTEGER DEFAULT 0,
            qty_on_hand INTEGER DEFAULT 0,
            location VARCHAR(100) DEFAULT 'NY',
            manufacturer VARCHAR(255),
            part_number VARCHAR(255),
            serial_number VARCHAR(255),
            pii VARCHAR(255),
            status VARCHAR(50) DEFAULT 'active',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # ASSET_LEDGER TABLE
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS asset_ledger (
            id SERIAL PRIMARY KEY,
            asset_id INTEGER NOT NULL,
            action VARCHAR(50) NOT NULL,
            qty INTEGER NOT NULL,
            username VARCHAR(255),
            note TEXT,
            ts_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # INVENTORY_TRANSACTIONS TABLE
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory_transactions (
            id SERIAL PRIMARY KEY,
            instance_id INTEGER,
            transaction_date DATE NOT NULL,
            transaction_type VARCHAR(50) NOT NULL,
            asset_id INTEGER,
            sku VARCHAR(100),
            item_type VARCHAR(255),
            manufacturer VARCHAR(255),
            product_name VARCHAR(255),
            submitter_name VARCHAR(255),
            quantity INTEGER NOT NULL,
            notes TEXT,
            part_number VARCHAR(255),
            serial_number VARCHAR(255),
            location VARCHAR(255),
            status VARCHAR(50) DEFAULT 'completed',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ts_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # INVENTORY_REPORTS TABLE (for insights)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory_reports (
            id SERIAL PRIMARY KEY,
            instance_id INTEGER,
            report_type VARCHAR(100),
            sku VARCHAR(255),
            asset_name VARCHAR(255),
            quantity_change INTEGER,
            new_quantity INTEGER,
            location VARCHAR(100),
            notes TEXT,
            performed_by VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ts_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_sku ON assets(sku)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ledger_asset ON asset_ledger(asset_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_date ON inventory_transactions(transaction_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reports_ts ON inventory_reports(ts_utc DESC)")
    
    cursor.close()
    print("✅ Inventory schema created!\n")

# ========== FULFILLMENT DATABASE ==========
print("📦 Setting up FULFILLMENT database...")
with get_db_connection("fulfillment") as conn:
    cursor = conn.cursor()
    
    # SERVICE_REQUESTS TABLE - Complete
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
            date_due DATE,
            completed_at TIMESTAMP,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ts_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # FULFILLMENT_REQUESTS TABLE (legacy compatibility)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fulfillment_requests (
            id SERIAL PRIMARY KEY,
            instance_id INTEGER,
            request_number VARCHAR(50) UNIQUE,
            service_id VARCHAR(100),
            requester TEXT,
            requester_name TEXT,
            requester_email VARCHAR(255),
            requester_dept VARCHAR(255),
            request_type VARCHAR(100),
            description TEXT,
            total_pages INTEGER,
            priority VARCHAR(50) DEFAULT 'normal',
            status VARCHAR(50) DEFAULT 'new',
            location VARCHAR(50) DEFAULT 'NY',
            staff VARCHAR(255),
            assigned_to VARCHAR(255),
            assigned_staff_name VARCHAR(255),
            is_archived BOOLEAN DEFAULT FALSE,
            date_submitted DATE DEFAULT CURRENT_DATE,
            date_due DATE,
            date_completed TIMESTAMP,
            completed_at TIMESTAMP,
            completed_utc TIMESTAMP,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ts_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_service_status ON service_requests(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_service_requester ON service_requests(requester_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fulfillment_status ON fulfillment_requests(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fulfillment_archived ON fulfillment_requests(is_archived)")
    
    cursor.close()
    print("✅ Fulfillment schema created!\n")

# ========== CREATE APPADMIN USER ==========
print("👤 Creating AppAdmin user...")
with get_db_connection("core") as conn:
    cursor = conn.cursor()
    
    # Check if exists
    cursor.execute("SELECT id FROM users WHERE username = 'AppAdmin'")
    exists = cursor.fetchone()
    
    if not exists:
        password_hash = bcrypt.hashpw(b'AppAdmin2025!', bcrypt.gensalt()).decode('utf-8')
        
        cursor.execute("""
            INSERT INTO users (username, password_hash, first_name, last_name, email, permission_level, location)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, ('AppAdmin', password_hash, 'App', 'Admin', 'admin@gridline.local', 'S1', 'ALL'))
        
        print("✅ AppAdmin user created!")
    else:
        print("✅ AppAdmin user already exists!")
    
    cursor.close()

print("\n🎉 Complete schema setup finished!")
print("\n📋 Summary:")
print("  ✅ Core database: users, audit_logs, deletion_requests, user_elevation_history, instances")
print("  ✅ Send database: counters, cache, package_manifest")
print("  ✅ Inventory database: assets, asset_ledger, inventory_transactions, inventory_reports")
print("  ✅ Fulfillment database: service_requests, fulfillment_requests")
print("  ✅ AppAdmin user ready")
print("\n🚀 Your application should now work completely!")