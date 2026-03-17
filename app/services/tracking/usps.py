"""
USPS Tracking API Integration (OAuth 2.0 v3)
Uses the modern USPS REST API with client_credentials grant.
"""

import requests
from typing import Optional
from datetime import datetime, timedelta
import logging
from .base import BaseCarrier, TrackingResult

logger = logging.getLogger(__name__)


class USPSTracker(BaseCarrier):
    """USPS tracking via OAuth 2.0 API v3"""

    def __init__(self, config):
        self.config = config
        self.carrier_name = 'USPS'
        self.consumer_key = config.get('USPS_CONSUMER_KEY')
        self.consumer_secret = config.get('USPS_CONSUMER_SECRET')
        self.api_url = config.get('USPS_API_URL', 'https://apis.usps.com')
        self._access_token = None
        self._token_expiry = None

    def _get_access_token(self) -> str:
        """Get OAuth 2.0 access token using client_credentials grant."""
        if self._access_token and self._token_expiry:
            if datetime.now() < self._token_expiry:
                return self._access_token

        token_url = f"{self.api_url}/oauth2/v3/token"

        try:
            response = requests.post(
                token_url,
                data={
                    'grant_type': 'client_credentials',
                    'client_id': self.consumer_key,
                    'client_secret': self.consumer_secret,
                },
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=10
            )
            response.raise_for_status()
            token_data = response.json()

            self._access_token = token_data['access_token']
            expires_in = int(float(token_data.get('expires_in', 3600)))
            self._token_expiry = datetime.now() + timedelta(seconds=int(expires_in * 0.95))

            return self._access_token

        except requests.exceptions.RequestException as e:
            logger.error(f"USPS OAuth token error: {e}")
            raise Exception(f"Failed to get USPS access token: {e}")

    def track(self, tracking_number: str) -> TrackingResult:
        """
        Track a USPS package.
        API: GET /tracking/v3/tracking/{trackingNumber}?expand=DETAIL
        Response is a flat object (not wrapped in an array).
        """
        result = TrackingResult()
        result.carrier = 'USPS'
        result.tracking_number = tracking_number

        try:
            token = self._get_access_token()

            tracking_url = f"{self.api_url}/tracking/v3/tracking/{tracking_number}"
            headers = {
                'Authorization': f'Bearer {token}',
                'Accept': 'application/json',
            }

            response = requests.get(
                tracking_url,
                params={'expand': 'DETAIL'},
                headers=headers,
                timeout=15
            )
            response.raise_for_status()

            data = response.json()
            result.raw_response = data

            # USPS v3 returns a flat object directly — no wrapper array
            result.status = self._standardize_status(
                data.get('statusCategory', '') or data.get('status', '')
            )
            result.status_description = data.get('statusSummary', data.get('status', ''))

            # Estimated delivery
            expected = data.get('expectedDeliveryDate') or data.get('predictedDeliveryFullDate')
            if expected:
                try:
                    result.estimated_delivery = datetime.fromisoformat(
                        str(expected).replace('Z', '+00:00')
                    )
                except (ValueError, AttributeError):
                    pass

            # Delivered details — look in trackSummary for the latest scan
            track_summary = data.get('trackSummary', {})
            if result.status == self.STATUS_DELIVERED and track_summary:
                event_ts = track_summary.get('eventTimestamp')
                if event_ts:
                    try:
                        result.actual_delivery = datetime.fromisoformat(
                            str(event_ts).replace('Z', '+00:00')
                        )
                    except (ValueError, AttributeError):
                        pass
                result.delivered_to = data.get('deliveryAttributeCode', '')

            # Current location from trackSummary
            if track_summary:
                city = track_summary.get('eventCity', '')
                state = track_summary.get('eventState', '')
                result.location = f"{city}, {state}" if city and state else city or state

            # Destination fallback when no summary location
            if not result.location:
                city = data.get('destinationCity', '')
                state = data.get('destinationState', '')
                result.location = f"{city}, {state}" if city and state else city or state

            # Events from trackDetail array
            for event in data.get('trackDetail', []):
                city = event.get('eventCity', '')
                state = event.get('eventState', '')
                loc = f"{city}, {state}" if city and state else city or state
                result.events.append({
                    'timestamp': event.get('eventTimestamp'),
                    'status': event.get('eventType', event.get('event', '')),
                    'description': event.get('eventSummary', event.get('event', '')),
                    'location': loc,
                })

            # Prepend the summary event as the most recent entry if present
            if track_summary:
                city = track_summary.get('eventCity', '')
                state = track_summary.get('eventState', '')
                loc = f"{city}, {state}" if city and state else city or state
                result.events.insert(0, {
                    'timestamp': track_summary.get('eventTimestamp'),
                    'status': track_summary.get('eventType', track_summary.get('event', '')),
                    'description': track_summary.get('eventSummary', track_summary.get('event', '')),
                    'location': loc,
                })

            result.success = True

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else 0
            if status_code == 404:
                result.error = "Tracking number not found"
            elif status_code == 400:
                result.error = "Invalid tracking number format"
            else:
                result.error = f"USPS API error: {e}"
            result.success = False
            logger.error(f"USPS tracking HTTP error for {tracking_number}: {e}")

        except Exception as e:
            result.error = f"Tracking failed: {e}"
            result.success = False
            logger.error(f"USPS tracking exception for {tracking_number}: {e}")

        return result

    def _standardize_status(self, usps_status: str) -> str:
        """Map USPS statusCategory or status string to a standard status code."""
        if not usps_status:
            return self.STATUS_UNKNOWN

        s = usps_status.upper().strip()

        status_map = {
            # --- statusCategory enum values from USPS v3 API ---
            'PRE_TRANSIT':              self.STATUS_PRE_TRANSIT,
            'LABEL_CREATED':            self.STATUS_PRE_TRANSIT,
            # USPS uses 'TRANSIT', not 'IN_TRANSIT'
            'TRANSIT':                  self.STATUS_IN_TRANSIT,
            'IN_TRANSIT':               self.STATUS_IN_TRANSIT,
            'ACCEPTED':                 self.STATUS_IN_TRANSIT,
            'OUT_FOR_DELIVERY':         self.STATUS_OUT_FOR_DELIVERY,
            'DELIVERED':                self.STATUS_DELIVERED,
            'AVAILABLE_FOR_PICKUP':     self.STATUS_AVAILABLE_FOR_PICKUP,
            'RETURN_TO_SENDER':         self.STATUS_RETURN_TO_SENDER,
            'UNDELIVERABLE':            self.STATUS_RETURN_TO_SENDER,
            'DELIVERY_ATTEMPTED':       self.STATUS_FAILED_ATTEMPT,
            'ALERT':                    self.STATUS_EXCEPTION,
            'INTERCEPTED':              self.STATUS_EXCEPTION,
            # --- Human-readable status strings (fallback for older/text responses) ---
            'PRE-SHIPMENT':             self.STATUS_PRE_TRANSIT,
            'LABEL CREATED':            self.STATUS_PRE_TRANSIT,
            'IN TRANSIT':               self.STATUS_IN_TRANSIT,
            'MOVING':                   self.STATUS_IN_TRANSIT,
            'OUT FOR DELIVERY':         self.STATUS_OUT_FOR_DELIVERY,
            'AVAILABLE FOR PICKUP':     self.STATUS_AVAILABLE_FOR_PICKUP,
            'RETURN TO SENDER':         self.STATUS_RETURN_TO_SENDER,
            'DELIVERY ATTEMPTED':       self.STATUS_FAILED_ATTEMPT,
        }

        if s in status_map:
            return status_map[s]

        # Substring fallback
        if 'DELIVERED' in s:
            return self.STATUS_DELIVERED
        if 'OUT FOR DELIVERY' in s or 'OUT_FOR_DELIVERY' in s:
            return self.STATUS_OUT_FOR_DELIVERY
        if 'IN TRANSIT' in s or 'IN_TRANSIT' in s or 'TRANSIT' in s:
            return self.STATUS_IN_TRANSIT
        if 'MOVING' in s or 'NETWORK' in s:
            return self.STATUS_IN_TRANSIT
        if 'RETURN' in s:
            return self.STATUS_RETURN_TO_SENDER
        if 'ATTEMPTED' in s or 'NOTICE LEFT' in s:
            return self.STATUS_FAILED_ATTEMPT
        if 'PICKUP' in s:
            return self.STATUS_AVAILABLE_FOR_PICKUP

        return self.STATUS_UNKNOWN
