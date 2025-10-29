# app/modules/admin/views.py
"""
Updated Admin module with new permission system
Enhanced audit logging and permission management
"""

import json
import csv
import io
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, jsonify

from app.modules.auth.security import (
    login_required, 
    current_user,
)

from app.modules.users.models import get_user_by_id, users_db
from app.modules.users.permissions import PermissionManager, PermissionLevel
from app.core.database import get_db_connection

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
    """Record an audit log entry with enhanced information."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        # Get user's current permission level
        permission_level = get_user_permission_level(user_data) or ""
        
        # Get request metadata
        ip_address = request.remote_addr if request else ""
        user_agent = request.headers.get('User-Agent', '')[:500] if request else ""
        session_id = request.cookies.get('session', '')[:100] if request else ""
        
        cursor.execute("""
            INSERT INTO audit_logs(
                user_id, username, action, module, details,
                target_user_id, target_username, permission_level,
                ip_address, user_agent, session_id, ts_utc
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,GETUTCDATE())
        """, (
            user_data["id"],
            user_data["username"],
            action,
            module,
            details,
            target_user_id,
            target_username,
            permission_level,
            ip_address,
            user_agent,
            session_id
        ))
        conn.commit()
        cursor.close()

def query_audit_logs(filters=None, limit=1000):
    """Query audit logs with filters."""
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        query = "SELECT TOP " + str(limit) + " * FROM audit_logs WHERE 1=1"
        params = []
        
        if filters:
            if filters.get("user_id"):
                query += " AND user_id = ?"
                params.append(filters["user_id"])
            
            if filters.get("username"):
                query += " AND username LIKE ?"
                params.append(f"%{filters['username']}%")
            
            if filters.get("action"):
                query += " AND action LIKE ?"
                params.append(f"%{filters['action']}%")
            
            if filters.get("module"):
                query += " AND module = ?"
                params.append(filters["module"])
            
            if filters.get("date_from"):
                query += " AND CAST(ts_utc AS DATE) >= ?"
                params.append(filters["date_from"])
            
            if filters.get("date_to"):
                query += " AND CAST(ts_utc AS DATE) <= ?"
                params.append(filters["date_to"])
            
            if filters.get("permission_level"):
                query += " AND permission_level = ?"
                params.append(filters["permission_level"])
            
            if filters.get("target_user_id"):
                query += " AND target_user_id = ?"
                params.append(filters["target_user_id"])
        
        query += " ORDER BY ts_utc DESC"
        
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
            "SELECT COUNT(*) FROM audit_logs WHERE CAST(ts_utc AS DATE) >= ?", 
            (cutoff_date,)
        )
        stats["total_actions"] = cursor.fetchone()[0]
        
        # Actions by module
        cursor.execute("""
            SELECT module, COUNT(*) as count
            FROM audit_logs
            WHERE CAST(ts_utc AS DATE) >= ?
            GROUP BY module
            ORDER BY count DESC
        """, (cutoff_date,))
        module_stats = cursor.fetchall()
        stats["by_module"] = {row[0]: row[1] for row in module_stats}
        
        # Actions by permission level
        cursor.execute("""
            SELECT permission_level, COUNT(*) as count
            FROM audit_logs
            WHERE CAST(ts_utc AS DATE) >= ? AND permission_level != ''
            GROUP BY permission_level
            ORDER BY count DESC
        """, (cutoff_date,))
        level_stats = cursor.fetchall()
        stats["by_level"] = {row[0]: row[1] for row in level_stats}
        
        # Most active users
        cursor.execute("""
            SELECT TOP 10 username, COUNT(*) as count
            FROM audit_logs
            WHERE CAST(ts_utc AS DATE) >= ?
            GROUP BY username
            ORDER BY count DESC
        """, (cutoff_date,))
        user_stats = cursor.fetchall()
        stats["top_users"] = [(row[0], row[1]) for row in user_stats]
        
        # Critical actions
        cursor.execute("""
            SELECT COUNT(*) FROM audit_logs
            WHERE CAST(ts_utc AS DATE) >= ? AND action IN (
                'elevate_user', 'demote_user', 'delete_user', 
                'approve_deletion', 'create_user', 'system_config_change'
            )
        """, (cutoff_date,))
        stats["critical_actions"] = cursor.fetchone()[0]
        
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
            SELECT TOP 10 * FROM audit_logs
            WHERE action IN (
                'elevate_user', 'demote_user', 'delete_user', 
                'approve_deletion', 'create_user', 'system_config_change'
            )
            ORDER BY ts_utc DESC
        """)
        recent_critical = cursor.fetchall()
        
        # Get pending deletion requests count
        cursor.execute("""
            SELECT COUNT(*) FROM deletion_requests
            WHERE status = 'pending'
        """)
        pending_deletions = cursor.fetchone()[0]
        
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
            WHERE deleted_at IS NULL OR deleted_at = ''
        """)
        user_counts = cursor.fetchone()
        
        cursor.close()
    
    # Record dashboard access
    record_audit_log(cu, "view_dashboard", "admin", "Accessed admin dashboard")
    
    # Convert user_counts to dict
    user_counts_dict = {
        "s1_count": user_counts[0] or 0,
        "l3_count": user_counts[1] or 0,
        "l2_count": user_counts[2] or 0,
        "l1_count": user_counts[3] or 0,
        "module_count": user_counts[4] or 0,
        "total_count": user_counts[5] or 0
    }
    
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
@require_admin_level("L2")
def audit_logs():
    """View and filter audit logs (L2+ only)."""
    cu = current_user()
    
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
    
    # Query logs
    logs = query_audit_logs(filters, limit=500)
    
    # Get available modules and actions for filter dropdowns
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT module FROM audit_logs ORDER BY module")
        modules_rows = cursor.fetchall()
        cursor.execute("SELECT DISTINCT action FROM audit_logs ORDER BY action")
        actions_rows = cursor.fetchall()
        cursor.close()
    
    # Convert rows to lists - FIX: pyodbc rows are accessed by index
    modules = [row[0] for row in modules_rows]
    actions = [row[0] for row in actions_rows]
    
    # Record audit log access
    record_audit_log(cu, "view_audit_logs", "admin", f"Viewed audit logs with filters: {filters}")
    
    return render_template("admin/audit_logs.html",
                         active="admin",
                         page="audit",
                         logs=logs,
                         filters=filters,
                         modules=modules,
                         actions=actions)

@admin_bp.route("/audit/export")
@login_required
@require_admin_level("L2")
def export_audit_logs():
    """Export audit logs as CSV."""
    cu = current_user()
    
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
    
    # Query logs
    logs = query_audit_logs(filters, limit=10000)
    
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
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        # Get table counts
        cursor.execute("SELECT COUNT(*) FROM users")
        users_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM audit_logs")
        audit_logs_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM deletion_requests")
        deletion_requests_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM user_elevation_history")
        elevation_history_count = cursor.fetchone()[0]
        
        db_stats = {
            "users_count": users_count,
            "audit_logs_count": audit_logs_count,
            "deletion_requests_count": deletion_requests_count,
            "elevation_history_count": elevation_history_count,
        }
        
        # Get table column counts (SQL Server)
        table_info = {}
        tables = ["users", "audit_logs", "deletion_requests", "user_elevation_history"]
        
        for table in tables:
            cursor.execute("""
                SELECT COUNT(*) 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME = ?
            """, (table,))
            result = cursor.fetchone()
            table_info[table] = result[0] if result else 0
        
        cursor.close()
    
    # Record export
    record_audit_log(cu, "export_audit_logs", "admin", f"Exported audit logs with filters: {filters}")
    
    # Return CSV
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=audit_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
    )

@admin_bp.route("/insights")
@login_required
@require_admin_level("L2")
def manage_insights():
    """Manage system insights (L2+ only)."""
    cu = current_user()
    
    # This would integrate with your existing insights system
    # For now, placeholder
    record_audit_log(cu, "view_insights_management", "admin", "Accessed insights management")
    
    return render_template("admin/insights.html",
                         active="admin",
                         page="insights")

@admin_bp.route("/database")
@login_required
@require_admin_level("L2")
def database_management():
    """Database management interface (L2+ only)."""
    cu = current_user()
    user_level = get_user_permission_level(cu)
    
    if user_level not in ["L2", "L3", "S1"]:
        flash("You need L2 (Systems Administrator) permissions or higher to access database management.", "danger")
        return redirect(url_for("admin.dashboard"))
    
    # Get database statistics
    con = users_db()
    
    try:
        cursor = con.cursor()
        
        # Get table counts (works on both SQLite and SQL Server)
        cursor.execute("SELECT COUNT(*) FROM users")
        users_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM audit_logs")
        audit_logs_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM deletion_requests")
        deletion_requests_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM user_elevation_history")
        elevation_history_count = cursor.fetchone()[0]
        
        db_stats = {
            "users_count": users_count,
            "audit_logs_count": audit_logs_count,
            "deletion_requests_count": deletion_requests_count,
            "elevation_history_count": elevation_history_count,
        }
        
        # FIXED: Use SQL Server compatible query instead of PRAGMA
        # Get table column counts (SQL Server compatible)
        table_info = {}
        tables = ["users", "audit_logs", "deletion_requests", "user_elevation_history"]
        
        # Detect if we're using Azure SQL or SQLite
        import os
        use_azure = os.environ.get("DB_CORE_CONNECTION_STRING") is not None
        
        for table in tables:
            if use_azure:
                # SQL Server query
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_NAME = ?
                """, (table,))
            else:
                # SQLite query
                cursor.execute(f"PRAGMA table_info({table})")
            
            result = cursor.fetchone()
            table_info[table] = result[0] if result else 0
        
        cursor.close()
        
    finally:
        # Only close if not using Azure SQL (which uses connection pooling)
        import os
        if not os.environ.get("DB_CORE_CONNECTION_STRING"):
            con.close()
    
    record_audit_log(cu, "view_database_management", "admin", "Accessed database management interface")
    
    return render_template("admin/database.html",
                         active="admin",
                         page="database",
                         db_stats=db_stats,
                         table_info=table_info,
                         user_level=user_level)

@admin_bp.route("/system")
@login_required
@require_admin_level("L3")
def system_management():
    """System management interface (L3+ only)."""
    cu = current_user()
    user_level = get_user_permission_level(cu)
    
    if user_level not in ["L3", "S1"]:
        flash("You need L3 (App Developer) permissions or higher to access system management.", "danger")
        return redirect(url_for("admin.dashboard"))
    
    # System information would go here
    # This is where Azure VM, SSH, cert management would be integrated
    
    record_audit_log(cu, "view_system_management", "admin", "Accessed system management interface")
    
    return render_template("admin/system.html",
                         active="admin",
                         page="system",
                         user_level=user_level)

@admin_bp.route("/config", methods=["GET", "POST"])
@login_required
@require_admin_level("L2")
def system_config():
    """System configuration (L2+ only)."""
    cu = current_user()
    
    if request.method == "POST":
        # Handle configuration updates
        config_data = request.get_json()
        
        # Save configuration (implement based on your config storage)
        # For now, just log the action
        record_audit_log(
            cu, 
            "system_config_change", 
            "admin",
            f"Updated system configuration: {json.dumps(config_data)}"
        )
        
        return jsonify({"success": True, "message": "Configuration updated"})
    
    # Load current configuration
    config = {}  # Load your actual configuration here
    
    return render_template("admin/config.html",
                         active="admin",
                         page="config",
                         config=config)

@admin_bp.route("/elevation-history")
@login_required
@require_admin_level("L1")
def elevation_history():
    """View user elevation history."""
    cu = current_user()
    
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT TOP 100
                eh.*,
                u1.username as user_username,
                u2.username as elevated_by_username
            FROM user_elevation_history eh
            JOIN users u1 ON eh.user_id = u1.id
            JOIN users u2 ON eh.elevated_by = u2.id
            ORDER BY eh.elevated_at DESC
        """)
        history = cursor.fetchall()
        cursor.close()
    
    return render_template("admin/elevation_history.html",
                         active="admin",
                         page="elevation_history",
                         history=history)

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
            WHERE dr.id = ? AND dr.status = 'pending'
        """, (request_id,))
        req = cursor.fetchone()
        
        if not req:
            flash("Deletion request not found or already processed.", "warning")
            return redirect(url_for("admin.dashboard"))
        
        user_id, username = req[0], req[1]
        
        # Approve and delete user
        cursor.execute("""
            UPDATE deletion_requests
            SET status = 'approved',
                approved_by = ?,
                approved_at = GETUTCDATE()
            WHERE id = ?
        """, (cu['id'], request_id))
        
        cursor.execute("""
            UPDATE users
            SET deleted_at = GETUTCDATE(),
                deletion_approved_by = ?
            WHERE id = ?
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
            WHERE dr.id = ? AND dr.status = 'pending'
        """, (request_id,))
        req = cursor.fetchone()
        
        if not req:
            flash("Deletion request not found or already processed.", "warning")
            return redirect(url_for("admin.dashboard"))
        
        username = req[1]
        
        cursor.execute("""
            UPDATE deletion_requests
            SET status = 'rejected',
                approved_by = ?,
                approved_at = GETUTCDATE(),
                rejection_reason = ?
            WHERE id = ?
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
        logs_data.append(dict(log))
    
    return jsonify(logs_data)