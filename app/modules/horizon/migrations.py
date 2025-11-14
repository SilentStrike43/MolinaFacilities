"""
Data Migration Processor
Handles bulk CSV imports for users, addresses, inventory, and packages
"""

import logging
import hashlib
from datetime import datetime
from typing import List, Dict, Any

from app.core.database import get_db_connection
from app.services.address.validator import AddressValidator
from flask import current_app

logger = logging.getLogger(__name__)


class MigrationProcessor:
    """Process and validate bulk data imports."""
    
    def __init__(self, instance_id: int, current_user: dict):
        self.instance_id = instance_id
        self.current_user = current_user
        
    def validate_import(self, migration_type: str, rows: List[Dict]) -> Dict[str, Any]:
        """Validate imported data based on type."""
        
        validators = {
            'users': self._validate_users,
            'addresses': self._validate_addresses,
            'inventory': self._validate_inventory,
            'packages': self._validate_packages
        }
        
        validator = validators.get(migration_type)
        if not validator:
            raise ValueError(f"Unknown migration type: {migration_type}")
        
        return validator(rows)
    
    def _validate_users(self, rows: List[Dict]) -> Dict[str, Any]:
        """
        Validate user import data.
        Required: username, password, email
        Optional: first_name, last_name, phone, department, position
        Default permission: M3A (Fulfillment Customer)
        """
        valid = []
        invalid = []
        warnings = []
        errors = []
        
        # Check for existing usernames
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT username FROM users WHERE deleted_at IS NULL")
            existing_usernames = {row['username'] for row in cursor.fetchall()}
            cursor.close()
        
        for idx, row in enumerate(rows):
            row_num = idx + 2  # +2 for header row and 0-index
            row_errors = []
            row_warnings = []
            
            # Required fields
            username = row.get('username', '').strip().lower()
            password = row.get('password', '').strip()
            email = row.get('email', '').strip()
            
            if not username:
                row_errors.append("Missing username")
            elif username in existing_usernames:
                row_errors.append(f"Username '{username}' already exists")
            elif len(username) < 3:
                row_errors.append("Username must be at least 3 characters")
            
            if not password:
                row_errors.append("Missing password")
            elif len(password) < 8:
                row_warnings.append("Password less than 8 characters (weak)")
            
            if not email:
                row_warnings.append("Missing email (optional but recommended)")
            elif '@' not in email:
                row_errors.append("Invalid email format")
            
            # Optional fields
            first_name = row.get('first_name', '').strip()
            last_name = row.get('last_name', '').strip()
            phone = row.get('phone', '').strip()
            department = row.get('department', '').strip()
            position = row.get('position', '').strip()
            address = row.get('address', '').strip()
            
            if row_errors:
                invalid.append({
                    'row': row_num,
                    'data': row,
                    'errors': row_errors,
                    'warnings': row_warnings
                })
                errors.extend([f"Row {row_num}: {err}" for err in row_errors])
            else:
                valid.append({
                    'username': username,
                    'password': password,
                    'email': email,
                    'first_name': first_name,
                    'last_name': last_name,
                    'phone': phone,
                    'department': department,
                    'position': position,
                    'address': address,
                    'permission_level': '',  # Module user
                    'module_permissions': ['M3A'],  # Default Fulfillment Customer
                    'warnings': row_warnings
                })
                if row_warnings:
                    warnings.extend([f"Row {row_num}: {warn}" for warn in row_warnings])
        
        return {
            'valid_count': len(valid),
            'invalid_count': len(invalid),
            'warnings': warnings,
            'errors': errors,
            'preview': valid + invalid,
            'validated_data': valid
        }
    
    def _validate_addresses(self, rows: List[Dict]) -> Dict[str, Any]:
        """
        Validate address book import data.
        Required: recipient_name, address_line1, city, state, zip_code
        Optional: recipient_company, phone, email, address_line2
        Uses FedEx API for validation if available
        """
        valid = []
        invalid = []
        warnings = []
        errors = []
        
        # Initialize address validator
        try:
            validator = AddressValidator(current_app.config)
            has_validator = True
        except:
            has_validator = False
            logger.warning("Address validator not available - skipping API validation")
        
        for idx, row in enumerate(rows):
            row_num = idx + 2
            row_errors = []
            row_warnings = []
            
            # Required fields
            recipient_name = row.get('recipient_name', '').strip()
            address_line1 = row.get('address_line1', '').strip()
            city = row.get('city', '').strip()
            state = row.get('state', '').strip()
            zip_code = row.get('zip_code', '').strip()
            
            if not recipient_name:
                row_errors.append("Missing recipient name")
            if not address_line1:
                row_errors.append("Missing address line 1")
            if not city:
                row_errors.append("Missing city")
            if not state:
                row_errors.append("Missing state")
            elif len(state) != 2:
                row_errors.append("State must be 2-letter code (e.g., NY)")
            if not zip_code:
                row_errors.append("Missing ZIP code")
            elif len(zip_code) not in [5, 10]:  # 12345 or 12345-6789
                row_warnings.append("ZIP code format unusual (expected 5 or 10 digits)")
            
            # Optional fields
            recipient_company = row.get('recipient_company', '').strip()
            phone = row.get('phone', '').strip()
            email = row.get('email', '').strip()
            address_line2 = row.get('address_line2', '').strip()
            notes = row.get('notes', '').strip()
            
            # Validate with FedEx API if available
            api_validated = False
            if has_validator and not row_errors:
                try:
                    validation_result = validator.validate(
                        address_line1, city, state, zip_code, address_line2
                    )
                    if validation_result and validation_result.get('valid'):
                        api_validated = True
                        row_warnings.append("✓ Verified by FedEx API")
                    else:
                        row_warnings.append("⚠ Could not verify address with FedEx")
                except Exception as e:
                    row_warnings.append(f"Address validation failed: {str(e)}")
            
            if row_errors:
                invalid.append({
                    'row': row_num,
                    'data': row,
                    'errors': row_errors,
                    'warnings': row_warnings
                })
                errors.extend([f"Row {row_num}: {err}" for err in row_errors])
            else:
                valid.append({
                    'recipient_name': recipient_name,
                    'recipient_company': recipient_company,
                    'recipient_phone': phone,
                    'recipient_email': email,
                    'address_line1': address_line1,
                    'address_line2': address_line2,
                    'city': city,
                    'state': state,
                    'zip_code': zip_code,
                    'notes': notes,
                    'api_validated': api_validated,
                    'warnings': row_warnings
                })
                if row_warnings:
                    warnings.extend([f"Row {row_num}: {warn}" for warn in row_warnings])
        
        return {
            'valid_count': len(valid),
            'invalid_count': len(invalid),
            'warnings': warnings,
            'errors': errors,
            'preview': valid + invalid,
            'validated_data': valid
        }
    
    def _validate_inventory(self, rows: List[Dict]) -> Dict[str, Any]:
        """
        Validate inventory asset import data.
        Required: sku, asset_name, category
        Optional: manufacturer, model, serial_number, location, status, etc.
        """
        valid = []
        invalid = []
        warnings = []
        errors = []
        
        # Check for existing SKUs
        with get_db_connection("inventory") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT sku FROM assets 
                WHERE instance_id = %s AND deleted_at IS NULL
            """, (self.instance_id,))
            existing_skus = {row['sku'] for row in cursor.fetchall()}
            cursor.close()
        
        for idx, row in enumerate(rows):
            row_num = idx + 2
            row_errors = []
            row_warnings = []
            
            # Required fields
            sku = row.get('sku', '').strip().upper()
            asset_name = row.get('asset_name', '').strip()
            category = row.get('category', '').strip()
            
            if not sku:
                row_errors.append("Missing SKU")
            elif sku in existing_skus:
                row_errors.append(f"SKU '{sku}' already exists")
            
            if not asset_name:
                row_errors.append("Missing asset name")
            
            if not category:
                row_errors.append("Missing category")
            
            # Optional fields
            manufacturer = row.get('manufacturer', '').strip()
            model = row.get('model', '').strip()
            serial_number = row.get('serial_number', '').strip()
            location = row.get('location', '').strip()
            status = row.get('status', 'available').strip().lower()
            purchase_date = row.get('purchase_date', '').strip()
            purchase_price = row.get('purchase_price', '').strip()
            notes = row.get('notes', '').strip()
            
            # Validate status
            valid_statuses = ['available', 'in_use', 'maintenance', 'retired']
            if status and status not in valid_statuses:
                row_warnings.append(f"Invalid status '{status}', defaulting to 'available'")
                status = 'available'
            
            # Validate price
            price_value = None
            if purchase_price:
                try:
                    price_value = float(purchase_price.replace('$', '').replace(',', ''))
                except:
                    row_warnings.append(f"Invalid price format '{purchase_price}'")
            
            if row_errors:
                invalid.append({
                    'row': row_num,
                    'data': row,
                    'errors': row_errors,
                    'warnings': row_warnings
                })
                errors.extend([f"Row {row_num}: {err}" for err in row_errors])
            else:
                valid.append({
                    'sku': sku,
                    'asset_name': asset_name,
                    'category': category,
                    'manufacturer': manufacturer,
                    'model': model,
                    'serial_number': serial_number,
                    'location': location,
                    'status': status,
                    'purchase_date': purchase_date or None,
                    'purchase_price': price_value,
                    'notes': notes,
                    'warnings': row_warnings
                })
                if row_warnings:
                    warnings.extend([f"Row {row_num}: {warn}" for warn in row_warnings])
        
        return {
            'valid_count': len(valid),
            'invalid_count': len(invalid),
            'warnings': warnings,
            'errors': errors,
            'preview': valid + invalid,
            'validated_data': valid
        }
    
    def _validate_packages(self, rows: List[Dict]) -> Dict[str, Any]:
        """
        Validate package/mail data import.
        Required: tracking_number, carrier, recipient_name, recipient_address
        Optional: package_type, weight, notes
        Can use FedEx API for validation
        """
        valid = []
        invalid = []
        warnings = []
        errors = []
        
        valid_carriers = ['FEDEX', 'UPS', 'USPS', 'DHL', 'OTHER']
        
        for idx, row in enumerate(rows):
            row_num = idx + 2
            row_errors = []
            row_warnings = []
            
            # Required fields
            tracking_number = row.get('tracking_number', '').strip()
            carrier = row.get('carrier', '').strip().upper()
            recipient_name = row.get('recipient_name', '').strip()
            recipient_address = row.get('recipient_address', '').strip()
            
            if not tracking_number:
                row_errors.append("Missing tracking number")
            
            if not carrier:
                row_errors.append("Missing carrier")
            elif carrier not in valid_carriers:
                row_warnings.append(f"Unknown carrier '{carrier}', will use as-is")
            
            if not recipient_name:
                row_errors.append("Missing recipient name")
            
            if not recipient_address:
                row_errors.append("Missing recipient address")
            
            # Optional fields
            package_type = row.get('package_type', 'Box').strip()
            weight = row.get('weight', '').strip()
            notes = row.get('notes', '').strip()
            recipient_company = row.get('recipient_company', '').strip()
            
            # Validate weight
            weight_value = None
            if weight:
                try:
                    weight_value = float(weight)
                except:
                    row_warnings.append(f"Invalid weight format '{weight}'")
            
            if row_errors:
                invalid.append({
                    'row': row_num,
                    'data': row,
                    'errors': row_errors,
                    'warnings': row_warnings
                })
                errors.extend([f"Row {row_num}: {err}" for err in row_errors])
            else:
                valid.append({
                    'tracking_number': tracking_number,
                    'carrier': carrier,
                    'recipient_name': recipient_name,
                    'recipient_company': recipient_company,
                    'recipient_address': recipient_address,
                    'package_type': package_type,
                    'weight': weight_value,
                    'notes': notes,
                    'warnings': row_warnings
                })
                if row_warnings:
                    warnings.extend([f"Row {row_num}: {warn}" for warn in row_warnings])
        
        return {
            'valid_count': len(valid),
            'invalid_count': len(invalid),
            'warnings': warnings,
            'errors': errors,
            'preview': valid + invalid,
            'validated_data': valid
        }
    
    def execute_import(self, migration_type: str, validated_data: List[Dict]) -> Dict[str, Any]:
        """Execute the actual import after validation."""
        
        importers = {
            'users': self._import_users,
            'addresses': self._import_addresses,
            'inventory': self._import_inventory,
            'packages': self._import_packages
        }
        
        importer = importers.get(migration_type)
        if not importer:
            raise ValueError(f"Unknown migration type: {migration_type}")
        
        return importer(validated_data)
    
    def _import_users(self, users: List[Dict]) -> Dict[str, Any]:
        """Import validated user data."""
        success_count = 0
        failed_count = 0
        details = []
        
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            
            for user in users:
                try:
                    # Hash password
                    password_hash = hashlib.sha256(user['password'].encode()).hexdigest()
                    
                    cursor.execute("""
                        INSERT INTO users (
                            username, password_hash, first_name, last_name,
                            email, phone, instance_id, permission_level,
                            module_permissions, is_active, force_password_reset,
                            created_by, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, TRUE, %s, CURRENT_TIMESTAMP)
                    """, (
                        user['username'], password_hash, user['first_name'],
                        user['last_name'], user['email'], user['phone'],
                        self.instance_id, user['permission_level'],
                        user['module_permissions'], self.current_user['id']
                    ))
                    
                    success_count += 1
                    details.append(f"✓ Created user: {user['username']}")
                    
                except Exception as e:
                    failed_count += 1
                    details.append(f"✗ Failed {user['username']}: {str(e)}")
                    logger.error(f"User import error: {e}")
            
            conn.commit()
            cursor.close()
        
        return {
            'success_count': success_count,
            'failed_count': failed_count,
            'details': details
        }
    
    def _import_addresses(self, addresses: List[Dict]) -> Dict[str, Any]:
        """Import validated address data."""
        success_count = 0
        failed_count = 0
        details = []
        
        with get_db_connection("send") as conn:
            cursor = conn.cursor()
            
            for addr in addresses:
                try:
                    cursor.execute("""
                        INSERT INTO address_book (
                            instance_id, recipient_name, recipient_company,
                            recipient_phone, recipient_email,
                            address_line1, address_line2, city, state, zip_code,
                            notes, created_by, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    """, (
                        self.instance_id, addr['recipient_name'],
                        addr['recipient_company'], addr['recipient_phone'],
                        addr['recipient_email'], addr['address_line1'],
                        addr['address_line2'], addr['city'], addr['state'],
                        addr['zip_code'], addr['notes'], self.current_user['id']
                    ))
                    
                    success_count += 1
                    details.append(f"✓ Added address: {addr['recipient_name']}")
                    
                except Exception as e:
                    failed_count += 1
                    details.append(f"✗ Failed {addr['recipient_name']}: {str(e)}")
                    logger.error(f"Address import error: {e}")
            
            conn.commit()
            cursor.close()
        
        return {
            'success_count': success_count,
            'failed_count': failed_count,
            'details': details
        }
    
    def _import_inventory(self, assets: List[Dict]) -> Dict[str, Any]:
        """Import validated inventory data."""
        success_count = 0
        failed_count = 0
        details = []
        
        with get_db_connection("inventory") as conn:
            cursor = conn.cursor()
            
            for asset in assets:
                try:
                    cursor.execute("""
                        INSERT INTO assets (
                            instance_id, sku, asset_name, category,
                            manufacturer, model, serial_number, location,
                            status, purchase_date, purchase_price, notes,
                            created_by, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    """, (
                        self.instance_id, asset['sku'], asset['asset_name'],
                        asset['category'], asset['manufacturer'], asset['model'],
                        asset['serial_number'], asset['location'], asset['status'],
                        asset['purchase_date'], asset['purchase_price'],
                        asset['notes'], self.current_user['id']
                    ))
                    
                    success_count += 1
                    details.append(f"✓ Added asset: {asset['sku']} - {asset['asset_name']}")
                    
                except Exception as e:
                    failed_count += 1
                    details.append(f"✗ Failed {asset['sku']}: {str(e)}")
                    logger.error(f"Inventory import error: {e}")
            
            conn.commit()
            cursor.close()
        
        return {
            'success_count': success_count,
            'failed_count': failed_count,
            'details': details
        }
    
    def _import_packages(self, packages: List[Dict]) -> Dict[str, Any]:
        """Import validated package data."""
        success_count = 0
        failed_count = 0
        details = []
        
        with get_db_connection("send") as conn:
            cursor = conn.cursor()
            
            for pkg in packages:
                try:
                    import time
                    checkin_id = f"CHK{int(time.time())}{success_count}"
                    package_id = f"PKG{int(time.time())}{success_count}"
                    
                    cursor.execute("""
                        INSERT INTO package_manifest (
                            instance_id, checkin_id, package_id, tracking_number,
                            carrier, package_type, recipient_name, recipient_company,
                            recipient_address, package_weight_lbs, notes,
                            submitter_name, checkin_date, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_DATE, CURRENT_TIMESTAMP)
                    """, (
                        self.instance_id, checkin_id, package_id,
                        pkg['tracking_number'], pkg['carrier'], pkg['package_type'],
                        pkg['recipient_name'], pkg['recipient_company'],
                        pkg['recipient_address'], pkg['weight'], pkg['notes'],
                        self.current_user['username']
                    ))
                    
                    success_count += 1
                    details.append(f"✓ Added package: {pkg['tracking_number']}")
                    
                except Exception as e:
                    failed_count += 1
                    details.append(f"✗ Failed {pkg['tracking_number']}: {str(e)}")
                    logger.error(f"Package import error: {e}")
            
            conn.commit()
            cursor.close()
        
        return {
            'success_count': success_count,
            'failed_count': failed_count,
            'details': details
        }