# app/modules/horizon/middleware.py
"""
Middleware and helpers for Global Admin module - PostgreSQL Edition
"""

from flask import g, session
from app.core.database import get_db_connection
from app.modules.auth.security import current_user

def update_permission_display():
    """Update the permission display for bottom bar."""
    cu = current_user()
    if cu:
        permission_level = cu.get('permission_level', 'User')
        
        # Map permission levels to display names
        permission_map = {
            'S1': 'System',
            'A1': 'Gridline Operator', 'A2': 'Platform Administrator', 
            'L2': 'Instance Administrator',
            'L1': 'Module Administrator',
            '': 'Module User'
        }
        
        display_level = permission_map.get(permission_level, 'Module User')
        
        # Get instance name
        instance_name = 'Global'
        
        if cu.get('instance_id'):
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM core.instances WHERE id = %s", 
                              (cu['instance_id'],))
                result = cursor.fetchone()
                if result:
                    instance_name = result['name']
                cursor.close()
        
        # Check if mirroring
        mirror_session = session.get('mirror_session')
        if mirror_session:
            instance_name = f"MIRRORING: {mirror_session.get('target_username')} @ {mirror_session.get('target_instance_name', instance_name)}"
        
        # Set the display string
        g.permission_display = f"{display_level} - {instance_name}"
        g.permission_level = permission_level
        g.instance_name = instance_name
    else:
        g.permission_display = "Not Authenticated"
        g.permission_level = None
        g.instance_name = None

def inject_permission_context():
    """Context processor to inject permission display."""
    return {
        'permission_display': g.get('permission_display', ''),
        'user_permission_level': g.get('permission_level', ''),
        'user_instance_name': g.get('instance_name', '')
    }

def check_instance_limits(instance_id: int) -> dict:
    """Check if instance is approaching or exceeding limits."""
    from app.modules.horizon.models import get_instance_by_id, get_instance_stats
    
    instance = get_instance_by_id(instance_id)
    stats = get_instance_stats(instance_id)
    
    warnings = []
    errors = []
    
    # Check user limit
    user_percentage = (stats['user_count'] / instance['max_users'] * 100) if instance['max_users'] > 0 else 0
    
    if user_percentage >= 100:
        errors.append(f"User limit exceeded: {stats['user_count']}/{instance['max_users']}")
    elif user_percentage >= 90:
        warnings.append(f"Approaching user limit: {stats['user_count']}/{instance['max_users']}")
    
    # Check storage
    storage_limit = 10240  # MB
    if instance.get('settings'):
        import json
        settings = json.loads(instance['settings']) if isinstance(instance['settings'], str) else instance['settings']
        storage_limit = settings.get('limits', {}).get('storage_mb', 10240)
    
    storage_percentage = (stats['storage_mb'] / storage_limit * 100) if storage_limit > 0 else 0
    
    if storage_percentage >= 90:
        warnings.append(f"High storage usage: {stats['storage_mb']:.1f} MB of {storage_limit} MB")
    
    # Check activity
    if stats['activity']['per_user_30d'] < 1:
        warnings.append("Low user engagement (< 1 action per user in 30 days)")
    
    return {
        'warnings': warnings,
        'errors': errors,
        'healthy': len(errors) == 0,
        'needs_attention': len(warnings) > 0 or len(errors) > 0
    }

def get_instance_administrators(instance_id: int) -> list:
    """Get all L2 administrators for an instance."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, email, first_name, last_name,
                   last_login_at, created_at
            FROM users
            WHERE instance_id = %s
            AND permission_level = 'L2'
            AND (deleted_at IS NULL OR deleted_at = '')
            ORDER BY created_at
        """, (instance_id,))
        
        admins = []
        for row in cursor.fetchall():
            admins.append({
                'id': row['id'],
                'username': row['username'],
                'email': row['email'],
                'full_name': f"{row['first_name']} {row['last_name']}",
                'last_login': row['last_login_at'],
                'created_at': row['created_at']
            })
        
        cursor.close()
    
    return admins

def can_user_manage_instance(user_permission: str, target_instance_id: int, user_instance_id: int = None) -> bool:
    """Check if a user can manage a specific instance."""
    if user_permission == 'S1':
        return True
    
    if user_permission == 'A1':
        return True
    
    if user_permission == 'L2':
        return user_instance_id == target_instance_id
    
    return False

def log_instance_action(user_id: int, action: str, instance_id: int, details: str = None):
    """Log an action performed on an instance."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO audit_logs (
                action, username, module, details, 
                ts_utc, permission_level, user_id
            )
            SELECT 
                %s, username, 'horizon', %s,
                CURRENT_TIMESTAMP, permission_level, %s
            FROM users 
            WHERE id = %s
        """, (
            f"instance_{action}",
            f"Instance ID: {instance_id}. {details or ''}",
            user_id,
            user_id
        ))
        conn.commit()
        cursor.close()