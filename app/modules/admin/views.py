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
                return redirect(url_for("home"))
            
            # Check if user has required level
            level_hierarchy = {"L1": 1, "L2": 2, "L3": 3, "S1": 4}
            required = level_hierarchy.get(min_level, 0)
            actual = level_hierarchy.get(user_level, 0)
            
            if actual < required:
                flash(f"You need {min_level} permissions or higher to access this area.", "danger")
                return redirect(url_for("home"))
            
            return f(*args, **kwargs)
        wrapped.__name__ = f.__name__
        return wrapped
    return decorator

# ---------- Audit Log Functions ----------
def record_audit_log(user_data, action, module, details, 
                     target_user_id=None, target_username=None):
    """Record an audit log entry with enhanced information."""
    con = users_db()
    
    # Get user's current permission level
    permission_level = get_user_permission_level(user_data) or ""
    
    # Get request metadata
    ip_address = request.remote_addr if request else ""
    user_agent = request.headers.get('User-Agent', '')[:500] if request else ""
    session_id = request.cookies.get('session', '')[:100] if request else ""
    
    con.execute("""
        INSERT INTO audit_logs(
            user_id, username, action, module, details,
            target_user_id, target_username, permission_level,
            ip_address, user_agent, session_id, ts_utc
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
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
        session_id,
        datetime.utcnow().isoformat() + "Z"
    ))
    con.commit()
    con.close()

def query_audit_logs(filters=None, limit=1000):
    """Query audit logs with filters."""
    con = users_db()
    
    query = "SELECT * FROM audit_logs WHERE 1=1"
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
            query += " AND date(ts_utc) >= date(?)"
            params.append(filters["date_from"])
        
        if filters.get("date_to"):
            query += " AND date(ts_utc) <= date(?)"
            params.append(filters["date_to"])
        
        if filters.get("permission_level"):
            query += " AND permission_level = ?"
            params.append(filters["permission_level"])
        
        if filters.get("target_user_id"):
            query += " AND target_user_id = ?"
            params.append(filters["target_user_id"])
    
    query += f" ORDER BY ts_utc DESC LIMIT {limit}"
    
    rows = con.execute(query, params).fetchall()
    con.close()
    return rows

def get_audit_statistics(days=30):
    """Get audit log statistics for dashboard."""
    con = users_db()
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
    
    stats = {}
    
    # Total actions
    stats["total_actions"] = con.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE ts_utc >= ?", (cutoff,)
    ).fetchone()[0]
    
    # Actions by module
    module_stats = con.execute("""
        SELECT module, COUNT(*) as count
        FROM audit_logs
        WHERE ts_utc >= ?
        GROUP BY module
        ORDER BY count DESC
    """, (cutoff,)).fetchall()
    stats["by_module"] = {row["module"]: row["count"] for row in module_stats}
    
    # Actions by permission level
    level_stats = con.execute("""
        SELECT permission_level, COUNT(*) as count
        FROM audit_logs
        WHERE ts_utc >= ? AND permission_level != ''
        GROUP BY permission_level
        ORDER BY count DESC
    """, (cutoff,)).fetchall()
    stats["by_level"] = {row["permission_level"]: row["count"] for row in level_stats}
    
    # Most active users
    user_stats = con.execute("""
        SELECT username, COUNT(*) as count
        FROM audit_logs
        WHERE ts_utc >= ?
        GROUP BY username
        ORDER BY count DESC
        LIMIT 10
    """, (cutoff,)).fetchall()
    stats["top_users"] = [(row["username"], row["count"]) for row in user_stats]
    
    # Critical actions (elevations, deletions, etc.)
    stats["critical_actions"] = con.execute("""
        SELECT COUNT(*) FROM audit_logs
        WHERE ts_utc >= ? AND action IN (
            'elevate_user', 'demote_user', 'delete_user', 
            'approve_deletion', 'create_user', 'system_config_change'
        )
    """, (cutoff,)).fetchone()[0]
    
    con.close()
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
    
    # Get recent critical actions
    con = users_db()
    recent_critical = con.execute("""
        SELECT * FROM audit_logs
        WHERE action IN (
            'elevate_user', 'demote_user', 'delete_user', 
            'approve_deletion', 'create_user', 'system_config_change'
        )
        ORDER BY ts_utc DESC
        LIMIT 10
    """).fetchall()
    
    # Get pending deletion requests count
    pending_deletions = con.execute("""
        SELECT COUNT(*) FROM deletion_requests
        WHERE status = 'pending'
    """).fetchone()[0]
    
    # Get user counts by permission level
    user_counts = con.execute("""
        SELECT 
            SUM(CASE WHEN permission_level = 'S1' THEN 1 ELSE 0 END) as s1_count,
            SUM(CASE WHEN permission_level = 'L3' THEN 1 ELSE 0 END) as l3_count,
            SUM(CASE WHEN permission_level = 'L2' THEN 1 ELSE 0 END) as l2_count,
            SUM(CASE WHEN permission_level = 'L1' THEN 1 ELSE 0 END) as l1_count,
            SUM(CASE WHEN permission_level = '' OR permission_level IS NULL THEN 1 ELSE 0 END) as module_count,
            COUNT(*) as total_count
        FROM users
        WHERE deleted_at IS NULL OR deleted_at = ''
    """).fetchone()
    
    con.close()
    
    # Record dashboard access
    record_audit_log(cu, "view_dashboard", "admin", "Accessed admin dashboard")
    
    return render_template("admin/dashboard.html",
                         active="admin",
                         page="dashboard",
                         user_level=user_level,
                         stats=stats,
                         recent_critical=recent_critical,
                         pending_deletions=pending_deletions,
                         user_counts=dict(user_counts))

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
    con = users_db()
    modules = con.execute("SELECT DISTINCT module FROM audit_logs ORDER BY module").fetchall()
    actions = con.execute("SELECT DISTINCT action FROM audit_logs ORDER BY action").fetchall()
    con.close()
    
    # Record audit log access
    record_audit_log(cu, "view_audit_logs", "admin", f"Viewed audit logs with filters: {filters}")
    
    return render_template("admin/audit_logs.html",
                         active="admin",
                         page="audit",
                         logs=logs,
                         filters=filters,
                         modules=[m["module"] for m in modules],
                         actions=[a["action"] for a in actions])

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
    for log in logs:
        writer.writerow([
            log["ts_utc"],
            log["user_id"],
            log["username"],
            log["permission_level"],
            log["action"],
            log["module"],
            log["details"],
            log["target_user_id"],
            log["target_username"],
            log["ip_address"],
            log["user_agent"],
            log["session_id"]
        ])
    
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
    
    db_stats = {
        "users_count": con.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "audit_logs_count": con.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0],
        "deletion_requests_count": con.execute("SELECT COUNT(*) FROM deletion_requests").fetchone()[0],
        "elevation_history_count": con.execute("SELECT COUNT(*) FROM user_elevation_history").fetchone()[0],
    }
    
    # Get table sizes (approximate)
    tables = ["users", "audit_logs", "deletion_requests", "user_elevation_history"]
    table_info = {}
    for table in tables:
        info = con.execute(f"PRAGMA table_info({table})").fetchall()
        table_info[table] = len(info)  # Number of columns
    
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
    
    con = users_db()
    history = con.execute("""
        SELECT 
            eh.*,
            u1.username as user_username,
            u2.username as elevated_by_username
        FROM user_elevation_history eh
        JOIN users u1 ON eh.user_id = u1.id
        JOIN users u2 ON eh.elevated_by = u2.id
        ORDER BY eh.ts_utc DESC
        LIMIT 100
    """).fetchall()
    con.close()
    
    return render_template("admin/elevation_history.html",
                         active="admin",
                         page="elevation_history",
                         history=history)

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