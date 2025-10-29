from dotenv import load_dotenv
load_dotenv()

from app.core.database import get_db_connection

print("Fixing AppAdmin user permissions...")

with get_db_connection("core") as conn:
    cursor = conn.cursor()
    
    # Update the AppAdmin user with correct permissions
    cursor.execute("""
        UPDATE users 
        SET permission_level = 'S1',
            is_admin = 1,
            is_sysadmin = 1,
            module_permissions = '[]',
            caps = '{"is_system": true}',
            location = 'ALL'
        WHERE username = 'AppAdmin'
    """)
    
    conn.commit()
    
    # Verify the update
    cursor.execute("SELECT username, permission_level, module_permissions, location FROM users WHERE username = 'AppAdmin'")
    user = cursor.fetchone()
    
    print("✓ AppAdmin user updated successfully!")
    print(f"  Username: {user[0]}")
    print(f"  Permission Level: {user[1]}")
    print(f"  Module Permissions: {user[2]}")
    print(f"  Location: {user[3]}")
    
    cursor.close()