# app/modules/send/reports.py
from flask import render_template, request, send_file
import csv
import io
import datetime
from . import bp
from app.modules.auth.security import require_cap, current_user, record_audit
from app.core.database import get_db_connection
from app.core.instance_context import get_current_instance

@bp.route("/insights", endpoint="insights")
@require_cap("can_send")
def reports():
    """Send insights with date range filtering and enhanced metrics."""
    cu = current_user()

    # Determine instance scope
    perm = cu.get('permission_level', '')
    instance_id_filter = None
    if perm not in ('L3', 'S1'):
        try:
            instance_id_filter = get_current_instance()
        except RuntimeError:
            instance_id_filter = cu.get('instance_id')

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

    with get_db_connection("send") as conn:
        cursor = conn.cursor()

        # --- Main search query ---
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
                checkin_date,
                tracking_status
            FROM package_manifest
            WHERE deleted_at IS NULL
            AND DATE(checkin_date) >= %s
            AND DATE(checkin_date) <= %s
        """
        params = [date_from, date_to]

        if instance_id_filter is not None:
            sql += " AND instance_id = %s"
            params.append(instance_id_filter)

        if q:
            sql += " AND (tracking_number ILIKE %s OR recipient_name ILIKE %s OR package_type ILIKE %s)"
            like = f"%{q}%"
            params.extend([like, like, like])

        if item_type:
            sql += " AND package_type = %s"
            params.append(item_type)

        sql += " ORDER BY ts_utc DESC"

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        results = []
        for row in rows:
            row_dict = dict(row)
            if row_dict.get('ts_utc'):
                row_dict['ts_utc'] = row_dict['ts_utc'].strftime('%Y-%m-%d %H:%M:%S')
            if row_dict.get('checkin_date'):
                row_dict['checkin_date'] = row_dict['checkin_date'].strftime('%Y-%m-%d')
            results.append(row_dict)

        # --- Package types dropdown (scoped to instance, active only) ---
        pt_sql = "SELECT DISTINCT package_type FROM package_manifest WHERE deleted_at IS NULL AND package_type IS NOT NULL"
        pt_params = []
        if instance_id_filter is not None:
            pt_sql += " AND instance_id = %s"
            pt_params.append(instance_id_filter)
        pt_sql += " ORDER BY package_type"
        cursor.execute(pt_sql, pt_params)
        package_types = [r['package_type'] for r in cursor.fetchall()]

        # --- Locations dropdown (scoped to instance, active only) ---
        loc_sql = "SELECT DISTINCT location FROM package_manifest WHERE deleted_at IS NULL AND location IS NOT NULL"
        loc_params = []
        if instance_id_filter is not None:
            loc_sql += " AND instance_id = %s"
            loc_params.append(instance_id_filter)
        loc_sql += " ORDER BY location"
        cursor.execute(loc_sql, loc_params)
        locations = [r['location'] for r in cursor.fetchall()]

        # --- Dashboard metrics (all scoped to instance) ---
        inst_clause = " WHERE instance_id = %s" if instance_id_filter is not None else ""
        inst_params = [instance_id_filter] if instance_id_filter is not None else []

        # Historical count: includes soft-deleted rows so the "all-time received"
        # total is preserved even after packages are removed from the manifest.
        cursor.execute(
            f"SELECT COUNT(*) as total FROM package_manifest{inst_clause}",
            inst_params
        )
        total_packages_all_time = cursor.fetchone()['total']

        # Active (non-deleted) metrics
        active_clause = (inst_clause + " AND deleted_at IS NULL") if inst_clause else " WHERE deleted_at IS NULL"
        active_and = active_clause + " AND"

        cursor.execute(f"""
            SELECT tracking_status, COUNT(*) as count
            FROM package_manifest
            {active_and} tracking_status IS NOT NULL
            GROUP BY tracking_status
            ORDER BY count DESC
        """, inst_params)
        by_status = [dict(r) for r in cursor.fetchall()]

        cursor.execute(f"""
            SELECT carrier, COUNT(*) as count
            FROM package_manifest
            {active_and} carrier IS NOT NULL
            GROUP BY carrier
            ORDER BY count DESC
        """, inst_params)
        by_carrier = [dict(r) for r in cursor.fetchall()]

        cursor.execute(f"""
            SELECT COUNT(*) as count
            FROM package_manifest
            {active_and} created_at >= CURRENT_DATE - INTERVAL '7 days'
        """, inst_params)
        recent_count = cursor.fetchone()['count']

        cursor.execute(f"""
            SELECT
                COUNT(CASE WHEN tracking_status = 'DELIVERED' THEN 1 END) as delivered,
                COUNT(*) as total
            FROM package_manifest
            {active_and} tracking_number IS NOT NULL
        """, inst_params)
        delivery_stats = cursor.fetchone()
        delivery_rate = (
            delivery_stats['delivered'] / delivery_stats['total'] * 100
            if delivery_stats['total'] > 0 else 0
        )

        cursor.close()

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
        total_packages=total_packages,
        by_type=by_type,
        by_location=by_location,
        total_packages_all_time=total_packages_all_time,
        by_status=by_status,
        by_carrier=by_carrier,
        recent_count=recent_count,
        delivery_rate=round(delivery_rate, 1)
    )


@bp.get("/insights/export")
@require_cap("can_send")
def export():
    """Export send insights to CSV with instance scope."""
    cu = current_user()

    perm = cu.get('permission_level', '')
    instance_id_filter = None
    if perm not in ('L3', 'S1'):
        try:
            instance_id_filter = get_current_instance()
        except RuntimeError:
            instance_id_filter = cu.get('instance_id')

    q = request.args.get("q", "").strip()
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    item_type = request.args.get("item_type", "")

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
                location,
                checkin_id,
                package_id,
                carrier
            FROM package_manifest
            WHERE 1=1
        """
        params = []

        if instance_id_filter is not None:
            sql += " AND instance_id = %s"
            params.append(instance_id_filter)

        if date_from:
            sql += " AND DATE(checkin_date) >= %s"
            params.append(date_from)

        if date_to:
            sql += " AND DATE(checkin_date) <= %s"
            params.append(date_to)

        if q:
            sql += " AND (tracking_number ILIKE %s OR recipient_name ILIKE %s OR package_type ILIKE %s)"
            like = f"%{q}%"
            params.extend([like, like, like])

        if item_type:
            sql += " AND package_type = %s"
            params.append(item_type)

        sql += " ORDER BY ts_utc DESC"

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()

    buf = io.StringIO()
    w = csv.writer(buf)

    w.writerow([
        "Timestamp",
        "Check-in ID",
        "Package ID",
        "Item Type",
        "Recipient Name",
        "Recipient Address",
        "Tracking Number",
        "Carrier",
        "Submitted By",
        "Location of Origin"
    ])

    for row in rows:
        w.writerow([
            row['ts_utc'].strftime('%Y-%m-%d %H:%M:%S') if row['ts_utc'] else '',
            row['checkin_id'],
            row['package_id'],
            row['package_type'],
            row['recipient_name'],
            row['recipient_address'],
            row['tracking_number'],
            row['carrier'],
            row['submitter_name'],
            row['location']
        ])

    record_audit(cu, "export_send_insights", "send", f"Exported {len(rows)} send records")

    data = io.BytesIO(buf.getvalue().encode("utf-8"))
    filename = f"send_insights_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return send_file(data, mimetype="text/csv", as_attachment=True, download_name=filename)
