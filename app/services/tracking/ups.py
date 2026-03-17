"""
UPS Tracking API Integration (OAuth 2.0)
"""

import uuid
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
        
        # UPS OAuth endpoint is at the root host, not under /api
        base_host = self.api_url.rstrip('/').replace('/api', '')
        token_url = f"{base_host}/security/v1/oauth/token"
        
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
            expires_in = int(float(token_data.get('expires_in', 3600)))
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
                'Content-Type': 'application/json',
                'transId': str(uuid.uuid4()),        # required: unique per request
                'transactionSrc': 'GridlineService', # required: identifies the app
            }

            params = {
                'locale': 'en_US',
                'returnSignature': 'false',
            }
            
            response = requests.get(tracking_url, headers=headers, params=params, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            result.raw_response = data
            
            # Parse UPS response
            if 'trackResponse' in data and 'shipment' in data['trackResponse']:
                shipment = data['trackResponse']['shipment'][0]
                package = shipment['package'][0]

                # Current status — UPS uses 'type' (single letter) on activity items
                # and may use 'code' or 'type' on currentStatus depending on API version.
                current_status = package.get('currentStatus', {})
                logger.info(f"UPS currentStatus raw: {current_status}")

                status_code = (
                    current_status.get('type')          # preferred: single-letter type
                    or current_status.get('code')        # fallback: may be numeric
                    or current_status.get('statusCode')  # alt field name
                )

                # If currentStatus gave nothing useful, fall back to the first activity
                if not status_code and package.get('activity'):
                    first = package['activity'][0]
                    activity_status = first.get('status', {})
                    logger.info(f"UPS first activity status raw: {activity_status}")
                    status_code = (
                        activity_status.get('type')
                        or activity_status.get('code')
                    )

                status_desc = (
                    current_status.get('description')
                    or current_status.get('simplifiedTextDescription', '')
                )
                logger.info(f"UPS resolved status_code: {status_code!r} -> {self._standardize_status(status_code or '', status_desc)}")

                result.status_description = (
                    current_status.get('description')
                    or current_status.get('simplifiedTextDescription', '')
                )
                result.status = self._standardize_status(status_code or '', result.status_description)
                
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
                logger.info(f"UPS response top-level keys: {list(data.keys())}")
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
    
    def _standardize_status(self, ups_code: str, description: str = '') -> str:
        """Convert UPS status code to standard status.

        UPS currentStatus returns 3-digit activity codes (e.g. '011').
        Activity items use single-letter type codes (e.g. 'D', 'I').
        Both are handled here; description is used as a final fallback.
        """
        if not ups_code and not description:
            return self.STATUS_UNKNOWN

        code = str(ups_code).upper().strip()

        status_map = {
            # ── 3-digit activity codes (currentStatus.code) ──────────────
            '001': self.STATUS_IN_TRANSIT,          # Pickup scan
            '003': self.STATUS_IN_TRANSIT,          # Pickup scan (alt)
            '007': self.STATUS_IN_TRANSIT,          # Arrived at facility
            '008': self.STATUS_IN_TRANSIT,          # Destination scan
            '010': self.STATUS_OUT_FOR_DELIVERY,    # Out for delivery
            '011': self.STATUS_DELIVERED,           # Delivered
            '013': self.STATUS_FAILED_ATTEMPT,      # Delivery attempted
            '014': self.STATUS_AVAILABLE_FOR_PICKUP,# Available for pickup
            '015': self.STATUS_EXCEPTION,           # Exception
            '016': self.STATUS_EXCEPTION,           # Exception
            '017': self.STATUS_EXCEPTION,           # Exception
            '018': self.STATUS_EXCEPTION,           # Exception
            '021': self.STATUS_RETURN_TO_SENDER,    # Return to sender
            '022': self.STATUS_EXCEPTION,           # Undeliverable
            '031': self.STATUS_IN_TRANSIT,          # Transferred to dest facility
            '033': self.STATUS_IN_TRANSIT,          # Departed facility
            '034': self.STATUS_IN_TRANSIT,          # Arrived at facility
            '040': self.STATUS_IN_TRANSIT,          # Departure scan
            '041': self.STATUS_IN_TRANSIT,          # Arrival scan
            '042': self.STATUS_IN_TRANSIT,          # In transit
            '045': self.STATUS_OUT_FOR_DELIVERY,    # Out for delivery (alt)
            '051': self.STATUS_DELIVERED,           # Delivered (left at door)
            '052': self.STATUS_DELIVERED,           # Delivered (signed)
            '053': self.STATUS_PRE_TRANSIT,         # Label created
            '055': self.STATUS_PRE_TRANSIT,         # Order processed
            '056': self.STATUS_PRE_TRANSIT,         # Label created (alt)
            # ── Single-letter type codes (activity.status.type) ──────────
            'M':  self.STATUS_PRE_TRANSIT,
            'P':  self.STATUS_IN_TRANSIT,
            'I':  self.STATUS_IN_TRANSIT,
            'O':  self.STATUS_OUT_FOR_DELIVERY,
            'D':  self.STATUS_DELIVERED,
            'X':  self.STATUS_EXCEPTION,
            'RS': self.STATUS_RETURN_TO_SENDER,
            'NA': self.STATUS_FAILED_ATTEMPT,
            'PA': self.STATUS_AVAILABLE_FOR_PICKUP,
        }

        if code in status_map:
            return status_map[code]

        # Description text fallback (uses same logic as FedEx)
        if description:
            desc = description.lower()
            if 'delivered' in desc:
                return self.STATUS_DELIVERED
            if 'out for delivery' in desc:
                return self.STATUS_OUT_FOR_DELIVERY
            if 'in transit' in desc or 'arrival scan' in desc or 'departed' in desc:
                return self.STATUS_IN_TRANSIT
            if 'attempted' in desc or 'notice left' in desc:
                return self.STATUS_FAILED_ATTEMPT
            if 'available for pickup' in desc:
                return self.STATUS_AVAILABLE_FOR_PICKUP
            if 'return' in desc:
                return self.STATUS_RETURN_TO_SENDER
            if 'exception' in desc or 'delay' in desc:
                return self.STATUS_EXCEPTION
            if 'label created' in desc or 'order processed' in desc:
                return self.STATUS_PRE_TRANSIT

        return self.STATUS_UNKNOWN