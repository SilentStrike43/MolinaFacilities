# app/core/schema_migrations.py
"""
Automated schema migration system - runs on app startup
Ensures all tables and columns exist with proper structure
"""

import logging
from app.core.database import get_db_connection, execute_script

logger = logging.getLogger(__name__)


def column_exists(conn, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) 
            FROM sys.columns 
            WHERE object_id = OBJECT_ID(?) AND name = ?
        """, (table_name, column_name))
        result = cursor.fetchone()[0]
        cursor.close()
        return result > 0
    except:
        return False


def table_exists(conn, table_name: str) -> bool:
    """Check if a table exists."""
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) 
            FROM sys.tables 
            WHERE name = ?
        """, (table_name,))
        result = cursor.fetchone()[0]
        cursor.close()
        return result > 0
    except:
        return False


def add_column_if_missing(conn, table_name: str, column_name: str, column_definition: str):
    """Add a column if it doesn't exist."""
    if not column_exists(conn, table_name, column_name):
        try:
            cursor = conn.cursor()
            sql = f"ALTER TABLE {table_name} ADD {column_name} {column_definition}"
            cursor.execute(sql)
            conn.commit()
            cursor.close()
            logger.info(f"   ✅ Added column {table_name}.{column_name}")
            return True
        except Exception as e:
            logger.warning(f"   ⚠️  Could not add {table_name}.{column_name}: {e}")
            return False
    return False


def migrate_send_database():
    """Migrate Send database schema."""
    logger.info("🔧 Checking Send database schema...")
    
    with get_db_connection("send") as conn:
        # Ensure counters table exists
        if not table_exists(conn, "counters"):
            logger.info("   Creating counters table...")
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE counters (
                    name NVARCHAR(100) PRIMARY KEY,
                    value INT NOT NULL DEFAULT 0
                )
            """)
            conn.commit()
            cursor.close()
            logger.info("   ✅ Created counters table")
        
        # Ensure package_manifest table exists
        if not table_exists(conn, "package_manifest"):
            logger.info("   Creating package_manifest table...")
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE package_manifest (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    checkin_date DATE,
                    checkin_id NVARCHAR(50),
                    package_type NVARCHAR(100),
                    package_id NVARCHAR(100) UNIQUE,
                    recipient_name NVARCHAR(255) NOT NULL,
                    recipient_address NVARCHAR(MAX),
                    tracking_number NVARCHAR(255),
                    carrier NVARCHAR(100),
                    submitter_name NVARCHAR(255),
                    location NVARCHAR(100),
                    status NVARCHAR(50) DEFAULT 'created',
                    created_by INT NOT NULL,
                    ts_utc DATETIME2 DEFAULT GETUTCDATE()
                )
                CREATE INDEX idx_manifest_package_id ON package_manifest(package_id)
                CREATE INDEX idx_manifest_checkin_date ON package_manifest(checkin_date)
                CREATE INDEX idx_manifest_location ON package_manifest(location)
                CREATE INDEX idx_manifest_ts_utc ON package_manifest(ts_utc)
            """)
            conn.commit()
            cursor.close()
            logger.info("   ✅ Created package_manifest table")
        else:
            # Table exists, check for missing columns
            added = False
            added |= add_column_if_missing(conn, "package_manifest", "carrier", "NVARCHAR(100)")
            added |= add_column_if_missing(conn, "package_manifest", "created_by", "INT NOT NULL DEFAULT 1")
            added |= add_column_if_missing(conn, "package_manifest", "submitter_name", "NVARCHAR(255)")
            added |= add_column_if_missing(conn, "package_manifest", "status", "NVARCHAR(50) DEFAULT 'created'")
            
            if not added:
                logger.info("   ✅ Send schema up to date")
        
        # Ensure cache table exists
        if not table_exists(conn, "cache"):
            logger.info("   Creating cache table...")
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE cache (
                    tracking NVARCHAR(255) PRIMARY KEY,
                    carrier NVARCHAR(100),
                    payload NVARCHAR(MAX),
                    updated DATETIME2 DEFAULT GETUTCDATE()
                )
                CREATE INDEX idx_cache_updated ON cache(updated)
            """)
            conn.commit()
            cursor.close()
            logger.info("   ✅ Created cache table")


def migrate_core_database():
    """Migrate Core database schema."""
    logger.info("🔧 Checking Core database schema...")
    
    with get_db_connection("core") as conn:
        # Add location column to users if missing
        added = add_column_if_missing(conn, "users", "location", "NVARCHAR(50) DEFAULT 'NY'")
        added |= add_column_if_missing(conn, "users", "module_permissions", "NVARCHAR(MAX) DEFAULT '[]'")
        added |= add_column_if_missing(conn, "users", "position", "NVARCHAR(255)")
        added |= add_column_if_missing(conn, "users", "last_modified_by", "INT")
        added |= add_column_if_missing(conn, "users", "last_modified_at", "DATETIME2")
        
        if not added:
            logger.info("   ✅ Core schema up to date")


def migrate_inventory_database():
    """Migrate Inventory database schema."""
    logger.info("🔧 Checking Inventory database schema...")
    
    with get_db_connection("inventory") as conn:
        # Add location column to assets if missing
        added = add_column_if_missing(conn, "assets", "location", "NVARCHAR(100) DEFAULT 'NY'")
        
        if not added:
            logger.info("   ✅ Inventory schema up to date")


def migrate_fulfillment_database():
    """Migrate Fulfillment database schema."""
    logger.info("🔧 Checking Fulfillment database schema...")
    
    with get_db_connection("fulfillment") as conn:
        # Check service_requests table
        if table_exists(conn, "service_requests"):
            added = add_column_if_missing(conn, "service_requests", "location", "NVARCHAR(100) DEFAULT 'NY'")
            
            if not added:
                logger.info("   ✅ Fulfillment schema up to date")
        else:
            logger.info("   ⚠️  service_requests table doesn't exist - run full schema init")


def run_all_migrations():
    """Run all database migrations."""
    logger.info("\n" + "=" * 70)
    logger.info("RUNNING AUTOMATED SCHEMA MIGRATIONS")
    logger.info("=" * 70)
    
    try:
        migrate_core_database()
        migrate_send_database()
        migrate_inventory_database()
        migrate_fulfillment_database()
        
        logger.info("\n" + "=" * 70)
        logger.info("✅ ALL MIGRATIONS COMPLETE")
        logger.info("=" * 70 + "\n")
        return True
        
    except Exception as e:
        logger.error(f"\n❌ MIGRATION FAILED: {e}\n", exc_info=True)
        return False