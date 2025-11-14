"""
FedEx Address Validation Service
Validate shipping addresses using FedEx API
"""

import requests
from datetime import datetime, timedelta
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class AddressValidator:
    """
    Address validation using FedEx Address Validation API
    """
    
    def __init__(self, config):
        self.api_key = config.get('FEDEX_SHIP_API_KEY')
        self.secret_key = config.get('FEDEX_SHIP_SECRET_KEY')
        self.api_url = config.get('FEDEX_API_URL', 'https://apis.fedex.com')
        self._access_token = None
        self._token_expiry = None
    
    def _get_access_token(self) -> str:
        """Get OAuth token"""
        if self._access_token and self._token_expiry:
            if datetime.now() < self._token_expiry:
                return self._access_token
        
        token_url = f"{self.api_url}/oauth/token"
        
        try:
            response = requests.post(
                token_url,
                data={
                    'grant_type': 'client_credentials',
                    'client_id': self.api_key,
                    'client_secret': self.secret_key
                },
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=10
            )
            
            response.raise_for_status()
            token_data = response.json()
            
            self._access_token = token_data['access_token']
            expires_in = token_data.get('expires_in', 3600)
            self._token_expiry = datetime.now() + timedelta(seconds=int(expires_in * 0.95))
            
            return self._access_token
            
        except requests.exceptions.RequestException as e:
            logger.error(f"FedEx OAuth token error: {str(e)}")
            raise Exception(f"Failed to get FedEx access token: {str(e)}")
    
    def validate(self, address_line1: str, city: str, state: str, 
                 zip_code: str, address_line2: Optional[str] = None,
                 country: str = 'US') -> Dict:
        """
        Validate an address using FedEx API
        
        Args:
            address_line1: Street address
            city: City name
            state: State code (e.g., 'NY')
            zip_code: ZIP code
            address_line2: Optional second address line
            country: Country code (default: 'US')
        
        Returns:
            {
                'valid': True/False,
                'classification': 'VALID', 'LIKELY_VALID', 'INVALID', etc.
                'corrected_address': {...},  # Suggested corrections if any
                'warnings': [...],
                'error': 'error message' if failed
            }
        """
        try:
            token = self._get_access_token()
            
            url = f"{self.api_url}/address/v1/addresses/resolve"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            # Build street lines array
            street_lines = [address_line1]
            if address_line2:
                street_lines.append(address_line2)
            
            payload = {
                "addressesToValidate": [
                    {
                        "address": {
                            "streetLines": street_lines,
                            "city": city,
                            "stateOrProvinceCode": state,
                            "postalCode": zip_code,
                            "countryCode": country
                        }
                    }
                ]
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            
            # Parse validation result
            if 'output' in data and 'resolvedAddresses' in data['output']:
                result = data['output']['resolvedAddresses'][0]
                
                classification = result.get('classification', 'UNKNOWN')
                is_valid = classification in ['VALID', 'LIKELY_VALID']
                
                # Extract corrected address if available
                corrected = None
                if 'resolvedAddress' in result:
                    resolved = result['resolvedAddress']
                    corrected = {
                        'address_line1': resolved.get('streetLines', [''])[0],
                        'address_line2': resolved.get('streetLines', ['', ''])[1] if len(resolved.get('streetLines', [])) > 1 else '',
                        'city': resolved.get('city', ''),
                        'state': resolved.get('stateOrProvinceCode', ''),
                        'zip_code': resolved.get('postalCode', ''),
                        'country': resolved.get('countryCode', 'US')
                    }
                
                return {
                    'valid': is_valid,
                    'classification': classification,
                    'corrected_address': corrected,
                    'warnings': result.get('warnings', []),
                    'raw_response': data
                }
            
            return {
                'valid': False,
                'error': 'No validation result returned',
                'raw_response': data
            }
            
        except requests.exceptions.HTTPError as e:
            error_msg = f"FedEx API error: {e.response.status_code}"
            try:
                error_data = e.response.json()
                if 'errors' in error_data:
                    error_msg = error_data['errors'][0].get('message', error_msg)
            except:
                pass
            
            logger.error(f"Address validation error: {error_msg}")
            return {'valid': False, 'error': error_msg}
            
        except Exception as e:
            logger.error(f"Address validation exception: {str(e)}")
            return {'valid': False, 'error': str(e)}
    
    def validate_batch(self, addresses: list) -> list:
        """
        Validate multiple addresses at once
        
        Args:
            addresses: List of address dicts with keys:
                      address_line1, city, state, zip_code, etc.
        
        Returns:
            List of validation results
        """
        results = []
        
        for addr in addresses:
            result = self.validate(
                addr.get('address_line1', ''),
                addr.get('city', ''),
                addr.get('state', ''),
                addr.get('zip_code', ''),
                addr.get('address_line2'),
                addr.get('country', 'US')
            )
            results.append(result)
        
        return results