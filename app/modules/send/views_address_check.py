# app/modules/send/views_address_check.py
"""
Address Check Tab - Part of Send Module
Validates addresses using FedEx API
"""

from flask import render_template, request, jsonify, flash, redirect, url_for
from app.modules.auth.security import login_required, current_user, record_audit
from app.modules.send.google_address_validator import GoogleAddressValidator
from app.core.instance_context import get_current_instance

def register_address_routes(send_bp):
    """Register address validation routes with the send blueprint."""
    
    @send_bp.route("/address-check")
    @login_required
    def address_check():
        """Display the Address Check interface."""
        cu = current_user()
        instance_id = get_current_instance()
        
        # Get recent validations for this instance (optional)
        recent_validations = []
        
        return render_template(
            "send/address_check.html",
            active="send",
            page="address_check",
            recent_validations=recent_validations,
            instance_id=instance_id
        )
    
    @send_bp.route("/api/validate-address", methods=["POST"])
    @login_required
    def validate_address():
        """API endpoint to validate an address."""
        cu = current_user()
        
        # Get address data from request
        data = request.get_json() or {}
        
        # Extract address fields
        address_data = {
            'street_lines': [],
            'city': data.get('city', '').strip(),
            'state_code': data.get('state', '').strip().upper(),
            'postal_code': data.get('postal_code', '').strip(),
            'country_code': data.get('country', 'US').upper(),
            'company': data.get('company', '').strip()
        }
        
        # Handle street lines
        street1 = data.get('street1', '').strip()
        street2 = data.get('street2', '').strip()
        
        if street1:
            address_data['street_lines'].append(street1)
        if street2:
            address_data['street_lines'].append(street2)
        
        # Validate required fields
        if not address_data['street_lines']:
            return jsonify({
                'success': False,
                'error': 'Street address is required'
            }), 400
        
        if not address_data['city']:
            return jsonify({
                'success': False,
                'error': 'City is required'
            }), 400
        
        if not address_data['postal_code']:
            return jsonify({
                'success': False,
                'error': 'Postal code is required'
            }), 400
        
        # Perform validation
        validator = GoogleAddressValidator()
        result = validator.validate(address_data)
        
        # Log the validation
        record_audit(
            cu, 
            "validate_address", 
            "send",
            f"Validated address: {address_data['city']}, {address_data['state_code']}"
        )
        
        return jsonify(result)
    
    @send_bp.route("/api/save-validated-address", methods=["POST"])
    @login_required
    def save_validated_address():
        """Save a validated address to the address book."""
        cu = current_user()
        instance_id = get_current_instance()
        
        data = request.get_json() or {}
        
        # Extract address data
        address_type = data.get('type', 'shipping')
        nickname = data.get('nickname', '')
        company = data.get('company', '')
        contact_name = data.get('contact_name', '')
        phone = data.get('phone', '')
        email = data.get('email', '')
        
        # Address fields
        street1 = data.get('street1', '')
        street2 = data.get('street2', '')
        city = data.get('city', '')
        state = data.get('state', '')
        postal_code = data.get('postal_code', '')
        country = data.get('country', 'US')
        
        # Classification from FedEx
        classification = data.get('classification', '')
        
        from app.core.database import get_db_connection
        
        try:
            with get_db_connection('send') as conn:
                cursor = conn.cursor()
                
                # Insert into address book
                cursor.execute("""
                    INSERT INTO address_book (
                        instance_id, nickname, company, contact_name,
                        street1, street2, city, state, postal_code, country,
                        phone, email, address_type, classification,
                        is_validated, created_by
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, TRUE, %s
                    ) RETURNING id
                """, (
                    instance_id, nickname, company, contact_name,
                    street1, street2, city, state, postal_code, country,
                    phone, email, address_type, classification,
                    cu['id']
                ))
                
                new_id = cursor.fetchone()['id']
                conn.commit()
                
                record_audit(
                    cu,
                    "save_validated_address",
                    "send",
                    f"Saved validated address: {nickname or company}"
                )
                
                return jsonify({
                    'success': True,
                    'message': 'Address saved to address book',
                    'id': new_id
                })
                
        except Exception as e:
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @send_bp.route("/api/batch-validate", methods=["POST"])
    @login_required
    def batch_validate():
        """Validate multiple addresses at once (CSV upload)."""
        cu = current_user()
        
        data = request.get_json() or {}
        addresses = data.get('addresses', [])
        
        if not addresses:
            return jsonify({
                'success': False,
                'error': 'No addresses provided'
            }), 400
        
        if len(addresses) > 100:
            return jsonify({
                'success': False,
                'error': 'Maximum 100 addresses per batch'
            }), 400
        
        # Process addresses
        validator = GoogleAddressValidator()
        results = []

        for idx, addr in enumerate(addresses):
            address_data = {
                'street_lines': [addr.get('street1', '')],
                'city': addr.get('city', ''),
                'state_code': addr.get('state', ''),
                'postal_code': addr.get('postal_code', ''),
                'country_code': addr.get('country', 'US')
            }
            
            if addr.get('street2'):
                address_data['street_lines'].append(addr['street2'])
            
            result = validator.validate(address_data)
            result['index'] = idx
            result['reference'] = addr.get('reference', '')
            results.append(result)
        
        record_audit(
            cu,
            "batch_validate_addresses",
            "send",
            f"Validated {len(addresses)} addresses"
        )
        
        return jsonify({
            'success': True,
            'results': results,
            'total': len(addresses),
            'valid': sum(1 for r in results if r.get('is_valid')),
            'invalid': sum(1 for r in results if not r.get('is_valid'))
        })
