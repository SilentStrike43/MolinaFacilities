from app.core.database import get_db_connection
from app.modules.users.models import get_user_by_username

# Check what get_user_by_username returns
user = get_user_by_username('AppAdmin')

if user:
    print(f"✅ User retrieved: {user.get('username')}")
    print(f"✅ Password hash in result: {bool(user.get('password_hash'))}")
    print(f"✅ Keys in user dict: {list(user.keys())}")
    print(f"✅ Hash value: {user.get('password_hash', 'MISSING')[:50]}...")
else:
    print("❌ get_user_by_username returned None!")

exit()