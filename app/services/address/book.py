"""
Address Book Service
Manage frequently used shipping addresses
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime
from app.core.database import get_db_connection

logger = logging.getLogger(__name__)


class AddressBookService:
    """
    Address book management service
    Store and retrieve frequently used addresses
    """
    
    def __init__(self, instance_id: int):
        self.instance_id = instance_id
    
    def search(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Search address book by name, company, or address
        
        Args:
            query: Search term
            limit: Maximum results to return
            
        Returns:
            List of matching addresses
        """
        try:
            with get_db_connection("send") as conn:
                cursor = conn.cursor()
                
                sql = """
                    SELECT 
                        id,
                        recipient_name,
                        recipient_company,
                        recipient_phone,
                        recipient_email,
                        address_line1,
                        address_line2,
                        city,
                        state,
                        zip_code,
                        country,
                        address_validated,
                        use_count,
                        last_used_at
                    FROM address_book
                    WHERE instance_id = %s
                    AND is_active = TRUE
                    AND (
                        recipient_name ILIKE %s OR
                        recipient_company ILIKE %s OR
                        address_line1 ILIKE %s OR
                        city ILIKE %s OR
                        zip_code ILIKE %s
                    )
                    ORDER BY use_count DESC, recipient_name ASC
                    LIMIT %s
                """
                
                search_term = f"%{query}%"
                cursor.execute(sql, (
                    self.instance_id,
                    search_term, search_term, search_term, search_term, search_term,
                    limit
                ))
                
                results = cursor.fetchall()
                cursor.close()
                
                return [dict(row) for row in results]
                
        except Exception as e:
            logger.error(f"Address book search error: {str(e)}")
            return []
    
    def get_by_id(self, address_id: int) -> Optional[Dict]:
        """
        Get address by ID
        
        Args:
            address_id: Address book entry ID
            
        Returns:
            Address details or None
        """
        try:
            with get_db_connection("send") as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT 
                        id,
                        recipient_name,
                        recipient_company,
                        recipient_phone,
                        recipient_email,
                        address_line1,
                        address_line2,
                        city,
                        state,
                        zip_code,
                        country,
                        address_validated,
                        validated_at,
                        use_count,
                        last_used_at,
                        notes
                    FROM address_book
                    WHERE id = %s AND instance_id = %s AND is_active = TRUE
                """, (address_id, self.instance_id))
                
                row = cursor.fetchone()
                cursor.close()
                
                return dict(row) if row else None
                
        except Exception as e:
            logger.error(f"Get address by ID error: {str(e)}")
            return None
    
    def get_all(self, sort_by: str = 'name', limit: int = 100) -> List[Dict]:
        """
        Get all addresses in book
        
        Args:
            sort_by: Sort order ('name', 'usage', 'recent')
            limit: Maximum results
            
        Returns:
            List of addresses
        """
        sort_map = {
            'name': 'recipient_name ASC',
            'usage': 'use_count DESC',
            'recent': 'last_used_at DESC NULLS LAST'
        }
        
        order_by = sort_map.get(sort_by, 'recipient_name ASC')
        
        try:
            with get_db_connection("send") as conn:
                cursor = conn.cursor()
                
                sql = f"""
                    SELECT 
                        id,
                        recipient_name,
                        recipient_company,
                        recipient_phone,
                        address_line1,
                        address_line2,
                        city,
                        state,
                        zip_code,
                        country,
                        address_validated,
                        use_count,
                        last_used_at,
                        created_at
                    FROM address_book
                    WHERE instance_id = %s AND is_active = TRUE
                    ORDER BY {order_by}
                    LIMIT %s
                """
                
                cursor.execute(sql, (self.instance_id, limit))
                results = cursor.fetchall()
                cursor.close()
                
                return [dict(row) for row in results]
                
        except Exception as e:
            logger.error(f"Get all addresses error: {str(e)}")
            return []
    
    def add(self, address_data: Dict, created_by: int) -> Optional[int]:
        """
        Add new address to book
        
        Args:
            address_data: Address information
            created_by: User ID creating the entry
            
        Returns:
            New address ID or None if failed
        """
        try:
            with get_db_connection("send") as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO address_book (
                        instance_id,
                        recipient_name,
                        recipient_company,
                        recipient_phone,
                        recipient_email,
                        address_line1,
                        address_line2,
                        city,
                        state,
                        zip_code,
                        country,
                        address_validated,
                        validation_source,
                        notes,
                        created_by,
                        created_at,
                        updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (instance_id, recipient_name, address_line1, city, state, zip_code)
                    DO UPDATE SET
                        recipient_company = EXCLUDED.recipient_company,
                        recipient_phone = EXCLUDED.recipient_phone,
                        recipient_email = EXCLUDED.recipient_email,
                        address_line2 = EXCLUDED.address_line2,
                        updated_at = CURRENT_TIMESTAMP,
                        is_active = TRUE
                    RETURNING id
                """, (
                    self.instance_id,
                    address_data.get('recipient_name'),
                    address_data.get('recipient_company'),
                    address_data.get('recipient_phone'),
                    address_data.get('recipient_email'),
                    address_data.get('address_line1'),
                    address_data.get('address_line2'),
                    address_data.get('city'),
                    address_data.get('state'),
                    address_data.get('zip_code'),
                    address_data.get('country', 'USA'),
                    address_data.get('address_validated', False),
                    address_data.get('validation_source'),
                    address_data.get('notes'),
                    created_by,
                    datetime.now(),
                    datetime.now()
                ))
                
                row = cursor.fetchone()
                address_id = row['id'] if row else None
                
                conn.commit()
                cursor.close()
                
                logger.info(f"Added address to book: {address_id}")
                return address_id
                
        except Exception as e:
            logger.error(f"Add address error: {str(e)}")
            return None
    
    def update(self, address_id: int, address_data: Dict) -> bool:
        """
        Update existing address
        
        Args:
            address_id: Address ID to update
            address_data: Updated address information
            
        Returns:
            Success status
        """
        try:
            with get_db_connection("send") as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE address_book
                    SET
                        recipient_name = %s,
                        recipient_company = %s,
                        recipient_phone = %s,
                        recipient_email = %s,
                        address_line1 = %s,
                        address_line2 = %s,
                        city = %s,
                        state = %s,
                        zip_code = %s,
                        country = %s,
                        notes = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND instance_id = %s
                """, (
                    address_data.get('recipient_name'),
                    address_data.get('recipient_company'),
                    address_data.get('recipient_phone'),
                    address_data.get('recipient_email'),
                    address_data.get('address_line1'),
                    address_data.get('address_line2'),
                    address_data.get('city'),
                    address_data.get('state'),
                    address_data.get('zip_code'),
                    address_data.get('country', 'USA'),
                    address_data.get('notes'),
                    address_id,
                    self.instance_id
                ))
                
                conn.commit()
                cursor.close()
                
                logger.info(f"Updated address: {address_id}")
                return True
                
        except Exception as e:
            logger.error(f"Update address error: {str(e)}")
            return False
    
    def delete(self, address_id: int) -> bool:
        """
        Soft delete address (mark as inactive)
        
        Args:
            address_id: Address ID to delete
            
        Returns:
            Success status
        """
        try:
            with get_db_connection("send") as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE address_book
                    SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND instance_id = %s
                """, (address_id, self.instance_id))
                
                conn.commit()
                cursor.close()
                
                logger.info(f"Deleted address: {address_id}")
                return True
                
        except Exception as e:
            logger.error(f"Delete address error: {str(e)}")
            return False
    
    def find_or_create(self, recipient_data: Dict, created_by: int) -> Optional[int]:
        """
        Find existing address or create new one
        Used for auto-adding addresses from tracking data
        
        Args:
            recipient_data: Recipient information from form/tracking
            created_by: User ID creating the entry
            
        Returns:
            Address ID (existing or newly created)
        """
        try:
            # Extract key fields for matching
            recipient_name = recipient_data.get('recipient_name', '').strip()
            address_line1 = recipient_data.get('address_line1', '').strip()
            zip_code = recipient_data.get('zip_code', '').strip()
            
            if not recipient_name or not address_line1:
                logger.warning("Insufficient data to find/create address")
                return None
            
            with get_db_connection("send") as conn:
                cursor = conn.cursor()
                
                # Check if address already exists (match on name + address + zip)
                cursor.execute("""
                    SELECT id, use_count
                    FROM address_book
                    WHERE instance_id = %s
                    AND is_active = TRUE
                    AND recipient_name ILIKE %s
                    AND address_line1 ILIKE %s
                    AND zip_code = %s
                    LIMIT 1
                """, (self.instance_id, recipient_name, address_line1, zip_code))
                
                existing = cursor.fetchone()
                
                if existing:
                    # Address exists - increment usage and return ID
                    address_id = existing['id']
                    cursor.execute("""
                        UPDATE address_book
                        SET 
                            use_count = use_count + 1,
                            last_used_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (address_id,))
                    conn.commit()
                    cursor.close()
                    
                    logger.info(f"Found existing address: {address_id}, incremented usage")
                    return address_id
                
                else:
                    # Address doesn't exist - create new entry
                    cursor.execute("""
                        INSERT INTO address_book (
                            instance_id,
                            recipient_name,
                            recipient_company,
                            recipient_phone,
                            recipient_email,
                            address_line1,
                            address_line2,
                            city,
                            state,
                            zip_code,
                            country,
                            notes,
                            use_count,
                            last_used_at,
                            created_by,
                            created_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, CURRENT_TIMESTAMP, %s, CURRENT_TIMESTAMP
                        ) RETURNING id
                    """, (
                        self.instance_id,
                        recipient_data.get('recipient_name'),
                        recipient_data.get('recipient_company'),
                        recipient_data.get('recipient_phone'),
                        recipient_data.get('recipient_email'),
                        recipient_data.get('address_line1'),
                        recipient_data.get('address_line2'),
                        recipient_data.get('city'),
                        recipient_data.get('state'),
                        recipient_data.get('zip_code'),
                        recipient_data.get('country', 'USA'),
                        'Auto-added from package checkin',
                        created_by
                    ))
                    
                    new_id = cursor.fetchone()['id']
                    conn.commit()
                    cursor.close()
                    
                    logger.info(f"Created new address book entry: {new_id}")
                    return new_id
                    
        except Exception as e:
            logger.error(f"Find or create address error: {str(e)}")
            return None

    def increment_usage(self, address_id: int):
        """
        Increment usage counter when address is used
        
        Args:
            address_id: Address ID
        """
        try:
            with get_db_connection("send") as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE address_book
                    SET 
                        use_count = use_count + 1,
                        last_used_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND instance_id = %s
                """, (address_id, self.instance_id))
                
                conn.commit()
                cursor.close()
                
        except Exception as e:
            logger.error(f"Increment usage error: {str(e)}")
    
    def get_frequent(self, limit: int = 10) -> List[Dict]:
        """
        Get most frequently used addresses
        
        Args:
            limit: Number of results
            
        Returns:
            List of addresses sorted by usage
        """
        return self.get_all(sort_by='usage', limit=limit)