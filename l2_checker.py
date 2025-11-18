# l2_checker.py - FIXED VERSION
from app.core.database import get_db_connection

print("=" * 60)
print("🔍 INSTANCE USER DIAGNOSTIC")
print("=" * 60)

with get_db_connection("core") as conn:
    cursor = conn.cursor()
    
    # 1. Check Molina instances
    print("\n📍 INSTANCE CHECK:")
    cursor.execute("""
        SELECT id, name, display_name, is_active, created_at
        FROM instances
        WHERE name ILIKE '%molina%' OR display_name ILIKE '%molina%'
    """)
    instances = cursor.fetchall()
    
    for inst in instances:
        print(f"   ID: {inst['id']}")
        print(f"   Name: {inst['name']}")
        print(f"   Display: {inst['display_name']}")
        print(f"   Active: {inst['is_active']}")
        print()
    
    # 2. Check ALL users in database
    print("\n👥 ALL USERS IN DATABASE:")
    cursor.execute("""
        SELECT id, username, instance_id, permission_level, 
               is_active, deleted_at
        FROM users
        ORDER BY instance_id NULLS LAST, username
    """)
    all_users = cursor.fetchall()
    
    print(f"   Total users: {len(all_users)}\n")
    
    for user in all_users:
        deleted = " [DELETED]" if user['deleted_at'] else ""
        active = "✅" if user['is_active'] else "❌"
        inst_id = str(user['instance_id']) if user['instance_id'] is not None else "None"
        perm = user['permission_level'] or 'Module'
        print(f"   {active} {user['username']:15} | Instance: {inst_id:>4} | Level: {perm:>6}{deleted}")
    
    # 3. Check users specifically for Molina NY (instance 5)
    print("\n\n🏢 USERS IN MOLINA NY (instance_id = 5):")
    cursor.execute("""
        SELECT id, username, permission_level, is_active, deleted_at
        FROM users
        WHERE instance_id = 5
        ORDER BY username
    """)
    molina_users = cursor.fetchall()
    
    if molina_users:
        for user in molina_users:
            deleted = " [DELETED]" if user['deleted_at'] else ""
            perm = user['permission_level'] or 'Module User'
            print(f"   - {user['username']} ({perm}){deleted}")
    else:
        print("   ❌ NO USERS FOUND!")
    
    # 4. Check what the user list query actually returns
    print("\n\n🔎 WHAT USER LIST QUERY RETURNS (excluding L3/S1):")
    cursor.execute("""
        SELECT id, username, permission_level, is_active, deleted_at
        FROM users
        WHERE instance_id = 5
        AND permission_level NOT IN ('L3', 'S1')
        AND deleted_at IS NULL
        ORDER BY username
    """)
    filtered_users = cursor.fetchall()
    
    print(f"   Query found: {len(filtered_users)} users")
    if filtered_users:
        for user in filtered_users:
            perm = user['permission_level'] or 'Module User'
            print(f"   ✅ {user['username']} ({perm})")
    else:
        print("   ❌ QUERY RETURNS NOTHING!")
    
    # 5. Check if molinaadmin shows without filter
    print("\n\n🔍 CHECKING molinaadmin SPECIFICALLY:")
    cursor.execute("""
        SELECT id, username, instance_id, permission_level, 
               is_active, deleted_at
        FROM users
        WHERE username = 'molinaadmin'
    """)
    molina_check = cursor.fetchone()
    
    if molina_check:
        print(f"   ✅ Found molinaadmin:")
        print(f"      - ID: {molina_check['id']}")
        print(f"      - Instance ID: {molina_check['instance_id']}")
        print(f"      - Permission Level: '{molina_check['permission_level']}'")
        print(f"      - Active: {molina_check['is_active']}")
        print(f"      - Deleted: {molina_check['deleted_at']}")
        
        # Check if it would pass the filter
        perm = molina_check['permission_level']
        if perm in ['L3', 'S1']:
            print(f"      ⚠️  FILTERED OUT: Level is {perm} (excluded from instance lists)")
        elif perm in ['L2', 'L1', '', None]:
            print(f"      ✅ SHOULD SHOW: Level is {perm or 'Module User'}")
    else:
        print("   ❌ molinaadmin not found!")
    
    # 6. Check user_instance_access
    print("\n\n🔗 USER-INSTANCE ACCESS RECORDS:")
    cursor.execute("""
        SELECT uia.user_id, u.username, uia.instance_id, i.name as instance_name
        FROM user_instance_access uia
        JOIN users u ON uia.user_id = u.id
        JOIN instances i ON uia.instance_id = i.id
        ORDER BY uia.instance_id, u.username
    """)
    access_records = cursor.fetchall()
    
    if access_records:
        for rec in access_records:
            print(f"   - {rec['username']} → {rec['instance_name']} (ID: {rec['instance_id']})")
    else:
        print("   ❌ NO ACCESS RECORDS FOUND!")
    
    cursor.close()

print("\n" + "=" * 60)