# create_app_admin.py
# Creates the App Administrator account with highest privileges
# This account can grant SysAdmin to others

import sqlite3
import json
import os
from werkzeug.security import generate_password_hash

# Path to auth database
AUTH_DB = os.path.join(os.path.dirname(__file__), "app", "data", "auth.sqlite")

def create_app_administrator():
    """Create the App Administrator account with full privileges."""
    
    if not os.path.exists(AUTH_DB):
        print(f"❌ Database not found at: {AUTH_DB}")
        print("Make sure you're running this from the project root directory.")
        return
    
    con = sqlite3.connect(AUTH_DB)
    con.row_factory = sqlite3.Row
    
    # Configuration for the App Administrator account
    USERNAME = "AppAdmin"
    PASSWORD = "AppAdmin2025!"  # Change this after first login!
    
    # Check if account already exists
    existing = con.execute("SELECT * FROM users WHERE username=?", (USERNAME,)).fetchone()
    
    if existing:
        print(f"⚠️  Account '{USERNAME}' already exists (ID: {existing['id']})")
        response = input("Reset password for existing account? (yes/no): ").strip().lower()
        
        if response not in ('yes', 'y'):
            print("❌ Cancelled.")
            con.close()
            return
        
        # Reset password and ensure proper flags
        password_hash = generate_password_hash(PASSWORD)
        caps = {
            "is_system": True,  # Special system flag
            "can_send": True,
            "inventory": True,
            "insights": True,
            "users": True,
            "fulfillment_staff": True,
            "fulfillment_customer": True
        }
        
        con.execute("""
            UPDATE users 
            SET password_hash=?, is_admin=1, is_sysadmin=1, caps=?
            WHERE username=?
        """, (password_hash, json.dumps(caps), USERNAME))
        
        con.commit()
        print(f"✅ Password reset for '{USERNAME}'!")
    else:
        # Create new account
        print(f"Creating new App Administrator account: {USERNAME}")
        
        password_hash = generate_password_hash(PASSWORD)
        
        # Full capabilities including the special "is_system" flag
        caps = {
            "is_system": True,  # Special flag for App Developer
            "can_send": True,
            "inventory": True,
            "insights": True,
            "users": True,
            "fulfillment_staff": True,
            "fulfillment_customer": True
        }
        
        con.execute("""
            INSERT INTO users (username, password_hash, is_admin, is_sysadmin, caps)
            VALUES (?, ?, 1, 1, ?)
        """, (USERNAME, password_hash, json.dumps(caps)))
        
        con.commit()
        print(f"✅ App Administrator account created!")
    
    # Verify creation
    user = con.execute("SELECT * FROM users WHERE username=?", (USERNAME,)).fetchone()
    con.close()
    
    print("\n" + "="*80)
    print("🎉 APP ADMINISTRATOR ACCOUNT READY")
    print("="*80)
    print(f"Username:      {USERNAME}")
    print(f"Password:      {PASSWORD}")
    print(f"User ID:       {user['id']}")
    print(f"SysAdmin:      ✓")
    print(f"Admin:         ✓")
    print(f"App Developer: ✓")
    print("="*80)
    print("\n⚠️  IMPORTANT SECURITY NOTES:")
    print("1. This account has FULL SYSTEM ACCESS")
    print("2. Can grant SysAdmin privileges to other users")
    print("3. Change the password immediately after first login!")
    print("4. Keep these credentials secure")
    print("\n🔐 Login at: http://127.0.0.1:5955/auth/login")
    print("="*80)

if __name__ == "__main__":
    try:
        create_app_administrator()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()