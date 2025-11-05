"""
Global Analytics Module - PostgreSQL Edition
Cross-instance analytics and insights
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List
from app.core.database import get_db_connection


class GlobalAnalytics:
    """Analytics engine for global insights."""
    
    def get_user_growth(self, date_from: str, date_to: str) -> Dict:
        """Get user growth metrics over time."""
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            # Daily new users
            cursor.execute("""
                SELECT 
                    DATE(created_at) as date,
                    COUNT(*) as new_users,
                    COUNT(DISTINCT instance_id) as instances_affected
                FROM users
                WHERE created_at BETWEEN %s AND %s
                GROUP BY DATE(created_at)
                ORDER BY date
            """, (date_from, date_to))
            
            daily_growth = cursor.fetchall()
            
            # Total growth
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_new,
                    COUNT(DISTINCT instance_id) as instances
                FROM users
                WHERE created_at BETWEEN %s AND %s
            """, (date_from, date_to))
            
            totals = cursor.fetchone()
            
            cursor.close()
        
        return {
            'daily': [
                {
                    'date': str(row[0]),
                    'new_users': row[1],
                    'instances': row[2]
                }
                for row in daily_growth
            ],
            'total_new_users': totals[0],
            'instances_with_growth': totals[1]
        }
    
    def get_activity_by_module(self, date_from: str, date_to: str) -> List[Dict]:
        """Get activity breakdown by module."""
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    module,
                    COUNT(*) as actions,
                    COUNT(DISTINCT user_id) as unique_users,
                    COUNT(DISTINCT DATE(ts_utc)) as active_days
                FROM audit_logs
                WHERE ts_utc BETWEEN %s AND %s
                GROUP BY module
                ORDER BY actions DESC
            """, (date_from, date_to))
            
            results = cursor.fetchall()
            cursor.close()
        
        return [
            {
                'module': row[0],
                'total_actions': row[1],
                'unique_users': row[2],
                'active_days': row[3],
                'avg_per_day': round(row[1] / row[3] if row[3] > 0 else 0, 2)
            }
            for row in results
        ]
    
    def get_instance_comparison(self) -> List[Dict]:
        """Compare all instances by key metrics."""
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    i.id,
                    i.name,
                    i.is_active,
                    COUNT(DISTINCT u.id) as user_count,
                    COUNT(DISTINCT CASE 
                        WHEN u.last_login_at >= CURRENT_TIMESTAMP - INTERVAL '30 days' 
                        THEN u.id 
                    END) as active_users,
                    COUNT(DISTINCT al.id) as total_actions,
                    COALESCE(i.max_users, 100) as max_users
                FROM public.instances i
                LEFT JOIN users u ON i.id = u.instance_id
                LEFT JOIN audit_logs al ON u.id = al.user_id 
                    AND al.ts_utc >= CURRENT_TIMESTAMP - INTERVAL '30 days'
                GROUP BY i.id, i.name, i.is_active, i.max_users
                ORDER BY user_count DESC
            """)
            
            results = cursor.fetchall()
            cursor.close()
        
        return [
            {
                'instance_id': row[0],
                'name': row[1],
                'is_active': row[2],
                'user_count': row[3],
                'active_users': row[4],
                'total_actions_30d': row[5],
                'max_users': row[6],
                'utilization_pct': round((row[3] / row[6] * 100) if row[6] > 0 else 0, 1),
                'activity_rate': round(row[5] / row[4] if row[4] > 0 else 0, 2)
            }
            for row in results
        ]
    
    def get_peak_usage_times(self, date_from: str, date_to: str) -> Dict:
        """Identify peak usage patterns."""
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            # Hourly distribution
            cursor.execute("""
                SELECT 
                    EXTRACT(HOUR FROM ts_utc) as hour,
                    COUNT(*) as actions,
                    COUNT(DISTINCT user_id) as unique_users
                FROM audit_logs
                WHERE ts_utc BETWEEN %s AND %s
                GROUP BY EXTRACT(HOUR FROM ts_utc)
                ORDER BY hour
            """, (date_from, date_to))
            
            hourly = cursor.fetchall()
            
            # Day of week distribution
            cursor.execute("""
                SELECT 
                    TO_CHAR(ts_utc, 'Day') as day_name,
                    EXTRACT(DOW FROM ts_utc) as day_num,
                    COUNT(*) as actions,
                    COUNT(DISTINCT user_id) as unique_users
                FROM audit_logs
                WHERE ts_utc BETWEEN %s AND %s
                GROUP BY TO_CHAR(ts_utc, 'Day'), EXTRACT(DOW FROM ts_utc)
                ORDER BY day_num
            """, (date_from, date_to))
            
            daily = cursor.fetchall()
            
            cursor.close()
        
        return {
            'hourly': [
                {
                    'hour': int(row[0]),
                    'actions': row[1],
                    'users': row[2]
                }
                for row in hourly
            ],
            'daily': [
                {
                    'day': row[0].strip(),
                    'actions': row[2],
                    'users': row[3]
                }
                for row in daily
            ]
        }
    
    def get_module_adoption(self) -> Dict:
        """Get module adoption rates across instances."""
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            # Get total instances
            cursor.execute("SELECT COUNT(*) FROM public.instances WHERE is_active = true")
            total_instances = cursor.fetchone()[0]
            
            # Module usage by instance
            cursor.execute("""
                SELECT 
                    'Ledger' as module,
                    COUNT(DISTINCT instance_id) as instances_using,
                    COUNT(*) as total_records
                FROM package_manifest
                UNION ALL
                SELECT 
                    'Flow' as module,
                    COUNT(DISTINCT instance_id) as instances_using,
                    COUNT(*) as total_records
                FROM assets
                UNION ALL
                SELECT 
                    'Fulfillment' as module,
                    COUNT(DISTINCT instance_id) as instances_using,
                    COUNT(*) as total_records
                FROM service_requests
            """)
            
            results = cursor.fetchall()
            cursor.close()
        
        return {
            'total_instances': total_instances,
            'modules': [
                {
                    'name': row[0],
                    'instances_using': row[1],
                    'adoption_rate': round((row[1] / total_instances * 100) if total_instances > 0 else 0, 1),
                    'total_records': row[2]
                }
                for row in results
            ]
        }