# app/modules/fulfillment/views.py
"""
Fulfillment Module Views - Instance-Aware Edition
Uses middleware-based instance context instead of manual instance_id handling
"""

import logging
import os
import json
import datetime
import mimetypes

logger = logging.getLogger(__name__)
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, send_file, abort
from werkzeug.utils import secure_filename

from app.modules.auth.security import login_required, current_user, record_audit
from app.core.permissions import PermissionManager
from app.core.database import get_db_connection
from app.core.s3 import s3_configured, s3_upload, s3_presigned_url, s3_delete
from app.core.instance_queries import build_insert, build_select, build_update, add_instance_filter
from app.core.instance_context import get_current_instance

# module-local DB
from app.modules.fulfillment.storage import ensure_schema

fulfillment_bp = Blueprint("fulfillment", __name__, url_prefix="/fulfillment", template_folder="templates")
bp = fulfillment_bp

STATUS_CHOICES = [
    "Received", "Hold", "In-Progress", "Suspended",
    "Cancelled", "Completed", "Archive"
]

# Upload directory
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "fulfillment_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ---------- Schema setup ----------
ensure_schema()

# ========== HELPER FUNCTIONS ==========

def get_instance_context():
    """Get instance context from middleware (set automatically per request)."""
    try:
        instance_id = get_current_instance()
        is_sandbox = (instance_id == 4)
        return instance_id, is_sandbox
    except RuntimeError:
        # Fallback if middleware didn't set context
        cu = current_user()
        instance_id = cu.get('instance_id') if cu else None
        is_sandbox = (instance_id == 4)
        return instance_id, is_sandbox


def should_filter_by_instance(user):
    """
    Determine if user should see only their instance's data.

    All users (including L3/S1) are scoped to the currently active instance.
    L3/S1 can switch to any instance freely, but when viewing instance X
    they only see instance X's data — no cross-instance bleed.
    """
    if not user:
        return (True, None)

    try:
        instance_id = get_current_instance()
    except RuntimeError:
        instance_id = user.get('instance_id')

    return (True, instance_id)


# ---------- Database helpers ----------

def update_status(request_id: int, status: str, archive: bool = False, 
                 staff_id: int = None, staff_name: str = None, 
                 completed_by_id: int = None, completed_by_name: str = None):
    """Update request status in BOTH tables."""
    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()
        
        # Update fulfillment_requests
        if status == 'Completed' or archive:
            cursor.execute("""
                UPDATE fulfillment_requests 
                SET status=%s, is_archived=%s,
                    completed_by_id=%s, completed_by_name=%s,
                    completed_at=CURRENT_TIMESTAMP
                WHERE id=%s
            """, (status, True, completed_by_id or staff_id, completed_by_name or staff_name, request_id))
            
            cursor.execute("""
                UPDATE service_requests
                SET status=%s, is_archived=%s, completed_at=CURRENT_TIMESTAMP
                WHERE id=(
                    SELECT service_request_id 
                    FROM fulfillment_requests 
                    WHERE id=%s
                )
            """, (status, True, request_id))
            
        else:
            # Just update status, don't archive
            cursor.execute("""
                UPDATE fulfillment_requests 
                SET status=%s
                WHERE id=%s
            """, (status, request_id))
            
            cursor.execute("""
                UPDATE service_requests
                SET status=%s
                WHERE id=(
                    SELECT service_request_id 
                    FROM fulfillment_requests 
                    WHERE id=%s
                )
            """, (status, request_id))
        
        conn.commit()
        cursor.close()


def list_queue(filter_by_instance=False, instance_id=None):
    """List non-archived requests, optionally filtered by instance."""
    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()
        
        base_where = "fr.is_archived = FALSE"
        params = []

        # Apply instance filter — use fr.instance_id (reliably set on all new rows)
        # with fallback to sr.instance_id for legacy rows that predate the column
        if filter_by_instance and instance_id is not None:
            base_where += " AND (fr.instance_id = %s OR (fr.instance_id IS NULL AND sr.instance_id = %s))"
            params.extend([instance_id, instance_id])

        query = f"""
            SELECT
                fr.id,
                sr.created_at,
                sr.requester_name,
                sr.description,
                COALESCE(fr.instance_id, sr.instance_id) AS instance_id,
                fr.status,
                fr.is_archived,
                fr.total_pages,
                fr.date_due,
                fr.options_json,
                fr.notes,
                fr.created_by_id,
                fr.created_by_name
            FROM fulfillment_requests fr
            LEFT JOIN service_requests sr ON fr.service_request_id = sr.id
            WHERE {base_where}
            ORDER BY sr.created_at DESC
        """

        cursor.execute(query, params)
        rows = cursor.fetchall()

        result = []
        for row in rows:
            result.append({
                'id': row['id'],
                'created_at': row['created_at'],
                'requester_name': row['requester_name'],
                'description': row['description'],
                'instance_id': row['instance_id'],
                'status': row['status'] or 'Received',
                'is_archived': row['is_archived'],
                'total_pages': row['total_pages'] or 0,
                'date_due': row['date_due'],
                'options_json': row['options_json'],
                'notes': row['notes'],
                'created_by_id': row['created_by_id'],
                'created_by_name': row['created_by_name']
            })
        
        cursor.close()
        return result


def list_archive(filter_by_instance=False, instance_id=None):
    """List archived requests, optionally filtered by instance."""
    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()
        
        base_where = "fr.is_archived = TRUE"
        params = []

        # Apply instance filter — use fr.instance_id (reliably set on all new rows)
        # with fallback to sr.instance_id for legacy rows that predate the column
        if filter_by_instance and instance_id is not None:
            base_where += " AND (fr.instance_id = %s OR (fr.instance_id IS NULL AND sr.instance_id = %s))"
            params.extend([instance_id, instance_id])

        query = f"""
            SELECT
                fr.id,
                sr.created_at,
                sr.requester_name,
                sr.description,
                COALESCE(fr.instance_id, sr.instance_id) AS instance_id,
                fr.status,
                fr.completed_at,
                fr.is_archived,
                fr.total_pages,
                fr.date_due,
                fr.options_json,
                fr.notes,
                fr.created_by_id,
                fr.created_by_name,
                fr.completed_by_id,
                fr.completed_by_name
            FROM fulfillment_requests fr
            LEFT JOIN service_requests sr ON fr.service_request_id = sr.id
            WHERE {base_where}
            ORDER BY fr.completed_at DESC, sr.created_at DESC
        """

        cursor.execute(query, params)
        rows = cursor.fetchall()

        result = []
        for row in rows:
            result.append({
                'id': row['id'],
                'created_at': row['created_at'],
                'requester_name': row['requester_name'],
                'description': row['description'],
                'instance_id': row['instance_id'],
                'status': row['status'] or 'Completed',
                'completed_at': row['completed_at'],
                'is_archived': row['is_archived'],
                'total_pages': row['total_pages'] or 0,
                'date_due': row['date_due'],
                'options_json': row['options_json'],
                'notes': row['notes'],
                'created_by_id': row['created_by_id'],
                'created_by_name': row['created_by_name'],
                'completed_by_id': row['completed_by_id'],
                'completed_by_name': row['completed_by_name']
            })
        
        cursor.close()
        return result


def get_request(request_id: int, user=None):
    """Get a single request WITH instance security check."""
    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT fr.*, sr.instance_id 
            FROM fulfillment_requests fr
            JOIN service_requests sr ON fr.service_request_id = sr.id
            WHERE fr.id=%s
        """, (request_id,))
        row = cursor.fetchone()
        cursor.close()
        
        # Security check if user provided
        if row and user:
            should_filter, allowed_instance = should_filter_by_instance(user)
            if should_filter and row['instance_id'] != allowed_instance:
                return None  # Access denied
        
        return row


def list_files(request_id: int):
    """List files for a request."""
    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM fulfillment_files 
            WHERE request_id=%s 
            ORDER BY ts_utc
        """, (request_id,))
        rows = cursor.fetchall()
        cursor.close()
        return rows


# ---------- Permission helpers ----------

def _user_can_staff(u) -> bool:
    """Check if user has M3B (Service) or M3C (Manager) permissions."""
    if not u:
        return False
    
    permission_level = u.get('permission_level', '')
    if permission_level in ['L1', 'L2', 'L3', 'S1']:
        return True
    
    effective_perms = PermissionManager.get_effective_permissions(u)
    return effective_perms.get('can_fulfillment_service') or effective_perms.get('can_fulfillment_manager')


def _user_can_customer(u) -> bool:
    """Check if user has M3A (Customer), M3B (Service), or M3C (Manager) permissions."""
    if not u:
        return False
    
    permission_level = u.get('permission_level', '')
    if permission_level in ['L1', 'L2', 'L3', 'S1']:
        return True
    
    effective_perms = PermissionManager.get_effective_permissions(u)
    return (effective_perms.get('can_fulfillment_customer') or 
            effective_perms.get('can_fulfillment_service') or 
            effective_perms.get('can_fulfillment_manager'))


def _require_staff():
    """Require M3B or M3C permissions."""
    u = current_user()
    if not _user_can_staff(u):
        flash("Fulfillment staff access required. You need M3B (Service) or M3C (Manager) permissions.", "danger")
        return None
    return u


def _require_customer():
    """Require M3A, M3B, or M3C permissions."""
    u = current_user()
    if not _user_can_customer(u):
        flash("Fulfillment access required. You need M3A (Customer), M3B (Service), or M3C (Manager) permissions.", "danger")
        return None
    return u


# ---------- ROUTES ----------

@fulfillment_bp.route("/request", methods=["GET", "POST"])
@login_required
def request_form():
    """Submit new fulfillment request."""
    cu = current_user()
    instance_id, is_sandbox = get_instance_context()
    
    effective_perms = PermissionManager.get_effective_permissions(cu)
    if not (effective_perms.get("can_fulfillment_customer") or 
            effective_perms.get("can_fulfillment_service") or 
            effective_perms.get("can_fulfillment_manager")):
        flash("You don't have access to Fulfillment.", "danger")
        return redirect(url_for("home.index"))
    
    if request.method == "POST":
        # Get form data
        requester_name = f"{cu.get('first_name', '')} {cu.get('last_name', '')}".strip()
        if not requester_name:
            requester_name = cu.get('username', 'Unknown')

        description = request.form.get("description", "").strip()
        page_count = int(request.form.get("page_count", 0) or 0)
        request_category = request.form.get('request_category', 'Standard Mail / Letter')

        # For Standard Mail / Letter: auto-detect page count from uploaded PDF
        # if the user didn't supply one, then enforce it as required.
        if request_category == 'Standard Mail / Letter':
            if page_count == 0:
                # Try to count pages from the first PDF attachment
                uploaded_files = request.files.getlist("attachments")
                for f in uploaded_files:
                    if f and f.filename and f.filename.lower().endswith('.pdf'):
                        try:
                            from pypdf import PdfReader
                            reader = PdfReader(f.stream)
                            page_count = len(reader.pages)
                            f.stream.seek(0)  # reset for later save
                        except Exception as _pdf_err:
                            logger.warning(f"PDF page count failed: {_pdf_err}")
                        break  # only read the first PDF

            if page_count == 0:
                flash("Total Pages is required for Standard Mail / Letter requests.", "danger")
                return redirect(url_for("fulfillment.request_form"))

        # GET PRINT OPTIONS
        print_options = {
            'request_category': request_category,
            'print_type': request.form.get('print_type', 'Black and White'),
            'paper_size': request.form.get('paper_size', '8.5x11'),
            'paper_stock': request.form.get('paper_stock', '#20 White Paper'),
            'paper_color': request.form.get('paper_color', 'White'),
            'paper_sides': request.form.get('paper_sides', 'Single-Sided'),
            'binding': request.form.get('binding', 'None')
        }
        
        if not description:
            flash("Description is required.", "danger")
            return redirect(url_for("fulfillment.request_form"))
        
        try:
            with get_db_connection("fulfillment") as conn:
                cursor = conn.cursor()
                
                # STEP 1: Insert into service_requests (instance_id added automatically)
                sr_columns = [
                    'title', 'description', 'request_type',
                    'requester_id', 'requester_name',
                    'status', 'is_archived', 'created_at'
                ]
                
                sr_values = [
                    description[:100],
                    description,
                    'fulfillment',
                    cu['id'],
                    requester_name,
                    'pending',
                    False,
                    datetime.datetime.now()
                ]
                
                # build_insert automatically adds instance_id
                sql, params = build_insert('service_requests', sr_columns, sr_values)
                sql += " RETURNING id"
                
                cursor.execute(sql, params)
                result = cursor.fetchone()
                service_request_id = result['id'] if result else None
                
                if not service_request_id:
                    raise Exception("No ID returned from service_requests insert")
                
                # STEP 2: Insert into fulfillment_requests
                cursor.execute("""
                    INSERT INTO fulfillment_requests (
                        instance_id, service_request_id, description,
                        total_pages, date_submitted, status, is_archived,
                        options_json,
                        created_by_id, created_by_name
                    )
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    instance_id,
                    service_request_id,
                    description,
                    page_count,
                    'Received',
                    False,
                    json.dumps(print_options),
                    cu['id'],
                    cu['username']
                ))
                
                result = cursor.fetchone()
                fulfillment_id = result['id'] if result else None
                
                if not fulfillment_id:
                    raise Exception("No ID returned from fulfillment_requests insert")
                
                # Commit the main inserts
                conn.commit()
                
                # Handle file uploads
                files = request.files.getlist("attachments")
                if files and any(f.filename for f in files):
                    for f in files:
                        if f and f.filename:
                            try:
                                import uuid
                                orig_name = secure_filename(f.filename)
                                ext = os.path.splitext(orig_name)[1].lower()
                                stored_name = f"{uuid.uuid4().hex}{ext}"

                                if s3_configured():
                                    # Upload to S3 — key encodes instance/request/filename
                                    s3_upload(f, stored_name, instance_id, fulfillment_id)
                                    size = f.seek(0, 2) or 0  # seek to end for size
                                else:
                                    # Local filesystem fallback (dev only)
                                    LOCAL_UPLOAD = os.path.join(os.path.dirname(__file__), "uploads")
                                    os.makedirs(LOCAL_UPLOAD, exist_ok=True)
                                    file_path = os.path.join(LOCAL_UPLOAD, stored_name)
                                    f.save(file_path)
                                    size = os.path.getsize(file_path)

                                cursor.execute("""
                                    INSERT INTO fulfillment_files(
                                        request_id, orig_name, stored_name, ext, bytes, ok
                                    )
                                    VALUES (%s, %s, %s, %s, %s, %s)
                                """, (fulfillment_id, orig_name, stored_name, ext, size, True))

                            except Exception as file_error:
                                logger.warning(f"File upload failed: {file_error}")

                    conn.commit()
                
                cursor.close()
            
            # Record audit
            record_audit(cu, "create_fulfillment_request", "fulfillment", 
                        f"Created request #{fulfillment_id}: {description[:50]}")
            
            flash(f"Request #{fulfillment_id} submitted successfully!", "success")
            return redirect(url_for("fulfillment.queue"))
            
        except Exception as e:
            error_msg = str(e)
            error_type = type(e).__name__
            
            print(f"❌ ERROR in request creation:")
            print(f"   Type: {error_type}")
            print(f"   Message: {error_msg}")
            
            import traceback
            traceback.print_exc()
            
            flash(f"Error creating request: {error_type}: {error_msg}", "danger")
            return redirect(url_for("fulfillment.request_form"))
    
    # GET request - show form
    return render_template(
        "fulfillment/request.html",
        active="fulfillment",
        page="request",
        cu=cu,
        is_sandbox=is_sandbox,
        instance_id=instance_id
    )


@fulfillment_bp.route("/queue", methods=["GET","POST"])
@login_required
def queue():
    """Fulfillment queue - view and manage requests."""
    u = _require_staff()
    if not u: 
        return redirect(url_for("home.index"))

    instance_id, is_sandbox = get_instance_context()

    if request.method == "POST":
        rid = int(request.form.get("rid") or 0)
        status = request.form.get("status") or "Received"
        cancellation_reason = request.form.get("cancellation_reason", "")
        
        archive = (status == "Archive") or (status == "Cancelled")
        
        completed_by_id = None
        completed_by_name = None
        if status == "Completed":
            completed_by_id = u["id"]
            completed_by_name = u["username"]
        
        if status == "Cancelled" and cancellation_reason:
            with get_db_connection("fulfillment") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE fulfillment_requests 
                    SET notes = %s
                    WHERE id = %s
                """, (f"CANCELLED: {cancellation_reason}", rid))
                conn.commit()
                cursor.close()
        
        update_status(
            rid, 
            status,
            archive=archive,
            staff_id=u["id"],
            staff_name=u["username"],
            completed_by_id=completed_by_id,
            completed_by_name=completed_by_name
        )
        
        action_detail = f"rid={rid}, status={status}"
        if cancellation_reason:
            action_detail += f", reason={cancellation_reason}"
        
        record_audit(u, "update_status", "fulfillment", action_detail)
        
        flash(f"Request #{rid} updated to {status}.", "success")
        return redirect(url_for("fulfillment.queue"))

    # GET request handling
    should_filter, filter_instance_id = should_filter_by_instance(u)
    
    rows = list_queue(
        filter_by_instance=should_filter,
        instance_id=filter_instance_id
    )
    
    # Map field names to match template expectations
    requests = []
    for row in rows:
        # Get files for this request
        with get_db_connection("fulfillment") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, orig_name, stored_name, ext, bytes
                FROM fulfillment_files
                WHERE request_id = %s AND ok = TRUE
            """, (row['id'],))
            files = cursor.fetchall()
            cursor.close()
        
        # Parse print options
        print_options = {}
        if row.get('options_json'):
            try:
                print_options = json.loads(row['options_json'])
            except:
                print_options = {}
        
        requests.append({
            'id': row['id'],
            'request_type': 'Fulfillment',
            'status': row['status'],
            'submitted_at': row['created_at'],
            'submitted_by': row['requester_name'],
            'customer_name': row['requester_name'],
            'customer_email': None,
            'customer_phone': None,
            'location': None,
            'description': row['description'],
            'page_count': row.get('total_pages', 0),
            'date_due': row.get('date_due'),
            'priority': 'normal',
            'files': files,
            'notes': row.get('notes'),
            'print_options': print_options,
            'created_by_id': row.get('created_by_id'),
            'created_by_name': row.get('created_by_name')
        })
    
    return render_template("fulfillment/queue.html", 
                           active="fulfillment", 
                           page="queue",
                           requests=requests,
                           statuses=STATUS_CHOICES,
                           user_instance=filter_instance_id if should_filter else "All",
                           is_sandbox=is_sandbox,
                           instance_id=instance_id)


@fulfillment_bp.route("/download/<int:file_id>")
@login_required
def download_file(file_id: int):
    """Download uploaded file — S3 presigned redirect or local filesystem fallback."""
    from flask import redirect as flask_redirect
    cu = current_user()

    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()
        # SECURITY: Join to verify instance ownership before serving the file
        cursor.execute("""
            SELECT
                ff.orig_name,
                ff.stored_name,
                ff.ext,
                fr.id AS request_id,
                sr.instance_id
            FROM fulfillment_files ff
            JOIN fulfillment_requests fr ON ff.request_id = fr.id
            JOIN service_requests sr   ON fr.service_request_id = sr.id
            WHERE ff.id = %s AND ff.ok = TRUE
        """, (file_id,))
        row = cursor.fetchone()
        cursor.close()

    if not row:
        flash("File not found.", "danger")
        return redirect(url_for("fulfillment.queue"))

    # SECURITY CHECK: Verify user can access this instance
    file_instance = row['instance_id']
    should_filter, allowed_instance = should_filter_by_instance(cu)

    if should_filter and file_instance != allowed_instance:
        record_audit(cu, "SECURITY_VIOLATION", "fulfillment",
                     f"Attempted to download file {file_id} from instance {file_instance}")
        flash("Access denied: File not found.", "danger")
        return redirect(url_for("fulfillment.queue"))

    orig_name  = row['orig_name']
    stored_name = row['stored_name']
    request_id  = row['request_id']
    instance_id = row['instance_id']

    record_audit(cu, "download_fulfillment_file", "fulfillment",
                 f"Downloaded file: {orig_name}")

    if s3_configured():
        # Generate a short-lived presigned URL and redirect the browser to it
        s3_key = f"fulfillment/{instance_id}/{request_id}/{stored_name}"
        try:
            url = s3_presigned_url(s3_key)
            return flask_redirect(url)
        except Exception as exc:
            logger.error(f"Presigned URL failed for file {file_id}: {exc}")
            flash("File temporarily unavailable. Please try again.", "danger")
            return redirect(url_for("fulfillment.queue"))

    # Local filesystem fallback (dev / no S3 configured)
    LOCAL_UPLOAD = os.path.join(os.path.dirname(__file__), "uploads")
    file_path = os.path.join(LOCAL_UPLOAD, stored_name)

    if not os.path.exists(file_path):
        flash("File not found on server.", "danger")
        return redirect(url_for("fulfillment.queue"))

    return send_file(file_path, as_attachment=True, download_name=orig_name)


@fulfillment_bp.route("/request/<int:request_id>")
@login_required
def view_request(request_id: int):
    """View detailed fulfillment request."""
    cu = current_user()
    instance_id, is_sandbox = get_instance_context()
    
    effective_perms = PermissionManager.get_effective_permissions(cu)
    if not (effective_perms.get("can_fulfillment_customer") or 
            effective_perms.get("can_fulfillment_service") or 
            effective_perms.get("can_fulfillment_manager")):
        flash("You don't have access to Fulfillment.", "danger")
        return redirect(url_for("home.index"))
    
    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()

        # SECURITY CHECK: Verify user can access this instance's data
        request_instance = row.get('instance_id')
        should_filter, allowed_instance = should_filter_by_instance(cu)

        if should_filter and request_instance != allowed_instance:
            # User trying to access request from different instance!
            record_audit(cu, "SECURITY_VIOLATION", "fulfillment", 
                        f"Attempted to access request #{request_id} from instance {request_instance}")
            flash("Access denied: Request not found.", "danger")
            return redirect(url_for("fulfillment.queue"))
        
        cursor.execute("""
            SELECT 
                fr.*,
                sr.instance_id,
                sr.created_at as sr_created_at,
                sr.completed_at as sr_completed_at
            FROM fulfillment_requests fr
            LEFT JOIN service_requests sr ON fr.service_request_id = sr.id
            WHERE fr.id = %s
        """, (request_id,))
        
        row = cursor.fetchone()
        if not row:
            flash("Request not found.", "warning")
            return redirect(url_for("fulfillment.queue"))
        
        request_data = dict(row)
        
        cursor.execute("""
            SELECT id, orig_name, ext, bytes, ts_utc
            FROM fulfillment_files
            WHERE request_id = %s AND ok = TRUE
            ORDER BY ts_utc DESC
        """, (request_id,))
        files = cursor.fetchall()
        
        cursor.close()
    
    record_audit(cu, "view_fulfillment_request", "fulfillment", 
                f"Viewed request #{request_id}")
    
    return render_template(
        "fulfillment/view_request.html",
        active="fulfillment",
        page="view",
        request=request_data,
        files=files,
        is_sandbox=is_sandbox,
        instance_id=instance_id
    )


@fulfillment_bp.route("/request/<int:request_id>/edit", methods=["GET", "POST"])
@login_required
def edit_request(request_id: int):
    """Edit fulfillment request (M3B/M3C only)."""
    cu = current_user()
    instance_id, is_sandbox = get_instance_context()
    
    if not _user_can_staff(cu):
        flash("You need M3B (Service) or M3C (Manager) permissions to edit requests.", "danger")
        return redirect(url_for("home.index"))
    
    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT fr.*, sr.instance_id, sr.created_at as sr_created_at
            FROM fulfillment_requests fr
            LEFT JOIN service_requests sr ON fr.service_request_id = sr.id
            WHERE fr.id = %s
        """, (request_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            flash("Request not found.", "warning")
            return redirect(url_for("fulfillment.queue"))

        if request.method == "POST":
            description = request.form.get("description", "").strip()
            total_pages = int(request.form.get("total_pages", 0) or 0)
            date_due = request.form.get("date_due", "") or None
            notes = request.form.get("notes", "").strip()
            status = request.form.get("status", "Received")

            # SECURITY CHECK: Verify user can edit this instance's data
            should_filter, allowed_instance = should_filter_by_instance(cu)
            if should_filter and row.get('instance_id') != allowed_instance:
                cursor.close()
                record_audit(cu, "SECURITY_VIOLATION", "fulfillment",
                             f"Attempted to edit request #{request_id} from instance {row.get('instance_id')}")
                flash("Access denied: Request not found.", "danger")
                return redirect(url_for("fulfillment.queue"))

            if not description:
                cursor.close()
                flash("Description is required.", "danger")
                return redirect(url_for("fulfillment.edit_request", request_id=request_id,
                                        instance_id=instance_id))

            cursor.execute("""
                UPDATE fulfillment_requests
                SET description = %s, total_pages = %s, date_due = %s,
                    notes = %s, status = %s,
                    assigned_staff_id = %s, assigned_staff_name = %s
                WHERE id = %s
            """, (description, total_pages, date_due, notes, status,
                  cu['id'], cu['username'], request_id))

            cursor.execute("""
                UPDATE service_requests
                SET description = %s, status = %s, assigned_to = %s
                WHERE id = (SELECT service_request_id FROM fulfillment_requests WHERE id = %s)
            """, (description, status, cu['id'], request_id))

            conn.commit()
            cursor.close()

            record_audit(cu, "edit_fulfillment_request", "fulfillment",
                         f"Edited request #{request_id}")
            flash(f"Request #{request_id} updated successfully.", "success")
            return redirect(url_for("fulfillment.queue", instance_id=instance_id))

        request_data = dict(row)
        cursor.close()
    
    return render_template(
        "fulfillment/edit_request.html",
        active="fulfillment",
        page="edit",
        request=request_data,
        statuses=STATUS_CHOICES,
        is_sandbox=is_sandbox,
        instance_id=instance_id
    )


@fulfillment_bp.route("/archive")
@login_required
def archive():
    """View archived fulfillment requests."""
    u = _require_staff()
    if not u: 
        return redirect(url_for("home.index"))
    
    instance_id, is_sandbox = get_instance_context()
    
    should_filter, filter_instance_id = should_filter_by_instance(u)
    
    rows = list_archive(
        filter_by_instance=should_filter,
        instance_id=filter_instance_id
    )
    
    # Map field names to match template expectations
    archived_requests = []
    for row in rows:
        # Get files for this request
        with get_db_connection("fulfillment") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, orig_name, stored_name, ext, bytes
                FROM fulfillment_files
                WHERE request_id = %s AND ok = TRUE
            """, (row['id'],))
            files = cursor.fetchall()
            cursor.close()
        
        # Parse print options
        print_options = {}
        if row.get('options_json'):
            try:
                print_options = json.loads(row['options_json'])
            except:
                print_options = {}
        
        archived_requests.append({
            'id': row['id'],
            'request_type': 'Fulfillment',
            'status': row['status'],
            'submitted_at': row['created_at'],
            'completed_at': row.get('completed_at'),
            'submitted_by': row['requester_name'],
            'customer_name': row['requester_name'],
            'customer_email': None,
            'customer_phone': None,
            'location': None,
            'description': row['description'],
            'page_count': row.get('total_pages', 0),
            'date_due': row.get('date_due'),
            'priority': 'normal',
            'files': files,
            'notes': row.get('notes'),
            'print_options': print_options,
            'created_by_id': row.get('created_by_id'),
            'created_by_name': row.get('created_by_name'),
            'completed_by_id': row.get('completed_by_id'),
            'completed_by_name': row.get('completed_by_name')
        })
    
    return render_template("fulfillment/archive.html", 
                           active="fulfillment", 
                           page="archive", 
                           archived_requests=archived_requests,
                           user_instance=filter_instance_id if should_filter else "All",
                           is_sandbox=is_sandbox,
                           instance_id=instance_id)


def _can_view_fulfillment_insights(user):
    """Check if user can view fulfillment insights (M3C or admin)."""
    if not user:
        return False
    
    permission_level = user.get('permission_level', '')
    if permission_level in ['L1', 'L2', 'L3', 'S1']:
        return True
    
    try:
        module_perms = json.loads(user.get('module_permissions', '[]') or '[]')
        if 'M3C' in module_perms:
            return True
    except:
        pass
    
    return False


@fulfillment_bp.route("/insights")
@login_required
def insights():
    """Fulfillment insights dashboard."""
    cu = current_user()
    instance_id, is_sandbox = get_instance_context()
    
    # Check permissions - only M3B (Service) and M3C (Manager) can access
    if not _user_can_staff(cu):
        flash("You need staff permissions to access Fulfillment Insights.", "danger")
        return redirect(url_for("home.index"))
    
    # Get filter parameters
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    status_filter = request.args.get("status", "")
    staff_filter = request.args.get("staff", "")
    
    # Default date range: last 30 days
    if not date_from:
        date_from = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    if not date_to:
        date_to = datetime.date.today().isoformat()
    
    # Use instance filtering
    should_filter, filter_instance_id = should_filter_by_instance(cu)
    
    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()
        
        # Build base query with instance filter
        base_conditions = [
            "DATE(fr.date_submitted) >= %s",
            "DATE(fr.date_submitted) <= %s"
        ]
        params = [date_from, date_to]
        
        if should_filter and filter_instance_id:
            base_conditions.append("sr.instance_id = %s")
            params.append(filter_instance_id)
        
        if status_filter:
            base_conditions.append("fr.status = %s")
            params.append(status_filter)
        
        if staff_filter:
            base_conditions.append("fr.completed_by_name ILIKE %s")
            params.append(f"%{staff_filter}%")
        
        where_clause = " AND ".join(base_conditions)
        
        query = f"""
            SELECT
                fr.id,
                fr.status,
                fr.total_pages,
                fr.date_submitted,
                fr.completed_at,
                fr.created_by_name,
                fr.completed_by_name,
                fr.is_archived,
                fr.options_json,
                sr.requester_name,
                sr.instance_id
            FROM fulfillment_requests fr
            LEFT JOIN service_requests sr ON fr.service_request_id = sr.id
            WHERE {where_clause}
            ORDER BY fr.date_submitted DESC
        """

        cursor.execute(query, params)
        rows = cursor.fetchall()

        # Calculate metrics
        total_requests = len(rows)
        total_pages = sum(row['total_pages'] or 0 for row in rows)
        completed_requests = sum(1 for row in rows if row['is_archived'])
        avg_pages = total_pages / total_requests if total_requests > 0 else 0
        completion_rate = (completed_requests / total_requests * 100) if total_requests > 0 else 0

        # Status breakdown
        status_counts = {}
        for row in rows:
            status = row['status'] or 'Unknown'
            status_counts[status] = status_counts.get(status, 0) + 1

        # Staff performance
        staff_stats = {}
        for row in rows:
            if row['completed_by_name']:
                staff = row['completed_by_name']
                if staff not in staff_stats:
                    staff_stats[staff] = {'completed': 0, 'pages': 0}
                staff_stats[staff]['completed'] += 1
                staff_stats[staff]['pages'] += row['total_pages'] or 0

        # Sort staff by completed count
        staff_stats = dict(sorted(staff_stats.items(), key=lambda x: x[1]['completed'], reverse=True))

        # Daily trends
        daily_stats = {}
        for row in rows:
            date = row['date_submitted'] if row['date_submitted'] else None
            if date:
                date_str = date.isoformat()
                if date_str not in daily_stats:
                    daily_stats[date_str] = {'requests': 0, 'pages': 0}
                daily_stats[date_str]['requests'] += 1
                daily_stats[date_str]['pages'] += row['total_pages'] or 0

        # Sort daily stats by date
        daily_stats = dict(sorted(daily_stats.items()))

        # Print options breakdowns (parsed from options_json)
        request_type_counts = {}
        print_type_counts = {}
        paper_sides_counts = {}
        paper_size_counts = {}
        binding_counts = {}

        for row in rows:
            opts = {}
            if row['options_json']:
                try:
                    opts = json.loads(row['options_json'])
                except Exception:
                    pass

            rc = opts.get('request_category', 'Unknown')
            request_type_counts[rc] = request_type_counts.get(rc, 0) + 1

            pt = opts.get('print_type', 'Unknown')
            print_type_counts[pt] = print_type_counts.get(pt, 0) + 1

            ps = opts.get('paper_sides', 'Unknown')
            paper_sides_counts[ps] = paper_sides_counts.get(ps, 0) + 1

            pz = opts.get('paper_size', 'Unknown')
            paper_size_counts[pz] = paper_size_counts.get(pz, 0) + 1

            bd = opts.get('binding', 'Unknown')
            binding_counts[bd] = binding_counts.get(bd, 0) + 1

        cursor.close()
    
    record_audit(cu, "view_fulfillment_insights", "fulfillment", 
                f"Viewed insights: {date_from} to {date_to}")
    
    return render_template(
        "fulfillment/insights.html",
        active="fulfillment-insights",
        page="insights",
        total_requests=total_requests,
        total_pages=total_pages,
        completed_requests=completed_requests,
        avg_pages=round(avg_pages, 1),
        completion_rate=round(completion_rate, 1),
        status_counts=status_counts,
        staff_stats=staff_stats,
        daily_stats=daily_stats,
        request_type_counts=request_type_counts,
        print_type_counts=print_type_counts,
        paper_sides_counts=paper_sides_counts,
        paper_size_counts=paper_size_counts,
        binding_counts=binding_counts,
        rows=rows,
        date_from=date_from,
        date_to=date_to,
        status_filter=status_filter,
        staff_filter=staff_filter,
        user_instance=filter_instance_id if should_filter else "All",
        is_sandbox=is_sandbox,
        instance_id=instance_id
    )


@fulfillment_bp.route("/insights/export")
@login_required
def insights_export():
    """Export fulfillment insights to CSV."""
    cu = current_user()
    
    if not _user_can_staff(cu):
        flash("You need staff permissions to export insights.", "danger")
        return redirect(url_for("home.index"))
    
    import csv
    import io
    
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    status_filter = request.args.get("status", "")
    staff_filter = request.args.get("staff", "")
    
    should_filter, filter_instance_id = should_filter_by_instance(cu)
    
    with get_db_connection("fulfillment") as conn:
        cursor = conn.cursor()
        
        base_conditions = ["1=1"]
        params = []
        
        if date_from:
            base_conditions.append("DATE(fr.date_submitted) >= %s")
            params.append(date_from)
        
        if date_to:
            base_conditions.append("DATE(fr.date_submitted) <= %s")
            params.append(date_to)
        
        if should_filter and filter_instance_id:
            base_conditions.append("sr.instance_id = %s")
            params.append(filter_instance_id)
        
        if status_filter:
            base_conditions.append("fr.status = %s")
            params.append(status_filter)
        
        if staff_filter:
            base_conditions.append("fr.completed_by_name ILIKE %s")
            params.append(f"%{staff_filter}%")
        
        where_clause = " AND ".join(base_conditions)
        
        query = f"""
            SELECT 
                fr.id,
                fr.status,
                fr.total_pages,
                fr.date_submitted,
                fr.completed_at,
                fr.created_by_name,
                fr.completed_by_name,
                sr.requester_name,
                sr.description
            FROM fulfillment_requests fr
            LEFT JOIN service_requests sr ON fr.service_request_id = sr.id
            WHERE {where_clause}
            ORDER BY fr.date_submitted DESC
        """
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()
    
    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow([
        "Request ID",
        "Status",
        "Page Count",
        "Submitted Date",
        "Completed Date",
        "Requester",
        "Created By",
        "Completed By",
        "Description"
    ])
    
    total_pages = 0
    for row in rows:
        pages = row['total_pages'] or 0
        total_pages += pages
        
        writer.writerow([
            row['id'],
            row['status'],
            pages,
            row['date_submitted'].strftime('%Y-%m-%d %H:%M') if row['date_submitted'] else '',
            row['completed_at'].strftime('%Y-%m-%d %H:%M') if row['completed_at'] else '',
            row['requester_name'],
            row['created_by_name'],
            row['completed_by_name'] or '',
            (row['description'] or '')[:100]
        ])
    
    writer.writerow([])
    writer.writerow(["TOTALS:"])
    writer.writerow(["Total Requests:", len(rows)])
    writer.writerow(["Total Pages:", total_pages])
    
    record_audit(cu, "export_fulfillment_insights", "fulfillment", 
                f"Exported {len(rows)} requests, {total_pages} pages")
    
    output.seek(0)
    mem = io.BytesIO(output.getvalue().encode("utf-8"))
    mem.seek(0)
    
    filename = f"fulfillment_insights_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return send_file(
        mem,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename
    )