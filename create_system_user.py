"""
Create System User (S1) for Gridline Services
Run this script once after database initialization
"""
import bcrypt
import json
from app.core.database import get_db_connection_connection, init_db

def create_system_user():
    """Create the S1 system user."""
    
    print("=" * 60)
    print("🔧 Gridline Services - System User Creation")
    print("=" * 60)
    
    # Initialize database first
    print("\n📦 Initializing database...")
    init_db()
    
    # Get user details
    print("\n👤 Creating S1 System User")
    print("-" * 60)
    
    username = input("Enter username (default: sysadmin): ").strip() or "sysadmin"
    email = input("Enter email (default: admin@gridline.local): ").strip() or "admin@gridline.local"
    password = input("Enter password (min 8 characters): ").strip()
    
    while len(password) < 8:
        print("❌ Password must be at least 8 characters!")
        password = input("Enter password (min 8 characters): ").strip()
    
    first_name = input("Enter first name (default: System): ").strip() or "System"
    last_name = input("Enter last name (default: Administrator): ").strip() or "Administrator"
    
    # Hash password
    print("\n🔐 Hashing password...")
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    # Create user
    print("💾 Creating user in database...")
    
    with get_db_connection_connection() as conn:
        cursor = conn.cursor()
        
        # Check if user already exists
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            print(f"\n❌ User '{username}' already exists!")
            return
        
        # Insert S1 user
        cursor.execute("""
            INSERT INTO users (
                username, email, password_hash,
                first_name, last_name,
                permission_level, module_permissions,
                instance_id, location, is_active,
                created_at, caps
            )
            VALUES (?, ?, ?, ?, ?, 'S1', ?, NULL, 'Global', 1, CURRENT_TIMESTAMP, ?)
        """, (
            username,
            email,
            hashed_password,
            first_name,
            last_name,
            json.dumps(["admin", "horizon", "ledger", "flow", "fulfillment"]),
            json.dumps({"is_system": True})
        ))
        
        user_id = cursor.lastrowid
        
        # Log creation
        cursor.execute("""
            INSERT INTO audit_logs (
                action, username, module, details,
                ts_utc, permission_level, user_id
            )
            VALUES ('system_user_created', ?, 'system', 'S1 system user created', CURRENT_TIMESTAMP, 'S1', ?)
        """, (username, user_id))
        
        conn.commit()
        
        print("\n" + "=" * 60)
        print("✅ System User Created Successfully!")
        print("=" * 60)
        print(f"Username:         {username}")
        print(f"Email:            {email}")
        print(f"Permission Level: S1 (System)")
        print(f"User ID:          {user_id}")
        print(f"\n🔗 Login at: http://localhost:5000/auth/login")
        print("=" * 60)


if __name__ == "__main__":
    try:
        create_system_user()
    except KeyboardInterrupt:
        print("\n\n⚠️  Cancelled by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()