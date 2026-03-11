"""
Create System User (S1) for Gridline Services
Run this script once after database initialization
"""
import bcrypt
import json
from app.core.database import get_db_connection, init_db

def create_system_user():
    print("=" * 60)
    print("🔧 Gridline Services - System User Creation")
    print("=" * 60)

    print("\n📦 Initializing database...")
    init_db()

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

    print("\n🔐 Hashing password...")
    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    print("💾 Creating user in database...")

    with get_db_connection("core") as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
        if cursor.fetchone():
            print(f"\n❌ User '{username}' already exists!")
            return

        cursor.execute("""
            INSERT INTO users (
                username, email, password_hash,
                first_name, last_name,
                permission_level, module_permissions,
                instance_id, location, is_active,
                created_at, caps
            )
            VALUES (%s, %s, %s, %s, %s, 'S1', %s, NULL, 'Global', 1, CURRENT_TIMESTAMP, %s)
            RETURNING id
        """, (
            username,
            email,
            hashed_password,
            first_name,
            last_name,
            json.dumps(["admin", "horizon", "ledger", "flow", "fulfillment"]),
            json.dumps({"is_system": True})
        ))

        user_id = cursor.fetchone()["id"]

        cursor.execute("""
            INSERT INTO audit_logs (
                action, username, module, details,
                ts_utc, permission_level, user_id
            )
            VALUES ('system_user_created', %s, 'system', 'S1 system user created', CURRENT_TIMESTAMP, 'S1', %s)
        """, (username, user_id))

        print("\n" + "=" * 60)
        print("✅ System User Created Successfully!")
        print("=" * 60)
        print(f"Username:         {username}")
        print(f"Email:            {email}")
        print(f"Permission Level: S1 (System)")
        print(f"User ID:          {user_id}")
        print("=" * 60)