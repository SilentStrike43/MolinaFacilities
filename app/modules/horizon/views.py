# app/modules/horizon/views.py
"""
Horizon - Global Administration Module
L3/S1 ONLY - Cross-instance management and oversight

Architecture:
    Horizon (Global Layer)
      ├── Sandbox Instance (instance_id=4)
      ├── Instance Selection (switch between instances)
      ├── Global Analytics (across all instances)
      ├── Instance Management (create/edit/delete instances)
      └── Global User Management (all users, all instances)
"""

import secrets
from datetime import datetime, timedelta
import json
import csv
import io
from functools import wraps
import bcrypt
import logging

logger = logging.getLogger(__name__)

from flask import (
    session,
    request, 
    jsonify, 
    Response, 
    send_file, 
    flash, 
    redirect, 
    url_for, 
    render_template
)

# Use relative imports
from . import bp
from app.core.database import get_db_connection
from app.modules.auth.security import login_required, current_user
from .audit import record_horizon_audit

# Global Admin specific imports
from .models import (
    get_instance_by_id,
    get_instance_by_subdomain,
    get_all_instances,
    get_instance_stats,
    get_system_health_metrics
)

from .instance_manager import InstanceManager
from .analytics import GlobalAnalytics


# ---------- Permission Checking ----------
def require_horizon(f):
    """Decorator to require L3 (App Operator) or S1 (System) permission."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        cu = current_user()
        
        if not cu:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("auth.login"))
        
        # Get permission level
        permission_level = cu.get('permission_level', '')
        
        # Check for system flag
        try:
            caps = json.loads(cu.get("caps", "{}") or "{}")
            if caps.get("is_system"):
                return f(*args, **kwargs)
        except:
            pass
        
        # Check if user is L3 (App Operator) or S1 (System)
        if permission_level not in ['L3', 'S1']:
            flash("Access denied. App Operator privileges required.", "danger")
            return redirect(url_for("home.index"))
        
        return f(*args, **kwargs)
    
    return decorated_function


def require_super_admin(f):
    """Decorator to require S1 (System) permission only."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        cu = current_user()
        
        if not cu:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("auth.login"))
        
        # Check if user is S1 (System)
        if cu.get('permission_level') != 'S1':
            flash("Access denied. System (S1) privileges required.", "danger")
            return redirect(url_for("horizon.dashboard"))
        
        return f(*args, **kwargs)
    
    return decorated_function


def record_global_audit(user_data, action, details):
    """Record audit log for global admin actions."""
    from app.modules.admin.views import record_audit_log
    record_audit_log(user_data, action, "horizon", details)


# ---------- Dashboard ----------
@bp.route("/")
@bp.route("/dashboard")
@login_required
@require_horizon
def dashboard():
    """
    Horizon Global Dashboard - Overview of ALL instances
    NO instance filtering - shows everything
    """
    cu = current_user()
    
    # Get all instances (NO filtering)
    instances = get_all_instances()
    
    # Get global statistics (across ALL instances)
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        # Total users across ALL instances
        cursor.execute("SELECT COUNT(*) as count FROM users WHERE deleted_at IS NULL")
        result = cursor.fetchone()
        total_users = result['count'] if result else 0
        
        # Active instances
        cursor.execute("SELECT COUNT(*) as count FROM instances WHERE is_active = true")
        result = cursor.fetchone()
        active_instances = result['count'] if result else 0
        
        # Total instances
        cursor.execute("SELECT COUNT(*) as count FROM instances")
        result = cursor.fetchone()
        total_instances = result['count'] if result else 0
        
        # Recent activity (last 24 hours) - ALL instances
        cursor.execute("""
            SELECT COUNT(*) as count FROM audit_logs 
            WHERE ts_utc >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
        """)
        result = cursor.fetchone()
        recent_activity = result['count'] if result else 0
        
        # Users by permission level (ALL instances)
        cursor.execute("""
            SELECT 
                permission_level,
                COUNT(*) as count
            FROM users
            WHERE deleted_at IS NULL
            GROUP BY permission_level
            ORDER BY permission_level
        """)
        users_by_level = cursor.fetchall()
        
        # Recent critical events (ALL instances)
        cursor.execute("""
            SELECT 
                username, action, module, details, ts_utc, permission_level
            FROM audit_logs
            WHERE action IN ('create_instance', 'delete_instance', 'deactivate_instance', 
                           'elevate_user', 'demote_user', 'create_user', 'delete_user')
            ORDER BY ts_utc DESC
            LIMIT 10
        """)
        recent_critical = cursor.fetchall()
        
        cursor.close()
    
    # System health metrics
    health = get_system_health_metrics()
    
    # Instance statistics (for each instance)
    instance_stats = []
    for inst in instances:
        stats = get_instance_stats(inst['id'])
        instance_stats.append({
            'instance': inst,
            'stats': stats
        })
    
    record_global_audit(cu, "view_global_dashboard", "Viewed global admin dashboard")
    
    return render_template(
        "horizon/dashboard.html",
        active="dashboard",
        page="dashboard",
        instances=instances,  # ✅ ADD THIS LINE
        total_users=total_users,
        active_instances=active_instances,
        total_instances=total_instances,
        recent_activity=recent_activity,
        users_by_level=users_by_level,
        recent_critical=recent_critical,
        health=health,
        instance_stats=instance_stats
    )


@bp.route("/back-to-app")
@login_required
def back_to_app():
    """
    Smart redirect from Horizon back to app.
    L3/S1 → Sandbox instance
    L2 → Their assigned home instance
    """
    cu = current_user()
    perm_level = cu.get('permission_level', '') if cu else ''

    if perm_level not in ['L2', 'L3', 'S1']:
        flash("Access denied.", "danger")
        return redirect(url_for("home.index"))

    # L3/S1 go to sandbox
    if perm_level in ['L3', 'S1']:
        try:
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id FROM instances
                    WHERE is_sandbox = true
                    LIMIT 1
                """)
                sandbox = cursor.fetchone()
                cursor.close()

                if sandbox:
                    return redirect(url_for('home.index', instance_id=sandbox['id']))
        except Exception as e:
            logger.error(f"Error finding sandbox: {e}")

    # L2 and fallback: go to assigned home instance
    instance_id = cu.get('instance_id')
    if instance_id:
        return redirect(url_for('home.index', instance_id=instance_id))

    flash('No instance assigned.', 'warning')
    return redirect(url_for('horizon.instance_management'))


# ---------- Instance Management ----------
@bp.route("/instances")
@login_required
def instance_management():
    """View instances. L3/S1 see all; L2 sees their assigned instances only."""
    cu = current_user()
    permission_level = cu.get('permission_level', '') if cu else ''

    if permission_level not in ['L2', 'L3', 'S1']:
        flash("Access denied.", "danger")
        return redirect(url_for("home.index"))

    is_l3_plus = permission_level in ['L3', 'S1']

    if is_l3_plus:
        instances = get_all_instances()
    else:
        # L2: filter to assigned instances only
        from app.core.instance_access import get_user_instances
        assigned = get_user_instances(cu)
        assigned_ids = {i['id'] for i in assigned}
        instances = [i for i in get_all_instances() if i['id'] in assigned_ids]

    # Enhance with statistics
    enhanced_instances = []
    for inst in instances:
        stats = get_instance_stats(inst['id'])
        enhanced_instances.append({
            'instance': inst,
            'stats': stats
        })

    record_global_audit(cu, "view_instances", f"Viewed {len(instances)} instances")

    return render_template(
        "horizon/instances.html",
        active="instances",
        page="instances",
        instances=enhanced_instances,
        is_l3_plus=is_l3_plus
    )

@bp.route("/switch-instance/<int:instance_id>")
@login_required
def switch_instance(instance_id):
    """
    Switch to a specific instance context.
    L2+ can enter instances; L2 is restricted to their assigned instances.
    """
    cu = current_user()
    permission_level = cu.get('permission_level', '') if cu else ''

    if permission_level not in ['L2', 'L3', 'S1']:
        flash("Access denied.", "danger")
        return redirect(url_for("home.index"))

    # L2: validate they have access to this specific instance
    if permission_level == 'L2':
        from app.core.instance_access import user_can_access_instance
        if not user_can_access_instance(cu, instance_id):
            flash("You do not have access to that instance.", "danger")
            return redirect(url_for('horizon.instance_management'))

    # Verify instance exists
    instance = get_instance_by_id(instance_id)
    if not instance:
        flash("Instance not found", "error")
        return redirect(url_for('horizon.instance_management'))

    if not instance['is_active']:
        flash(f"Cannot switch to inactive instance: {instance['display_name']}", "warning")
        return redirect(url_for('horizon.instance_management'))
    
    # Store in session
    session['active_instance_id'] = instance_id
    session['active_instance_name'] = instance.get('display_name') or instance['name']
    
    # Record audit — write to both tables so global_audits (audit_logs) captures it
    record_horizon_audit(
        cu,
        "switch_instance",
        "instances",
        f"Switched to instance: {instance['display_name']} (ID: {instance_id})",
        target_instance_id=instance_id,
        severity="info"
    )
    record_global_audit(cu, "switch_instance", f"Entered instance: {instance['display_name']} (ID: {instance_id})")

    flash(f"Switched to instance: {instance['display_name']}", "success")
    logger.info(f"User {cu['username']} switched to instance {instance_id}")
    
    # Redirect to home page of that instance WITH instance_id in URL
    return redirect(url_for('home.index', instance_id=instance_id))


@bp.route("/exit-instance")
@login_required
def exit_instance():
    """
    Exit instance context and return to Horizon.
    L3/S1 return to Horizon dashboard; L2 returns to Instances page.
    """
    cu = current_user()
    permission_level = cu.get('permission_level', '') if cu else ''

    if permission_level not in ['L2', 'L3', 'S1']:
        flash("Access denied.", "danger")
        return redirect(url_for("home.index"))

    # Get current instance before clearing
    current_instance = session.get('active_instance_name', 'Unknown')

    # Clear session
    session.pop('active_instance_id', None)
    session.pop('active_instance_name', None)

    # Record audit — write to both tables so global_audits (audit_logs) captures it
    record_horizon_audit(
        cu,
        "exit_instance",
        "instances",
        f"Exited instance: {current_instance}",
        severity="info"
    )
    record_global_audit(cu, "exit_instance", f"Exited instance: {current_instance}")

    flash("Exited instance mode.", "info")

    if permission_level in ['L3', 'S1']:
        return redirect(url_for('horizon.index'))
    else:
        return redirect(url_for('horizon.instance_management'))


@bp.route("/api/current-instance")
@login_required
@require_horizon
def api_current_instance():
    """
    API: Get currently active instance for L3/S1 user
    """
    instance_id = session.get('active_instance_id')
    instance_name = session.get('active_instance_name')
    
    return jsonify({
        'active': instance_id is not None,
        'instance_id': instance_id,
        'instance_name': instance_name
    })

@bp.route("/instances/<int:instance_id>")
@login_required
@require_horizon
def instance_detail(instance_id: int):
    """View detailed instance information."""
    cu = current_user()
    
    instance = get_instance_by_id(instance_id)
    if not instance:
        flash("Instance not found.", "warning")
        return redirect(url_for("horizon.instance_management"))
    
    stats = get_instance_stats(instance_id)
    
    # Get instance users (filter by THIS instance)
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                id, username, first_name, last_name, email,
                permission_level, module_permissions,
                is_active, created_at
            FROM users
            WHERE instance_id = %s
            ORDER BY created_at DESC
        """, (instance_id,))
        users = cursor.fetchall()
        
        # Get recent activity for THIS instance
        cursor.execute("""
            SELECT 
                username, action, module, details, ts_utc
            FROM audit_logs
            WHERE user_id IN (SELECT id FROM users WHERE instance_id = %s)
            ORDER BY ts_utc DESC
            LIMIT 20
        """, (instance_id,))
        recent_activity = cursor.fetchall()
        
        cursor.close()
    
    record_global_audit(cu, "view_instance_detail", f"Viewed instance {instance['name']} (ID: {instance_id})")
    
    return render_template(
        "horizon/instance_detail.html",
        active="global",
        page="instance_detail",
        instance=instance,
        stats=stats,
        users=users,
        recent_activity=recent_activity
    )


@bp.route("/create-instance", methods=["GET", "POST"])
@login_required
@require_horizon
def create_instance():
    """Create new company instance."""
    cu = current_user()
    
    if request.method == "POST":
        # Basic info
        name = request.form.get("name", "").strip()
        display_name = request.form.get("display_name", "").strip() or name
        description = request.form.get("description", "").strip()
        
        # Contact info
        contact_name = request.form.get("contact_name", "").strip()
        contact_email = request.form.get("contact_email", "").strip()
        contact_phone = request.form.get("contact_phone", "").strip()
        
        # Resources
        max_users = int(request.form.get("max_users", 100))
        
        # Module Access - Get enabled modules
        enabled_modules = []
        if request.form.get("module_send"):
            enabled_modules.append("send")
        if request.form.get("module_inventory"):
            enabled_modules.append("inventory")
        if request.form.get("module_fulfillment"):
            enabled_modules.append("fulfillment")
        
        # Ensure at least one module is enabled
        if not enabled_modules:
            flash("At least one module must be enabled.", "danger")
            return redirect(url_for("horizon.create_instance"))
        
        # Status
        is_active = bool(request.form.get("is_active"))
        notes = request.form.get("notes", "").strip()
        
        # L2 Administrator setup
        l2_setup_option = request.form.get("l2_setup_option", "skip")
        
        if not name:
            flash("Company name is required.", "danger")
            return redirect(url_for("horizon.create_instance"))
        
        try:
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                
                # Create instance
                cursor.execute("""
                    INSERT INTO instances (
                        name, display_name, description,
                        contact_name, contact_email, contact_phone,
                        max_users, is_active, notes, enabled_modules
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    name, display_name, description,
                    contact_name, contact_email, contact_phone,
                    max_users, is_active, notes, enabled_modules
                ))
                
                instance_id = cursor.fetchone()['id']
                
                # Handle L2 Administrator Setup
                from app.core.instance_access import grant_instance_access
                
                if l2_setup_option == "create_new":
                    # Create new L2 user
                    l2_username = request.form.get("l2_username", "").strip().lower()
                    l2_password = request.form.get("l2_password", "").strip()
                    l2_first_name = request.form.get("l2_first_name", "").strip()
                    l2_last_name = request.form.get("l2_last_name", "").strip()
                    l2_email = request.form.get("l2_email", "").strip()
                    l2_phone = request.form.get("l2_phone", "").strip()
                    
                    if not l2_username or not l2_password:
                        conn.rollback()
                        flash("L2 username and password are required.", "danger")
                        return redirect(url_for("horizon.create_instance"))
                    
                    # Check if username exists
                    cursor.execute("SELECT id FROM users WHERE username = %s", (l2_username,))
                    if cursor.fetchone():
                        conn.rollback()
                        flash(f"Username '{l2_username}' already exists.", "danger")
                        return redirect(url_for("horizon.create_instance"))
                    
                    # Hash password
                    import hashlib
                    pw_hash = hashlib.sha256(l2_password.encode()).hexdigest()
                    
                    # Create L2 user
                    cursor.execute("""
                        INSERT INTO users (
                            username, password_hash, permission_level,
                            first_name, last_name, email, phone,
                            instance_id, force_password_reset, is_active,
                            created_by, created_at
                        )
                        VALUES (%s, %s, 'L2', %s, %s, %s, %s, %s, TRUE, TRUE, %s, CURRENT_TIMESTAMP)
                        RETURNING id
                    """, (
                        l2_username, pw_hash, l2_first_name, l2_last_name,
                        l2_email, l2_phone, instance_id, cu["id"]
                    ))
                    
                    l2_user_id = cursor.fetchone()['id']
                    
                    # Grant access to this instance
                    cursor.execute("""
                        INSERT INTO user_instance_access (user_id, instance_id, granted_by)
                        VALUES (%s, %s, %s)
                    """, (l2_user_id, instance_id, cu["id"]))
                    
                    l2_info = f"Created new L2 user: {l2_username}"
                    
                elif l2_setup_option == "assign_existing":
                    # Assign existing L2 users
                    l2_user_ids = request.form.getlist('assign_l2_users[]')
                    
                    if not l2_user_ids:
                        conn.rollback()
                        flash("Please select at least one L2 user to assign.", "danger")
                        return redirect(url_for("horizon.create_instance"))
                    
                    for l2_id in l2_user_ids:
                        cursor.execute("""
                            INSERT INTO user_instance_access (user_id, instance_id, granted_by)
                            VALUES (%s, %s, %s)
                        """, (int(l2_id), instance_id, cu["id"]))
                    
                    l2_info = f"Assigned {len(l2_user_ids)} existing L2 user(s)"
                    
                else:
                    l2_info = "No L2 assigned (will be assigned later)"
                
                conn.commit()
                cursor.close()
            
            # Record Horizon audit
            modules_str = ", ".join(enabled_modules)
            record_horizon_audit(
                cu, 
                "create_instance", 
                "instances",
                f"Created company instance: {name} (ID: {instance_id}) with modules: {modules_str}. {l2_info}",
                target_instance_id=instance_id,
                severity="info"
            )
            
            flash(f"✅ Company instance '{name}' created successfully!", "success")
            return redirect(url_for("horizon.instance_detail", instance_id=instance_id))
            
        except Exception as e:
            logger.error(f"Error creating instance: {e}")
            import traceback
            traceback.print_exc()
            
            # Audit the failed attempt
            record_horizon_audit(
                cu,
                "create_instance_failed",
                "instances",
                f"Failed to create instance '{name}': {str(e)}",
                severity="warning"
            )
            
            flash(f"❌ Error creating instance: {str(e)}", "danger")
            return redirect(url_for("horizon.create_instance"))
    
    if request.method == "GET":
        # Get existing L2 users for assignment option
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, username, first_name, last_name, email
                FROM users
                WHERE permission_level = 'L2'
                AND deleted_at IS NULL
                ORDER BY username
            """)
            existing_l2_users = cursor.fetchall()
            cursor.close()
        
        return render_template(
            "horizon/create_instance.html",
            active="instances",
            page="create_instance",
            cu=cu,
            existing_l2_users=existing_l2_users
        )


@bp.route("/instances/<int:instance_id>/edit", methods=["GET", "POST"])
@login_required
@require_horizon
def instance_edit(instance_id: int):
    """Edit instance details."""
    cu = current_user()
    
    instance = get_instance_by_id(instance_id)
    if not instance:
        flash("Instance not found.", "warning")
        return redirect(url_for("horizon.instance_management"))
    
    if request.method == "POST":
        try:
            # Collect enabled modules
            enabled_modules = []
            if request.form.get("module_send"):
                enabled_modules.append("send")
            if request.form.get("module_inventory"):
                enabled_modules.append("inventory")
            if request.form.get("module_fulfillment"):
                enabled_modules.append("fulfillment")
            
            # Ensure at least one module is enabled
            if not enabled_modules:
                flash("At least one module must be enabled.", "danger")
                return redirect(url_for("horizon.instance_edit", instance_id=instance_id))
            
            # Update instance
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE instances SET
                        name = %s,
                        display_name = %s,
                        description = %s,
                        subdomain = %s,
                        contact_name = %s,
                        contact_email = %s,
                        contact_phone = %s,
                        max_users = %s,
                        storage_limit_gb = %s,
                        subscription_tier = %s,
                        enabled_modules = %s,
                        is_active = %s,
                        notes = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (
                    request.form.get("name", "").strip(),
                    request.form.get("display_name", "").strip() or None,
                    request.form.get("description", "").strip() or None,
                    request.form.get("subdomain", "").strip() or None,
                    request.form.get("contact_name", "").strip() or None,
                    request.form.get("contact_email", "").strip() or None,
                    request.form.get("contact_phone", "").strip() or None,
                    int(request.form.get("max_users", 100)),
                    int(request.form.get("storage_limit_gb", 10)),
                    request.form.get("subscription_tier", "standard"),
                    enabled_modules,
                    bool(request.form.get("is_active")),
                    request.form.get("notes", "").strip() or None,
                    instance_id
                ))
                conn.commit()
                cursor.close()
            
            # Record audit
            modules_str = ", ".join(enabled_modules)
            record_horizon_audit(
                cu, 
                "update_instance", 
                "instances",
                f"Updated instance: {request.form.get('name')} (ID: {instance_id}). Modules: {modules_str}",
                target_instance_id=instance_id,
                severity="info"
            )
            
            flash(f"✅ Instance '{request.form.get('name')}' updated successfully!", "success")
            return redirect(url_for("horizon.instance_detail", instance_id=instance_id))
            
        except Exception as e:
            logger.error(f"Error updating instance: {e}")
            import traceback
            traceback.print_exc()
            flash(f"❌ Error updating instance: {str(e)}", "danger")
            return redirect(url_for("horizon.instance_edit", instance_id=instance_id))
    
    # GET request - show form
    return render_template(
        "horizon/instance_edit.html",
        active="global",
        page="instance_edit",
        instance=instance
    )


@bp.route("/instances/<int:instance_id>/delete", methods=["POST"])
@login_required
@require_horizon
def delete_instance(instance_id: int):
    """Permanently delete an instance and all its data."""
    cu = current_user()
    
    try:
        # Get instance
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, is_sandbox 
                FROM instances 
                WHERE id = %s
            """, (instance_id,))
            instance = cursor.fetchone()
            cursor.close()
        
        if not instance:
            return jsonify({
                "success": False, 
                "error": "Instance not found"
            }), 404
        
        # Prevent deleting sandbox
        if instance['is_sandbox']:
            return jsonify({
                "success": False, 
                "error": "Cannot delete sandbox instance"
            }), 403
        
        # Get deletion reason
        reason = request.json.get("reason", "No reason provided")
        
        # DELETE EVERYTHING IN ORDER
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            # 1. Delete horizon audit logs that reference this instance
            cursor.execute("""
                DELETE FROM horizon_audit_logs 
                WHERE target_instance_id = %s
            """, (instance_id,))
            deleted_horizon_audits = cursor.rowcount
            
            # 2. Delete user instance access records
            cursor.execute("""
                DELETE FROM user_instance_access 
                WHERE instance_id = %s
            """, (instance_id,))
            deleted_access = cursor.rowcount
            
            # 3. Get user IDs for this instance (for deleting their audit logs)
            cursor.execute("""
                SELECT id FROM users WHERE instance_id = %s
            """, (instance_id,))
            user_ids = [row['id'] for row in cursor.fetchall()]
            
            # 4. Delete audit logs for users in this instance
            if user_ids:
                cursor.execute("""
                    DELETE FROM audit_logs 
                    WHERE user_id = ANY(%s)
                """, (user_ids,))
                deleted_audits = cursor.rowcount
            else:
                deleted_audits = 0
            
            # 5. Delete all users in this instance
            cursor.execute("""
                DELETE FROM users 
                WHERE instance_id = %s
            """, (instance_id,))
            deleted_users = cursor.rowcount
            
            # 6. Finally, delete the instance itself
            cursor.execute("""
                DELETE FROM instances 
                WHERE id = %s
            """, (instance_id,))
            
            conn.commit()
            cursor.close()
        
        # Record in Horizon audit (before deletion)
        record_horizon_audit(
            cu,
            "delete_instance",
            "instances",
            f"DELETED instance: {instance['name']} (ID: {instance_id}). "
            f"Removed: {deleted_users} users, {deleted_audits} audit logs, "
            f"{deleted_horizon_audits} horizon audits, {deleted_access} access records. "
            f"Reason: {reason}",
            severity="critical"
        )
        
        logger.warning(f"Instance {instance_id} ({instance['name']}) DELETED by {cu['username']}")
        
        return jsonify({
            "success": True,
            "message": f"Instance '{instance['name']}' and all associated data deleted. "
                      f"({deleted_users} users, {deleted_audits + deleted_horizon_audits} audit logs)"
        })
        
    except Exception as e:
        logger.error(f"Error deleting instance {instance_id}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route("/instances/<int:instance_id>/activate", methods=["POST"])
@login_required
@require_horizon
def activate_instance(instance_id: int):
    """Activate an instance."""
    cu = current_user()
    
    instance = get_instance_by_id(instance_id)
    if not instance:
        return jsonify({"success": False, "error": "Instance not found"}), 404
    
    InstanceManager.activate_instance(instance_id)
    
    record_global_audit(cu, "activate_instance", 
                       f"Activated instance: {instance['name']} (ID: {instance_id})")
    
    return jsonify({"success": True, "message": f"Instance '{instance['name']}' activated"})


@bp.route("/instances/<int:instance_id>/export")
@login_required
@require_horizon
def export_instance(instance_id: int):
    """Export instance data as JSON."""
    cu = current_user()
    
    instance = get_instance_by_id(instance_id)
    if not instance:
        flash("Instance not found.", "warning")
        return redirect(url_for("horizon.instance_management"))
    
    # Export data
    export_data = InstanceManager.export_instance_data(instance_id)
    
    record_global_audit(cu, "export_instance_data", 
                       f"Exported data for instance: {instance['name']} (ID: {instance_id})")
    
    # Return as JSON download
    json_data = json.dumps(export_data, indent=2, default=str)
    
    return Response(
        json_data,
        mimetype='application/json',
        headers={
            'Content-Disposition': f'attachment; filename=instance_{instance_id}_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        }
    )

# ---------- Support & Documentation ----------

@bp.route("/support")
@login_required
@require_horizon
def instance_support():
    """Support Tools — cross-instance visibility and management for L3/S1 operators."""
    cu = current_user()

    instances = get_all_instances()

    with get_db_connection("core") as conn:
        cursor = conn.cursor()

        # Pending inquiry counts per instance
        cursor.execute("""
            SELECT instance_id, COUNT(*) AS cnt
            FROM user_inquiries WHERE status = 'pending'
            GROUP BY instance_id
        """)
        inquiry_counts = {r['instance_id']: r['cnt'] for r in cursor.fetchall()}

        # Last user activity per instance
        cursor.execute("""
            SELECT instance_id, MAX(last_seen) AS last_activity
            FROM users WHERE instance_id IS NOT NULL AND deleted_at IS NULL
            GROUP BY instance_id
        """)
        last_activity = {r['instance_id']: r['last_activity'] for r in cursor.fetchall()}

        # All pending inquiries with instance name
        cursor.execute("""
            SELECT ui.id, ui.username, ui.first_name, ui.last_name,
                   ui.request_type, ui.request_details, ui.submitted_at,
                   ui.instance_id, i.name AS instance_name
            FROM user_inquiries ui
            LEFT JOIN instances i ON i.id = ui.instance_id
            WHERE ui.status = 'pending'
            ORDER BY ui.submitted_at DESC
            LIMIT 200
        """)
        pending_inquiries = [dict(r) for r in cursor.fetchall()]

        # Instance entry log (last 60)
        cursor.execute("""
            SELECT al.username, al.permission_level, al.details,
                   al.ts_utc, al.ip_address, al.instance_id,
                   i.name AS instance_name
            FROM audit_logs al
            LEFT JOIN instances i ON i.id = al.instance_id
            WHERE al.module = 'instance_access'
            ORDER BY al.ts_utc DESC
            LIMIT 60
        """)
        entry_log = [dict(r) for r in cursor.fetchall()]

        # All announcements
        cursor.execute("""
            SELECT id, instance_id, title, message, active,
                   created_by_username, created_at, expires_at
            FROM instance_announcements
            ORDER BY created_at DESC
        """)
        announcements = [dict(r) for r in cursor.fetchall()]

        # Instance names for announcement labels
        cursor.execute("SELECT id, name FROM instances ORDER BY name")
        all_instances_list = [dict(r) for r in cursor.fetchall()]

        cursor.close()

    # Build health cards
    instance_health = []
    for inst in instances:
        stats = get_instance_stats(inst['id'])
        instance_health.append({
            'id': inst['id'],
            'name': inst['name'],
            'display_name': inst.get('display_name') or inst['name'],
            'is_active': inst.get('is_active', True),
            'user_count': stats.get('user_count', 0),
            'max_users': inst.get('max_users', 0),
            'pending_inquiries': inquiry_counts.get(inst['id'], 0),
            'last_activity': last_activity.get(inst['id']),
        })

    record_global_audit(cu, "view_support", "Viewed Support Tools")

    return render_template(
        "horizon/instance_support.html",
        active="support",
        page="support",
        instance_health=instance_health,
        pending_inquiries=pending_inquiries,
        entry_log=entry_log,
        announcements=announcements,
        all_instances_list=all_instances_list,
    )


@bp.route("/support/user-lookup")
@login_required
@require_horizon
def support_user_lookup():
    """AJAX: search users across all instances."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"users": []})

    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.id, u.username, u.first_name, u.last_name, u.email,
                   u.permission_level, u.module_permissions, u.last_seen,
                   u.force_logout, u.instance_id, i.name AS instance_name
            FROM users u
            LEFT JOIN instances i ON i.id = u.instance_id
            WHERE u.deleted_at IS NULL
              AND (u.username ILIKE %s OR u.email ILIKE %s
                   OR u.first_name ILIKE %s OR u.last_name ILIKE %s)
            ORDER BY u.username
            LIMIT 25
        """, (f"%{q}%",) * 4)
        users = [dict(r) for r in cursor.fetchall()]
        cursor.close()

    for u in users:
        u['last_seen'] = u['last_seen'].strftime('%Y-%m-%d %H:%M') if u.get('last_seen') else None

    return jsonify({"users": users})


@bp.route("/support/audit-search")
@login_required
@require_horizon
def support_audit_search():
    """AJAX: cross-instance audit log search."""
    q = (request.args.get("q") or "").strip()
    module_filter = (request.args.get("module") or "").strip()
    if not q:
        return jsonify({"logs": []})

    params = [f"%{q}%", f"%{q}%"]
    where = "WHERE (al.username ILIKE %s OR al.ip_address ILIKE %s)"
    if module_filter:
        where += " AND al.module = %s"
        params.append(module_filter)

    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT al.username, al.permission_level, al.action, al.module,
                   al.details, al.ts_utc, al.ip_address, al.instance_id,
                   i.name AS instance_name
            FROM audit_logs al
            LEFT JOIN instances i ON i.id = al.instance_id
            {where}
            ORDER BY al.ts_utc DESC
            LIMIT 50
        """, params)
        logs = [dict(r) for r in cursor.fetchall()]
        cursor.close()

    for row in logs:
        row['ts_utc'] = row['ts_utc'].strftime('%Y-%m-%d %H:%M') if row.get('ts_utc') else None

    return jsonify({"logs": logs})


@bp.route("/support/force-logout/<int:user_id>", methods=["POST"])
@login_required
@require_horizon
def support_force_logout(user_id):
    """Flag a user for forced session invalidation on their next request."""
    cu = current_user()
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username FROM users WHERE id = %s", (user_id,))
        target = cursor.fetchone()
        if not target:
            return jsonify({"error": "User not found"}), 404
        cursor.execute("UPDATE users SET force_logout = TRUE WHERE id = %s", (user_id,))
        cursor.close()

    from app.core.audit import log_action
    log_action(cu, "force_logout", "support",
               f"Force-invalidated session for {target['username']} (id={user_id})",
               target_user_id=user_id, target_username=target['username'])

    return jsonify({"success": True})


@bp.route("/support/announcement", methods=["POST"])
@login_required
@require_horizon
def support_create_announcement():
    """Create a new announcement."""
    cu = current_user()
    data = request.get_json() or {}
    title = (data.get("title") or "").strip()
    message = (data.get("message") or "").strip()
    instance_id = data.get("instance_id") or None
    expires_raw = (data.get("expires_at") or "").strip()

    if not title or not message:
        return jsonify({"error": "Title and message are required"}), 400

    expires_at = None
    if expires_raw:
        try:
            expires_at = datetime.strptime(expires_raw, "%Y-%m-%dT%H:%M")
        except ValueError:
            pass

    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO instance_announcements
                (instance_id, title, message, active, created_by_username, expires_at)
            VALUES (%s, %s, %s, TRUE, %s, %s)
            RETURNING id
        """, (instance_id, title, message, cu['username'], expires_at))
        ann_id = cursor.fetchone()['id']
        cursor.close()

    record_global_audit(cu, "create_announcement",
                        f"Created announcement '{title}' (instance={instance_id or 'ALL'})")

    return jsonify({"success": True, "id": ann_id})


@bp.route("/support/announcement/<int:ann_id>/toggle", methods=["POST"])
@login_required
@require_horizon
def support_toggle_announcement(ann_id):
    """Toggle an announcement active/inactive."""
    cu = current_user()
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE instance_announcements SET active = NOT active
            WHERE id = %s RETURNING active, title
        """, (ann_id,))
        row = cursor.fetchone()
        cursor.close()

    if not row:
        return jsonify({"error": "Not found"}), 404

    record_global_audit(cu, "toggle_announcement",
                        f"{'Activated' if row['active'] else 'Deactivated'} announcement '{row['title']}'")

    return jsonify({"success": True, "active": row['active']})


@bp.route("/support/announcement/<int:ann_id>/delete", methods=["POST"])
@login_required
@require_horizon
def support_delete_announcement(ann_id):
    """Delete an announcement."""
    cu = current_user()
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM instance_announcements WHERE id = %s RETURNING title", (ann_id,))
        row = cursor.fetchone()
        cursor.close()

    if row:
        record_global_audit(cu, "delete_announcement", f"Deleted announcement '{row['title']}'")

    return jsonify({"success": True})

# ---------- Global Insights ----------
@bp.route("/insights")
@login_required
@require_horizon
def global_insights():
    """Cross-instance analytics and insights - NO instance filtering."""
    cu = current_user()
    
    # Get date range
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    
    if not date_from:
        date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        # User Growth (ALL instances)
        cursor.execute("""
            SELECT 
                DATE(created_at) as date,
                COUNT(*) as new_users
            FROM users
            WHERE created_at >= %s AND created_at <= %s
            AND deleted_at IS NULL
            GROUP BY DATE(created_at)
            ORDER BY date
        """, (date_from, date_to))
        user_growth = cursor.fetchall()
        
        # Activity by Module (ALL instances)
        cursor.execute("""
            SELECT 
                module,
                COUNT(*) as count
            FROM audit_logs
            WHERE ts_utc >= %s AND ts_utc <= %s
            GROUP BY module
            ORDER BY count DESC
        """, (date_from, date_to))
        activity_by_module = cursor.fetchall()
        
        # Instance Comparison (ALL instances)
        cursor.execute("""
            SELECT 
                i.id,
                i.name,
                COUNT(DISTINCT u.id) as user_count,
                COUNT(DISTINCT al.id) as activity_count
            FROM instances i
            LEFT JOIN users u ON i.id = u.instance_id AND u.deleted_at IS NULL
            LEFT JOIN audit_logs al ON u.id = al.user_id 
                AND al.ts_utc >= %s AND al.ts_utc <= %s
            GROUP BY i.id, i.name
            ORDER BY user_count DESC
        """, (date_from, date_to))
        instance_comparison = cursor.fetchall()
        
        # Peak Usage Times (ALL instances)
        cursor.execute("""
            SELECT 
                EXTRACT(HOUR FROM ts_utc) as hour,
                COUNT(*) as activity
            FROM audit_logs
            WHERE ts_utc >= %s AND ts_utc <= %s
            GROUP BY EXTRACT(HOUR FROM ts_utc)
            ORDER BY hour
        """, (date_from, date_to))
        peak_usage_times = cursor.fetchall()
        
        # Module Adoption by Instance (ALL instances)
        cursor.execute("""
            SELECT 
                i.name as instance_name,
                COALESCE(array_length(i.enabled_modules, 1), 0) as module_count,
                i.enabled_modules
            FROM instances i
            WHERE i.is_active = TRUE
            ORDER BY module_count DESC
        """)
        module_adoption = cursor.fetchall()

        # Top Active Users (ALL instances)
        cursor.execute("""
            SELECT 
                u.username,
                u.first_name,
                u.last_name,
                i.name as instance_name,
                COUNT(al.id) as action_count
            FROM users u
            LEFT JOIN instances i ON u.instance_id = i.id
            LEFT JOIN audit_logs al ON u.id = al.user_id 
                AND al.ts_utc >= %s AND al.ts_utc <= %s
            WHERE u.deleted_at IS NULL
            GROUP BY u.id, u.username, u.first_name, u.last_name, i.name
            ORDER BY action_count DESC
            LIMIT 10
        """, (date_from, date_to))
        top_users = cursor.fetchall()
        
        cursor.close()
    
    insights = {
        'user_growth': user_growth,
        'activity_by_module': activity_by_module,
        'instance_comparison': instance_comparison,
        'peak_usage_times': peak_usage_times,
        'module_adoption': module_adoption,
        'top_users': top_users
    }
    
    record_global_audit(cu, "view_global_insights", f"Viewed global insights: {date_from} to {date_to}")
    
    return render_template(
        "horizon/global_insights.html",
        active="global",
        page="insights",
        date_from=date_from,
        date_to=date_to,
        insights=insights
    )


# ---------- Global User Management ----------
@bp.route("/global-users")
@login_required
@require_horizon
def global_users():
    """View and manage ALL users across ALL instances, grouped by instance."""
    cu = current_user()

    search           = request.args.get('q', '').strip()
    instance_filter  = request.args.get('instance', type=int)
    permission_filter = request.args.get('permission', '')
    status_filter    = request.args.get('status', '')

    instances = get_all_instances()
    instances_by_id = {inst['id']: inst for inst in instances}

    enhanced_users = []
    sorted_groups  = []
    stats = {'s1_count': 0, 'l3_count': 0, 'l2_count': 0,
             'l1_count': 0, 'module_count': 0, 'total_count': 0}

    try:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()

            # Explicit column list — omits last_login which may not exist
            query = """
                SELECT
                    u.id, u.username, u.first_name, u.last_name, u.email,
                    u.permission_level, u.module_permissions, u.instance_id,
                    u.created_at,
                    i.name          AS instance_name,
                    i.display_name  AS instance_display_name,
                    i.is_sandbox
                FROM users u
                LEFT JOIN instances i ON u.instance_id = i.id
                WHERE u.deleted_at IS NULL
            """
            params = []

            if search:
                query += """ AND (
                    u.username   ILIKE %s OR
                    u.first_name ILIKE %s OR
                    u.last_name  ILIKE %s OR
                    u.email      ILIKE %s
                )"""
                sp = f'%{search}%'
                params.extend([sp, sp, sp, sp])

            if instance_filter:
                query += " AND u.instance_id = %s"
                params.append(instance_filter)

            if permission_filter:
                if permission_filter == 'module':
                    query += " AND (u.permission_level IS NULL OR u.permission_level = '')"
                else:
                    query += " AND u.permission_level = %s"
                    params.append(permission_filter)

            # is_active filter — safe: will silently skip if column absent
            if status_filter in ('active', 'inactive'):
                try:
                    clause = " AND u.is_active = TRUE" if status_filter == 'active' else " AND u.is_active = FALSE"
                    query += clause
                except Exception:
                    pass

            query += " ORDER BY i.name NULLS LAST, u.username"

            cursor.execute(query, params)
            users_raw = cursor.fetchall()

            from app.core.permissions import PermissionManager

            for user in users_raw:
                user_dict = dict(user)

                perm_level = user_dict.get('permission_level') or ''
                user_dict['permission_level_desc'] = PermissionManager.get_permission_description(perm_level)

                mp = user_dict.get('module_permissions') or []
                if isinstance(mp, str):
                    try:
                        mp = json.loads(mp)
                    except Exception:
                        mp = []
                user_dict['module_permissions_list'] = mp

                # Accessible instances for L2 — wrap in try/except in case table missing
                user_dict['accessible_instances'] = []
                if perm_level == 'L2':
                    try:
                        cursor.execute("""
                            SELECT i.id, i.name, i.display_name, i.is_sandbox
                            FROM user_instance_access uia
                            JOIN instances i ON uia.instance_id = i.id
                            WHERE uia.user_id = %s
                            ORDER BY i.name
                        """, (user_dict['id'],))
                        user_dict['accessible_instances'] = [dict(r) for r in cursor.fetchall()]
                    except Exception as e:
                        logger.warning(f"user_instance_access query failed for user {user_dict['id']}: {e}")

                enhanced_users.append(user_dict)

            # Group users by instance
            instance_groups: dict = {}
            for user in enhanced_users:
                iid = user.get('instance_id') or 0
                if iid not in instance_groups:
                    inst_info = instances_by_id.get(iid) or {
                        'id': iid, 'name': 'no-instance',
                        'display_name': 'No Instance Assigned',
                        'is_sandbox': False, 'is_active': True
                    }
                    instance_groups[iid] = {'instance': inst_info, 'users': []}
                instance_groups[iid]['users'].append(user)

            # Sort: sandbox first, then alphabetically
            sorted_groups = sorted(
                instance_groups.values(),
                key=lambda g: (
                    not bool(g['instance'].get('is_sandbox')),
                    (g['instance'].get('display_name') or g['instance'].get('name', '')).lower()
                )
            )

            # Stats — avoid is_active which may be absent
            cursor.execute("""
                SELECT
                    COUNT(CASE WHEN permission_level = 'S1' THEN 1 END)                     AS s1_count,
                    COUNT(CASE WHEN permission_level = 'L3' THEN 1 END)                     AS l3_count,
                    COUNT(CASE WHEN permission_level = 'L2' THEN 1 END)                     AS l2_count,
                    COUNT(CASE WHEN permission_level = 'L1' THEN 1 END)                     AS l1_count,
                    COUNT(CASE WHEN permission_level = '' OR permission_level IS NULL THEN 1 END) AS module_count,
                    COUNT(*)                                                                  AS total_count
                FROM users
                WHERE deleted_at IS NULL
            """)
            stats = dict(cursor.fetchone())
            cursor.close()

    except Exception as e:
        logger.error(f"global_users error: {e}", exc_info=True)
        flash(f"Error loading users: {str(e)}", "danger")

    record_horizon_audit(
        cu, "view_global_users", "users",
        f"Viewed global user list ({len(enhanced_users)} users)",
        severity="info"
    )

    return render_template(
        "horizon/global_users.html",
        active="users",
        page="global_users",
        cu=cu,
        instances=instances,
        instance_groups=sorted_groups,
        users=enhanced_users,
        stats=stats,
        search=search,
        instance_filter=instance_filter,
        permission_filter=permission_filter,
        status_filter=status_filter
    )


@bp.route("/global-users/create", methods=["GET", "POST"])
@login_required
@require_horizon
def create_global_user():
    """Create a new user and assign to an instance."""
    cu = current_user()
    
    if request.method == "POST":
        try:
            username = request.form.get("username", "").strip().lower()
            password = request.form.get("password", "").strip()
            instance_id = request.form.get("instance_id", type=int)
            permission_level = request.form.get("permission_level", "")
            
            if not username or not password:
                flash("Username and password are required.", "danger")
                return redirect(url_for("horizon.create_global_user"))
            
            # 🆕 AUTO-ASSIGN S1/L3 to Sandbox (override form selection)
            if permission_level in ['S1', 'L3']:
                with get_db_connection("core") as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT id FROM instances 
                        WHERE is_sandbox = true 
                        LIMIT 1
                    """)
                    sandbox = cursor.fetchone()
                    instance_id = sandbox['id'] if sandbox else 4
                    cursor.close()
                
                logger.info(f"🏖️ Auto-assigning {permission_level} user '{username}' to Sandbox (ID: {instance_id})")
            
            elif not instance_id:
                flash("Please select an instance.", "danger")
                return redirect(url_for("horizon.create_global_user"))
            
            # Check if username exists
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
                if cursor.fetchone():
                    flash(f"Username '{username}' already exists.", "danger")
                    cursor.close()
                    return redirect(url_for("horizon.create_global_user"))
                
                # Hash password
                import hashlib
                pw_hash = hashlib.sha256(password.encode()).hexdigest()
                
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
                
                # Create user
                cursor.execute("""
                    INSERT INTO users (
                        username, password_hash, first_name, last_name,
                        email, phone, instance_id, permission_level,
                        module_permissions, is_active, created_by, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, CURRENT_TIMESTAMP)
                    RETURNING id
                """, (
                    username, pw_hash,
                    request.form.get("first_name", ""),
                    request.form.get("last_name", ""),
                    request.form.get("email", ""),
                    request.form.get("phone", ""),
                    instance_id,
                    permission_level,
                    json.dumps(module_perms),
                    cu["id"]
                ))
                user_id = cursor.fetchone()['id']
                conn.commit()
                cursor.close()
            
            assignment_note = ""
            if permission_level in ['S1', 'L3']:
                assignment_note = " (auto-assigned to Sandbox)"
            
            record_horizon_audit(
                cu, "create_user", "users",
                f"Created user {username} (ID: {user_id}) with level {permission_level} in instance {instance_id}{assignment_note}",
                target_user_id=user_id,
                severity="info"
            )
            
            flash(f"✅ User '{username}' created successfully!{assignment_note}", "success")
            return redirect(url_for("horizon.global_users"))
            
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            flash(f"❌ Error: {str(e)}", "danger")
            return redirect(url_for("horizon.create_global_user"))
    
    # GET - show form
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, display_name, is_sandbox FROM instances WHERE is_active = TRUE ORDER BY is_sandbox DESC, name")
        instances = cursor.fetchall()
        cursor.close()

    return render_template(
        "horizon/create_global_user.html",
        active="users",
        cu=cu,
        instances=instances
    )


@bp.route("/global-users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@require_horizon
def edit_global_user(user_id: int):
    """Edit a user from global panel."""
    cu = current_user()
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.*, i.name as instance_name
            FROM users u
            LEFT JOIN instances i ON u.instance_id = i.id
            WHERE u.id = %s
        """, (user_id,))
        user = cursor.fetchone()
        cursor.close()
    
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("horizon.global_users"))
    
    if request.method == "POST":
        try:
            # Parse module permissions
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
            
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users SET
                        first_name = %s,
                        last_name = %s,
                        email = %s,
                        phone = %s,
                        permission_level = %s,
                        module_permissions = %s,
                        is_active = %s,
                        last_modified_by = %s,
                        last_modified_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (
                    request.form.get("first_name", ""),
                    request.form.get("last_name", ""),
                    request.form.get("email", ""),
                    request.form.get("phone", ""),
                    request.form.get("permission_level", ""),
                    json.dumps(module_perms),
                    bool(request.form.get("is_active")),
                    cu["id"],
                    user_id
                ))
                conn.commit()
                cursor.close()
            
            record_horizon_audit(
                cu, "update_user", "users",
                f"Updated user {user['username']} (ID: {user_id})",
                target_user_id=user_id,
                severity="info"
            )
            
            flash("✅ User updated successfully!", "success")
            return redirect(url_for("horizon.global_users"))
            
        except Exception as e:
            logger.error(f"Error updating user: {e}")
            flash(f"❌ Error: {str(e)}", "danger")
    
    # GET - show form
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, display_name FROM instances ORDER BY name")
        instances = cursor.fetchall()
        cursor.close()
    
    return render_template(
        "horizon/edit_global_users.html",
        active="users",
        user=user,
        instances=instances
    )

# ========== USER EXPORT ENDPOINTS ==========

@bp.route("/export/users/csv")
@login_required
@require_horizon
def export_users_csv():
    """Export all users as CSV."""
    cu = current_user()
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                u.username, u.first_name, u.last_name, u.email, u.phone,
                u.permission_level, u.module_permissions, u.department, u.position,
                u.is_active, u.created_at, u.last_login,
                i.name as instance_name
            FROM users u
            LEFT JOIN instances i ON u.instance_id = i.id
            WHERE u.deleted_at IS NULL
            ORDER BY u.username
        """)
        users = cursor.fetchall()
        cursor.close()
    
    import csv
    import io
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        'Username', 'First Name', 'Last Name', 'Email', 'Phone',
        'Permission Level', 'Modules', 'Department', 'Position',
        'Status', 'Instance', 'Created', 'Last Login'
    ])
    
    # Data
    for user in users:
        writer.writerow([
            user['username'],
            user['first_name'] or '',
            user['last_name'] or '',
            user['email'] or '',
            user['phone'] or '',
            user['permission_level'] or 'Module User',
            user['module_permissions'] or '',
            user['department'] or '',
            user['position'] or '',
            'Active' if user['is_active'] else 'Inactive',
            user['instance_name'] or '',
            user['created_at'].strftime('%Y-%m-%d') if user['created_at'] else '',
            user['last_login'].strftime('%Y-%m-%d') if user['last_login'] else 'Never'
        ])
    
    record_horizon_audit(cu, "export_users_csv", "users", 
                        f"Exported {len(users)} users as CSV",
                        severity="info")
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment;filename=users_{datetime.now().strftime('%Y%m%d')}.csv"
        }
    )


@bp.route("/export/users/json")
@login_required
@require_horizon
def export_users_json():
    """Export all users as JSON."""
    cu = current_user()
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                u.id, u.username, u.first_name, u.last_name, u.email, u.phone,
                u.permission_level, u.module_permissions, u.department, u.position,
                u.is_active, u.created_at, u.last_login,
                i.name as instance_name
            FROM users u
            LEFT JOIN instances i ON u.instance_id = i.id
            WHERE u.deleted_at IS NULL
            ORDER BY u.username
        """)
        users = cursor.fetchall()
        cursor.close()
    
    # Convert to JSON-serializable format
    users_list = []
    for user in users:
        users_list.append({
            'id': user['id'],
            'username': user['username'],
            'first_name': user['first_name'],
            'last_name': user['last_name'],
            'email': user['email'],
            'phone': user['phone'],
            'permission_level': user['permission_level'],
            'module_permissions': user['module_permissions'],
            'department': user['department'],
            'position': user['position'],
            'is_active': user['is_active'],
            'instance': user['instance_name'],
            'created_at': user['created_at'].isoformat() if user['created_at'] else None,
            'last_login': user['last_login'].isoformat() if user['last_login'] else None
        })
    
    record_horizon_audit(cu, "export_users_json", "users",
                        f"Exported {len(users)} users as JSON",
                        severity="info")
    
    return jsonify({
        'exported_at': datetime.now().isoformat(),
        'total_users': len(users_list),
        'users': users_list
    })

@bp.route("/global-users/<int:user_id>/assign", methods=["POST"])
@login_required
@require_horizon
def assign_user_instance(user_id: int):
    """Assign/reassign user to a different instance."""
    cu = current_user()
    
    try:
        new_instance_id = request.json.get("instance_id", type=int)
        
        if not new_instance_id:
            return jsonify({"success": False, "error": "No instance specified"}), 400
        
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            # Get user info
            cursor.execute("SELECT username, instance_id FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            
            if not user:
                return jsonify({"success": False, "error": "User not found"}), 404
            
            old_instance_id = user['instance_id']
            
            # Update instance
            cursor.execute("""
                UPDATE users 
                SET instance_id = %s, last_modified_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (new_instance_id, user_id))
            
            conn.commit()
            cursor.close()
        
        record_horizon_audit(
            cu, "reassign_user_instance", "users",
            f"Reassigned user {user['username']} from instance {old_instance_id} to {new_instance_id}",
            target_user_id=user_id,
            severity="info"
        )
        
        return jsonify({"success": True, "message": "User reassigned successfully"})
        
    except Exception as e:
        logger.error(f"Error reassigning user: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/global-users/<int:user_id>/delete", methods=["POST"])
@login_required
@require_horizon
def delete_global_user(user_id: int):
    """Delete a user from global panel."""
    cu = current_user()
    
    try:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            # Get user info
            cursor.execute("""
                SELECT username, permission_level 
                FROM users 
                WHERE id = %s
            """, (user_id,))
            user = cursor.fetchone()
            
            if not user:
                return jsonify({"success": False, "error": "User not found"}), 404
            
            # Prevent deleting S1 users
            if user['permission_level'] == 'S1':
                return jsonify({"success": False, "error": "Cannot delete System Admin"}), 403
            
            # Delete user's audit logs
            cursor.execute("DELETE FROM audit_logs WHERE user_id = %s", (user_id,))
            
            # Delete user
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
            
            conn.commit()
            cursor.close()
        
        record_horizon_audit(
            cu, "delete_user", "users",
            f"Deleted user {user['username']} (ID: {user_id})",
            severity="warning"
        )
        
        return jsonify({"success": True, "message": f"User '{user['username']}' deleted"})
        
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/global-users/export")
@login_required
@require_horizon
def export_global_users():
    """Export ALL users as CSV or JSON."""
    cu = current_user()
    
    # Get same filters as global_users route
    search = request.args.get('search', '')
    instance_filter = request.args.get('instance_id', type=int)
    permission_filter = request.args.get('permission_level', '')
    status_filter = request.args.get('status', '')
    export_format = request.args.get('export', 'csv')
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        query = """
            SELECT 
                u.id, u.username, u.first_name, u.last_name, u.email, u.phone,
                u.permission_level, u.is_active, u.created_at, u.last_login,
                i.name as instance_name
            FROM users u
            LEFT JOIN instances i ON u.instance_id = i.id
            WHERE u.deleted_at IS NULL
        """
        params = []
        
        # Apply same filters
        if search:
            query += """ AND (
                u.username ILIKE %s OR u.first_name ILIKE %s OR 
                u.last_name ILIKE %s OR u.email ILIKE %s
            )"""
            search_term = f"%{search}%"
            params.extend([search_term] * 4)
        
        if instance_filter:
            query += " AND u.instance_id = %s"
            params.append(instance_filter)
        
        if permission_filter:
            query += " AND u.permission_level = %s"
            params.append(permission_filter)
        
        if status_filter == 'active':
            query += " AND u.is_active = TRUE"
        elif status_filter == 'inactive':
            query += " AND u.is_active = FALSE"
        
        query += " ORDER BY i.name, u.username"
        
        cursor.execute(query, params)
        users = cursor.fetchall()
        cursor.close()
    
    record_global_audit(cu, "export_global_users", 
                       f"Exported {len(users)} users as {export_format}")
    
    if export_format == 'json':
        users_data = [{
            'id': u['id'],
            'username': u['username'],
            'first_name': u['first_name'],
            'last_name': u['last_name'],
            'email': u['email'],
            'phone': u['phone'],
            'permission_level': u['permission_level'] or 'Module User',
            'is_active': u['is_active'],
            'instance': u['instance_name'],
            'created_at': str(u['created_at']),
            'last_login': str(u['last_login']) if u['last_login'] else None
        } for u in users]
        
        return Response(
            json.dumps(users_data, indent=2),
            mimetype='application/json',
            headers={'Content-Disposition': f'attachment; filename=all_users_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'}
        )
    else:
        # CSV export
        output = io.StringIO()
        writer = csv.writer(output)
        
        writer.writerow(['Username', 'First Name', 'Last Name', 'Email', 'Phone', 
                        'Permission Level', 'Status', 'Instance', 'Created', 'Last Login'])
        
        for u in users:
            writer.writerow([
                u['username'], u['first_name'], u['last_name'], u['email'] or '', u['phone'] or '',
                u['permission_level'] or 'Module User',
                'Active' if u['is_active'] else 'Inactive',
                u['instance_name'],
                str(u['created_at']) if u['created_at'] else '',
                str(u['last_login']) if u['last_login'] else ''
            ])
        
        output.seek(0)
        mem = io.BytesIO(output.getvalue().encode("utf-8"))
        mem.seek(0)
        
        return send_file(
            mem,
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"all_users_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )


# ---------- Global Audits ----------
@bp.route("/audits")
@login_required
@require_horizon
def global_audits():
    """View Horizon platform audit logs - ALL instances."""
    cu = current_user()
    
    # Get filter parameters
    filters = {
        'username': request.args.get('username', ''),
        'action': request.args.get('action', ''),
        'module': request.args.get('module', ''),
        'instance_id': request.args.get('instance_id', ''),
        'permission_level': request.args.get('permission_level', ''),
        'date_from': request.args.get('date_from', ''),
        'date_to': request.args.get('date_to', '')
    }
    
    # Remove empty filters
    filters = {k: v for k, v in filters.items() if v}
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        # Build query (NO automatic instance filtering)
        query = """
            SELECT
                al.id,
                al.action,
                al.username,
                al.module,
                al.details,
                al.ts_utc,
                al.permission_level,
                al.ip_address,
                al.user_agent,
                COALESCE(al.instance_id, u.instance_id) AS instance_id,
                i.name AS instance_name,
                al.target_user_id,
                al.target_username
            FROM audit_logs al
            LEFT JOIN users u ON al.user_id = u.id
            LEFT JOIN instances i ON COALESCE(al.instance_id, u.instance_id) = i.id
            WHERE (
                -- All Horizon-level actions (L2/L3/S1 entering, editing, creating instances)
                al.module = 'horizon'

                -- Instance access events (entering/exiting instances)
                OR al.module = 'instance_access'

                -- All actions taken by L3/S1 platform operators (always globally visible)
                OR al.permission_level IN ('L3', 'S1')

                -- Sign-in and sign-out events for all users (session tracking)
                OR al.action IN ('sign_in', 'sign_out')
            )
        """
        params = []

        # Apply filters
        if filters.get('instance_id'):
            query += " AND COALESCE(al.instance_id, u.instance_id) = %s"
            params.append(int(filters['instance_id']))
        
        if filters.get('username'):
            query += " AND al.username ILIKE %s"
            params.append(f"%{filters['username']}%")
        
        if filters.get('action'):
            query += " AND al.action = %s"
            params.append(filters['action'])
        
        if filters.get('module'):
            query += " AND al.module = %s"
            params.append(filters['module'])
        
        if filters.get('date_from'):
            query += " AND CAST(al.ts_utc AS DATE) >= %s"
            params.append(filters['date_from'])
        
        if filters.get('date_to'):
            query += " AND CAST(al.ts_utc AS DATE) <= %s"
            params.append(filters['date_to'])
        
        if filters.get('permission_level'):
            query += " AND al.permission_level = %s"
            params.append(filters['permission_level'])
        
        query += " ORDER BY al.ts_utc DESC LIMIT 500"
        
        cursor.execute(query, params)
        logs = cursor.fetchall()
        
        # Get unique instances for filter
        cursor.execute("""
            SELECT DISTINCT i.id, i.name
            FROM instances i
            INNER JOIN users u ON u.instance_id = i.id
            ORDER BY i.name
        """)
        instances = cursor.fetchall()
        
        # Get unique actions
        cursor.execute("""
            SELECT DISTINCT action 
            FROM audit_logs 
            WHERE action IS NOT NULL
            ORDER BY action
        """)
        actions = [row['action'] for row in cursor.fetchall()]
        
        # Get unique modules
        cursor.execute("""
            SELECT DISTINCT module 
            FROM audit_logs 
            WHERE module IS NOT NULL
            ORDER BY module
        """)
        modules = [row['module'] for row in cursor.fetchall()]
        
        cursor.close()
    
    record_global_audit(cu, "view_global_audits", f"Viewed global audit logs ({len(logs)} entries)")
    
    return render_template(
        "horizon/global_audits.html",
        active="audits",
        cu=cu,
        logs=logs,
        instances=instances,
        actions=actions,
        modules=modules,
        filters=filters
    )


@bp.route("/audits/export")
@login_required
@require_horizon
def export_audits():
    """Export audit logs as CSV or JSON."""
    cu = current_user()
    
    # Get filters
    filters = {
        "instance_id": request.args.get("instance_id", ""),
        "username": request.args.get("username", ""),
        "action": request.args.get("action", ""),
        "module": request.args.get("module", ""),
        "date_from": request.args.get("date_from", ""),
        "date_to": request.args.get("date_to", ""),
        "permission_level": request.args.get("permission_level", "")
    }
    filters = {k: v for k, v in filters.items() if v}
    
    export_format = request.args.get("export", "csv")
    
    # Query logs (same as global_audits view)
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        query = """
            SELECT 
                al.*,
                u.instance_id,
                i.name as instance_name
            FROM audit_logs al
            LEFT JOIN users u ON al.user_id = u.id
            LEFT JOIN instances i ON u.instance_id = i.id
            WHERE 1=1
        """
        params = []
        
        # Apply filters
        if filters.get("instance_id"):
            query += " AND u.instance_id = %s"
            params.append(int(filters["instance_id"]))
        
        if filters.get("username"):
            query += " AND al.username ILIKE %s"
            params.append(f"%{filters['username']}%")
        
        if filters.get("action"):
            query += " AND al.action ILIKE %s"
            params.append(f"%{filters['action']}%")
        
        if filters.get("module"):
            query += " AND al.module = %s"
            params.append(filters["module"])
        
        if filters.get("date_from"):
            query += " AND CAST(al.ts_utc AS DATE) >= %s"
            params.append(filters["date_from"])
        
        if filters.get("date_to"):
            query += " AND CAST(al.ts_utc AS DATE) <= %s"
            params.append(filters["date_to"])
        
        if filters.get("permission_level"):
            query += " AND al.permission_level = %s"
            params.append(filters["permission_level"])
        
        query += " ORDER BY al.ts_utc DESC LIMIT 10000"
        
        cursor.execute(query, params)
        logs = cursor.fetchall()
        cursor.close()
    
    # Export based on format
    if export_format == "json":
        logs_data = []
        for log in logs:
            log_dict = dict(log)
            if log_dict.get('ts_utc'):
                log_dict['ts_utc'] = log_dict['ts_utc'].isoformat()
            logs_data.append(log_dict)
        
        record_global_audit(cu, "export_global_audits", 
                          f"Exported {len(logs)} audit logs as JSON")
        
        return Response(
            json.dumps(logs_data, indent=2, default=str),
            mimetype='application/json',
            headers={
                'Content-Disposition': f'attachment; filename=audit_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
            }
        )
    else:
        # CSV export
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            'Timestamp', 'User', 'Permission Level', 'Action', 'Module',
            'Details', 'Target User', 'Instance', 'IP Address', 'User Agent'
        ])
        
        # Data rows
        for log in logs:
            writer.writerow([
                log['ts_utc'],
                log['username'],
                log['permission_level'] if log['permission_level'] else 'Module User',
                log['action'],
                log['module'],
                log['details'] if log['details'] else '',
                log['target_username'] if log.get('target_username') else '',
                log.get('instance_name', ''),
                log['ip_address'] if log['ip_address'] else '',
                log['user_agent'][:100] if log['user_agent'] else ''
            ])
        
        record_global_audit(cu, "export_global_audits", 
                          f"Exported {len(logs)} audit logs as CSV")
        
        output.seek(0)
        mem = io.BytesIO(output.getvalue().encode("utf-8"))
        mem.seek(0)
        
        filename = f"audit_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return send_file(
            mem,
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename
        )


# ---------- System Health ----------
@bp.route("/system-health")
@login_required
@require_horizon
def system_health():
    """View system health and performance metrics - ALL instances."""
    cu = current_user()

    health = get_system_health_metrics()

    # Per-database sizes and table counts
    db_info = {}
    for db_name in ('core', 'send', 'inventory', 'fulfillment'):
        try:
            with get_db_connection(db_name) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT
                        current_database() AS db_name,
                        pg_database_size(current_database()) / (1024.0 * 1024.0) AS size_mb,
                        (SELECT COUNT(*) FROM pg_stat_user_tables) AS table_count,
                        version() AS pg_version
                """)
                row = dict(cursor.fetchone())
                cursor.execute("""
                    SELECT SUM(n_live_tup) AS total_rows
                    FROM pg_stat_user_tables
                """)
                row['total_rows'] = (cursor.fetchone()['total_rows'] or 0)
                cursor.close()
            db_info[db_name] = {
                'actual_name': row['db_name'],
                'size_mb': round(row['size_mb'], 2),
                'table_count': row['table_count'],
                'total_rows': row['total_rows'],
                'pg_version': row['pg_version'].split(' ')[1] if row['pg_version'] else 'N/A',
                'status': 'healthy' if row['size_mb'] < 5000 else 'warning',
                'reachable': True,
            }
        except Exception as e:
            db_info[db_name] = {
                'actual_name': db_name,
                'size_mb': 0,
                'table_count': 0,
                'total_rows': 0,
                'pg_version': 'N/A',
                'status': 'error',
                'reachable': False,
                'error': str(e),
            }

    # Core table stats for the detailed breakdown
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                schemaname || '.' || relname AS table_name,
                n_live_tup AS row_count
            FROM pg_stat_user_tables
            ORDER BY n_live_tup DESC
            LIMIT 20
        """)
        table_stats = cursor.fetchall()
        cursor.close()

    # ── AWS Elastic Beanstalk info ─────────────────────────────────────────────
    # Set EB_ENV_NAME in EB environment variables to pin a specific environment.
    # If not set, auto-detects by listing all active (non-terminated) environments.
    import os as _os
    eb_info = {'reachable': False}
    try:
        import boto3 as _boto3
        _eb = _boto3.client('elasticbeanstalk', region_name='us-east-1')
        _env_name = _os.environ.get('EB_ENV_NAME', '').strip()
        if _env_name:
            _resp = _eb.describe_environments(
                EnvironmentNames=[_env_name], IncludeDeleted=False
            )
        else:
            _resp = _eb.describe_environments(IncludeDeleted=False)

        _envs = [
            e for e in _resp.get('Environments', [])
            if e.get('Status') not in ('Terminated', 'Terminating')
        ]
        if _envs:
            _e        = _envs[0]
            _stack    = _e.get('SolutionStackName', '')
            _platform = _stack.split(' running ')[0] if ' running ' in _stack else _stack
            _runtime  = _stack.split(' running ')[-1] if ' running ' in _stack else ''
            _app_name = _e.get('ApplicationName', '')
            _env_id   = _e.get('EnvironmentId', '')
            if _app_name and _env_id:
                _env_url = (
                    f"https://us-east-1.console.aws.amazon.com/elasticbeanstalk/home"
                    f"?region=us-east-1#/environment/overview"
                    f"?applicationName={_app_name}&environmentId={_env_id}"
                )
            else:
                _env_url = (
                    "https://us-east-1.console.aws.amazon.com/elasticbeanstalk"
                    "/home?region=us-east-1#/environments"
                )
            eb_info = {
                'reachable':     True,
                'name':          _e.get('EnvironmentName', ''),
                'app_name':      _app_name,
                'status':        _e.get('Status', 'Unknown'),
                'health':        _e.get('Health', 'Unknown'),
                'health_status': _e.get('HealthStatus', 'Unknown'),
                'platform':      _platform,
                'runtime':       _runtime,
                'tier':          _e.get('Tier', {}).get('Name', 'WebServer'),
                'cname':         _e.get('CNAME', ''),
                'region':        'us-east-1',
                'date_updated':  str(_e.get('DateUpdated', ''))[:19],
                'env_id':        _env_id,
                'env_url':       _env_url,
            }
    except Exception as _exc:
        eb_info = {'reachable': False, 'error': str(_exc)}

    # ── AWS S3 info (sizes via CloudWatch — 24 h delayed) ─────────────────────
    s3_info = {'reachable': False, 'buckets': []}
    try:
        import boto3 as _boto3
        import datetime as _dt
        from datetime import timedelta as _td

        _s3  = _boto3.client('s3',         region_name='us-east-1')
        _cw  = _boto3.client('cloudwatch', region_name='us-east-1')
        _now = _dt.datetime.utcnow()
        _ago = _now - _td(days=2)

        _buckets = []
        for _b in _s3.list_buckets().get('Buckets', []):
            _bname   = _b['Name']
            _created = str(_b.get('CreationDate', ''))[:10]

            try:
                _sz_pts = _cw.get_metric_statistics(
                    Namespace='AWS/S3', MetricName='BucketSizeBytes',
                    Dimensions=[{'Name': 'BucketName',   'Value': _bname},
                                {'Name': 'StorageType',  'Value': 'StandardStorage'}],
                    StartTime=_ago, EndTime=_now, Period=86400, Statistics=['Average'],
                ).get('Datapoints', [])
                _sz_bytes = sorted(_sz_pts, key=lambda x: x['Timestamp'])[-1]['Average'] if _sz_pts else 0
            except Exception:
                _sz_bytes = 0

            try:
                _obj_pts = _cw.get_metric_statistics(
                    Namespace='AWS/S3', MetricName='NumberOfObjects',
                    Dimensions=[{'Name': 'BucketName',  'Value': _bname},
                                {'Name': 'StorageType', 'Value': 'AllStorageTypes'}],
                    StartTime=_ago, EndTime=_now, Period=86400, Statistics=['Average'],
                ).get('Datapoints', [])
                _obj_cnt = int(sorted(_obj_pts, key=lambda x: x['Timestamp'])[-1]['Average']) if _obj_pts else 0
            except Exception:
                _obj_cnt = 0

            _buckets.append({
                'name':         _bname,
                'created':      _created,
                'size_mb':      round(_sz_bytes / (1024 * 1024), 2),
                'size_gb':      round(_sz_bytes / (1024 ** 3), 3),
                'object_count': _obj_cnt,
            })

        s3_info = {
            'reachable':     True,
            'buckets':       _buckets,
            'total_buckets': len(_buckets),
            'total_gb':      round(sum(b['size_gb'] for b in _buckets), 3),
        }
    except Exception as _exc:
        s3_info = {'reachable': False, 'buckets': [], 'error': str(_exc)}

    # Latest health check results for System Tests tab
    try:
        from app.core.health import get_latest_results
        check_results = get_latest_results()
    except Exception:
        check_results = []

    record_global_audit(cu, "view_system_health", "Viewed system health metrics")

    return render_template(
        "horizon/system_health.html",
        active="global",
        page="system_health",
        health=health,
        table_stats=table_stats,
        db_info=db_info,
        eb_info=eb_info,
        s3_info=s3_info,
        check_results=check_results,
    )


# ---------- System Tests — manual trigger ----------
@bp.route("/system-health/run-checks", methods=["POST"])
@login_required
@require_horizon
def run_health_checks():
    """Manually trigger all health checks and return JSON results."""
    from flask import jsonify
    from app.core.health import run_all_checks
    cu = current_user()
    try:
        results = run_all_checks()
        record_global_audit(cu, "run_health_checks", "Manually triggered system health checks")
        return jsonify({"ok": True, "results": [
            {**r, "checked_at": r["checked_at"].isoformat()} for r in results
        ]})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ---------- API Endpoints ----------
@bp.route("/api/instance/<int:instance_id>/stats")
@login_required
@require_horizon
def api_instance_stats(instance_id: int):
    """Get instance statistics as JSON."""
    stats = get_instance_stats(instance_id)
    return jsonify(stats)


@bp.route("/api/instances/list")
@login_required
@require_horizon
def api_instances_list():
    """Get all instances as JSON."""
    instances = get_all_instances()
    return jsonify(instances)

# ---------- Data Migrations ----------

@bp.route("/data-migrations", methods=["GET", "POST"])
@login_required
@require_horizon
def data_migrations():
    """Bulk data import for instances - CSV upload and validation."""
    cu = current_user()
    
    if request.method == "GET":
        # Get all instances for selection
        instances = get_all_instances()
        
        return render_template(
            "horizon/data_migrations.html",
            active="migrations",
            page="data_migrations",
            instances=instances
        )
    
    # POST - Handle file upload
    if request.method == "POST":
        try:
            # Get form data
            instance_id = request.form.get("instance_id", type=int)
            migration_type = request.form.get("migration_type")
            uploaded_file = request.files.get("csv_file")
            
            if not instance_id:
                flash("Please select an instance.", "danger")
                return redirect(url_for("horizon.data_migrations"))
            
            if not migration_type:
                flash("Please select a migration type.", "danger")
                return redirect(url_for("horizon.data_migrations"))
            
            if not uploaded_file or uploaded_file.filename == '':
                flash("Please upload a CSV file.", "danger")
                return redirect(url_for("horizon.data_migrations"))
            
            # Validate instance
            instance = get_instance_by_id(instance_id)
            if not instance:
                flash("Invalid instance selected.", "danger")
                return redirect(url_for("horizon.data_migrations"))
            
            # Read CSV file
            import csv
            import io
            
            # Decode the file
            stream = io.StringIO(uploaded_file.stream.read().decode("UTF8"), newline=None)
            csv_reader = csv.DictReader(stream)
            
            # Get headers
            csv_headers = csv_reader.fieldnames
            
            # Convert to list for processing
            rows = list(csv_reader)
            
            if not rows:
                flash("CSV file is empty.", "danger")
                return redirect(url_for("horizon.data_migrations"))
            
            if len(rows) > 10000:
                flash("File exceeds maximum limit of 10,000 rows.", "danger")
                return redirect(url_for("horizon.data_migrations"))
            
            # Store in session for column mapping
            session['csv_upload_data'] = {
                'instance_id': instance_id,
                'instance_name': instance['display_name'] or instance['name'],
                'migration_type': migration_type,
                'csv_headers': csv_headers,
                'csv_rows': rows,
                'filename': uploaded_file.filename,
                'row_count': len(rows)
            }
            
            record_horizon_audit(
                cu, "upload_migration_csv", "migrations",
                f"Uploaded {uploaded_file.filename} for {migration_type} migration ({len(rows)} rows)",
                target_instance_id=instance_id,
                severity="info"
            )
            
            # Redirect to column mapping
            return redirect(url_for("horizon.map_columns"))
            
        except Exception as e:
            logger.error(f"Migration upload error: {e}", exc_info=True)
            flash(f"Error processing file: {str(e)}", "danger")
            return redirect(url_for("horizon.data_migrations"))

@bp.route("/data-migrations/map-columns", methods=["GET", "POST"])
@login_required
@require_horizon
def map_columns():
    """Column mapping interface for flexible CSV imports."""
    cu = current_user()
    
    if request.method == "GET":
        # Check if we have uploaded file data in session
        upload_data = session.get('csv_upload_data')
        if not upload_data:
            flash("No CSV file uploaded. Please start again.", "warning")
            return redirect(url_for("horizon.data_migrations"))
        
        from .column_mapper import ColumnMapper
        
        # Detect columns automatically
        detection = ColumnMapper.detect_columns(
            upload_data['csv_headers'],
            upload_data['migration_type']
        )
        
        # Get all instances for display
        instances = get_all_instances()
        instance = next((i for i in instances if i['id'] == upload_data['instance_id']), None)
        
        return render_template(
            "horizon/map_columns.html",
            active="migrations",
            page="map_columns",
            upload_data=upload_data,
            detection=detection,
            instance=instance
        )
    
    # POST - User has confirmed mappings
    if request.method == "POST":
        upload_data = session.get('csv_upload_data')
        if not upload_data:
            flash("Session expired. Please upload file again.", "warning")
            return redirect(url_for("horizon.data_migrations"))
        
        # Get user's column mappings from form
        mapping = {}
        for key in request.form.keys():
            if key.startswith('map_'):
                app_field = key[4:]  # Remove 'map_' prefix
                csv_column = request.form.get(key)
                if csv_column:
                    mapping[app_field] = csv_column
        
        # Store mapping in session
        upload_data['column_mapping'] = mapping
        session['csv_upload_data'] = upload_data
        
        # Apply mapping to all rows
        from .column_mapper import ColumnMapper
        mapped_rows = []
        for row in upload_data['csv_rows']:
            mapped_row = ColumnMapper.apply_mapping(row, mapping)
            mapped_rows.append(mapped_row)
        
        # Now validate with mapped data
        from .migrations import MigrationProcessor
        processor = MigrationProcessor(upload_data['instance_id'], cu)
        
        result = processor.validate_import(upload_data['migration_type'], mapped_rows)
        
        # Store in session for preview
        session['migration_preview'] = {
            'instance_id': upload_data['instance_id'],
            'instance_name': upload_data['instance_name'],
            'migration_type': upload_data['migration_type'],
            'total_rows': len(mapped_rows),
            'valid_rows': result['valid_count'],
            'invalid_rows': result['invalid_count'],
            'warnings': result['warnings'],
            'errors': result['errors'],
            'preview_data': result['preview'][:20],
            'validated_data': result['validated_data'],
            'column_mapping': mapping
        }
        
        record_horizon_audit(
            cu, "map_columns_migration", "migrations",
            f"Mapped columns for {upload_data['migration_type']} migration ({len(mapping)} fields mapped)",
            target_instance_id=upload_data['instance_id'],
            severity="info"
        )
        
        return redirect(url_for("horizon.migration_preview"))

@bp.route("/data-migrations/preview")
@login_required
@require_horizon
def migration_preview():
    """Preview migration data before import."""
    cu = current_user()
    
    preview_data = session.get('migration_preview')
    if not preview_data:
        flash("No migration data found. Please upload a file first.", "warning")
        return redirect(url_for("horizon.data_migrations"))
    
    return render_template(
        "horizon/migration_preview.html",
        active="migrations",
        page="migration_preview",
        preview=preview_data
    )


@bp.route("/data-migrations/execute", methods=["POST"])
@login_required
@require_horizon
def execute_migration():
    """Execute the migration after preview confirmation."""
    cu = current_user()
    
    preview_data = session.get('migration_preview')
    if not preview_data:
        return jsonify({"success": False, "error": "No migration data found"}), 400
    
    try:
        instance_id = preview_data['instance_id']
        migration_type = preview_data['migration_type']
        validated_data = preview_data['validated_data']
        
        # Execute the migration
        from .migrations import MigrationProcessor
        processor = MigrationProcessor(instance_id, cu)
        
        result = processor.execute_import(migration_type, validated_data)
        
        # Clear session data
        session.pop('migration_preview', None)
        
        # Record audit
        record_horizon_audit(
            cu, "execute_migration", "migrations",
            f"Completed {migration_type} migration for instance {instance_id}: "
            f"{result['success_count']} successful, {result['failed_count']} failed",
            target_instance_id=instance_id,
            severity="info"
        )
        
        return jsonify({
            "success": True,
            "message": f"Migration complete! {result['success_count']} records imported, {result['failed_count']} failed.",
            "details": result
        })
        
    except Exception as e:
        logger.error(f"Migration execution error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/data-migrations/cancel", methods=["POST"])
@login_required
@require_horizon
def cancel_migration():
    """Cancel a pending migration."""
    cu = current_user()
    
    preview_data = session.pop('migration_preview', None)
    
    if preview_data:
        record_horizon_audit(
            cu, "cancel_migration", "migrations",
            f"Cancelled {preview_data['migration_type']} migration for instance {preview_data['instance_id']}",
            severity="info"
        )
    
    return jsonify({"success": True, "message": "Migration cancelled"})