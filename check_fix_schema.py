from dotenv import load_dotenv
load_dotenv()

from app.core.database import get_db_connection

def check_and_fix_fulfillment_schema():
    """Check fulfillment database schema and fix issues."""
    
    print("="*80)
    print("FULFILLMENT DATABASE SCHEMA CHECK & FIX")
    print("="*80)
    
    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()
        
        # Get all tables
        print("\n📋 EXISTING TABLES:")
        cursor.execute("""
            SELECT TABLE_NAME 
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """)
        tables = [row[0] for row in cursor.fetchall()]
        
        for table in tables:
            print(f"\n  📦 {table}")
            cursor.execute("""
                SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME = ?
                ORDER BY ORDINAL_POSITION
            """, (table,))
            columns = cursor.fetchall()
            for col in columns:
                nullable = "NULL" if col[2] == "YES" else "NOT NULL"
                default = f" DEFAULT {col[3]}" if col[3] else ""
                print(f"    • {col[0]}: {col[1]} {nullable}{default}")
        
        print("\n" + "="*80)
        print("FIXING SCHEMA...")
        print("="*80)
        
        # Fix service_requests table
        print("\n🔧 Fixing service_requests table...")
        if 'service_requests' in tables:
            # Check if requester_id exists
            cursor.execute("""
                SELECT COUNT(*) 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME = 'service_requests' 
                AND COLUMN_NAME = 'requester_id'
            """)
            has_requester_id = cursor.fetchone()[0] > 0
            
            if not has_requester_id:
                print("  ✓ Adding requester_id column...")
                cursor.execute("""
                    ALTER TABLE service_requests 
                    ADD requester_id INT NULL
                """)
                conn.commit()
            
            # Check if title exists
            cursor.execute("""
                SELECT COUNT(*) 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME = 'service_requests' 
                AND COLUMN_NAME = 'title'
            """)
            has_title = cursor.fetchone()[0] > 0
            
            if not has_title:
                print("  ✓ Adding title column...")
                cursor.execute("""
                    ALTER TABLE service_requests 
                    ADD title NVARCHAR(255) NULL
                """)
                conn.commit()
            
            # Check if request_type exists
            cursor.execute("""
                SELECT COUNT(*) 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME = 'service_requests' 
                AND COLUMN_NAME = 'request_type'
            """)
            has_request_type = cursor.fetchone()[0] > 0
            
            if not has_request_type:
                print("  ✓ Adding request_type column...")
                cursor.execute("""
                    ALTER TABLE service_requests 
                    ADD request_type NVARCHAR(50) DEFAULT 'fulfillment' NOT NULL
                """)
                conn.commit()
        else:
            print("  ✓ Creating service_requests table from scratch...")
            cursor.execute("""
                CREATE TABLE service_requests (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    requester_id INT NULL,
                    requester_name NVARCHAR(255) NOT NULL,
                    title NVARCHAR(255) NULL,
                    description NVARCHAR(MAX) NOT NULL,
                    request_type NVARCHAR(50) DEFAULT 'fulfillment' NOT NULL,
                    location NVARCHAR(10) NOT NULL,
                    status NVARCHAR(50) DEFAULT 'pending' NOT NULL,
                    is_archived BIT DEFAULT 0 NOT NULL,
                    created_at DATETIME2 DEFAULT GETUTCDATE() NOT NULL,
                    completed_at DATETIME2 NULL,
                    assigned_to INT NULL
                )
            """)
            conn.commit()
        
        # Fix fulfillment_requests table
        print("\n🔧 Fixing fulfillment_requests table...")
        if 'fulfillment_requests' not in tables:
            print("  ✓ Creating fulfillment_requests table...")
            cursor.execute("""
                CREATE TABLE fulfillment_requests (
                    id INT PRIMARY KEY,
                    requester_name NVARCHAR(255) NOT NULL,
                    description NVARCHAR(MAX) NOT NULL,
                    total_pages INT DEFAULT 0,
                    date_submitted DATE DEFAULT GETDATE() NOT NULL,
                    assigned_staff_name NVARCHAR(255) NULL,
                    completed_at DATETIME2 NULL,
                    status NVARCHAR(50) DEFAULT 'pending' NOT NULL,
                    is_archived BIT DEFAULT 0 NOT NULL,
                    FOREIGN KEY (id) REFERENCES service_requests(id)
                )
            """)
            conn.commit()
        
        # Fix fulfillment_files table
        print("\n🔧 Fixing fulfillment_files table...")
        if 'fulfillment_files' not in tables:
            print("  ✓ Creating fulfillment_files table...")
            cursor.execute("""
                CREATE TABLE fulfillment_files (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    request_id INT NOT NULL,
                    orig_name NVARCHAR(255) NOT NULL,
                    stored_name NVARCHAR(255) NOT NULL,
                    ext NVARCHAR(10) NULL,
                    bytes INT DEFAULT 0,
                    ok BIT DEFAULT 1,
                    uploaded_at DATETIME2 DEFAULT GETUTCDATE() NOT NULL,
                    FOREIGN KEY (request_id) REFERENCES service_requests(id)
                )
            """)
            conn.commit()
        
        cursor.close()
        
        print("\n" + "="*80)
        print("✅ SCHEMA CHECK & FIX COMPLETE!")
        print("="*80)
        
        # Show updated schema
        print("\n📋 UPDATED SCHEMA:")
        cursor = conn.cursor()
        cursor.execute("""
            SELECT TABLE_NAME 
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """)
        tables = [row[0] for row in cursor.fetchall()]
        
        for table in tables:
            print(f"\n  📦 {table}")
            cursor.execute("""
                SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME = ?
                ORDER BY ORDINAL_POSITION
            """, (table,))
            columns = cursor.fetchall()
            for col in columns:
                nullable = "NULL" if col[2] == "YES" else "NOT NULL"
                print(f"    • {col[0]}: {col[1]} {nullable}")
        
        cursor.close()

if __name__ == "__main__":
    check_and_fix_fulfillment_schema()