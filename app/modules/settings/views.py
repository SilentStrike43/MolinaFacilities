# app/modules/settings/views.py
import json
import re
import logging
from flask import render_template, request, jsonify, g

from . import bp
from app.modules.auth.security import login_required, current_user
from app.core.database import get_db_connection
from app.core.instance_context import get_current_instance

logger = logging.getLogger(__name__)


def _is_valid_hex_color(value):
    """Validate a #RRGGBB hex color string."""
    if not value:
        return True  # Empty = use default
    return bool(re.match(r'^#[0-9A-Fa-f]{6}$', value))


@bp.route("/", methods=["GET"])
@login_required
def index():
    cu = current_user()

    # Parse saved preferences
    raw = cu.get('user_preferences') or '{}'
    try:
        prefs = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        prefs = {}

    # Determine sandbox context
    is_sandbox = False
    try:
        current_instance = get_current_instance()
        is_sandbox = (current_instance == 4)
    except RuntimeError:
        pass

    # Build module access summary
    perm = cu.get('permission_level', '')
    caps = cu.get('caps') or {}
    if isinstance(caps, str):
        try:
            caps = json.loads(caps)
        except Exception:
            caps = {}

    ep = cu.get('effective_permissions') or {}

    access = {
        'send':                   ep.get('can_send', False) or perm in ('L1','L2','L3','S1'),
        'inventory':              ep.get('can_inventory', False) or perm in ('L1','L2','L3','S1'),
        'fulfillment_customer':   ep.get('can_fulfillment_customer', False) or perm in ('L1','L2','L3','S1'),
        'fulfillment_staff':      ep.get('can_fulfillment_service', False) or perm in ('L1','L2','L3','S1'),
        'fulfillment_manager':    ep.get('can_fulfillment_manager', False) or perm in ('L1','L2','L3','S1'),
        'admin_users':            perm in ('L1','L2','L3','S1'),
        'multi_instance':         perm in ('L2','L3','S1'),
        'horizon':                perm in ('L3','S1'),
        'sysadmin':               perm == 'S1',
    }

    return render_template(
        "settings/index.html",
        active="settings",
        cu=cu,
        prefs=prefs,
        access=access,
        is_sandbox=is_sandbox,
    )


@bp.route("/save", methods=["POST"])
@login_required
def save_preferences():
    cu = current_user()
    data = request.get_json(silent=True) or {}

    sidebar_color = data.get('sidebar_color', '').strip()
    topbar_color  = data.get('topbar_color', '').strip()
    theme         = data.get('theme', '').strip()

    # Validate colors
    if not _is_valid_hex_color(sidebar_color):
        return jsonify({"success": False, "error": "Invalid sidebar color"}), 400
    if not _is_valid_hex_color(topbar_color):
        return jsonify({"success": False, "error": "Invalid topbar color"}), 400
    if theme and theme not in ('light', 'dark'):
        return jsonify({"success": False, "error": "Invalid theme value"}), 400

    # Load existing prefs so we don't clobber unrelated keys
    raw = cu.get('user_preferences') or '{}'
    try:
        prefs = json.loads(raw)
    except Exception:
        prefs = {}

    if sidebar_color:
        prefs['sidebar_color'] = sidebar_color
    else:
        prefs.pop('sidebar_color', None)

    if topbar_color:
        prefs['topbar_color'] = topbar_color
    else:
        prefs.pop('topbar_color', None)

    if theme:
        prefs['theme'] = theme

    prefs_json = json.dumps(prefs)

    try:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET user_preferences = %s WHERE id = %s",
                (prefs_json, cu['id'])
            )
            conn.commit()
            cursor.close()

        # Invalidate request-level cache so next call to current_user() re-fetches
        if hasattr(g, '_current_user_cache'):
            delattr(g, '_current_user_cache')

        return jsonify({"success": True})

    except Exception as e:
        logger.error(f"Failed to save user preferences for user {cu.get('id')}: {e}")
        return jsonify({"success": False, "error": "Database error"}), 500
