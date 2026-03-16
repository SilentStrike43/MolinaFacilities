# app/modules/admin/views.py
"""
Admin Module - Instance-Aware Edition
L1: Can view/manage users in their own instance
L2+: Can view/manage users across all instances
"""

import json
import csv
import io
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, jsonify

from app.modules.auth.security import (
    login_required, current_user, record_audit,
    get_audit_logs, get_audit_statistics
)

from app.modules.users.models import get_user_by_id
from app.core.permissions import PermissionManager, PermissionLevel
from app.core.database import get_db_connection
from app.core.instance_context import get_current_instance

admin_bp = Blueprint("admin", __name__, url_prefix="/admin", template_folder="templates")

bp = admin_bp

# ---------- Permission Checking ----------
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
    
    # Legacy compatibility
    if user_data.get("is_sysadmin"):
        return "L2"
    elif user_data.get("is_admin"):
        return "L1"
    
    return None


def require_admin_level(min_level="L1"):
    """Decorator to require minimum admin level."""
    def decorator(f):
        def wrapped(*args, **kwargs):
            cu = current_user()
            if not cu:
                flash("Please log in to continue.", "warning")
                return redirect(url_for("auth.login"))
            
            user_level = get_user_permission_level(cu)
            if not user_level:
                flash("You need administrative permissions to access this area.", "danger")
                return redirect(url_for("home.index"))
            
            # Check if user has required level
            level_hierarchy = {"L1": 1, "L2": 2, "L3": 3, "S1": 4}
            required = level_hierarchy.get(min_level, 0)
            actual = level_hierarchy.get(user_level, 0)
            
            if actual < required:
                flash(f"You need {min_level} permissions or higher to access this area.", "danger")
                return redirect(url_for("home.index"))
            
            return f(*args, **kwargs)
        wrapped.__name__ = f.__name__
        return wrapped
    return decorator


# ---------- Audit Log Functions ----------
def record_audit_log(user_data, action, module, details,
                     target_user_id=None, target_username=None):
    """Record an audit log entry. Delegates to app.core.audit.log_action."""
    from app.core.audit import log_action
    log_action(
        user_data, action, module, details,
        target_user_id=target_user_id,
        target_username=target_username,
    )


def query_audit_logs(filters=None, limit=1000):
    """Query audit logs with filters."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        query = "SELECT * FROM audit_logs WHERE 1=1"
        params = []
        
        if filters:
            if filters.get("user_id"):
                query += " AND user_id = %s"
                params.append(filters["user_id"])
            
            if filters.get("username"):
                query += " AND username ILIKE %s"
                params.append(f"%{filters['username']}%")
            
            if filters.get("action"):
                query += " AND action ILIKE %s"
                params.append(f"%{filters['action']}%")
            
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
        
        query += " ORDER BY ts_utc DESC"
        query += f" LIMIT {limit}"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()
        return rows


def get_audit_statistics(days=30):
    """Get audit log statistics for dashboard."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        cutoff_date = (datetime.utcnow() - timedelta(days=days)).date()
        
        stats = {}
        
        # Total actions
        cursor.execute(
            "SELECT COUNT(*) as count FROM audit_logs WHERE DATE(ts_utc) >= %s", 
            (cutoff_date,)
        )
        result = cursor.fetchone()
        stats["total_actions"] = result['count'] if result else 0
        
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
            ORDER BY count DESC LIMIT 10
        """, (cutoff_date,))
        user_stats = cursor.fetchall()
        stats["top_users"] = [(row['username'], row['count']) for row in user_stats]
        
        # Critical actions
        cursor.execute("""
            SELECT COUNT(*) as count FROM audit_logs
            WHERE DATE(ts_utc) >= %s AND action IN (
                'elevate_user', 'demote_user', 'delete_user', 
                'approve_deletion', 'create_user', 'system_config_change'
            )
        """, (cutoff_date,))
        result = cursor.fetchone()
        stats["critical_actions"] = result['count'] if result else 0
        
        cursor.close()
        return stats


# ---------- Routes ----------

@admin_bp.route("/")
@login_required
@require_admin_level("L1")
def dashboard():
    """Admin dashboard with statistics and overview."""
    cu = current_user()
    user_level = get_user_permission_level(cu)
    
    # Get statistics
    stats = get_audit_statistics(30)
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        # Get deletion requests
        cursor.execute("""
            SELECT 
                dr.id, dr.user_id, dr.reason, dr.requested_at,
                u.username, u.first_name, u.last_name
            FROM deletion_requests dr
            JOIN users u ON dr.user_id = u.id
            WHERE dr.status = 'pending'
            ORDER BY dr.requested_at DESC
        """)
        deletion_requests = cursor.fetchall()

        # Get recent critical actions
        cursor.execute("""
            SELECT * FROM audit_logs
            WHERE action IN (
                'elevate_user', 'demote_user', 'delete_user', 
                'approve_deletion', 'create_user', 'system_config_change'
            )
            ORDER BY ts_utc DESC LIMIT 10
        """)
        recent_critical = cursor.fetchall()
        
        # Get pending deletion requests count
        cursor.execute("""
            SELECT COUNT(*) as count FROM deletion_requests
            WHERE status = 'pending'
        """)
        result = cursor.fetchone()
        pending_deletions = result['count'] if result else 0
        
        # Get user counts by permission level
        cursor.execute("""
            SELECT 
                SUM(CASE WHEN permission_level = 'S1' THEN 1 ELSE 0 END) as s1_count,
                SUM(CASE WHEN permission_level = 'L3' THEN 1 ELSE 0 END) as l3_count,
                SUM(CASE WHEN permission_level = 'L2' THEN 1 ELSE 0 END) as l2_count,
                SUM(CASE WHEN permission_level = 'L1' THEN 1 ELSE 0 END) as l1_count,
                SUM(CASE WHEN permission_level = '' OR permission_level IS NULL THEN 1 ELSE 0 END) as module_count,
                COUNT(*) as total_count
            FROM users
            WHERE deleted_at IS NULL
        """)
        user_counts = cursor.fetchone()

        # Convert to dict with proper key access
        user_counts_dict = {
            "s1_count": user_counts['s1_count'] or 0,
            "l3_count": user_counts['l3_count'] or 0,
            "l2_count": user_counts['l2_count'] or 0,
            "l1_count": user_counts['l1_count'] or 0,
            "module_count": user_counts['module_count'] or 0,
            "total_count": user_counts['total_count'] or 0
        }
        
        cursor.close()
    
    # Record dashboard access
    record_audit_log(cu, "view_dashboard", "admin", "Accessed admin dashboard")
    
    return render_template("admin/dashboard.html",
                        active="admin",
                        page="dashboard",
                        user_level=user_level,
                        stats=stats,
                        deletion_requests=deletion_requests,
                        recent_critical=recent_critical,
                        pending_deletions=pending_deletions,
                        user_counts=user_counts_dict)


@admin_bp.route("/audit")
@login_required
@require_admin_level("L1")
def audit_logs():
    """
    View and filter audit logs - INSTANCE-AWARE

    L1:    See only logs from users in their own instance.
    L2:    See logs for all their accessible instances.
    L3/S1: Redirected to Horizon Global Audits.
    """
    cu = current_user()
    cu_level = get_user_permission_level(cu)

    # L3/S1 should use Horizon
    if cu_level in ['L3', 'S1']:
        flash("Please use Horizon Global Audits for cross-instance audit logs.", "info")
        return redirect(url_for('horizon.global_audits'))
    
    # Get instance context
    from app.core.instance_context import get_current_instance
    try:
        current_instance_id = get_current_instance()
    except RuntimeError:
        current_instance_id = cu.get('instance_id')
    
    # L1 - only their instance
    if cu_level == 'L1':
        accessible_instances = [current_instance_id] if current_instance_id else []
    
    # L2 - their accessible instances
    elif cu_level == 'L2':
        from app.core.instance_access import get_user_instances
        accessible_instances = [inst['id'] for inst in get_user_instances(cu)]
    
    else:
        accessible_instances = []
    
    if not accessible_instances:
        flash("No accessible instances found.", "warning")
        return redirect(url_for('admin.dashboard'))
    
    # Get selected instance from query params
    selected_instance_id = request.args.get('instance_id', type=int)
    if selected_instance_id not in accessible_instances:
        selected_instance_id = accessible_instances[0]
    
    # Get filters from query params
    filters = {
        "username": request.args.get("username", ""),
        "action": request.args.get("action", ""),
        "module": request.args.get("module", ""),
        "date_from": request.args.get("date_from", ""),
        "date_to": request.args.get("date_to", ""),
        "permission_level": request.args.get("permission_level", "")
    }
    
    # Remove empty filters
    filters = {k: v for k, v in filters.items() if v}
    
    # Query logs for THIS INSTANCE ONLY
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        # CRITICAL: Get logs from users in this instance
        # OR logs by L3/S1 that have target context in this instance
        query = """
            SELECT
                al.id,
                al.ts_utc,
                al.user_id,
                al.username,
                al.action,
                al.module,
                al.details,
                al.permission_level,
                al.ip_address,
                al.target_user_id,
                al.target_username,
                COALESCE(al.instance_id, u.instance_id) as user_instance_id,
                u.permission_level as user_perm_level
            FROM audit_logs al
            LEFT JOIN users u ON al.user_id = u.id
            WHERE (
                -- Logs explicitly tagged to this instance
                al.instance_id = %s

                -- OR logs from users whose home instance is this one
                OR (al.instance_id IS NULL AND u.instance_id = %s)

                -- OR actions by L3/S1 users whose target_user belongs to this instance
                OR (
                    al.permission_level IN ('L3', 'S1')
                    AND al.target_user_id IN (
                        SELECT id FROM users WHERE instance_id = %s
                    )
                )
            )
        """
        params = [selected_instance_id, selected_instance_id, selected_instance_id]
        
        # Apply additional filters
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
            query += " AND DATE(al.ts_utc) >= %s"
            params.append(filters["date_from"])
        
        if filters.get("date_to"):
            query += " AND DATE(al.ts_utc) <= %s"
            params.append(filters["date_to"])
        
        if filters.get("permission_level"):
            query += " AND al.permission_level = %s"
            params.append(filters["permission_level"])
        
        query += " ORDER BY al.ts_utc DESC LIMIT 500"
        
        cursor.execute(query, params)
        logs = cursor.fetchall()
        
        # Get available modules and actions for filter dropdowns (instance-specific)
        cursor.execute("""
            SELECT DISTINCT al.module
            FROM audit_logs al
            LEFT JOIN users u ON al.user_id = u.id
            WHERE u.instance_id = %s
              AND al.module IS NOT NULL
            ORDER BY al.module
        """, (selected_instance_id,))
        modules = [row['module'] for row in cursor.fetchall()]

        cursor.execute("""
            SELECT DISTINCT al.action
            FROM audit_logs al
            LEFT JOIN users u ON al.user_id = u.id
            WHERE u.instance_id = %s
              AND al.action IS NOT NULL
            ORDER BY al.action
        """, (selected_instance_id,))
        actions = [row['action'] for row in cursor.fetchall()]
        
        # Get instance info for dropdown
        cursor.execute("""
            SELECT id, name, display_name
            FROM instances
            WHERE id = ANY(%s)
            ORDER BY name
        """, (accessible_instances,))
        instances = cursor.fetchall()
        
        cursor.close()
    
    # Record audit log access
    record_audit_log(cu, "view_audit_logs", "admin", 
                    f"Viewed audit logs for instance {selected_instance_id} with filters: {filters}")
    
    return render_template("admin/audit_logs.html",
                         active="admin",
                         page="audit",
                         logs=logs,
                         filters=filters,
                         modules=modules,
                         actions=actions,
                         instances=instances,
                         selected_instance_id=selected_instance_id)


@admin_bp.route("/audit/export")
@login_required
@require_admin_level("L2")
def export_audit_logs():
    """Export audit logs as CSV - INSTANCE-AWARE."""
    cu = current_user()
    cu_level = get_user_permission_level(cu)
    
    # Get instance context
    from app.core.instance_context import get_current_instance
    try:
        current_instance_id = get_current_instance()
    except RuntimeError:
        current_instance_id = cu.get('instance_id')
    
    # L1 - only their instance
    if cu_level == 'L1':
        accessible_instances = [current_instance_id] if current_instance_id else []
    
    # L2 - their accessible instances
    elif cu_level == 'L2':
        from app.core.instance_access import get_user_instances
        accessible_instances = [inst['id'] for inst in get_user_instances(cu)]
    
    else:
        flash("Please use Horizon for global audit exports.", "info")
        return redirect(url_for('horizon.export_audits'))
    
    # Get selected instance
    selected_instance_id = request.args.get('instance_id', type=int)
    if selected_instance_id not in accessible_instances:
        selected_instance_id = accessible_instances[0] if accessible_instances else None
    
    if not selected_instance_id:
        flash("No instance selected.", "warning")
        return redirect(url_for('admin.audit_logs'))
    
    # Get filters from query params
    filters = {
        "username": request.args.get("username", ""),
        "action": request.args.get("action", ""),
        "module": request.args.get("module", ""),
        "date_from": request.args.get("date_from", ""),
        "date_to": request.args.get("date_to", ""),
        "permission_level": request.args.get("permission_level", "")
    }
    filters = {k: v for k, v in filters.items() if v}
    
    # Query logs for THIS INSTANCE ONLY (same logic as audit_logs view)
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        query = """
            SELECT
                al.ts_utc,
                al.user_id,
                al.username,
                al.permission_level,
                al.action,
                al.module,
                al.details,
                al.target_user_id,
                al.target_username,
                al.ip_address,
                al.user_agent,
                al.session_id
            FROM audit_logs al
            LEFT JOIN users u ON al.user_id = u.id
            WHERE (
                al.instance_id = %s
                OR (al.instance_id IS NULL AND u.instance_id = %s)
                OR (
                    al.permission_level IN ('L3', 'S1')
                    AND al.target_user_id IN (
                        SELECT id FROM users WHERE instance_id = %s
                    )
                )
            )
        """
        params = [selected_instance_id, selected_instance_id, selected_instance_id]
        
        # Apply filters (same as audit_logs view)
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
            query += " AND DATE(al.ts_utc) >= %s"
            params.append(filters["date_from"])
        
        if filters.get("date_to"):
            query += " AND DATE(al.ts_utc) <= %s"
            params.append(filters["date_to"])
        
        if filters.get("permission_level"):
            query += " AND al.permission_level = %s"
            params.append(filters["permission_level"])
        
        query += " ORDER BY al.ts_utc DESC LIMIT 10000"
        
        cursor.execute(query, params)
        logs = cursor.fetchall()
        cursor.close()
    
    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        "Timestamp", "User ID", "Username", "Permission Level",
        "Action", "Module", "Details", 
        "Target User ID", "Target Username",
        "IP Address", "User Agent", "Session ID"
    ])
    
    # Data rows
    for log in logs:
        writer.writerow([
            log['ts_utc'],
            log['user_id'],
            log['username'],
            log.get('permission_level', ''),
            log['action'],
            log['module'],
            log.get('details', ''),
            log.get('target_user_id', ''),
            log.get('target_username', ''),
            log.get('ip_address', ''),
            log.get('user_agent', '')[:100],
            log.get('session_id', '')
        ])
    
    # Record export
    record_audit_log(cu, "export_audit_logs", "admin", 
                    f"Exported {len(logs)} audit logs for instance {selected_instance_id}")
    
    # Return CSV
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=audit_logs_instance_{selected_instance_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        }
    )


@admin_bp.route("/deletion-request/<int:request_id>/approve", methods=["POST"])
@login_required
@require_admin_level("L1")
def approve_deletion_request(request_id: int):
    """Approve a user deletion request."""
    cu = current_user()
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        # Get the request
        cursor.execute("""
            SELECT dr.user_id, u.username
            FROM deletion_requests dr
            JOIN users u ON dr.user_id = u.id
            WHERE dr.id = %s AND dr.status = 'pending'
        """, (request_id,))
        req = cursor.fetchone()
        
        if not req:
            flash("Deletion request not found or already processed.", "warning")
            return redirect(url_for("admin.dashboard"))
        
        user_id = req['user_id']
        username = req['username']
        
        # Approve and delete user
        cursor.execute("""
            UPDATE deletion_requests
            SET status = 'approved',
                approved_by = %s,
                approved_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (cu['id'], request_id))
        
        cursor.execute("""
            UPDATE users
            SET deleted_at = CURRENT_TIMESTAMP,
                deletion_approved_by = %s
            WHERE id = %s
        """, (cu['id'], user_id))
        
        conn.commit()
        cursor.close()
    
    record_audit_log(cu, "approve_deletion", "admin", 
                    f"Approved deletion of user {username} (ID: {user_id})")
    
    flash(f"User '{username}' has been deleted.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/deletion-request/<int:request_id>/reject", methods=["POST"])
@login_required
@require_admin_level("L1")
def reject_deletion_request(request_id: int):
    """Reject a user deletion request."""
    cu = current_user()
    reason = request.form.get("reason", "")
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT dr.user_id, u.username
            FROM deletion_requests dr
            JOIN users u ON dr.user_id = u.id
            WHERE dr.id = %s AND dr.status = 'pending'
        """, (request_id,))
        req = cursor.fetchone()
        
        if not req:
            flash("Deletion request not found or already processed.", "warning")
            return redirect(url_for("admin.dashboard"))
        
        username = req['username']
        
        cursor.execute("""
            UPDATE deletion_requests
            SET status = 'rejected',
                approved_by = %s,
                approved_at = CURRENT_TIMESTAMP,
                rejection_reason = %s
            WHERE id = %s
        """, (cu['id'], reason, request_id))
        
        conn.commit()
        cursor.close()
    
    record_audit_log(cu, "reject_deletion", "admin", 
                    f"Rejected deletion of user {username}: {reason}")
    
    flash(f"Deletion request for '{username}' has been rejected.", "info")
    return redirect(url_for("admin.dashboard"))


# ---------- API Endpoints ----------

@admin_bp.route("/api/stats")
@login_required
@require_admin_level("L1")
def api_stats():
    """Get system statistics as JSON."""
    stats = get_audit_statistics(30)
    return jsonify(stats)


@admin_bp.route("/api/audit-logs")
@login_required
@require_admin_level("L2")
def api_audit_logs():
    """Get audit logs as JSON."""
    filters = request.args.to_dict()
    logs = query_audit_logs(filters, limit=100)
    
    # Convert to JSON-serializable format
    logs_data = []
    for log in logs:
        log_dict = dict(log)
        # Convert datetime to string
        if log_dict.get('ts_utc'):
            log_dict['ts_utc'] = log_dict['ts_utc'].isoformat()
        logs_data.append(log_dict)
    
    return jsonify(logs_data)


# ---------- User Inquiries ----------

REQUEST_TYPE_LABELS = {
    'password_reset': 'Password Reset',
    'profile_adjustment': 'Profile Adjustment',
    'account_deletion': 'Account Deletion',
    'elevation_request': 'Elevation Request',
    'module_access_request': 'Module Access Request',
}


@admin_bp.route("/inquiries")
@login_required
@require_admin_level("L1")
def inquiries():
    """User Inquiries tab — view all pending user requests for this instance."""
    cu = current_user()
    try:
        instance_id = get_current_instance()
    except RuntimeError:
        instance_id = cu.get('instance_id')

    status_filter = request.args.get('status', 'pending')

    with get_db_connection("core") as conn:
        cursor = conn.cursor()

        query = "SELECT * FROM user_inquiries WHERE instance_id = %s"
        params = [instance_id]

        if status_filter and status_filter != 'all':
            query += " AND status = %s"
            params.append(status_filter)

        query += " ORDER BY submitted_at DESC LIMIT 200"
        cursor.execute(query, params)
        inquiry_list = [dict(r) for r in cursor.fetchall()]

        cursor.execute("""
            SELECT COUNT(*) as count FROM user_inquiries
            WHERE instance_id = %s AND status = 'pending'
        """, (instance_id,))
        pending_count = cursor.fetchone()['count']
        cursor.close()

    record_audit_log(cu, "view_inquiries", "admin", "Viewed User Inquiries tab")

    return render_template(
        "admin/inquiries.html",
        active="admin",
        page="inquiries",
        inquiries=inquiry_list,
        status_filter=status_filter,
        pending_count=pending_count,
        request_type_labels=REQUEST_TYPE_LABELS,
        instance_id=instance_id,
    )


@admin_bp.route("/inquiries/<int:inquiry_id>/review", methods=["POST"])
@login_required
@require_admin_level("L1")
def review_inquiry(inquiry_id):
    """Approve or deny a user inquiry."""
    cu = current_user()
    try:
        instance_id = get_current_instance()
    except RuntimeError:
        instance_id = cu.get('instance_id')

    data = request.get_json() or {}
    action = data.get('action', '')
    reason = (data.get('reason') or '').strip()

    if action not in ('approve', 'deny'):
        return jsonify({"error": "Invalid action"}), 400

    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM user_inquiries WHERE id = %s AND instance_id = %s",
            (inquiry_id, instance_id)
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Inquiry not found"}), 404

        inquiry = dict(row)
        if inquiry['status'] != 'pending':
            return jsonify({"error": "This inquiry has already been reviewed"}), 409

        new_status = 'approved' if action == 'approve' else 'denied'
        cursor.execute("""
            UPDATE user_inquiries
            SET status = %s,
                reviewed_by = %s,
                reviewer_username = %s,
                review_reason = %s,
                reviewed_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (new_status, cu['id'], cu['username'], reason or None, inquiry_id))
        cursor.close()

    cu_level = get_user_permission_level(cu) or ''
    action_label = 'Approved' if action == 'approve' else 'Denied'
    req_label = REQUEST_TYPE_LABELS.get(inquiry['request_type'], inquiry['request_type'])
    detail = (f"User Change Request {action_label} — {req_label} for {inquiry['username']}"
              + (f" — Reason: {reason}" if reason else ""))
    record_audit_log(cu, "inquiry_review", "admin", detail,
                     target_user_id=inquiry['user_id'],
                     target_username=inquiry['username'])

    # Send email notification
    from app.modules.admin.emails import send_inquiry_reviewed, send_password_reset_link
    user_email = inquiry.get('email', '')

    if action == 'approve' and inquiry['request_type'] == 'password_reset':
        # Generate a one-time reset token (1-hour expiry) and email the link
        import secrets
        from datetime import datetime, timedelta
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=1)
        with get_db_connection("core") as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO password_reset_tokens
                    (user_id, username, token, inquiry_id, expires_at)
                VALUES (%s, %s, %s, %s, %s)
            """, (inquiry['user_id'], inquiry['username'], token, inquiry_id, expires_at))
            cur.close()
        reset_url = url_for('auth.reset_password', token=token, _external=True)
        send_password_reset_link(user_email, inquiry['username'], reset_url,
                                 first_name=inquiry.get('first_name', ''))
    else:
        send_inquiry_reviewed(user_email, inquiry['username'],
                              inquiry['request_type'], action, reason or None,
                              first_name=inquiry.get('first_name', ''),
                              last_name=inquiry.get('last_name', ''))

    return jsonify({"success": True})