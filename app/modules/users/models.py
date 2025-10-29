"""
User database models and functions - AZURE SQL ONLY
"""
import os
import json
from typing import Optional, List, Dict, Any
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

# Use Azure SQL connection
from app.core.database import get_db_connection

def get_db():
    """
    DEPRECATED: Legacy compatibility function.
    Returns a connection but caller must manage it properly.
    
    New code should use: with get_db_connection("core") as conn:
    """
    from app.core.database import get_db_connection
    return get_db_connection("core").__enter__()

def users_db():
    """
    Legacy compatibility function.
    DO NOT USE - kept only for backward compatibility with existing code.
    Use get_db_connection("core") context manager instead.
    """
    # This is a stub - the actual connection should be managed properly
    # in the calling code using with get_db_connection("core") as conn:
    import warnings
    warnings.warn(
        "users_db() is deprecated. Use 'with get_db_connection(\"core\") as conn:' instead",
        DeprecationWarning,
        stacklevel=2
    )
    return None

def get_user_by_id(user_id: int) -> Optional[Any]:
    """Get user by ID."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        cursor.close()
        return user


def get_user_by_username(username: str) -> Optional[Any]:
    """Get user by username."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        cursor.close()
        return user


def list_users(include_system=False, include_deleted=False):
    """List all users with enhanced filtering."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        query = "SELECT * FROM users WHERE 1=1"
        
        if not include_system:
            query += " AND username NOT IN ('system', 'sysadmin', 'AppAdmin')"
        
        if not include_deleted:
            query += " AND (deleted_at IS NULL OR deleted_at = '')"
        
        query += " ORDER BY username"
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        # Convert rows to dicts before returning
        result = []
        for row in rows:
            row_dict = dict(zip([col[0] for col in cursor.description], row))
            result.append(row_dict)
        
        cursor.close()
        return result


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
                location, created_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, GETUTCDATE())
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
        conn.commit()
        
        # Get last inserted ID
        cursor.execute("SELECT @@IDENTITY")
        user_id = cursor.fetchone()[0]
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
                fields.append(f"{field} = ?")
                if field == 'module_permissions':
                    values.append(json.dumps(data[field]))
                else:
                    values.append(data[field])
        
        if not fields:
            return False
        
        fields.append("last_modified_at = GETUTCDATE()")
        values.append(user_id)
        
        query = f"UPDATE users SET {', '.join(fields)} WHERE id = ?"
        
        cursor = conn.cursor()
        cursor.execute(query, values)
        conn.commit()
        cursor.close()
        
        return True


def verify_password(user, password: str) -> bool:
    """Verify user password."""
    if not user:
        return False
    
    user_dict = dict(zip([col[0] for col in user.cursor_description], user)) if hasattr(user, 'cursor_description') else dict(user)
    return check_password_hash(user_dict.get('password_hash', ''), password)


def set_password(user_id: int, new_password: str) -> bool:
    """Set a new password for a user."""
    with get_db_connection("core") as conn:
        try:
            password_hash = generate_password_hash(new_password)
            
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users 
                SET password_hash = ?,
                    last_modified_at = GETUTCDATE()
                WHERE id = ?
            """, (password_hash, user_id))
            
            conn.commit()
            cursor.close()
            return True
        
        except Exception as e:
            print(f"Error setting password: {e}")
            conn.rollback()
            return False


def change_password(user_id: int, old_password: str, new_password: str) -> tuple[bool, str]:
    """Change user password after verifying old password."""
    user = get_user_by_id(user_id)
    if not user:
        return False, "User not found"
    
    if not verify_password(user, old_password):
        return False, "Current password is incorrect"
    
    if set_password(user_id, new_password):
        return True, "Password changed successfully"
    else:
        return False, "Failed to update password"


def reset_password(user_id: int, new_password: str, reset_by: int = None) -> bool:
    """Reset user password (admin function)."""
    with get_db_connection("core") as conn:
        try:
            password_hash = generate_password_hash(new_password)
            
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users 
                SET password_hash = ?,
                    last_modified_by = ?,
                    last_modified_at = GETUTCDATE()
                WHERE id = ?
            """, (password_hash, reset_by, user_id))
            
            conn.commit()
            cursor.close()
            return True
        
        except Exception as e:
            print(f"Error resetting password: {e}")
            conn.rollback()
            return False


def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """Authenticate a user by username and password."""
    user = get_user_by_username(username)
    
    if not user:
        return None
    
    user_dict = dict(zip([col[0] for col in user.cursor_description], user)) if hasattr(user, 'cursor_description') else dict(user)
    
    if user_dict.get('deleted_at'):
        return None
    
    if verify_password(user, password):
        return user_dict
    
    return None


def get_user_permissions(user_id: int) -> Dict[str, bool]:
    """Get permission flags for a user."""
    user = get_user_by_id(user_id)
    if not user:
        return {}
    
    user_dict = dict(zip([col[0] for col in user.cursor_description], user)) if hasattr(user, 'cursor_description') else dict(user)
    
    try:
        module_perms = json.loads(user_dict.get('module_permissions', '[]') or '[]')
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
    
    permission_level = user_dict.get('permission_level', '')
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
                SET deleted_at = GETUTCDATE(),
                    deletion_approved_by = ?,
                    deletion_notes = ?
                WHERE id = ?
            """, (deleted_by, notes, user_id))
            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"Error deleting user: {e}")
            conn.rollback()
            return False


def ensure_user_schema():
    """Ensure the user database schema exists and is up to date - Azure SQL Server version."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        # Create users table if it doesn't exist
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'users')
            BEGIN
                CREATE TABLE users (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    username NVARCHAR(255) NOT NULL UNIQUE,
                    password_hash NVARCHAR(255) NOT NULL,
                    first_name NVARCHAR(255),
                    last_name NVARCHAR(255),
                    email NVARCHAR(255),
                    phone NVARCHAR(50),
                    department NVARCHAR(255),
                    position NVARCHAR(255),
                    permission_level NVARCHAR(50) DEFAULT '',
                    module_permissions NVARCHAR(MAX) DEFAULT '[]',
                    location NVARCHAR(50) DEFAULT 'NY',
                    elevated_by INT,
                    elevated_at DATETIME2,
                    is_admin BIT DEFAULT 0,
                    is_sysadmin BIT DEFAULT 0,
                    caps NVARCHAR(MAX) DEFAULT '{}',
                    created_utc DATETIME2 DEFAULT GETUTCDATE(),
                    last_modified_by INT,
                    last_modified_at DATETIME2,
                    deletion_requested_at DATETIME2,
                    deleted_at DATETIME2,
                    deletion_approved_by INT,
                    deletion_notes NVARCHAR(MAX)
                )
            END
        """)
        conn.commit()
        
        # Add missing columns if they don't exist
        missing_columns = {
            'permission_level': 'NVARCHAR(50) DEFAULT \'\'',
            'module_permissions': 'NVARCHAR(MAX) DEFAULT \'[]\'',
            'location': 'NVARCHAR(50) DEFAULT \'NY\'',
            'elevated_by': 'INT',
            'elevated_at': 'DATETIME2',
            'is_admin': 'BIT DEFAULT 0',
            'is_sysadmin': 'BIT DEFAULT 0',
            'caps': 'NVARCHAR(MAX) DEFAULT \'{}\'',
            'last_modified_by': 'INT',
            'last_modified_at': 'DATETIME2',
            'deletion_requested_at': 'DATETIME2',
            'deleted_at': 'DATETIME2',
            'deletion_approved_by': 'INT',
            'deletion_notes': 'NVARCHAR(MAX)'
        }
        
        for col_name, col_def in missing_columns.items():
            try:
                cursor.execute(f"""
                    IF NOT EXISTS (
                        SELECT * FROM sys.columns 
                        WHERE object_id = OBJECT_ID('users') 
                        AND name = '{col_name}'
                    )
                    BEGIN
                        ALTER TABLE users ADD {col_name} {col_def}
                    END
                """)
                conn.commit()
            except Exception as e:
                print(f"  Note: Could not add column {col_name}: {e}")
        
        # Create audit_logs table if it doesn't exist
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'audit_logs')
            BEGIN
                CREATE TABLE audit_logs (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    user_id INT NOT NULL,
                    username NVARCHAR(255) NOT NULL,
                    action NVARCHAR(255) NOT NULL,
                    module NVARCHAR(255) NOT NULL,
                    details NVARCHAR(MAX),
                    target_user_id INT,
                    target_username NVARCHAR(255),
                    permission_level NVARCHAR(50),
                    ip_address NVARCHAR(50),
                    user_agent NVARCHAR(MAX),
                    session_id NVARCHAR(255),
                    ts_utc DATETIME2 DEFAULT GETUTCDATE()
                )
                CREATE INDEX idx_audit_logs_user ON audit_logs(user_id, ts_utc DESC)
                CREATE INDEX idx_audit_logs_action ON audit_logs(action, ts_utc DESC)
                CREATE INDEX idx_audit_logs_module ON audit_logs(module, ts_utc DESC)
            END
        """)
        conn.commit()
        
        cursor.close()
        print("✓ User schema initialized")


def ensure_first_sysadmin():
    """Ensure at least one system administrator exists."""
    with get_db_connection("core") as conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM users 
                WHERE permission_level = 'S1' 
                   OR is_sysadmin = 1
                   OR username IN ('admin', 'sysadmin', 'AppAdmin')
            """)
            count = cursor.fetchone()[0]
            
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
                        created_utc
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, GETUTCDATE())
                """, (
                    'admin',
                    password_hash,
                    'System',
                    'Administrator',
                    'S1',
                    1,
                    1,
                    '{"is_system": true}'
                ))
                
                conn.commit()
                
                print("✓ Default admin user created")
                print(f"  Username: admin")
                print(f"  Password: {default_password}")
                print("  ⚠️  CHANGE THIS PASSWORD IMMEDIATELY!")
            else:
                print(f"✓ Found {count} system administrator(s)")
            
            cursor.close()
        
        except Exception as e:
            print(f"✗ Error ensuring sysadmin: {e}")
            conn.rollback()


if __name__ == "__main__":
    ensure_user_schema()
    ensure_first_sysadmin()
    print("\n✓ Database ready")