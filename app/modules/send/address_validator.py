# app/modules/send/address_validator.py - FIXED VERSION
"""
Address Validation using FedEx API
Validates and standardizes addresses for shipping
FIXED: Proper database connection handling and error management
"""

import os
import json
import logging
import requests
from typing import Dict, List, Optional
from flask import current_app
from app.core.database import get_db_connection

logger = logging.getLogger(__name__)


class FedExAddressValidator:
    """Handle FedEx Address Validation API calls."""
    
    def __init__(self):
        # FedEx API credentials from environment/config
        self.client_id = os.getenv('FEDEX_CLIENT_ID')
        self.client_secret = os.getenv('FEDEX_CLIENT_SECRET')
        self.account_number = os.getenv('FEDEX_ACCOUNT_NUMBER')
        
        # API endpoints
        self.auth_url = "https://apis.fedex.com/oauth/token"
        self.validate_url = "https://apis.fedex.com/address/v1/addresses/resolve"
        
        # Use sandbox for testing
        if os.getenv('FEDEX_ENV', 'sandbox') == 'sandbox':
            self.auth_url = "https://apis-sandbox.fedex.com/oauth/token"
            self.validate_url = "https://apis-sandbox.fedex.com/address/v1/addresses/resolve"
        
        self.access_token = None
    
    def get_access_token(self) -> Optional[str]:
        """Get OAuth 2.0 access token from FedEx."""
        if self.access_token:
            return self.access_token
        
        try:
            response = requests.post(
                self.auth_url,
                data={
                    'grant_type': 'client_credentials',
                    'client_id': self.client_id,
                    'client_secret': self.client_secret
                },
                headers={
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get('access_token')
                return self.access_token
            else:
                logger.error(f"FedEx Auth Error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"FedEx Auth Exception: {str(e)}")
            return None
    
    def validate_address(self, address_data: Dict) -> Dict:
        """
        Validate an address using FedEx API.
        
        Args:
            address_data: Dictionary containing address fields
                - street_lines: List of street address lines
                - city: City name
                - state_code: State/Province code
                - postal_code: ZIP/Postal code
                - country_code: Country code (US, CA, etc.)
                - company: Optional company name
        
        Returns:
            Dict with validation results and suggestions
        """
        token = self.get_access_token()
        if not token:
            return {
                'success': False,
                'error': 'Unable to authenticate with FedEx API'
            }
        
        # Build request payload
        payload = {
            "addressesToValidate": [{
                "address": {
                    "streetLines": address_data.get('street_lines', []),
                    "city": address_data.get('city', ''),
                    "stateOrProvinceCode": address_data.get('state_code', ''),
                    "postalCode": address_data.get('postal_code', ''),
                    "countryCode": address_data.get('country_code', 'US')
                }
            }]
        }
        
        if address_data.get('company'):
            payload["addressesToValidate"][0]["address"]["companyName"] = address_data['company']
        
        try:
            response = requests.post(
                self.validate_url,
                json=payload,
                headers={
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json',
                    'X-Customer-Transaction-Id': 'address-validation',
                    'X-locale': 'en_US'
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                return self._parse_validation_response(result, address_data)
            else:
                return {
                    'success': False,
                    'error': f'FedEx API Error: {response.status_code}',
                    'details': response.text
                }
                
        except Exception as e:
            logger.error(f"FedEx validation error: {str(e)}")
            return {
                'success': False,
                'error': f'Validation Exception: {str(e)}'
            }
    
    def _parse_validation_response(self, response: Dict, original: Dict) -> Dict:
        """Parse FedEx validation response into a user-friendly format."""
        output = response.get('output', {})
        resolved_addresses = output.get('resolvedAddresses', [])
        
        # Check for PO Box FIRST
        is_po_box = self._detect_po_box(original)
        if is_po_box:
            return {
                'success': True,
                'is_valid': False,
                'is_po_box': True,
                'classification': 'PO_BOX',
                'carriers': self._determine_carriers('PO_BOX', True, False),
                'original': original,
                'suggested': None,
                'corrections': [],
                'message': '📮 PO Box Detected - Please send through USPS. FedEx does not deliver to PO Boxes.',
                'error_type': 'po_box'
            }
        
        # Check for Rural Route
        is_rural = self._detect_rural_route(original)
        
        if not resolved_addresses:
            return {
                'success': True,
                'is_valid': False,
                'classification': 'INVALID',
                'carriers': [],
                'message': '❌ Invalid Address - Address not found in FedEx database. Please verify all fields.',
                'original': original,
                'suggested': None,
                'corrections': [],
                'error_type': 'invalid'
            }
        
        # Get the first (best) match
        best_match = resolved_addresses[0]
        classification = best_match.get('classification', 'UNKNOWN')
        
        # Get resolution details
        resolution = best_match.get('resolutionMethodAttributes', {})
        confidence = resolution.get('overAllConfidenceScore', 0)
        
        # Get the resolved address
        suggested = None
        if 'address' in best_match:
            addr = best_match['address']
            suggested = {
                'street_lines': addr.get('streetLines', []),
                'city': addr.get('city', ''),
                'state_code': addr.get('stateOrProvinceCode', ''),
                'postal_code': addr.get('postalCode', ''),
                'country_code': addr.get('countryCode', 'US'),
                'classification': classification
            }
            
            # Add ZIP+4 if available
            parsed_postal = addr.get('parsedPostalCode', {})
            if parsed_postal:
                base_zip = parsed_postal.get('base', '')
                extension = parsed_postal.get('extension', '')
                if extension:
                    suggested['postal_code'] = f"{base_zip}-{extension}"
                else:
                    suggested['postal_code'] = base_zip
        
        # Determine if address is valid
        is_valid = classification in ['BUSINESS', 'RESIDENTIAL', 'MIXED']
        
        # Handle different types with appropriate messaging
        if is_rural:
            message = '⚠️ Rural Route Address - Additional delivery instructions may be needed. Contact recipient for landmarks or gate codes.'
            error_type = 'rural'
        elif classification == 'UNKNOWN':
            message = '❌ Address Issue Detected - Unable to validate address. Please verify all information is correct.'
            error_type = 'unknown'
            is_valid = False
        elif not is_valid:
            message = '❌ Invalid Address - This address could not be validated for delivery.'
            error_type = 'invalid'
        else:
            # Valid address - check for corrections
            corrections = self._identify_corrections(original, suggested) if suggested else []
            if corrections:
                message = f'✅ Valid {classification} address with suggested corrections'
            else:
                message = f'✅ Valid {classification} address - Ready for shipping!'
            error_type = None
        
        # Identify corrections
        corrections = []
        if suggested and original:
            corrections = self._identify_corrections(original, suggested)
        
        return {
            'success': True,
            'is_valid': is_valid,
            'is_rural': is_rural,
            'confidence': confidence,
            'classification': classification,
            'carriers': self._determine_carriers(classification, False, is_rural),
            'original': original,
            'suggested': suggested,
            'corrections': corrections,
            'message': message,
            'error_type': error_type
        }
    
    def _determine_carriers(self, classification: str, is_po_box: bool, is_rural: bool) -> List[str]:
        """Determine which carriers can service this address."""
        if is_po_box:
            return ['USPS']
        if classification in ('INVALID', 'UNKNOWN', None) or not classification:
            return []
        if is_rural:
            return ['USPS', 'FedEx (access may vary)', 'UPS (access may vary)']
        return ['USPS', 'FedEx', 'UPS']

    def _detect_po_box(self, address: Dict) -> bool:
        """Detect if address is a PO Box."""
        street_lines = address.get('street_lines', [])
        for line in street_lines:
            line_upper = line.upper()
            # Check for various PO Box formats
            if any(pattern in line_upper for pattern in [
                'P.O. BOX', 'PO BOX', 'P O BOX', 'POST OFFICE BOX',
                'P.O BOX', 'P. O. BOX', 'POBOX', 'P.O.BOX'
            ]):
                return True
        return False
    
    def _detect_rural_route(self, address: Dict) -> bool:
        """Detect if address is a rural route."""
        street_lines = address.get('street_lines', [])
        for line in street_lines:
            line_upper = line.upper()
            # Check for rural route patterns
            if any(pattern in line_upper for pattern in [
                'RR ', 'R.R.', 'RURAL ROUTE', 'RFD ', 'R.F.D.',
                'RURAL DELIVERY', 'HC ', 'HIGHWAY CONTRACT'
            ]):
                return True
        return False
    
    def _identify_corrections(self, original: Dict, suggested: Dict) -> List[str]:
        """Identify specific corrections made."""
        corrections = []
        
        if not suggested:
            return corrections
        
        # Check street address
        orig_streets = original.get('street_lines', [])
        sugg_streets = suggested.get('street_lines', [])
        if orig_streets != sugg_streets:
            corrections.append(f"Street: {' '.join(sugg_streets)}")
        
        # Check city
        if original.get('city', '').upper() != suggested.get('city', '').upper():
            corrections.append(f"City: {suggested['city']}")
        
        # Check state
        if original.get('state_code', '').upper() != suggested.get('state_code', '').upper():
            corrections.append(f"State: {suggested['state_code']}")
        
        # Check ZIP
        orig_zip = original.get('postal_code', '')
        sugg_zip = suggested.get('postal_code', '')
        if orig_zip != sugg_zip:
            corrections.append(f"ZIP: {sugg_zip}")
        
        return corrections
    
    def _get_validation_message(self, is_valid: bool, classification: str, corrections: List[str]) -> str:
        """Generate user-friendly validation message."""
        if is_valid and not corrections:
            if classification == 'BUSINESS':
                return "✅ Valid business address - ready for shipping!"
            elif classification == 'RESIDENTIAL':
                return "✅ Valid residential address - ready for shipping!"
            else:
                return "✅ Address is valid and deliverable!"
        elif is_valid and corrections:
            return f"⚠️ Address is valid but has suggested corrections: {', '.join(corrections)}"
        else:
            return "❌ Address could not be validated. Please check and correct."


class AddressValidator:
    """Main address validation handler with caching and fallback options."""
    
    def __init__(self):
        self.fedex = FedExAddressValidator()
        self.cache_duration = 86400  # 24 hours
    
    def validate(self, address_data: Dict, use_cache: bool = True) -> Dict:
        """
        Validate an address with caching support.
        
        Args:
            address_data: Address fields to validate
            use_cache: Whether to check cache first
        
        Returns:
            Validation results with suggestions
        """
        # Check cache if enabled
        if use_cache:
            cached = self._check_cache(address_data)
            if cached:
                cached['from_cache'] = True
                return cached
        
        # Validate with FedEx
        result = self.fedex.validate_address(address_data)
        
        # Cache successful validations
        if result.get('success'):
            self._cache_result(address_data, result)
        
        return result
    
    def _check_cache(self, address_data: Dict) -> Optional[Dict]:
        """Check if we have a cached validation for this address."""
        cache_key = self._generate_cache_key(address_data)
        
        try:
            with get_db_connection('send') as conn:
                cursor = conn.cursor()
                try:
                    # FIX: Correct PostgreSQL interval syntax
                    cursor.execute("""
                        SELECT validation_result, created_at
                        FROM address_validation_cache
                        WHERE cache_key = %s
                        AND created_at > NOW() - INTERVAL %s
                    """, (cache_key, f'{self.cache_duration} seconds'))
                    
                    row = cursor.fetchone()
                    if row:
                        return json.loads(row['validation_result'])
                        
                finally:
                    # CRITICAL: Always close the cursor
                    cursor.close()
                    
        except Exception as e:
            # FIX: Proper error logging instead of silent failure
            logger.warning(f"Cache check failed: {str(e)}")
            # Return None to proceed without cache
        
        return None
    
    def _cache_result(self, address_data: Dict, result: Dict):
        """Cache validation result for future use."""
        cache_key = self._generate_cache_key(address_data)
        
        try:
            with get_db_connection('send') as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("""
                        INSERT INTO address_validation_cache (cache_key, validation_result)
                        VALUES (%s, %s)
                        ON CONFLICT (cache_key) 
                        DO UPDATE SET 
                            validation_result = EXCLUDED.validation_result,
                            created_at = CURRENT_TIMESTAMP
                    """, (cache_key, json.dumps(result)))
                    
                    # FIX: Commit is handled by context manager, but we'll be explicit
                    # conn.commit() is handled by the context manager
                    
                finally:
                    # CRITICAL: Always close the cursor
                    cursor.close()
                    
        except Exception as e:
            # FIX: Log the error instead of silent failure
            logger.warning(f"Failed to cache validation result: {str(e)}")
            # Caching is optional, so we continue
    
    def _generate_cache_key(self, address_data: Dict) -> str:
        """Generate a unique cache key for an address."""
        import hashlib
        
        # Create consistent string from address
        key_parts = [
            '|'.join(address_data.get('street_lines', [])),
            address_data.get('city', '').upper(),
            address_data.get('state_code', '').upper(),
            address_data.get('postal_code', ''),
            address_data.get('country_code', 'US')
        ]
        
        key_string = '::'.join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()
    
    def bulk_validate(self, addresses: List[Dict]) -> List[Dict]:
        """Validate multiple addresses efficiently."""
        results = []
        
        for address in addresses:
            try:
                result = self.validate(address)
                results.append(result)
            except Exception as e:
                logger.error(f"Bulk validation error for address: {str(e)}")
                results.append({
                    'success': False,
                    'error': str(e),
                    'original': address
                })
        
        return results