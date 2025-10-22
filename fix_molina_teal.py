#!/usr/bin/env python3
"""
Fix Molina Teal Branding Colors in base.html
Replaces all purple/blue hardcoded colors with Molina teal

Run from project root: python fix_molina_colors.py
"""

import os
import re
import shutil
from datetime import datetime

def backup_file(filepath):
    """Create timestamped backup"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = f"{filepath}.backup_{timestamp}"
    shutil.copy2(filepath, backup_path)
    print(f"  ✓ Backup created: {backup_path}")
    return backup_path

def fix_molina_colors():
    """Fix all hardcoded purple/blue colors to use Molina teal"""
    filepath = "app/templates/base.html"
    
    if not os.path.exists(filepath):
        print(f"❌ File not found: {filepath}")
        return False
    
    backup_file(filepath)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    print("\n🎨 Replacing hardcoded colors with Molina teal...")
    
    # Count replacements
    replacements = 0
    
    # 1. Module Badges - Replace purple/blue gradients with teal
    color_replacements = [
        # Send badge (blue) → Molina teal
        (r'\.badge-send\s*{\s*background:\s*linear-gradient\([^)]+\);',
         '.badge-send {\n            background: linear-gradient(135deg, var(--molina-teal) 0%, var(--molina-teal-dark) 100%);'),
        
        # Inventory badge (purple) → Molina teal
        (r'\.badge-inventory\s*{\s*background:\s*linear-gradient\(135deg,\s*#8b5cf6[^)]+\);',
         '.badge-inventory {\n            background: linear-gradient(135deg, var(--molina-teal) 0%, var(--molina-teal-dark) 100%);'),
        
        # Insights badge (pink) → Molina teal dark
        (r'\.badge-insights\s*{\s*background:\s*linear-gradient\(135deg,\s*#ec4899[^)]+\);',
         '.badge-insights {\n            background: linear-gradient(135deg, var(--molina-teal-dark) 0%, var(--molina-teal) 100%);'),
        
        # Users badge (orange) → Keep as accent, but could change to teal variant
        # Keeping this one as is for visual distinction
        
        # Fulfillment badge (green) → Keep as accent
        # Keeping this one as is for visual distinction
        
        # Primary buttons and interactive elements
        (r'#3b82f6', 'var(--molina-teal)'),  # Blue → Teal
        (r'#2563eb', 'var(--molina-teal-dark)'),  # Dark blue → Dark teal
        (r'#667eea', 'var(--molina-teal)'),  # Purple-blue → Teal
        (r'#764ba2', 'var(--molina-teal-dark)'),  # Purple → Dark teal
        (r'#8b5cf6', 'var(--molina-teal)'),  # Violet → Teal
        (r'#7c3aed', 'var(--molina-teal-dark)'),  # Dark violet → Dark teal
    ]
    
    for pattern, replacement in color_replacements:
        matches = len(re.findall(pattern, content, re.IGNORECASE))
        if matches > 0:
            content = re.sub(pattern, replacement, content, flags=re.IGNORECASE)
            replacements += matches
            print(f"    ✓ Replaced {matches} instance(s) of {pattern[:30]}...")
    
    # 2. Fix dashboard cards and stat cards
    dashboard_colors = [
        # Stat card gradients
        (r'linear-gradient\(135deg,\s*#667eea\s+0%,\s*#764ba2\s+100%\)',
         'var(--primary-gradient)'),
        
        # Action card colors
        (r'--action-color:\s*#667eea',
         '--action-color: var(--molina-teal)'),
        
        (r'--action-bg:\s*rgba\(102,\s*126,\s*234,\s*0\.\d+\)',
         '--action-bg: rgba(0, 163, 173, 0.1)'),
    ]
    
    for pattern, replacement in dashboard_colors:
        matches = len(re.findall(pattern, content))
        if matches > 0:
            content = re.sub(pattern, replacement, content)
            replacements += matches
            print(f"    ✓ Fixed {matches} dashboard color(s)")
    
    # 3. Fix box shadows with blue/purple tints
    shadow_replacements = [
        (r'rgba\(102,\s*126,\s*234,\s*(0\.\d+)\)',
         r'rgba(0, 163, 173, \1)'),  # Purple-blue shadow → Teal shadow
        
        (r'rgba\(139,\s*92,\s*246,\s*(0\.\d+)\)',
         r'rgba(0, 163, 173, \1)'),  # Violet shadow → Teal shadow
    ]
    
    for pattern, replacement in shadow_replacements:
        matches = len(re.findall(pattern, content))
        if matches > 0:
            content = re.sub(pattern, replacement, content)
            replacements += matches
            print(f"    ✓ Fixed {matches} shadow color(s)")
    
    # 4. Save the file
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"\n✅ Total replacements made: {replacements}")
    print(f"✅ File updated: {filepath}")
    
    return True

def verify_colors():
    """Verify that Molina colors are being used"""
    filepath = "app/templates/base.html"
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    print("\n🔍 Verifying color usage...")
    
    # Check for remaining non-Molina colors (excluding approved accent colors)
    problematic_colors = [
        (r'#667eea', 'Purple-blue'),
        (r'#764ba2', 'Purple'),
        (r'#8b5cf6', 'Violet'),
        (r'#7c3aed', 'Dark violet'),
        (r'#3b82f6', 'Blue'),
        (r'#2563eb', 'Dark blue'),
    ]
    
    issues_found = 0
    for pattern, color_name in problematic_colors:
        matches = re.findall(pattern, content, re.IGNORECASE)
        if matches:
            issues_found += len(matches)
            print(f"  ⚠️  Found {len(matches)} instance(s) of {color_name} ({pattern})")
    
    # Check for Molina color usage
    molina_usage = [
        (r'var\(--molina-teal\)', 'Molina Teal Variable'),
        (r'#00A3AD', 'Molina Teal Hex'),
        (r'var\(--primary-gradient\)', 'Primary Gradient'),
    ]
    
    total_molina = 0
    for pattern, name in molina_usage:
        matches = re.findall(pattern, content)
        total_molina += len(matches)
        if matches:
            print(f"  ✓ {name}: {len(matches)} uses")
    
    print(f"\n📊 Summary:")
    print(f"  Molina colors used: {total_molina} times")
    print(f"  Potential issues: {issues_found}")
    
    if issues_found == 0:
        print("\n✅ All hardcoded colors have been replaced with Molina branding!")
    else:
        print("\n⚠️  Some hardcoded colors still remain. Review manually.")
    
    return issues_found == 0

def main():
    print("\n" + "="*70)
    print("🎨 Molina Teal Branding Color Fix")
    print("="*70)
    
    if not os.path.exists("app/templates/base.html"):
        print("\n❌ Error: Must run from project root directory")
        print(f"   Current directory: {os.getcwd()}")
        return
    
    print("\n1️⃣  Fixing hardcoded colors...")
    success = fix_molina_colors()
    
    if success:
        print("\n2️⃣  Verifying changes...")
        verify_colors()
        
        print("\n" + "="*70)
        print("✅ COLOR FIX COMPLETE!")
        print("="*70)
        
        print("\n📋 Changes made:")
        print("  ✓ Replaced purple/blue gradients with Molina teal")
        print("  ✓ Updated module badges to use teal")
        print("  ✓ Fixed shadow colors to use teal")
        print("  ✓ Updated interactive elements to use teal")
        
        print("\n🚀 Next steps:")
        print("  1. Restart Flask: python -m app.app")
        print("  2. Hard refresh browser: Ctrl+Shift+R (Windows) or Cmd+Shift+R (Mac)")
        print("  3. Check sidebar, navigation, and module badges")
        print("  4. If still seeing purple, clear browser cache completely")
        
        print("\n💾 Backup created - you can revert if needed")
        print("="*70 + "\n")
    else:
        print("\n❌ Fix failed. Check errors above.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()