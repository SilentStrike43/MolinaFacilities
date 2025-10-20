# migrate_assets_schema.py
# Run this script ONCE to update your existing assets table
# Usage: python migrate_assets_schema.py

import sqlite3
import os

DB_PATH = os.path.join("app", "data", "assets.sqlite")

def migrate_assets_table():
    """Add new columns to existing assets table."""
    
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found: {DB_PATH}")
        print("The database will be created automatically when you first use the app.")
        return
    
    con = sqlite3.connect(DB_PATH)
    cursor = con.cursor()
    
    print("🔍 Checking current schema...")
    
    # Get current columns
    cursor.execute("PRAGMA table_info(assets)")
    columns = {row[1] for row in cursor.fetchall()}
    print(f"Current columns: {columns}")
    
    # Add missing columns
    migrations = []
    
    if "manufacturer" not in columns:
        migrations.append("ALTER TABLE assets ADD COLUMN manufacturer TEXT")
    
    if "part_number" not in columns:
        migrations.append("ALTER TABLE assets ADD COLUMN part_number TEXT")
    
    if "serial_number" not in columns:
        migrations.append("ALTER TABLE assets ADD COLUMN serial_number TEXT")
    
    if "pii" not in columns:
        migrations.append("ALTER TABLE assets ADD COLUMN pii TEXT")
    
    if "notes" not in columns:
        migrations.append("ALTER TABLE assets ADD COLUMN notes TEXT")
    
    if "status" not in columns:
        migrations.append("ALTER TABLE assets ADD COLUMN status TEXT DEFAULT 'active'")
    
    if "created_utc" not in columns:
        migrations.append("ALTER TABLE assets ADD COLUMN created_utc TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))")
    
    # Execute migrations
    if migrations:
        print(f"\n📝 Applying {len(migrations)} migrations...")
        for i, sql in enumerate(migrations, 1):
            try:
                cursor.execute(sql)
                print(f"  ✅ {i}. {sql}")
            except sqlite3.OperationalError as e:
                print(f"  ⚠️  {i}. Already exists or error: {e}")
        
        con.commit()
        print("\n✅ Migration completed successfully!")
    else:
        print("\n✅ Schema is already up to date!")
    
    # Verify final schema
    print("\n🔍 Final schema:")
    cursor.execute("PRAGMA table_info(assets)")
    for row in cursor.fetchall():
        print(f"  - {row[1]:20s} {row[2]:10s} {'NOT NULL' if row[3] else ''} {f'DEFAULT {row[4]}' if row[4] else ''}")
    
    # Update any NULL status values to 'active'
    cursor.execute("UPDATE assets SET status='active' WHERE status IS NULL OR status=''")
    updated = cursor.rowcount
    if updated > 0:
        print(f"\n📊 Updated {updated} assets with default status='active'")
        con.commit()
    
    con.close()
    print("\n🎉 Ready to use the new inventory system!")

if __name__ == "__main__":
    print("="*60)
    print("Asset Table Migration Script")
    print("="*60)
    migrate_assets_table()