"""
Global Admin Views - PostgreSQL Edition
Multi-tenant administration and management
"""

import secrets  # Python standard library for generating random tokens
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
    """Global admin dashboard with system overview."""
    cu = current_user()
    
    # Get all instances
    instances = get_all_instances()
    
    # Get global statistics
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        # Total users across all instances
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
        
        # Recent activity (last 24 hours)
        cursor.execute("""
            SELECT COUNT(*) as count FROM audit_logs 
            WHERE ts_utc >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
        """)
        result = cursor.fetchone()
        recent_activity = result['count'] if result else 0
        
        # Users by permission level
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
        
        # Recent critical events
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
    
    # Instance statistics
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
        active="global",
        page="dashboard",
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
@require_horizon
def back_to_app():
    """Smart redirect to sandbox or user's instance."""
    from app.core.database import get_db_connection
    
    cu = current_user()
    perm_level = cu.get('permission_level')
    
    print(f"🔙 BACK TO APP: user={cu.get('username')}, perm={perm_level}")
    
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
                    print(f"➡️ Sending to sandbox (ID: {sandbox['id']})")
                    return redirect(url_for('home.index', instance_id=sandbox['id']))
        except Exception as e:
            print(f"❌ Error finding sandbox: {e}")
    
    # Others go to their assigned instance
    instance_id = cu.get('instance_id')
    if instance_id:
        print(f"➡️ Sending to instance {instance_id}")
        return redirect(url_for('home.index', instance_id=instance_id))
    
    flash('No instance assigned.', 'warning')
    return redirect(url_for('horizon.dashboard'))

# ---------- Instance Management ----------
@bp.route("/instances")
@login_required
@require_horizon
def instance_management():
    """View and manage all instances."""
    cu = current_user()
    
    instances = get_all_instances()
    
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
        active="global",
        page="instances",
        instances=enhanced_instances
    )


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
    
    # Get instance users
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
        
        # Get recent activity for this instance
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
        storage_limit_gb = int(request.form.get("storage_limit_gb", 10))
        subscription_tier = request.form.get("subscription_tier", "standard")
        
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
        
        # Future features
        subdomain = request.form.get("subdomain", "").strip().lower()
        custom_domain = request.form.get("custom_domain", "").strip().lower()
        rate_limit_per_hour = int(request.form.get("rate_limit_per_hour", 1000))
        allowed_ips = request.form.get("allowed_ips", "").strip()
        require_2fa = bool(request.form.get("require_2fa"))
        
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
                        max_users, storage_limit_gb, subscription_tier,
                        subdomain, custom_domain, rate_limit_per_hour,
                        allowed_ips, require_2fa, is_active, notes,
                        enabled_modules
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    name, display_name, description,
                    contact_name, contact_email, contact_phone,
                    max_users, storage_limit_gb, subscription_tier,
                    subdomain or None, custom_domain or None, rate_limit_per_hour,
                    allowed_ips or None, require_2fa, is_active, notes,
                    enabled_modules
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
        page="edit_instance",
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


# ---------- Instance Support ----------
@bp.route("/support")
@login_required
@require_horizon
def instance_support():
    """Instance support and troubleshooting."""
    cu = current_user()
    
    # Get instances with issues
    instances_raw = get_all_instances()
    
    issues = []
    instances_enhanced = []
    
    for inst in instances_raw:
        stats = get_instance_stats(inst['id'])
        
        # Add enhanced data for display
        inst_enhanced = {
            'id': inst['id'],
            'name': inst['name'],
            'subdomain': inst.get('subdomain'),
            'is_active': inst['is_active'],
            'max_users': inst['max_users'],
            'users': stats['user_count'],
            'storage_pct': round((stats['storage_mb'] / 10240 * 100) if stats.get('storage_mb') else 0, 1),
            'last_check': 'Just now'  # Mock - implement actual health check timestamp
        }
        instances_enhanced.append(inst_enhanced)
        
        # Check for potential issues
        if stats['user_count'] >= inst['max_users']:
            issues.append({
                'severity': 'critical',
                'instance': inst,
                'type': 'User Limit',
                'message': f"User limit reached: {stats['user_count']}/{inst['max_users']}"
            })
        elif stats['user_count'] >= inst['max_users'] * 0.9:
            issues.append({
                'severity': 'warning',
                'instance': inst,
                'type': 'User Limit',
                'message': f"Near user limit: {stats['user_count']}/{inst['max_users']}"
            })
        
        if not inst['is_active']:
            issues.append({
                'severity': 'critical',
                'instance': inst,
                'type': 'Inactive',
                'message': "Instance is deactivated"
            })
        
        if stats['inactive_users'] > stats['user_count'] * 0.5:
            issues.append({
                'severity': 'info',
                'instance': inst,
                'type': 'Inactive Users',
                'message': f"High inactive user count: {stats['inactive_users']}"
            })
        
        if stats.get('storage_mb', 0) > 9000:  # 90% of 10GB
            issues.append({
                'severity': 'warning',
                'instance': inst,
                'type': 'Storage',
                'message': f"High storage usage: {stats['storage_mb']} MB"
            })
    
    record_global_audit(cu, "view_instance_support", f"Viewed instance support, found {len(issues)} issues")
    
    return render_template(
        "horizon/instance_support.html",
        active="global",
        page="support",
        instances=instances_enhanced,
        issues=issues
    )


@bp.route("/support/mirror/<int:user_id>", methods=["GET", "POST"])
@login_required
@require_horizon
def mirror_user_session(user_id: int):
    """Start mirroring a user's session for support."""
    cu = current_user()
    
    if request.method == "POST":
        # Get target user
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT u.id, u.username, u.instance_id, u.permission_level,
                       i.name as instance_name
                FROM users u
                LEFT JOIN instances i ON u.instance_id = i.id
                WHERE u.id = %s AND (u.deleted_at IS NULL OR u.deleted_at = '')
            """, (user_id,))
            target_user = cursor.fetchone()
            cursor.close()
        
        if not target_user:
            flash("User not found", "danger")
            return redirect(url_for("horizon.instance_support"))
        
        # Check if L3 can mirror this user (not other L3s or S1s)
        if cu.get('permission_level') == 'L3':
            if target_user[3] in ['L3', 'S1']:
                flash("You cannot mirror other Global or Super Admins", "danger")
                return redirect(url_for("horizon.instance_support"))
        
        reason = request.form.get("reason", "").strip()
        
        if not reason:
            flash("Please provide a reason for mirroring", "warning")
            return redirect(url_for("horizon.instance_support"))
        
        # End any existing mirror sessions for this support user
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_mirror_sessions
                SET is_active = false, ended_at = CURRENT_TIMESTAMP
                WHERE support_user_id = %s AND is_active = true
            """, (cu['id'],))
            conn.commit()
            cursor.close()
        
        # Create new mirror session
        session_token = secrets.token_urlsafe(32)
        
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_mirror_sessions (
                    support_user_id, support_username,
                    target_user_id, target_username, target_instance_id,
                    reason, session_token, ip_address, user_agent
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                cu['id'], cu['username'],
                target_user[0], target_user[1], target_user[2],
                reason, session_token,
                request.remote_addr, request.headers.get('User-Agent', '')[:500]
            ))
            conn.commit()
            cursor.close()
        
        # Store mirror session in Flask session
        session['mirror_session'] = {
            'token': session_token,
            'target_user_id': user_id,
            'target_username': target_user[1],
            'target_instance_id': target_user[2],
            'target_instance_name': target_user[4],
            'started_at': datetime.utcnow().isoformat()
        }
        
        # Record audit
        record_global_audit(cu, "start_mirror_session", 
            f"Started mirroring user {target_user[1]} (ID: {user_id}). Reason: {reason}")
        
        flash(f"Now mirroring {target_user[1]} from {target_user[4]}", "success")
        return redirect(url_for('home.index'))
    
    # GET - show confirmation form
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.username, u.permission_level, i.name
            FROM users u
            LEFT JOIN instances i ON u.instance_id = i.id
            WHERE u.id = %s
        """, (user_id,))
        user_info = cursor.fetchone()
        cursor.close()
    
    if not user_info:
        flash("User not found", "danger")
        return redirect(url_for("horizon.instance_support"))
    
    return render_template(
        "horizon/confirm_mirror.html",
        active="global",
        page="support",
        user_id=user_id,
        username=user_info[0],
        permission_level=user_info[1],
        instance_name=user_info[2]
    )


@bp.route("/api/session-info")
@login_required
def get_session_info():
    """Get current session information including mirror status."""
    cu = current_user()
    mirror_info = session.get('mirror_session')
    
    response = {
        'user': {
            'id': cu['id'],
            'username': cu['username'],
            'permission_level': cu.get('permission_level', ''),
            'instance_id': cu.get('instance_id'),
        },
        'is_mirroring': bool(mirror_info),
        'mirror_session': None
    }
    
    if mirror_info:
        response['mirror_session'] = {
            'target_username': mirror_info['target_username'],
            'target_instance': mirror_info.get('target_instance_name'),
            'started_at': mirror_info['started_at']
        }
    
    return jsonify(response)


@bp.route("/mirror/end", methods=["POST"])
@login_required
def end_mirror_session():
    """End current mirror session."""
    token = session.get('mirror_session_token')
    
    if not token:
        return jsonify({"success": False, "error": "No active mirror session"}), 400
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE user_mirror_sessions
            SET is_active = false, ended_at = CURRENT_TIMESTAMP
            WHERE session_token = %s AND is_active = true
        """, (token,))
        conn.commit()
        cursor.close()
    
    # Clear from session
    session.pop('mirror_session_token', None)
    session.pop('mirror_target_user_id', None)
    
    return jsonify({"success": True, "message": "Mirror session ended"})


# ---------- Global Insights ----------
@bp.route("/insights")
@login_required
@require_horizon
def global_insights():
    """Cross-instance analytics and insights."""
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
        
        # User Growth
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
        
        # Activity by Module
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
        
        # Instance Comparison
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
        
        # Peak Usage Times
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
        
        # Module Adoption by Instance
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

        # Top Active Users
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


# ---------- Global Audits ----------
@bp.route("/audits")
@login_required
@require_horizon
def global_audits():
    """View Horizon platform audit logs."""
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
        
        # Build query
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
                u.instance_id,
                i.name as instance_name,
                al.target_user_id,
                al.target_username
            FROM audit_logs al
            LEFT JOIN users u ON al.user_id = u.id
            LEFT JOIN instances i ON u.instance_id = i.id
            WHERE 1=1
        """
        params = []
        
        # Apply filters
        if filters.get('instance_id'):
            query += " AND u.instance_id = %s"
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
        
        # Apply filters (same as global_audits)
        if filters.get("instance_id"):
            query += " AND u.instance_id = %s"
            params.append(int(filters["instance_id"]))
        
        if filters.get("username"):
            query += " AND al.username LIKE %s"
            params.append(f"%{filters['username']}%")
        
        if filters.get("action"):
            query += " AND al.action LIKE %s"
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
            logs_data.append({
                'id': log[0],
                'action': log[1],
                'username': log[2],
                'module': log[3],
                'details': log[4],
                'timestamp': str(log[5]),
                'permission_level': log[6],
                'ip_address': log[7],
                'user_agent': log[8],
                'instance_name': log[-1] if len(log) > 10 else None
            })
        
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
                log[5],  # timestamp
                log[2],  # username
                log[6] if log[6] else 'Module User',  # permission_level
                log[1],  # action
                log[3],  # module
                log[4] if log[4] else '',  # details
                log[12] if len(log) > 12 and log[12] else '',  # target_username
                log[-1] if len(log) > 10 and log[-1] else '',  # instance_name
                log[7] if log[7] else '',  # ip_address
                log[8][:100] if log[8] else ''  # user_agent (truncated)
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

# ========== GLOBAL USER MANAGEMENT ==========

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
            
            if not username or not password:
                flash("Username and password are required.", "danger")
                return redirect(url_for("horizon.create_global_user"))
            
            if not instance_id:
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
                
                # Get permission level and modules
                permission_level = request.form.get("permission_level", "")
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
            
            record_horizon_audit(
                cu, "create_user", "users",
                f"Created user {username} (ID: {user_id}) in instance {instance_id}",
                target_user_id=user_id,
                severity="info"
            )
            
            flash(f"✅ User '{username}' created successfully!", "success")
            return redirect(url_for("horizon.global_users"))
            
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            flash(f"❌ Error: {str(e)}", "danger")
            return redirect(url_for("horizon.create_global_user"))
    
    # GET - show form
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, display_name FROM instances WHERE is_active = TRUE ORDER BY name")
        instances = cursor.fetchall()
        cursor.close()
    
    return render_template(
        "horizon/create_global_user.html",
        active="users",
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
        "horizon/edit_global_user.html",
        active="users",
        user=user,
        instances=instances
    )


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

# ---------- System Health ----------
@bp.route("/system-health")
@login_required
@require_horizon
def system_health():
    """View system health and performance metrics."""
    cu = current_user()
    
    health = get_system_health_metrics()
    
    # Get database statistics (PostgreSQL version)
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        # Table sizes using PostgreSQL system catalogs
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
    
    record_global_audit(cu, "view_system_health", "Viewed system health metrics")
    
    return render_template(
        "horizon/system_health.html",
        active="global",
        page="system_health",
        health=health,
        table_stats=table_stats
    )

@bp.route("/global-users")
@login_required
@require_horizon
def global_users():
    """Global user management - shows all users across all instances."""
    cu = current_user()
    
    # Get search/filter parameters
    search = request.args.get('search', '')
    instance_filter = request.args.get('instance_id', type=int)
    permission_filter = request.args.get('permission_level', '')
    status_filter = request.args.get('status', '')  # 'active' or 'inactive'
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        # Get all instances for filter dropdown
        cursor.execute("""
            SELECT id, name, display_name, is_active
            FROM instances
            ORDER BY name
        """)
        instances = cursor.fetchall()
        
        # Build user query with filters
        query = """
            SELECT 
                u.id, u.username, u.first_name, u.last_name, u.email, u.phone,
                u.permission_level, u.module_permissions, u.is_active,
                u.created_at, u.last_login, u.instance_id,
                i.name as instance_name, i.display_name as instance_display_name,
                i.is_active as instance_active
            FROM users u
            LEFT JOIN instances i ON u.instance_id = i.id
            WHERE u.deleted_at IS NULL
        """
        params = []
        
        # Apply filters
        if search:
            query += """ AND (
                u.username ILIKE %s OR 
                u.first_name ILIKE %s OR 
                u.last_name ILIKE %s OR 
                u.email ILIKE %s
            )"""
            search_term = f"%{search}%"
            params.extend([search_term, search_term, search_term, search_term])
        
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
        all_users = cursor.fetchall()
        
        # Get user statistics
        cursor.execute("""
            SELECT 
                COUNT(*) as total_users,
                COUNT(CASE WHEN permission_level = 'S1' THEN 1 END) as s1_count,
                COUNT(CASE WHEN permission_level = 'L3' THEN 1 END) as l3_count,
                COUNT(CASE WHEN permission_level = 'L2' THEN 1 END) as l2_count,
                COUNT(CASE WHEN permission_level = 'L1' THEN 1 END) as l1_count,
                COUNT(CASE WHEN permission_level = '' OR permission_level IS NULL THEN 1 END) as module_count,
                COUNT(CASE WHEN is_active = TRUE THEN 1 END) as active_count,
                COUNT(CASE WHEN is_active = FALSE THEN 1 END) as inactive_count
            FROM users
            WHERE deleted_at IS NULL
        """)
        stats = cursor.fetchone()
        
        cursor.close()
    
    record_global_audit(cu, "view_global_users", f"Viewed global user list ({len(all_users)} users)")
    
    return render_template(
        "horizon/global_users.html",
        active="users",
        page="global_users",
        cu=cu,
        instances=instances,
        users=all_users,
        stats=stats,
        search=search,
        instance_filter=instance_filter,
        permission_filter=permission_filter,
        status_filter=status_filter
    )

@bp.route("/global-users/export")
@login_required
@require_horizon
def export_global_users():
    """Export all users as CSV or JSON."""
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
            'id': u.id,
            'username': u.username,
            'first_name': u.first_name,
            'last_name': u.last_name,
            'email': u.email,
            'phone': u.phone,
            'permission_level': u.permission_level or 'Module User',
            'is_active': u.is_active,
            'instance': u.instance_name,
            'created_at': str(u.created_at),
            'last_login': str(u.last_login) if u.last_login else None
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
                u.username, u.first_name, u.last_name, u.email or '', u.phone or '',
                u.permission_level or 'Module User',
                'Active' if u.is_active else 'Inactive',
                u.instance_name,
                str(u.created_at) if u.created_at else '',
                str(u.last_login) if u.last_login else ''
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