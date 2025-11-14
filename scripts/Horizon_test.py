# Horizon_test.py
"""Quick Horizon integration test"""
import sys
sys.path.insert(0, '.')

from app.app import create_app  # ← Changed from 'from app import create_app'
from app.core.database import get_db_connection_connection

print("🧪 Testing Horizon Integration\n")

# Test 1: App creation
print("1️⃣ Creating Flask app...")
try:
    app = create_app()
    print("   ✅ App created successfully")
except Exception as e:
    print(f"   ❌ Failed: {e}")
    sys.exit(1)

# Test 2: Horizon blueprint registered
print("\n2️⃣ Checking Horizon blueprint...")
try:
    if 'horizon' in [bp.name for bp in app.blueprints.values()]:
        print("   ✅ Horizon blueprint registered")
    else:
        print("   ❌ Horizon blueprint NOT found")
except Exception as e:
    print(f"   ❌ Failed: {e}")

# Test 3: Database connection
print("\n3️⃣ Testing database connection...")
try:
    with get_db_connection_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM instances")
        count = cursor.fetchone()[0]
        print(f"   ✅ Connected! Found {count} instances")
        cursor.close()
except Exception as e:
    print(f"   ❌ Failed: {e}")

# Test 4: Check admin users
print("\n4️⃣ Checking admin users...")
try:
    with get_db_connection_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT username, permission_level 
            FROM users 
            WHERE permission_level IN ('L3', 'S1')
        """)
        admins = cursor.fetchall()
        if admins:
            print(f"   ✅ Found {len(admins)} admin users:")
            for admin in admins:
                print(f"      - {admin['username']} ({admin['permission_level']})")
        else:
            print("   ⚠️  No admin users found - run the SQL to create them")
        cursor.close()
except Exception as e:
    print(f"   ❌ Failed: {e}")

# Test 5: Test Horizon imports
print("\n5️⃣ Testing Horizon module imports...")
try:
    from app.modules.horizon import bp as horizon_bp
    print(f"   ✅ Horizon blueprint imported: {horizon_bp.name}")
    
    from app.modules.horizon.models import get_all_instances
    print(f"   ✅ Horizon models imported")
    
    from app.modules.horizon.filters import register_filters
    print(f"   ✅ Horizon filters imported")
    
except Exception as e:
    print(f"   ❌ Horizon imports failed: {e}")

print("\n" + "="*60)
print("✅ Integration test complete!")
print("\nNext steps:")
print("  1. Run SQL to create admin users (if not done)")
print("  2. Run 'python app.py' to start the server")
print("  3. Login as AppAdmin")
print("  4. Visit http://localhost:5000/horizon")
print("="*60)