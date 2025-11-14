"""
Verify Send database schema matches check-in form
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.app import create_app
from app.core.database import get_db_connection

def verify_schema():
    """Check package_manifest table structure"""
    
    print("=" * 60)
    print("Verifying Send Database Schema")
    print("=" * 60)
    
    app = create_app()
    
    with app.app_context():
        try:
            with get_db_connection("send") as conn:
                cursor = conn.cursor()
                
                # Get column information
                cursor.execute("""
                    SELECT column_name, data_type, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_name = 'package_manifest'
                    ORDER BY ordinal_position;
                """)
                
                columns = cursor.fetchall()
                cursor.close()
                
                if not columns:
                    print("❌ Table 'package_manifest' not found!")
                    return False
                
                print("\n✅ Table 'package_manifest' exists")
                print("\nColumns in database:\n")
                print(f"{'Column Name':<30} {'Type':<20} {'Nullable':<10}")
                print("-" * 60)
                
                column_names = []
                for col in columns:
                    column_names.append(col['column_name'])
                    nullable = "YES" if col['is_nullable'] == 'YES' else "NO"
                    print(f"{col['column_name']:<30} {col['data_type']:<20} {nullable:<10}")
                
                # Check required columns for check-in form
                print("\n" + "=" * 60)
                print("Checking Required Columns for Check-In Form")
                print("=" * 60)
                
                required_columns = [
                    'checkin_id',
                    'package_id',
                    'tracking_number',
                    'carrier',
                    'package_type',
                    'recipient_name',
                    'recipient_company',
                    'recipient_address',  # Combined address field
                    'weight_oz',
                    'tracking_status',
                    'status_description',
                    'estimated_delivery_date',
                    'current_location',
                    'location',
                    'submitter_name',
                    'notes',
                    'auto_populated',
                    'checkin_date',
                    'created_at',
                    'ts_utc',
                    'last_tracked_at'
                ]
                
                print("\nChecking each required column:\n")
                
                all_good = True
                for col in required_columns:
                    if col in column_names:
                        print(f"  ✅ {col}")
                    else:
                        print(f"  ❌ {col} - MISSING!")
                        all_good = False
                
                # Check for unexpected separate address columns
                print("\nChecking for conflicting address columns:\n")
                
                address_columns = [
                    'address_line1',
                    'address_line2', 
                    'city',
                    'state',
                    'postal_code',
                    'country'
                ]
                
                conflicts = False
                for col in address_columns:
                    if col in column_names:
                        print(f"  ⚠️ {col} - Exists (may conflict with recipient_address)")
                        conflicts = True
                
                if not conflicts:
                    print("  ✅ No conflicting address columns")
                
                print("\n" + "=" * 60)
                
                if all_good and not conflicts:
                    print("✅ SCHEMA VERIFICATION PASSED")
                    print("   Check-in form matches database schema perfectly!")
                elif all_good and conflicts:
                    print("⚠️ SCHEMA HAS EXTRA COLUMNS")
                    print("   Form will work, but separate address columns are unused")
                else:
                    print("❌ SCHEMA VERIFICATION FAILED")
                    print("   Missing required columns - check-in will fail!")
                
                print("=" * 60)
                
                return all_good
                
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == "__main__":
    verify_schema()