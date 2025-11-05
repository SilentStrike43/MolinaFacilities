#!/usr/bin/env python3
"""
Automatic AzureSQL to PostgreSQL syntax converter
Converts all SQL syntax in Python files from Azure SQL Server to PostgreSQL
"""
import os
import re
import sys
from pathlib import Path

class SQLConverter:
    def __init__(self):
        self.changes_made = 0
    
    def convert_placeholders(self, content):
        """Convert ? placeholders to %s in SQL queries."""
        # Pattern: Find cursor.execute() calls and replace ? with %s inside them
        def replace_in_query(match):
            full_match = match.group(0)
            # Count how many ? to replace
            return full_match.replace('?', '%s')
        
        # Match cursor.execute with triple quotes
        content = re.sub(
            r'cursor\.execute\(\s*""".*?"""\s*(?:,|\))',
            replace_in_query,
            content,
            flags=re.DOTALL
        )
        
        # Match cursor.execute with single quotes
        content = re.sub(
            r"cursor\.execute\(\s*'''.*?'''\s*(?:,|\))",
            replace_in_query,
            content,
            flags=re.DOTALL
        )
        
        # Match cursor.execute with double quotes (single line)
        content = re.sub(
            r'cursor\.execute\(\s*"[^"]*"\s*(?:,|\))',
            replace_in_query,
            content
        )
        
        # Match cursor.execute with single quotes (single line)
        content = re.sub(
            r"cursor\.execute\(\s*'[^']*'\s*(?:,|\))",
            replace_in_query,
            content
        )
        
        return content
    
    def convert_date_functions(self, content):
        """Convert SQL Server date functions to PostgreSQL."""
        content = content.replace('GETUTCDATE()', 'CURRENT_TIMESTAMP')
        content = content.replace('GETDATE()', 'CURRENT_TIMESTAMP')
        content = re.sub(r'CAST\(([^)]+) AS DATE\)', r'DATE(\1)', content)
        return content
    
    def convert_top_to_limit(self, content):
        """Convert TOP n to LIMIT n."""
        # Pattern: SELECT TOP n ... ORDER BY ... → SELECT ... ORDER BY ... LIMIT n
        def replace_top(match):
            select_part = match.group(1)
            top_num = match.group(2)
            rest = match.group(3)
            
            # Add LIMIT at the end if ORDER BY exists
            if 'ORDER BY' in rest:
                # Find the end of the ORDER BY clause
                rest = re.sub(r'(ORDER BY [^\n;]+)', rf'\1 LIMIT {top_num}', rest, count=1)
                return f'{select_part}{rest}'
            else:
                # No ORDER BY, add LIMIT before WHERE/newline/semicolon
                rest = re.sub(r'(\s+WHERE|\n|;|$)', rf' LIMIT {top_num}\1', rest, count=1)
                return f'{select_part}{rest}'
        
        content = re.sub(
            r'(SELECT)\s+TOP\s+(\d+)\s+(.*?)(?=\s*(?:cursor\.execute|"""|\'\'\'|$))',
            replace_top,
            content,
            flags=re.DOTALL
        )
        
        return content
    
    def convert_identity(self, content):
        """Convert SELECT @@IDENTITY to RETURNING id pattern."""
        # Pattern 1: Remove standalone SELECT @@IDENTITY lines
        content = re.sub(
            r'\s*cursor\.execute\(\s*["\']SELECT @@IDENTITY["\']\s*\)\s*\n',
            '',
            content
        )
        
        # Pattern 2: Convert INSERT + @@IDENTITY to INSERT...RETURNING
        # Find INSERT statements followed by @@IDENTITY
        lines = content.split('\n')
        new_lines = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # Check if this is an INSERT statement
            if 'cursor.execute' in line and 'INSERT INTO' in line:
                # Look ahead for SELECT @@IDENTITY
                if i + 1 < len(lines) and '@@IDENTITY' in lines[i + 1]:
                    # This INSERT needs RETURNING id
                    # Add RETURNING id before the closing quote
                    if '"""' in line:
                        line = line.replace('""")', ' RETURNING id""")', 1)
                        if ' RETURNING id' not in line:
                            line = line.replace('"""', ' RETURNING id"""', 1)
                    elif "'''" in line:
                        line = line.replace("''')", " RETURNING id''')", 1)
                        if ' RETURNING id' not in line:
                            line = line.replace("'''", " RETURNING id'''", 1)
                    elif line.strip().endswith('")') or line.strip().endswith("')"):
                        # Single line query
                        if '")' in line:
                            line = line.replace('")', ' RETURNING id")', 1)
                        elif "')" in line:
                            line = line.replace("')", " RETURNING id')", 1)
                    
                    new_lines.append(line)
                    
                    # Skip the @@IDENTITY line
                    i += 1
                    
                    # Update the variable assignment line if it exists
                    if i + 1 < len(lines):
                        next_line = lines[i + 1]
                        # Change [0] to ['id']
                        next_line = re.sub(r'fetchone\(\)\[0\]', "fetchone()['id']", next_line)
                        new_lines.append(next_line)
                        i += 1
                    
                    i += 1
                    continue
            
            new_lines.append(line)
            i += 1
        
        content = '\n'.join(new_lines)
        return content
    
    def convert_nvarchar_to_varchar(self, content):
        """Convert NVARCHAR to VARCHAR in schema definitions."""
        content = re.sub(r'\bNVARCHAR\b', 'VARCHAR', content)
        content = re.sub(r'\bNVARCHAR\(MAX\)', 'TEXT', content)
        return content
    
    def convert_bit_to_boolean(self, content):
        """Convert BIT to BOOLEAN."""
        content = re.sub(r'\bBIT\b', 'BOOLEAN', content)
        return content
    
    def convert_datetime_to_timestamp(self, content):
        """Convert DATETIME2 to TIMESTAMP."""
        content = re.sub(r'\bDATETIME2\b', 'TIMESTAMP', content)
        return content
    
    def convert_identity_to_serial(self, content):
        """Convert IDENTITY(1,1) to SERIAL."""
        content = re.sub(r'\bINT IDENTITY\(1,1\)', 'SERIAL', content)
        content = re.sub(r'\bINTEGER IDENTITY\(1,1\)', 'SERIAL', content)
        return content
    
    def convert_file(self, filepath):
        """Convert a single file."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"  ❌ Error reading {filepath}: {e}")
            return False
        
        original_content = content
        
        # Apply all conversions
        content = self.convert_placeholders(content)
        content = self.convert_date_functions(content)
        content = self.convert_identity(content)
        content = self.convert_top_to_limit(content)
        content = self.convert_nvarchar_to_varchar(content)
        content = self.convert_bit_to_boolean(content)
        content = self.convert_datetime_to_timestamp(content)
        content = self.convert_identity_to_serial(content)
        
        if content != original_content:
            # Create backup
            backup_path = str(filepath) + '.azure_backup'
            try:
                with open(backup_path, 'w', encoding='utf-8') as f:
                    f.write(original_content)
                
                # Write converted content
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                self.changes_made += 1
                print(f"  ✅ Converted: {filepath.name}")
                return True
            except Exception as e:
                print(f"  ❌ Error writing {filepath}: {e}")
                return False
        else:
            print(f"  ⚪ No changes: {filepath.name}")
            return False
    
    def convert_directory(self, directory):
        """Convert all Python files in a directory."""
        path = Path(directory)
        
        if not path.exists():
            print(f"  ⚠️  Directory not found: {directory}")
            return 0
        
        print(f"\n📁 Processing: {directory}")
        
        converted = 0
        for filepath in path.glob('*.py'):
            if filepath.name == '__init__.py':
                continue
            
            if self.convert_file(filepath):
                converted += 1
        
        return converted
    
    def run(self):
        """Run conversion on all target directories."""
        directories = [
            'app/modules/users',
            'app/modules/admin',
            'app/modules/fulfillment',
            'app/modules/inventory',
            'app/modules/send',
            'app/modules/auth'
        ]
        
        print("\n" + "="*70)
        print("  🔄 AzureSQL → PostgreSQL Converter")
        print("="*70)
        
        total_converted = 0
        
        for directory in directories:
            total_converted += self.convert_directory(directory)
        
        print("\n" + "="*70)
        print(f"  ✅ Conversion Complete!")
        print(f"  📝 Files converted: {self.changes_made}")
        print("="*70)
        
        if self.changes_made > 0:
            print("\n💡 Next steps:")
            print("  1. Review changes: git diff")
            print("  2. Test the application")
            print("  3. Delete backups: find app/modules -name '*.azure_backup' -delete")
            print("  4. If issues: find app/modules -name '*.azure_backup' -exec bash -c 'mv \"$1\" \"${1%.azure_backup}\"' _ {} \\;")


def main():
    print("\n" + "="*70)
    print("  AzureSQL → PostgreSQL Automated Converter")
    print("="*70)
    print("\n  ⚠️  This will modify Python files in app/modules/")
    print("  📦 Backups will be created with .azure_backup extension")
    print("  🔍 The following conversions will be applied:")
    print("     • ? → %s (query placeholders)")
    print("     • GETUTCDATE() → CURRENT_TIMESTAMP")
    print("     • SELECT @@IDENTITY → RETURNING id")
    print("     • TOP n → LIMIT n")
    print("     • NVARCHAR → VARCHAR")
    print("     • BIT → BOOLEAN")
    print("     • DATETIME2 → TIMESTAMP")
    
    response = input("\n  Continue? [y/N]: ")
    
    if response.lower() in ['y', 'yes']:
        converter = SQLConverter()
        converter.run()
    else:
        print("\n  ❌ Cancelled.")
        sys.exit(0)


if __name__ == '__main__':
    main()