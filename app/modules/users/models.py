"""
User database models and functions
"""
import sqlite3
import os
import json
from typing import Optional, List, Dict, Any
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

# Database configuration
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "users.sqlite")

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)


def get_db():
    """Get database connection with Row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def users_db():
    """Legacy function for backwards compatibility."""
    return get_db()


def get_user_by_id(user_id: int) -> Optional[sqlite3.Row]:
    """Get user by ID."""
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return user


def get_user_by_username(username: str) -> Optional[sqlite3.Row]:
    """Get user by username."""
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return user


def list_users(include_system: bool = False, include_deleted: bool = False) -> List[sqlite3.Row]:
    """
    List all users with optional filters.
    
    Args:
        include_system: Include system users (S1 level)
        include_deleted: Include deleted users
    
    Returns:
        List of user Row objects
    """
    conn = get_db()
    
    query = "SELECT * FROM users WHERE 1=1"
    params = []
    
    if not include_system:
        query += " AND permission_level != 'S1'"
    
    if not include_deleted:
        query += " AND (deleted_at IS NULL OR deleted_at = '')"
    
    query += " ORDER BY username"
    
    users = conn.execute(query, params).fetchall()
    conn.close()
    return users


def create_user(data: dict) -> int:
    """
    Create a new user.
    
    Args:
        data: Dictionary containing:
            - username (required)
            - password (required)
            - first_name, last_name, email, phone, department, position (optional)
            - permission_level (optional, default '')
            - module_permissions (optional, list, default [])
    
    Returns:
        int: New user ID
    """
    conn = get_db()
    
    # Hash password
    password_hash = generate_password_hash(data['password'])
    
    cursor = conn.execute("""
        INSERT INTO users (
            username, password_hash,
            first_name, last_name, email, phone,
            department, position,
            permission_level, module_permissions,
            created_utc
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        datetime.utcnow().isoformat() + "Z"
    ))
    
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return user_id


def update_user(user_id: int, data: dict) -> bool:
    """
    Update user information.
    
    Args:
        user_id: User ID to update
        data: Dictionary of fields to update
    
    Returns:
        bool: Success status
    """
    conn = get_db()
    
    # Build dynamic update query
    fields = []
    values = []
    
    updateable_fields = [
        'first_name', 'last_name', 'email', 'phone',
        'department', 'position', 'permission_level',
        'module_permissions'
    ]
    
    for field in updateable_fields:
        if field in data:
            fields.append(f"{field} = ?")
            values.append(data[field])
    
    if not fields:
        conn.close()
        return False
    
    # Add last modified timestamp
    fields.append("last_modified_at = ?")
    values.append(datetime.utcnow().isoformat() + "Z")
    
    # Add user_id for WHERE clause
    values.append(user_id)
    
    query = f"UPDATE users SET {', '.join(fields)} WHERE id = ?"
    
    conn.execute(query, values)
    conn.commit()
    conn.close()
    
    return True


def verify_password(user, password: str) -> bool:
    """Verify user password."""
    if not user:
        return False
    
    # Convert Row to dict if needed
    if not isinstance(user, dict):
        user = dict(user)
    
    return check_password_hash(user.get('password_hash', ''), password)

def set_password(user_id: int, new_password: str) -> bool:
    """
    Set a new password for a user.
    
    Args:
        user_id: User ID
        new_password: New plain text password to hash and store
    
    Returns:
        bool: Success status
    """
    conn = get_db()
    
    try:
        password_hash = generate_password_hash(new_password)
        
        conn.execute("""
            UPDATE users 
            SET password_hash = ?,
                last_modified_at = ?
            WHERE id = ?
        """, (
            password_hash,
            datetime.utcnow().isoformat() + "Z",
            user_id
        ))
        
        conn.commit()
        return True
    
    except Exception as e:
        print(f"Error setting password: {e}")
        conn.rollback()
        return False
    
    finally:
        conn.close()


def change_password(user_id: int, old_password: str, new_password: str) -> tuple[bool, str]:
    """
    Change user password after verifying old password.
    
    Args:
        user_id: User ID
        old_password: Current password for verification
        new_password: New password to set
    
    Returns:
        tuple: (success: bool, message: str)
    """
    # Get user
    user = get_user_by_id(user_id)
    if not user:
        return False, "User not found"
    
    # Verify old password
    if not verify_password(user, old_password):
        return False, "Current password is incorrect"
    
    # Set new password
    if set_password(user_id, new_password):
        return True, "Password changed successfully"
    else:
        return False, "Failed to update password"


def reset_password(user_id: int, new_password: str, reset_by: int = None) -> bool:
    """
    Reset user password (admin function, no old password required).
    
    Args:
        user_id: User ID to reset password for
        new_password: New password to set
        reset_by: Admin user ID who performed the reset
    
    Returns:
        bool: Success status
    """
    conn = get_db()
    
    try:
        password_hash = generate_password_hash(new_password)
        
        conn.execute("""
            UPDATE users 
            SET password_hash = ?,
                last_modified_by = ?,
                last_modified_at = ?
            WHERE id = ?
        """, (
            password_hash,
            reset_by,
            datetime.utcnow().isoformat() + "Z",
            user_id
        ))
        
        conn.commit()
        return True
    
    except Exception as e:
        print(f"Error resetting password: {e}")
        conn.rollback()
        return False
    
    finally:
        conn.close()


def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """
    Authenticate a user by username and password.
    
    Args:
        username: Username
        password: Plain text password
    
    Returns:
        User dict if authenticated, None otherwise
    """
    user = get_user_by_username(username)
    
    if not user:
        return None
    
    # Check if user is deleted
    user_dict = dict(user) if not isinstance(user, dict) else user
    if user_dict.get('deleted_at'):
        return None
    
    # Verify password
    if verify_password(user, password):
        return user_dict
    
    return None


def get_user_permissions(user_id: int) -> Dict[str, Any]:
    """
    Get user's permissions as a dictionary.
    
    Args:
        user_id: User ID
    
    Returns:
        Dictionary of permission flags
    """
    user = get_user_by_id(user_id)
    if not user:
        return {}
    
    user_dict = dict(user) if not isinstance(user, dict) else user
    
    # Parse module permissions
    try:
        module_perms = json.loads(user_dict.get('module_permissions', '[]') or '[]')
    except:
        module_perms = []
    
    # Build permissions dict
    perms = {
        'can_send': 'M1' in module_perms,
        'can_inventory': 'M2' in module_perms,
        'can_asset': 'M2' in module_perms,  # Alias
        'can_fulfillment_customer': 'M3A' in module_perms,
        'can_fulfillment_service': 'M3B' in module_perms,
        'can_fulfillment_manager': 'M3C' in module_perms,
    }
    
    # Add admin permissions based on level
    permission_level = user_dict.get('permission_level', '')
    if permission_level:
        perms['is_admin'] = True
        perms['permission_level'] = permission_level
        
        # S1, L3, L2, L1 all have admin access
        if permission_level in ['S1', 'L3', 'L2', 'L1']:
            perms['can_admin_users'] = True
            perms['can_view_audit_logs'] = True
        
        # S1 and L3 can manage system
        if permission_level in ['S1', 'L3']:
            perms['can_manage_system'] = True
    
    # Legacy flags
    if user_dict.get('is_admin'):
        perms['is_admin'] = True
    if user_dict.get('is_sysadmin'):
        perms['is_sysadmin'] = True
    
    return perms


def user_exists(username: str) -> bool:
    """Check if a user exists by username."""
    user = get_user_by_username(username)
    return user is not None


def delete_user(user_id: int, deleted_by: int = None, notes: str = None) -> bool:
    """
    Mark a user as deleted (soft delete).
    
    Args:
        user_id: User ID to delete
        deleted_by: Admin user ID who performed the deletion
        notes: Deletion notes/reason
    
    Returns:
        bool: Success status
    """
    conn = get_db()
    
    try:
        conn.execute("""
            UPDATE users 
            SET deleted_at = ?,
                deletion_approved_by = ?,
                deletion_notes = ?
            WHERE id = ?
        """, (
            datetime.utcnow().isoformat() + "Z",
            deleted_by,
            notes,
            user_id
        ))
        
        conn.commit()
        return True
    
    except Exception as e:
        print(f"Error deleting user: {e}")
        conn.rollback()
        return False
    
    finally:
        conn.close()

def init_db():
    """Initialize the database with required tables."""
    conn = get_db()
    
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            first_name TEXT,
            last_name TEXT,
            email TEXT,
            phone TEXT,
            department TEXT,
            position TEXT,
            permission_level TEXT DEFAULT '',
            module_permissions TEXT DEFAULT '[]',
            elevated_by INTEGER,
            elevated_at TEXT,
            is_admin INTEGER DEFAULT 0,
            is_sysadmin INTEGER DEFAULT 0,
            caps TEXT DEFAULT '{}',
            created_utc TEXT DEFAULT (datetime('now')),
            last_modified_by INTEGER,
            last_modified_at TEXT,
            deletion_requested_at TEXT,
            deleted_at TEXT,
            deletion_approved_by INTEGER,
            deletion_notes TEXT,
            FOREIGN KEY (elevated_by) REFERENCES users(id),
            FOREIGN KEY (last_modified_by) REFERENCES users(id),
            FOREIGN KEY (deletion_approved_by) REFERENCES users(id)
        );
        
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            action TEXT NOT NULL,
            module TEXT NOT NULL,
            details TEXT,
            target_user_id INTEGER,
            target_username TEXT,
            permission_level TEXT,
            ip_address TEXT,
            user_agent TEXT,
            session_id TEXT,
            ts_utc TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (target_user_id) REFERENCES users(id)
        );
        
        CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id, ts_utc DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action, ts_utc DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_logs_module ON audit_logs(module, ts_utc DESC);
        
        CREATE TABLE IF NOT EXISTS deletion_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            reason TEXT,
            status TEXT DEFAULT 'pending',
            requested_at TEXT DEFAULT (datetime('now')),
            approved_by INTEGER,
            approved_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (approved_by) REFERENCES users(id)
        );
        
        CREATE INDEX IF NOT EXISTS idx_deletion_requests_status ON deletion_requests(status, requested_at DESC);
        
        CREATE TABLE IF NOT EXISTS user_elevation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            elevated_by INTEGER NOT NULL,
            old_level TEXT,
            new_level TEXT NOT NULL,
            old_permissions TEXT,
            new_permissions TEXT,
            reason TEXT,
            elevated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (elevated_by) REFERENCES users(id)
        );
        
        CREATE INDEX IF NOT EXISTS idx_elevation_history_user ON user_elevation_history(user_id, elevated_at DESC);
    """)
    
    conn.commit()
    conn.close()


def ensure_user_schema():
    """
    Ensure the user database schema is up to date.
    Creates tables if they don't exist, adds missing columns.
    """
    conn = get_db()
    
    try:
        # First, initialize base tables
        init_db()
        
        # Check if we need to add new columns to existing tables
        cursor = conn.execute("PRAGMA table_info(users)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        
        # Columns that should exist in the new permission system
        required_columns = {
            'permission_level': 'TEXT DEFAULT ""',
            'module_permissions': 'TEXT DEFAULT "[]"',
            'elevated_by': 'INTEGER',
            'elevated_at': 'TEXT',
            'last_modified_by': 'INTEGER',
            'last_modified_at': 'TEXT',
            'deletion_requested_at': 'TEXT',
            'deleted_at': 'TEXT',
            'deletion_approved_by': 'INTEGER',
            'deletion_notes': 'TEXT',
        }
        
        # Add missing columns
        for col_name, col_def in required_columns.items():
            if col_name not in existing_columns:
                try:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
                    print(f"  ✓ Added column: {col_name}")
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        print(f"  ✗ Could not add {col_name}: {e}")
        
        conn.commit()
        print("✓ User schema up to date")
        
    except Exception as e:
        print(f"✗ Error ensuring schema: {e}")
        conn.rollback()
    finally:
        conn.close()


def ensure_first_sysadmin():
    """
    Ensure at least one system administrator exists.
    Creates a default 'admin' user with S1 permissions if no admins exist.
    """
    conn = get_db()
    
    try:
        # Check if any S1 or sysadmin users exist
        cursor = conn.execute("""
            SELECT COUNT(*) FROM users 
            WHERE permission_level = 'S1' 
               OR is_sysadmin = 1
               OR username IN ('admin', 'sysadmin', 'AppAdmin')
        """)
        count = cursor.fetchone()[0]
        
        if count == 0:
            print("\n⚠️  No system administrator found!")
            print("Creating default admin user...")
            
            # Create default admin with S1 permissions
            default_password = "ChangeMe123!"  # User MUST change this
            password_hash = generate_password_hash(default_password)
            
            conn.execute("""
                INSERT INTO users (
                    username, password_hash,
                    first_name, last_name,
                    permission_level, 
                    is_admin, is_sysadmin,
                    caps,
                    created_utc
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                'admin',
                password_hash,
                'System',
                'Administrator',
                'S1',
                1,
                1,
                '{"is_system": true}',
                datetime.utcnow().isoformat() + "Z"
            ))
            
            conn.commit()
            
            print("✓ Default admin user created")
            print(f"  Username: admin")
            print(f"  Password: {default_password}")
            print("  ⚠️  CHANGE THIS PASSWORD IMMEDIATELY!")
        else:
            print(f"✓ Found {count} system administrator(s)")
    
    except Exception as e:
        print(f"✗ Error ensuring sysadmin: {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    # Initialize database if run directly
    ensure_user_schema()
    ensure_first_sysadmin()
    print(f"\n✓ Database ready at {DB_PATH}")