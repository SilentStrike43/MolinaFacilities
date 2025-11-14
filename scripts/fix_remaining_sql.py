#!/usr/bin/env python3
"""
Fix remaining SQL syntax issues
"""
import re

files_to_fix = [
    'app/modules/send/reports.py',
    'app/modules/fulfillment/reports.py',
]

for filepath in files_to_fix:
    print(f"Fixing {filepath}...")
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Replace ? with %s in SQL queries
        content = re.sub(
            r'(sql\s*\+?=\s*["\'].*?)(\?)(.*?["\'])',
            r'\1%s\3',
            content,
            flags=re.MULTILINE
        )
        
        # Fix cursor_description access for PostgreSQL
        content = content.replace(
            'w.writerow([col[0] for col in rows[0].cursor_description])',
            'w.writerow(rows[0].keys())'
        )
        content = content.replace(
            'for r in rows:\n            w.writerow(list(r))',
            'for r in rows:\n            w.writerow(list(r.values()))'
        )
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"  ✅ Fixed {filepath}")
    except Exception as e:
        print(f"  ❌ Error fixing {filepath}: {e}")

print("\n✅ All fixes applied!")