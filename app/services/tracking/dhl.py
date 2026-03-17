"""
DHL Tracking API Integration
Uses DHL Unified Tracking API v2 with API key authentication.
No OAuth — credentials go in the DHL-API-Key request header.
"""

import requests
from datetime import datetime
import logging
from .base import BaseCarrier, TrackingResult

logger = logging.getLogger(__name__)


class DHLTracker(BaseCarrier):
    """DHL tracking via Unified Tracking API v2."""

    # DHL uses https://api.dhl.com, not a sandbox subdomain
    DEFAULT_URL = 'https://api.dhl.com'

    def __init__(self, config):
        self.config = config
        self.carrier_name = 'DHL'
        self.api_key = config.get('DHL_API_KEY')
        self.api_url = config.get('DHL_API_URL', self.DEFAULT_URL)

    def track(self, tracking_number: str) -> TrackingResult:
        """
        Track a DHL shipment.
        API: GET /track/shipments?trackingNumber={number}
        Auth: DHL-API-Key header
        """
        result = TrackingResult()
        result.carrier = 'DHL'
        result.tracking_number = tracking_number

        if not self.api_key:
            result.error = 'DHL API key not configured'
            result.success = False
            return result

        try:
            response = requests.get(
                f"{self.api_url}/track/shipments",
                params={'trackingNumber': tracking_number},
                headers={
                    'DHL-API-Key': self.api_key,
                    'Accept': 'application/json',
                },
                timeout=15
            )
            response.raise_for_status()

            data = response.json()
            result.raw_response = data

            shipments = data.get('shipments', [])
            if not shipments:
                result.error = 'No tracking information found'
                result.success = False
                return result

            shipment = shipments[0]
            status_obj = shipment.get('status', {})

            result.status = self._standardize_status(
                status_obj.get('statusCode', '') or status_obj.get('status', '')
            )
            result.status_description = status_obj.get('description', '')

            # Current location from status
            loc = status_obj.get('location', {}).get('address', {})
            city = loc.get('addressLocality', '')
            country = loc.get('countryCode', '')
            result.location = f"{city}, {country}" if city and country else city or country

            # Estimated delivery
            estimated = shipment.get('estimatedTimeOfDelivery') or shipment.get('estimatedDeliveryTime')
            if estimated:
                try:
                    result.estimated_delivery = datetime.fromisoformat(
                        str(estimated).replace('Z', '+00:00')
                    )
                except (ValueError, AttributeError):
                    pass

            # Actual delivery from events
            if result.status == self.STATUS_DELIVERED:
                events_list = shipment.get('events', [])
                for ev in events_list:
                    if self._standardize_status(ev.get('statusCode', '')) == self.STATUS_DELIVERED:
                        ts = ev.get('timestamp')
                        if ts:
                            try:
                                result.actual_delivery = datetime.fromisoformat(
                                    str(ts).replace('Z', '+00:00')
                                )
                            except (ValueError, AttributeError):
                                pass
                        result.delivered_to = ev.get('description', '')
                        break

            # Events
            for ev in shipment.get('events', []):
                ev_loc = ev.get('location', {}).get('address', {})
                ev_city = ev_loc.get('addressLocality', '')
                ev_country = ev_loc.get('countryCode', '')
                loc_str = f"{ev_city}, {ev_country}" if ev_city and ev_country else ev_city or ev_country

                result.events.append({
                    'timestamp': ev.get('timestamp'),
                    'status': ev.get('statusCode', ''),
                    'description': ev.get('description', ''),
                    'location': loc_str,
                })

            result.success = True

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else 0
            if status_code == 404:
                result.error = 'Tracking number not found'
            elif status_code == 401:
                result.error = 'DHL API key invalid or unauthorised'
            else:
                result.error = f'DHL API error: {e}'
            result.success = False
            logger.error(f'DHL tracking HTTP error for {tracking_number}: {e}')

        except Exception as e:
            result.error = f'Tracking failed: {e}'
            result.success = False
            logger.error(f'DHL tracking exception for {tracking_number}: {e}')

        return result

    def _standardize_status(self, dhl_code: str) -> str:
        """Map DHL statusCode to a standard status."""
        if not dhl_code:
            return self.STATUS_UNKNOWN

        code = dhl_code.upper().strip()

        status_map = {
            # Pre-transit
            'PRE-TRANSIT':          self.STATUS_PRE_TRANSIT,
            'SHIPMENT_PICKED_UP':   self.STATUS_PRE_TRANSIT,
            'LABEL_CREATED':        self.STATUS_PRE_TRANSIT,
            # In transit
            'TRANSIT':              self.STATUS_IN_TRANSIT,
            'IN_TRANSIT':           self.STATUS_IN_TRANSIT,
            'IN-TRANSIT':           self.STATUS_IN_TRANSIT,
            'CUSTOMS':              self.STATUS_IN_TRANSIT,
            'CLEARANCE':            self.STATUS_IN_TRANSIT,
            # Out for delivery
            'DELIVERY':             self.STATUS_OUT_FOR_DELIVERY,
            'OUT_FOR_DELIVERY':     self.STATUS_OUT_FOR_DELIVERY,
            'WITH_DELIVERY_COURIER':self.STATUS_OUT_FOR_DELIVERY,
            # Delivered
            'DELIVERED':            self.STATUS_DELIVERED,
            # Available for pickup
            'AVAILABLE_FOR_PICKUP': self.STATUS_AVAILABLE_FOR_PICKUP,
            'HELD_FOR_PICKUP':      self.STATUS_AVAILABLE_FOR_PICKUP,
            # Failed attempt
            'ATTEMPTED_DELIVERY':   self.STATUS_FAILED_ATTEMPT,
            'DELIVERY_ATTEMPTED':   self.STATUS_FAILED_ATTEMPT,
            # Exception / returned
            'EXCEPTION':            self.STATUS_EXCEPTION,
            'RETURN_TO_SENDER':     self.STATUS_RETURN_TO_SENDER,
            'RETURNED':             self.STATUS_RETURN_TO_SENDER,
        }

        if code in status_map:
            return status_map[code]

        # Substring fallback
        if 'DELIVERED' in code:
            return self.STATUS_DELIVERED
        if 'DELIVERY' in code:
            return self.STATUS_OUT_FOR_DELIVERY
        if 'TRANSIT' in code or 'CUSTOMS' in code:
            return self.STATUS_IN_TRANSIT
        if 'RETURN' in code:
            return self.STATUS_RETURN_TO_SENDER
        if 'EXCEPTION' in code or 'FAILED' in code:
            return self.STATUS_EXCEPTION

        return self.STATUS_UNKNOWN
