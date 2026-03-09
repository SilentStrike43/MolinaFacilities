"""
Send Module API Endpoints
AJAX endpoints for dynamic features
"""

from flask import jsonify, request, current_app
from . import bp
from app.modules.auth.security import require_cap, current_user, login_required
from app.modules.auth.security import record_audit
from app.services.tracking.tracker import TrackingService
from app.services.address.book import AddressBookService
from app.services.address.validator import AddressValidator
from app.utils.carrier_detector import CarrierDetector
from app.core.database import get_db_connection
from app.core.instance_context import get_current_instance
from app.modules.send.models import next_checkin_id, next_package_id
import logging

logger = logging.getLogger(__name__)


@bp.route("/api/track", methods=["POST"])
@require_cap("can_send")
def api_track():
    """
    API: Track a package by tracking number
    
    POST /send/api/track
    Body: {"tracking_number": "...", "carrier": "USPS" (optional)}
    
    Returns: TrackingResult as JSON
    """
    try:
        data = request.get_json()
        tracking_number = data.get('tracking_number', '').strip()
        carrier = data.get('carrier')
        
        if not tracking_number:
            return jsonify({'error': 'Tracking number required'}), 400
        
        # Auto-detect carrier if not provided
        if not carrier:
            carrier = CarrierDetector.detect(tracking_number)
        
        # Track the package
        tracker = TrackingService(current_app.config)
        result = tracker.track(tracking_number, carrier)
        
        # Log the API call
        cu = current_user()
        try:
            with get_db_connection("send") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO carrier_api_calls (
                        tracking_number, carrier, success, 
                        error_message, called_by, called_at
                    ) VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                """, (tracking_number, carrier, result.success, result.error, cu['id']))
                conn.commit()
                cursor.close()
        except Exception as e:
            logger.warning(f"Failed to log API call: {e}")
        
        return jsonify(result.to_dict()), 200
        
    except Exception as e:
        logger.error(f"API track error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route("/api/address-book/search", methods=["GET"])
@require_cap("can_send")
def api_address_search():
    """
    API: Search address book
    
    GET /send/api/address-book/search?q=query
    
    Returns: List of matching addresses
    """
    try:
        cu = current_user()
        query = request.args.get('q', '').strip()
        
        if not query or len(query) < 2:
            return jsonify([]), 200
        
        service = AddressBookService(cu['instance_id'])
        results = service.search(query, limit=10)
        
        return jsonify(results), 200
        
    except Exception as e:
        logger.error(f"Address search error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route("/api/address-book/<int:address_id>", methods=["GET"])
@require_cap("can_send")
def api_address_get(address_id):
    """
    API: Get address by ID
    
    GET /send/api/address-book/123
    
    Returns: Address details
    """
    try:
        cu = current_user()
        service = AddressBookService(cu['instance_id'])
        address = service.get_by_id(address_id)
        
        if not address:
            return jsonify({'error': 'Address not found'}), 404
        
        return jsonify(address), 200
        
    except Exception as e:
        logger.error(f"Get address error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route("/api/address-validate", methods=["POST"])
@require_cap("can_send")
def api_address_validate():
    """
    API: Validate an address using FedEx
    
    POST /send/api/address-validate
    Body: {
        "address_line1": "...",
        "city": "...",
        "state": "...",
        "zip_code": "...",
        "address_line2": "..." (optional)
    }
    
    Returns: Validation result
    """
    try:
        data = request.get_json()
        
        required = ['address_line1', 'city', 'state', 'zip_code']
        for field in required:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        validator = AddressValidator(current_app.config)
        result = validator.validate(
            data['address_line1'],
            data['city'],
            data['state'],
            data['zip_code'],
            data.get('address_line2'),
            data.get('country', 'US')
        )
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Address validation error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route("/api/carrier/detect", methods=["POST"])
@require_cap("can_send")
def api_carrier_detect():
    """
    API: Detect carrier from tracking number
    
    POST /send/api/carrier/detect
    Body: {"tracking_number": "..."}
    
    Returns: {"carrier": "USPS", "carrier_name": "..."}
    """
    try:
        data = request.get_json()
        tracking_number = data.get('tracking_number', '').strip()
        
        if not tracking_number:
            return jsonify({'error': 'Tracking number required'}), 400
        
        carrier = CarrierDetector.detect(tracking_number)
        carrier_name = CarrierDetector.get_carrier_name(carrier)
        carrier_url = CarrierDetector.get_carrier_url(carrier, tracking_number)
        
        return jsonify({
            'carrier': carrier,
            'carrier_name': carrier_name,
            'carrier_url': carrier_url
        }), 200
        
    except Exception as e:
        logger.error(f"Carrier detection error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route("/api/package/<int:package_id>/track-now", methods=["POST"])
@require_cap("can_send")
def track_package_now(package_id):
    """
    Immediately update tracking for a specific package
    
    POST /send/api/package/<id>/track-now
    """
    try:
        cu = current_user()
        
        # Get package info from database
        with get_db_connection("send") as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    package_id,
                    tracking_number,
                    carrier
                FROM package_manifest
                WHERE id = %s
            """, (package_id,))
            
            pkg = cursor.fetchone()
            
            if not pkg:
                return jsonify({'success': False, 'error': 'Package not found'}), 404
            
            tracking_number = pkg['tracking_number']
            carrier = pkg['carrier']
            pkg_id = pkg['package_id']
            
            cursor.close()
        
        if not tracking_number:
            return jsonify({'success': False, 'error': 'No tracking number'}), 400
        
        logger.info(f"Manual tracking refresh for package ID {package_id}: {tracking_number} ({carrier})")
        
        # Track the package
        if carrier == 'FEDEX':
            from app.services.tracking.fedex import FedExTracker
            from flask import current_app
            tracker = FedExTracker(current_app.config)
        elif carrier == 'USPS':
            from app.services.tracking.usps import USPSCarrier
            from flask import current_app
            tracker = USPSCarrier(current_app.config)
        elif carrier == 'UPS':
            from app.services.tracking.ups import UPSCarrier
            from flask import current_app
            tracker = UPSCarrier(current_app.config)
        else:
            return jsonify({'success': False, 'error': f'Unsupported carrier: {carrier}'}), 400
        
        result = tracker.track(tracking_number)
        
        if result.success:
    # Update database with new tracking info
            with get_db_connection("send") as conn:
                cursor = conn.cursor()
                
                from datetime import datetime
                
                cursor.execute("""
                    UPDATE package_manifest
                    SET 
                        tracking_status = %s,
                        tracking_status_description = %s,
                        estimated_delivery_date = %s,
                        actual_delivery_date = %s,
                        last_tracked_at = %s,
                        tracking_last_updated = %s
                    WHERE id = %s
                """, (
                    result.status,
                    result.status_description,
                    result.estimated_delivery,
                    result.actual_delivery,
                    datetime.now(),
                    datetime.now(),
                    package_id
                ))
                
                rows_updated = cursor.rowcount
                conn.commit()
                cursor.close()
            
            # Log audit
            record_audit(cu, "tracking_refresh", "send", f"Manually refreshed tracking for {pkg_id}")
            
            logger.info(f"Successfully updated tracking for package {package_id}: {result.status} (rows updated: {rows_updated})")
            
            return jsonify({
                'success': True,
                'status': result.status,
                'status_description': result.status_description,
                'estimated_delivery': result.estimated_delivery.isoformat() if result.estimated_delivery else None,
                'rows_updated': rows_updated
            }), 200
        else:
            logger.warning(f"Tracking failed for package {package_id}: {result.error_message}")
            return jsonify({
                'success': False,
                'error': result.error_message or 'Tracking failed'
            }), 200
            
    except Exception as e:
        logger.error(f"Track now error for package {package_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route("/api/validate-tracking", methods=["POST"])
@require_cap("can_send")
def api_validate_tracking():
    """
    Validate a tracking number and return shipment data for form auto-population.
    Auto-detects carrier; handles DHL and UNKNOWN gracefully without crashing.

    POST /send/api/validate-tracking
    Body: {"tracking_number": "...", "carrier": "FEDEX"|""|"AUTO"}
    """
    try:
        cu = current_user()
        data = request.get_json() or {}
        tracking_number = data.get('tracking_number', '').strip()
        carrier_hint = (data.get('carrier') or '').upper().strip()

        if not tracking_number:
            return jsonify({'success': False, 'error': 'No tracking number provided'}), 400

        # Auto-detect carrier if form left on blank/auto
        carrier = CarrierDetector.detect(tracking_number) if not carrier_hint or carrier_hint == 'AUTO' else carrier_hint
        carrier_url = CarrierDetector.get_carrier_url(carrier, tracking_number)

        # DHL detected but no API configured — still useful to identify it
        if carrier == 'DHL':
            return jsonify({
                'success': True,
                'carrier_detected': 'DHL',
                'message': '✓ DHL tracking number identified. Enter recipient details manually.',
                'data': {
                    'carrier': 'DHL',
                    'tracking_number': tracking_number,
                    'status': 'UNKNOWN',
                    'limited_data': True,
                    'note': 'DHL tracking API not configured. Carrier has been identified.'
                },
                'carrier_url': carrier_url,
                'tracking_events': []
            })

        if carrier == 'UNKNOWN':
            return jsonify({
                'success': False,
                'carrier_detected': 'UNKNOWN',
                'error': 'Could not identify carrier from this tracking number. Please select the carrier manually.'
            })

        # Call carrier API
        tracker = TrackingService(current_app.config)
        result = tracker.track(tracking_number, carrier)

        if not result.success:
            return jsonify({
                'success': False,
                'carrier_detected': carrier,
                'error': result.error or 'Could not retrieve tracking information. Please enter details manually.'
            })

        dest = result.destination or ''
        dest_parts = [p.strip() for p in dest.split(',')] if dest else []

        populated_data = {
            'carrier': carrier,
            'tracking_number': tracking_number,
            'status': result.status,
            'status_description': result.status_description,
            'estimated_delivery': result.estimated_delivery.strftime('%Y-%m-%d') if result.estimated_delivery else None,
            'actual_delivery': result.actual_delivery,
            'origin': result.origin,
            'destination': dest,
            'service_type': result.service_type or 'Standard',
            'recipient_city': dest_parts[0] if len(dest_parts) > 0 else '',
            'recipient_state': dest_parts[1] if len(dest_parts) > 1 else '',
            'limited_data': True,
            'note': f'{carrier} tracking provides limited recipient details for privacy. Please complete remaining fields.'
        }

        record_audit(cu, "validate_tracking_success", "send",
                     f"Validated tracking: {tracking_number} ({carrier})")

        try:
            with get_db_connection("send") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO carrier_api_calls (
                        tracking_number, carrier, success, response_data, called_by, called_at
                    ) VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                """, (tracking_number, carrier, True, str(result.to_dict()), cu['id']))
                conn.commit()
                cursor.close()
        except Exception:
            pass  # API call logging is optional

        return jsonify({
            'success': True,
            'carrier_detected': carrier,
            'message': f'✓ {carrier} tracking validated — Status: {result.status}',
            'data': populated_data,
            'carrier_url': carrier_url,
            'tracking_events': result.events[:3] if result.events else []
        })

    except Exception as e:
        logger.error(f"Tracking validation error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Error retrieving tracking information.'}), 500


@bp.route("/api/add-to-manifest", methods=["POST"])
@login_required
@require_cap("can_send")
def api_add_to_manifest():
    """
    Add one or more tracking numbers to the manifest directly from the lookup page.
    Each entry receives its own CheckIn ID and Package ID.

    POST /send/api/add-to-manifest
    Body: {"entries": [{"tracking_number": "...", "carrier": "...", "status": "...",
                        "status_description": "...", "estimated_delivery": "YYYY-MM-DD"}]}
    """
    try:
        cu = current_user()
        instance_id = get_current_instance()
        data = request.get_json() or {}
        entries = data.get('entries', [])

        if not entries:
            return jsonify({'success': False, 'error': 'No tracking numbers provided'}), 400
        if len(entries) > 50:
            return jsonify({'success': False, 'error': 'Maximum 50 entries per request'}), 400

        added = []
        with get_db_connection("send") as conn:
            cursor = conn.cursor()
            for entry in entries:
                tn = (entry.get('tracking_number') or '').strip()
                if not tn:
                    continue
                carrier = (entry.get('carrier') or 'UNKNOWN').upper()
                status = entry.get('status') or 'UNKNOWN'
                status_desc = entry.get('status_description') or ''
                est_delivery = entry.get('estimated_delivery') or None

                chk_id = next_checkin_id()
                pkg_id = next_package_id('Box')

                cursor.execute("""
                    INSERT INTO package_manifest (
                        instance_id, created_by, tracking_number, carrier,
                        checkin_id, package_id, tracking_status,
                        tracking_status_description, estimated_delivery_date,
                        status, ts_utc
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'received', CURRENT_TIMESTAMP)
                    RETURNING id
                """, (instance_id, cu['id'], tn, carrier, chk_id, pkg_id,
                      status, status_desc, est_delivery))
                row = cursor.fetchone()
                added.append({'tracking_number': tn, 'checkin_id': chk_id,
                              'package_id': pkg_id, 'db_id': row['id']})
                record_audit(cu, "add_to_manifest_from_lookup", "send",
                             f"Added {tn} ({carrier}) to manifest as {chk_id}")
            conn.commit()
            cursor.close()

        return jsonify({'success': True, 'added': len(added), 'results': added})

    except Exception as e:
        logger.error(f"Add-to-manifest error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route("/api/bulk-lookup", methods=["POST"])
@login_required
@require_cap("can_send")
def api_bulk_lookup():
    """
    Look up multiple tracking numbers in one request.

    POST /send/api/bulk-lookup
    Body: {"tracking_numbers": ["...", "..."]}
    """
    try:
        cu = current_user()
        data = request.get_json() or {}
        raw_numbers = data.get('tracking_numbers', [])
        tracking_numbers = [t.strip() for t in raw_numbers if t.strip()]

        if not tracking_numbers:
            return jsonify({'success': False, 'error': 'No tracking numbers provided'}), 400
        if len(tracking_numbers) > 50:
            return jsonify({'success': False, 'error': 'Maximum 50 tracking numbers per batch'}), 400

        tracker = TrackingService(current_app.config)
        results = []

        for tn in tracking_numbers:
            carrier = CarrierDetector.detect(tn)
            carrier_url = CarrierDetector.get_carrier_url(carrier, tn)

            if carrier in ('DHL', 'UNKNOWN'):
                results.append({
                    'tracking_number': tn,
                    'carrier': carrier,
                    'success': False,
                    'status': 'UNKNOWN',
                    'error': 'DHL API not configured — check DHL website' if carrier == 'DHL' else 'Unknown carrier format',
                    'carrier_url': carrier_url
                })
                continue

            try:
                result = tracker.track(tn, carrier)
                r = result.to_dict() if hasattr(result, 'to_dict') else {}
                r['success'] = result.success
                r['carrier_url'] = carrier_url
                if result.estimated_delivery and hasattr(result.estimated_delivery, 'strftime'):
                    r['estimated_delivery'] = result.estimated_delivery.strftime('%Y-%m-%d')
                results.append(r)
            except Exception as ex:
                results.append({
                    'tracking_number': tn, 'carrier': carrier,
                    'success': False, 'error': str(ex), 'carrier_url': carrier_url
                })

        record_audit(cu, "bulk_lookup", "send", f"Bulk lookup: {len(tracking_numbers)} numbers")

        return jsonify({
            'success': True,
            'results': results,
            'total': len(results),
            'found': sum(1 for r in results if r.get('success'))
        })

    except Exception as e:
        logger.error(f"Bulk lookup error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route("/api/package/<int:package_id>", methods=["GET"])
@require_cap("can_send")
def api_package_get(package_id):
    """
    API: Get package details with tracking events
    
    GET /send/api/package/123
    
    Returns: Package details + tracking events
    """
    try:
        with get_db_connection("send") as conn:
            cursor = conn.cursor()
            
            # Get package details
            cursor.execute("""
                SELECT 
                    id, checkin_id, package_id, tracking_number,
                    carrier, tracking_status, tracking_status_description,
                    recipient_name, recipient_company, recipient_address,
                    package_type, estimated_delivery_date, actual_delivery_date,
                    delivered_to, delivery_signature, location,
                    submitter_name, created_at, last_tracked_at
                FROM package_manifest
                WHERE id = %s
            """, (package_id,))
            
            package = cursor.fetchone()
            
            if not package:
                cursor.close()
                return jsonify({'error': 'Package not found'}), 404
            
            # Get tracking events
            cursor.execute("""
                SELECT 
                    event_timestamp,
                    status_code,
                    status_description,
                    location_full
                FROM tracking_events
                WHERE package_id = %s
                ORDER BY event_timestamp DESC
            """, (package_id,))
            
            events = cursor.fetchall()
            cursor.close()
        
        result = dict(package)
        result['events'] = [dict(e) for e in events]
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Get package error: {str(e)}")
        return jsonify({'error': str(e)}), 500
    
