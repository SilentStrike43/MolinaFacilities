"""
Base Carrier API Class
All carrier integrations inherit from this
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from datetime import datetime


class TrackingResult:
    """Standard tracking result format across all carriers"""
    
    def __init__(self):
        self.carrier: str = ''
        self.tracking_number: str = ''
        self.status: str = ''
        self.status_description: str = ''
        self.estimated_delivery: Optional[datetime] = None
        self.actual_delivery: Optional[datetime] = None
        self.delivered_to: Optional[str] = None
        self.signature: Optional[str] = None
        self.location: Optional[str] = None
        self.events: List[Dict] = []
        self.error: Optional[str] = None
        self.success: bool = False
        self.raw_response: Optional[Dict] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'carrier': self.carrier,
            'tracking_number': self.tracking_number,
            'status': self.status,
            'status_description': self.status_description,
            'estimated_delivery': self.estimated_delivery.isoformat() if self.estimated_delivery else None,
            'actual_delivery': self.actual_delivery.isoformat() if self.actual_delivery else None,
            'delivered_to': self.delivered_to,
            'signature': self.signature,
            'location': self.location,
            'events': self.events,
            'error': self.error,
            'success': self.success
        }


class BaseCarrier(ABC):
    """Base class for all carrier API integrations"""
    
    # Standard status codes
    STATUS_PRE_TRANSIT = 'PRE_TRANSIT'
    STATUS_IN_TRANSIT = 'IN_TRANSIT'
    STATUS_OUT_FOR_DELIVERY = 'OUT_FOR_DELIVERY'
    STATUS_DELIVERED = 'DELIVERED'
    STATUS_AVAILABLE_FOR_PICKUP = 'AVAILABLE_FOR_PICKUP'
    STATUS_RETURN_TO_SENDER = 'RETURN_TO_SENDER'
    STATUS_FAILED_ATTEMPT = 'FAILED_ATTEMPT'
    STATUS_EXCEPTION = 'EXCEPTION'
    STATUS_UNKNOWN = 'UNKNOWN'
    
    def __init__(self, config):
        self.config = config
        self.carrier_name = ''
    
    @abstractmethod
    def track(self, tracking_number: str) -> TrackingResult:
        """
        Track a shipment
        
        Args:
            tracking_number: The tracking number to look up
            
        Returns:
            TrackingResult object with tracking information
        """
        pass
    
    def _standardize_status(self, carrier_status: str) -> str:
        """
        Convert carrier-specific status to standard status
        
        Override this in each carrier implementation
        """
        return self.STATUS_UNKNOWN