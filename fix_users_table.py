from dotenv import load_dotenv
load_dotenv()

from app.core.database import get_db_connection

print("Checking and fixing users table schema...")

with get_db_connection("core") as conn:
    cursor = conn.cursor()
    
    # Get current columns
    cursor.execute("""
        SELECT COLUMN_NAME 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_NAME = 'users'
        ORDER BY ORDINAL_POSITION
    """)
    existing_columns = [row[0] for row in cursor.fetchall()]
    print(f"\nExisting columns: {existing_columns}\n")
    
    # Define columns that should exist
    required_columns = {
        'phone': 'NVARCHAR(50)',
        'department': 'NVARCHAR(255)',
        'position': 'NVARCHAR(255)',
        'created_utc': 'DATETIME2 DEFAULT GETUTCDATE()'
    }
    
    # Add missing columns
    for col_name, col_def in required_columns.items():
        if col_name not in existing_columns:
            print(f"Adding column: {col_name}")
            try:
                cursor.execute(f"ALTER TABLE users ADD {col_name} {col_def}")
                conn.commit()
                print(f"  ✓ Added {col_name}")
            except Exception as e:
                print(f"  ✗ Error adding {col_name}: {e}")
        else:
            print(f"  ✓ Column {col_name} already exists")
    
    cursor.close()
    print("\n✓ Users table schema updated!")