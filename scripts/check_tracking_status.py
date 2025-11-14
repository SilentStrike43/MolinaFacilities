"""
Check what's actually in the database for tracking status
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.app import create_app
from app.core.database import get_db_connection

def check_status():
    print("=" * 60)
    print("Checking Package Tracking Status in Database")
    print("=" * 60)
    
    app = create_app()
    
    with app.app_context():
        with get_db_connection("send") as conn:
            cursor = conn.cursor()
            
            # Get recent packages
            cursor.execute("""
                SELECT 
                    package_id,
                    tracking_number,
                    carrier,
                    tracking_status,
                    tracking_status_description,
                    last_tracked_at,
                    created_at
                FROM package_manifest
                ORDER BY created_at DESC
                LIMIT 10
            """)
            
            packages = cursor.fetchall()
            
            print(f"\nFound {len(packages)} recent packages:\n")
            
            for pkg in packages:
                print(f"Package: {pkg['package_id']}")
                print(f"  Tracking: {pkg['tracking_number']}")
                print(f"  Carrier: {pkg['carrier']}")
                print(f"  Status: {pkg['tracking_status'] or 'NULL'}")
                print(f"  Description: {pkg['tracking_status_description'] or 'NULL'}")
                print(f"  Last Tracked: {pkg['last_tracked_at'] or 'Never'}")
                print(f"  Created: {pkg['created_at']}")
                print()
            
            cursor.close()
    
    print("=" * 60)

if __name__ == "__main__":
    check_status()