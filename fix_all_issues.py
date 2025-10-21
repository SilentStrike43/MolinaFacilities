#!/usr/bin/env python3
"""
Auto-fix script for BTManifest application issues.
Run this from the project root: python fix_all_issues.py
"""

import os
import re
import shutil
from pathlib import Path

def backup_file(filepath):
    """Create a backup of the file before modifying."""
    backup_path = f"{filepath}.backup"
    if not os.path.exists(backup_path):
        shutil.copy2(filepath, backup_path)
        print(f"  ✓ Backed up: {filepath}")

def fix_ledger_blueprint():
    """Fix the ledger.py blueprint naming and redirects."""
    filepath = "app/modules/inventory/ledger.py"
    if not os.path.exists(filepath):
        print(f"  ✗ File not found: {filepath}")
        return
    
    backup_file(filepath)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Fix redirect endpoints
    content = content.replace(
        'url_for("inventory_ledger.ledger_home"',
        'url_for("asset_ledger.ledger_home"'
    )
    
    # Fix template path
    content = content.replace(
        'render_template("inventory_ledger.html"',
        'render_template("inventory/inventory_ledger.html"'
    )
    
    # Fix active navigation
    content = content.replace(
        'active="inventory"',
        'active="asset-ledger"'
    )
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"  ✓ Fixed: {filepath}")

def fix_base_template():
    """Add Send Insights link to navigation."""
    filepath = "app/templates/base.html"
    if not os.path.exists(filepath):
        print(f"  ✗ File not found: {filepath}")
        return
    
    backup_file(filepath)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Find the Send section and add Insights link
    new_lines = []
    for i, line in enumerate(lines):
        new_lines.append(line)
        # Add Insights link after Track Package
        if 'send.tracking' in line and 'nav-link-custom' in line:
            # Check if next few lines don't already have send.reports
            if i + 5 < len(lines) and 'send.reports' not in ''.join(lines[i:i+5]):
                # Get the indentation from current line
                indent = len(line) - len(line.lstrip())
                new_lines.append(' ' * indent + '<a href="{{ url_for(\'send.reports\') }}" class="nav-link-custom {{ \'active\' if active==\'send-insights\' else \'\' }}">\n')
                new_lines.append(' ' * (indent + 4) + '<i class="bi bi-bar-chart-line nav-link-icon"></i>\n')
                new_lines.append(' ' * (indent + 4) + '<span>Insights</span>\n')
                new_lines.append(' ' * indent + '</a>\n')
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    
    print(f"  ✓ Fixed: {filepath}")

def fix_send_insights_template():
    """Fix JavaScript/template issues in send/insights.html."""
    filepath = "app/modules/send/templates/send/insights.html"
    if not os.path.exists(filepath):
        print(f"  ✗ File not found: {filepath}")
        return
    
    backup_file(filepath)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Fix form action
    content = content.replace(
        "{{ url_for('send.reports') if 'send.reports' in url_for else '#' }}",
        "{{ url_for('send.reports') }}"
    )
    
    # Fix export link
    content = content.replace(
        "{{ url_for('send.export', q=q or '') if 'send.export' in url_for else '#' }}",
        "{{ url_for('send.export') }}?q={{ q or '' }}"
    )
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"  ✓ Fixed: {filepath}")

def fix_auth_security():
    """Fix capability synonyms in auth/security.py."""
    filepath = "app/modules/auth/security.py"
    if not os.path.exists(filepath):
        print(f"  ✗ File not found: {filepath}")
        return
    
    backup_file(filepath)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find and replace the _CAP_SYNONYMS dictionary
    new_synonyms = '''_CAP_SYNONYMS = {
    "asset": "can_asset",
    "inventory": "can_inventory",
    "can_asset": "can_asset",
    "can_inventory": "can_inventory",
    "send": "can_send",
    "can_send": "can_send",
    "insights": "can_insights",
    "can_insights": "can_insights",
    "users": "can_users",
    "can_users": "can_users",
    "admin": "is_admin",
    "sysadmin": "is_sysadmin",
    "fulfillment_staff": "can_fulfillment_staff",
    "can_fulfillment_staff": "can_fulfillment_staff",
    "fulfillment_customer": "can_fulfillment_customer",
    "can_fulfillment_customer": "can_fulfillment_customer",
    "fulfillment_any": "fulfillment_any",
}'''
    
    # Replace the old dictionary
    pattern = r'_CAP_SYNONYMS\s*=\s*\{[^}]+\}'
    content = re.sub(pattern, new_synonyms, content, flags=re.DOTALL)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"  ✓ Fixed: {filepath}")

def fix_admin_permissions():
    """Fix permissions mapping in admin/views.py."""
    filepath = "app/modules/admin/views.py"
    if not os.path.exists(filepath):
        print(f"  ✗ File not found: {filepath}")
        return
    
    backup_file(filepath)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Fix the capability assignments
    content = content.replace(
        'caps["inventory"] = bool(request.form.get("can_asset"))',
        'caps["can_asset"] = bool(request.form.get("can_asset"))'
    )
    content = content.replace(
        'caps["insights"] = bool(request.form.get("can_insights"))',
        'caps["can_insights"] = bool(request.form.get("can_insights"))'
    )
    content = content.replace(
        'caps["users"] = bool(request.form.get("can_users"))',
        'caps["can_users"] = bool(request.form.get("can_users"))'
    )
    content = content.replace(
        'caps["fulfillment_staff"] = bool(request.form.get("can_fulfillment_staff"))',
        'caps["can_fulfillment_staff"] = bool(request.form.get("can_fulfillment_staff"))'
    )
    content = content.replace(
        'caps["fulfillment_customer"] = bool(request.form.get("can_fulfillment_customer"))',
        'caps["can_fulfillment_customer"] = bool(request.form.get("can_fulfillment_customer"))'
    )
    
    # Add inventory capability if not present
    if 'caps["can_inventory"]' not in content:
        # Find the location after the other caps assignments
        insert_after = 'caps["can_fulfillment_customer"]'
        if insert_after in content:
            content = content.replace(
                insert_after + ' = bool(request.form.get("can_fulfillment_customer"))',
                insert_after + ' = bool(request.form.get("can_fulfillment_customer"))\n        caps["can_inventory"] = bool(request.form.get("can_inventory"))'
            )
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"  ✓ Fixed: {filepath}")

def delete_duplicate_file():
    """Delete the duplicate ledger_views.py file."""
    filepath = "app/modules/inventory/ledger_views.py"
    if os.path.exists(filepath):
        backup_file(filepath)
        os.remove(filepath)
        print(f"  ✓ Deleted duplicate file: {filepath}")
    else:
        print(f"  ✓ Duplicate file already removed: {filepath}")

def fix_core_ui():
    """Ensure core/ui.py exposes all capabilities."""
    filepath = "app/core/ui.py"
    if not os.path.exists(filepath):
        print(f"  ✗ File not found: {filepath}")
        return
    
    backup_file(filepath)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Ensure can_inventory is exposed
    if 'cu["can_inventory"]' not in content:
        # Find where other capabilities are set
        insert_after = 'cu["can_fulfillment_customer"]'
        if insert_after in content:
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if insert_after in line:
                    # Get the indentation
                    indent = len(line) - len(line.lstrip())
                    lines.insert(i + 1, ' ' * indent + 'cu["can_inventory"] = caps.get("can_inventory", False)')
                    break
            content = '\n'.join(lines)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"  ✓ Fixed: {filepath}")

def main():
    """Run all fixes."""
    print("\n" + "="*80)
    print("🔧 BTManifest Auto-Fix Script")
    print("="*80)
    
    print("\n📋 Applying fixes...\n")
    
    print("1. Fixing Asset Ledger Blueprint...")
    fix_ledger_blueprint()
    
    print("\n2. Adding Send Insights to Navigation...")
    fix_base_template()
    
    print("\n3. Fixing Send Insights Template...")
    fix_send_insights_template()
    
    print("\n4. Fixing Auth Security Capabilities...")
    fix_auth_security()
    
    print("\n5. Fixing Admin Permissions...")
    fix_admin_permissions()
    
    print("\n6. Removing Duplicate Files...")
    delete_duplicate_file()
    
    print("\n7. Fixing Core UI...")
    fix_core_ui()
    
    print("\n" + "="*80)
    print("✅ ALL FIXES APPLIED SUCCESSFULLY!")
    print("="*80)
    
    print("\n📋 Next Steps:")
    print("1. Stop your Flask app if running")
    print("2. Run: python create_app_admin.py")
    print("3. Restart Flask: python -m app.app")
    print("4. Log in as AppAdmin with the credentials from step 2")
    print("5. Verify all modules are accessible")
    print("\n💾 Backup files created with .backup extension")
    print("   To restore: rename .backup files back to original names")
    print("="*80 + "\n")

if __name__ == "__main__":
    # Ensure we're in the project root
    if not os.path.exists("app") or not os.path.exists("app/modules"):
        print("❌ Error: Must run this script from the project root directory (C:\\BTManifest)")
        print("   Current directory:", os.getcwd())
        exit(1)
    
    main()