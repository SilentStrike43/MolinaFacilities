"""
Asset Ledger Permission Diagnostic Script
Run this to see exactly why Asset Ledger is denied
Usage: python diagnose_asset_ledger.py
"""

import sqlite3
import json
import sys
from pathlib import Path

# Find database
PROJECT_ROOT = Path(__file__).parent
DB_PATH = PROJECT_ROOT / "app" / "data" / "auth.sqlite"

if not DB_PATH.exists():
    print(f"❌ Database not found at: {DB_PATH}")
    print("Make sure you're running this from the project root directory.")
    sys.exit(1)

print("="*80)
print("ASSET LEDGER PERMISSION DIAGNOSTIC")
print("="*80)

# Connect to database
db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row

# Get AppAdmin user
print("\n1. Checking AppAdmin user...")
print("-"*80)

user = db.execute("SELECT * FROM users WHERE username = 'AppAdmin'").fetchone()

if not user:
    print("❌ AppAdmin user not found in database!")
    print("   This is a serious problem. The system account is missing.")
    db.close()
    sys.exit(1)

print(f"✓ User found: {user['username']}")
print(f"  User ID: {user['id']}")
print(f"  Created: {user['created_utc']}")

# Check admin flags
print("\n2. Checking Administrator Flags...")
print("-"*80)

is_admin = bool(user['is_admin'])
is_sysadmin = bool(user['is_sysadmin'])

print(f"  is_admin: {is_admin} {'✓' if is_admin else '✗'}")
print(f"  is_sysadmin: {is_sysadmin} {'✓' if is_sysadmin else '✗'}")

if is_admin or is_sysadmin:
    print("\n  ✓ AppAdmin has administrator privileges")
    print("    Admins should bypass all permission checks!")
    print("    If you're still getting denied, there's a code bug.")
else:
    print("\n  ⚠️  AppAdmin is NOT an administrator!")
    print("     This is unusual - system accounts are typically admins.")

# Parse capabilities
print("\n3. Checking Capabilities JSON...")
print("-"*80)

caps_raw = user['caps'] or '{}'
print(f"  Raw JSON: {caps_raw}")

try:
    caps = json.loads(caps_raw)
    print(f"\n  Parsed Capabilities ({len(caps)} total):")
    
    if len(caps) == 0:
        print("    ⚠️  No capabilities defined!")
    else:
        for key, value in sorted(caps.items()):
            status = "✓" if value else "✗"
            print(f"    {status} {key}: {value}")
    
    # Check specific permissions needed for Asset Ledger
    print("\n4. Asset Ledger Permission Check...")
    print("-"*80)
    
    required_perms = [
        "inventory",
        "can_asset", 
        "can_inventory",
        "is_system"
    ]
    
    found_perms = []
    for perm in required_perms:
        if caps.get(perm):
            found_perms.append(perm)
            print(f"    ✓ Has '{perm}': {caps[perm]}")
        else:
            print(f"    ✗ Missing '{perm}'")
    
    if found_perms:
        print(f"\n  ✓ Found {len(found_perms)} relevant permission(s): {', '.join(found_perms)}")
    else:
        print("\n  ❌ NO asset/inventory permissions found!")
        print("     This is why you're getting 'Access Denied'")
        
except json.JSONDecodeError as e:
    print(f"  ❌ ERROR: Invalid JSON in caps field!")
    print(f"     {e}")
    caps = {}

# Check what the code is looking for
print("\n5. What Code is Checking...")
print("-"*80)

print("  ledger.py checks for: 'can_asset'")
print("  But synonym mapping translates:")
print("    'can_asset' → looks for 'inventory' in database")
print("    'inventory' → looks for 'inventory' in database")
print("    'asset' → looks for 'inventory' in database")

print("\n6. Diagnosis Summary...")
print("-"*80)

issues = []

if not (is_admin or is_sysadmin):
    issues.append("AppAdmin is not marked as admin/sysadmin")

if not caps.get('inventory') and not caps.get('can_asset') and not caps.get('can_inventory'):
    issues.append("No inventory/asset permission in capabilities")

if issues:
    print("  ❌ PROBLEMS FOUND:")
    for i, issue in enumerate(issues, 1):
        print(f"     {i}. {issue}")
    
    print("\n  🔧 RECOMMENDED FIX:")
    print("     Run the fix script: python fix_appadmin_perms.py")
else:
    if is_admin or is_sysadmin:
        print("  ⚠️  UNEXPECTED ISSUE:")
        print("     User HAS admin privileges but still denied")
        print("     This suggests a code bug in the permission checking")
        print("\n  🔧 RECOMMENDED FIX:")
        print("     1. Check ledger.py uses correct decorator")
        print("     2. Verify security.py has_cap() function")
        print("     3. Enable debug logging in Flask")
    else:
        print("  ✓ User HAS required permissions")
        print("     If still denied, check:")
        print("     1. ledger.py decorator (@require_asset vs @require_cap)")
        print("     2. Restart Flask server")
        print("     3. Clear browser cache")

# Show fix SQL
print("\n7. Quick Fix SQL...")
print("-"*80)

print("\n-- Run this SQL to give AppAdmin all permissions:")
print("UPDATE users SET")
print("  is_admin = 1,")
print("  is_sysadmin = 1,")
print("  caps = '{\"inventory\": true, \"can_send\": true, \"insights\": true, \"users\": true, \"fulfillment_staff\": true, \"is_system\": true}'")
print("WHERE username = 'AppAdmin';")

db.close()

print("\n" + "="*80)
print("Diagnostic Complete")
print("="*80)