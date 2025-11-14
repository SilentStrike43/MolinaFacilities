"""Test PostgreSQL connection"""
from app.core.database import init_connection_pool, get_db_connection_connection, execute_query

def test_connection():
    print("=" * 60)
    print("Testing PostgreSQL Connection")
    print("=" * 60)
    
    # Test 1: Initialize pool
    print("\n1. Initializing connection pool...")
    if init_connection_pool():
        print("   ✓ Connection pool created")
    else:
        print("   ✗ Failed to create pool")
        return False
    
    # Test 2: Test connection
    print("\n2. Testing connection...")
    try:
        with get_db_connection_connection('core') as conn:
            print("   ✓ Connected successfully")
    except Exception as e:
        print(f"   ✗ Connection failed: {e}")
        return False
    
    # Test 3: Query database
    print("\n3. Querying database...")
    result = execute_query(
        "SELECT id, username, permission_level, email FROM users WHERE permission_level = %s",
        ('S1',),
        schema='core'
    )
    
    if result:
        print(f"   ✓ Found {len(result)} S1 user(s)")
        for user in result:
            print(f"      - {user['username']} ({user['email']})")
    else:
        print("   ✗ No results")
        return False
    
    # Test 4: Check schemas
    print("\n4. Checking schemas...")
    schemas = execute_query(
        """SELECT schema_name FROM information_schema.schemata 
           WHERE schema_name IN ('core', 'templates') 
           ORDER BY schema_name""",
        schema='core'
    )
    
    if schemas:
        print(f"   ✓ Found {len(schemas)} schemas:")
        for schema in schemas:
            print(f"      - {schema['schema_name']}")
    
    # Test 5: Check tables
    print("\n5. Checking core tables...")
    tables = execute_query(
        """SELECT table_name FROM information_schema.tables 
           WHERE table_schema = 'core' AND table_type = 'BASE TABLE'
           ORDER BY table_name""",
        schema='core'
    )
    
    if tables:
        print(f"   ✓ Found {len(tables)} tables:")
        for table in tables:
            print(f"      - {table['table_name']}")
    
    print("\n" + "=" * 60)
    print("✓ ALL TESTS PASSED!")
    print("=" * 60)
    return True

if __name__ == "__main__":
    test_connection()