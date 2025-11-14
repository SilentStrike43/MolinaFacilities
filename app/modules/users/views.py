# app/modules/users/views.py
"""
Users Module - Instance-Aware Edition
L1: Can only view/manage users in their own instance
L2: Can view/manage users in instances they have access to
L3/S1: Can view/manage users across all instances (use Horizon instead)
"""

import json
import logging
from datetime import datetime
from typing import List
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from werkzeug.security import generate_password_hash

from .models import (
    get_user_by_id,
    get_user_by_username,
    create_user,
)
from app.core.database import get_db_connection
from app.core.instance_context import get_current_instance
from app.modules.auth.security import (
    login_required,
    current_user,
)
from app.modules.users.permissions import PermissionManager, PermissionLevel

users_bp = Blueprint("users", __name__, url_prefix="/users", template_folder="templates")
bp = users_bp

logger = logging.getLogger(__name__)


def row_to_dict(row):
    """Convert database Row to dictionary."""
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except:
        return row


# Audit logging wrapper
def record_audit(user_data, action, module, details, target_user_id=None, target_username=None):
    """Wrapper for admin module's database audit logging"""
    from app.modules.admin.views import record_audit_log
    record_audit_log(user_data, action, module, details, target_user_id, target_username)


# ---------- Database helpers ----------
def list_users(instance_id=None, include_system=False, include_deleted=False):
    """
    List users with instance filtering.
    
    Args:
        instance_id: Filter by specific instance (None = all instances)
        include_system: Include system users
        include_deleted: Include deleted users
    """
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        query = "SELECT * FROM users WHERE 1=1"
        params = []
        
        if not include_system:
            query += " AND username NOT IN ('system', 'sysadmin', 'AppAdmin')"
        
        if not include_deleted:
            query += " AND deleted_at IS NULL"
        
        if instance_id is not None:
            query += " AND instance_id = %s"
            params.append(instance_id)
        
        query += " ORDER BY username"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()
        return rows


def get_user_permission_level(user_data):
    """Get the effective permission level for a user."""
    if not user_data:
        return None
    
    # Convert to dict if needed
    if not isinstance(user_data, dict):
        user_data = dict(user_data)
    
    # Check for system flag first
    try:
        caps = json.loads(user_data.get("caps", "{}") or "{}")
        if caps.get("is_system"):
            return "S1"
    except:
        pass
    
    # Check explicit permission_level field
    if user_data.get("permission_level"):
        return user_data["permission_level"]
    
    # Legacy compatibility
    if user_data.get("is_sysadmin"):
        return "L2"
    elif user_data.get("is_admin"):
        return "L1"
    
    return None


def update_user_permissions(uid: int, permission_level: str, module_permissions: List[str], 
                           elevated_by: int = None, reason: str = None):
    """Update user permissions with history tracking."""
    user = get_user_by_id(uid)
    if not user:
        return False
    
    user = row_to_dict(user)
    
    # Get old permissions for history
    old_level = user.get("permission_level", "")
    old_modules = user.get("module_permissions", "[]")
    
    # Update user
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE users 
            SET permission_level = %s,
                module_permissions = %s,
                elevated_by = %s,
                elevated_at = %s,
                last_modified_at = %s
            WHERE id = %s
        """, (
            permission_level,
            json.dumps(module_permissions),
            elevated_by,
            datetime.utcnow() if elevated_by else None,
            datetime.utcnow(),
            uid
        ))
        
        # Record elevation history if this is an elevation
        if elevated_by and (permission_level != old_level or json.dumps(module_permissions) != old_modules):
            cursor.execute("""
                INSERT INTO user_elevation_history(
                    user_id, elevated_by, old_level, new_level,
                    old_permissions, new_permissions, reason, elevated_at
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)
            """, (
                uid, elevated_by, old_level, permission_level,
                old_modules, json.dumps(module_permissions), reason
            ))
        
        conn.commit()
        cursor.close()
    
    return True


def _request_user_deletion_db(uid: int, reason: str = None):
    """Request user account deletion (requires admin approval)."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO deletion_requests(user_id, reason, status, requested_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
        """, (uid, reason, "pending"))
        
        # Mark user as deletion requested
        cursor.execute("""
            UPDATE users 
            SET deletion_requested_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (uid,))
        
        conn.commit()
        cursor.close()


def approve_user_deletion(uid: int, approved_by: int, notes: str = None):
    """Approve and execute user deletion."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        # Update deletion request
        cursor.execute("""
            UPDATE deletion_requests
            SET status = 'approved',
                approved_by = %s,
                approved_at = CURRENT_TIMESTAMP
            WHERE user_id = %s AND status = 'pending'
        """, (approved_by, uid))
        
        # Soft delete the user
        cursor.execute("""
            UPDATE users 
            SET deleted_at = CURRENT_TIMESTAMP,
                deletion_approved_by = %s,
                deletion_notes = %s
            WHERE id = %s
        """, (approved_by, notes, uid))
        
        conn.commit()
        cursor.close()


# ---------- Permission Checking ----------
def can_view_users(user_data) -> bool:
    """Check if user can view user list."""
    if not user_data:
        return False
    
    level = get_user_permission_level(user_data)
    if level in ["L1", "L2", "L3", "S1"]:
        return True
    
    return False


def can_create_users(user_data) -> bool:
    """Check if user can create new users (L1+)."""
    if not user_data:
        return False
    
    level = get_user_permission_level(user_data)
    return level in ["L1", "L2", "L3", "S1"]


def can_modify_user(actor_data, target_data) -> bool:
    """Check if actor can modify target user."""
    if not actor_data:
        return False
    
    # Convert to dict
    if not isinstance(actor_data, dict):
        actor_data = dict(actor_data)
    if target_data and not isinstance(target_data, dict):
        target_data = dict(target_data)
    
    actor_level = get_user_permission_level(actor_data)
    target_level = get_user_permission_level(target_data) if target_data else None
    
    # Use PermissionManager to check
    return PermissionManager.can_modify_user(actor_level, target_level or "")


def can_elevate_users(user_data, to_level=None) -> bool:
    """Check if user can elevate others."""
    if not user_data:
        return False
    
    actor_level = get_user_permission_level(user_data)
    
    if to_level:
        return PermissionManager.can_elevate_to(actor_level, to_level)
    
    return actor_level in ["L1", "L2", "L3", "S1"]


def get_accessible_instances(user):
    """Get list of instances user can access."""
    if not user:
        return []
    
    user_level = get_user_permission_level(user)
    
    # L3/S1 can access all instances
    if user_level in ['L3', 'S1']:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, display_name 
                FROM instances 
                ORDER BY name
            """)
            instances = cursor.fetchall()
            cursor.close()
            return instances
    
    # L2 can access instances they're granted access to
    if user_level == 'L2':
        from app.core.instance_access import get_user_instances
        return get_user_instances(user)
    
    # L1 and below can only access their own instance
    user_instance_id = user.get('instance_id')
    if user_instance_id:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, display_name 
                FROM instances 
                WHERE id = %s
            """, (user_instance_id,))
            instance = cursor.fetchone()
            cursor.close()
            return [instance] if instance else []
    
    return []


# ---------- Routes ----------

@users_bp.route("/")
@login_required
def user_list():
    """
    List users - Instance-aware:
    - L1: Only see users in their own instance
    - L2: See users in instances they have access to
    - L3/S1: Should use Horizon global users instead
    """
    cu = current_user()
    instance_id = request.args.get('instance_id', type=int)
    
    user_level = get_user_permission_level(cu)
    
    # L3/S1 should use Horizon
    if user_level in ['L3', 'S1']:
        flash("Please use Horizon Global Users for cross-instance user management.", "info")
        return redirect(url_for('horizon.global_users'))
    
    # L2 must have access to the requested instance
    if user_level == 'L2':
        from app.core.instance_access import user_can_access_instance
        
        if instance_id:
            if not user_can_access_instance(cu, instance_id):
                flash("Access denied to this instance.", "danger")
                instance_id = None
        
        # If no instance specified, show their accessible instances
        if not instance_id:
            accessible = get_accessible_instances(cu)
            if len(accessible) == 1:
                instance_id = accessible[0]['id']
            else:
                return render_template(
                    "users/select_instance.html",
                    active="users",
                    instances=accessible
                )
    
    # L1 - force to their own instance
    if user_level == 'L1':
        instance_id = cu.get('instance_id')
        if not instance_id:
            flash("No instance assigned.", "danger")
            return redirect(url_for('home.index'))
    
    # Regular users without admin permissions
    if not user_level:
        instance_id = cu.get('instance_id')
        if not instance_id:
            flash("No instance assigned.", "danger")
            return redirect(url_for('home.index'))
    
    # Get instance info
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, name, display_name, is_active
            FROM instances WHERE id = %s
        """, (instance_id,))
        instance = cursor.fetchone()
        
        if not instance:
            flash("Instance not found.", "danger")
            return redirect(url_for('home.index'))
        
        # Get users for this instance
        show_inactive = request.args.get('show_inactive') == 'true'
        
        query = """
            SELECT id, username, first_name, last_name, email, phone,
                   permission_level, module_permissions, is_active,
                   created_at, last_login, department, position
            FROM users
            WHERE instance_id = %s
        """
        params = [instance_id]
        
        if not show_inactive:
            query += " AND deleted_at IS NULL AND is_active = true"
        
        query += " ORDER BY username"
        
        cursor.execute(query, params)
        users = cursor.fetchall()
        cursor.close()
    
    return render_template(
        "users/list.html",
        active="users",
        users=users,
        instance=instance,
        instance_id=instance_id,
        show_inactive=show_inactive,
        can_manage=user_level in ['L1', 'L2']
    )


@users_bp.route("/profile/<int:uid>")
@login_required
def view_profile(uid: int):
    """View detailed user profile."""
    cu = current_user()
    
    # Get target user
    target = get_user_by_id(uid)
    if not target:
        flash("User not found.", "warning")
        return redirect(url_for("users.user_list"))
    
    target = row_to_dict(target)
    
    # Check permissions
    if uid != cu['id'] and not can_view_users(cu):
        flash("You don't have permission to view this profile.", "danger")
        return redirect(url_for("users.user_list"))
    
    # Verify instance access for non-own profiles
    if uid != cu['id']:
        user_level = get_user_permission_level(cu)
        
        if user_level == 'L1':
            # L1 can only view users in their own instance
            if target.get('instance_id') != cu.get('instance_id'):
                flash("Access denied - user belongs to different instance.", "danger")
                return redirect(url_for("users.user_list"))
        
        elif user_level == 'L2':
            # L2 must have access to the target's instance
            from app.core.instance_access import user_can_access_instance
            if not user_can_access_instance(cu, target.get('instance_id')):
                flash("Access denied - user belongs to instance you cannot access.", "danger")
                return redirect(url_for("users.user_list"))
    
    # Get permission information
    permission_level = get_user_permission_level(target)
    permission_desc = PermissionManager.get_permission_description(permission_level or "")
    effective_perms = PermissionManager.get_effective_permissions(target)
    module_perms_list = PermissionManager.parse_module_permissions(target.get("module_permissions", "[]"))
    
    # Get recent audit logs for this user
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT action, module, details, ts_utc
            FROM audit_logs
            WHERE user_id = %s
            ORDER BY ts_utc DESC LIMIT 5
        """, (uid,))
        recent_actions = cursor.fetchall()
        cursor.close()
    
    # Get elevation history if admin
    elevation_history = []
    if permission_level:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT old_level, new_level, reason, elevated_at,
                    (SELECT username FROM users WHERE id = elevated_by) as elevated_by_name
                FROM user_elevation_history
                WHERE user_id = %s
                ORDER BY elevated_at DESC LIMIT 5
            """, (uid,))
            elevation_history = cursor.fetchall()
            cursor.close()
    
    # Record profile view
    record_audit(cu, "view_user_profile", "users", f"Viewed profile of {target['username']}")
    
    return render_template(
        "users/profile_view.html",
        active="users",
        page="profile",
        user=target,
        permission_level=permission_level,
        permission_desc=permission_desc,
        effective_perms=effective_perms,
        module_perms_list=module_perms_list,
        recent_actions=recent_actions,
        elevation_history=elevation_history,
        is_own_profile=(uid == cu['id'])
    )


@users_bp.route("/profile")
@login_required
def profile():
    """User's own profile page."""
    cu = current_user()
    user_data = dict(cu)
    
    # Add effective permissions
    user_data["effective_permissions"] = PermissionManager.get_effective_permissions(user_data)
    user_data["permission_level_desc"] = PermissionManager.get_permission_description(
        user_data.get("permission_level", "")
    )
    
    # Get deletion request status if any
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM deletion_requests 
            WHERE user_id = %s AND status = 'pending'
            ORDER BY requested_at DESC LIMIT 1
        """, (cu["id"],))
        deletion_request = cursor.fetchone()
        cursor.close()
    
    return render_template("users/profile.html",
                         active="users",
                         page="profile",
                         user=user_data,
                         deletion_request=deletion_request)


@users_bp.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    """Edit own profile."""
    cu = current_user()
    
    if request.method == "POST":
        # Update profile fields
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users 
                SET first_name = %s, last_name = %s, 
                    email = %s, phone = %s,
                    department = %s, position = %s,
                    last_modified_at = %s
                WHERE id = %s
            """, (
                request.form.get("first_name", ""),
                request.form.get("last_name", ""),
                request.form.get("email", ""),
                request.form.get("phone", ""),
                request.form.get("department", ""),
                request.form.get("position", ""),
                datetime.utcnow(),
                cu["id"]
            ))
            conn.commit()
            cursor.close()
        
        record_audit(cu, "update_profile", "users", "Updated own profile")
        flash("Profile updated successfully.", "success")
        return redirect(url_for("users.profile"))
    
    return render_template("users/edit_profile.html",
                         active="users",
                         page="profile",
                         user=cu)


@users_bp.route("/profile/delete", methods=["POST"])
@login_required
def request_deletion():
    """Request account deletion."""
    cu = current_user()
    reason = request.form.get("reason", "")
    
    _request_user_deletion_db(cu["id"], reason)
    record_audit(cu, "request_deletion", "users", f"Requested account deletion: {reason}")
    flash("Deletion request submitted. An administrator will review your request.", "info")
    
    return redirect(url_for("users.profile"))


@users_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    """Create new user (L1+ only) - instance-aware."""
    cu = current_user()
    
    if not can_create_users(cu):
        flash("You need L1 (Module Administrator) permissions or higher to create users.", "danger")
        return redirect(url_for("users.user_list"))
    
    user_level = get_user_permission_level(cu)
    
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        
        if not username or not password:
            flash("Username and password are required.", "danger")
            return redirect(url_for("users.create"))
        
        # Check if username exists
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
            existing = cursor.fetchone()
            cursor.close()
        
        if existing:
            flash("Username already exists.", "danger")
            return redirect(url_for("users.create"))
        
        # Collect module permissions
        module_perms = []
        if request.form.get("perm_m1"):
            module_perms.append("M1")
        if request.form.get("perm_m2"):
            module_perms.append("M2")
        if request.form.get("perm_m3a"):
            module_perms.append("M3A")
        if request.form.get("perm_m3b"):
            module_perms.append("M3B")
        if request.form.get("perm_m3c"):
            module_perms.append("M3C")
        
        # Determine instance_id
        instance_id = request.args.get('instance_id', type=int)
        
        # Validate instance access
        if user_level == 'L1':
            # L1 can only create users in their own instance
            instance_id = cu.get('instance_id')
        elif user_level == 'L2':
            # L2 must have access to the target instance
            if not instance_id:
                flash("Please specify an instance.", "danger")
                return redirect(url_for('users.create'))
            
            from app.core.instance_access import user_can_access_instance
            if not user_can_access_instance(cu, instance_id):
                flash("Access denied to this instance.", "danger")
                return redirect(url_for('users.user_list'))
        elif user_level in ['L3', 'S1']:
            # L3/S1 should use Horizon
            flash("Please use Horizon to create users across instances.", "info")
            return redirect(url_for('horizon.create_global_user'))
        
        if not instance_id:
            flash("No instance specified.", "danger")
            return redirect(url_for('users.user_list'))

        # Hash the password
        import hashlib
        pw_hash = hashlib.sha256(password.encode()).hexdigest()

        # Create user
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (
                    username, password_hash, first_name, last_name,
                    email, phone, department, position,
                    permission_level, module_permissions, instance_id,
                    is_active, created_at, created_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP, %s)
                RETURNING id
            """, (
                username, pw_hash,
                request.form.get("first_name", ""),
                request.form.get("last_name", ""),
                request.form.get("email", ""),
                request.form.get("phone", ""),
                request.form.get("department", ""),
                request.form.get("position", ""),
                "",  # permission_level (empty for module users)
                json.dumps(module_perms),
                instance_id,
                cu["id"]
            ))
            uid = cursor.fetchone()['id']
            conn.commit()
            cursor.close()

        record_audit(cu, "create_user", "users", 
                    f"Created user {username} with permissions: {', '.join(module_perms)}")
        
        flash(f"User '{username}' created successfully.", "success")
        return redirect(url_for("users.user_list", instance_id=instance_id))
    
    # GET - show form
    accessible_instances = get_accessible_instances(cu)
    
    return render_template("users/create.html",
                         active="users",
                         page="create",
                         instances=accessible_instances)


@users_bp.route("/edit/<int:uid>", methods=["GET","POST"])
@login_required
def edit_user(uid: int):
    """Edit user (admin only) - instance-aware."""
    cu = current_user()
    user_level = get_user_permission_level(cu)
    
    try:
        target = get_user_by_id(uid)
        
        if not target:
            flash("User not found.", "warning")
            return redirect(url_for("users.user_list"))
        
        target = row_to_dict(target)
        
        if not can_modify_user(cu, target):
            flash("You cannot modify users at your level or higher.", "danger")
            return redirect(url_for("users.user_list"))
        
        # Verify instance access
        if user_level == 'L1':
            if target.get('instance_id') != cu.get('instance_id'):
                flash("Access denied - user belongs to different instance.", "danger")
                return redirect(url_for('users.user_list', instance_id=cu.get('instance_id')))
        elif user_level == 'L2':
            from app.core.instance_access import user_can_access_instance
            if not user_can_access_instance(cu, target.get('instance_id')):
                flash("Access denied - user belongs to instance you cannot access.", "danger")
                return redirect(url_for('users.user_list'))
        
        if request.method == "POST":
            try:
                # Get form data
                first_name = request.form.get("first_name", "")
                last_name = request.form.get("last_name", "")
                email = request.form.get("email", "")
                phone = request.form.get("phone", "")
                department = request.form.get("department", "")
                position = request.form.get("position", "")
                
                # Get module permissions
                module_perms = []
                if request.form.get("perm_m1"):
                    module_perms.append("M1")
                if request.form.get("perm_m2"):
                    module_perms.append("M2")
                if request.form.get("perm_m3a"):
                    module_perms.append("M3A")
                if request.form.get("perm_m3b"):
                    module_perms.append("M3B")
                if request.form.get("perm_m3c"):
                    module_perms.append("M3C")
                
                # Update database
                with get_db_connection("core") as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE users 
                        SET first_name=%s, last_name=%s, email=%s, phone=%s, 
                            department=%s, position=%s, module_permissions=%s,
                            last_modified_by=%s, last_modified_at=%s
                        WHERE id = %s
                    """, (first_name, last_name, email, phone, 
                          department, position, json.dumps(module_perms),
                          cu["id"], datetime.utcnow(), uid))
                    
                    # Handle L2 multi-instance access
                    if target.get('permission_level') == 'L2':
                        from app.core.instance_access import sync_l2_instance_access
                        
                        instance_ids = request.form.getlist('instance_access[]')
                        instance_ids = [int(i) for i in instance_ids if i]
                        
                        sync_l2_instance_access(uid, instance_ids, cu["id"])
                    
                    conn.commit()
                    cursor.close()
                
                # Record audit
                record_audit(cu, "update_user", "users", f"Updated user {target['username']}")
                
                flash("User updated successfully.", "success")
                return redirect(url_for("users.user_list", instance_id=target.get('instance_id')))
                
            except Exception as e:
                logger.error(f"ERROR updating user: {e}")
                import traceback
                traceback.print_exc()
                flash(f"Error updating user: {str(e)}", "danger")
        
        # GET: Load data for form
        target["module_permissions_list"] = PermissionManager.parse_module_permissions(
            target.get("module_permissions", "[]")
        )
        
        # Get all instances for L2 selection
        all_instances = []
        user_instance_ids = []
        
        if target.get('permission_level') == 'L2':
            from app.core.instance_access import get_user_instances
            
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, name, display_name FROM instances ORDER BY name")
                all_instances = cursor.fetchall()
                cursor.close()
            
            user_instances = get_user_instances(target)
            user_instance_ids = [inst['id'] for inst in user_instances]
        
        return render_template("users/edit.html",
                             active="users",
                             page="edit",
                             user=target,
                             all_instances=all_instances,
                             user_instance_ids=user_instance_ids)
                             
    except Exception as e:
        logger.error(f"ERROR in edit_user route: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error loading user: {str(e)}", "danger")
        return redirect(url_for("users.user_list"))


@users_bp.route("/elevation")
@login_required
def elevation_management():
    """Elevation management page (L2+ only)."""
    cu = current_user()
    cu_level = get_user_permission_level(cu)
    
    if cu_level not in ['L2', 'L3', 'S1']:
        flash("You need L2 (Systems Administrator) permissions or higher to access elevation management.", "danger")
        return redirect(url_for("users.user_list"))
    
    # Get instance filter
    instance_id = request.args.get('instance_id', type=int)
    
    # Determine which instance to show
    if cu_level == 'L2':
        accessible = get_accessible_instances(cu)
        if not instance_id and len(accessible) > 0:
            instance_id = accessible[0]['id']
    
    # Get all users for the instance (or all if L3/S1)
    if cu_level in ['L3', 'S1']:
        rows = list_users(instance_id=instance_id, include_system=False, include_deleted=False)
    else:
        rows = list_users(instance_id=instance_id, include_system=False, include_deleted=False)
    
    # Filter to show only users this admin can manage
    users = []
    for row in rows:
        row_dict = row_to_dict(row)
        
        row_dict["current_level"] = get_user_permission_level(row_dict) or "None"
        row_dict["level_description"] = PermissionManager.get_permission_description(row_dict["current_level"])
        
        # Determine what levels this admin can elevate this user to
        available_elevations = []
        blocked_elevations = []

        all_levels = [
            ("L1", "Module Administrator"),
            ("L2", "Systems Administrator"), 
            ("L3", "App Operator"),
            ("S1", "System")
        ]

        for level, desc in all_levels:
            if PermissionManager.can_elevate_to(cu_level, level):
                available_elevations.append({
                    "level": level,
                    "description": desc
                })
            else:
                # Show why it's blocked
                if level == cu_level:
                    reason = "Cannot elevate to your own level"
                elif level == "S1":
                    reason = "Only S1 can create S1 users"
                else:
                    reason = "Level above your permissions"
                
                blocked_elevations.append({
                    "level": level,
                    "description": desc,
                    "reason": reason
                })

        row_dict["available_elevations"] = available_elevations
        row_dict["blocked_elevations"] = blocked_elevations
                    
        row_dict["available_elevations"] = available_elevations
        row_dict["can_demote"] = can_modify_user(cu, row_dict)
                    
        users.append(row_dict)
    
    # Get accessible instances for dropdown
    accessible_instances = get_accessible_instances(cu)
    
    return render_template("users/elevation.html",
                         active="users",
                         page="elevation",
                         users=users,
                         current_user_level=cu_level,
                         instances=accessible_instances,
                         current_instance_id=instance_id)


@users_bp.route("/elevate/<int:uid>", methods=["POST"])
@login_required
def elevate_user(uid: int):
    """Elevate a user to admin level."""
    cu = current_user()
    cu_level = get_user_permission_level(cu)
    
    target = get_user_by_id(uid)
    if not target:
        return jsonify({"error": "User not found"}), 404
    
    target = row_to_dict(target)
    
    new_level = request.json.get("level")
    if not new_level:
        return jsonify({"error": "No level specified"}), 400
    
    # Check if current user can perform this elevation
    if not PermissionManager.can_elevate_to(cu_level, new_level):
        return jsonify({"error": f"You cannot elevate users to {new_level}"}), 403
    
    # Remove all module permissions when elevating
    update_user_permissions(
        uid, 
        new_level, 
        [],  # Clear module permissions
        elevated_by=cu["id"],
        reason=request.json.get("reason", "")
    )
    
    # 🆕 AUTO-ASSIGN S1/L3 to Sandbox
    if new_level in ['S1', 'L3']:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            # Get Sandbox instance ID
            cursor.execute("""
                SELECT id FROM instances 
                WHERE is_sandbox = true 
                LIMIT 1
            """)
            sandbox = cursor.fetchone()
            sandbox_id = sandbox['id'] if sandbox else 4  # Fallback to ID 4
            
            # Assign to Sandbox
            cursor.execute("""
                UPDATE users 
                SET instance_id = %s 
                WHERE id = %s
            """, (sandbox_id, uid))
            
            conn.commit()
            cursor.close()
    
    record_audit(
        cu, 
        "elevate_user", 
        "users",
        f"Elevated {target['username']} to {new_level}" + 
        (f" (auto-assigned to Sandbox)" if new_level in ['S1', 'L3'] else ""),
        target_user_id=uid,
        target_username=target["username"]
    )
    
    return jsonify({"success": True, "message": f"User elevated to {new_level}"})


@users_bp.route("/demote/<int:uid>", methods=["POST"])
@login_required
def demote_user(uid: int):
    """Demote a user from admin level."""
    cu = current_user()
    
    target = get_user_by_id(uid)
    if not target:
        return jsonify({"success": False, "error": "User not found"}), 404
    
    target = row_to_dict(target)
    
    if not can_modify_user(cu, target):
        return jsonify({"success": False, "error": "You cannot demote this user"}), 403
    
    try:
        # Clear admin level but preserve module permissions
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users 
                SET permission_level = '',
                    elevated_by = NULL,
                    elevated_at = NULL,
                    last_modified_by = %s,
                    last_modified_at = %s
                WHERE id = %s
            """, (cu["id"], datetime.utcnow(), uid))
            conn.commit()
            cursor.close()
        
        record_audit(
            cu, 
            "demote_user", 
            "users",
            f"Demoted {target['username']} from admin level",
            target_user_id=uid,
            target_username=target["username"]
        )
        
        return jsonify({"success": True, "message": "User demoted to module access only"}), 200
    
    except Exception as e:
        logger.error(f"ERROR demoting user: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@users_bp.route("/request-deletion/<int:uid>", methods=["POST"])
@login_required
def request_user_deletion(uid: int):
    """Request user deletion (requires L1+ approval)."""
    cu = current_user()
    
    if not can_modify_user(cu, None):
        flash("You don't have permission to request user deletions.", "danger")
        return redirect(url_for("users.user_list"))
    
    target = get_user_by_id(uid)
    if not target:
        flash("User not found.", "warning")
        return redirect(url_for("users.user_list"))
    
    target = row_to_dict(target)
    
    _request_user_deletion_db(uid, reason=f"Requested by {cu['username']}")
    
    record_audit(cu, "request_user_deletion", "users", 
                f"Requested deletion of user {target['username']} (ID: {uid})")
    
    flash(f"Deletion request submitted for user '{target['username']}'. Awaiting admin approval.", "info")
    return redirect(url_for("users.user_list", instance_id=target.get('instance_id')))


@users_bp.route("/deletion-requests")
@login_required
def deletion_requests():
    """View pending deletion requests (L1+ only)."""
    cu = current_user()
    if not can_view_users(cu):
        flash("You need administrative permissions to view deletion requests.", "danger")
        return redirect(url_for("home.index"))
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT dr.*, u.username, u.first_name, u.last_name
            FROM deletion_requests dr
            JOIN users u ON dr.user_id = u.id
            WHERE dr.status = 'pending'
            ORDER BY dr.requested_at DESC
        """)
        requests = cursor.fetchall()
        cursor.close()
    
    return render_template("users/deletion_requests.html",
                         active="users",
                         page="deletions",
                         requests=requests)


@users_bp.route("/approve-deletion/<int:request_id>", methods=["POST"])
@login_required
def approve_deletion(request_id: int):
    """Approve a deletion request."""
    cu = current_user()
    if not can_view_users(cu):
        return jsonify({"error": "Insufficient permissions"}), 403
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM deletion_requests WHERE id = %s", (request_id,))
        req = cursor.fetchone()
        cursor.close()
    
    if not req:
        return jsonify({"error": "Request not found"}), 404
    
    if req["status"] != "pending":
        return jsonify({"error": "Request already processed"}), 400
    
    notes = request.json.get("notes", "")
    approve_user_deletion(req["user_id"], cu["id"], notes)
    
    record_audit(
        cu, 
        "approve_deletion", 
        "users",
        f"Approved deletion of user ID {req['user_id']}"
    )
    
    return jsonify({"success": True, "message": "Deletion approved"})


@users_bp.route("/reject-deletion/<int:request_id>", methods=["POST"])
@login_required
def reject_deletion(request_id: int):
    """Reject a deletion request."""
    cu = current_user()
    if not can_view_users(cu):
        return jsonify({"error": "Insufficient permissions"}), 403
    
    reason = request.json.get("reason", "")
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE deletion_requests
            SET status = 'rejected',
                rejection_reason = %s,
                approved_by = %s,
                approved_at = %s
            WHERE id = %s
        """, (reason, cu["id"], datetime.utcnow(), request_id))
        conn.commit()
        cursor.close()
    
    record_audit(
        cu, 
        "reject_deletion", 
        "users",
        f"Rejected deletion request ID {request_id}: {reason}"
    )
    
    return jsonify({"success": True, "message": "Deletion request rejected"})