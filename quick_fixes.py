"""
Quick diagnostic and fix helper for Gridline Services
"""
import os
from dotenv import load_dotenv

load_dotenv()

print("🔍 Diagnosing Gridline Services Issues")
print("=" * 60)

# Check 1: Environment variables
print("\n1️⃣ Checking environment variables...")
db_host = os.getenv('DB_HOST')
db_user = os.getenv('DB_USER')
db_pass = os.getenv('DB_PASSWORD')
db_port = os.getenv('DB_PORT')

print(f"   DB_HOST: {db_host}")
print(f"   DB_USER: {db_user}")
print(f"   DB_PASSWORD: {'*' * len(db_pass) if db_pass else 'NOT SET'}")
print(f"   DB_PORT: {db_port}")

if not db_pass:
    print("   ❌ DB_PASSWORD is not set!")
else:
    print("   ✅ Environment variables loaded")

# Check 2: Database connection
print("\n2️⃣ Testing database connection...")
try:
    import psycopg2
    conn = psycopg2.connect(
        host=db_host or 'localhost',
        port=db_port or 5432,
        database='gridline_core',
        user=db_user or 'postgres',
        password=db_pass
    )
    print("   ✅ Direct connection successful!")
    conn.close()
except Exception as e:
    print(f"   ❌ Direct connection failed: {e}")

# Check 3: Find syntax errors
print("\n3️⃣ Checking for syntax errors...")
import ast
import os

files_to_check = [
    'app/modules/inventory/views.py',
    'app/modules/users/models.py',
    'app/modules/users/views.py'
]

for filepath in files_to_check:
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                ast.parse(f.read())
            print(f"   ✅ {filepath} - No syntax errors")
        except SyntaxError as e:
            print(f"   ❌ {filepath} - Line {e.lineno}: {e.msg}")
    else:
        print(f"   ⚠️  {filepath} - File not found")

# Check 4: Find get_db_connection imports
print("\n4️⃣ Searching for old 'get_db_connection' imports...")
search_dirs = ['app/modules/users', 'app/modules/inventory', 'app/modules/send', 'app/modules/fulfillment']

for search_dir in search_dirs:
    if os.path.exists(search_dir):
        for root, dirs, files in os.walk(search_dir):
            for file in files:
                if file.endswith('.py'):
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            content = f.read()
                            if 'from app.core.database import get_db_connection' in content or 'import get_db_connection' in content:
                                print(f"   ⚠️  Found in: {filepath}")
                    except:
                        pass

print("\n" + "=" * 60)
print("Diagnostic complete!")