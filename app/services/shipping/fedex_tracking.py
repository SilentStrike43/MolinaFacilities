"""
FedEx Tracking Service
Extracts package/shipment metadata only (NO recipient details)
"""

import requests
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class FedExTrackingService:
    """Extract shipment metadata from tracking numbers."""
    
    def __init__(self, config):
        self.api_url = config.get('FEDEX_API_URL')
        self.api_key = config.get('FEDEX_TRACK_API_KEY')
        self.secret_key = config.get('FEDEX_TRACK_SECRET_KEY')
        self._access_token = None
        self._token_expiry = None
        
    def _get_token(self) -> Optional[str]:
        """Get OAuth access token."""
        if self._access_token and self._token_expiry:
            if datetime.now() < self._token_expiry:
                return self._access_token
        
        try:
            response = requests.post(
                f"{self.api_url}/oauth/token",
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                data={
                    'grant_type': 'client_credentials',
                    'client_id': self.api_key,
                    'client_secret': self.secret_key
                },
                timeout=10
            )
            
            if response.status_code == 200:
                token_data = response.json()
                self._access_token = token_data['access_token']
                expires_in = token_data.get('expires_in', 3600)
                self._token_expiry = datetime.now() + timedelta(seconds=int(expires_in * 0.95))
                return self._access_token
            else:
                logger.error(f"FedEx token error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"FedEx token request failed: {e}")
            return None
    
    def track_shipment(self, tracking_number: str) -> Dict[str, Any]:
        """
        Extract package metadata from tracking number.
        Returns ONLY shipment info (service, weight, dates, etc.)
        Does NOT return recipient details.
        """
        try:
            token = self._get_token()
            if not token:
                return {
                    "success": False,
                    "error": "FedEx authentication failed"
                }
            
            payload = {
                "includeDetailedScans": True,
                "trackingInfo": [
                    {
                        "trackingNumberInfo": {
                            "trackingNumber": tracking_number
                        }
                    }
                ]
            }
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
                'X-locale': 'en_US'
            }
            
            response = requests.post(
                f"{self.api_url}/track/v1/trackingnumbers",
                headers=headers,
                json=payload,
                timeout=15
            )
            
            if response.status_code == 403:
                logger.error(f"FedEx 403 error: {response.text}")
                return {
                    "success": False,
                    "error": "Permission denied. Check FedEx Track API credentials."
                }
            
            if response.status_code != 200:
                logger.error(f"FedEx API error: {response.status_code} - {response.text}")
                return {
                    "success": False,
                    "error": f"FedEx API returned {response.status_code}"
                }
            
            data = response.json()
            
            if 'output' not in data or 'completeTrackResults' not in data['output']:
                return {
                    "success": False,
                    "error": "Invalid FedEx response format"
                }
            
            track_results = data['output']['completeTrackResults']
            if not track_results:
                return {
                    "success": False,
                    "error": "Tracking number not found in FedEx system"
                }
            
            result = track_results[0]
            track_result = result.get('trackResults', [{}])[0]
            
            # Extract package metadata
            package_data = self._extract_package_metadata(track_result)
            
            return {
                "success": True,
                "carrier": "FedEx",
                "tracking_number": tracking_number,
                "package_data": package_data
            }
            
        except Exception as e:
            logger.error(f"FedEx tracking error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }
    
    def _extract_package_metadata(self, track_result: Dict) -> Dict[str, Any]:
        """Extract all package/shipment metadata (no recipient info)."""
        
        metadata = {
            # Service information
            'service_type': '',
            'service_description': '',
            
            # Package details
            'package_type': 'Box',
            'weight': '',
            'weight_value': None,
            'weight_unit': '',
            'dimensions': '',
            'piece_count': 1,
            
            # Status
            'status': '',
            'status_description': '',
            
            # Dates
            'ship_date': '',
            'estimated_delivery': '',
            'actual_delivery': '',
            'last_update': '',
            
            # Locations
            'origin': '',
            'origin_city': '',
            'origin_state': '',
            'destination': '',
            'destination_city': '',
            'destination_state': '',
            
            # Delivery details
            'delivery_signature': '',
            'delivery_instructions': ''
        }
        
        # Service type
        if 'serviceDetail' in track_result:
            service = track_result['serviceDetail']
            metadata['service_type'] = service.get('type', '')
            metadata['service_description'] = service.get('description', '')
        
        # Package details
        if 'packageDetails' in track_result:
            package = track_result['packageDetails']
            
            # Weight
            if 'weight' in package:
                weight_info = package['weight']
                metadata['weight_value'] = weight_info.get('value', '')
                metadata['weight_unit'] = weight_info.get('units', 'LBS')
                metadata['weight'] = f"{weight_info.get('value', '')} {weight_info.get('units', 'LBS')}".strip()
            
            # Dimensions
            if 'dimensions' in package:
                dims = package['dimensions']
                length = dims.get('length', '')
                width = dims.get('width', '')
                height = dims.get('height', '')
                unit = dims.get('units', 'IN')
                if length and width and height:
                    metadata['dimensions'] = f"{length}x{width}x{height} {unit}"
            
            # Packaging type
            metadata['package_type'] = package.get('packagingDescription', 'Box')
            
            # Piece count
            metadata['piece_count'] = package.get('count', 1)
        
        # Status
        if 'latestStatusDetail' in track_result:
            status = track_result['latestStatusDetail']
            metadata['status'] = status.get('code', '')
            metadata['status_description'] = status.get('description', '')
        
        # Ship date
        if 'shipDatestamp' in track_result:
            metadata['ship_date'] = track_result['shipDatestamp']
        
        # Estimated delivery
        if 'estimatedDeliveryTimeWindow' in track_result:
            window = track_result['estimatedDeliveryTimeWindow']
            if 'window' in window and 'ends' in window['window']:
                metadata['estimated_delivery'] = window['window']['ends']
        
        # Actual delivery
        if 'deliveryDetails' in track_result:
            delivery = track_result['deliveryDetails']
            metadata['actual_delivery'] = delivery.get('actualDeliveryTimestamp', '')
            
            if delivery.get('signatureProofOfDeliveryAvailable'):
                metadata['delivery_signature'] = 'Required'
        
        # Origin
        if 'shipperInformation' in track_result:
            shipper = track_result['shipperInformation'].get('address', {})
            metadata['origin_city'] = shipper.get('city', '')
            metadata['origin_state'] = shipper.get('stateOrProvinceCode', '')
            metadata['origin'] = f"{metadata['origin_city']}, {metadata['origin_state']}".strip(', ')
        
        # Destination
        if 'destinationLocation' in track_result:
            dest = track_result['destinationLocation']
            metadata['destination_city'] = dest.get('city', '')
            metadata['destination_state'] = dest.get('stateOrProvinceCode', '')
            metadata['destination'] = f"{metadata['destination_city']}, {metadata['destination_state']}".strip(', ')
        
        return metadata