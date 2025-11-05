# fix_send_schema.py
"""Fix Send database schema - add missing columns"""

from app.core.database import get_db_connection

print("🔧 Fixing Send database schema...")

with get_db_connection("send") as conn:
    cursor = conn.cursor()
    
    # Add missing columns
    try:
        cursor.execute("ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS recipient VARCHAR(255)")
        print("✅ Added 'recipient' column")
    except Exception as e:
        print(f"⚠️  recipient: {e}")
    
    try:
        cursor.execute("ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS ts_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        print("✅ Added 'ts_utc' column")
    except Exception as e:
        print(f"⚠️  ts_utc: {e}")
    
    try:
        cursor.execute("ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS checked_in_by VARCHAR(255)")
        print("✅ Added 'checked_in_by' column")
    except Exception as e:
        print(f"⚠️  checked_in_by: {e}")
    
    # Create index on recipient
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_package_recipient ON package_manifest(recipient)")
        print("✅ Created index on 'recipient'")
    except Exception as e:
        print(f"⚠️  index: {e}")
    
    cursor.close()
    print("\n✅ Send schema fixed!")

print("🎉 You can now use the Send module!")