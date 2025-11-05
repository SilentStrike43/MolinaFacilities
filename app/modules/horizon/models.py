"""
Global Admin Models - PostgreSQL Edition
Multi-tenant instance management
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from app.core.database import get_db_connection


# ---------- Instance Models ----------

def get_all_instances(include_inactive: bool = True) -> List[Dict]:
    """Get all instances from core database."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        query = "SELECT * FROM instances"
        
        if not include_inactive:
            query += " WHERE is_active = true"
        
        query += " ORDER BY name"
        
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
        
        instances = []
        for row in rows:
            inst = dict(row)
            # Parse JSON fields if they exist
            if inst.get('features'):
                inst['features'] = json.loads(inst['features']) if isinstance(inst['features'], str) else inst['features']
            if inst.get('settings'):
                inst['settings'] = json.loads(inst['settings']) if isinstance(inst['settings'], str) else inst['settings']
            instances.append(inst)
        
        return instances


def get_instance_by_id(instance_id: int) -> Optional[Dict]:
    """Get instance by ID from core database."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM instances WHERE id = %s", (instance_id,))
        row = cursor.fetchone()
        cursor.close()
        
        if not row:
            return None
        
        inst = dict(row)
        # Parse JSON fields
        if inst.get('features'):
            inst['features'] = json.loads(inst['features']) if isinstance(inst['features'], str) else inst['features']
        if inst.get('settings'):
            inst['settings'] = json.loads(inst['settings']) if isinstance(inst['settings'], str) else inst['settings']
        
        return inst


def get_instance_by_subdomain(subdomain: str) -> Optional[Dict]:
    """Get instance by subdomain."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM instances WHERE subdomain = %s", (subdomain,))
        row = cursor.fetchone()
        cursor.close()
        
        if not row:
            return None
        
        inst = dict(row)
        if inst.get('features'):
            inst['features'] = json.loads(inst['features']) if isinstance(inst['features'], str) else inst['features']
        if inst.get('settings'):
            inst['settings'] = json.loads(inst['settings']) if isinstance(inst['settings'], str) else inst['settings']
        
        return inst


def get_instance_stats(instance_id: int) -> Dict:
    """Get comprehensive statistics for an instance."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        # User counts
        cursor.execute("""
            SELECT COUNT(*) as total_users
            FROM users 
            WHERE instance_id = %s 
            AND deleted_at IS NULL
        """, (instance_id,))
        user_count = cursor.fetchone()['total_users'] or 0
        
        # Active users (last 30 days)
        cursor.execute("""
            SELECT COUNT(*) as active_users
            FROM users 
            WHERE instance_id = %s 
            AND deleted_at IS NULL
            AND last_login_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
        """, (instance_id,))
        active_users = cursor.fetchone()['active_users'] or 0
        
        # Permission level counts
        cursor.execute("""
            SELECT 
                SUM(CASE WHEN permission_level = 'L1' THEN 1 ELSE 0 END) as l1_count,
                SUM(CASE WHEN permission_level = 'L2' THEN 1 ELSE 0 END) as l2_count,
                SUM(CASE WHEN permission_level = 'L3' THEN 1 ELSE 0 END) as l3_count,
                SUM(CASE WHEN permission_level = 'S1' THEN 1 ELSE 0 END) as s1_count
            FROM users 
            WHERE instance_id = %s 
            AND deleted_at IS NULL
        """, (instance_id,))
        admin_counts = cursor.fetchone()
        
        # Activity from audit_logs (last 7 days)
        cursor.execute("""
            SELECT COUNT(*) as activity_7d
            FROM audit_logs 
            WHERE user_id IN (SELECT id FROM users WHERE instance_id = %s)
            AND ts_utc >= CURRENT_TIMESTAMP - INTERVAL '7 days'
        """, (instance_id,))
        activity_7d = cursor.fetchone()['activity_7d'] or 0
        
        # Activity (last 30 days)
        cursor.execute("""
            SELECT COUNT(*) as activity_30d
            FROM audit_logs 
            WHERE user_id IN (SELECT id FROM users WHERE instance_id = %s)
            AND ts_utc >= CURRENT_TIMESTAMP - INTERVAL '30 days'
        """, (instance_id,))
        activity_30d = cursor.fetchone()['activity_30d'] or 0
        
        cursor.close()
    
    # Module usage - Send/Ledger
    with get_db_connection("send") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) as ledger_records
            FROM package_manifest
            WHERE instance_id = %s
        """, (instance_id,))
        ledger_records = cursor.fetchone()['ledger_records'] or 0
        cursor.close()
    
    # Module usage - Inventory/Flow
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) as flow_assets
            FROM assets
            WHERE instance_id = %s
        """, (instance_id,))
        flow_assets = cursor.fetchone()['flow_assets'] or 0
        cursor.close()
    
    # Module usage - Fulfillment
    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) as fulfillment_requests
            FROM service_requests
            WHERE instance_id = %s
        """, (instance_id,))
        fulfillment_requests = cursor.fetchone()['fulfillment_requests'] or 0
        cursor.close()
    
    # Storage estimate (from fulfillment)
    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COALESCE(SUM(LENGTH(CAST(description AS TEXT))), 0) as total_bytes
            FROM service_requests
            WHERE instance_id = %s
        """, (instance_id,))
        storage_bytes = cursor.fetchone()['total_bytes'] or 0
        cursor.close()
    
    # Most active users
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.username, COUNT(al.id) as action_count
            FROM users u
            LEFT JOIN audit_logs al ON u.id = al.user_id
            WHERE u.instance_id = %s
            AND (u.deleted_at IS NULL OR u.deleted_at = '')
            AND al.ts_utc >= CURRENT_TIMESTAMP - INTERVAL '30 days'
            GROUP BY u.username
            ORDER BY action_count DESC
            LIMIT 5
        """, (instance_id,))
        top_users = cursor.fetchall()
        cursor.close()
    
    return {
        'user_count': user_count,
        'active_users': active_users,
        'inactive_users': user_count - active_users,
        'admins': {
            'l1': admin_counts['l1_count'] or 0,
            'l2': admin_counts['l2_count'] or 0,
            'l3': admin_counts['l3_count'] or 0,
            's1': admin_counts['s1_count'] or 0,
            'total': sum([admin_counts[k] or 0 for k in ['l1_count', 'l2_count', 'l3_count', 's1_count']])
        },
        'modules': {
            'ledger': ledger_records,
            'flow': flow_assets,
            'fulfillment': fulfillment_requests,
            'total': ledger_records + flow_assets + fulfillment_requests
        },
        'activity': {
            'last_7d': activity_7d,
            'last_30d': activity_30d,
            'per_user_30d': round(activity_30d / user_count if user_count > 0 else 0, 2)
        },
        'storage_mb': round(storage_bytes / (1024 * 1024), 2),
        'top_users': [
            {'username': row['username'], 'actions': row['action_count']}
            for row in top_users
        ]
    }


def get_system_health_metrics() -> Dict:
    """Get system-wide health metrics."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        # Database size (PostgreSQL)
        cursor.execute("""
            SELECT pg_database_size(current_database()) / (1024.0 * 1024.0) as size_mb
        """)
        db_size = cursor.fetchone()['size_mb'] or 0
        
        # Instance counts
        cursor.execute("SELECT COUNT(*) as total FROM instances")
        total_instances = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) as active FROM instances WHERE is_active = true")
        active_instances = cursor.fetchone()['active']
        
        # Total users
        cursor.execute("""
            SELECT COUNT(*) as total_users
            FROM users 
            WHERE deleted_at IS NULL
        """)
        total_users = cursor.fetchone()['total_users'] or 0
        
        # Activity last 24h
        cursor.execute("""
            SELECT COUNT(*) as activity_24h
            FROM audit_logs 
            WHERE ts_utc >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
        """)
        activity_24h = cursor.fetchone()['activity_24h'] or 0
        
        # Errors last 24h
        cursor.execute("""
            SELECT COUNT(*) as errors_24h
            FROM audit_logs 
            WHERE ts_utc >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
            AND (action LIKE '%error%' OR action LIKE '%fail%')
        """)
        errors_24h = cursor.fetchone()['errors_24h'] or 0
        
        # Total audit logs
        cursor.execute("SELECT COUNT(*) as total_logs FROM audit_logs")
        audit_log_count = cursor.fetchone()['total_logs'] or 0
        
        cursor.close()
    
    # Calculate health score
    health_score = 100
    
    if errors_24h > 100:
        health_score -= 20
    elif errors_24h > 50:
        health_score -= 10
    
    if db_size > 50000:
        health_score -= 15
    elif db_size > 25000:
        health_score -= 5
    
    inactive_ratio = (total_instances - active_instances) / total_instances if total_instances > 0 else 0
    if inactive_ratio > 0.3:
        health_score -= 10
    
    # Determine status
    if health_score >= 90:
        status = 'excellent'
        status_color = 'success'
    elif health_score >= 70:
        status = 'good'
        status_color = 'info'
    elif health_score >= 50:
        status = 'fair'
        status_color = 'warning'
    else:
        status = 'poor'
        status_color = 'danger'
    
    return {
        'health_score': health_score,
        'status': status,
        'status_color': status_color,
        'database_size_mb': round(db_size, 2),
        'instances': {
            'total': total_instances,
            'active': active_instances,
            'inactive': total_instances - active_instances
        },
        'users': {
            'total': total_users,
            'per_instance': round(total_users / active_instances if active_instances > 0 else 0, 1)
        },
        'activity': {
            'last_24h': activity_24h,
            'errors_24h': errors_24h,
            'error_rate': round((errors_24h / activity_24h * 100) if activity_24h > 0 else 0, 2)
        },
        'audit_logs': {
            'count': audit_log_count,
            'size_estimate_mb': round(audit_log_count * 0.001, 2)
        }
    }