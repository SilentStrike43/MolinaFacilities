"""
Intelligent Column Mapper
Maps CSV columns from various sources to app-expected fields
"""

import logging
from typing import Dict, List, Tuple
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class ColumnMapper:
    """Intelligent column mapping for CSV imports."""
    
    # Define expected fields for each migration type
    FIELD_SCHEMAS = {
        'users': {
            'required': {
                'username': ['username', 'user', 'login', 'userid', 'user_id', 'email'],
                'email': ['email', 'e-mail', 'email_address', 'mail'],
            },
            'optional': {
                'password': ['password', 'pass', 'pwd', 'user_password'],
                'first_name': ['first_name', 'firstname', 'fname', 'given_name', 'first'],
                'last_name': ['last_name', 'lastname', 'lname', 'surname', 'family_name', 'last'],
                'phone': ['phone', 'phone_number', 'telephone', 'mobile', 'cell'],
                'department': ['department', 'dept', 'division', 'team'],
                'position': ['position', 'title', 'job_title', 'role'],
            }
        },
        'addresses': {
            'required': {
                'recipient_name': ['recipient_name', 'name', 'recipient', 'customer_name', 'to_name'],
                'address_line1': ['address_line1', 'address1', 'street', 'address', 'street_address', 'line1'],
                'city': ['city', 'town', 'locality'],
                'state': ['state', 'province', 'region', 'st'],
                'zip_code': ['zip_code', 'zip', 'postal_code', 'postcode', 'zipcode'],
            },
            'optional': {
                'address_line2': ['address_line2', 'address2', 'apt', 'suite', 'unit', 'line2'],
                'recipient_company': ['recipient_company', 'company', 'organization', 'business'],
                'recipient_phone': ['recipient_phone', 'phone', 'telephone', 'contact_number'],
                'notes': ['notes', 'note', 'comments', 'memo', 'remarks'],
            }
        },
        'inventory': {
            'required': {
                'sku': ['sku', 'item_number', 'product_code', 'item_id', 'part_number'],
                'asset_name': ['asset_name', 'name', 'item_name', 'product_name', 'description'],
                'category': ['category', 'type', 'class', 'group'],
            },
            'optional': {
                'quantity': ['quantity', 'qty', 'count', 'amount', 'stock'],
                'location': ['location', 'warehouse', 'storage', 'shelf'],
                'purchase_id': ['purchase_id', 'po_number', 'order_id', 'invoice'],
                'cost': ['cost', 'price', 'unit_cost', 'value'],
                'notes': ['notes', 'note', 'comments', 'description'],
            }
        },
        'packages': {
            'required': {
                'tracking_number': ['tracking_number', 'tracking', 'track_number', 'tracking_id'],
                'carrier': ['carrier', 'shipper', 'shipping_company', 'courier'],
                'recipient_name': ['recipient_name', 'recipient', 'to_name', 'name'],
            },
            'optional': {
                'recipient_address': ['recipient_address', 'address', 'destination'],
                'recipient_company': ['recipient_company', 'company', 'organization'],
                'sender_name': ['sender_name', 'sender', 'from_name', 'ship_from'],
                'service_type': ['service_type', 'service', 'shipping_method', 'delivery_type'],
                'notes': ['notes', 'note', 'comments', 'memo'],
            }
        }
    }
    
    @classmethod
    def detect_columns(cls, csv_headers: List[str], migration_type: str) -> Dict[str, any]:
        """
        Automatically detect and suggest column mappings.
        
        Returns:
            {
                'detected_mappings': {app_field: csv_column},
                'unmapped_required': [list of required fields not found],
                'unmapped_csv_columns': [list of CSV columns not mapped],
                'confidence_scores': {app_field: confidence_score}
            }
        """
        if migration_type not in cls.FIELD_SCHEMAS:
            raise ValueError(f"Unknown migration type: {migration_type}")
        
        schema = cls.FIELD_SCHEMAS[migration_type]
        all_fields = {**schema['required'], **schema['optional']}
        
        detected_mappings = {}
        confidence_scores = {}
        unmapped_csv = set(csv_headers)
        
        # Normalize CSV headers
        normalized_headers = {h: h.lower().strip().replace(' ', '_').replace('-', '_') 
                             for h in csv_headers}
        
        # Try to map each app field
        for app_field, possible_names in all_fields.items():
            best_match = None
            best_score = 0
            
            for csv_col, normalized in normalized_headers.items():
                # Exact match check
                if normalized in [p.lower() for p in possible_names]:
                    best_match = csv_col
                    best_score = 1.0
                    break
                
                # Fuzzy match check (using sequence matching)
                for possible_name in possible_names:
                    score = SequenceMatcher(None, normalized, possible_name.lower()).ratio()
                    if score > best_score and score > 0.6:  # 60% similarity threshold
                        best_match = csv_col
                        best_score = score
            
            if best_match:
                detected_mappings[app_field] = best_match
                confidence_scores[app_field] = best_score
                unmapped_csv.discard(best_match)
        
        # Find unmapped required fields
        unmapped_required = [
            field for field in schema['required'].keys()
            if field not in detected_mappings
        ]
        
        return {
            'detected_mappings': detected_mappings,
            'unmapped_required': unmapped_required,
            'unmapped_csv_columns': list(unmapped_csv),
            'confidence_scores': confidence_scores,
            'schema': schema
        }
    
    @classmethod
    def apply_mapping(cls, row: Dict, mapping: Dict[str, str]) -> Dict:
        """
        Apply column mapping to a CSV row.
        
        Args:
            row: Original CSV row with original column names
            mapping: {app_field: csv_column} mapping
        
        Returns:
            Mapped row with app field names
        """
        mapped_row = {}
        for app_field, csv_column in mapping.items():
            mapped_row[app_field] = row.get(csv_column, '')
        
        return mapped_row
    
    @classmethod
    def get_field_description(cls, migration_type: str, field_name: str) -> str:
        """Get human-readable description of a field."""
        descriptions = {
            'users': {
                'username': 'Unique username for login',
                'email': 'Email address',
                'password': 'User password (will be hashed)',
                'first_name': 'User\'s first name',
                'last_name': 'User\'s last name',
                'phone': 'Phone number',
                'department': 'Department or team',
                'position': 'Job title or position',
            },
            'addresses': {
                'recipient_name': 'Full name of recipient',
                'address_line1': 'Street address',
                'address_line2': 'Apartment, suite, etc.',
                'city': 'City name',
                'state': 'State/Province (2-letter code)',
                'zip_code': 'ZIP or postal code',
                'recipient_company': 'Company name',
                'recipient_phone': 'Phone number',
                'notes': 'Additional notes',
            },
            'inventory': {
                'sku': 'Unique product/asset identifier',
                'asset_name': 'Name or description',
                'category': 'Asset category or type',
                'quantity': 'Current quantity in stock',
                'location': 'Storage location',
                'purchase_id': 'Purchase order or invoice number',
                'cost': 'Unit cost or price',
                'notes': 'Additional notes',
            },
            'packages': {
                'tracking_number': 'Package tracking number',
                'carrier': 'Shipping carrier (USPS, FedEx, UPS)',
                'recipient_name': 'Recipient name',
                'recipient_address': 'Delivery address',
                'recipient_company': 'Company name',
                'sender_name': 'Sender name',
                'service_type': 'Shipping service type',
                'notes': 'Additional notes',
            }
        }
        
        return descriptions.get(migration_type, {}).get(field_name, field_name)