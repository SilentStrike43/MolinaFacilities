# app/modules/fulfillment/reports.py
import io
import csv
import json
import datetime
from flask import render_template, request, send_file
from . import bp
from app.core.database import get_db_connection
from app.modules.auth.security import require_any, current_user
from app.core.instance_context import get_current_instance


def _get_instance_scope(cu):
    """
    Returns (instance_id_filter, instance_id_for_template).
    L3/S1 see all data (filter=None). Others are scoped to their instance.
    """
    perm = cu.get('permission_level', '') if cu else ''
    if perm in ('L3', 'S1'):
        return None, cu.get('instance_id')
    try:
        iid = get_current_instance()
    except RuntimeError:
        iid = cu.get('instance_id') if cu else None
    return iid, iid


@bp.route("/insights", endpoint="insights")
@require_any(["can_fulfillment_staff", "can_fulfillment_customer"])
def insights():
    cu = current_user()
    instance_id_filter, instance_id = _get_instance_scope(cu)
    is_sandbox = (instance_id == 4)

    # Filters from request
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    status_filter = request.args.get("status", "")
    staff_filter = request.args.get("staff", "").strip()

    if not date_from:
        date_from = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    if not date_to:
        date_to = datetime.date.today().isoformat()

    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()

        sql = """
            SELECT
                fr.id,
                fr.status,
                fr.total_pages,
                fr.options_json,
                fr.completed_by_name,
                fr.completed_at,
                fr.is_archived,
                sr.created_at,
                sr.requester_name,
                sr.instance_id
            FROM fulfillment_requests fr
            LEFT JOIN service_requests sr ON fr.service_request_id = sr.id
            WHERE 1=1
        """
        params = []

        if instance_id_filter is not None:
            sql += " AND sr.instance_id = %s"
            params.append(instance_id_filter)

        if date_from:
            sql += " AND DATE(sr.created_at) >= %s"
            params.append(date_from)

        if date_to:
            sql += " AND DATE(sr.created_at) <= %s"
            params.append(date_to)

        if status_filter:
            sql += " AND fr.status = %s"
            params.append(status_filter)

        if staff_filter:
            sql += " AND fr.completed_by_name ILIKE %s"
            params.append(f"%{staff_filter}%")

        sql += " ORDER BY sr.created_at DESC"

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()

    # --- Compute metrics ---
    total_requests = len(rows)
    total_pages = 0
    completed_count = 0
    status_counts = {}
    staff_stats = {}
    daily_stats = {}
    request_type_counts = {}
    print_type_counts = {}
    paper_sides_counts = {}
    paper_size_counts = {}
    binding_counts = {}

    for row in rows:
        pages = row.get('total_pages') or 0
        total_pages += pages
        status = row.get('status') or 'Unknown'

        if status == 'Completed':
            completed_count += 1

        status_counts[status] = status_counts.get(status, 0) + 1

        # Staff performance
        staff = row.get('completed_by_name')
        if staff:
            if staff not in staff_stats:
                staff_stats[staff] = {'completed': 0, 'pages': 0}
            staff_stats[staff]['completed'] += 1
            staff_stats[staff]['pages'] += pages

        # Daily trends
        created = row.get('created_at')
        if created:
            day = created.strftime('%Y-%m-%d') if hasattr(created, 'strftime') else str(created)[:10]
            if day not in daily_stats:
                daily_stats[day] = {'requests': 0, 'pages': 0}
            daily_stats[day]['requests'] += 1
            daily_stats[day]['pages'] += pages

        # Options JSON breakdowns
        opts_raw = row.get('options_json')
        if opts_raw:
            try:
                opts = json.loads(opts_raw) if isinstance(opts_raw, str) else opts_raw
            except (json.JSONDecodeError, TypeError):
                opts = {}

            rtype = opts.get('request_category') or 'Unknown'
            request_type_counts[rtype] = request_type_counts.get(rtype, 0) + 1

            ptype = opts.get('print_type') or 'Unknown'
            print_type_counts[ptype] = print_type_counts.get(ptype, 0) + 1

            sides = opts.get('paper_sides') or 'Unknown'
            paper_sides_counts[sides] = paper_sides_counts.get(sides, 0) + 1

            size = opts.get('paper_size') or 'Unknown'
            paper_size_counts[size] = paper_size_counts.get(size, 0) + 1

            binding = opts.get('binding') or 'None'
            binding_counts[binding] = binding_counts.get(binding, 0) + 1

    avg_pages = round(total_pages / total_requests, 1) if total_requests > 0 else 0
    completion_rate = round(completed_count / total_requests * 100, 1) if total_requests > 0 else 0

    # Sort daily_stats descending by date
    daily_stats = dict(sorted(daily_stats.items(), reverse=True))

    return render_template(
        "fulfillment/insights.html",
        active="insights",
        is_sandbox=is_sandbox,
        instance_id=instance_id,
        date_from=date_from,
        date_to=date_to,
        status_filter=status_filter,
        staff_filter=staff_filter,
        total_requests=total_requests,
        total_pages=total_pages,
        avg_pages=avg_pages,
        completion_rate=completion_rate,
        status_counts=status_counts,
        staff_stats=staff_stats,
        daily_stats=daily_stats,
        request_type_counts=request_type_counts,
        print_type_counts=print_type_counts,
        paper_sides_counts=paper_sides_counts,
        paper_size_counts=paper_size_counts,
        binding_counts=binding_counts,
    )


@bp.get("/insights/export", endpoint="insights_export")
@require_any(["can_fulfillment_staff", "can_fulfillment_customer"])
def insights_export():
    cu = current_user()
    instance_id_filter, _ = _get_instance_scope(cu)

    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    status_filter = request.args.get("status", "")
    staff_filter = request.args.get("staff", "").strip()

    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()

        sql = """
            SELECT
                fr.id,
                sr.created_at,
                sr.requester_name,
                sr.description,
                sr.instance_id,
                fr.status,
                fr.total_pages,
                fr.completed_by_name,
                fr.completed_at,
                fr.options_json,
                fr.notes
            FROM fulfillment_requests fr
            LEFT JOIN service_requests sr ON fr.service_request_id = sr.id
            WHERE 1=1
        """
        params = []

        if instance_id_filter is not None:
            sql += " AND sr.instance_id = %s"
            params.append(instance_id_filter)

        if date_from:
            sql += " AND DATE(sr.created_at) >= %s"
            params.append(date_from)

        if date_to:
            sql += " AND DATE(sr.created_at) <= %s"
            params.append(date_to)

        if status_filter:
            sql += " AND fr.status = %s"
            params.append(status_filter)

        if staff_filter:
            sql += " AND fr.completed_by_name ILIKE %s"
            params.append(f"%{staff_filter}%")

        sql += " ORDER BY sr.created_at DESC"

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()

    buf = io.StringIO()
    w = csv.writer(buf)

    w.writerow([
        "ID", "Submitted At", "Requester Name", "Description",
        "Instance ID", "Status", "Total Pages", "Completed By",
        "Completed At", "Notes"
    ])

    for row in rows:
        created = row.get('created_at')
        completed = row.get('completed_at')
        w.writerow([
            row.get('id'),
            created.strftime('%Y-%m-%d %H:%M:%S') if created else '',
            row.get('requester_name', ''),
            row.get('description', ''),
            row.get('instance_id', ''),
            row.get('status', ''),
            row.get('total_pages', 0),
            row.get('completed_by_name', ''),
            completed.strftime('%Y-%m-%d %H:%M:%S') if completed else '',
            row.get('notes', ''),
        ])

    data = io.BytesIO(buf.getvalue().encode("utf-8"))
    filename = f"fulfillment_insights_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return send_file(data, mimetype="text/csv", as_attachment=True, download_name=filename)
