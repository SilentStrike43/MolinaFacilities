# app/modules/auth/security.py - FIXED VERSION
from __future__ import annotations

import json
from functools import wraps
from typing import Any, Iterable, Optional

from flask import session, redirect, url_for, request, flash

import logging

def record_audit(user, action, source, details=""):
    """
    Record security/audit events.
    
    Args:
        user: User dict or None
        action: Action being audited (e.g., 'login', 'create_user')
        source: Source module (e.g., 'auth', 'users', 'admin')
        details: Additional details about the action
    """
    logger = logging.getLogger('app.security.audit')
    
    username = user.get('username', 'anonymous') if user else 'anonymous'
    user_id = user.get('id', 'N/A') if user else 'N/A'
    
    logger.info(
        f"AUDIT: {action} | User: {username} (ID:{user_id}) | Source: {source} | Details: {details}"
    )

# Import user lookup functions
from app.modules.users.models import get_user_by_id as _get_user_by_id, get_user_by_username as _get_user_by_username

# ----------------------------- user lookup -----------------------------

def _row_to_dict(row: Any) -> dict:
    """Convert database row to dict."""
    if row is None:
        return {}
    
    # If it's already a dict, return it
    if isinstance(row, dict):
        return row
    
    # If it has cursor_description (pyodbc Row), convert it
    try:
        if hasattr(row, 'cursor_description'):
            return dict(zip([col[0] for col in row.cursor_description], row))
    except:
        pass
    
    # Try generic dict conversion
    try:
        return dict(row)
    except:
        return {}

def _fetch_user_by_id(uid: Any) -> Optional[dict]:
    """Fetch user by ID and return as dict."""
    if uid is None:
        return None
    
    row = _get_user_by_id(uid)
    return _row_to_dict(row) if row else None

def _fetch_user_by_username(username: str) -> Optional[dict]:
    """Fetch user by username and return as dict."""
    if not username:
        return None
    
    row = _get_user_by_username(username)
    return _row_to_dict(row) if row else None

# ------------------------------ session API ----------------------------

def current_user():
    """Get current logged-in user (cached per request)."""
    from flask import g
    
    # Check if already cached in this request
    if hasattr(g, '_current_user_cache'):
        return g._current_user_cache
    
    user_id = session.get("user_id")
    
    if not user_id:
        g._current_user_cache = None
        return None
    
    # Get user from database
    from app.modules.users.models import get_user_by_id
    user = get_user_by_id(user_id)
    
    if not user:
        # User doesn't exist anymore, clear session
        session.clear()
        g._current_user_cache = None
        return None
    
    # Convert to dict properly for pyodbc Row objects
    if hasattr(user, 'cursor_description'):
        # pyodbc Row object - convert using column names
        user_dict = dict(zip([col[0] for col in user.cursor_description], user))
    elif isinstance(user, dict):
        # Already a dict
        user_dict = user
    else:
        # Try generic conversion
        try:
            user_dict = dict(user)
        except TypeError:
            # If conversion fails, try extracting attributes
            user_dict = {}
            for key in dir(user):
                if not key.startswith('_'):
                    try:
                        user_dict[key] = getattr(user, key)
                    except:
                        pass
    
    # Add effective permissions
    try:
        from app.core.permissions import PermissionManager
        user_dict['effective_permissions'] = PermissionManager.get_effective_permissions(user_dict)
        user_dict['permission_level_desc'] = PermissionManager.get_permission_description(
            user_dict.get('permission_level', '')
        )
    except Exception as e:
        user_dict['effective_permissions'] = {}
        user_dict['permission_level_desc'] = 'Unknown'
    
    # Cache the result
    g._current_user_cache = user_dict
    return user_dict

def get_user_instance_context(instance_id=None):
    """
    Get user's context for a specific instance.
    For L3/S1 accessing sandbox, gives full permissions.
    """
    from app.core.database import get_db_connection
    
    user = current_user()
    if not user:
        return None
    
    print(f"🔐 GET CONTEXT: user={user.get('username')}, instance_id={instance_id}, perm={user.get('permission_level')}")
    
    if instance_id is not None:
        # Check if this instance is the sandbox
        try:
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT is_sandbox, name, display_name 
                    FROM instances 
                    WHERE id = %s
                """, (instance_id,))
                inst = cursor.fetchone()
                cursor.close()
                
                # If it's the sandbox and user is L3/S1, give full access
                if inst and inst.get('is_sandbox'):
                    perm_level = user.get('permission_level')
                    if perm_level in ['L3', 'S1']:
                        print(f"✅ Granting sandbox access to {perm_level} user")
                        return {
                            **user,
                            'instance_id': instance_id,
                            'instance_name': inst['name'] or 'Global Sandbox',
                            'can_send': True,
                            'can_inventory': True,
                            'can_asset': True,
                            'can_fulfillment_customer': True,
                            'can_fulfillment_service': True,
                            'can_fulfillment_manager': True,
                        }
                    else:
                        print(f"❌ User {user.get('username')} cannot access sandbox (perm: {perm_level})")
                        return None
        except Exception as e:
            print(f"❌ Error checking sandbox: {e}")
            import traceback
            traceback.print_exc()
    
    # Regular instance access
    if instance_id:
        try:
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT u.*, i.name as instance_name, i.display_name
                    FROM users u
                    JOIN instances i ON u.instance_id = i.id
                    WHERE u.id = %s AND u.instance_id = %s
                """, (user['id'], instance_id))
                result = cursor.fetchone()
                cursor.close()
                
                if result:
                    return dict(result)
        except Exception as e:
            print(f"❌ Error getting instance context: {e}")
            import traceback
            traceback.print_exc()
    
    return user

# ------------------------------ capability logic -----------------------

def _parse_caps(u: dict) -> dict:
    """
    FIXED: Parse user capabilities from both old caps field and new permission system.
    
    Caps can be stored as JSON text, a dict, or a list of strings.
    Return a dict-like view with booleans.
    
    Also checks permission_level AND module_permissions fields.
    """
    raw = u.get("caps")
    caps_dict: dict[str, bool] = {}

    # Parse old-style caps field
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}

    if isinstance(raw, dict):
        caps_dict.update({str(k): bool(v) for k, v in raw.items()})
    elif isinstance(raw, (list, tuple, set)):
        for k in raw:
            caps_dict[str(k)] = True

    # Also honor explicit boolean columns if they exist
    for k in ("is_admin", "is_sysadmin"):
        if k in u:
            caps_dict[k] = bool(u[k])
    
    # NEW: Use PermissionManager for comprehensive permission checking
    try:
        from app.core.permissions import PermissionManager
        
        # Get effective permissions using PermissionManager
        effective_perms = PermissionManager.get_effective_permissions(u)
        
        # Map effective permissions to capability flags
        if effective_perms.get("can_send"):
            caps_dict["can_send"] = True
        
        if effective_perms.get("can_inventory"):
            caps_dict["can_inventory"] = True
            caps_dict["can_asset"] = True  # Alias
        
        if effective_perms.get("can_fulfillment_customer"):
            caps_dict["can_fulfillment_customer"] = True
        
        if effective_perms.get("can_fulfillment_service"):
            caps_dict["can_fulfillment_staff"] = True  # Map M3B to staff
        
        if effective_perms.get("can_fulfillment_manager"):
            caps_dict["can_fulfillment_staff"] = True  # M3C includes staff access
            caps_dict["can_fulfillment_customer"] = True  # M3C includes customer access
        
        # Admin permissions
        if effective_perms.get("can_admin_users"):
            caps_dict["is_admin"] = True
            caps_dict["can_users"] = True
        
        if effective_perms.get("can_admin_system"):
            caps_dict["is_admin"] = True
            caps_dict["is_sysadmin"] = True
            caps_dict["can_users"] = True
        
        if effective_perms.get("can_admin_developer"):
            caps_dict["is_admin"] = True
            caps_dict["is_sysadmin"] = True
            caps_dict["can_users"] = True
        
        if effective_perms.get("is_system"):
            caps_dict["is_admin"] = True
            caps_dict["is_sysadmin"] = True
            caps_dict["can_users"] = True
            caps_dict["is_system"] = True
            
    except ImportError as e:
        # If PermissionManager not available, fall back to legacy behavior
        print(f"Warning: Could not import PermissionManager: {e}")
        pass
    except Exception as e:
        print(f"Error parsing permissions: {e}")
        pass

    return caps_dict

# synonyms / compound capabilities used around the app
_CAP_SYNONYMS = {
    "asset": "can_asset",
    "inventory": "can_inventory",
    "can_asset": "can_asset",
    "can_inventory": "can_inventory",
    "send": "can_send",
    "can_send": "can_send",
    "insights": "can_insights",
    "can_insights": "can_insights",
    "users": "can_users",
    "can_users": "can_users",
    "admin": "is_admin",
    "sysadmin": "is_sysadmin",
    "fulfillment_staff": "can_fulfillment_staff",
    "can_fulfillment_staff": "can_fulfillment_staff",
    "fulfillment_customer": "can_fulfillment_customer",
    "can_fulfillment_customer": "can_fulfillment_customer",
    "fulfillment_any": "fulfillment_any",
}

def has_cap(user_row: Optional[dict], cap: str) -> bool:
    """
    Central capability check.
    - sysadmins/admins always pass
    - understands both JSON caps and boolean columns
    - supports synonyms and the special 'fulfillment_any'
    """
    if not user_row:
        return False
    u = _row_to_dict(user_row)
    caps = _parse_caps(u)

    # admin/sysadmin bypass
    if caps.get("is_sysadmin") or caps.get("is_admin"):
        return True

    key = _CAP_SYNONYMS.get(cap, cap)

    if key == "fulfillment_any":
        return bool(caps.get("can_fulfillment_staff") or caps.get("can_fulfillment_customer"))

    return bool(caps.get(key))

# ------------------------------- decorators ----------------------------

def login_required(f):
    """Decorator to require login for routes."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        user_id = session.get("user_id")
        print(f"✓ login_required check: user_id in session = {user_id}")
        print(f"✓ Session contents: {dict(session)}")
        
        if not user_id:
            session['next_url'] = request.url
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("auth.login"))
        
        return f(*args, **kwargs)
    
    return wrapped

def require_cap(cap: str):
    def deco(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            u = current_user()
            if not u:
                flash("Please sign in to continue.", "warning")
                return redirect(url_for("auth.login", next=request.full_path or request.path))
            if not has_cap(u, cap):
                # DEBUG - More detailed output
                print(f"⚠️ PERMISSION DENIED: User {u.get('username')} tried to access {request.endpoint} requiring '{cap}'")
                print(f"   URL: {request.url}")
                print(f"   User permission_level: {u.get('permission_level')}")
                print(f"   User module_permissions: {u.get('module_permissions')}")
                print(f"   Parsed caps: {_parse_caps(u)}")
                
                flash(f"Access denied. You need '{cap}' permission to access this feature.", "danger")
                return redirect(url_for("home.index"))
            return view(*args, **kwargs)
        return wrapped
    return deco

def require_any(caps: Iterable[str]):
    caps = list(caps)
    def deco(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            u = current_user()
            if not u:
                flash("Please sign in to continue.", "warning")
                return redirect(url_for("auth.login", next=request.full_path or request.path))
            if not any(has_cap(u, c) for c in caps):
                flash("Access denied for this feature.", "danger")
                return redirect(url_for("home.index"))
            return view(*args, **kwargs)
        return wrapped
    return deco
    
def get_audit_logs(filters: dict = None, limit: int = 100):
    """Get audit logs with optional filters."""
    from app.core.database import get_db_connection
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        query = "SELECT * FROM audit_logs WHERE 1=1"
        params = []
        
        if filters:
            if filters.get("user_id"):
                query += " AND user_id = %s"
                params.append(filters["user_id"])
            
            if filters.get("action"):
                query += " AND action = %s"
                params.append(filters["action"])
            
            if filters.get("module"):
                query += " AND module = %s"
                params.append(filters["module"])
            
            if filters.get("date_from"):
                query += " AND DATE(ts_utc) >= %s"
                params.append(filters["date_from"])
            
            if filters.get("date_to"):
                query += " AND DATE(ts_utc) <= %s"
                params.append(filters["date_to"])
            
            if filters.get("permission_level"):
                query += " AND permission_level = %s"
                params.append(filters["permission_level"])
            
            if filters.get("target_user_id"):
                query += " AND target_user_id = %s"
                params.append(filters["target_user_id"])
        
        query += " ORDER BY ts_utc DESC LIMIT %s"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()
        return [dict(row) for row in rows]

def get_audit_statistics(days=30):
    """Get audit log statistics for dashboard."""
    from datetime import datetime, timedelta
    from app.core.database import get_db_connection
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        cutoff_date = (datetime.utcnow() - timedelta(days=days)).date()
        
        stats = {}
        
        # Total actions
        cursor.execute(
            "SELECT COUNT(*) as count FROM audit_logs WHERE DATE(ts_utc) >= %s", 
            (cutoff_date,)
        )
        stats["total_actions"] = cursor.fetchone()['count']
        
        # Actions by module
        cursor.execute("""
            SELECT module, COUNT(*) as count
            FROM audit_logs
            WHERE DATE(ts_utc) >= %s
            GROUP BY module
            ORDER BY count DESC
        """, (cutoff_date,))
        module_stats = cursor.fetchall()
        stats["by_module"] = {row['module']: row['count'] for row in module_stats}
        
        # Actions by permission level
        cursor.execute("""
            SELECT permission_level, COUNT(*) as count
            FROM audit_logs
            WHERE DATE(ts_utc) >= %s AND permission_level != ''
            GROUP BY permission_level
            ORDER BY count DESC
        """, (cutoff_date,))
        level_stats = cursor.fetchall()
        stats["by_level"] = {row['permission_level']: row['count'] for row in level_stats}
        
        # Most active users
        cursor.execute("""
            SELECT username, COUNT(*) as count
            FROM audit_logs
            WHERE DATE(ts_utc) >= %s
            GROUP BY username
            ORDER BY count DESC
            LIMIT 10
        """, (cutoff_date,))
        user_stats = cursor.fetchall()
        stats["top_users"] = [(row['username'], row['count']) for row in user_stats]
        
        # Critical actions
        cursor.execute("""
            SELECT COUNT(*) as count FROM audit_logs
            WHERE DATE(ts_utc) >= %s
            AND action IN ('delete_user', 'elevate_user', 'system_config_change')
        """, (cutoff_date,))
        stats["critical_actions"] = cursor.fetchone()['count']
        
        cursor.close()
        
        return stats


# --------- convenience shims (let old names continue to work) ----------

# Common single-cap wrappers used throughout the codebase.
require_inventory     = require_cap("inventory")
require_asset         = require_cap("inventory")
require_send          = require_cap("can_send")
require_insights      = require_cap("insights")
require_users         = require_cap("users")
require_admin         = require_cap("admin")
require_sysadmin      = require_cap("sysadmin")
require_fulfillment_staff    = require_cap("fulfillment_staff")
require_fulfillment_customer = require_cap("fulfillment_customer")
require_fulfillment_any      = require_cap("fulfillment_any")