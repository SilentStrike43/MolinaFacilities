"""
Send Module Views - Instance-Aware Edition
Uses middleware-based instance context instead of manual instance_id handling
"""

from datetime import datetime, date
from flask import render_template, request, redirect, url_for, flash, jsonify, current_app

from . import bp

from app.modules.auth.security import (
    login_required, require_cap, current_user, 
    record_audit, get_user_location
)
from app.core.database import get_db_connection
from app.core.instance_queries import build_insert, build_select, add_instance_filter
from app.core.instance_context import get_current_instance, get_current_instance_safe

from app.services.tracking.tracker import TrackingService
from app.services.address.book import AddressBookService
from app.services.address.validator import AddressValidator
from app.utils.carrier_detector import CarrierDetector

from .models import (
    ensure_schema, 
    peek_next_checkin_id, next_checkin_id,
    peek_next_package_id, next_package_id,
    PACKAGE_PREFIX
)

import logging

logger = logging.getLogger(__name__)

PACKAGE_TYPES = ["Box", "Envelope", "Packs", "Tubes", "Certified", "Sensitive", "Critical"]


# ========== HELPER FUNCTIONS ==========

def get_instance_context():
    """Get instance context from middleware (set automatically per request)."""
    try:
        instance_id = get_current_instance()
        is_sandbox = (instance_id == 4)
        return instance_id, is_sandbox
    except RuntimeError:
        # Fallback if middleware didn't set context (shouldn't happen)
        cu = current_user()
        instance_id = cu.get('instance_id') if cu else None
        is_sandbox = (instance_id == 4)
        logger.warning(f"Instance context not set by middleware, using fallback: {instance_id}")
        return instance_id, is_sandbox


# ========== ROUTE 1: PACKAGE CHECK-IN ==========

@bp.route("/")
@bp.route("/checkin", methods=["GET", "POST"])
@login_required
@require_cap("can_send")
def checkin():
    """Package check-in form"""
    cu = current_user()
    instance_id, is_sandbox = get_instance_context()
    
    if request.method == "POST":
        try:
            # Get form data
            tracking_number = request.form.get('tracking_number', '').strip()
            carrier = request.form.get('carrier', 'FEDEX').strip().upper()
            package_type = request.form.get('package_type', 'Package').strip()
            
            # Recipient info
            recipient_name = request.form.get('recipient_name', '').strip()
            recipient_company = request.form.get('recipient_company', '').strip()
            
            # Build full address from form fields
            address_line1 = request.form.get('address_line1', '').strip()
            address_line2 = request.form.get('address_line2', '').strip()
            city = request.form.get('city', '').strip()
            state = request.form.get('state', '').strip()
            postal_code = request.form.get('postal_code', '').strip()
            country = request.form.get('country', 'US').strip()
            
            # Combine address into single field
            address_parts = [p for p in [address_line1, address_line2, city, state, postal_code, country] if p]
            recipient_address = ', '.join(address_parts)
            
            weight = request.form.get('weight', '').strip()
            notes = request.form.get('notes', '').strip()
            
            # USE USER'S LOCATION FROM INSTANCE
            location = cu.get('instance_name', 'New York')
            
            # Validation
            if not tracking_number:
                flash('Tracking number is required', 'error')
                return redirect(url_for('send.checkin'))
            
            if not recipient_name:
                flash('Recipient name is required', 'error')
                return redirect(url_for('send.checkin'))
            
            if not address_line1 or not city or not state or not postal_code:
                flash('Complete address is required', 'error')
                return redirect(url_for('send.checkin'))
            
            # Generate IDs
            import time
            checkin_id = f"CHK{int(time.time())}"
            package_id = f"PKG{int(time.time())}"
            
            # Try to track the package
            tracking_status = None
            status_description = None
            estimated_delivery = None
            actual_delivery = None

            try:
                if carrier == 'FEDEX':
                    from app.services.tracking.fedex import FedExTracker
                    tracker = FedExTracker(current_app.config)
                    result = tracker.track(tracking_number)
                    
                    if result.success:
                        tracking_status = result.status
                        status_description = result.status_description
                        estimated_delivery = result.estimated_delivery
                        actual_delivery = result.actual_delivery
                    else:
                        logger.warning(f"Tracking failed: {result.error_message}")
                        flash(f'⚠️ Package logged but tracking failed: {result.error_message}', 'warning')
                        
            except Exception as e:
                logger.error(f"Tracking error for {tracking_number}: {e}", exc_info=True)
                flash(f'⚠️ Package logged but tracking unavailable', 'warning')
            
            # Convert weight from oz to lbs
            weight_lbs = None
            if weight:
                try:
                    weight_lbs = float(weight) / 16.0
                except:
                    pass
            
            # Insert into database using instance-aware helper
            with get_db_connection("send") as conn:
                cursor = conn.cursor()
                
                # Define columns (instance_id will be added automatically)
                columns = [
                    'checkin_id', 'package_id', 'tracking_number', 'carrier',
                    'package_type', 'recipient_name', 'recipient_company',
                    'recipient_address', 'package_weight_lbs', 'tracking_status',
                    'tracking_status_description', 'estimated_delivery_date',
                    'delivery_location', 'location', 'submitter_name', 'notes',
                    'auto_populated', 'checkin_date', 'created_at', 'ts_utc',
                    'last_tracked_at'
                ]
                
                values = [
                    checkin_id, package_id, tracking_number, carrier,
                    package_type, recipient_name, recipient_company,
                    recipient_address, weight_lbs, tracking_status,
                    status_description, estimated_delivery, None, location,
                    cu.get('username'), notes, False, datetime.now().date(),
                    datetime.now(), datetime.now(),
                    datetime.now() if tracking_status else None
                ]
                
                # build_insert automatically adds instance_id
                sql, params = build_insert('package_manifest', columns, values)
                cursor.execute(sql, params)
                
                conn.commit()
                cursor.close()
            
            # Log audit
            record_audit(cu, "package_checkin", "send", f"Checked in package {tracking_number}")
            
            flash(f'✅ Package {tracking_number} checked in successfully!', 'success')
            return redirect(url_for('send.manifest'))
            
        except Exception as e:
            logger.error(f"Error creating package: {e}", exc_info=True)
            flash(f'❌ Error creating package: {e}', 'error')
            return redirect(url_for('send.checkin'))
    
    # GET - show form
    return render_template(
        "send/checkin.html",
        active="send-checkin",
        is_sandbox=is_sandbox,
        instance_id=instance_id if is_sandbox else None,
        today=date.today().isoformat()
    )


# ========== ROUTE 2: PACKAGE LOOKUP ==========

@bp.route("/lookup", methods=["GET", "POST"])
@login_required
@require_cap("can_send")
def lookup():
    """Package Lookup - Track packages by tracking number"""
    instance_id, is_sandbox = get_instance_context()
    
    ctx = {
        "active": "send-lookup",
        "result": None,
        "error": None,
        "carrier": None,
        "carrier_url": None,
        "is_sandbox": is_sandbox,
        "instance_id": instance_id
    }
    
    if request.method == "POST":
        tracking_number = request.form.get("TrackingNumber", "").strip()
        
        if not tracking_number:
            ctx["error"] = "Please enter a tracking number."
        else:
            try:
                # Track the package
                tracker = TrackingService(current_app.config)
                result = tracker.track(tracking_number)
                
                if result.success:
                    ctx["result"] = result.to_dict()
                    ctx["carrier"] = result.carrier
                    ctx["carrier_url"] = CarrierDetector.get_carrier_url(result.carrier, tracking_number)
                    
                    # Record audit
                    cu = current_user()
                    record_audit(cu, "lookup_tracking", "send", f"Looked up tracking: {tracking_number}")
                else:
                    ctx["error"] = result.error or "Could not retrieve tracking information."
                    
            except Exception as e:
                logger.error(f"Lookup error: {e}", exc_info=True)
                ctx["error"] = f"Error: {str(e)}"
    
    return render_template("send/lookup.html", **ctx)


# ========== ROUTE 3: ADDRESS BOOK ==========

@bp.route("/address-book", methods=["GET", "POST"])
@login_required
@require_cap("can_send")
def address_book():
    """Address Book - Manage frequently used addresses"""
    instance_id, is_sandbox = get_instance_context()
    cu = current_user()
    service = AddressBookService(instance_id)  # Use middleware-set instance
    
    # Handle POST (add/edit)
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "add":
            address_data = {
                'recipient_name': request.form.get("RecipientName"),
                'recipient_company': request.form.get("RecipientCompany"),
                'recipient_phone': request.form.get("RecipientPhone"),
                'recipient_email': request.form.get("RecipientEmail"),
                'address_line1': request.form.get("AddressLine1"),
                'address_line2': request.form.get("AddressLine2"),
                'city': request.form.get("City"),
                'state': request.form.get("State"),
                'zip_code': request.form.get("ZipCode"),
                'notes': request.form.get("Notes")
            }
            
            address_id = service.add(address_data, cu['id'])
            if address_id:
                flash("✅ Address added to book!", "success")
                record_audit(cu, "add_address", "send", f"Added address: {address_data['recipient_name']}")
            else:
                flash("❌ Failed to add address", "danger")
                
        elif action == "edit":
            address_id = int(request.form.get("AddressID"))
            address_data = {
                'recipient_name': request.form.get("RecipientName"),
                'recipient_company': request.form.get("RecipientCompany"),
                'recipient_phone': request.form.get("RecipientPhone"),
                'recipient_email': request.form.get("RecipientEmail"),
                'address_line1': request.form.get("AddressLine1"),
                'address_line2': request.form.get("AddressLine2"),
                'city': request.form.get("City"),
                'state': request.form.get("State"),
                'zip_code': request.form.get("ZipCode"),
                'notes': request.form.get("Notes")
            }
            
            if service.update(address_id, address_data):
                flash("✅ Address updated!", "success")
                record_audit(cu, "update_address", "send", f"Updated address ID: {address_id}")
            else:
                flash("❌ Failed to update address", "danger")
                
        elif action == "delete":
            address_id = int(request.form.get("AddressID"))
            if service.delete(address_id):
                flash("✅ Address deleted!", "success")
                record_audit(cu, "delete_address", "send", f"Deleted address ID: {address_id}")
            else:
                flash("❌ Failed to delete address", "danger")
        
        return redirect(url_for("send.address_book"))
    
    # GET - fetch addresses
    sort_by = request.args.get("sort", "name")
    search_query = request.args.get("q", "")
    
    if search_query:
        addresses = service.search(search_query, limit=100)
    else:
        addresses = service.get_all(sort_by=sort_by)
    
    return render_template(
        "send/address_book.html",
        active="send-address-book",
        addresses=addresses,
        sort_by=sort_by,
        search_query=search_query,
        is_sandbox=is_sandbox,
        instance_id=instance_id
    )


# ========== ROUTE 4: ADDRESS LOOKUP/VALIDATION ==========

@bp.route("/address-lookup", methods=["GET", "POST"])
@login_required
@require_cap("can_send")
def address_lookup():
    """Address Lookup - Validate addresses using FedEx API"""
    instance_id, is_sandbox = get_instance_context()
    
    ctx = {
        "active": "send-address-lookup",
        "result": None,
        "error": None,
        "is_sandbox": is_sandbox,
        "instance_id": instance_id
    }
    
    if request.method == "POST":
        address_line1 = request.form.get("AddressLine1", "").strip()
        address_line2 = request.form.get("AddressLine2", "").strip()
        city = request.form.get("City", "").strip()
        state = request.form.get("State", "").strip()
        zip_code = request.form.get("ZipCode", "").strip()
        
        if not all([address_line1, city, state, zip_code]):
            ctx["error"] = "Please fill in all required fields."
        else:
            try:
                validator = AddressValidator(current_app.config)
                result = validator.validate(
                    address_line1, city, state, zip_code, address_line2
                )
                
                ctx["result"] = result
                
                # Record audit
                cu = current_user()
                record_audit(cu, "validate_address", "send", 
                           f"Validated: {address_line1}, {city}, {state}")
                
            except Exception as e:
                logger.error(f"Address validation error: {e}", exc_info=True)
                ctx["error"] = f"Validation error: {str(e)}"
    
    return render_template("send/address_lookup.html", **ctx)


# ========== ROUTE 6: SHIPPING MANIFEST ==========

@bp.route("/manifest")
@login_required
@require_cap("can_send")
def manifest():
    """Shipping Manifest - Live view of all packages with tracking"""
    instance_id, is_sandbox = get_instance_context()
    cu = current_user()
    
    # Filters
    status_filter = request.args.get("status", "")
    carrier_filter = request.args.get("carrier", "")
    search_query = request.args.get("q", "")
    
    try:
        with get_db_connection("send") as conn:
            cursor = conn.cursor()
            
            # Build WHERE conditions (instance_id added automatically by helper)
            conditions = []
            params = []
            
            if status_filter:
                conditions.append("tracking_status = %s")
                params.append(status_filter)
            
            if carrier_filter:
                conditions.append("carrier = %s")
                params.append(carrier_filter)
            
            if search_query:
                conditions.append("(tracking_number ILIKE %s OR recipient_name ILIKE %s OR package_id ILIKE %s)")
                like = f"%{search_query}%"
                params.extend([like, like, like])
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            # Use instance-aware query helper
            sql, params = build_select(
                table='package_manifest',
                columns='''
                    id, checkin_id, package_id, tracking_number,
                    carrier, tracking_status, tracking_status_description,
                    recipient_name, recipient_company,
                    package_type, estimated_delivery_date, actual_delivery_date,
                    location, submitter_name, created_at, last_tracked_at,
                    (SELECT COUNT(*) FROM tracking_events WHERE package_id = package_manifest.id) as event_count
                ''',
                where=where_clause,
                params=params,
                order_by='created_at DESC LIMIT 100'
            )
            
            cursor.execute(sql, params)
            packages = cursor.fetchall()
            cursor.close()

        # Format dates before passing to template
        formatted_packages = []
        for pkg in packages:
            pkg_dict = dict(pkg)
            
            # Convert date/datetime objects to strings
            if pkg_dict.get('estimated_delivery_date'):
                pkg_dict['estimated_delivery_date'] = pkg_dict['estimated_delivery_date'].isoformat()
            if pkg_dict.get('actual_delivery_date'):
                pkg_dict['actual_delivery_date'] = pkg_dict['actual_delivery_date'].isoformat()
            if pkg_dict.get('created_at'):
                pkg_dict['created_at'] = pkg_dict['created_at'].isoformat()
            if pkg_dict.get('last_tracked_at'):
                pkg_dict['last_tracked_at'] = pkg_dict['last_tracked_at'].isoformat()
            
            formatted_packages.append(pkg_dict)

        record_audit(cu, "view_manifest", "send", "Viewed shipping manifest")

        return render_template(
            "send/manifest.html",
            active="send-manifest",
            packages=formatted_packages,
            status_filter=status_filter,
            carrier_filter=carrier_filter,
            search_query=search_query,
            is_sandbox=is_sandbox,
            instance_id=instance_id
        )
        
    except Exception as e:
        logger.error(f"Manifest error: {e}", exc_info=True)
        flash(f"Error loading manifest: {str(e)}", "danger")
        return redirect(url_for("send.checkin"))


# ========== ROUTE 7: SHIPPING REPORT ==========

@bp.route("/report", methods=["GET"])
@login_required
@require_cap("can_send")
def report():
    """Report generation page"""
    cu = current_user()
    instance_id, is_sandbox = get_instance_context()
    
    # Filters
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    carrier_filter = request.args.get("carrier", "")
    status_filter = request.args.get("status", "")
    location_filter = request.args.get("location", "")
    search_query = request.args.get("q", "")
    
    # Default date range: last 30 days
    from datetime import timedelta
    if not date_from:
        date_from = (date.today() - timedelta(days=30)).isoformat()
    if not date_to:
        date_to = date.today().isoformat()
    
    try:
        with get_db_connection("send") as conn:
            cursor = conn.cursor()
            
            # Build WHERE conditions (instance_id added automatically)
            conditions = [
                "DATE(created_at) >= %s",
                "DATE(created_at) <= %s"
            ]
            params = [date_from, date_to]
            
            if carrier_filter:
                conditions.append("carrier = %s")
                params.append(carrier_filter)
            
            if status_filter:
                conditions.append("tracking_status = %s")
                params.append(status_filter)
            
            if location_filter:
                conditions.append("location = %s")
                params.append(location_filter)
            
            if search_query:
                conditions.append("(tracking_number ILIKE %s OR recipient_name ILIKE %s)")
                like = f"%{search_query}%"
                params.extend([like, like])
            
            where_clause = " AND ".join(conditions)
            
            # Use instance-aware query helper
            sql, params = build_select(
                table='package_manifest',
                columns='''
                    checkin_id, package_id, tracking_number,
                    carrier, tracking_status,
                    recipient_name, recipient_company, recipient_address,
                    package_type, shipping_method,
                    estimated_delivery_date, actual_delivery_date,
                    location, submitter_name, created_at
                ''',
                where=where_clause,
                params=params,
                order_by='created_at DESC'
            )
            
            cursor.execute(sql, params)
            results = cursor.fetchall()
            cursor.close()

        # Format dates before passing to template
        formatted_results = []
        for row in results:
            row_dict = dict(row)
            
            # Convert date/datetime objects to strings
            if row_dict.get('estimated_delivery_date'):
                row_dict['estimated_delivery_date'] = row_dict['estimated_delivery_date'].isoformat()
            if row_dict.get('actual_delivery_date'):
                row_dict['actual_delivery_date'] = row_dict['actual_delivery_date'].isoformat()
            if row_dict.get('created_at'):
                row_dict['created_at'] = row_dict['created_at'].isoformat()
            
            formatted_results.append(row_dict)

        record_audit(cu, "view_report", "send", f"Viewed shipping report: {date_from} to {date_to}")

        return render_template(
            "send/report.html",
            active="send-report",
            results=formatted_results,
            date_from=date_from,
            date_to=date_to,
            carrier_filter=carrier_filter,
            status_filter=status_filter,
            location_filter=location_filter,
            search_query=search_query,
            is_sandbox=is_sandbox,
            instance_id=instance_id
        )
        
    except Exception as e:
        logger.error(f"Report error: {e}", exc_info=True)
        flash(f"Error loading report: {str(e)}", "danger")
        return redirect(url_for("send.checkin"))


# ========== DELETE PACKAGE API ==========

@bp.route("/api/package/<int:package_id>/delete", methods=["DELETE"], endpoint="delete_package")
@require_cap("can_send")
def delete_package(package_id):
    """Delete a package (L1+ only)"""
    try:
        cu = current_user()
        
        # Check if user has L1+ permissions
        user_level = cu.get('permission_level', '')
        allowed_levels = ['L1', 'L2', 'L3', 'S1']
        
        if user_level not in allowed_levels:
            return jsonify({
                'success': False, 
                'error': 'Insufficient permissions. L1+ required.'
            }), 403
        
        # Get package info before deleting (for audit log)
        with get_db_connection("send") as conn:
            cursor = conn.cursor()
            
            # Use instance-aware query
            where_clause, params = add_instance_filter("id = %s", [package_id])
            
            cursor.execute(f"""
                SELECT 
                    package_id,
                    tracking_number,
                    recipient_name,
                    carrier
                FROM package_manifest
                WHERE {where_clause}
            """, params)
            
            pkg = cursor.fetchone()
            
            if not pkg:
                return jsonify({'success': False, 'error': 'Package not found'}), 404
            
            package_id_str = pkg['package_id']
            tracking_number = pkg['tracking_number']
            recipient_name = pkg['recipient_name']
            carrier = pkg['carrier']
            
            # Delete the package (instance filter ensures we only delete from our instance)
            cursor.execute(f"DELETE FROM package_manifest WHERE {where_clause}", params)
            
            rows_deleted = cursor.rowcount
            conn.commit()
            cursor.close()
        
        if rows_deleted > 0:
            # Log audit
            record_audit(
                cu, 
                "delete_package", 
                "send", 
                f"Deleted package {package_id_str} (Tracking: {tracking_number}, Recipient: {recipient_name}, Carrier: {carrier})"
            )
            
            logger.info(f"User {cu.get('username')} deleted package {package_id_str}")
            
            return jsonify({
                'success': True,
                'message': f'Package {package_id_str} deleted successfully'
            }), 200
        else:
            return jsonify({'success': False, 'error': 'Package not found'}), 404
            
    except Exception as e:
        logger.error(f"Delete package error for package {package_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route("/api/validate-tracking", methods=["POST"])
@login_required
@require_cap("can_send")
def validate_tracking():
    """
    Validate tracking number and auto-populate form fields.
    Fetches shipment data from FedEx API.
    """
    cu = current_user()
    instance_id, is_sandbox = get_instance_context()
    
    try:
        data = request.get_json()
        tracking_number = data.get('tracking_number', '').strip()
        carrier = data.get('carrier', 'FedEx').strip().upper()
        
        if not tracking_number:
            return jsonify({"success": False, "error": "Tracking number required"}), 400
        
        # Only support FedEx for now
        if carrier != 'FEDEX':
            return jsonify({
                "success": False,
                "error": f"Auto-populate only supported for FedEx. Please enter details manually for {carrier}."
            }), 400
        
        # Fetch tracking data from FedEx
        from app.services.shipping.fedex_tracking import FedExTrackingService
        
        tracking_service = FedExTrackingService(current_app.config)
        tracking_data = tracking_service.track_shipment(tracking_number)
        
        if not tracking_data or not tracking_data.get('success'):
            return jsonify({
                "success": False,
                "error": "Could not retrieve tracking information. Please enter details manually.",
                "details": tracking_data.get('error', 'Unknown error')
            }), 404
        
        # Extract shipment details
        shipment = tracking_data.get('shipment', {})
        
        # Parse recipient information
        recipient = shipment.get('recipient', {})
        recipient_address = shipment.get('recipient_address', {})
        
        # Parse package information
        package_info = shipment.get('package', {})
        
        # Build auto-populated data
        populated_data = {
            # Recipient info
            'recipient_name': recipient.get('name', ''),
            'recipient_company': recipient.get('company', ''),
            'recipient_phone': recipient.get('phone', ''),
            'recipient_email': recipient.get('email', ''),
            
            # Address
            'recipient_address': recipient_address.get('street', ''),
            'recipient_city': recipient_address.get('city', ''),
            'recipient_state': recipient_address.get('state', ''),
            'recipient_zip': recipient_address.get('zip', ''),
            
            # Package details
            'package_type': package_info.get('type', 'Box'),
            'package_weight': package_info.get('weight', ''),
            'carrier': 'FedEx',
            'service_type': shipment.get('service_type', ''),
            'delivery_date': shipment.get('estimated_delivery', ''),
            
            # Status
            'status': shipment.get('status', 'In Transit'),
            'status_description': shipment.get('status_description', ''),
            
            # Additional info
            'origin': shipment.get('origin', ''),
            'destination': shipment.get('destination', '')
        }
        
        # Record audit
        record_audit(
            cu, "validate_tracking", "send",
            f"Auto-populated from tracking {tracking_number}"
        )
        
        return jsonify({
            "success": True,
            "message": "✓ Tracking data retrieved successfully",
            "data": populated_data,
            "tracking_info": {
                'tracking_number': tracking_number,
                'carrier': 'FedEx',
                'status': shipment.get('status', ''),
                'last_update': shipment.get('last_update', '')
            }
        })
        
    except Exception as e:
        logger.error(f"Tracking validation error: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": "Error retrieving tracking information. Please enter details manually.",
            "details": str(e)
        }), 500

# ========== LEGACY ROUTES ==========

@bp.route("/tracking", methods=["GET", "POST"])
@login_required
@require_cap("can_send")
def tracking_legacy():
    """Legacy route - redirect to new lookup"""
    return redirect(url_for("send.lookup", **request.args))


@bp.route("/next-id")
@login_required
def get_next_id():
    """Get next package ID for a given type (AJAX helper)"""
    pkg_type = request.args.get('type', 'Box')
    next_id = peek_next_package_id(pkg_type)
    return jsonify({'next_id': next_id})