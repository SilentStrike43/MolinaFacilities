# app/core/instance_access.py
"""
Instance Access Management
Handles multi-instance access for L2+ users
"""

import logging
from app.core.database import get_db_connection

logger = logging.getLogger(__name__)


def get_user_instances(user_data):
    """
    Get all instances a user has access to.
    
    Returns:
        List of instance dicts the user can access
        
    Logic:
        - L3/S1: All instances
        - L2: Instances from user_instance_access table
        - L1 and below: Single instance from users.instance_id
    """
    if not user_data:
        return []
    
    permission_level = user_data.get('permission_level', '')
    
    # L3 and S1: Access ALL instances
    if permission_level in ['L3', 'S1']:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, display_name, is_active
                FROM instances
                ORDER BY name
            """)
            instances = cursor.fetchall()
            cursor.close()
            return [dict(inst) for inst in instances]
    
    # L2: Access multiple instances via junction table
    if permission_level == 'L2':
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT i.id, i.name, i.display_name, i.is_active, uia.granted_at
                FROM user_instance_access uia
                JOIN instances i ON uia.instance_id = i.id
                WHERE uia.user_id = %s AND i.is_active = TRUE
                ORDER BY i.name
            """, (user_data['id'],))
            instances = cursor.fetchall()
            cursor.close()
            return [dict(inst) for inst in instances]
    
    # L1 and below: Single instance only
    instance_id = user_data.get('instance_id')
    if instance_id:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, display_name, is_active
                FROM instances
                WHERE id = %s
            """, (instance_id,))
            instance = cursor.fetchone()
            cursor.close()
            return [dict(instance)] if instance else []
    
    return []


def user_can_access_instance(user_data, instance_id):
    """
    Check if a user has access to a specific instance.
    
    Args:
        user_data: Current user dict
        instance_id: Instance to check access for
        
    Returns:
        Boolean
    """
    if not user_data or not instance_id:
        return False
    
    permission_level = user_data.get('permission_level', '')
    
    # L3/S1: Access everything
    if permission_level in ['L3', 'S1']:
        return True
    
    # L2: Check junction table
    if permission_level == 'L2':
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 1 FROM user_instance_access
                WHERE user_id = %s AND instance_id = %s
            """, (user_data['id'], instance_id))
            has_access = cursor.fetchone() is not None
            cursor.close()
            return has_access
    
    # L1 and below: Check single instance
    return user_data.get('instance_id') == instance_id


def grant_instance_access(user_id, instance_id, granted_by_user_id, role_notes=None):
    """
    Grant an L2 user access to an instance.
    
    Args:
        user_id: User to grant access to (must be L2)
        instance_id: Instance to grant access to
        granted_by_user_id: Admin granting the access
        role_notes: Optional notes about their role
        
    Returns:
        Boolean success
    """
    try:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            # Verify user is L2
            cursor.execute("SELECT permission_level FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            if not user or user['permission_level'] != 'L2':
                logger.warning(f"Attempted to grant instance access to non-L2 user {user_id}")
                return False
            
            # Insert access
            cursor.execute("""
                INSERT INTO user_instance_access (user_id, instance_id, granted_by, role_notes)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id, instance_id) DO NOTHING
            """, (user_id, instance_id, granted_by_user_id, role_notes))
            
            conn.commit()
            cursor.close()
            return True
            
    except Exception as e:
        logger.error(f"Error granting instance access: {e}")
        return False


def revoke_instance_access(user_id, instance_id):
    """
    Revoke an L2 user's access to an instance.
    
    Args:
        user_id: User to revoke access from
        instance_id: Instance to revoke access to
        
    Returns:
        Boolean success
    """
    try:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM user_instance_access
                WHERE user_id = %s AND instance_id = %s
            """, (user_id, instance_id))
            conn.commit()
            cursor.close()
            return True
            
    except Exception as e:
        logger.error(f"Error revoking instance access: {e}")
        return False


def get_instance_access_details(user_id):
    """
    Get detailed information about a user's instance access.
    
    Returns:
        List of dicts with instance info and access details
    """
    try:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    i.id, i.name, i.display_name,
                    uia.granted_at, uia.role_notes,
                    u.username as granted_by_username
                FROM user_instance_access uia
                JOIN instances i ON uia.instance_id = i.id
                LEFT JOIN users u ON uia.granted_by = u.id
                WHERE uia.user_id = %s
                ORDER BY i.name
            """, (user_id,))
            access = cursor.fetchall()
            cursor.close()
            return [dict(row) for row in access]
            
    except Exception as e:
        logger.error(f"Error getting instance access details: {e}")
        return []


def sync_l2_instance_access(user_id, instance_ids, granted_by_user_id):
    """
    Sync an L2 user's instance access (add/remove as needed).
    
    Args:
        user_id: L2 user
        instance_ids: List of instance IDs they should have access to
        granted_by_user_id: Admin making the change
    """
    try:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            # Get current access
            cursor.execute("""
                SELECT instance_id FROM user_instance_access
                WHERE user_id = %s
            """, (user_id,))
            current_instances = {row['instance_id'] for row in cursor.fetchall()}
            
            new_instances = set(instance_ids)
            
            # Add new access
            to_add = new_instances - current_instances
            for inst_id in to_add:
                cursor.execute("""
                    INSERT INTO user_instance_access (user_id, instance_id, granted_by)
                    VALUES (%s, %s, %s)
                """, (user_id, inst_id, granted_by_user_id))
            
            # Remove old access
            to_remove = current_instances - new_instances
            for inst_id in to_remove:
                cursor.execute("""
                    DELETE FROM user_instance_access
                    WHERE user_id = %s AND instance_id = %s
                """, (user_id, inst_id))
            
            conn.commit()
            cursor.close()
            return True
            
    except Exception as e:
        logger.error(f"Error syncing instance access: {e}")
        return False