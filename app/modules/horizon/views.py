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
            flash("Access denied. System privileges required.", "danger")
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
                permission_level, module_permissions, location,
                created_at, last_login_at
            FROM users
            WHERE instance_id = %s
            AND deleted_at IS NULL
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


@bp.route("/instances/create", methods=["GET", "POST"])
@login_required
@require_horizon
def create_instance():
    """Create new instance with L2 administrator."""
    cu = current_user()
    
    if request.method == "POST":
        # Instance details
        name = request.form.get("name", "").strip()
        subdomain = request.form.get("subdomain", "").strip()
        contact_email = request.form.get("contact_email", "").strip()
        contact_phone = request.form.get("contact_phone", "").strip()
        address = request.form.get("address", "").strip()
        max_users = int(request.form.get("max_users", 100) or 100)
        features = request.form.getlist("features")
        
        # L2 Administrator details
        admin_username = request.form.get("admin_username", "").strip()
        admin_password = request.form.get("admin_password", "")
        admin_email = request.form.get("admin_email", "").strip()
        admin_first_name = request.form.get("admin_first_name", "").strip()
        admin_last_name = request.form.get("admin_last_name", "").strip()
        
        # Validation
        errors = []
        
        if not name:
            errors.append("Instance name is required")
        
        if not contact_email:
            errors.append("Contact email is required")
        
        if not admin_username:
            errors.append("Administrator username is required")
        
        if not admin_password or len(admin_password) < 8:
            errors.append("Administrator password must be at least 8 characters")
        
        if not admin_email:
            errors.append("Administrator email is required")
        
        # Validate subdomain
        if subdomain:
            import re
            if not re.match(r'^[a-z0-9-]+$', subdomain):
                errors.append("Invalid subdomain format. Use only lowercase letters, numbers, and hyphens.")
            else:
                # Check if subdomain exists
                existing = get_instance_by_subdomain(subdomain)
                if existing:
                    errors.append(f"Subdomain '{subdomain}' is already in use.")
        
        # Check if admin username already exists
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = %s", (admin_username,))
            if cursor.fetchone():
                errors.append(f"Username '{admin_username}' already exists")
            cursor.close()
        
        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template(
                "horizon/create_instance.html",
                active="global",
                page="create_instance",
                form_data=request.form
            )
        
        try:
            # Create instance
            instance_id = InstanceManager.create_instance(
                name=name,
                subdomain=subdomain or None,
                contact_email=contact_email,
                contact_phone=contact_phone or None,
                address=address or None,
                max_users=max_users,
                features=features,
                created_by=cu['id']
            )
            
            # Create L2 administrator account
            hashed_password = bcrypt.hashpw(
                admin_password.encode('utf-8'), 
                bcrypt.gensalt()
            ).decode('utf-8')
            
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                
                # Determine module permissions based on features
                module_permissions = []
                if 'ledger' in features or 'ledger_enabled' in features:
                    module_permissions.append('ledger')
                if 'flow' in features or 'flow_enabled' in features:
                    module_permissions.append('flow')
                if 'fulfillment' in features or 'fulfillment_enabled' in features:
                    module_permissions.append('fulfillment')
                module_permissions.append('admin')  # Always give admin access
                
                cursor.execute("""
                    INSERT INTO users (
                        username, email, password_hash,
                        first_name, last_name, 
                        permission_level, module_permissions,
                        instance_id, location, is_active,
                        created_at, created_by
                    )
                    VALUES (%s, %s, %s, %s, %s, 'L2', %s, %s, %s, true, CURRENT_TIMESTAMP, %s)
                """, (
                    admin_username,
                    admin_email,
                    hashed_password,
                    admin_first_name,
                    admin_last_name,
                    json.dumps(module_permissions),
                    instance_id,
                    name,  # Use instance name as location
                    cu['id']
                ))
                
                conn.commit()
                cursor.close()
            
            # Update instance settings
            custom_settings = {
                'branding': {
                    'logo_url': request.form.get("logo_url", ""),
                    'primary_color': request.form.get("primary_color", "#0d6efd"),
                    'secondary_color': request.form.get("secondary_color", "#6c757d"),
                    'custom_css': ''
                },
                'modules': {
                    'ledger_enabled': 'ledger' in features,
                    'flow_enabled': 'flow' in features,
                    'fulfillment_enabled': 'fulfillment' in features
                },
                'features': {
                    'sso_enabled': 'sso' in features,
                    'api_access': 'api_access' in features,
                    'custom_reports': 'custom_reports' in features,
                    'mobile_app': 'mobile_app' in features
                },
                'limits': {
                    'storage_mb': int(request.form.get("storage_limit", 10240) or 10240),
                    'api_calls_per_day': 10000,
                    'max_file_size_mb': 50
                },
                'security': {
                    'force_2fa': 'force_2fa' in features,
                    'password_expiry_days': int(request.form.get("password_expiry", 90) or 90),
                    'session_timeout_minutes': int(request.form.get("session_timeout", 480) or 480),
                    'ip_whitelist': []
                }
            }
            
            InstanceManager.update_instance(instance_id, {'settings': custom_settings})
            
            record_global_audit(cu, "create_instance", 
                f"Created instance: {name} (ID: {instance_id}) with L2 admin: {admin_username}")
            
            flash(f"Instance '{name}' created successfully with administrator '{admin_username}'!", "success")
            return redirect(url_for("horizon.instance_detail", instance_id=instance_id))
            
        except Exception as e:
            flash(f"Error creating instance: {str(e)}", "danger")
            return render_template(
                "horizon/create_instance.html",
                active="global",
                page="create_instance",
                form_data=request.form
            )
    
    # GET request
    return render_template(
        "horizon/create_instance.html",
        active="global",
        page="create_instance"
    )


@bp.route("/instances/<int:instance_id>/edit", methods=["GET", "POST"])
@login_required
@require_horizon
def edit_instance(instance_id: int):
    """Edit instance details."""
    cu = current_user()
    
    instance = get_instance_by_id(instance_id)
    if not instance:
        flash("Instance not found.", "warning")
        return redirect(url_for("horizon.instance_management"))
    
    if request.method == "POST":
        updates = {
            'name': request.form.get("name", "").strip(),
            'subdomain': request.form.get("subdomain", "").strip(),
            'contact_email': request.form.get("contact_email", "").strip(),
            'contact_phone': request.form.get("contact_phone", "").strip(),
            'address': request.form.get("address", "").strip(),
            'max_users': int(request.form.get("max_users", 100) or 100),
            'is_active': bool(request.form.get("is_active")),
        }
        
        InstanceManager.update_instance(instance_id, updates)
        
        record_global_audit(cu, "update_instance", f"Updated instance: {updates['name']} (ID: {instance_id})")
        
        flash(f"Instance '{updates['name']}' updated successfully!", "success")
        return redirect(url_for("horizon.instance_detail", instance_id=instance_id))
    
    return render_template(
        "horizon/edit_instance.html",
        active="global",
        page="edit_instance",
        instance=instance
    )


@bp.route("/instances/<int:instance_id>/delete", methods=["POST"])
@login_required
@require_super_admin  # Only S1 can delete
def delete_instance(instance_id: int):
    """Permanently delete an instance (S1 only)."""
    cu = current_user()
    
    instance = get_instance_by_id(instance_id)
    if not instance:
        return jsonify({"success": False, "error": "Instance not found"}), 404
    
    # Confirm deletion with extra verification
    confirmation_code = request.json.get("confirmation_code", "")
    expected_code = f"DELETE-{instance['name'].upper()[:6]}-{instance_id}"
    
    if confirmation_code != expected_code:
        return jsonify({
            "success": False, 
            "error": f"Invalid confirmation code. Expected: {expected_code}"
        }), 400
    
    try:
        success = InstanceManager.delete_instance(instance_id, cu['id'])
        
        if success:
            record_global_audit(cu, "delete_instance", 
                f"PERMANENTLY DELETED instance: {instance['name']} (ID: {instance_id})")
            
            return jsonify({
                "success": True, 
                "message": f"Instance '{instance['name']}' permanently deleted"
            })
        else:
            return jsonify({"success": False, "error": "Failed to delete instance"}), 500
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/instances/<int:instance_id>/deactivate", methods=["POST"])
@login_required
@require_horizon
def deactivate_instance(instance_id: int):
    """Deactivate an instance."""
    cu = current_user()
    
    instance = get_instance_by_id(instance_id)
    if not instance:
        return jsonify({"success": False, "error": "Instance not found"}), 404
    
    reason = request.json.get("reason", "")
    
    InstanceManager.deactivate_instance(instance_id, reason, cu['id'])
    
    record_global_audit(cu, "deactivate_instance", 
                       f"Deactivated instance: {instance['name']} (ID: {instance_id}). Reason: {reason}")
    
    return jsonify({"success": True, "message": f"Instance '{instance['name']}' deactivated"})


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
    
    analytics = GlobalAnalytics()
    
    # Get insights data
    insights = {
        'user_growth': analytics.get_user_growth(date_from, date_to),
        'activity_by_module': analytics.get_activity_by_module(date_from, date_to),
        'instance_comparison': analytics.get_instance_comparison(),
        'peak_usage_times': analytics.get_peak_usage_times(date_from, date_to),
        'module_adoption': analytics.get_module_adoption(),
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
    """View global audit logs across all instances."""
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
    
    # Remove empty filters
    filters = {k: v for k, v in filters.items() if v}
    
    # Build query
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
        
        query += " ORDER BY al.ts_utc DESC LIMIT 500"
        
        cursor.execute(query, params)
        logs = cursor.fetchall()
        
        # Get filter options
        cursor.execute("SELECT id, name FROM instances ORDER BY name")
        instances = cursor.fetchall()
        
        cursor.execute("SELECT DISTINCT module FROM audit_logs ORDER BY module")
        modules = [row[0] for row in cursor.fetchall()]
        
        cursor.execute("SELECT DISTINCT action FROM audit_logs ORDER BY action")
        actions = [row[0] for row in cursor.fetchall()]
        
        cursor.close()
    
    record_global_audit(cu, "view_global_audits", f"Viewed global audits with filters: {filters}")
    
    return render_template(
        "horizon/global_audits.html",
        active="global",
        page="audits",
        logs=logs,
        filters=filters,
        instances=instances,
        modules=modules,
        actions=actions
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
                schemaname || '.' || tablename AS table_name,
                n_live_tup AS row_count
            FROM pg_stat_user_tables
            ORDER BY n_live_tup DESC
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