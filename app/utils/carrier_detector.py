"""
Carrier Detection Utility
Automatically detects carrier from tracking number format
"""

import re
from typing import Optional


class CarrierDetector:
    """Detect shipping carrier from tracking number format"""
    
    @staticmethod
    def detect(tracking_number: str) -> str:
        """
        Detect carrier from tracking number format
        
        Args:
            tracking_number: The tracking number to analyze
            
        Returns:
            'USPS', 'UPS', 'FEDEX', or 'UNKNOWN'
        """
        if not tracking_number:
            return 'UNKNOWN'
        
        # Clean the tracking number
        cleaned = tracking_number.strip().replace(' ', '').replace('-', '').upper()
        
        # Check patterns in priority order
        if CarrierDetector._is_usps(cleaned):
            return 'USPS'
        if CarrierDetector._is_ups(cleaned):
            return 'UPS'
        if CarrierDetector._is_fedex(cleaned):
            return 'FEDEX'
        if CarrierDetector._is_dhl(cleaned):
            return 'DHL'

        return 'UNKNOWN'
    
    @staticmethod
    def _is_usps(tracking: str) -> bool:
        """
        Check if tracking number matches USPS format.
        All patterns are prefix-anchored — no generic digit-count fallbacks
        that could steal numbers from FedEx or UPS.
        """
        patterns = [
            # 22-digit IMpb (prefix + 20 digits)
            r'^94\d{20}$',           # Priority Mail, Signature Confirmation
            r'^93\d{20}$',           # Signature Confirmation (intl)
            r'^92\d{20}$',           # Certified Mail
            r'^91\d{20}$',           # Priority Mail Express
            r'^90\d{20}$',           # Priority Mail (alt)
            # 30-digit IMpb (extended barcode — e.g. certified mail labels)
            r'^94\d{28}$',
            r'^93\d{28}$',
            r'^92\d{28}$',
            r'^91\d{28}$',
            r'^90\d{28}$',
            # Other USPS-specific formats
            r'^82\d{8}$',            # Registered Mail (10-digit)
            r'^70\d{14}$',           # Certified Mail (older 16-digit)
            r'^[A-Z]{2}\d{9}US$',    # International (EA123456789US format)
        ]
        return any(re.match(pattern, tracking) for pattern in patterns)
    
    @staticmethod
    def _is_ups(tracking: str) -> bool:
        """Check if tracking number matches UPS format"""
        patterns = [
            r'^1Z[A-Z0-9]{16}$',    # Standard UPS (1Z...)
            r'^[HKT]\d{10}$',       # UPS Mail Innovations
            r'^\d{18}$',            # UPS Ground (18 digits)
            r'^\d{26}$',            # UPS Next Day Air (26 digits)
        ]
        return any(re.match(pattern, tracking) for pattern in patterns)
    
    @staticmethod
    def _is_fedex(tracking: str) -> bool:
        """Check if tracking number matches FedEx format"""
        patterns = [
            r'^\d{12}$',            # FedEx Express (12 digits)
            r'^\d{15}$',            # FedEx Ground (15 digits)
            r'^\d{20}$',            # FedEx Ground (20 digits)
            r'^\d{22}$',            # FedEx SmartPost (22 digits)
            r'^\d{34}$',            # FedEx Ground (34 digits)
        ]
        return any(re.match(pattern, tracking) for pattern in patterns)
    
    @staticmethod
    def _is_dhl(tracking: str) -> bool:
        """Check if tracking number matches DHL format"""
        patterns = [
            r'^\d{10}$',               # DHL Express (10 digits)
            r'^JD\d{18}$',             # DHL Parcel (JD + 18 digits)
            r'^GM\d{16}$',             # DHL Parcel (GM + 16 digits)
            r'^[A-Z]{2}\d{9}[A-Z]{2}$',  # DHL international (e.g. EA123456789DE)
            r'^\d{11}$',               # DHL Express (11 digits)
        ]
        return any(re.match(pattern, tracking) for pattern in patterns)

    @staticmethod
    def get_carrier_name(carrier_code: str) -> str:
        """Get friendly carrier name"""
        names = {
            'USPS':  'United States Postal Service',
            'UPS':   'United Parcel Service',
            'FEDEX': 'FedEx',
            'DHL':   'DHL Express',
            'UNKNOWN': 'Unknown Carrier'
        }
        return names.get(carrier_code, 'Unknown Carrier')
    
    @staticmethod
    def get_carrier_url(carrier_code: str, tracking_number: str) -> Optional[str]:
        """Get carrier tracking URL"""
        tracking = tracking_number.replace(' ', '').replace('-', '')
        
        urls = {
            'USPS':  f'https://tools.usps.com/go/TrackConfirmAction?tLabels={tracking}',
            'UPS':   f'https://www.ups.com/track?loc=en_US&tracknum={tracking}',
            'FEDEX': f'https://www.fedex.com/fedextrack/?trknbr={tracking}',
            'DHL':   f'https://www.dhl.com/us-en/home/tracking.html?tracking-id={tracking}',
        }

        return urls.get(carrier_code)