"""Test PostgreSQL connection from Flask"""
import os
from dotenv import load_dotenv
import psycopg2
import psycopg2.extras

load_dotenv()

print("🔌 Testing PostgreSQL Connections...")
print("=" * 50)
print(f"Host: {os.getenv('DB_HOST')}")
print(f"Port: {os.getenv('DB_PORT')}")
print(f"User: {os.getenv('DB_USER')}")
print("=" * 50)
print()

# Test connection to each database
databases = {
    'core': os.getenv('DB_NAME_CORE'),
    'send': os.getenv('DB_NAME_SEND'),
    'inventory': os.getenv('DB_NAME_INVENTORY'),
    'fulfillment': os.getenv('DB_NAME_FULFILLMENT')
}

all_success = True

for db_key, db_name in databases.items():
    try:
        conn = psycopg2.connect(
            host=os.getenv('DB_HOST'),
            port=os.getenv('DB_PORT', 5432),
            database=db_name,
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            cursor_factory=psycopg2.extras.RealDictCursor
        )
        
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM information_schema.tables WHERE table_schema = 'public'")
        result = cursor.fetchone()
        
        print(f"✅ {db_name:25} Connected! ({result['count']} tables)")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ {db_name:25} FAILED: {str(e)}")
        all_success = False

print()
print("=" * 50)
if all_success:
    print("🎉 All databases connected successfully!")
else:
    print("⚠️ Some connections failed. Check credentials.")
print("=" * 50)