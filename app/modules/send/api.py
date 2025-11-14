"""
Send Module API Endpoints
AJAX endpoints for dynamic features
"""

from flask import jsonify, request, current_app
from . import bp
from app.modules.auth.security import require_cap, current_user
from app.modules.auth.security import record_audit
from app.services.tracking.tracker import TrackingService
from app.services.address.book import AddressBookService
from app.services.address.validator import AddressValidator
from app.utils.carrier_detector import CarrierDetector
from app.core.database import get_db_connection
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
def validate_tracking():
    """
    Validate tracking number and return info
    
    POST /send/api/validate-tracking
    Body: {"tracking_number": "...", "carrier": "FEDEX"}
    """
    try:
        data = request.get_json()
        tracking_number = data.get('tracking_number', '').strip()
        carrier = data.get('carrier', 'FEDEX').upper()
        
        if not tracking_number:
            return jsonify({'success': False, 'error': 'Tracking number required'}), 400
        
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
            return jsonify({'success': False, 'error': 'Unsupported carrier'}), 400
        
        result = tracker.track(tracking_number)
        
        if result.success:
            return jsonify({
                'success': True,
                'status': result.status,
                'status_description': result.status_description,
                'recipient_name': None,  # FedEx API doesn't return recipient name
                'recipient_address': result.actual_delivery,
                'estimated_delivery': result.estimated_delivery.isoformat() if result.estimated_delivery else None
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': result.error_message or 'Tracking failed'
            }), 200
            
    except Exception as e:
        logger.error(f"Tracking validation error: {e}", exc_info=True)
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
    
@bp.route("/api/package/<int:package_id>/delete", methods=["DELETE"])
@require_cap("can_send")
def delete_package(package_id):
    """
    Delete a package (L1+ only)
    
    DELETE /send/api/package/<id>/delete
    """
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
            
            cursor.execute("""
                SELECT 
                    package_id,
                    tracking_number,
                    recipient_name,
                    carrier
                FROM package_manifest
                WHERE id = %s
            """, (package_id,))
            
            pkg = cursor.fetchone()
            
            if not pkg:
                return jsonify({'success': False, 'error': 'Package not found'}), 404
            
            package_id_str = pkg['package_id']
            tracking_number = pkg['tracking_number']
            recipient_name = pkg['recipient_name']
            carrier = pkg['carrier']
            
            # Delete the package
            cursor.execute("DELETE FROM package_manifest WHERE id = %s", (package_id,))
            
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