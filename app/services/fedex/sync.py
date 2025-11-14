"""
FedEx Auto-Sync Service
Automatically pull shipments from FedEx account and import to app
"""

import requests
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Optional
from app.core.database import get_db_connection

logger = logging.getLogger(__name__)


class FedExShipmentSync:
    """
    Automatically sync FedEx shipments from account to database
    """
    
    def __init__(self, config):
        # Don't call super().__init__() - just set attributes directly
        self.config = config
        self.carrier_name = 'FEDEX'
        self.api_key = config.get('FEDEX_SHIP_API_KEY')
        self.secret_key = config.get('FEDEX_SHIP_SECRET_KEY')
        self.account_number = config.get('FEDEX_ACCOUNT_NUMBER')
        self.api_url = config.get('FEDEX_API_URL', 'https://apis.fedex.com')
        self._access_token = None
        self._token_expiry = None
    
    def _get_access_token(self) -> Optional[str]:
        """Get OAuth access token from FedEx API"""
        
        # Check if we have a valid cached token
        if self._access_token and self._token_expiry:
            if datetime.now() < self._token_expiry:
                return self._access_token
        
        # Request new token
        logger.info("Requesting new FedEx access token...")
        
        try:
            response = requests.post(
                f"{self.api_url}/oauth/token",
                headers={
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                data={
                    'grant_type': 'client_credentials',
                    'client_id': self.api_key,
                    'client_secret': self.secret_key
                },
                timeout=30
            )
            
            # Log the response for debugging
            logger.info(f"FedEx token response status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                self._access_token = data['access_token']
                expires_in = data.get('expires_in', 3600)
                self._token_expiry = datetime.now() + timedelta(seconds=expires_in - 60)
                logger.info("Successfully obtained FedEx access token")
                return self._access_token
            else:
                error_msg = f"FedEx token request failed: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return None
                
        except Exception as e:
            logger.error(f"Error getting FedEx token: {e}", exc_info=True)
            return None
    
    def sync_recent_shipments(self, hours: int = 1, instance_id: int = None) -> Dict:
        """
        Query FedEx for recent shipments and auto-import them
        
        Args:
            hours: How many hours back to search (default: 1)
            instance_id: Instance ID to assign imported shipments
        
        Returns:
            {
                'success': True/False,
                'imported': count,
                'skipped': count,
                'error': error message if failed
            }
        """
        logger.info(f"Starting FedEx auto-sync for last {hours} hour(s)")
        
        try:
            token = self._get_access_token()
            
            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(hours=hours)
            
            # Query shipments
            url = f"{self.api_url}/ship/v1/shipments/history"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                "accountNumber": {
                    "value": self.account_number
                },
                "shipDateBegin": start_date.strftime("%Y-%m-%d"),
                "shipDateEnd": end_date.strftime("%Y-%m-%d")
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            # Process shipments
            imported_count = 0
            skipped_count = 0
            
            if 'output' in data and 'shipments' in data['output']:
                for shipment_data in data['output']['shipments']:
                    if self._import_shipment(shipment_data, instance_id):
                        imported_count += 1
                    else:
                        skipped_count += 1
            
            logger.info(f"FedEx sync complete: {imported_count} imported, {skipped_count} skipped")
            
            return {
                'success': True,
                'imported': imported_count,
                'skipped': skipped_count
            }
            
        except Exception as e:
            logger.error(f"FedEx sync error: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'imported': 0,
                'skipped': 0
            }
    
    def _import_shipment(self, shipment_data: Dict, instance_id: Optional[int]) -> bool:
        """
        Import a single shipment into database
        
        Returns:
            True if imported, False if skipped (already exists)
        """
        try:
            tracking_number = shipment_data.get('masterTrackingNumber')
            
            if not tracking_number:
                logger.warning("Shipment missing tracking number, skipping")
                return False
            
            # Check if already exists
            with get_db_connection("send") as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT id FROM package_manifest
                    WHERE tracking_number = %s
                """, (tracking_number,))
                
                existing = cursor.fetchone()
                
                if existing:
                    logger.debug(f"Shipment {tracking_number} already exists, skipping")
                    cursor.close()
                    return False
                
                # Extract recipient info
                recipient = shipment_data.get('recipient', {})
                address = recipient.get('address', {})
                
                # Build full address
                street_lines = address.get('streetLines', [])
                address_line1 = street_lines[0] if len(street_lines) > 0 else None
                address_line2 = street_lines[1] if len(street_lines) > 1 else None
                
                full_address_parts = [
                    address_line1,
                    address_line2,
                    address.get('city'),
                    address.get('stateOrProvinceCode'),
                    address.get('postalCode')
                ]
                full_address = ", ".join([p for p in full_address_parts if p])
                
                # Create new shipment record
                cursor.execute("""
                    INSERT INTO package_manifest (
                        instance_id,
                        tracking_number,
                        carrier,
                        recipient_name,
                        recipient_company,
                        recipient_address,
                        address_line1,
                        address_line2,
                        city,
                        state,
                        zip_code,
                        country,
                        source,
                        auto_populated,
                        tracking_status,
                        created_at,
                        checkin_date
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    RETURNING id
                """, (
                    instance_id,
                    tracking_number,
                    'FEDEX',
                    recipient.get('personName', 'Unknown'),
                    recipient.get('companyName'),
                    full_address,
                    address_line1,
                    address_line2,
                    address.get('city'),
                    address.get('stateOrProvinceCode'),
                    address.get('postalCode'),
                    address.get('countryCode', 'US'),
                    'fedex_sync',
                    True,
                    'PRE_TRANSIT',
                    datetime.now(),
                    datetime.now().date()
                ))
                
                row = cursor.fetchone()
                new_id = row['id'] if row else None
                
                conn.commit()
                cursor.close()
                
                logger.info(f"Imported shipment {tracking_number} from FedEx (ID: {new_id})")
                return True
                
        except Exception as e:
            logger.error(f"Error importing shipment: {str(e)}")
            return False