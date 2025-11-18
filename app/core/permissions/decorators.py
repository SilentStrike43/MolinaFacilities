# app/core/permissions/decorators.py
"""
Permission and instance access decorators
"""
from functools import wraps
from flask import flash, redirect, url_for, request, session
import logging

logger = logging.getLogger(__name__)


def require_permission(permission_code: str):
    """
    Decorator to require specific permission code (M1, M2, M3A, etc.)
    
    Usage:
        @require_permission('M1')
        def send_package():
            ...
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            from app.modules.auth.security import current_user
            from .manager import PermissionManager
            
            user = current_user()
            if not user:
                flash("Please log in to access this page.", "warning")
                return redirect(url_for("auth.login"))
            
            # Check if user has the required permission
            if not PermissionManager.check_permission(user, permission_code):
                perm_desc = PermissionManager.get_permission_description(permission_code)
                flash(f"Access denied. Required: {perm_desc}", "danger")
                logger.warning(
                    f"Permission denied: {user.get('username')} attempted to access "
                    f"{request.endpoint} requiring {permission_code}"
                )
                return redirect(url_for("home.index"))
            
            return f(*args, **kwargs)
        return wrapped
    return decorator


def require_admin_level(min_level: str):
    """
    Decorator to require minimum admin level (L1, L2, L3, S1).
    
    Usage:
        @require_admin_level('L2')
        def manage_instances():
            ...
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            from app.modules.auth.security import current_user
            from .constants import PERMISSION_HIERARCHY
            
            user = current_user()
            if not user:
                flash("Please log in to access this page.", "warning")
                return redirect(url_for("auth.login"))
            
            user_level = user.get('permission_level', '')
            
            # Check if user has admin privileges
            if user_level not in ['L1', 'L2', 'L3', 'S1']:
                flash("Access denied. Admin privileges required.", "danger")
                logger.warning(
                    f"Admin access denied: {user.get('username')} attempted to access "
                    f"{request.endpoint} requiring {min_level}"
                )
                return redirect(url_for("home.index"))
            
            # Check hierarchy level
            user_rank = PERMISSION_HIERARCHY.get(user_level, 0)
            required_rank = PERMISSION_HIERARCHY.get(min_level, 100)
            
            if user_rank < required_rank:
                flash(f"Access denied. Minimum level required: {min_level}", "danger")
                logger.warning(
                    f"Insufficient admin level: {user.get('username')} ({user_level}) "
                    f"attempted to access {request.endpoint} requiring {min_level}"
                )
                return redirect(url_for("home.index"))
            
            return f(*args, **kwargs)
        return wrapped
    return decorator


def require_instance_access(instance_id_param: str = 'instance_id'):
    """
    Decorator to verify user has access to the specified instance.
    
    Args:
        instance_id_param: Name of the parameter/arg containing instance_id
    
    Usage:
        @require_instance_access()  # Looks for 'instance_id' in kwargs
        def view_instance(instance_id):
            ...
        
        @require_instance_access('inst_id')  # Custom parameter name
        def view_instance(inst_id):
            ...
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            from app.modules.auth.security import current_user
            from app.core.database import get_db_connection
            
            user = current_user()
            if not user:
                flash("Please log in to access this page.", "warning")
                return redirect(url_for("auth.login"))
            
            # Get instance_id from kwargs or request args
            instance_id = kwargs.get(instance_id_param) or request.args.get(instance_id_param, type=int)
            
            if not instance_id:
                flash("Instance ID required.", "warning")
                return redirect(url_for("home.index"))
            
            user_level = user.get('permission_level', '')
            user_instance_id = user.get('instance_id')
            
            # L3/S1 can access any instance
            if user_level in ['L3', 'S1']:
                return f(*args, **kwargs)
            
            # L2 can access multiple instances (check user_instance_access table)
            if user_level == 'L2':
                try:
                    with get_db_connection("core") as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            SELECT 1 FROM user_instance_access
                            WHERE user_id = %s AND instance_id = %s
                        """, (user.get('id'), instance_id))
                        has_access = cursor.fetchone() is not None
                        cursor.close()
                        
                        if has_access:
                            return f(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Error checking instance access: {e}")
            
            # L1 and regular users can only access their own instance
            if user_instance_id == instance_id:
                return f(*args, **kwargs)
            
            flash("Access denied to this instance.", "danger")
            logger.warning(
                f"Instance access denied: {user.get('username')} attempted to access "
                f"instance {instance_id} (user's instance: {user_instance_id})"
            )
            return redirect(url_for("home.index"))
        
        return wrapped
    return decorator


def require_instance_owner(instance_id_param: str = 'instance_id'):
    """
    Decorator to verify user is assigned to the specified instance.
    Stricter than require_instance_access - only allows users whose instance_id matches.
    L3/S1 still have access (global admins).
    
    Usage:
        @require_instance_owner()
        def edit_instance_data(instance_id):
            ...
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            from app.modules.auth.security import current_user
            
            user = current_user()
            if not user:
                flash("Please log in to access this page.", "warning")
                return redirect(url_for("auth.login"))
            
            # Get instance_id
            instance_id = kwargs.get(instance_id_param) or request.args.get(instance_id_param, type=int)
            
            if not instance_id:
                flash("Instance ID required.", "warning")
                return redirect(url_for("home.index"))
            
            user_level = user.get('permission_level', '')
            user_instance_id = user.get('instance_id')
            
            # L3/S1 bypass (global admins)
            if user_level in ['L3', 'S1']:
                return f(*args, **kwargs)
            
            # Must be assigned to this exact instance
            if user_instance_id == instance_id:
                return f(*args, **kwargs)
            
            flash("Access denied. You are not assigned to this instance.", "danger")
            logger.warning(
                f"Instance owner check failed: {user.get('username')} attempted to access "
                f"instance {instance_id} (user's instance: {user_instance_id})"
            )
            return redirect(url_for("home.index"))
        
        return wrapped
    return decorator


def require_any_permission(*permission_codes):
    """
    Decorator to require ANY of the specified permissions (OR logic).
    
    Usage:
        @require_any_permission('M1', 'M2', 'M3A')
        def view_dashboard():
            ...
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            from app.modules.auth.security import current_user
            from .manager import PermissionManager
            
            user = current_user()
            if not user:
                flash("Please log in to access this page.", "warning")
                return redirect(url_for("auth.login"))
            
            # Check if user has ANY of the required permissions
            has_any = any(
                PermissionManager.check_permission(user, perm)
                for perm in permission_codes
            )
            
            if not has_any:
                perms_str = " or ".join(permission_codes)
                flash(f"Access denied. Required: {perms_str}", "danger")
                logger.warning(
                    f"Permission denied: {user.get('username')} attempted to access "
                    f"{request.endpoint} requiring any of {permission_codes}"
                )
                return redirect(url_for("home.index"))
            
            return f(*args, **kwargs)
        return wrapped
    return decorator