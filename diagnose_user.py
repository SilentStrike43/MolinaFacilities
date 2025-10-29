from dotenv import load_dotenv
load_dotenv()

from app.core.database import get_db_connection

print("Diagnosing user table...")

with get_db_connection("core") as conn:
    cursor = conn.cursor()
    
    # Get column names
    cursor.execute("SELECT TOP 1 * FROM users")
    columns = [col[0] for col in cursor.description]  # FIX: description not cursor_description
    print(f"\nTable columns: {columns}\n")
    
    # Get all users with explicit column selection
    cursor.execute("""
        SELECT id, username, permission_level, module_permissions, 
               is_admin, is_sysadmin, location, caps
        FROM users
    """)
    users = cursor.fetchall()
    
    if users:
        print(f"Found {len(users)} user(s):\n")
        for user in users:
            print(f"User ID: {user[0]}")
            print(f"  Username: {user[1]}")
            print(f"  Permission Level: '{user[2]}'")
            print(f"  Module Permissions: {user[3]}")
            print(f"  is_admin: {user[4]}")
            print(f"  is_sysadmin: {user[5]}")
            print(f"  Location: {user[6]}")
            print(f"  Caps: {user[7]}")
            print()
    
    # Try direct update again with verification
    print("Attempting UPDATE...")
    cursor.execute("""
        UPDATE users 
        SET permission_level = 'S1'
        WHERE username = 'AppAdmin'
    """)
    rows_affected = cursor.rowcount
    print(f"Rows affected: {rows_affected}")
    conn.commit()
    
    # Verify immediately
    cursor.execute("SELECT username, permission_level FROM users WHERE username = 'AppAdmin'")
    result = cursor.fetchone()
    print(f"After update: {result[0]} has permission_level = '{result[1]}'")
    
    cursor.close()