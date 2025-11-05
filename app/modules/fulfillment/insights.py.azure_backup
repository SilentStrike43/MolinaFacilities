# app/modules/fulfillment/insights.py
import csv
import io
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, send_file, flash, redirect, url_for

from app.modules.auth.security import login_required, current_user, record_audit, get_user_location, should_filter_by_location
from app.core.database import get_db_connection

fulfillment_insights_bp = Blueprint("fulfillment_insights", __name__, url_prefix="/fulfillment/insights")

def can_view_fulfillment_insights(user):
    """Check if user can view fulfillment insights (M3C or admin)."""
    if not user:
        return False
    
    # Check permission level (L1+ can access)
    permission_level = user.get('permission_level', '')
    if permission_level in ['L1', 'L2', 'L3', 'S1']:
        return True
    
    # Check module permissions for M3C
    try:
        import json
        module_perms = json.loads(user.get('module_permissions', '[]') or '[]')
        if 'M3C' in module_perms:
            return True
    except:
        pass
    
    return False

@fulfillment_insights_bp.route("/", methods=["GET"])
@login_required
def insights():
    """Fulfillment insights with comprehensive filtering (M3C+ only)."""
    cu = current_user()
    
    if not can_view_fulfillment_insights(cu):
        flash("You need M3C (Fulfillment Manager) permissions or higher to access Fulfillment Insights.", "danger")
        return redirect(url_for("home.index"))
    
    # Get filter parameters
    order_number = request.args.get("order_number", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    requester_name = request.args.get("requester_name", "")
    page_count_min = request.args.get("page_count_min", "")
    page_count_max = request.args.get("page_count_max", "")
    completed_by = request.args.get("completed_by", "")
    location = request.args.get("location", "")
    
    # Default date range: last 90 days
    if not date_from:
        date_from = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")
    
    # Check if user should be filtered by location
    should_filter, user_location = should_filter_by_location(cu)
    
    # Build query
    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()
        
        query = """
            SELECT 
                fr.id,
                fr.date_submitted,
                fr.requester_name,
                fr.description,
                fr.total_pages,
                fr.assigned_staff_name,
                fr.completed_at,
                sr.location
            FROM fulfillment_requests fr
            LEFT JOIN service_requests sr ON fr.id = sr.id
            WHERE fr.is_archived = 1
            AND CAST(fr.date_submitted AS DATE) >= ? 
            AND CAST(fr.date_submitted AS DATE) <= ?
        """
        params = [date_from, date_to]
        
        # Apply location filter if needed
        if should_filter and user_location:
            query += " AND sr.location = ?"
            params.append(user_location)
        elif location:
            query += " AND sr.location = ?"
            params.append(location)
        
        # Apply other filters
        if order_number:
            query += " AND fr.id = ?"
            params.append(int(order_number))
        
        if requester_name:
            query += " AND fr.requester_name LIKE ?"
            params.append(f"%{requester_name}%")
        
        if page_count_min:
            query += " AND fr.total_pages >= ?"
            params.append(int(page_count_min))
        
        if page_count_max:
            query += " AND fr.total_pages <= ?"
            params.append(int(page_count_max))
        
        if completed_by:
            query += " AND fr.assigned_staff_name LIKE ?"
            params.append(f"%{completed_by}%")
        
        query += " ORDER BY fr.date_submitted DESC, fr.id DESC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        # Convert to dicts
        results = []
        total_pages = 0
        for row in rows:
            result = {
                'order_number': row[0],
                'timestamp': row[1],
                'requester_name': row[2],
                'description': row[3],
                'page_count': row[4] or 0,
                'completed_by': row[5],
                'completed_at': row[6],
                'location': row[7]
            }
            results.append(result)
            total_pages += result['page_count']
        
        # Get unique locations for filter dropdown
        cursor.execute("""
            SELECT DISTINCT sr.location 
            FROM service_requests sr
            WHERE sr.location IS NOT NULL 
            ORDER BY sr.location
        """)
        locations = [r[0] for r in cursor.fetchall()]
        
        cursor.close()
    
    # Statistics
    total_orders = len(results)
    avg_pages = total_pages / total_orders if total_orders > 0 else 0
    
    by_location = {}
    for r in results:
        loc = r['location'] or 'Unknown'
        by_location[loc] = by_location.get(loc, 0) + 1
    
    record_audit(cu, "view_fulfillment_insights", "fulfillment", 
                f"Viewed fulfillment insights: {date_from} to {date_to}")
    
    return render_template(
        "fulfillment/insights.html",
        active="fulfillment-insights",
        results=results,
        total_orders=total_orders,
        total_pages=total_pages,
        avg_pages=round(avg_pages, 1),
        by_location=by_location,
        date_from=date_from,
        date_to=date_to,
        order_number=order_number,
        requester_name=requester_name,
        page_count_min=page_count_min,
        page_count_max=page_count_max,
        completed_by=completed_by,
        location=location,
        locations=locations,
        user_location=user_location if should_filter else None
    )

@fulfillment_insights_bp.route("/export")
@login_required
def export():
    """Export fulfillment insights to CSV."""
    cu = current_user()
    
    if not can_view_fulfillment_insights(cu):
        flash("You need M3C permissions or higher to export fulfillment insights.", "danger")
        return redirect(url_for("home.index"))
    
    # Get filter parameters (same as insights view)
    order_number = request.args.get("order_number", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    requester_name = request.args.get("requester_name", "")
    page_count_min = request.args.get("page_count_min", "")
    page_count_max = request.args.get("page_count_max", "")
    completed_by = request.args.get("completed_by", "")
    location = request.args.get("location", "")
    
    # Check if user should be filtered by location
    should_filter, user_location = should_filter_by_location(cu)
    
    # Build query (same as insights view)
    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()
        
        query = """
            SELECT 
                fr.id,
                fr.date_submitted,
                fr.requester_name,
                fr.description,
                fr.total_pages
            FROM fulfillment_requests fr
            LEFT JOIN service_requests sr ON fr.id = sr.id
            WHERE fr.is_archived = 1
        """
        params = []
        
        if date_from:
            query += " AND CAST(fr.date_submitted AS DATE) >= ?"
            params.append(date_from)
        
        if date_to:
            query += " AND CAST(fr.date_submitted AS DATE) <= ?"
            params.append(date_to)
        
        # Apply location filter if needed
        if should_filter and user_location:
            query += " AND sr.location = ?"
            params.append(user_location)
        elif location:
            query += " AND sr.location = ?"
            params.append(location)
        
        if order_number:
            query += " AND fr.id = ?"
            params.append(int(order_number))
        
        if requester_name:
            query += " AND fr.requester_name LIKE ?"
            params.append(f"%{requester_name}%")
        
        if page_count_min:
            query += " AND fr.total_pages >= ?"
            params.append(int(page_count_min))
        
        if page_count_max:
            query += " AND fr.total_pages <= ?"
            params.append(int(page_count_max))
        
        if completed_by:
            query += " AND fr.assigned_staff_name LIKE ?"
            params.append(f"%{completed_by}%")
        
        query += " ORDER BY fr.date_submitted DESC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()
    
    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        "Order Number",
        "Timestamp",
        "Requester Name",
        "Description",
        "Page Count"
    ])
    
    # Data rows
    total_pages = 0
    for row in rows:
        page_count = row[4] or 0
        total_pages += page_count
        writer.writerow([
            row[0],  # order_number
            row[1],  # timestamp
            row[2],  # requester_name
            row[3],  # description
            page_count
        ])
    
    # Total row at bottom
    writer.writerow([])
    writer.writerow(["TOTAL PAGES:", "", "", "", total_pages])
    
    # Record export
    record_audit(cu, "export_fulfillment_insights", "fulfillment", 
                f"Exported fulfillment insights: {len(rows)} orders, {total_pages} pages")
    
    # Return CSV
    output.seek(0)
    mem = io.BytesIO(output.getvalue().encode("utf-8"))
    mem.seek(0)
    
    filename = f"fulfillment_insights_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return send_file(
        mem,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename
    )