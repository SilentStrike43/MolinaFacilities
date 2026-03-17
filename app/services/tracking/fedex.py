"""
FedEx Tracking API Integration
"""

import requests
from typing import Optional
from datetime import datetime, timedelta
import logging
from .base import BaseCarrier, TrackingResult

logger = logging.getLogger(__name__)


class FedExTracker(BaseCarrier):
    """FedEx tracking via REST API"""
    
    def __init__(self, config):
        # Don't call super().__init__() - just set attributes directly
        self.config = config
        self.carrier_name = 'FEDEX'
        self.api_key = config.get('FEDEX_TRACK_API_KEY')
        self.secret_key = config.get('FEDEX_TRACK_SECRET_KEY')
        self.api_url = config.get('FEDEX_API_URL', 'https://apis.fedex.com')
        self._access_token = None
        self._token_expiry = None
    
    def _get_access_token(self) -> str:
        """Get OAuth 2.0 access token"""
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
                headers={
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                timeout=10
            )
            
            response.raise_for_status()
            token_data = response.json()
            
            self._access_token = token_data['access_token']
            expires_in = int(float(token_data.get('expires_in', 3600)))
            self._token_expiry = datetime.now() + timedelta(seconds=int(expires_in * 0.95))
            
            return self._access_token
            
        except requests.exceptions.RequestException as e:
            logger.error(f"FedEx OAuth token error: {str(e)}")
            raise Exception(f"Failed to get FedEx access token: {str(e)}")
    
    def track(self, tracking_number: str) -> TrackingResult:
        """
        Track a FedEx package
        
        API Docs: https://developer.fedex.com/api/en-us/catalog/track/v1/docs.html
        """
        result = TrackingResult()
        result.carrier = 'FEDEX'
        result.tracking_number = tracking_number
        
        try:
            token = self._get_access_token()
            
            tracking_url = f"{self.api_url}/track/v1/trackingnumbers"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                'includeDetailedScans': True,
                'trackingInfo': [
                    {
                        'trackingNumberInfo': {
                            'trackingNumber': tracking_number
                        }
                    }
                ]
            }
            
            response = requests.post(tracking_url, json=payload, headers=headers, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            result.raw_response = data
            
            # Parse FedEx response
            if 'output' in data and 'completeTrackResults' in data['output']:
                track_results = data['output']['completeTrackResults'][0]
                
                if 'trackResults' in track_results:
                    track_info = track_results['trackResults'][0]
                    
                    # Status
                    latest_status = track_info.get('latestStatusDetail', {})
                    status_code = latest_status.get('code', '')
                    status_by_locale = latest_status.get('statusByLocale', '')
                    result.status_description = latest_status.get('description', '')

                    # Try to get status from code first, then from statusByLocale
                    if status_code:
                        result.status = self._standardize_status(status_code)
                    elif status_by_locale:
                        result.status = self._standardize_status(status_by_locale)
                    else:
                        # Fallback: infer from description
                        result.status = self._infer_status_from_description(result.status_description)
                    
                    # Dates
                    if 'estimatedDeliveryTimeWindow' in track_info:
                        window = track_info['estimatedDeliveryTimeWindow']
                        if 'window' in window and 'ends' in window['window']:
                            try:
                                result.estimated_delivery = datetime.fromisoformat(
                                    window['window']['ends'].replace('Z', '+00:00')
                                )
                            except (ValueError, AttributeError):
                                pass
                    
                    if 'deliveryDetails' in track_info:
                        delivery = track_info['deliveryDetails']
                        if 'actualDeliveryTimestamp' in delivery:
                            try:
                                result.actual_delivery = datetime.fromisoformat(
                                    delivery['actualDeliveryTimestamp'].replace('Z', '+00:00')
                                )
                            except (ValueError, AttributeError):
                                pass
                        result.delivered_to = delivery.get('receivedByName', '')
                        result.location = delivery.get('deliveryLocation', '')
                        
                        if delivery.get('signatureProofOfDeliveryAvailable'):
                            result.signature = 'Yes'
                    
                    # Events
                    if 'scanEvents' in track_info:
                        for event in track_info['scanEvents']:
                            scan_loc = event.get('scanLocation', {})
                            city = scan_loc.get('city', '')
                            state = scan_loc.get('stateOrProvinceCode', '')
                            location_str = f"{city}, {state}" if city and state else city or state
                            
                            result.events.append({
                                'timestamp': event.get('date', ''),
                                'status': event.get('eventType', ''),
                                'description': event.get('eventDescription', ''),
                                'location': location_str
                            })
                    
                    result.success = True
                else:
                    result.error = "No tracking information found"
                    result.success = False
            else:
                result.error = "No tracking information found"
                result.success = False
                
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                result.error = "Tracking number not found"
            else:
                result.error = f"FedEx API error: {str(e)}"
            result.success = False
            logger.error(f"FedEx tracking error for {tracking_number}: {str(e)}")
            
        except Exception as e:
            result.error = f"Tracking failed: {str(e)}"
            result.success = False
            logger.error(f"FedEx tracking exception for {tracking_number}: {str(e)}")
        
        return result
    
    def _standardize_status(self, fedex_code: str) -> str:
        """Convert FedEx status code to standard status"""
        
        # If no code, return unknown
        if not fedex_code:
            return self.STATUS_UNKNOWN
        
        # Normalize the code
        code = str(fedex_code).upper().strip()
        
        # Comprehensive status mapping
        status_map = {
            # Pre-transit
            'PU': self.STATUS_PRE_TRANSIT,
            'PICKUP': self.STATUS_PRE_TRANSIT,
            'READY_FOR_PICKUP': self.STATUS_PRE_TRANSIT,
            
            # In transit
            'IT': self.STATUS_IN_TRANSIT,
            'IN_TRANSIT': self.STATUS_IN_TRANSIT,
            'AR': self.STATUS_IN_TRANSIT,  # Arrived at facility
            'DP': self.STATUS_IN_TRANSIT,  # Departed facility
            'AT_FEDEX_FACILITY': self.STATUS_IN_TRANSIT,
            'AT_FEDEX_DESTINATION_FACILITY': self.STATUS_IN_TRANSIT,
            'IN_FEDEX_POSSESSION': self.STATUS_IN_TRANSIT,
            
            # Out for delivery
            'OD': self.STATUS_OUT_FOR_DELIVERY,
            'OUT_FOR_DELIVERY': self.STATUS_OUT_FOR_DELIVERY,
            'ON_FEDEX_VEHICLE_FOR_DELIVERY': self.STATUS_OUT_FOR_DELIVERY,
            
            # Delivered
            'DL': self.STATUS_DELIVERED,
            'DELIVERED': self.STATUS_DELIVERED,
            'DELIVERY': self.STATUS_DELIVERED,
            
            # Exception
            'DE': self.STATUS_EXCEPTION,
            'EXCEPTION': self.STATUS_EXCEPTION,
            'DELAY': self.STATUS_EXCEPTION,
            'DELAYED': self.STATUS_EXCEPTION,
            
            # Return to sender
            'RS': self.STATUS_RETURN_TO_SENDER,
            'RETURN_TO_SENDER': self.STATUS_RETURN_TO_SENDER,
        }
        
        # Try exact match first
        if code in status_map:
            return status_map[code]
        
        # Try partial matching for compound codes
        for key, value in status_map.items():
            if key in code or code in key:
                return value
        
        # If description contains key phrases, infer status
        # (This is a fallback for when code doesn't match)
        return self.STATUS_UNKNOWN
    
    def _infer_status_from_description(self, description: str) -> str:
        """Infer status from description text when code is unavailable"""
        if not description:
            return self.STATUS_UNKNOWN
        
        desc_lower = description.lower()
        
        # Delivered patterns
        if any(word in desc_lower for word in ['delivered', 'left at', 'signed for']):
            return self.STATUS_DELIVERED
        
        # Out for delivery patterns
        if any(word in desc_lower for word in ['out for delivery', 'on vehicle', 'loaded on']):
            return self.STATUS_OUT_FOR_DELIVERY
        
        # In transit patterns
        if any(word in desc_lower for word in ['in transit', 'departed', 'arrived', 'at facility', 'at fedex']):
            return self.STATUS_IN_TRANSIT
        
        # Exception patterns
        if any(word in desc_lower for word in ['exception', 'delay', 'unable', 'attempted', 'missed']):
            return self.STATUS_EXCEPTION
        
        # Pre-transit patterns
        if any(word in desc_lower for word in ['picked up', 'shipment information', 'label created']):
            return self.STATUS_PRE_TRANSIT
        
        return self.STATUS_UNKNOWN