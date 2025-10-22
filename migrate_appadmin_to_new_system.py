#!/usr/bin/env python3
"""
Migrate or create AppAdmin user in the new users.sqlite database
with full system administrator privileges.

Run from project root: python migrate_appadmin_to_new_system.py
"""

import sqlite3
import json
import os
from pathlib import Path
from werkzeug.security import generate_password_hash

# Database paths
OLD_DB = Path("app/data/auth.sqlite")
NEW_DB = Path("app/modules/users/data/users.sqlite")

# AppAdmin configuration
USERNAME = "AppAdmin"
DEFAULT_PASSWORD = "AppAdmin2025!"  # Change after first login!

def row_to_dict(row):
    """Safely convert sqlite3.Row to dict"""
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}

def check_old_database():
    """Check if AppAdmin exists in old database"""
    if not OLD_DB.exists():
        print(f"ℹ️  Old database not found: {OLD_DB}")
        return None
    
    try:
        con = sqlite3.connect(OLD_DB)
        con.row_factory = sqlite3.Row
        user = con.execute("SELECT * FROM users WHERE username=?", (USERNAME,)).fetchone()
        con.close()
        
        if user:
            print(f"✓ Found {USERNAME} in old database")
            return row_to_dict(user)
        else:
            print(f"ℹ️  {USERNAME} not found in old database")
            return None
    except Exception as e:
        print(f"⚠️  Error reading old database: {e}")
        return None

def check_new_database():
    """Check if AppAdmin exists in new database"""
    if not NEW_DB.exists():
        print(f"❌ New database not found: {NEW_DB}")
        print("   Make sure app/modules/users/models.py has been imported at least once")
        return None
    
    try:
        con = sqlite3.connect(NEW_DB)
        con.row_factory = sqlite3.Row
        user = con.execute("SELECT * FROM users WHERE username=?", (USERNAME,)).fetchone()
        con.close()
        
        if user:
            print(f"✓ Found {USERNAME} in new database")
            return row_to_dict(user)
        else:
            print(f"ℹ️  {USERNAME} not found in new database")
            return None
    except Exception as e:
        print(f"❌ Error reading new database: {e}")
        return None

def create_system_caps():
    """Create full system administrator capabilities"""
    return {
        # System flag
        "is_system": True,
        "is_admin": True,
        "is_sysadmin": True,
        
        # All module permissions (can_ prefix - new standard)
        "can_send": True,
        "can_asset": True,
        "can_inventory": True,
        "can_insights": True,
        "can_users": True,
        "can_fulfillment_staff": True,
        "can_fulfillment_customer": True,
        
        # Legacy compatibility (old names without can_ prefix)
        "send": True,
        "asset": True,
        "inventory": True,
        "insights": True,
        "users": True,
        "fulfillment_staff": True,
        "fulfillment_customer": True,
    }

def migrate_appadmin(old_user):
    """Migrate AppAdmin from old database to new database"""
    con = sqlite3.connect(str(NEW_DB))
    
    # Use existing password hash if available, otherwise create new one
    password_hash = old_user.get('password_hash') if old_user else generate_password_hash(DEFAULT_PASSWORD)
    
    # Create full system capabilities
    caps = create_system_caps()
    caps_json = json.dumps(caps)
    
    try:
        # Insert the user
        con.execute("""
            INSERT INTO users (username, password_hash, caps, is_admin, is_sysadmin)
            VALUES (?, ?, ?, 1, 1)
        """, (USERNAME, password_hash, caps_json))
        
        con.commit()
        print(f"\n✅ Successfully created {USERNAME} in new database!")
        
        # Get the new user to display info
        new_user = con.execute("SELECT * FROM users WHERE username=?", (USERNAME,)).fetchone()
        con.close()
        
        return dict(new_user) if new_user else None
        
    except sqlite3.IntegrityError:
        con.close()
        print(f"⚠️  {USERNAME} already exists in new database")
        return None
    except Exception as e:
        con.close()
        print(f"❌ Error creating user: {e}")
        import traceback
        traceback.print_exc()
        return None

def update_existing_appadmin():
    """Update existing AppAdmin with full system capabilities"""
    con = sqlite3.connect(str(NEW_DB))
    
    # Create full system capabilities
    caps = create_system_caps()
    caps_json = json.dumps(caps)
    
    try:
        # FIXED: Use proper SQL UPDATE syntax
        con.execute("""
            UPDATE users 
            SET caps = ?,
                is_admin = 1,
                is_sysadmin = 1
            WHERE username = ?
        """, (caps_json, USERNAME))
        
        con.commit()
        
        # Get updated user
        user = con.execute("SELECT * FROM users WHERE username=?", (USERNAME,)).fetchone()
        con.close()
        
        print(f"\n✅ Successfully updated {USERNAME} with full system permissions!")
        return dict(user) if user else None
        
    except Exception as e:
        con.close()
        print(f"❌ Error updating user: {e}")
        import traceback
        traceback.print_exc()
        return None

def display_user_info(user):
    """Display user information"""
    if not user:
        return
    
    print("\n" + "="*80)
    print(f"📋 {USERNAME} Account Details")
    print("="*80)
    print(f"User ID:       {user['id']}")
    print(f"Username:      {user['username']}")
    print(f"Admin:         {'✓ Yes' if user['is_admin'] else '✗ No'}")
    print(f"SysAdmin:      {'✓ Yes' if user['is_sysadmin'] else '✗ No'}")
    
    try:
        caps = json.loads(user['caps'] or '{}')
        print(f"\n📋 Capabilities ({len(caps)} total):")
        
        # System capabilities
        if caps.get('is_system'):
            print("  ✓ is_system (Full System Access)")
        
        # Group by category
        categories = {
            "Send/Mail": ["can_send", "send"],
            "Inventory/Assets": ["can_asset", "can_inventory", "asset", "inventory"],
            "Analytics": ["can_insights", "insights"],
            "User Management": ["can_users", "users"],
            "Fulfillment": ["can_fulfillment_staff", "can_fulfillment_customer", "fulfillment_staff", "fulfillment_customer"],
        }
        
        for category, cap_list in categories.items():
            category_caps = [c for c in cap_list if caps.get(c)]
            if category_caps:
                print(f"\n  {category}:")
                for cap in category_caps:
                    print(f"    ✓ {cap}")
                    
    except Exception as e:
        print(f"  ⚠️  Error parsing capabilities: {e}")
    
    print("\n" + "="*80)

def main():
    """Main migration function"""
    print("\n" + "="*80)
    print("🔧 AppAdmin Migration to New Database System")
    print("="*80)
    
    # Check old database
    print("\n1️⃣  Checking old database...")
    old_user = check_old_database()
    
    # Check new database
    print("\n2️⃣  Checking new database...")
    new_user = check_new_database()
    
    if not NEW_DB.exists():
        print("\n❌ New database doesn't exist yet!")
        print("   Run this after starting the Flask app at least once.")
        return
    
    # Decide what to do
    if new_user:
        print(f"\n3️⃣  Updating existing {USERNAME}...")
        result = update_existing_appadmin()
    else:
        print(f"\n3️⃣  Creating new {USERNAME}...")
        result = migrate_appadmin(old_user)
    
    # Display results
    if result:
        display_user_info(result)
        
        print("\n⚠️  IMPORTANT NEXT STEPS:")
        print("="*80)
        
        if old_user and old_user.get('password_hash'):
            print("✓ Your existing password was preserved")
            print("  Login with your current AppAdmin password")
        else:
            print("🔐 NEW ACCOUNT CREATED")
            print(f"  Username: {USERNAME}")
            print(f"  Password: {DEFAULT_PASSWORD}")
            print("\n⚠️  CHANGE THIS PASSWORD IMMEDIATELY AFTER LOGIN!")
        
        print("\n📋 What to do now:")
        print("  1. Restart your Flask application")
        print("  2. Clear browser cookies/use incognito mode")
        print("  3. Login at: http://localhost:5000/auth/login")
        print(f"  4. Username: {USERNAME}")
        print("  5. Access all modules including user management")
        
        print("\n✨ As a sysadmin, you can now:")
        print("  • Create new users")
        print("  • Grant admin/sysadmin privileges")
        print("  • Access all modules")
        print("  • Manage all system settings")
        print("  • Delete assets (with soft delete)")
        
        print("="*80)
    else:
        print("\n❌ Migration failed. Check errors above.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()