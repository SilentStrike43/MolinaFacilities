# migrate_appadmin.py
import sqlite3
import json

# Source database (old)
auth_db = sqlite3.connect("app/data/auth.sqlite")
auth_db.row_factory = sqlite3.Row

# Target database (new)
users_db = sqlite3.connect("app/modules/users/data/users.sqlite")
users_db.row_factory = sqlite3.Row

# Get AppAdmin from auth.sqlite
admin = auth_db.execute("SELECT * FROM users WHERE username='AppAdmin'").fetchone()

if admin:
    # Check if already exists
    existing = users_db.execute("SELECT id FROM users WHERE username='AppAdmin'").fetchone()
    
    if existing:
        print("AppAdmin already exists in users.sqlite")
        print(f"ID: {existing['id']}")
    else:
        # Insert into users.sqlite
        users_db.execute("""
            INSERT INTO users (username, password_hash, caps, is_admin, is_sysadmin)
            VALUES (?, ?, ?, ?, ?)
        """, (
            admin['username'],
            admin['password_hash'],
            admin['caps'],
            admin['is_admin'],
            admin['is_sysadmin']
        ))
        users_db.commit()
        print("✅ AppAdmin migrated successfully!")
        
        # Get new ID
        new_admin = users_db.execute("SELECT * FROM users WHERE username='AppAdmin'").fetchone()
        print(f"New ID in users.sqlite: {new_admin['id']}")
else:
    print("❌ AppAdmin not found in auth.sqlite")

auth_db.close()
users_db.close()