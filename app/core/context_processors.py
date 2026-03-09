# app/core/context_processors.py
"""
Jinja2 context processors.
Extracted from app.py to keep the factory lean.
"""
import os
import json
import logging

logger = logging.getLogger(__name__)

# ── Announcement cache (per-request helper) ───────────────────────────────────

def _get_active_announcements(instance_id):
    """Fetch active announcements for the current instance (global + instance-specific)."""
    if not instance_id:
        return []
    try:
        from app.core.database import get_db_connection
        with get_db_connection("core") as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, title, message FROM instance_announcements
                WHERE active = TRUE
                  AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
                  AND (instance_id IS NULL OR instance_id = %s)
                ORDER BY created_at DESC
            """, (instance_id,))
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rows
    except Exception:
        return []


def _count_pending_inquiries(instance_id):
    """Return count of pending user_inquiries for the given instance."""
    if not instance_id:
        return 0
    try:
        from app.core.database import get_db_connection
        with get_db_connection("core") as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) as c FROM user_inquiries WHERE instance_id=%s AND status='pending'",
                (instance_id,)
            )
            row = cur.fetchone()
            cur.close()
            return row['c'] if row else 0
    except Exception:
        return 0


# ── Registration ──────────────────────────────────────────────────────────────

def register_context_processors(app):
    """Attach all context processors to the Flask app."""

    @app.context_processor
    def inject_user_context():
        from flask import request, session
        from app.modules.auth.security import current_user
        from app.core.permissions import PermissionManager
        from app.core.module_access import get_user_available_modules
        from app.core.database import get_db_connection
        from app.core.instance_access import get_user_instances

        APP_VERSION = os.environ.get("APP_VERSION", "0.4.0")
        BRAND_TEAL = os.environ.get("BRAND_TEAL", "#00A3AD")

        default_settings = {
            'instance_name': 'Gridline Services',
            'instance_subtitle': 'Enterprise Platform',
            'logo_url': None,
            'favicon_url': None,
            'primary_color': '#0066cc',
            'secondary_color': '#00b4d8',
            'sidebar_bg_start': '#1a1d2e',
            'sidebar_bg_end': '#2d3142',
            'topbar_bg': '#ffffff',
        }

        # Resolve instance_id
        instance_id = request.args.get('instance_id', type=int)
        is_sandbox = False
        sandbox_instance_name = None

        cu = current_user()

        # S1/L3 without explicit instance_id → Sandbox (skip Horizon routes)
        if cu and not instance_id and not request.path.startswith('/horizon'):
            perm_level = cu.get('permission_level', '')
            if perm_level in ['S1', 'L3']:
                instance_id = 4
                is_sandbox = True

        if instance_id:
            try:
                with get_db_connection("core") as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT is_sandbox, name, display_name FROM instances WHERE id = %s",
                        (instance_id,)
                    )
                    inst = cur.fetchone()
                    cur.close()
                    if inst:
                        if inst.get('is_sandbox'):
                            is_sandbox = True
                        sandbox_instance_name = inst.get('display_name') or inst.get('name')
            except Exception as e:
                logger.warning(f"Failed to check sandbox status: {e}")

        # Unauthenticated — return minimal context
        if not cu:
            return {
                'cu': None, 'current_user': None,
                'can_send': False, 'can_inventory': False, 'can_asset': False,
                'can_fulfillment_customer': False, 'can_fulfillment_service': False,
                'can_fulfillment_manager': False, 'can_admin_users': False,
                'elevated': False,
                'is_sandbox': is_sandbox,
                'instance_id': instance_id,
                'instance_name': sandbox_instance_name or default_settings['instance_name'],
                'instance_subtitle': 'SANDBOX MODE' if is_sandbox else default_settings['instance_subtitle'],
                'instance_logo': default_settings['logo_url'],
                'instance_favicon': default_settings['favicon_url'],
                'instance_colors': {
                    'primary': default_settings['primary_color'],
                    'secondary': default_settings['secondary_color'],
                    'sidebar_bg_start': default_settings['sidebar_bg_start'],
                    'sidebar_bg_end': default_settings['sidebar_bg_end'],
                    'topbar_bg': default_settings['topbar_bg'],
                },
                'user_prefs': {},
                'current_sid': '',
                'active_announcements': [],
                'pending_inquiry_count': 0,
                'APP_VERSION': APP_VERSION,
                'BRAND_TEAL': BRAND_TEAL,
            }

        # Authenticated
        effective_perms = PermissionManager.get_effective_permissions(cu)
        permission_level = cu.get('permission_level', '')
        is_elevated = permission_level in ['L1', 'L2', 'L3', 'S1']

        # L3/S1 get full module access in sandbox
        if is_sandbox and permission_level in ['L3', 'S1']:
            effective_perms = {
                'can_send': True, 'can_inventory': True, 'can_asset': True,
                'can_fulfillment_customer': True, 'can_fulfillment_service': True,
                'can_fulfillment_manager': True,
            }

        try:
            user_prefs = json.loads(cu.get('user_preferences', '{}') or '{}')
        except Exception:
            user_prefs = {}

        # Accessible instances for L3/S1
        accessible_instances = []
        if permission_level in ['L3', 'S1']:
            accessible_instances = get_user_instances(cu)

        return {
            'cu': cu,
            'current_user': cu,
            'can_send': effective_perms.get('can_send', False) or is_elevated,
            'can_inventory': effective_perms.get('can_inventory', False) or is_elevated,
            'can_asset': effective_perms.get('can_asset', False) or is_elevated,
            'can_fulfillment_customer': effective_perms.get('can_fulfillment_customer', False) or is_elevated,
            'can_fulfillment_service': effective_perms.get('can_fulfillment_service', False) or is_elevated,
            'can_fulfillment_manager': effective_perms.get('can_fulfillment_manager', False) or is_elevated,
            'can_admin_users': is_elevated,
            'elevated': is_elevated,
            'available_modules': get_user_available_modules(cu),
            'accessible_instances': accessible_instances,
            'is_sandbox': is_sandbox,
            'instance_id': instance_id,
            'instance_name': sandbox_instance_name or default_settings['instance_name'],
            'instance_subtitle': 'SANDBOX MODE' if is_sandbox else default_settings['instance_subtitle'],
            'instance_logo': default_settings['logo_url'],
            'instance_favicon': default_settings['favicon_url'],
            'instance_colors': {
                'primary': default_settings['primary_color'],
                'secondary': default_settings['secondary_color'],
                'sidebar_bg_start': default_settings['sidebar_bg_start'],
                'sidebar_bg_end': default_settings['sidebar_bg_end'],
                'topbar_bg': default_settings['topbar_bg'],
            },
            'user_prefs': user_prefs,
            'current_sid': session.get('session_id', ''),
            'pending_inquiry_count': _count_pending_inquiries(instance_id) if is_elevated else 0,
            'active_announcements': _get_active_announcements(instance_id),
            'APP_VERSION': APP_VERSION,
            'BRAND_TEAL': BRAND_TEAL,
        }

    @app.context_processor
    def utility_processor():
        def get_instance_id():
            from flask import session, g
            return session.get('active_instance_id') or (
                g.cu.instance_id if hasattr(g, 'cu') and g.cu else None
            )
        return dict(get_instance_id=get_instance_id)
