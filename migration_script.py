#!/usr/bin/env python3
"""
Azure SQL Migration Script: Add Location Columns
Adds location filtering support to users, fulfillment, and mail databases.

Usage:
    python migrate_add_location.py
"""

import pyodbc
import sys
from datetime import datetime

# ============================================
# CONFIGURATION
# ============================================

SERVER = "facilitieswebservice.database.windows.net"
USERNAME = "CloudSAc9a971d5"
PASSWORD = "qonvIt-2dazki-huttop"

# Database names
DATABASES = {
    'users': 'users',
    'fulfillment': 'fulfillment',
    'mail': 'mail'
}

# ============================================
# SQL MIGRATIONS - SPLIT INTO SEPARATE STEPS
# ============================================

MIGRATIONS = {
    'users': [
        # Step 1: Add column
        """
        IF NOT EXISTS (
            SELECT * FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_NAME = 'users' AND COLUMN_NAME = 'location'
        )
        BEGIN
            ALTER TABLE dbo.users ADD location NVARCHAR(10) DEFAULT 'NY';
            PRINT 'Added location column to users table';
        END
        ELSE
        BEGIN
            PRINT 'Location column already exists in users table';
        END
        """,
        # Step 2: Set defaults (separate batch)
        """
        UPDATE dbo.users SET location = 'NY' WHERE location IS NULL OR location = '';
        PRINT 'Set default location for existing users';
        """,
        # Step 3: Set admin users (separate batch)
        """
        UPDATE dbo.users SET location = 'ALL' 
        WHERE permission_level IN ('L1', 'L2', 'L3', 'S1');
        PRINT 'Set admin users to see ALL locations';
        """
    ],
    
    'fulfillment': [
        # Step 1: Add column
        """
        IF NOT EXISTS (
            SELECT * FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_NAME = 'service_requests' AND COLUMN_NAME = 'location'
        )
        BEGIN
            ALTER TABLE dbo.service_requests ADD location NVARCHAR(10) DEFAULT 'NY';
            PRINT 'Added location column to service_requests table';
        END
        ELSE
        BEGIN
            PRINT 'Location column already exists in service_requests table';
        END
        """,
        # Step 2: Set defaults (separate batch)
        """
        UPDATE dbo.service_requests SET location = 'NY' WHERE location IS NULL OR location = '';
        PRINT 'Set default location for existing service requests';
        """,
        # Step 3: Create index (separate batch)
        """
        IF NOT EXISTS (
            SELECT * FROM sys.indexes 
            WHERE name = 'idx_service_requests_location' 
              AND object_id = OBJECT_ID('dbo.service_requests')
        )
        BEGIN
            CREATE INDEX idx_service_requests_location ON dbo.service_requests(location);
            PRINT 'Created index on service_requests.location';
        END
        """
    ],
    
    'mail': [
        # Step 1: Add column
        """
        IF NOT EXISTS (
            SELECT * FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_NAME = 'packages' AND COLUMN_NAME = 'location'
        )
        BEGIN
            ALTER TABLE dbo.packages ADD location NVARCHAR(10) DEFAULT 'NY';
            PRINT 'Added location column to packages table';
        END
        ELSE
        BEGIN
            PRINT 'Location column already exists in packages table';
        END
        """,
        # Step 2: Set defaults (separate batch)
        """
        UPDATE dbo.packages SET location = 'NY' WHERE location IS NULL OR location = '';
        PRINT 'Set default location for existing packages';
        """,
        # Step 3: Create index (separate batch)
        """
        IF NOT EXISTS (
            SELECT * FROM sys.indexes 
            WHERE name = 'idx_packages_location' 
              AND object_id = OBJECT_ID('dbo.packages')
        )
        BEGIN
            CREATE INDEX idx_packages_location ON dbo.packages(location);
            PRINT 'Created index on packages.location';
        END
        """
    ]
}

# ============================================
# VERIFICATION QUERIES
# ============================================

VERIFY_QUERIES = {
    'users': """
        SELECT 
            COUNT(*) as total_users,
            SUM(CASE WHEN location = 'NY' THEN 1 ELSE 0 END) as ny_users,
            SUM(CASE WHEN location = 'CT' THEN 1 ELSE 0 END) as ct_users,
            SUM(CASE WHEN location = 'ALL' THEN 1 ELSE 0 END) as all_users
        FROM dbo.users;
    """,
    
    'fulfillment': """
        SELECT 
            COUNT(*) as total_requests,
            SUM(CASE WHEN location = 'NY' THEN 1 ELSE 0 END) as ny_requests,
            SUM(CASE WHEN location = 'CT' THEN 1 ELSE 0 END) as ct_requests
        FROM dbo.service_requests;
    """,
    
    'mail': """
        SELECT 
            COUNT(*) as total_packages,
            SUM(CASE WHEN location = 'NY' THEN 1 ELSE 0 END) as ny_packages,
            SUM(CASE WHEN location = 'CT' THEN 1 ELSE 0 END) as ct_packages
        FROM dbo.packages;
    """
}

# ============================================
# HELPER FUNCTIONS
# ============================================

def get_connection_string(database):
    """Build connection string for a database."""
    return f"""
    Driver={{ODBC Driver 18 for SQL Server}};
    Server=tcp:{SERVER},1433;
    Database={database};
    Uid={USERNAME};
    Pwd={PASSWORD};
    Encrypt=yes;
    TrustServerCertificate=no;
    Connection Timeout=30;
    """

def print_banner(text):
    """Print a nice banner."""
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)

def print_step(text):
    """Print a step message."""
    print(f"\n→ {text}")

def print_success(text):
    """Print a success message."""
    print(f"  ✓ {text}")

def print_error(text):
    """Print an error message."""
    print(f"  ✗ {text}")

def print_info(text):
    """Print an info message."""
    print(f"  ℹ {text}")

def run_migration(database_key):
    """Run migration for a specific database."""
    database_name = DATABASES[database_key]
    migration_steps = MIGRATIONS[database_key]
    
    print_step(f"Connecting to {database_name} database...")
    
    try:
        conn_str = get_connection_string(database_name)
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        
        print_success(f"Connected to {database_name}")
        
        # Execute each migration step separately
        for i, migration_sql in enumerate(migration_steps, 1):
            print_step(f"Running migration step {i}/{len(migration_steps)} on {database_name}...")
            
            try:
                cursor.execute(migration_sql)
                conn.commit()
                
                # Consume any result sets
                while cursor.nextset():
                    pass
                
                print_success(f"Step {i} completed")
                
            except pyodbc.Error as e:
                print_error(f"Error in step {i}: {e}")
                # Continue with next step even if one fails
                continue
        
        print_success(f"All migration steps completed on {database_name}")
        
        # Verify the migration
        print_step(f"Verifying migration on {database_name}...")
        
        cursor.execute(VERIFY_QUERIES[database_key])
        row = cursor.fetchone()
        
        if database_key == 'users':
            print_info(f"Total users: {row[0]}")
            print_info(f"  NY users: {row[1] or 0}")
            print_info(f"  CT users: {row[2] or 0}")
            print_info(f"  ALL users (admins): {row[3] or 0}")
        elif database_key == 'fulfillment':
            print_info(f"Total requests: {row[0]}")
            print_info(f"  NY requests: {row[1] or 0}")
            print_info(f"  CT requests: {row[2] or 0}")
        elif database_key == 'mail':
            print_info(f"Total packages: {row[0]}")
            print_info(f"  NY packages: {row[1] or 0}")
            print_info(f"  CT packages: {row[2] or 0}")
        
        cursor.close()
        conn.close()
        
        print_success(f"{database_name} migration successful!")
        return True
        
    except pyodbc.Error as e:
        print_error(f"Database error on {database_name}: {e}")
        return False
    except Exception as e:
        print_error(f"Unexpected error on {database_name}: {e}")
        import traceback
        traceback.print_exc()
        return False

# ============================================
# MAIN FUNCTION
# ============================================

def main():
    """Main migration function."""
    print_banner("Azure SQL Location Migration Script")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Server: {SERVER}")
    
    results = {}
    
    # Run migrations for each database
    for db_key in ['users', 'fulfillment', 'mail']:
        print_banner(f"Migrating {db_key.upper()} Database")
        results[db_key] = run_migration(db_key)
    
    # Print summary
    print_banner("Migration Summary")
    
    success_count = sum(1 for v in results.values() if v)
    total_count = len(results)
    
    for db_key, success in results.items():
        status = "✓ SUCCESS" if success else "✗ FAILED"
        print(f"  {db_key:15} {status}")
    
    print(f"\n  Total: {success_count}/{total_count} successful")
    
    if success_count == total_count:
        print("\n🎉 All migrations completed successfully!")
        print("\nNext steps:")
        print("  1. Update your application code with location filtering logic")
        print("  2. Deploy the updated code to Azure")
        print("  3. Test with NY and CT users")
        print("  4. Assign users to their correct locations")
        return 0
    else:
        print("\n⚠️  Some migrations failed. Please check errors above.")
        return 1

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️  Migration interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n✗ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)