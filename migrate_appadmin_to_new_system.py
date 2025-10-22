#!/usr/bin/env python3
"""
Comprehensive User Migration with Permission Levels

This script migrates users from the old auth.sqlite to the new users.sqlite
and implements a 4-level permission hierarchy:

L0 - Module Access (basic user with specific module permissions)
L1 - Administrator (all modules + create/modify/delete users)
L2 - Systems Administrator (L1 + promote to admin + delete insights)
L3 - App Developer (L2 + promote to sysadmin)

Run from project root: python migrate_users_with_levels.py
"""

import sqlite3
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from werkzeug.security import generate_password_hash

# Database paths
OLD_DB = Path("app/data/auth.sqlite")
NEW_DB = Path("app/modules/users/data/users.sqlite")

# Color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_colored(text, color=Colors.ENDC):
    """Print colored text"""
    print(f"{color}{text}{Colors.ENDC}")

def print_header(text):
    """Print a header"""
    print_colored(f"\n{'='*80}", Colors.CYAN)
    print_colored(f"{text}", Colors.BOLD + Colors.CYAN)
    print_colored(f"{'='*80}", Colors.CYAN)

def row_to_dict(row):
    """Safely convert sqlite3.Row to dict"""
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


# ============================================================================
# PERMISSION LEVEL SYSTEM
# ============================================================================

PERMISSION_LEVELS = {
    0: {
        "name": "Module Access",
        "description": "Basic user with specific module permissions",
        "is_admin": False,
        "is_sysadmin": False,
        "can_create_users": False,
        "can_modify_users": False,
        "can_delete_users": False,
        "can_grant_admin": False,
        "can_grant_sysadmin": False,
        "can_delete_insights": False,
    },
    1: {
        "name": "Administrator",
        "description": "All module access + user management",
        "is_admin": True,
        "is_sysadmin": False,
        "can_create_users": True,
        "can_modify_users": True,
        "can_delete_users": True,
        "can_grant_admin": False,  # Can't promote to admin
        "can_grant_sysadmin": False,
        "can_delete_insights": False,
    },
    2: {
        "name": "Systems Administrator",
        "description": "Administrator + promote to admin + delete insights",
        "is_admin": True,
        "is_sysadmin": True,
        "can_create_users": True,
        "can_modify_users": True,
        "can_delete_users": True,
        "can_grant_admin": True,  # Can promote to admin
        "can_grant_sysadmin": False,  # Can't promote to sysadmin
        "can_delete_insights": True,
    },
    3: {
        "name": "App Developer",
        "description": "Systems Administrator + promote to sysadmin",
        "is_admin": True,
        "is_sysadmin": True,
        "can_create_users": True,
        "can_modify_users": True,
        "can_delete_users": True,
        "can_grant_admin": True,
        "can_grant_sysadmin": True,  # Can promote to sysadmin!
        "can_delete_insights": True,
    }
}

def create_caps_for_level(level: int, include_all_modules: bool = False) -> dict:
    """
    Create capabilities dict for a given permission level.
    
    Args:
        level: 0-3 (L0-L3)
        include_all_modules: If True (for L1+), includes all module permissions
    
    Returns:
        Dictionary of capabilities
    """
    level_info = PERMISSION_LEVELS.get(level, PERMISSION_LEVELS[0])
    
    caps = {
        "permission_level": level,
        "level_name": level_info["name"],
        
        # Management capabilities based on level
        "can_create_users": level_info["can_create_users"],
        "can_modify_users": level_info["can_modify_users"],
        "can_delete_users": level_info["can_delete_users"],
        "can_grant_admin": level_info["can_grant_admin"],
        "can_grant_sysadmin": level_info["can_grant_sysadmin"],
        "can_delete_insights": level_info["can_delete_insights"],
    }
    
    # If level 1+ or explicitly requested, add all module permissions
    if include_all_modules or level >= 1:
        # New standard names (can_*)
        caps.update({
            "can_send": True,
            "can_asset": True,
            "can_inventory": True,
            "can_insights": True,
            "can_users": True,
            "can_fulfillment_staff": True,
            "can_fulfillment_customer": True,
        })
        
        # Legacy names for backward compatibility
        caps.update({
            "send": True,
            "asset": True,
            "inventory": True,
            "insights": True,
            "users": True,
            "fulfillment_staff": True,
            "fulfillment_customer": True,
        })
    
    return caps


# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

def check_old_database():
    """Check and list all users in old database"""
    if not OLD_DB.exists():
        print_colored(f"ℹ️  Old database not found: {OLD_DB}", Colors.YELLOW)
        return []
    
    try:
        con = sqlite3.connect(OLD_DB)
        con.row_factory = sqlite3.Row
        users = con.execute("SELECT * FROM users ORDER BY username").fetchall()
        con.close()
        
        return [row_to_dict(row) for row in users]
        
    except Exception as e:
        print_colored(f"⚠️  Error reading old database: {e}", Colors.RED)
        import traceback
        traceback.print_exc()
        return []

def get_new_db_users():
    """Get all users from new database"""
    if not NEW_DB.exists():
        print_colored(f"❌ New database not found: {NEW_DB}", Colors.RED)
        print_colored("   Start the Flask app at least once to create it", Colors.YELLOW)
        return []
    
    try:
        con = sqlite3.connect(NEW_DB)
        con.row_factory = sqlite3.Row
        users = con.execute("SELECT * FROM users ORDER BY username").fetchall()
        con.close()
        
        return [row_to_dict(row) for row in users]
        
    except Exception as e:
        print_colored(f"❌ Error reading new database: {e}", Colors.RED)
        return []

def migrate_user(username: str, password_hash: str, permission_level: int, 
                 preserve_password: bool = True):
    """
    Migrate or create a user in the new database with specified permission level.
    
    Args:
        username: Username
        password_hash: Password hash (from old DB or new)
        permission_level: 0-3 (L0-L3)
        preserve_password: If True, use existing hash; if False, generate new password
    
    Returns:
        Created/updated user dict or None
    """
    if not NEW_DB.exists():
        print_colored(f"❌ New database doesn't exist!", Colors.RED)
        return None
    
    level_info = PERMISSION_LEVELS.get(permission_level, PERMISSION_LEVELS[0])
    caps = create_caps_for_level(permission_level, include_all_modules=(permission_level >= 1))
    caps_json = json.dumps(caps, indent=2)
    
    # Determine password hash to use
    if not preserve_password or not password_hash:
        # Generate new password: Username + current year
        new_password = f"{username}{datetime.now().year}!"
        final_hash = generate_password_hash(new_password)
        print_colored(f"   🔐 New password: {new_password}", Colors.YELLOW)
        print_colored(f"   ⚠️  CHANGE THIS IMMEDIATELY AFTER LOGIN!", Colors.RED + Colors.BOLD)
    else:
        final_hash = password_hash
        print_colored(f"   ✓ Preserved existing password", Colors.GREEN)
    
    try:
        con = sqlite3.connect(str(NEW_DB))
        con.row_factory = sqlite3.Row
        
        # Check if user exists
        existing = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        
        if existing:
            # Update existing user
            con.execute("""
                UPDATE users 
                SET password_hash = ?,
                    caps = ?,
                    is_admin = ?,
                    is_sysadmin = ?
                WHERE username = ?
            """, (final_hash, caps_json, 
                  int(level_info["is_admin"]), 
                  int(level_info["is_sysadmin"]), 
                  username))
            print_colored(f"   ✓ Updated existing user '{username}'", Colors.GREEN)
        else:
            # Insert new user
            con.execute("""
                INSERT INTO users (username, password_hash, caps, is_admin, is_sysadmin)
                VALUES (?, ?, ?, ?, ?)
            """, (username, final_hash, caps_json, 
                  int(level_info["is_admin"]), 
                  int(level_info["is_sysadmin"])))
            print_colored(f"   ✓ Created new user '{username}'", Colors.GREEN)
        
        con.commit()
        
        # Get the final user
        user = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        con.close()
        
        return row_to_dict(user) if user else None
        
    except sqlite3.IntegrityError as e:
        print_colored(f"   ❌ Database integrity error: {e}", Colors.RED)
        return None
    except Exception as e:
        print_colored(f"   ❌ Error migrating user: {e}", Colors.RED)
        import traceback
        traceback.print_exc()
        return None


# ============================================================================
# DISPLAY FUNCTIONS
# ============================================================================

def display_permission_levels():
    """Display explanation of permission levels"""
    print_header("📊 Permission Level System")
    
    for level, info in PERMISSION_LEVELS.items():
        print(f"\n{Colors.BOLD}L{level} - {info['name']}{Colors.ENDC}")
        print(f"  {info['description']}")
        print(f"  Flags: admin={info['is_admin']}, sysadmin={info['is_sysadmin']}")
        print(f"  Permissions:")
        print(f"    • Create Users: {info['can_create_users']}")
        print(f"    • Modify Users: {info['can_modify_users']}")
        print(f"    • Delete Users: {info['can_delete_users']}")
        print(f"    • Grant Admin: {info['can_grant_admin']}")
        print(f"    • Grant SysAdmin: {info['can_grant_sysadmin']}")
        print(f"    • Delete Insights: {info['can_delete_insights']}")

def display_user_details(user: dict):
    """Display detailed user information"""
    if not user:
        return
    
    print(f"\n{Colors.BOLD}👤 {user['username']}{Colors.ENDC}")
    print(f"   ID: {user['id']}")
    print(f"   Admin: {'✓' if user['is_admin'] else '✗'}")
    print(f"   SysAdmin: {'✓' if user['is_sysadmin'] else '✗'}")
    
    try:
        caps = json.loads(user.get('caps', '{}'))
        level = caps.get('permission_level', 'Unknown')
        level_name = caps.get('level_name', 'Unknown')
        
        print(f"   {Colors.BOLD}Permission Level: L{level} - {level_name}{Colors.ENDC}")
        
        # Show management capabilities
        mgmt_caps = [
            ('Create Users', caps.get('can_create_users', False)),
            ('Modify Users', caps.get('can_modify_users', False)),
            ('Delete Users', caps.get('can_delete_users', False)),
            ('Grant Admin', caps.get('can_grant_admin', False)),
            ('Grant SysAdmin', caps.get('can_grant_sysadmin', False)),
            ('Delete Insights', caps.get('can_delete_insights', False)),
        ]
        
        print(f"   Management:")
        for cap_name, cap_val in mgmt_caps:
            symbol = '✓' if cap_val else '✗'
            color = Colors.GREEN if cap_val else Colors.RED
            print(f"     {color}{symbol}{Colors.ENDC} {cap_name}")
        
        # Show module access
        module_caps = [k for k in caps.keys() if k.startswith('can_') and caps[k]]
        if module_caps:
            print(f"   Modules: {', '.join([c.replace('can_', '') for c in module_caps[:5]])}")
            
    except Exception as e:
        print(f"   ⚠️  Error parsing capabilities: {e}")

def list_old_users(users):
    """List all users from old database"""
    if not users:
        print_colored("No users found in old database", Colors.YELLOW)
        return
    
    print(f"\n{Colors.BOLD}Found {len(users)} user(s) in old database:{Colors.ENDC}")
    for i, user in enumerate(users, 1):
        print(f"{i}. {user.get('username', 'UNKNOWN')}")

def list_new_users(users):
    """List all users from new database"""
    if not users:
        print_colored("No users found in new database", Colors.YELLOW)
        return
    
    print(f"\n{Colors.BOLD}Current users in new database:{Colors.ENDC}")
    for user in users:
        display_user_details(user)


# ============================================================================
# INTERACTIVE MENUS
# ============================================================================

def interactive_migration():
    """Interactive migration wizard"""
    print_header("🧙 Interactive User Migration Wizard")
    
    # Show old users
    old_users = check_old_database()
    if old_users:
        print_colored(f"\n✓ Found {len(old_users)} user(s) in old database", Colors.GREEN)
        list_old_users(old_users)
    else:
        print_colored("\nNo old database or no users found", Colors.YELLOW)
        old_users = []
    
    # Show new users
    new_users = get_new_db_users()
    if not NEW_DB.exists():
        print_colored("\n❌ New database doesn't exist! Start Flask app first.", Colors.RED)
        return
    
    if new_users:
        list_new_users(new_users)
    
    # Ask what to do
    print(f"\n{Colors.BOLD}What would you like to do?{Colors.ENDC}")
    print("1. Migrate a user from old database")
    print("2. Upgrade existing 'admin' to L3 (App Developer)")
    print("3. Create a new L3 user (App Developer)")
    print("4. Show permission level explanations")
    print("5. Exit")
    
    choice = input("\nEnter choice (1-5): ").strip()
    
    if choice == '1':
        migrate_from_old(old_users)
    elif choice == '2':
        upgrade_admin_to_l3()
    elif choice == '3':
        create_new_l3_user()
    elif choice == '4':
        display_permission_levels()
        input("\nPress Enter to continue...")
        interactive_migration()
    elif choice == '5':
        print_colored("\n👋 Goodbye!", Colors.CYAN)
        return
    else:
        print_colored("\n⚠️  Invalid choice", Colors.YELLOW)
        interactive_migration()

def migrate_from_old(old_users):
    """Migrate a user from old database"""
    if not old_users:
        print_colored("\n❌ No users in old database to migrate", Colors.RED)
        return
    
    print(f"\n{Colors.BOLD}Select user to migrate:{Colors.ENDC}")
    for i, user in enumerate(old_users, 1):
        print(f"{i}. {user.get('username')}")
    print(f"{len(old_users) + 1}. Cancel")
    
    choice = input("\nEnter number: ").strip()
    
    try:
        idx = int(choice) - 1
        if idx == len(old_users):
            return
        if idx < 0 or idx >= len(old_users):
            print_colored("Invalid selection", Colors.RED)
            return
        
        user = old_users[idx]
        username = user.get('username')
        password_hash = user.get('password_hash')
        
        # Ask for permission level
        print(f"\n{Colors.BOLD}Select permission level for '{username}':{Colors.ENDC}")
        for level, info in PERMISSION_LEVELS.items():
            print(f"  L{level}. {info['name']} - {info['description']}")
        
        level_input = input("\nEnter level (0-3): ").strip()
        level = int(level_input)
        
        if level not in PERMISSION_LEVELS:
            print_colored("Invalid level", Colors.RED)
            return
        
        # Ask about password
        preserve = input("\nPreserve existing password? (y/n): ").strip().lower() == 'y'
        
        # Migrate
        print(f"\n{Colors.BOLD}Migrating '{username}' as Level {level}...{Colors.ENDC}")
        result = migrate_user(username, password_hash, level, preserve)
        
        if result:
            print_colored(f"\n✅ SUCCESS!", Colors.GREEN)
            display_user_details(result)
        else:
            print_colored(f"\n❌ Migration failed", Colors.RED)
            
    except (ValueError, IndexError):
        print_colored("\n⚠️  Invalid input", Colors.YELLOW)

def upgrade_admin_to_l3():
    """Upgrade the 'admin' user to L3 (App Developer)"""
    print_header("⬆️ Upgrade Admin to L3 (App Developer)")
    
    # Check if admin exists
    new_users = get_new_db_users()
    admin_user = next((u for u in new_users if u['username'] == 'admin'), None)
    
    if not admin_user:
        print_colored("\n❌ 'admin' user not found in new database", Colors.RED)
        create = input("Create new 'admin' user as L3? (y/n): ").strip().lower() == 'y'
        if create:
            password = f"admin{datetime.now().year}!"
            password_hash = generate_password_hash(password)
            result = migrate_user('admin', password_hash, 3, preserve_password=False)
            if result:
                print_colored(f"\n✅ Created 'admin' as L3 App Developer!", Colors.GREEN)
                display_user_details(result)
        return
    
    print_colored(f"\n✓ Found 'admin' user", Colors.GREEN)
    display_user_details(admin_user)
    
    confirm = input(f"\n{Colors.BOLD}Upgrade 'admin' to L3 (App Developer)? (y/n): {Colors.ENDC}").strip().lower()
    
    if confirm == 'y':
        # Preserve password
        result = migrate_user('admin', admin_user['password_hash'], 3, preserve_password=True)
        
        if result:
            print_colored(f"\n✅ Successfully upgraded 'admin' to L3!", Colors.GREEN)
            display_user_details(result)
            
            print(f"\n{Colors.BOLD}Admin now has App Developer (L3) privileges:{Colors.ENDC}")
            print("  ✓ Full module access")
            print("  ✓ Create/modify/delete users")
            print("  ✓ Grant admin privileges")
            print("  ✓ Grant sysadmin privileges")
            print("  ✓ Delete insights data")
        else:
            print_colored(f"\n❌ Upgrade failed", Colors.RED)
    else:
        print_colored("\n❌ Cancelled", Colors.YELLOW)

def create_new_l3_user():
    """Create a new L3 (App Developer) user"""
    print_header("➕ Create New L3 User (App Developer)")
    
    username = input("\nEnter username: ").strip()
    if not username:
        print_colored("Username required", Colors.RED)
        return
    
    # Check if exists
    new_users = get_new_db_users()
    if any(u['username'] == username for u in new_users):
        print_colored(f"\n⚠️  User '{username}' already exists", Colors.YELLOW)
        overwrite = input("Upgrade to L3? (y/n): ").strip().lower() == 'y'
        if not overwrite:
            return
        
        # Get existing password hash
        existing = next(u for u in new_users if u['username'] == username)
        password_hash = existing['password_hash']
        preserve = True
    else:
        # New user - generate password
        password = f"{username}{datetime.now().year}!"
        password_hash = generate_password_hash(password)
        preserve = False
    
    result = migrate_user(username, password_hash, 3, preserve_password=preserve)
    
    if result:
        print_colored(f"\n✅ Created '{username}' as L3 App Developer!", Colors.GREEN)
        display_user_details(result)
    else:
        print_colored(f"\n❌ Failed to create user", Colors.RED)


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main function"""
    print_header("🔧 User Migration with Permission Levels")
    print(f"\nOld Database: {OLD_DB}")
    print(f"New Database: {NEW_DB}")
    
    # Check if new DB exists
    if not NEW_DB.exists():
        print_colored(f"\n❌ New database doesn't exist yet!", Colors.RED)
        print_colored("   Start your Flask application at least once:", Colors.YELLOW)
        print_colored("   python -m app.app", Colors.CYAN)
        return
    
    # Show current state
    new_users = get_new_db_users()
    old_users = check_old_database()
    
    print(f"\nOld database: {len(old_users)} user(s)")
    print(f"New database: {len(new_users)} user(s)")
    
    # Run interactive wizard
    interactive_migration()
    
    print_colored(f"\n{'='*80}", Colors.CYAN)
    print_colored("Migration complete!", Colors.GREEN + Colors.BOLD)
    print_colored(f"{'='*80}\n", Colors.CYAN)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print_colored("\n\n👋 Migration cancelled by user", Colors.YELLOW)
    except Exception as e:
        print_colored(f"\n❌ Unexpected error: {e}", Colors.RED)
        import traceback
        traceback.print_exc()