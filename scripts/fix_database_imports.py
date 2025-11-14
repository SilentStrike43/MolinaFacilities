"""
Fixed version - won't double-replace!
"""
import os
import re

MODULE_TO_DB = {
    'users': 'core',
    'inventory': 'inventory',
    'send': 'send',
    'fulfillment': 'fulfillment',
    'admin': 'core',
    'auth': 'core',
    'home': 'core'
}

def get_database_for_module(filepath):
    """Determine which database a module should use"""
    for module, db in MODULE_TO_DB.items():
        if f'modules/{module}/' in filepath.replace('\\', '/'):
            return db
    return 'core'

def fix_file(filepath):
    """Fix a single file - carefully to avoid double replacements"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        original_content = ''.join(lines)
        fixed_lines = []
        database_name = get_database_for_module(filepath)
        changed = False
        
        for line in lines:
            new_line = line
            
            # Fix import statement (only if not already fixed)
            if 'from app.core.database import get_db_connection' in line and 'get_db_connection_connection' not in line:
                new_line = line.replace(
                    'from app.core.database import get_db_connection',
                    'from app.core.database import get_db_connection_connection'
                )
                changed = True
            
            # Fix with statement (only if not already fixed)
            elif 'with get_db_connection() as' in line and 'get_db_connection_connection' not in line:
                new_line = re.sub(
                    r'with get_db_connection_connection("core") as (\w+):',
                    rf'with get_db_connection_connection("{database_name}") as \1:',
                    line
                )
                changed = True
            
            # Fix standalone get_db_connection() calls (only if not already fixed)
            elif 'get_db_connection()' in line and 'get_db_connection_connection' not in line:
                new_line = line.replace('get_db_connection()', f'get_db_connection_connection("{database_name}")')
                changed = True
            
            fixed_lines.append(new_line)
        
        if changed:
            # Backup
            with open(filepath + '.bak', 'w', encoding='utf-8') as f:
                f.write(original_content)
            
            # Write fixed
            with open(filepath, 'w', encoding='utf-8') as f:
                f.writelines(fixed_lines)
            
            return True, database_name
        
        return False, None
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False, None

def main():
    print("🔧 Fixed Auto-Fix Script v2")
    print("=" * 60)
    
    files_to_fix = [
        'app/modules/users/models.py',
        'app/modules/users/views.py',
        'app/modules/inventory/assets.py',
        'app/modules/inventory/models.py',
        'app/modules/inventory/storage.py',
        'app/modules/inventory/views.py',
        'app/modules/send/models.py',
        'app/modules/send/reports.py',
        'app/modules/send/storage.py',
        'app/modules/send/views.py',
        'app/modules/fulfillment/insights.py',
        'app/modules/fulfillment/reports.py',
        'app/modules/fulfillment/storage.py',
        'app/modules/fulfillment/views.py',
    ]
    
    fixed = 0
    for filepath in files_to_fix:
        if os.path.exists(filepath):
            was_fixed, db = fix_file(filepath)
            if was_fixed:
                print(f"   ✅ {filepath} → '{db}' database")
                fixed += 1
            else:
                print(f"   ℹ️  {filepath} (already correct)")
        else:
            print(f"   ⚠️  {filepath} (not found)")
    
    print("\n" + "=" * 60)
    print(f"✅ Fixed {fixed} files successfully!")
    print("\nBackups saved as .bak files")

if __name__ == '__main__':
    main()