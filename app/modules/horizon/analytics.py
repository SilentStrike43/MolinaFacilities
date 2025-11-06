# app/modules/horizon/analytics.py
"""
Horizon Analytics Engine
Provides cross-instance analytics and reporting
"""

import logging
from datetime import datetime, timedelta
from app.core.database import get_db_connection

logger = logging.getLogger(__name__)


class GlobalAnalytics:
    """Analytics engine for Horizon platform."""
    
    def get_user_growth(self, date_from, date_to):
        """Get user growth over time."""
        try:
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT 
                        DATE(created_at) as date,
                        COUNT(*) as count
                    FROM users
                    WHERE created_at >= %s AND created_at <= %s
                    GROUP BY DATE(created_at)
                    ORDER BY date
                """, (date_from, date_to))
                
                rows = cursor.fetchall()
                cursor.close()
                
                return [{
                    'date': str(row['date']),
                    'count': row['count']
                } for row in rows]
        except Exception as e:
            logger.error(f"Error getting user growth: {e}")
            return []
    
    def get_activity_by_module(self, date_from, date_to):
        """Get activity breakdown by module."""
        try:
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT 
                        module,
                        COUNT(*) as count
                    FROM audit_logs
                    WHERE DATE(ts_utc) >= %s AND DATE(ts_utc) <= %s
                    GROUP BY module
                    ORDER BY count DESC
                """, (date_from, date_to))
                
                rows = cursor.fetchall()
                cursor.close()
                
                return [{
                    'module': row['module'],
                    'count': row['count']
                } for row in rows]
        except Exception as e:
            logger.error(f"Error getting activity by module: {e}")
            return []
    
    def get_activity_timeline(self, date_from, date_to):
        """Get activity timeline."""
        try:
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT 
                        DATE(ts_utc) as date,
                        COUNT(*) as count
                    FROM audit_logs
                    WHERE DATE(ts_utc) >= %s AND DATE(ts_utc) <= %s
                    GROUP BY DATE(ts_utc)
                    ORDER BY date
                """, (date_from, date_to))
                
                rows = cursor.fetchall()
                cursor.close()
                
                return [{
                    'date': str(row['date']),
                    'count': row['count']
                } for row in rows]
        except Exception as e:
            logger.error(f"Error getting activity timeline: {e}")
            return []
    
    def get_top_actions(self, limit=10):
        """Get most common actions."""
        try:
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT 
                        action,
                        COUNT(*) as count
                    FROM audit_logs
                    WHERE ts_utc >= NOW() - INTERVAL '30 days'
                    GROUP BY action
                    ORDER BY count DESC
                    LIMIT %s
                """, (limit,))
                
                rows = cursor.fetchall()
                cursor.close()
                
                return [{
                    'action': row['action'],
                    'count': row['count']
                } for row in rows]
        except Exception as e:
            logger.error(f"Error getting top actions: {e}")
            return []
    
    def get_users_by_permission_level(self):
        """Get user distribution by permission level."""
        try:
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT 
                        COALESCE(permission_level, 'Module User') as level,
                        COUNT(*) as count
                    FROM users
                    WHERE deleted_at IS NULL
                    GROUP BY permission_level
                    ORDER BY 
                        CASE permission_level
                            WHEN 'S1' THEN 1
                            WHEN 'L3' THEN 2
                            WHEN 'L2' THEN 3
                            WHEN 'L1' THEN 4
                            ELSE 5
                        END
                """)
                
                rows = cursor.fetchall()
                cursor.close()
                
                return [{
                    'level': row['level'],
                    'count': row['count']
                } for row in rows]
        except Exception as e:
            logger.error(f"Error getting users by permission: {e}")
            return []
    
    def get_instance_activity(self, instance_id, days=7):
        """Get activity for a specific instance."""
        try:
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                
                # Get date range
                end_date = datetime.now().date()
                start_date = end_date - timedelta(days=days)
                
                cursor.execute("""
                    SELECT 
                        DATE(al.ts_utc) as date,
                        COUNT(*) as count
                    FROM audit_logs al
                    JOIN users u ON al.user_id = u.id
                    WHERE u.instance_id = %s
                    AND DATE(al.ts_utc) >= %s
                    AND DATE(al.ts_utc) <= %s
                    GROUP BY DATE(al.ts_utc)
                    ORDER BY date
                """, (instance_id, start_date, end_date))
                
                rows = cursor.fetchall()
                cursor.close()
                
                return [{
                    'date': str(row['date']),
                    'count': row['count']
                } for row in rows]
        except Exception as e:
            logger.error(f"Error getting instance activity: {e}")
            return []
    
    def get_module_usage_stats(self):
        """Get module usage statistics."""
        try:
            stats = {
                'send': self._get_module_stats('send'),
                'inventory': self._get_module_stats('inventory'),
                'fulfillment': self._get_module_stats('fulfillment')
            }
            return stats
        except Exception as e:
            logger.error(f"Error getting module usage stats: {e}")
            return {
                'send': {'total': 0, 'last_30d': 0},
                'inventory': {'total': 0, 'last_30d': 0},
                'fulfillment': {'total': 0, 'last_30d': 0}
            }
    
    def _get_module_stats(self, module):
        """Get stats for a specific module."""
        try:
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                
                # Total actions
                cursor.execute("""
                    SELECT COUNT(*) as total
                    FROM audit_logs
                    WHERE module = %s
                """, (module,))
                total = cursor.fetchone()['total']
                
                # Last 30 days
                cursor.execute("""
                    SELECT COUNT(*) as count
                    FROM audit_logs
                    WHERE module = %s
                    AND ts_utc >= NOW() - INTERVAL '30 days'
                """, (module,))
                last_30d = cursor.fetchone()['count']
                
                cursor.close()
                
                return {
                    'total': total,
                    'last_30d': last_30d
                }
        except Exception as e:
            logger.error(f"Error getting module stats for {module}: {e}")
            return {'total': 0, 'last_30d': 0}
    
    def get_error_rate(self, days=7):
        """Calculate error rate from audit logs."""
        try:
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                
                end_date = datetime.now().date()
                start_date = end_date - timedelta(days=days)
                
                # Total actions
                cursor.execute("""
                    SELECT COUNT(*) as total
                    FROM audit_logs
                    WHERE DATE(ts_utc) >= %s
                    AND DATE(ts_utc) <= %s
                """, (start_date, end_date))
                total = cursor.fetchone()['total']
                
                # Error actions (actions containing 'error', 'fail', etc.)
                cursor.execute("""
                    SELECT COUNT(*) as errors
                    FROM audit_logs
                    WHERE DATE(ts_utc) >= %s
                    AND DATE(ts_utc) <= %s
                    AND (action ILIKE '%error%' OR action ILIKE '%fail%' OR action ILIKE '%exception%')
                """, (start_date, end_date))
                errors = cursor.fetchone()['errors']
                
                cursor.close()
                
                error_rate = (errors / total * 100) if total > 0 else 0
                
                return {
                    'total_actions': total,
                    'errors': errors,
                    'error_rate': round(error_rate, 2)
                }
        except Exception as e:
            logger.error(f"Error calculating error rate: {e}")
            return {
                'total_actions': 0,
                'errors': 0,
                'error_rate': 0
            }
    
    def get_active_users_count(self, days=7):
        """Get count of active users in the last N days."""
        try:
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                
                end_date = datetime.now().date()
                start_date = end_date - timedelta(days=days)
                
                cursor.execute("""
                    SELECT COUNT(DISTINCT user_id) as count
                    FROM audit_logs
                    WHERE DATE(ts_utc) >= %s
                    AND DATE(ts_utc) <= %s
                """, (start_date, end_date))
                
                result = cursor.fetchone()
                cursor.close()
                
                return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Error getting active users count: {e}")
            return 0
    
    def get_system_health_metrics(self):
        """Get system health metrics."""
        try:
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                
                # Database size
                cursor.execute("""
                    SELECT pg_database_size(current_database()) as size_bytes
                """)
                db_size = cursor.fetchone()['size_bytes']
                
                # Table counts
                cursor.execute("""
                    SELECT 
                        COUNT(*) as table_count
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                """)
                table_count = cursor.fetchone()['table_count']
                
                # Recent errors
                cursor.execute("""
                    SELECT COUNT(*) as error_count
                    FROM audit_logs
                    WHERE ts_utc >= NOW() - INTERVAL '24 hours'
                    AND (action ILIKE '%error%' OR action ILIKE '%fail%')
                """)
                errors_24h = cursor.fetchone()['error_count']
                
                cursor.close()
                
                # Calculate health score
                health_score = 100
                if errors_24h > 100:
                    health_score -= 20
                elif errors_24h > 50:
                    health_score -= 10
                elif errors_24h > 10:
                    health_score -= 5
                
                if db_size > 10 * 1024 * 1024 * 1024:  # 10GB
                    health_score -= 10
                
                return {
                    'health_score': max(health_score, 0),
                    'database_size_mb': round(db_size / (1024 * 1024), 2),
                    'table_count': table_count,
                    'errors_24h': errors_24h,
                    'status': 'healthy' if health_score >= 80 else 'warning' if health_score >= 60 else 'critical'
                }
        except Exception as e:
            logger.error(f"Error getting system health metrics: {e}")
            return {
                'health_score': 0,
                'database_size_mb': 0,
                'table_count': 0,
                'errors_24h': 0,
                'status': 'unknown'
            }


# Create singleton instance
analytics = GlobalAnalytics()