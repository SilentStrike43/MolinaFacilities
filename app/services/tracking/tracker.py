"""
Main Tracking Service
Orchestrates all carrier APIs
"""

import logging
from typing import Optional
from .base import TrackingResult
from .usps import USPSTracker
from .fedex import FedExTracker
from .ups import UPSTracker
from app.utils.carrier_detector import CarrierDetector

logger = logging.getLogger(__name__)


class TrackingService:
    """
    Main tracking service - automatically detects carrier and routes to correct API
    """
    
    def __init__(self, config):
        self.config = config
        self.usps = USPSTracker(config)
        self.fedex = FedExTracker(config)
        self.ups = UPSTracker(config)
    
    def track(self, tracking_number: str, carrier: Optional[str] = None) -> TrackingResult:
        """
        Track a package across all carriers
        
        Args:
            tracking_number: The tracking number to look up
            carrier: Optional - specify carrier ('USPS', 'FEDEX', 'UPS')
                    If not provided, will auto-detect
        
        Returns:
            TrackingResult object
        """
        # Auto-detect carrier if not specified
        if not carrier:
            carrier = CarrierDetector.detect(tracking_number)
        
        logger.info(f"Tracking {tracking_number} via {carrier}")
        
        # Route to appropriate carrier
        if carrier == 'USPS':
            return self.usps.track(tracking_number)
        elif carrier == 'FEDEX':
            return self.fedex.track(tracking_number)
        elif carrier == 'UPS':
            return self.ups.track(tracking_number)
        else:
            # Unknown carrier - return error
            result = TrackingResult()
            result.carrier = 'UNKNOWN'
            result.tracking_number = tracking_number
            result.error = f"Unsupported carrier: {carrier}"
            result.success = False
            return result
    
    def bulk_track(self, tracking_numbers: list) -> dict:
        """
        Track multiple packages at once
        
        Args:
            tracking_numbers: List of tracking numbers
        
        Returns:
            Dictionary mapping tracking_number -> TrackingResult
        """
        results = {}
        
        for tracking_number in tracking_numbers:
            try:
                results[tracking_number] = self.track(tracking_number)
            except Exception as e:
                logger.error(f"Error tracking {tracking_number}: {str(e)}")
                result = TrackingResult()
                result.tracking_number = tracking_number
                result.error = str(e)
                result.success = False
                results[tracking_number] = result
        
        return results