#!/usr/bin/env python3
"""
Upgrade AppAdmin to App Developer (L3) with System Privileges

This script safely upgrades the AppAdmin user to be a true system-level
App Developer with full permissions.

Usage: python upgrade_appadmin_to_system.py
"""

import sqlite3
import json
import sys
from pathlib import Path
from datetime import datetime

# Database path
DB_PATH = Path("app/modules/users/data/users.sqlite")

# Colors for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_success(msg):
    print(f"{Colors.GREEN}✓ {msg}{Colors.END}")

def print_warning(msg):
    print(f"{Colors.YELLOW}⚠ {msg}{Colors.END}")

def print_error(msg):
    print(f"{Colors.RED}✗ {msg}{Colors.END}")

def print_info(msg):
    print(f"{Colors.BLUE}ℹ {msg}{Colors.END}")

def print_header(msg):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{msg}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}\n")

# App Developer (L3) capabilities
APP_DEVELOPER_CAPS = {
    "permission_level": 3,
    "level_name": "App Developer",
    "is_system": True,
    
    # Management capabilities (full permissions)
    "can_create_users": True,
    "can_modify_users": True,
    "can_delete_users": True,
    "can_grant_admin": True,
    "can_grant_sysadmin": True,
    "can_delete_insights": True,
    
    # Module access (all modules)
    "can_send": True,
    "can_asset": True,
    "can_inventory": True,
    "can_insights": True,
    "can_users": True,
    "can_fulfillment_staff": True,
    "can_fulfillment_customer": True,
    
    # Legacy compatibility
    "send": True,
    "asset": True,
    "inventory": True,
    "insights": True,
    "users": True,
    "fulfillment_staff": True,
    "fulfillment_customer": True
}

def check_database():
    """Verify database exists and is accessible"""
    if not DB_PATH.exists():
        print_error(f"Database not found at: {DB_PATH}")
        print_info("Expected location: app/modules/users/data/users.sqlite")
        print_info("Make sure you're running this from the project root directory")
        return False
    print_success(f"Database found: {DB_PATH}")
    return True

def backup_database():
    """Create a backup of the database"""
    backup_path = DB_PATH.with_suffix(f'.sqlite.backup.{datetime.now():%Y%m%d_%H%M%S}')
    try:
        import shutil
        shutil.copy2(DB_PATH, backup_path)
        print_success(f"Backup created: {backup_path}")
        return True
    except Exception as e:
        print_error(f"Failed to create backup: {e}")
        return False

def get_current_appadmin(con):
    """Get current AppAdmin user details"""
    cursor = con.execute("SELECT * FROM users WHERE username = 'AppAdmin'")
    row = cursor.fetchone()
    
    if not row:
        print_error("AppAdmin user not found in database!")
        return None
    
    user = dict(row)
    print_success("Found AppAdmin user")
    
    # Display current state
    print_info(f"  ID: {user['id']}")
    print_info(f"  is_admin: {user['is_admin']}")
    print_info(f"  is_sysadmin: {user['is_sysadmin']}")
    
    try:
        caps = json.loads(user['caps'] or '{}')
        print_info(f"  Current level: {caps.get('level_name', 'Unknown')}")
        print_info(f"  is_system: {caps.get('is_system', False)}")
    except:
        print_warning("  Could not parse current capabilities")
    
    return user

def upgrade_appadmin(con):
    """Upgrade AppAdmin to App Developer (L3)"""
    print_info("Upgrading AppAdmin to App Developer (L3)...")
    
    caps_json = json.dumps(APP_DEVELOPER_CAPS, indent=2)
    
    con.execute("""
        UPDATE users
        SET 
            caps = ?,
            is_admin = 1,
            is_sysadmin = 1
        WHERE username = 'AppAdmin'
    """, (caps_json,))
    
    con.commit()
    print_success("AppAdmin upgraded successfully!")

def verify_upgrade(con):
    """Verify the upgrade was successful"""
    print_info("Verifying upgrade...")
    
    cursor = con.execute("""
        SELECT id, username, is_admin, is_sysadmin, caps
        FROM users 
        WHERE username = 'AppAdmin'
    """)
    
    row = cursor.fetchone()
    if not row:
        print_error("AppAdmin user disappeared! Something went wrong.")
        return False
    
    user = dict(row)
    
    # Check flags
    if user['is_admin'] != 1:
        print_error("is_admin flag not set correctly")
        return False
    
    if user['is_sysadmin'] != 1:
        print_error("is_sysadmin flag not set correctly")
        return False
    
    # Check caps
    try:
        caps = json.loads(user['caps'])
        
        if caps.get('permission_level') != 3:
            print_error("Permission level not set to 3")
            return False
        
        if caps.get('level_name') != 'App Developer':
            print_error("Level name not set to 'App Developer'")
            return False
        
        if caps.get('is_system') != True:
            print_error("is_system flag not set to True")
            return False
        
        if caps.get('can_grant_sysadmin') != True:
            print_error("can_grant_sysadmin not set to True")
            return False
        
        print_success("All verification checks passed!")
        print_info("\nFinal state:")
        print_info(f"  Permission Level: L{caps['permission_level']} - {caps['level_name']}")
        print_info(f"  System User: {caps['is_system']}")
        print_info(f"  Can Grant SysAdmin: {caps['can_grant_sysadmin']}")
        print_info(f"  Can Grant Admin: {caps['can_grant_admin']}")
        
        return True
        
    except Exception as e:
        print_error(f"Error parsing capabilities: {e}")
        return False

def main():
    print_header("Upgrade AppAdmin to App Developer (L3)")
    
    # Step 1: Check database
    if not check_database():
        sys.exit(1)
    
    # Step 2: Backup
    print_info("\nStep 1: Creating backup...")
    if not backup_database():
        print_warning("Backup failed, but continuing anyway...")
    
    # Step 3: Connect to database
    print_info("\nStep 2: Connecting to database...")
    try:
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        print_success("Connected to database")
    except Exception as e:
        print_error(f"Failed to connect: {e}")
        sys.exit(1)
    
    try:
        # Step 4: Get current state
        print_info("\nStep 3: Checking current AppAdmin state...")
        current = get_current_appadmin(con)
        if not current:
            sys.exit(1)
        
        # Step 5: Confirm upgrade
        print_warning("\nThis will upgrade AppAdmin to:")
        print_info("  - Permission Level: L3 (App Developer)")
        print_info("  - System User: TRUE")
        print_info("  - Can grant SysAdmin: TRUE")
        print_info("  - All module access: TRUE")
        
        response = input(f"\n{Colors.YELLOW}Proceed with upgrade? (yes/no): {Colors.END}").strip().lower()
        if response not in ['yes', 'y']:
            print_warning("Upgrade cancelled by user")
            sys.exit(0)
        
        # Step 6: Perform upgrade
        print_info("\nStep 4: Performing upgrade...")
        upgrade_appadmin(con)
        
        # Step 7: Verify
        print_info("\nStep 5: Verifying upgrade...")
        if not verify_upgrade(con):
            print_error("Verification failed! Check the database.")
            sys.exit(1)
        
        print_header("SUCCESS!")
        print_success("AppAdmin has been successfully upgraded to App Developer (L3)")
        print_info("\nWhat this means:")
        print_info("  ✓ AppAdmin is now a true system-level user")
        print_info("  ✓ Can grant/revoke SysAdmin privileges to other users")
        print_info("  ✓ Has access to all modules and features")
        print_info("  ✓ Is recognized as 'system' user in the application")
        print_info("\nNext steps:")
        print_info("  1. Restart your Flask application")
        print_info("  2. Log in as AppAdmin")
        print_info("  3. Go to Admin → Elevated Users")
        print_info("  4. You should now be able to toggle SysAdmin for other users")
        
    finally:
        con.close()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print_warning("\n\nUpgrade cancelled by user")
        sys.exit(0)
    except Exception as e:
        print_error(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)