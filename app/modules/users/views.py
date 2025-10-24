# app/modules/users/views.py
"""
Updated Users module with new permission system
Implements M1-M3C, L1-L3, S1 permission levels
"""

import json
from datetime import datetime
from typing import List  # ← CRITICAL: Add this for List[str] type hints
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from werkzeug.security import generate_password_hash

from app.modules.auth.security import (
    login_required, 
    current_user,
    # NOTE: record_audit removed - using admin module's version
)

from app.modules.users.models import (
    get_user_by_id,
    users_db
)

from app.modules.users.permissions import PermissionManager, PermissionLevel

users_bp = Blueprint("users", __name__, url_prefix="/users", template_folder="templates")
bp = users_bp

# Audit logging wrapper - avoids circular import
def record_audit(user_data, action, module, details, target_user_id=None, target_username=None):
    """Wrapper for admin module's database audit logging"""
    from app.modules.admin.views import record_audit_log
    record_audit_log(user_data, action, module, details, target_user_id, target_username)

# ---------- Database helpers ----------
def get_db():
    """Get users database connection."""
    return users_db()

def list_users(include_system=False, include_deleted=False):
    """List all users with enhanced filtering."""
    con = get_db()
    query = "SELECT * FROM users"
    conditions = []
    
    if not include_system:
        conditions.append("username NOT IN ('system', 'sysadmin', 'AppAdmin')")
    
    if not include_deleted:
        conditions.append("(deleted_at IS NULL OR deleted_at = '')")
    
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    
    query += " ORDER BY username"
    rows = con.execute(query).fetchall()
    con.close()
    return rows

def get_user_permission_level(user_data):
    """Get the effective permission level for a user."""
    if not user_data:
        return None
    
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
    
    # Legacy compatibility - map old flags to new levels
    if user_data.get("is_sysadmin"):
        return "L2"
    elif user_data.get("is_admin"):
        return "L1"
    
    return None

def create_user(data: dict) -> int:
    """Create a new user with new permission system."""
    username = data["username"]
    password = data["password"]
    permission_level = data.get("permission_level", "")
    module_permissions = data.get("module_permissions", [])
    
    # Validate permission level if provided
    if permission_level and not PermissionLevel.from_string(permission_level):
        raise ValueError(f"Invalid permission level: {permission_level}")
    
    con = get_db()
    cur = con.execute("""
        INSERT INTO users(
            username, password_hash, first_name, last_name, 
            email, phone, department, position,
            permission_level, module_permissions,
            created_utc
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        username,
        generate_password_hash(password),
        data.get("first_name", ""),
        data.get("last_name", ""),
        data.get("email", ""),
        data.get("phone", ""),
        data.get("department", ""),
        data.get("position", ""),
        permission_level,
        json.dumps(module_permissions),
        datetime.utcnow().isoformat() + "Z"
    ))
    
    uid = cur.lastrowid
    con.commit()
    con.close()
    return uid

def update_user_permissions(uid: int, permission_level: str, module_permissions: List[str], 
                           elevated_by: int = None, reason: str = None):
    """Update user permissions with history tracking."""
    user = get_user_by_id(uid)
    if not user:
        return False
    
    con = get_db()
    
    # Get old permissions for history
    old_level = user.get("permission_level", "")
    old_modules = user.get("module_permissions", "[]")
    
    # Update user
    con.execute("""
        UPDATE users 
        SET permission_level = ?,
            module_permissions = ?,
            elevated_by = ?,
            elevated_at = ?,
            last_modified_at = ?
        WHERE id = ?
    """, (
        permission_level,
        json.dumps(module_permissions),
        elevated_by,
        datetime.utcnow().isoformat() + "Z" if elevated_by else None,
        datetime.utcnow().isoformat() + "Z",
        uid
    ))
    
    # Record elevation history if this is an elevation
    if elevated_by and (permission_level != old_level or module_permissions != old_modules):
        con.execute("""
            INSERT INTO user_elevation_history(
                user_id, elevated_by, old_level, new_level,
                old_permissions, new_permissions, reason
            )
            VALUES (?,?,?,?,?,?,?)
        """, (
            uid, elevated_by, old_level, permission_level,
            old_modules, json.dumps(module_permissions), reason
        ))
    
    con.commit()
    con.close()
    return True

def request_user_deletion(uid: int, reason: str = None):
    """Request user account deletion (requires admin approval)."""
    con = get_db()
    con.execute("""
        INSERT INTO deletion_requests(user_id, reason, status)
        VALUES (?,?,?)
    """, (uid, reason, "pending"))
    
    # Mark user as deletion requested
    con.execute("""
        UPDATE users 
        SET deletion_requested_at = ?
        WHERE id = ?
    """, (datetime.utcnow().isoformat() + "Z", uid))
    
    con.commit()
    con.close()

def approve_user_deletion(uid: int, approved_by: int, notes: str = None):
    """Approve and execute user deletion."""
    con = get_db()
    
    # Update deletion request
    con.execute("""
        UPDATE deletion_requests
        SET status = 'approved',
            approved_by = ?,
            approved_at = ?
        WHERE user_id = ? AND status = 'pending'
    """, (approved_by, datetime.utcnow().isoformat() + "Z", uid))
    
    # Soft delete the user
    con.execute("""
        UPDATE users 
        SET deleted_at = ?,
            deletion_approved_by = ?,
            deletion_notes = ?
        WHERE id = ?
    """, (
        datetime.utcnow().isoformat() + "Z",
        approved_by,
        notes,
        uid
    ))
    
    con.commit()
    con.close()

# ---------- Permission Checking ----------
def can_view_users(user_data) -> bool:
    """Check if user can view user list."""
    if not user_data:
        return False
    
    level = get_user_permission_level(user_data)
    if level in ["L1", "L2", "L3", "S1"]:
        return True
    
    # Legacy compatibility
    return bool(user_data.get("is_admin") or user_data.get("is_sysadmin"))

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
    
    # General check - can they elevate at all?
    return actor_level in ["L1", "L2", "L3", "S1"]

def record_audit(user_data, action, module, details, target_user_id=None, target_username=None):
    """Wrapper for admin module's audit logging - avoids circular import"""
    from app.modules.admin.views import record_audit_log
    record_audit_log(user_data, action, module, details, target_user_id, target_username)

# ---------- Routes ----------

@users_bp.route("/")
@login_required
def user_list():
    """Display user list with search and filtering."""
    cu = current_user()
    if not can_view_users(cu):
        flash("You don't have access to Users.", "danger")
        return redirect(url_for("home"))
    
    # Get query parameters
    q = (request.args.get("q") or "").strip().lower()
    include_inactive = bool(request.args.get("all"))
    
    rows = list_users(include_system=False, include_deleted=include_inactive)
    
    # Filter and enhance user data
    filtered = []
    for row in rows:
        row_dict = dict(row)
        
        # Add effective permissions
        row_dict["effective_permissions"] = PermissionManager.get_effective_permissions(row_dict)
        row_dict["permission_level_desc"] = PermissionManager.get_permission_description(
            row_dict.get("permission_level", "")
        )
        
        # Search filter
        if q:
            searchable = " ".join([
                row_dict.get("username", ""),
                row_dict.get("first_name", ""),
                row_dict.get("last_name", ""),
                row_dict.get("email", ""),
                row_dict.get("department", ""),
                str(row_dict.get("id", ""))
            ]).lower()
            if q not in searchable:
                continue
        
        filtered.append(row_dict)
    
    return render_template("users/list.html",
                         active="users", 
                         page="list",
                         rows=filtered, 
                         q=q, 
                         show_all=include_inactive,
                         can_create=can_create_users(cu))

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
    con = get_db()
    deletion_request = con.execute("""
        SELECT * FROM deletion_requests 
        WHERE user_id = ? AND status = 'pending'
        ORDER BY requested_at DESC LIMIT 1
    """, (cu["id"],)).fetchone()
    con.close()
    
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
        con = get_db()
        con.execute("""
            UPDATE users 
            SET first_name = ?, last_name = ?, 
                email = ?, phone = ?,
                department = ?, position = ?,
                last_modified_at = ?
            WHERE id = ?
        """, (
            request.form.get("first_name", ""),
            request.form.get("last_name", ""),
            request.form.get("email", ""),
            request.form.get("phone", ""),
            request.form.get("department", ""),
            request.form.get("position", ""),
            datetime.utcnow().isoformat() + "Z",
            cu["id"]
        ))
        con.commit()
        con.close()
        
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
    
    request_user_deletion(cu["id"], reason)
    record_audit(cu, "request_deletion", "users", f"Requested account deletion: {reason}")
    flash("Deletion request submitted. An administrator will review your request.", "info")
    
    return redirect(url_for("users.profile"))

@users_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    """Create new user (L1+ only)."""
    cu = current_user()
    if not can_create_users(cu):
        flash("You need L1 (Module Administrator) permissions or higher to create users.", "danger")
        return redirect(url_for("users.user_list"))
    
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        
        if not username or not password:
            flash("Username and password are required.", "danger")
            return redirect(url_for("users.create"))
        
        # Check if username exists
        con = get_db()
        existing = con.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        con.close()
        
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
        
        data = {
            "username": username,
            "password": password,
            "first_name": request.form.get("first_name", ""),
            "last_name": request.form.get("last_name", ""),
            "email": request.form.get("email", ""),
            "phone": request.form.get("phone", ""),
            "department": request.form.get("department", ""),
            "position": request.form.get("position", ""),
            "permission_level": "",  # Regular users start without admin level
            "module_permissions": module_perms
        }
        
        uid = create_user(data)
        record_audit(cu, "create_user", "users", 
                    f"Created user {username} with permissions: {', '.join(module_perms)}")
        flash(f"User '{username}' created successfully.", "success")
        return redirect(url_for("users.user_list"))
    
    return render_template("users/create.html",
                         active="users",
                         page="create")

@users_bp.route("/<int:uid>/edit", methods=["GET", "POST"])
@login_required
def edit_user(uid: int):
    """Edit user (admin only, cannot edit users at same or higher level)."""
    cu = current_user()
    target = get_user_by_id(uid)
    
    if not target:
        flash("User not found.", "warning")
        return redirect(url_for("users.user_list"))
    
    if not can_modify_user(cu, target):
        flash("You cannot modify users at your level or higher.", "danger")
        return redirect(url_for("users.user_list"))
    
    if request.method == "POST":
        # Update profile fields
        con = get_db()
        con.execute("""
            UPDATE users 
            SET first_name = ?, last_name = ?, 
                email = ?, phone = ?,
                department = ?, position = ?,
                last_modified_by = ?,
                last_modified_at = ?
            WHERE id = ?
        """, (
            request.form.get("first_name", ""),
            request.form.get("last_name", ""),
            request.form.get("email", ""),
            request.form.get("phone", ""),
            request.form.get("department", ""),
            request.form.get("position", ""),
            cu["id"],
            datetime.utcnow().isoformat() + "Z",
            uid
        ))
        
        # Update module permissions
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
        
        con.execute("""
            UPDATE users 
            SET module_permissions = ?
            WHERE id = ?
        """, (json.dumps(module_perms), uid))
        
        con.commit()
        con.close()
        
        record_audit(cu, "update_user", "users", 
                    f"Updated user {target['username']} - permissions: {', '.join(module_perms)}")
        flash("User updated successfully.", "success")
        return redirect(url_for("users.user_list"))
    
    # Parse existing permissions for display
    target_dict = dict(target)
    target_dict["module_permissions_list"] = PermissionManager.parse_module_permissions(
        target_dict.get("module_permissions", "[]")
    )
    
    return render_template("users/edit.html",
                         active="users",
                         page="edit",
                         user=target_dict)

@users_bp.route("/elevation")
@login_required
def elevation_management():
    """Elevation management page (L1+ only)."""
    cu = current_user()
    cu_level = get_user_permission_level(cu)
    
    if not can_elevate_users(cu):
        flash("You need administrative permissions to access elevation management.", "danger")
        return redirect(url_for("users.user_list"))
    
    # Get all users
    rows = list_users(include_system=False, include_deleted=False)
    
    # Filter to show only users this admin can manage
    users = []
    for row in rows:
        row_dict = dict(row)
        row_dict["current_level"] = get_user_permission_level(row_dict) or "None"
        row_dict["level_description"] = PermissionManager.get_permission_description(row_dict["current_level"])
        
        # Determine what levels this admin can elevate this user to
        available_elevations = []
        for level in ["L1", "L2", "L3", "S1"]:
            if PermissionManager.can_elevate_to(cu_level, level):
                available_elevations.append({
                    "level": level,
                    "description": PermissionManager.get_permission_description(level)
                })
        
        row_dict["available_elevations"] = available_elevations
        row_dict["can_demote"] = can_modify_user(cu, row_dict)
        
        users.append(row_dict)
    
    return render_template("users/elevation.html",
                         active="users",
                         page="elevation",
                         users=users,
                         current_user_level=cu_level)

@users_bp.route("/elevate/<int:uid>", methods=["POST"])
@login_required
def elevate_user(uid: int):
    """Elevate a user to admin level."""
    cu = current_user()
    cu_level = get_user_permission_level(cu)
    
    target = get_user_by_id(uid)
    if not target:
        return jsonify({"error": "User not found"}), 404
    
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
    
    record_audit(
        cu, 
        "elevate_user", 
        "users",
        f"Elevated {target['username']} to {new_level}",
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
        return jsonify({"error": "User not found"}), 404
    
    if not can_modify_user(cu, target):
        return jsonify({"error": "You cannot demote this user"}), 403
    
    # Clear admin level but preserve module permissions
    con = get_db()
    con.execute("""
        UPDATE users 
        SET permission_level = '',
            elevated_by = NULL,
            elevated_at = NULL,
            last_modified_by = ?,
            last_modified_at = ?
        WHERE id = ?
    """, (cu["id"], datetime.utcnow().isoformat() + "Z", uid))
    con.commit()
    con.close()
    
    record_audit(
        cu, 
        "demote_user", 
        "users",
        f"Demoted {target['username']} from admin level",
        target_user_id=uid,
        target_username=target["username"]
    )
    
    return jsonify({"success": True, "message": "User demoted to module access only"})

@users_bp.route("/deletion-requests")
@login_required
def deletion_requests():
    """View pending deletion requests (L1+ only)."""
    cu = current_user()
    if not can_view_users(cu):
        flash("You need administrative permissions to view deletion requests.", "danger")
        return redirect(url_for("home"))
    
    con = get_db()
    requests = con.execute("""
        SELECT dr.*, u.username, u.first_name, u.last_name
        FROM deletion_requests dr
        JOIN users u ON dr.user_id = u.id
        WHERE dr.status = 'pending'
        ORDER BY dr.requested_at DESC
    """).fetchall()
    con.close()
    
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
    
    con = get_db()
    req = con.execute("SELECT * FROM deletion_requests WHERE id = ?", (request_id,)).fetchone()
    con.close()
    
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
    
    con = get_db()
    con.execute("""
        UPDATE deletion_requests
        SET status = 'rejected',
            rejection_reason = ?,
            approved_by = ?,
            approved_at = ?
        WHERE id = ?
    """, (reason, cu["id"], datetime.utcnow().isoformat() + "Z", request_id))
    con.commit()
    con.close()
    
    record_audit(
        cu, 
        "reject_deletion", 
        "users",
        f"Rejected deletion request ID {request_id}: {reason}"
    )
    
    return jsonify({"success": True, "message": "Deletion request rejected"})