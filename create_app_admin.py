#!/usr/bin/env python3
"""
create_app_admin.py
Fix the AppAdmin account with full system privileges
Run this from the project root: python create_app_admin.py
"""

import sqlite3
import json
import os
from werkzeug.security import generate_password_hash

# Path to auth database
AUTH_DB = os.path.join(os.path.dirname(__file__), "app", "data", "auth.sqlite")

def fix_app_admin():
    """Fix the AppAdmin account with full privileges."""
    
    if not os.path.exists(AUTH_DB):
        print(f"❌ Database not found at: {AUTH_DB}")
        print("Make sure you're running this from the project root directory (C:\\BTManifest)")
        return
    
    con = sqlite3.connect(AUTH_DB)
    con.row_factory = sqlite3.Row
    
    # Configuration
    USERNAME = "AppAdmin"
    PASSWORD = "AppAdmin2025!"  # You can change this
    
    # Check if account exists
    existing = con.execute("SELECT * FROM users WHERE username=?", (USERNAME,)).fetchone()
    
    if not existing:
        print(f"❌ User '{USERNAME}' not found in database!")
        print("\nAvailable users:")
        users = con.execute("SELECT id, username FROM users").fetchall()
        for u in users:
            print(f"  - {u['username']} (ID: {u['id']})")
        con.close()
        return
    
    print(f"✓ Found user '{USERNAME}' (ID: {existing['id']})")
    print("\nCurrent settings:")
    print(f"  - is_admin: {existing['is_admin']}")
    print(f"  - is_sysadmin: {existing['is_sysadmin']}")
    
    try:
        caps = json.loads(existing.get("caps", "{}") or "{}")
        print(f"  - Capabilities: {list(caps.keys())}")
    except:
        caps = {}
        print(f"  - Capabilities: (none)")
    
    # Update the account with FULL privileges
    password_hash = generate_password_hash(PASSWORD)
    
    # ALL capabilities
    new_caps = {
        "is_system": True,           # Special App Developer flag
        "can_send": True,            # Shipping module
        "can_asset": True,           # Inventory/Asset management
        "can_insights": True,        # Insights/Reports
        "can_users": True,           # User management
        "can_fulfillment_staff": True,   # Fulfillment staff access
        "can_fulfillment_customer": True,  # Fulfillment customer access
        "can_inventory": True,       # Inventory ledger
    }
    
    con.execute("""
        UPDATE users 
        SET password_hash=?, 
            is_admin=1, 
            is_sysadmin=1, 
            caps=?
        WHERE username=?
    """, (password_hash, json.dumps(new_caps), USERNAME))
    
    con.commit()
    
    # Verify update
    updated = con.execute("SELECT * FROM users WHERE username=?", (USERNAME,)).fetchone()
    con.close()
    
    print("\n" + "="*80)
    print("✅ APP ADMIN ACCOUNT UPDATED SUCCESSFULLY")
    print("="*80)
    print(f"Username:      {USERNAME}")
    print(f"Password:      {PASSWORD}")
    print(f"User ID:       {updated['id']}")
    print(f"Admin:         {'✓' if updated['is_admin'] else '✗'}")
    print(f"SysAdmin:      {'✓' if updated['is_sysadmin'] else '✗'}")
    print(f"Capabilities:  {len(new_caps)} permissions granted")
    print("="*80)
    
    print("\n📋 Granted Capabilities:")
    for cap, value in new_caps.items():
        if value:
            print(f"  ✓ {cap}")
    
    print("\n⚠️  NEXT STEPS:")
    print("1. Restart your Flask app: python -m app.app")
    print("2. Log out from the browser (if logged in)")
    print("3. Log back in with:")
    print(f"   Username: {USERNAME}")
    print(f"   Password: {PASSWORD}")
    print("4. All modules should now be visible!")
    print("\n🔐 SECURITY: Change this password after first login!")
    print("="*80)

if __name__ == "__main__":
    print("\n🔧 Fixing AppAdmin Account...\n")
    try:
        fix_app_admin()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        print("\nIf the database is locked, stop your Flask app first!")