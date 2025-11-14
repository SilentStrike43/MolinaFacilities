"""Check what's being imported where"""
import os

files_to_check = [
    ('app/modules/users/views.py', 13),
    ('app/modules/users/models.py', 9),
]

for filepath, line_num in files_to_check:
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            lines = f.readlines()
            if line_num <= len(lines):
                print(f"\n{filepath} line {line_num}:")
                print(f"  {lines[line_num-1].strip()}")
                # Show context
                for i in range(max(0, line_num-3), min(len(lines), line_num+2)):
                    print(f"  {i+1}: {lines[i].rstrip()}")