"""
FedEx Tracking Service
Retrieve shipment information from tracking numbers
"""

import requests
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class FedExTrackingService:
    """Service for tracking FedEx shipments."""
    
    def __init__(self, config):
        self.api_url = config.get('FEDEX_API_URL')
        self.api_key = config.get('FEDEX_SHIP_API_KEY')
        self.secret_key = config.get('FEDEX_SHIP_SECRET_KEY')
        self.account_number = config.get('FEDEX_ACCOUNT_NUMBER')
        
    def _get_token(self) -> Optional[str]:
        """Get OAuth access token."""
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
                return response.json().get('access_token')
            else:
                logger.error(f"Token error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Token request failed: {e}")
            return None
    
    def track_shipment(self, tracking_number: str) -> Dict[str, Any]:
        """
        Track a shipment by tracking number.
        Returns shipment details including recipient and package info.
        """
        try:
            # Get access token
            token = self._get_token()
            if not token:
                return {
                    "success": False,
                    "error": "Authentication failed"
                }
            
            # Track shipment
            payload = {
                "includeDetailedScans": True,
                "trackingInfo": [{
                    "trackingNumberInfo": {
                        "trackingNumber": tracking_number
                    }
                }]
            }
            
            response = requests.post(
                f"{self.api_url}/track/v1/trackingnumbers",
                headers={
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json'
                },
                json=payload,
                timeout=15
            )
            
            if response.status_code != 200:
                logger.error(f"Tracking API error: {response.status_code} - {response.text}")
                return {
                    "success": False,
                    "error": f"FedEx API error: {response.status_code}"
                }
            
            data = response.json()
            
            # Parse tracking response
            if 'output' not in data or 'completeTrackResults' not in data['output']:
                return {
                    "success": False,
                    "error": "Invalid tracking response format"
                }
            
            track_results = data['output']['completeTrackResults']
            if not track_results or len(track_results) == 0:
                return {
                    "success": False,
                    "error": "No tracking information found"
                }
            
            # Get first result
            result = track_results[0]
            track_result = result.get('trackResults', [{}])[0]
            
            # Extract shipment details
            shipment_data = self._parse_tracking_data(track_result)
            
            return {
                "success": True,
                "shipment": shipment_data
            }
            
        except requests.exceptions.Timeout:
            logger.error("FedEx tracking request timed out")
            return {
                "success": False,
                "error": "Request timed out"
            }
        except Exception as e:
            logger.error(f"Tracking error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }
    
    def _parse_tracking_data(self, track_result: Dict) -> Dict[str, Any]:
        """Parse FedEx tracking result into simplified format."""
        
        # Delivery address
        delivery_address = track_result.get('recipientInformation', {}).get('address', {})
        
        # Latest status
        latest_status = track_result.get('latestStatusDetail', {})
        status_code = latest_status.get('code', '')
        status_desc = latest_status.get('description', 'In Transit')
        
        # Delivery information
        delivery_info = track_result.get('dateAndTimes', [])
        estimated_delivery = None
        for date_info in delivery_info:
            if date_info.get('type') == 'ESTIMATED_DELIVERY':
                estimated_delivery = date_info.get('dateTime', '')
                break
        
        # Package details
        package_details = track_result.get('packageDetails', {})
        weight = package_details.get('weight', {})
        
        # Service type
        service_detail = track_result.get('serviceDetail', {})
        service_type = service_detail.get('description', '')
        
        # Recipient information
        recipient_info = track_result.get('recipientInformation', {})
        
        return {
            'recipient': {
                'name': recipient_info.get('personName', ''),
                'company': recipient_info.get('companyName', ''),
                'phone': recipient_info.get('phoneNumber', ''),
                'email': ''  # Not provided by tracking API
            },
            'recipient_address': {
                'street': ', '.join(delivery_address.get('streetLines', [])),
                'city': delivery_address.get('city', ''),
                'state': delivery_address.get('stateOrProvinceCode', ''),
                'zip': delivery_address.get('postalCode', ''),
                'country': delivery_address.get('countryCode', 'US')
            },
            'package': {
                'type': package_details.get('packagingDescription', 'Box'),
                'weight': weight.get('value', '') if weight else '',
                'weight_unit': weight.get('units', 'LB') if weight else 'LB'
            },
            'service_type': service_type,
            'status': status_desc,
            'status_code': status_code,
            'status_description': latest_status.get('statusByLocale', ''),
            'estimated_delivery': estimated_delivery,
            'origin': track_result.get('shipperInformation', {}).get('address', {}).get('city', ''),
            'destination': delivery_address.get('city', ''),
            'last_update': latest_status.get('scanEventTime', '')
        }