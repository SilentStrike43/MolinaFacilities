# app/modules/users/models.py
"""
User management models - PostgreSQL Edition
"""
import os
import json
from typing import Optional, Dict, Any, List
from werkzeug.security import generate_password_hash, check_password_hash
from app.core.database import get_db_connection

def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """Get user by ID."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """Get user by username."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        row = cursor.fetchone()
        cursor.close()
        return dict(row) if row else None


def list_users(include_system=False, include_deleted=False) -> List[Dict[str, Any]]:
    """List all users."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        query = "SELECT * FROM users WHERE 1=1"
        
        if not include_system:
            query += " AND username NOT IN ('system', 'sysadmin', 'AppAdmin')"
        
        if not include_deleted:
            query += " AND deleted_at IS NULL"
        
        query += " ORDER BY username"
        
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
        return [dict(row) for row in rows]


def create_user(data: dict) -> int:
    """Create a new user."""
    with get_db_connection("core") as conn:
        password_hash = generate_password_hash(data['password'])
        
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (
                username, password_hash,
                first_name, last_name, email, phone,
                department, position,
                permission_level, module_permissions,
                location, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            RETURNING id
        """, (
            data['username'],
            password_hash,
            data.get('first_name', ''),
            data.get('last_name', ''),
            data.get('email', ''),
            data.get('phone', ''),
            data.get('department', ''),
            data.get('position', ''),
            data.get('permission_level', ''),
            json.dumps(data.get('module_permissions', [])),
            data.get('location', 'NY')
        ))
        
        user_id = cursor.fetchone()['id']
        cursor.close()
        return int(user_id)


def update_user(user_id: int, data: dict) -> bool:
    """Update user information."""
    with get_db_connection("core") as conn:
        fields = []
        values = []
        
        updateable_fields = [
            'first_name', 'last_name', 'email', 'phone',
            'department', 'position', 'permission_level',
            'module_permissions', 'location'
        ]
        
        for field in updateable_fields:
            if field in data:
                fields.append(f"{field} = %s")
                if field == 'module_permissions':
                    values.append(json.dumps(data[field]))
                else:
                    values.append(data[field])
        
        if not fields:
            return False
        
        fields.append("last_modified_at = CURRENT_TIMESTAMP")
        values.append(user_id)
        
        query = f"UPDATE users SET {', '.join(fields)} WHERE id = %s"
        
        cursor = conn.cursor()
        cursor.execute(query, values)
        cursor.close()
        
        return True


def verify_password(user_dict: Dict[str, Any], password: str) -> bool:
    """Verify password against stored hash (supports both bcrypt and werkzeug)."""
    password_hash = user_dict.get('password_hash', '')
    
    if not password_hash:
        return False
    
    # Check if it's a bcrypt hash (starts with $2b$ or $2a$ or $2y$)
    if password_hash.startswith('$2'):
        import bcrypt
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    else:
        # Werkzeug format
        return check_password_hash(password_hash, password)


def set_password(user_id: int, new_password: str, reset_by: int = None) -> bool:
    """Set a new password for a user."""
    with get_db_connection("core") as conn:
        try:
            password_hash = generate_password_hash(new_password)
            
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users 
                SET password_hash = %s,
                    last_modified_at = CURRENT_TIMESTAMP,
                    last_modified_by = %s
                WHERE id = %s
            """, (password_hash, reset_by, user_id))
            
            cursor.close()
            return True
        
        except Exception as e:
            print(f"Error resetting password: {e}")
            return False


def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """Authenticate a user by username and password."""
    user = get_user_by_username(username)
    
    if not user:
        return None
    
    if user.get('deleted_at'):
        return None
    
    if verify_password(user, password):
        return user
    
    return None


def get_user_permissions(user_id: int) -> Dict[str, bool]:
    """Get permission flags for a user."""
    user = get_user_by_id(user_id)
    if not user:
        return {}
    
    try:
        module_perms = json.loads(user.get('module_permissions', '[]') or '[]')
    except:
        module_perms = []
    
    perms = {
        'can_send': 'M1' in module_perms,
        'can_inventory': 'M2' in module_perms,
        'can_asset': 'M2' in module_perms,
        'can_fulfillment_customer': 'M3A' in module_perms,
        'can_fulfillment_service': 'M3B' in module_perms,
        'can_fulfillment_manager': 'M3C' in module_perms,
    }
    
    permission_level = user.get('permission_level', '')
    if permission_level:
        perms['is_admin'] = True
        perms['permission_level'] = permission_level
        
        if permission_level in ['S1', 'L3', 'L2', 'L1']:
            perms['can_admin_users'] = True
            perms['can_view_audit_logs'] = True
        
        if permission_level in ['S1', 'L3']:
            perms['can_manage_system'] = True
    
    return perms


def user_exists(username: str) -> bool:
    """Check if a user exists by username."""
    user = get_user_by_username(username)
    return user is not None


def delete_user(user_id: int, deleted_by: int = None, notes: str = None) -> bool:
    """Mark a user as deleted (soft delete)."""
    with get_db_connection("core") as conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users 
                SET deleted_at = CURRENT_TIMESTAMP,
                    deletion_approved_by = %s,
                    deletion_notes = %s
                WHERE id = %s
            """, (deleted_by, notes, user_id))
            cursor.close()
            return True
        except Exception as e:
            print(f"Error deleting user: {e}")
            return False


def ensure_user_schema():
    """Ensure the user database schema exists - PostgreSQL version."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        # Create users table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                first_name VARCHAR(255),
                last_name VARCHAR(255),
                email VARCHAR(255),
                phone VARCHAR(50),
                department VARCHAR(255),
                position VARCHAR(255),
                permission_level VARCHAR(50) DEFAULT '',
                module_permissions TEXT DEFAULT '[]',
                location VARCHAR(50) DEFAULT 'NY',
                elevated_by INTEGER,
                elevated_at TIMESTAMP,
                is_admin BOOLEAN DEFAULT FALSE,
                is_sysadmin BOOLEAN DEFAULT FALSE,
                caps TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_modified_by INTEGER,
                last_modified_at TIMESTAMP,
                deletion_requested_at TIMESTAMP,
                deleted_at TIMESTAMP,
                deletion_approved_by INTEGER,
                deletion_notes TEXT
            )
        """)
        
        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_permission ON users(permission_level)
        """)
        
        # Create audit_logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id SERIAL PRIMARY KEY,
                user_id INTEGER,
                username VARCHAR(255) NOT NULL,
                action VARCHAR(255) NOT NULL,
                module VARCHAR(255) NOT NULL,
                details TEXT,
                target_user_id INTEGER,
                target_username VARCHAR(255),
                permission_level VARCHAR(50),
                ip_address VARCHAR(50),
                user_agent TEXT,
                session_id VARCHAR(255),
                ts_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create audit indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id, ts_utc DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action, ts_utc DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_logs_module ON audit_logs(module, ts_utc DESC)
        """)
        
        cursor.close()
        print("✓ User schema initialized")


def ensure_first_sysadmin():
    """Ensure at least one system administrator exists."""
    with get_db_connection("core") as conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) as count FROM users 
                WHERE permission_level = 'S1' 
                   OR is_sysadmin = TRUE
                   OR username IN ('admin', 'sysadmin', 'AppAdmin')
            """)
            count = cursor.fetchone()['count']
            
            if count == 0:
                print("\n⚠️  No system administrator found!")
                print("Creating default admin user...")
                
                default_password = "ChangeMe123!"
                password_hash = generate_password_hash(default_password)
                
                cursor.execute("""
                    INSERT INTO users (
                        username, password_hash,
                        first_name, last_name,
                        permission_level, 
                        is_admin, is_sysadmin,
                        caps,
                        created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                """, (
                    'admin',
                    password_hash,
                    'System',
                    'Administrator',
                    'S1',
                    True,
                    True,
                    '{"is_system": true}'
                ))
                
                print("✓ Default admin user created")
                print(f"  Username: admin")
                print(f"  Password: {default_password}")
                print("  ⚠️  CHANGE THIS PASSWORD IMMEDIATELY!")
            else:
                print(f"✓ Found {count} system administrator(s)")
            
            cursor.close()
        
        except Exception as e:
            print(f"✗ Error ensuring sysadmin: {e}")


if __name__ == "__main__":
    ensure_user_schema()
    ensure_first_sysadmin()
    print("\n✓ Database ready")