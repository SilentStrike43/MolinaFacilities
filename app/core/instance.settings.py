# app/core/instance_settings.py
"""
Instance Settings Helper
Manages per-instance branding and customization
"""

from app.core.database import get_db_connection

def get_instance_settings(instance_id=None):
    """Get instance-specific settings for branding/customization."""
    if not instance_id:
        # Return default Gridline Services branding
        return {
            'instance_name': 'Gridline Services',
            'instance_subtitle': 'Enterprise Platform',
            'logo_url': None,
            'favicon_url': None,
            'primary_color': '#0066cc',
            'secondary_color': '#00b4d8',
            'sidebar_bg_start': '#1a1d2e',
            'sidebar_bg_end': '#2d3142',
            'topbar_bg': '#ffffff',
            'timezone': 'America/New_York',
            'date_format': 'YYYY-MM-DD'
        }
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                instance_name, instance_subtitle, logo_url, favicon_url,
                primary_color, secondary_color, sidebar_bg_start, sidebar_bg_end,
                topbar_bg, timezone, date_format
            FROM instance_settings
            WHERE instance_id = %s
        """, (instance_id,))
        
        row = cursor.fetchone()
        cursor.close()
        
        if not row:
            return get_instance_settings(None)  # Return defaults
        
        return {
            'instance_name': row['instance_name'],
            'instance_subtitle': row['instance_subtitle'],
            'logo_url': row['logo_url'],
            'favicon_url': row['favicon_url'],
            'primary_color': row['primary_color'],
            'secondary_color': row['secondary_color'],
            'sidebar_bg_start': row['sidebar_bg_start'],
            'sidebar_bg_end': row['sidebar_bg_end'],
            'topbar_bg': row['topbar_bg'],
            'timezone': row['timezone'],
            'date_format': row['date_format']
        }

def update_instance_settings(instance_id, settings):
    """Update instance settings."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        # Check if settings exist
        cursor.execute("SELECT id FROM instance_settings WHERE instance_id = %s", (instance_id,))
        exists = cursor.fetchone()
        
        if exists:
            # Update existing
            cursor.execute("""
                UPDATE instance_settings
                SET instance_name = %s,
                    instance_subtitle = %s,
                    logo_url = %s,
                    favicon_url = %s,
                    primary_color = %s,
                    secondary_color = %s,
                    sidebar_bg_start = %s,
                    sidebar_bg_end = %s,
                    topbar_bg = %s,
                    timezone = %s,
                    date_format = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE instance_id = %s
            """, (
                settings.get('instance_name'),
                settings.get('instance_subtitle'),
                settings.get('logo_url'),
                settings.get('favicon_url'),
                settings.get('primary_color'),
                settings.get('secondary_color'),
                settings.get('sidebar_bg_start'),
                settings.get('sidebar_bg_end'),
                settings.get('topbar_bg'),
                settings.get('timezone'),
                settings.get('date_format'),
                instance_id
            ))
        else:
            # Insert new
            cursor.execute("""
                INSERT INTO instance_settings (
                    instance_id, instance_name, instance_subtitle, logo_url, favicon_url,
                    primary_color, secondary_color, sidebar_bg_start, sidebar_bg_end,
                    topbar_bg, timezone, date_format
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                instance_id,
                settings.get('instance_name'),
                settings.get('instance_subtitle'),
                settings.get('logo_url'),
                settings.get('favicon_url'),
                settings.get('primary_color'),
                settings.get('secondary_color'),
                settings.get('sidebar_bg_start'),
                settings.get('sidebar_bg_end'),
                settings.get('topbar_bg'),
                settings.get('timezone'),
                settings.get('date_format')
            ))
        
        conn.commit()
        cursor.close()
        return True