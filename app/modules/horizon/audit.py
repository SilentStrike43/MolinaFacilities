# app/modules/horizon/audit.py
"""
Horizon Audit Logging
Separate audit system for platform-level actions
"""

import logging
from datetime import datetime
from flask import request
from app.core.database import get_db_connection

logger = logging.getLogger(__name__)


def record_horizon_audit(user_data, action, category, details, 
                        target_instance_id=None, severity="info"):
    """
    Record a Horizon platform-level audit event.
    
    Args:
        user_data: Current user dict
        action: Action performed (e.g., "create_instance", "delete_user")
        category: Category (e.g., "instances", "users", "settings")
        details: Detailed description of the action
        target_instance_id: Instance affected (if applicable)
        severity: "info", "warning", "critical"
    """
    try:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            # Get request metadata
            ip_address = request.remote_addr if request else None
            user_agent = request.headers.get('User-Agent', '')[:500] if request else ""
            
            cursor.execute("""
                INSERT INTO horizon_audit_logs (
                    user_id, username, permission_level,
                    action, category, details,
                    target_instance_id, severity,
                    ip_address, user_agent, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            """, (
                user_data.get("id"),
                user_data.get("username"),
                user_data.get("permission_level", ""),
                action,
                category,
                details,
                target_instance_id,
                severity,
                ip_address,
                user_agent
            ))
            
            conn.commit()
            cursor.close()
            
            logger.info(f"Horizon Audit: {user_data.get('username')} - {action} - {details}")
            
    except Exception as e:
        logger.error(f"Failed to record Horizon audit: {e}")
        # Don't raise - audit failures shouldn't break the app


def get_horizon_audit_logs(filters=None, limit=100):
    """
    Retrieve Horizon audit logs with optional filters.
    
    Args:
        filters: Dict with keys like 'user_id', 'action', 'category', 'instance_id', etc.
        limit: Maximum number of records to return
    
    Returns:
        List of audit log dicts
    """
    try:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM horizon_audit_logs WHERE 1=1"
            params = []
            
            if filters:
                if filters.get("user_id"):
                    query += " AND user_id = %s"
                    params.append(filters["user_id"])
                
                if filters.get("username"):
                    query += " AND username ILIKE %s"
                    params.append(f"%{filters['username']}%")
                
                if filters.get("action"):
                    query += " AND action = %s"
                    params.append(filters["action"])
                
                if filters.get("category"):
                    query += " AND category = %s"
                    params.append(filters["category"])
                
                if filters.get("instance_id"):
                    query += " AND target_instance_id = %s"
                    params.append(filters["instance_id"])
                
                if filters.get("severity"):
                    query += " AND severity = %s"
                    params.append(filters["severity"])
                
                if filters.get("date_from"):
                    query += " AND DATE(created_at) >= %s"
                    params.append(filters["date_from"])
                
                if filters.get("date_to"):
                    query += " AND DATE(created_at) <= %s"
                    params.append(filters["date_to"])
            
            query += " ORDER BY created_at DESC LIMIT %s"
            params.append(limit)
            
            cursor.execute(query, params)
            logs = cursor.fetchall()
            cursor.close()
            
            return [dict(log) for log in logs]
            
    except Exception as e:
        logger.error(f"Failed to retrieve Horizon audit logs: {e}")
        return []


def get_horizon_audit_stats(days=30):
    """Get statistics about Horizon audit activity."""
    try:
        from datetime import timedelta
        
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            cutoff = datetime.now() - timedelta(days=days)
            
            # Total actions
            cursor.execute("""
                SELECT COUNT(*) as total
                FROM horizon_audit_logs
                WHERE created_at >= %s
            """, (cutoff,))
            total = cursor.fetchone()['total']
            
            # By category
            cursor.execute("""
                SELECT category, COUNT(*) as count
                FROM horizon_audit_logs
                WHERE created_at >= %s
                GROUP BY category
                ORDER BY count DESC
            """, (cutoff,))
            by_category = {row['category']: row['count'] for row in cursor.fetchall()}
            
            # By severity
            cursor.execute("""
                SELECT severity, COUNT(*) as count
                FROM horizon_audit_logs
                WHERE created_at >= %s
                GROUP BY severity
            """, (cutoff,))
            by_severity = {row['severity']: row['count'] for row in cursor.fetchall()}
            
            # Most active users
            cursor.execute("""
                SELECT username, COUNT(*) as count
                FROM horizon_audit_logs
                WHERE created_at >= %s
                GROUP BY username
                ORDER BY count DESC
                LIMIT 10
            """, (cutoff,))
            top_users = [(row['username'], row['count']) for row in cursor.fetchall()]
            
            cursor.close()
            
            return {
                'total_actions': total,
                'by_category': by_category,
                'by_severity': by_severity,
                'top_users': top_users
            }
            
    except Exception as e:
        logger.error(f"Failed to get Horizon audit stats: {e}")
        return {
            'total_actions': 0,
            'by_category': {},
            'by_severity': {},
            'top_users': []
        }