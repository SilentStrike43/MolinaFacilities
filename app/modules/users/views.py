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
    delete_user,
)
from app.core.database import get_db_connection
from app.core.instance_context import get_current_instance
from app.modules.auth.security import (
    login_required,
    current_user,
)
from app.core.permissions import PermissionManager, PermissionLevel

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
def index():
    """Discord-style user management interface"""
    cu = current_user()
    
    if not can_view_users(cu):
        flash("Permission denied", "danger")
        return redirect(url_for("home.index"))
    
    # Get instance context
    from flask import session
    instance_id = (
        request.args.get('instance_id', type=int) or 
        session.get('active_instance_id') or
        cu.get('instance_id')
    )
    
    # Get users for the instance
    users = list_users(instance_id=instance_id)
    
    # Get user's accessible instances
    from app.core.instance_access import get_user_instances
    user_instances = get_user_instances(cu)
    
    # Permission descriptions
    permission_descriptions = {
        'S1': 'System Administrator',
        'L3': 'App Operator',
        'L2': 'Systems Administrator',
        'L1': 'Module Administrator'
    }
    
    return render_template(
        "users/discord_manager.html",
        users=users,
        user_count=len(users),
        current_user=cu,
        current_instance_id=instance_id,
        user_instances=user_instances,
        permission_descriptions=permission_descriptions,
        can_create=can_create_users(cu)
    )

# ============== API ENDPOINTS FOR AJAX ==============

@users_bp.route("/api/user/<int:user_id>", methods=["GET"])
@login_required
def api_get_user(user_id):
    """Get user data for Discord-style interface"""
    cu = current_user()
    
    if not can_view_users(cu):
        return jsonify({"error": "Permission denied"}), 403
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        # Get user data
        cursor.execute("""
            SELECT * FROM users WHERE id = %s
        """, (user_id,))
        
        user = cursor.fetchone()
        
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        user_dict = dict(user)
        
        # Parse module permissions
        try:
            user_dict['module_permissions'] = json.loads(user_dict.get('module_permissions', '[]') or '[]')
        except:
            user_dict['module_permissions'] = []
        
        # Get accessible instances if L2
        if user_dict.get('permission_level') == 'L2':
            cursor.execute("""
                SELECT instance_id FROM user_instance_access WHERE user_id = %s
            """, (user_id,))
            user_dict['accessible_instances'] = [row['instance_id'] for row in cursor.fetchall()]
        else:
            user_dict['accessible_instances'] = []
        
        # Convert datetime objects to strings
        for key in ['created_at', 'last_login', 'deleted_at', 'last_modified_at']:
            if key in user_dict and user_dict[key]:
                user_dict[key] = str(user_dict[key])
        
        cursor.close()
    
    return jsonify(user_dict)

@users_bp.route("/api/user", methods=["POST"])
@login_required
def api_create_user():
    """Create new user via API"""
    cu = current_user()
    
    if not can_create_users(cu):
        return jsonify({"error": "Permission denied"}), 403
    
    data = request.get_json()
    
    # Use your existing create logic
    from flask import session
    instance_id = (
        data.get('instance_id') or
        session.get('active_instance_id') or
        cu.get('instance_id')
    )
    
    try:
        # Hash password
        import hashlib
        pw_hash = hashlib.sha256(data['password'].encode()).hexdigest()
        
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
                data['username'], pw_hash,
                data.get('first_name', ''),
                data.get('last_name', ''),
                data.get('email', ''),
                data.get('phone', ''),
                data.get('department', ''),
                data.get('position', ''),
                data.get('permission_level', ''),
                json.dumps(data.get('module_permissions', [])),
                instance_id,
                cu['id']
            ))
            
            new_user_id = cursor.fetchone()['id']
            conn.commit()
            cursor.close()
        
        record_audit(cu, "create_user", "users", f"Created user {data['username']}")
        
        return jsonify({"success": True, "user_id": new_user_id})
    
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        return jsonify({"error": str(e)}), 500

@users_bp.route("/api/user/<int:user_id>", methods=["PUT"])
@login_required
def api_update_user(user_id):
    """Update user via API"""
    cu = current_user()
    
    target = get_user_by_id(user_id)
    if not can_modify_user(cu, target):
        return jsonify({"error": "Permission denied"}), 403
    
    data = request.get_json()
    
    try:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            # Build update query
            update_fields = []
            params = []
            
            # Update basic fields
            for field in ['first_name', 'last_name', 'email', 'phone', 'department', 'position']:
                if field in data:
                    update_fields.append(f"{field} = %s")
                    params.append(data[field])
            
            # Update password if provided
            if data.get('password'):
                import hashlib
                pw_hash = hashlib.sha256(data['password'].encode()).hexdigest()
                update_fields.append("password_hash = %s")
                params.append(pw_hash)
            
            # Update permissions
            if 'permission_level' in data:
                update_fields.append("permission_level = %s")
                params.append(data['permission_level'] or None)
            
            if 'module_permissions' in data:
                update_fields.append("module_permissions = %s")
                params.append(json.dumps(data['module_permissions']))
            
            # Add user_id at the end
            params.append(user_id)
            
            # Execute update
            cursor.execute(f"""
                UPDATE users 
                SET {', '.join(update_fields)}
                WHERE id = %s
            """, params)
            
            # Handle L2 instance access
            if data.get('permission_level') == 'L2' and 'accessible_instances' in data:
                # Clear existing
                cursor.execute("DELETE FROM user_instance_access WHERE user_id = %s", (user_id,))
                
                # Add new
                for inst_id in data['accessible_instances']:
                    cursor.execute("""
                        INSERT INTO user_instance_access (user_id, instance_id, granted_by)
                        VALUES (%s, %s, %s)
                    """, (user_id, inst_id, cu['id']))
            
            conn.commit()
            cursor.close()
        
        record_audit(cu, "update_user", "users", f"Updated user ID {user_id}")
        
        return jsonify({"success": True})
    
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        return jsonify({"error": str(e)}), 500

@users_bp.route("/api/user/<int:user_id>", methods=["DELETE"])
@login_required
def api_delete_user(user_id):
    """Delete user via API"""
    cu = current_user()
    
    target = get_user_by_id(user_id)
    if not can_modify_user(cu, target):
        return jsonify({"error": "Permission denied"}), 403
    
    success = delete_user(user_id, cu['id'])
    
    if success:
        record_audit(cu, "delete_user", "users", f"Deleted user ID {user_id}")
    
    return jsonify({"success": success})

@users_bp.route("/profile/<int:uid>")
@login_required
def view_profile(uid: int):
    """View detailed user profile."""
    cu = current_user()
    
    # Get target user
    target = get_user_by_id(uid)
    if not target:
        flash("User not found.", "warning")
        return redirect(url_for("users.index"))
    
    target = row_to_dict(target)
    
    # Check permissions
    if uid != cu['id'] and not can_view_users(cu):
        flash("You don't have permission to view this profile.", "danger")
        return redirect(url_for("users.index"))
    
    # Verify instance access for non-own profiles
    if uid != cu['id']:
        user_level = get_user_permission_level(cu)
        
        if user_level == 'L1':
            # L1 can only view users in their own instance
            if target.get('instance_id') != cu.get('instance_id'):
                flash("Access denied - user belongs to different instance.", "danger")
                return redirect(url_for("users.index"))
        
        elif user_level == 'L2':
            # L2 must have access to the target's instance
            from app.core.instance_access import user_can_access_instance
            if not user_can_access_instance(cu, target.get('instance_id')):
                flash("Access denied - user belongs to instance you cannot access.", "danger")
                return redirect(url_for("users.index"))
    
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
    
    # Determine if this user belongs to sandbox instance
    target_instance_id = target.get('instance_id')
    is_sandbox_mode = (target_instance_id == 4)  # Assuming instance 4 is sandbox

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
        is_own_profile=(uid == cu['id']),
        is_sandbox=is_sandbox_mode
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
    
    # Check if user belongs to sandbox
    is_sandbox_mode = (cu.get('instance_id') == 4)

    return render_template("users/profile.html",
                        active="users",
                        page="profile",
                        user=user_data,
                        deletion_request=deletion_request,
                        is_sandbox=is_sandbox_mode)


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

@users_bp.route("/elevation")
@login_required
def elevation_management():
    """Elevation management page (L2+ only)."""
    from flask import session
    from app.core.database import get_db_connection
    
    cu = current_user()
    cu_level = get_user_permission_level(cu)
    
    if cu_level not in ['L2', 'L3', 'S1']:
        flash("You need L2 (Systems Administrator) permissions or higher to access elevation management.", "danger")
        return redirect(url_for("users.index"))
    
    # Get instance context
    instance_id = (
        request.args.get('instance_id', type=int) or 
        session.get('active_instance_id') or
        cu.get('instance_id')
    )
    
    logger.info(f"🔍 elevation_management: user={cu.get('username')}, level={cu_level}, instance_id={instance_id}")
    
    # Get accessible instances for dropdown
    accessible_instances = get_accessible_instances(cu)
    
    # Get users for the instance
    users = []  # ✅ Initialize empty list
    
    if instance_id:
        # Get users from this specific instance
        rows = list_users(instance_id=instance_id, include_system=False, include_deleted=False)
        
        # Filter out L3/S1 users from instance views
        rows = [row for row in rows if row_to_dict(row).get('permission_level') not in ['L3', 'S1']]
        
        # Process each user
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
            row_dict["can_demote"] = can_modify_user(cu, row_dict)
            
            users.append(row_dict)
    
    logger.info(f"📋 Elevation Management: Found {len(users)} users for instance {instance_id}")
    
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
        return redirect(url_for("users.index"))
    
    target = get_user_by_id(uid)
    if not target:
        flash("User not found.", "warning")
        return redirect(url_for("users.index"))
    
    target = row_to_dict(target)
    
    _request_user_deletion_db(uid, reason=f"Requested by {cu['username']}")
    
    record_audit(cu, "request_user_deletion", "users", 
                f"Requested deletion of user {target['username']} (ID: {uid})")
    
    flash(f"Deletion request submitted for user '{target['username']}'. Awaiting admin approval.", "info")
    return redirect(url_for("users.index", instance_id=target.get('instance_id')))


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

# ========== PERMISSION MANAGEMENT API ==========
# Discord-style permission badge system

@users_bp.route("/api/user/<int:user_id>/permissions", methods=["GET"])
@login_required
def get_user_permissions_api(user_id):
    """API endpoint to get user permissions in badge-friendly format"""
    cu = current_user()
    
    # Permission check - only L1+ can view permissions
    if cu.get('permission_level') not in ['L1', 'L2', 'L3', 'S1']:
        return jsonify({"error": "Insufficient permissions"}), 403
    
    try:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            # Get user data
            cursor.execute("""
                SELECT id, username, permission_level, instance_id, module_permissions
                FROM users 
                WHERE id = %s AND (deleted_at IS NULL OR deleted_at = '')
            """, (user_id,))
            user = cursor.fetchone()
            
            if not user:
                return jsonify({"error": "User not found"}), 404
            
            # Get instances for L2 users
            accessible_instances = []
            if user['permission_level'] == 'L2':
                cursor.execute("""
                    SELECT i.id, i.name, i.display_name, i.is_sandbox
                    FROM user_instance_access uia
                    JOIN instances i ON uia.instance_id = i.id
                    WHERE uia.user_id = %s
                    ORDER BY i.name
                """, (user_id,))
                accessible_instances = [dict(row) for row in cursor.fetchall()]
            
            cursor.close()
        
        # Parse module permissions
        module_perms = user['module_permissions'] or []
        if isinstance(module_perms, str):
            import json
            try:
                module_perms = json.loads(module_perms)
            except:
                module_perms = []
        
        return jsonify({
            "permission_level": user['permission_level'] or '',
            "instance_id": user['instance_id'],
            "accessible_instances": accessible_instances,
            "module_permissions": module_perms
        })
        
    except Exception as e:
        logger.error(f"Error getting user permissions: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@users_bp.route("/api/user/<int:user_id>/permissions", methods=["POST"])
@login_required
def update_user_permissions_api(user_id):
    """API endpoint to update user permissions via toggles"""
    cu = current_user()
    
    # Permission check - only L1+ can modify permissions
    if cu.get('permission_level') not in ['L1', 'L2', 'L3', 'S1']:
        return jsonify({"error": "Insufficient permissions"}), 403
    
    try:
        data = request.json
        
        permission_level = data.get('permission_level', '')
        module_permissions = data.get('module_permissions', [])
        accessible_instances = data.get('accessible_instances', [])
        
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            # Get current user data for audit
            cursor.execute("SELECT username FROM users WHERE id = %s", (user_id,))
            target_user = cursor.fetchone()
            
            if not target_user:
                return jsonify({"error": "User not found"}), 404
            
            # Update permission level and module permissions
            import json
            cursor.execute("""
                UPDATE users 
                SET permission_level = %s,
                    module_permissions = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (
                permission_level if permission_level else None,
                json.dumps(module_permissions),
                user_id
            ))
            
            # Handle L2 instance access
            if permission_level == 'L2':
                # Clear existing instance access
                cursor.execute("DELETE FROM user_instance_access WHERE user_id = %s", (user_id,))
                
                # Add new instance access
                for inst_id in accessible_instances:
                    cursor.execute("""
                        INSERT INTO user_instance_access (user_id, instance_id, granted_by)
                        VALUES (%s, %s, %s)
                    """, (user_id, inst_id, cu['id']))
            else:
                # Not L2 - clear all instance access
                cursor.execute("DELETE FROM user_instance_access WHERE user_id = %s", (user_id,))
            
            conn.commit()
            cursor.close()
        
        # Record audit
        record_audit(cu, "update_user_permissions", "users", 
                    f"Updated permissions for {target_user['username']}: {permission_level}, modules: {module_permissions}")
        
        return jsonify({
            "success": True,
            "message": "Permissions updated successfully"
        })
        
    except Exception as e:
        logger.error(f"Error updating user permissions: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@users_bp.route("/api/instances", methods=["GET"])
@login_required
def get_instances_api():
    """API endpoint to get all available instances"""
    cu = current_user()
    
    # Only L1+ can see instances
    if cu.get('permission_level') not in ['L1', 'L2', 'L3', 'S1']:
        return jsonify({"error": "Insufficient permissions"}), 403
    
    try:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, display_name, is_sandbox, is_active
                FROM instances
                WHERE is_active = TRUE
                ORDER BY is_sandbox DESC, name
            """)
            instances = [dict(row) for row in cursor.fetchall()]
            cursor.close()
        
        return jsonify(instances)
        
    except Exception as e:
        logger.error(f"Error getting instances: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@users_bp.route("/user/<int:user_id>/edit-permissions")
@login_required
def edit_permissions(user_id):
    """Edit user permissions with Discord-style interface"""
    cu = current_user()
    
    # Only L1+ can edit permissions
    if cu.get('permission_level') not in ['L1', 'L2', 'L3', 'S1']:
        flash("You don't have permission to edit user permissions.", "danger")
        return redirect(url_for('users.list_users'))
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, first_name, last_name, email, 
                   permission_level, instance_id, module_permissions
            FROM users 
            WHERE id = %s AND deleted_at IS NULL  -- ✅ FIXED: Removed empty string check
        """, (user_id,))
        user = cursor.fetchone()
        cursor.close()
    
    if not user:
        flash("User not found.", "warning")
        return redirect(url_for('users.list_users'))
    
    return render_template(
        "users/edit_permissions.html",
        active="users",
        user=user
    )