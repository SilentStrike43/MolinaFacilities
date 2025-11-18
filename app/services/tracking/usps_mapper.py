"""
USPS Service Type Mapper
Maps USPS API responses to human-readable service types
"""

class USPSServiceMapper:
    """Maps USPS mail classes and service types to display names"""
    
    # USPS Mail Classes
    MAIL_CLASS_MAP = {
        'PRIORITY_MAIL': 'Priority Mail',
        'PRIORITY_MAIL_EXPRESS': 'Priority Mail Express',
        'FIRST_CLASS_MAIL': 'First-Class Mail',
        'FIRST_CLASS_PACKAGE_SERVICE': 'First-Class Package Service',
        'PARCEL_SELECT': 'USPS Ground Advantage',
        'MEDIA_MAIL': 'Media Mail',
        'LIBRARY_MAIL': 'Library Mail',
        'BOUND_PRINTED_MATTER': 'Bound Printed Matter',
        'USPS_RETAIL_GROUND': 'USPS Retail Ground',
        'USPS_MARKETING_MAIL': 'USPS Marketing Mail',
        'CERTIFIED_MAIL': 'Certified Mail',
        'REGISTERED_MAIL': 'Registered Mail',
        'INSURED_MAIL': 'Insured Mail',
        'SIGNATURE_CONFIRMATION': 'Signature Confirmation',
        'RETURN_RECEIPT': 'Return Receipt',
        'COLLECT_ON_DELIVERY': 'Collect on Delivery',
    }
    
    # USPS Service Types (more specific)
    SERVICE_TYPE_MAP = {
        'USPS_PRIORITY_MAIL': 'Priority Mail',
        'USPS_PRIORITY_MAIL_EXPRESS': 'Priority Mail Express',
        'USPS_FIRST_CLASS': 'First-Class Mail',
        'USPS_FIRST_CLASS_PACKAGE': 'First-Class Package',
        'USPS_GROUND_ADVANTAGE': 'USPS Ground Advantage',
        'USPS_MEDIA_MAIL': 'Media Mail',
        'USPS_LIBRARY_MAIL': 'Library Mail',
    }
    
    # Package type mapping based on USPS descriptions
    PACKAGE_TYPE_MAP = {
        'LETTER': 'Letter',
        'FLAT': 'Envelope',
        'PARCEL': 'Package',
        'PACKAGE': 'Package',
        'FLAT_RATE_ENVELOPE': 'Envelope',
        'FLAT_RATE_BOX': 'Box',
        'SMALL_FLAT_RATE_BOX': 'Small Box',
        'MEDIUM_FLAT_RATE_BOX': 'Medium Box',
        'LARGE_FLAT_RATE_BOX': 'Large Box',
        'REGIONAL_RATE_BOX_A': 'Box',
        'REGIONAL_RATE_BOX_B': 'Box',
    }
    
    @classmethod
    def get_service_type(cls, mail_class: str, service_type: str = None) -> str:
        """
        Get human-readable service type
        
        Args:
            mail_class: USPS mail class from API
            service_type: Optional service type from API
            
        Returns:
            Human-readable service name
        """
        if not mail_class:
            return 'USPS Mail'
        
        # Clean up the input
        mail_class = mail_class.upper().replace(' ', '_').replace('-', '_')
        
        # Try service type first if provided
        if service_type:
            service_type = service_type.upper().replace(' ', '_').replace('-', '_')
            if service_type in cls.SERVICE_TYPE_MAP:
                return cls.SERVICE_TYPE_MAP[service_type]
        
        # Try mail class
        if mail_class in cls.MAIL_CLASS_MAP:
            return cls.MAIL_CLASS_MAP[mail_class]
        
        # Return cleaned version if no match
        return mail_class.replace('_', ' ').title()
    
    @classmethod
    def get_package_type(cls, package_type: str) -> str:
        """
        Get standardized package type
        
        Args:
            package_type: USPS package type from API
            
        Returns:
            Standardized package type
        """
        if not package_type:
            return 'Package'
        
        package_type = package_type.upper().replace(' ', '_').replace('-', '_')
        
        return cls.PACKAGE_TYPE_MAP.get(package_type, 'Package')
    
    @classmethod
    def parse_tracking_response(cls, track_info: dict) -> dict:
        """
        Parse USPS tracking response into standardized format
        
        Args:
            track_info: USPS trackResults[0] object
            
        Returns:
            Dictionary with standardized fields
        """
        # Get service type
        mail_class = track_info.get('mailClass', '')
        service_type = track_info.get('serviceType', '')
        display_service = cls.get_service_type(mail_class, service_type)
        
        # Get package type
        package_type = track_info.get('packageType', '')
        display_package_type = cls.get_package_type(package_type)
        
        # Parse destination address
        destination_address = None
        if track_info.get('destinationCity'):
            parts = [
                track_info.get('destinationCity', ''),
                track_info.get('destinationState', ''),
                track_info.get('destinationZIP', '')
            ]
            destination_address = ', '.join(p for p in parts if p)
        
        # Parse origin address
        origin_address = None
        if track_info.get('originCity'):
            parts = [
                track_info.get('originCity', ''),
                track_info.get('originState', ''),
                track_info.get('originZIP', '')
            ]
            origin_address = ', '.join(p for p in parts if p)
        
        # Get latest event details
        latest_location = None
        latest_event_time = None
        if 'events' in track_info and track_info['events']:
            latest_event = track_info['events'][0]
            event_parts = [
                latest_event.get('eventCity', ''),
                latest_event.get('eventState', ''),
                latest_event.get('eventZIP', '')
            ]
            latest_location = ', '.join(p for p in event_parts if p)
            latest_event_time = latest_event.get('eventTimestamp')
        
        return {
            'service_type': display_service,
            'package_type': display_package_type,
            'mail_class': mail_class,
            'status': track_info.get('status', ''),
            'status_category': track_info.get('statusCategory', ''),
            'status_summary': track_info.get('statusSummary', ''),
            'destination_city': track_info.get('destinationCity', ''),
            'destination_state': track_info.get('destinationState', ''),
            'destination_zip': track_info.get('destinationZIP', ''),
            'destination_address': destination_address,
            'origin_city': track_info.get('originCity', ''),
            'origin_state': track_info.get('originState', ''),
            'origin_zip': track_info.get('originZIP', ''),
            'origin_address': origin_address,
            'latest_location': latest_location,
            'latest_event_time': latest_event_time,
            'expected_delivery': track_info.get('expectedDeliveryDate'),
            'raw_mail_class': track_info.get('mailClass'),
            'raw_service_type': track_info.get('serviceType'),
        }