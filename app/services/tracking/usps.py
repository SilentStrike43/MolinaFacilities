"""
USPS Tracking API Integration (OAuth 2.0)
Uses modern USPS API with REST/JSON
"""

import requests
from typing import Optional
from datetime import datetime, timedelta
import logging
from .base import BaseCarrier, TrackingResult

logger = logging.getLogger(__name__)


class USPSTracker(BaseCarrier):
    """USPS tracking via OAuth 2.0 API"""
    
    def __init__(self, config):
        # Don't call super().__init__() - just set attributes directly
        self.config = config
        self.carrier_name = 'USPS'
        self.consumer_key = config.get('USPS_CONSUMER_KEY')
        self.consumer_secret = config.get('USPS_CONSUMER_SECRET')
        self.api_url = config.get('USPS_API_URL', 'https://api.usps.com')
        self._access_token = None
        self._token_expiry = None
    
    def _get_access_token(self) -> str:
        """Get OAuth 2.0 access token"""
        # Check if we have a valid cached token
        if self._access_token and self._token_expiry:
            if datetime.now() < self._token_expiry:
                return self._access_token
        
        # Request new token
        token_url = f"{self.api_url}/oauth2/v3/token"
        
        try:
            response = requests.post(
                token_url,
                auth=(self.consumer_key, self.consumer_secret),
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
            # Token expires in seconds, cache for 95% of that time
            expires_in = token_data.get('expires_in', 3600)
            self._token_expiry = datetime.now() + timedelta(seconds=int(expires_in * 0.95))
            
            return self._access_token
            
        except requests.exceptions.RequestException as e:
            logger.error(f"USPS OAuth token error: {str(e)}")
            raise Exception(f"Failed to get USPS access token: {str(e)}")
    
    def track(self, tracking_number: str) -> TrackingResult:
        """
        Track a USPS package
        
        API Docs: https://developer.usps.com/api/tracking
        """
        result = TrackingResult()
        result.carrier = 'USPS'
        result.tracking_number = tracking_number
        
        try:
            # Get access token
            token = self._get_access_token()
            
            # Make tracking request
            tracking_url = f"{self.api_url}/tracking/v3/tracking/{tracking_number}"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Accept': 'application/json'
            }
            
            response = requests.get(tracking_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            result.raw_response = data
            
            # Parse response
            if 'trackResults' in data and len(data['trackResults']) > 0:
                track_info = data['trackResults'][0]
                
                # Basic info
                result.status = self._standardize_status(track_info.get('status', ''))
                result.status_description = track_info.get('statusSummary', '')
                
                # Delivery info
                if 'expectedDeliveryDate' in track_info:
                    try:
                        result.estimated_delivery = datetime.fromisoformat(
                            track_info['expectedDeliveryDate'].replace('Z', '+00:00')
                        )
                    except (ValueError, AttributeError):
                        pass
                
                if track_info.get('status') == 'Delivered':
                    if 'deliveryDate' in track_info:
                        try:
                            result.actual_delivery = datetime.fromisoformat(
                                track_info['deliveryDate'].replace('Z', '+00:00')
                            )
                        except (ValueError, AttributeError):
                            pass
                    result.delivered_to = track_info.get('deliveryLocation', '')
                    result.signature = track_info.get('signedBy', '')
                
                # Location
                if 'location' in track_info:
                    loc = track_info['location']
                    city = loc.get('city', '')
                    state = loc.get('state', '')
                    result.location = f"{city}, {state}" if city and state else city or state
                
                # Events
                if 'trackingEvents' in track_info:
                    for event in track_info['trackingEvents']:
                        result.events.append({
                            'timestamp': event.get('eventTimestamp'),
                            'status': event.get('eventType', ''),
                            'description': event.get('eventSummary', ''),
                            'location': f"{event.get('eventCity', '')}, {event.get('eventState', '')}"
                        })
                
                result.success = True
            else:
                result.error = "No tracking information found"
                result.success = False
                
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                result.error = "Tracking number not found"
            else:
                result.error = f"USPS API error: {str(e)}"
            result.success = False
            logger.error(f"USPS tracking error for {tracking_number}: {str(e)}")
            
        except Exception as e:
            result.error = f"Tracking failed: {str(e)}"
            result.success = False
            logger.error(f"USPS tracking exception for {tracking_number}: {str(e)}")
        
        return result
    
    def _standardize_status(self, usps_status: str) -> str:
        """Convert USPS status to standard status"""
        status_map = {
            'Pre-Shipment': self.STATUS_PRE_TRANSIT,
            'Label Created': self.STATUS_PRE_TRANSIT,
            'Accepted': self.STATUS_IN_TRANSIT,
            'In Transit': self.STATUS_IN_TRANSIT,
            'Out for Delivery': self.STATUS_OUT_FOR_DELIVERY,
            'Delivered': self.STATUS_DELIVERED,
            'Available for Pickup': self.STATUS_AVAILABLE_FOR_PICKUP,
            'Return to Sender': self.STATUS_RETURN_TO_SENDER,
            'Delivery Attempted': self.STATUS_FAILED_ATTEMPT,
            'Alert': self.STATUS_EXCEPTION,
        }
        
        return status_map.get(usps_status, self.STATUS_UNKNOWN)