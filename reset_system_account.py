# reset_system_account.py
# Run this script to reset the System Administrator account password
# Usage: python reset_system_account.py

import sqlite3
import os
from werkzeug.security import generate_password_hash

# Path to auth database
AUTH_DB = os.path.join(os.path.dirname(__file__), "app", "data", "auth.sqlite")

def reset_system_account():
    """Find and reset the system administrator account."""
    
    if not os.path.exists(AUTH_DB):
        print(f"❌ Database not found at: {AUTH_DB}")
        print("Make sure you're running this from the project root directory.")
        return
    
    con = sqlite3.connect(AUTH_DB)
    con.row_factory = sqlite3.Row
    
    # Find all admin/sysadmin accounts
    print("\n🔍 Looking for administrator accounts...\n")
    rows = con.execute("""
        SELECT id, username, is_admin, is_sysadmin, created_utc 
        FROM users 
        WHERE is_admin=1 OR is_sysadmin=1
        ORDER BY id
    """).fetchall()
    
    if not rows:
        print("❌ No administrator accounts found!")
        con.close()
        return
    
    print("Found administrator accounts:")
    print("-" * 80)
    for r in rows:
        is_sys = "✓" if r["is_sysadmin"] else " "
        is_adm = "✓" if r["is_admin"] else " "
        print(f"ID: {r['id']:3d} | Username: {r['username']:20s} | SysAdmin:[{is_sys}] Admin:[{is_adm}]")
    print("-" * 80)
    
    # Prompt for which account to reset
    print("\nWhich account would you like to reset?")
    account_id = input("Enter account ID (or username): ").strip()
    
    # Find the account
    if account_id.isdigit():
        user = con.execute("SELECT * FROM users WHERE id=?", (int(account_id),)).fetchone()
    else:
        user = con.execute("SELECT * FROM users WHERE username=?", (account_id,)).fetchone()
    
    if not user:
        print(f"❌ Account not found: {account_id}")
        con.close()
        return
    
    print(f"\n📋 Selected account: {user['username']} (ID: {user['id']})")
    print(f"   - System Administrator: {'Yes' if user['is_sysadmin'] else 'No'}")
    print(f"   - Administrator: {'Yes' if user['is_admin'] else 'No'}")
    
    # Prompt for new password
    print("\n🔐 Enter new password for this account:")
    new_password = input("Password: ").strip()
    
    if len(new_password) < 4:
        print("❌ Password must be at least 4 characters.")
        con.close()
        return
    
    # Confirm
    confirm = input(f"\n⚠️  Reset password for '{user['username']}'? (yes/no): ").strip().lower()
    if confirm not in ('yes', 'y'):
        print("❌ Cancelled.")
        con.close()
        return
    
    # Update password
    password_hash = generate_password_hash(new_password)
    con.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, user['id']))
    con.commit()
    con.close()
    
    print(f"\n✅ Password reset successfully for '{user['username']}'!")
    print(f"\nYou can now log in with:")
    print(f"   Username: {user['username']}")
    print(f"   Password: {new_password}")
    print("\n⚠️  Make sure to change this password after logging in!")

if __name__ == "__main__":
    try:
        reset_system_account()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()