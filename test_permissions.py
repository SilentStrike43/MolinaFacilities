from dotenv import load_dotenv
load_dotenv()

from app.core.database import get_db_connection

# Get ALL users
with get_db_connection("core") as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()
    
    if users:
        print(f"Found {len(users)} user(s):\n")
        for user in users:
            print(f"User ID: {user[0]}")
            print(f"  Username: {user[1]}")
            print(f"  Permission Level: {user[9] if len(user) > 9 else 'N/A'}")
            print(f"  Module Permissions: {user[10] if len(user) > 10 else 'N/A'}")
            print()
    else:
        print("No users found in database!")
    
    cursor.close()