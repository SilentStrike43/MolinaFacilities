# fix_admin_user.py
"""Fix AppAdmin user with proper bcrypt hash"""

from app.core.database import get_db_connection
import bcrypt

print("🔧 Fixing AppAdmin user with proper bcrypt hash...")

with get_db_connection("core") as conn:
    cursor = conn.cursor()
    
    # Generate proper bcrypt hash
    password = 'AppAdmin2025!'
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    print(f"Generated hash: {password_hash[:50]}...")
    
    # Delete old user
    cursor.execute("DELETE FROM users WHERE username = 'AppAdmin'")
    
    # Create new user with proper hash
    cursor.execute("""
        INSERT INTO users (username, password_hash, first_name, last_name, email, permission_level, location)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, ('AppAdmin', password_hash, 'App', 'Admin', 'admin@gridline.local', 'S1', 'ALL'))
    
    cursor.close()
    print("✅ AppAdmin user fixed with proper bcrypt hash!")

print("\n🎉 You can now login with:")
print("Username: AppAdmin")
print("Password: AppAdmin2025!")