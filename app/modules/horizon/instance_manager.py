"""
Instance Manager - PostgreSQL Edition
Multi-tenant instance operations
"""

import json
from datetime import datetime
from typing import Dict, List, Optional
from app.core.database import get_db_connection


class InstanceManager:
    """Manage Gridline Services instances (tenants)."""
    
    @staticmethod
    def create_instance(
        name: str,
        subdomain: str = None,
        contact_email: str = None,
        contact_phone: str = None,
        address: str = None,
        max_users: int = 100,
        features: List[str] = None,
        created_by: int = None
    ) -> int:
        """Create a new tenant instance."""
        features_json = json.dumps(features or [])
        
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO instances (
                    name, subdomain, contact_email, contact_phone,
                    address, max_users, features, is_active,
                    created_at, created_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, true, CURRENT_TIMESTAMP, %s)
                RETURNING id
            """, (
                name, subdomain, contact_email, contact_phone,
                address, max_users, features_json, created_by
            ))
            
            instance_id = cursor.fetchone()['id']
            
            # Initialize instance settings
            InstanceManager._initialize_instance_settings(instance_id)
            
            cursor.close()
        
        return instance_id
    
    @staticmethod
    def _initialize_instance_settings(instance_id: int):
        """Initialize default settings for new instance."""
        default_settings = {
            'branding': {
                'logo_url': '',
                'primary_color': '#007bff',
                'secondary_color': '#6c757d',
                'custom_css': ''
            },
            'modules': {
                'ledger_enabled': True,
                'flow_enabled': True,
                'fulfillment_enabled': True
            },
            'features': {
                'sso_enabled': False,
                'api_access': False,
                'custom_reports': False,
                'mobile_app': False,
                'ip_whitelist': False,
                'force_2fa': False,
                'database_import': False
            },
            'limits': {
                'storage_mb': 10240,
                'api_calls_per_day': 10000,
                'max_file_size_mb': 50
            },
            'security': {
                'password_expiry_days': 90,
                'session_timeout_minutes': 480,
                'ip_whitelist': []
            }
        }
        
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE instances
                SET settings = %s::jsonb,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (json.dumps(default_settings), instance_id))
            cursor.close()
    
    @staticmethod
    def update_instance(instance_id: int, updates: Dict) -> bool:
        """Update instance details."""
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            set_clauses = []
            params = []
            
            for key, value in updates.items():
                if key in ['name', 'subdomain', 'contact_email', 'contact_phone', 
                          'address', 'max_users', 'is_active']:
                    set_clauses.append(f"{key} = %s")
                    params.append(value)
                elif key == 'settings':
                    set_clauses.append("settings = %s::jsonb")
                    params.append(json.dumps(value) if isinstance(value, dict) else value)
                elif key == 'features':
                    set_clauses.append("features = %s::jsonb")
                    params.append(json.dumps(value) if isinstance(value, list) else value)
            
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            params.append(instance_id)
            
            query = f"UPDATE instances SET {', '.join(set_clauses)} WHERE id = %s"
            cursor.execute(query, params)
            cursor.close()
        
        return True
    
    @staticmethod
    def delete_instance(instance_id: int, deleted_by: int = None) -> bool:
        """Permanently delete an instance and all associated data."""
        # Archive instance data before deletion
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            # Archive
            cursor.execute("""
                INSERT INTO instance_archive (
                    original_id, name, subdomain, contact_email,
                    created_at, deleted_at, deleted_by, archive_data
                )
                SELECT 
                    id, name, subdomain, contact_email,
                    created_at, CURRENT_TIMESTAMP, %s, 
                    row_to_json(instances.*)::jsonb
                FROM instances
                WHERE id = %s
            """, (deleted_by, instance_id))
            
            # Delete audit logs
            cursor.execute("""
                DELETE FROM audit_logs
                WHERE user_id IN (SELECT id FROM users WHERE instance_id = %s)
            """, (instance_id,))
            
            # Delete users
            cursor.execute("DELETE FROM users WHERE instance_id = %s", (instance_id,))
            
            # Finally, delete the instance
            cursor.execute("DELETE FROM instances WHERE id = %s", (instance_id,))
            
            cursor.close()
        
        # Delete module data from other databases
        with get_db_connection("send") as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM package_manifest WHERE instance_id = %s", (instance_id,))
            cursor.close()
        
        with get_db_connection("inventory") as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM assets WHERE instance_id = %s", (instance_id,))
            cursor.execute("DELETE FROM inventory_transactions WHERE instance_id = %s", (instance_id,))
            cursor.close()
        
        with get_db_connection("fulfillment") as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM service_requests WHERE instance_id = %s", (instance_id,))
            cursor.execute("DELETE FROM fulfillment_requests WHERE instance_id = %s", (instance_id,))
            cursor.close()
        
        return True
    
    @staticmethod
    def deactivate_instance(instance_id: int, reason: str = None, deactivated_by: int = None):
        """Deactivate an instance (soft delete)."""
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE instances
                SET is_active = false,
                    deactivation_reason = %s,
                    deactivated_at = CURRENT_TIMESTAMP,
                    deactivated_by = %s
                WHERE id = %s
            """, (reason, deactivated_by, instance_id))
            cursor.close()
    
    @staticmethod
    def activate_instance(instance_id: int):
        """Activate a deactivated instance."""
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE instances
                SET is_active = true,
                    deactivation_reason = NULL,
                    deactivated_at = NULL,
                    deactivated_by = NULL
                WHERE id = %s
            """, (instance_id,))
            cursor.close()
    
    @staticmethod
    def export_instance_data(instance_id: int) -> Dict:
        """Export all data for an instance as JSON."""
        export = {
            'instance_id': instance_id,
            'exported_at': datetime.utcnow().isoformat(),
            'users': [],
            'ledger': [],
            'flow': [],
            'fulfillment': []
        }
        
        # Export users
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM users WHERE instance_id = %s AND (deleted_at IS NULL OR deleted_at = '')
            """, (instance_id,))
            export['users'] = [dict(row) for row in cursor.fetchall()]
            cursor.close()
        
        # Export ledger data
        with get_db_connection("send") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM package_manifest WHERE instance_id = %s", (instance_id,))
            export['ledger'] = [dict(row) for row in cursor.fetchall()]
            cursor.close()
        
        # Export flow data
        with get_db_connection("inventory") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM assets WHERE instance_id = %s", (instance_id,))
            export['flow'] = [dict(row) for row in cursor.fetchall()]
            cursor.close()
        
        # Export fulfillment data
        with get_db_connection("fulfillment") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM service_requests WHERE instance_id = %s", (instance_id,))
            export['fulfillment'] = [dict(row) for row in cursor.fetchall()]
            cursor.close()
        
        return export