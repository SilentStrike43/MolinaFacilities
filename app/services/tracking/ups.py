"""
UPS Tracking API Integration (OAuth 2.0)
"""

import requests
from typing import Optional
from datetime import datetime, timedelta
import logging
from .base import BaseCarrier, TrackingResult

logger = logging.getLogger(__name__)


class UPSTracker(BaseCarrier):
    """UPS tracking via OAuth 2.0 API"""
    
    def __init__(self, config):
        # Don't call super().__init__() - just set attributes directly
        self.config = config
        self.carrier_name = 'UPS'
        self.client_id = config.get('UPS_CLIENT_ID')
        self.client_secret = config.get('UPS_CLIENT_SECRET')
        self.account_number = config.get('UPS_ACCOUNT_NUMBER')
        self.api_url = config.get('UPS_API_URL', 'https://onlinetools.ups.com/api')
        self._access_token = None
        self._token_expiry = None
    
    def _get_access_token(self) -> str:
        """Get OAuth 2.0 access token"""
        if not self.client_id or not self.client_secret:
            raise Exception("UPS credentials not configured")
            
        if self._access_token and self._token_expiry:
            if datetime.now() < self._token_expiry:
                return self._access_token
        
        token_url = f"{self.api_url}/security/v1/oauth/token"
        
        try:
            response = requests.post(
                token_url,
                auth=(self.client_id, self.client_secret),
                data={
                    'grant_type': 'client_credentials'
                },
                headers={
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                timeout=10
            )
            
            response.raise_for_status()
            token_data = response.json()
            
            self._access_token = token_data['access_token']
            expires_in = token_data.get('expires_in', 3600)
            self._token_expiry = datetime.now() + timedelta(seconds=int(expires_in * 0.95))
            
            return self._access_token
            
        except requests.exceptions.RequestException as e:
            logger.error(f"UPS OAuth token error: {str(e)}")
            raise Exception(f"Failed to get UPS access token: {str(e)}")
    
    def track(self, tracking_number: str) -> TrackingResult:
        """
        Track a UPS package
        
        API Docs: https://developer.ups.com/api/reference/tracking
        """
        result = TrackingResult()
        result.carrier = 'UPS'
        result.tracking_number = tracking_number
        
        if not self.client_id or not self.client_secret:
            result.error = "UPS API credentials not configured"
            result.success = False
            return result
        
        try:
            token = self._get_access_token()
            
            tracking_url = f"{self.api_url}/track/v1/details/{tracking_number}"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            params = {
                'locale': 'en_US',
                'returnSignature': 'true'
            }
            
            response = requests.get(tracking_url, headers=headers, params=params, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            result.raw_response = data
            
            # Parse UPS response
            if 'trackResponse' in data and 'shipment' in data['trackResponse']:
                shipment = data['trackResponse']['shipment'][0]
                package = shipment['package'][0]
                
                # Current status
                current_status = package.get('currentStatus', {})
                result.status = self._standardize_status(current_status.get('code', ''))
                result.status_description = current_status.get('description', '')
                
                # Delivery dates
                if 'deliveryDate' in package:
                    delivery_info = package['deliveryDate'][0]
                    if delivery_info.get('type') == 'DEL':
                        try:
                            result.actual_delivery = datetime.strptime(
                                delivery_info['date'], '%Y%m%d'
                            )
                        except (ValueError, KeyError):
                            pass
                
                # Delivery details
                if 'deliveryInformation' in package:
                    delivery = package['deliveryInformation']
                    result.delivered_to = delivery.get('receivedBy', '')
                    result.location = delivery.get('location', '')
                    
                    if 'signature' in delivery:
                        result.signature = delivery['signature'].get('image', 'Yes')
                
                # Activity/Events
                if 'activity' in package:
                    for activity in package['activity']:
                        event_location = activity.get('location', {})
                        address = event_location.get('address', {})
                        city = address.get('city', '')
                        state = address.get('stateProvince', '')
                        location_str = f"{city}, {state}" if city and state else city or state
                        
                        result.events.append({
                            'timestamp': f"{activity.get('date', '')} {activity.get('time', '')}",
                            'status': activity.get('status', {}).get('description', ''),
                            'description': activity.get('status', {}).get('description', ''),
                            'location': location_str
                        })
                
                result.success = True
            else:
                result.error = "No tracking information found"
                result.success = False
                
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                result.error = "Tracking number not found"
            else:
                result.error = f"UPS API error: {str(e)}"
            result.success = False
            logger.error(f"UPS tracking error for {tracking_number}: {str(e)}")
            
        except Exception as e:
            result.error = f"Tracking failed: {str(e)}"
            result.success = False
            logger.error(f"UPS tracking exception for {tracking_number}: {str(e)}")
        
        return result
    
    def _standardize_status(self, ups_code: str) -> str:
        """Convert UPS status code to standard status"""
        status_map = {
            'M': self.STATUS_PRE_TRANSIT,
            'P': self.STATUS_IN_TRANSIT,
            'I': self.STATUS_IN_TRANSIT,
            'X': self.STATUS_OUT_FOR_DELIVERY,
            'D': self.STATUS_DELIVERED,
            'RS': self.STATUS_RETURN_TO_SENDER,
            'DE': self.STATUS_EXCEPTION,
        }
        
        return status_map.get(ups_code, self.STATUS_UNKNOWN)