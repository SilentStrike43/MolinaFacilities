# app/modules/users/models.py
"""
User management models - PostgreSQL Edition
"""
import logging
import os
import json
from typing import Optional, Dict, Any, List
from werkzeug.security import generate_password_hash, check_password_hash
from app.core.database import get_db_connection

logger = logging.getLogger(__name__)

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
            logger.error(f"Error resetting password for user {user_id}: {e}", exc_info=True)
            return False


_MAX_FAILED_ATTEMPTS = 5
_LOCKOUT_MINUTES = 15


def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """
    Authenticate a user by username and password.

    Returns:
        user dict on success
        {'locked': True, 'locked_until': datetime} if account is locked
        None on bad credentials or non-existent / deleted user
    """
    from datetime import datetime, timezone

    user = get_user_by_username(username)

    if not user or user.get('deleted_at'):
        return None

    # Check active lockout
    locked_until = user.get('locked_until')
    if locked_until:
        # psycopg2 returns timezone-aware datetimes when the column has tz;
        # our column is TIMESTAMP (no tz), so compare against UTC naive.
        now = datetime.utcnow()
        if isinstance(locked_until, datetime) and locked_until.tzinfo is not None:
            now = datetime.now(timezone.utc)
        if locked_until > now:
            return {'locked': True, 'locked_until': locked_until}

    if verify_password(user, password):
        # Successful login — reset failure counter
        if user.get('failed_login_attempts') or user.get('locked_until'):
            try:
                with get_db_connection("core") as conn:
                    c = conn.cursor()
                    c.execute(
                        "UPDATE users SET failed_login_attempts = 0, locked_until = NULL WHERE id = %s",
                        (user['id'],)
                    )
                    c.close()
            except Exception:
                pass
        return user

    # Wrong password — increment failure counter
    try:
        with get_db_connection("core") as conn:
            c = conn.cursor()
            new_attempts = (user.get('failed_login_attempts') or 0) + 1
            if new_attempts >= _MAX_FAILED_ATTEMPTS:
                from datetime import timedelta
                lockout_until = datetime.utcnow() + timedelta(minutes=_LOCKOUT_MINUTES)
                c.execute(
                    "UPDATE users SET failed_login_attempts = %s, locked_until = %s WHERE id = %s",
                    (new_attempts, lockout_until, user['id'])
                )
            else:
                c.execute(
                    "UPDATE users SET failed_login_attempts = %s WHERE id = %s",
                    (new_attempts, user['id'])
                )
            c.close()
    except Exception:
        pass

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
            logger.error(f"Error deleting user {user_id}: {e}", exc_info=True)
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
        
        # Column additions (user_preferences, last_seen) handled by app/core/migrations.py

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
                instance_id INTEGER,
                ts_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # audit_logs instance_id column handled by app/core/migrations.py

        # Create horizon_audit_logs table (used by horizon/audit.py)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS horizon_audit_logs (
                id SERIAL PRIMARY KEY,
                user_id INTEGER,
                username VARCHAR(255),
                permission_level VARCHAR(50),
                action VARCHAR(255) NOT NULL,
                category VARCHAR(255),
                details TEXT,
                target_instance_id INTEGER,
                severity VARCHAR(50) DEFAULT 'info',
                ip_address VARCHAR(100),
                user_agent TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_horizon_audit_user
                ON horizon_audit_logs(user_id, created_at DESC)
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
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_logs_instance
                ON audit_logs(instance_id, ts_utc DESC)
        """)
        cursor.close()

    logger.info("User schema initialized")


def ensure_inquiry_schema():
    """Ensure the user_inquiries table exists."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_inquiries (
                id SERIAL PRIMARY KEY,
                instance_id INTEGER,
                user_id INTEGER NOT NULL,
                username VARCHAR(255),
                first_name VARCHAR(255),
                last_name VARCHAR(255),
                email VARCHAR(255),
                department VARCHAR(255),
                position VARCHAR(255),
                request_type VARCHAR(50) NOT NULL,
                request_details TEXT,
                status VARCHAR(20) DEFAULT 'pending',
                reviewed_by INTEGER,
                reviewer_username VARCHAR(255),
                review_reason TEXT,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_inquiries_instance
                ON user_inquiries(instance_id, status, submitted_at DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_inquiries_user
                ON user_inquiries(user_id, submitted_at DESC)
        """)
        cursor.close()


def ensure_announcement_schema():
    """Ensure instance_announcements table exists."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS instance_announcements (
                id SERIAL PRIMARY KEY,
                instance_id INTEGER,
                title VARCHAR(200) NOT NULL,
                message TEXT NOT NULL,
                active BOOLEAN DEFAULT TRUE,
                created_by_username VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_announcements_lookup
                ON instance_announcements(active, instance_id)
        """)
        # Column additions (force_logout, failed_login_attempts, locked_until)
        # are handled by app/core/migrations.py
        cursor.close()


def ensure_support_ticket_schema():
    """Ensure support_tickets and support_ticket_replies tables exist."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id SERIAL PRIMARY KEY,
                instance_id INTEGER,
                user_id INTEGER NOT NULL,
                username VARCHAR(255) NOT NULL,
                user_email VARCHAR(255),
                subject VARCHAR(200) NOT NULL,
                category VARCHAR(50) NOT NULL,
                body TEXT NOT NULL,
                status VARCHAR(20) DEFAULT 'open',
                priority VARCHAR(20) DEFAULT 'normal',
                resolved_by_id INTEGER,
                resolved_by_username VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS support_ticket_replies (
                id SERIAL PRIMARY KEY,
                ticket_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL,
                author_username VARCHAR(255) NOT NULL,
                author_level VARCHAR(10),
                body TEXT NOT NULL,
                is_staff BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tickets_status
                ON support_tickets(status, created_at DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ticket_replies_ticket
                ON support_ticket_replies(ticket_id)
        """)
        cursor.close()


def ensure_reset_token_schema():
    """Ensure the password_reset_tokens table exists."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                username VARCHAR(255) NOT NULL,
                token VARCHAR(128) NOT NULL UNIQUE,
                inquiry_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                used_at TIMESTAMP,
                used_from_ip VARCHAR(45)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_reset_tokens_token
                ON password_reset_tokens(token)
        """)
        cursor.close()


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
                logger.warning("No system administrator found — creating default admin user")

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

                logger.warning("Default admin user created — CHANGE THIS PASSWORD IMMEDIATELY (username: admin)")
            else:
                logger.info(f"Found {count} system administrator(s)")

            cursor.close()

        except Exception as e:
            logger.error(f"Error ensuring sysadmin: {e}", exc_info=True)


if __name__ == "__main__":
    ensure_user_schema()
    ensure_first_sysadmin()
    logger.info("Database ready")