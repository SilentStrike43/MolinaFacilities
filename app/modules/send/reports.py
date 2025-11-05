# app/modules/send/reports.py
from flask import render_template, request, send_file
import csv
import io
import datetime
from . import bp
from app.modules.auth.security import require_cap, current_user, record_audit, should_filter_by_location
from app.core.database import get_db_connection

@bp.route("/insights", endpoint="insights")
@require_cap("can_send")
def reports():
    """Send insights with date range filtering and enhanced metrics."""
    cu = current_user()
    
    # Get filter parameters
    q = request.args.get("q", "").strip()
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    item_type = request.args.get("item_type", "")
    location_filter = request.args.get("location", "")
    
    # Default date range: last 30 days
    if not date_from:
        date_from = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    if not date_to:
        date_to = datetime.date.today().isoformat()
    
    # Check if user should be filtered by location
    should_filter, user_location = should_filter_by_location(cu)
    
    # Build query with PostgreSQL
    with get_db_connection("send") as conn:
        cursor = conn.cursor()
        
        sql = """
            SELECT 
                ts_utc,
                package_type,
                recipient_name,
                recipient_address,
                tracking_number,
                carrier,
                submitter_name,
                location,
                notes,
                checkin_id,
                package_id,
                checkin_date
            FROM package_manifest
            WHERE DATE(checkin_date) >= %s 
            AND DATE(checkin_date) <= %s
        """
        params = [date_from, date_to]

        # Apply location filter if user is restricted
        if should_filter and user_location:
            sql += " AND location = %s"
            params.append(user_location)
        elif location_filter:
            sql += " AND location = %s"
            params.append(location_filter)

        # Apply search filter
        if q:
            sql += " AND (tracking_number LIKE %s OR recipient_name LIKE %s OR package_type LIKE %s)"
            like = f"%{q}%"
            params.extend([like, like, like])

        # Apply package type filter
        if item_type:
            sql += " AND package_type = %s"
            params.append(item_type)
        
        sql += " ORDER BY ts_utc DESC"
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        
        # Convert to list of dicts
        results = [dict(row) for row in rows]
        
        # Get unique package types for dropdown
        cursor.execute("SELECT DISTINCT package_type FROM package_manifest WHERE package_type IS NOT NULL ORDER BY package_type")
        package_types = [r['package_type'] for r in cursor.fetchall()]
        
        # Get unique locations for dropdown
        cursor.execute("SELECT DISTINCT location FROM package_manifest WHERE location IS NOT NULL ORDER BY location")
        locations = [r['location'] for r in cursor.fetchall()]
        
        cursor.close()
    
    # Statistics
    total_packages = len(results)
    by_type = {}
    by_location = {}
    for r in results:
        pkg_type = r.get('package_type') or 'Unknown'
        by_type[pkg_type] = by_type.get(pkg_type, 0) + 1
        
        loc = r.get('location') or 'Unknown'
        by_location[loc] = by_location.get(loc, 0) + 1
    
    record_audit(cu, "view_send_insights", "send", f"Viewed send insights: {date_from} to {date_to}")
    
    return render_template(
        "send/insights.html",
        active="send-insights",
        rows=results,
        q=q,
        date_from=date_from,
        date_to=date_to,
        item_type=item_type,
        location_filter=location_filter,
        package_types=package_types,
        locations=locations,
        user_location=user_location if should_filter else None,
        total_packages=total_packages,
        by_type=by_type,
        by_location=by_location
    )

@bp.get("/insights/export")
@require_cap("can_send")
def export():
    """Export send insights to CSV with new metric format."""
    cu = current_user()
    
    # Get filter parameters
    q = request.args.get("q", "").strip()
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    item_type = request.args.get("item_type", "")
    location_filter = request.args.get("location", "")
    
    # Check if user should be filtered by location
    should_filter, user_location = should_filter_by_location(cu)
    
    # Build query (same as reports view)
    with get_db_connection("send") as conn:
        cursor = conn.cursor()
        
        sql = """
            SELECT 
                ts_utc,
                package_type,
                recipient_name,
                recipient_address,
                tracking_number,
                submitter_name,
                location
            FROM package_manifest
            WHERE 1=1
        """
        params = []
        
        if date_from:
            sql += " AND DATE(checkin_date) >= %s"
            params.append(date_from)
        
        if date_to:
            sql += " AND DATE(checkin_date) <= %s"
            params.append(date_to)
        
        # Apply location filter
        if should_filter and user_location:
            sql += " AND location = %s"
            params.append(user_location)
        elif location_filter:
            sql += " AND location = %s"
            params.append(location_filter)
        
        if q:
            sql += " AND (tracking_number LIKE %s OR recipient_name LIKE ? OR package_type LIKE ?)"
            like = f"%{q}%"
            params.extend([like, like, like])
        
        if item_type:
            sql += " AND package_type = %s"
            params.append(item_type)
        
        sql += " ORDER BY ts_utc DESC"
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()
    
    # Create CSV with new metric format
    buf = io.StringIO()
    w = csv.writer(buf)
    
    # Header row with required metrics
    w.writerow([
        "Timestamp",
        "Item Type",
        "Recipient Name",
        "Recipient Address",
        "Tracking Number",
        "Submitted By",
        "Location of Origin"
    ])
    
    # Data rows
    results = []
    for row in rows:
        results.append({
            'ts_utc': row['ts_utc'],
            'checkin_id': row['checkin_id'],
            'package_id': row['package_id'],
            'tracking_number': row['tracking_number'],
            'recipient_name': row['recipient_name'],
            'recipient_address': row['recipient_address'],
            'package_type': row['package_type'],
            'carrier': row['carrier'],
            'weight_oz': row['weight_oz'],
            'length': row['length'],
            'width': row['width'],
            'height': row['height'],
            'location': row['location'],
            'submitter_name': row['submitter_name'],
            'notes': row['notes']
        })
    
    record_audit(cu, "export_send_insights", "send", f"Exported {len(rows)} send records")
    
    # Return CSV
    data = io.BytesIO(buf.getvalue().encode("utf-8"))
    filename = f"send_insights_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return send_file(data, mimetype="text/csv", as_attachment=True, download_name=filename)