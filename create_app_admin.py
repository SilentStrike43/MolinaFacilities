#!/usr/bin/env python3
"""
create_app_admin.py - Fixed Version
Creates/updates the AppAdmin account with full system privileges
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
    PASSWORD = "AppAdmin2025!"  # Change this for production!
    
    # Check if account exists
    existing = con.execute("SELECT * FROM users WHERE username=?", (USERNAME,)).fetchone()
    
    if not existing:
        print(f"❌ User '{USERNAME}' not found in database!")
        print("\n📋 Creating new AppAdmin user...")
        
        # Create new AppAdmin user
        password_hash = generate_password_hash(PASSWORD)
        new_caps = {
            "is_system": True,
            "can_send": True,
            "can_asset": True,
            "can_insights": True,
            "can_users": True,
            "can_fulfillment_staff": True,
            "can_fulfillment_customer": True,
            "can_inventory": True,
            # Legacy compatibility
            "inventory": True,
            "asset": True,
            "insights": True,
            "users": True,
            "fulfillment_staff": True,
            "fulfillment_customer": True,
        }
        
        con.execute("""
            INSERT INTO users (username, password_hash, is_admin, is_sysadmin, caps)
            VALUES (?, ?, 1, 1, ?)
        """, (USERNAME, password_hash, json.dumps(new_caps)))
        
        con.commit()
        print(f"✅ Created new AppAdmin user successfully!")
        
    else:
        print(f"✓ Found user '{USERNAME}' (ID: {existing['id']})")
        print("\n📋 Current settings:")
        print(f"  - is_admin: {existing['is_admin']}")
        print(f"  - is_sysadmin: {existing['is_sysadmin']}")
        
        try:
            caps = json.loads(existing.get("caps", "{}") or "{}")
            print(f"  - Current capabilities: {len(caps)} permissions")
        except:
            caps = {}
            print(f"  - Current capabilities: (none)")
        
        # Update the account with FULL privileges
        password_hash = generate_password_hash(PASSWORD)
        
        # ALL capabilities with both new and legacy names for compatibility
        new_caps = {
            "is_system": True,           # Special App Developer flag
            "can_send": True,            # Shipping module
            "can_asset": True,           # Inventory/Asset management
            "can_insights": True,        # Insights/Reports
            "can_users": True,           # User management
            "can_fulfillment_staff": True,   # Fulfillment staff access
            "can_fulfillment_customer": True,  # Fulfillment customer access
            "can_inventory": True,       # Inventory ledger
            # Legacy compatibility - keep old names too
            "inventory": True,
            "asset": True,
            "insights": True,
            "users": True,
            "fulfillment_staff": True,
            "fulfillment_customer": True,
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
        print(f"\n✅ Updated existing AppAdmin account!")
    
    # Verify update
    updated = con.execute("SELECT * FROM users WHERE username=?", (USERNAME,)).fetchone()
    
    # Also fix any other admin users to have proper capabilities
    print("\n📋 Checking other admin users...")
    other_admins = con.execute("SELECT id, username, caps FROM users WHERE is_admin=1 AND username!=?", (USERNAME,)).fetchall()
    
    for admin in other_admins:
        try:
            admin_caps = json.loads(admin["caps"] or "{}")
        except:
            admin_caps = {}
        
        # Ensure admins have at least the can_ versions
        updated_caps = False
        for old_key, new_key in [
            ("send", "can_send"),
            ("asset", "can_asset"),
            ("inventory", "can_inventory"),
            ("insights", "can_insights"),
            ("users", "can_users"),
            ("fulfillment_staff", "can_fulfillment_staff"),
            ("fulfillment_customer", "can_fulfillment_customer")
        ]:
            if old_key in admin_caps and new_key not in admin_caps:
                admin_caps[new_key] = admin_caps[old_key]
                updated_caps = True
        
        if updated_caps:
            con.execute("UPDATE users SET caps=? WHERE id=?", (json.dumps(admin_caps), admin["id"]))
            print(f"  ✓ Updated capabilities for admin user: {admin['username']}")
    
    con.commit()
    con.close()
    
    print("\n" + "="*80)
    print("✅ APP ADMIN ACCOUNT READY")
    print("="*80)
    print(f"Username:      {USERNAME}")
    print(f"Password:      {PASSWORD}")
    print(f"User ID:       {updated['id']}")
    print(f"Admin:         {'✓' if updated['is_admin'] else '✗'}")
    print(f"SysAdmin:      {'✓' if updated['is_sysadmin'] else '✗'}")
    
    try:
        final_caps = json.loads(updated['caps'])
        print(f"Capabilities:  {len(final_caps)} permissions granted")
        print("\n📋 Granted Capabilities:")
        for cap in sorted([k for k in final_caps.keys() if final_caps[k]]):
            print(f"  ✓ {cap}")
    except:
        print("Capabilities:  Error reading capabilities")
    
    print("\n⚠️  NEXT STEPS:")
    print("1. Restart your Flask app: python -m app.app")
    print("2. Log out from the browser (if logged in)")
    print("3. Log back in with:")
    print(f"   Username: {USERNAME}")
    print(f"   Password: {PASSWORD}")
    print("4. All modules should now be accessible!")
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