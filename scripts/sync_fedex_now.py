"""
Quick FedEx Sync Script
Run this to immediately sync FedEx shipments
"""

import os
import sys
from datetime import datetime

# Add app to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.app import create_app
from app.services.fedex.sync import FedExShipmentSync

def main():
    """Run FedEx sync immediately"""
    print("=" * 60)
    print("FedEx Shipment Auto-Sync")
    print("=" * 60)
    print(f"Started: {datetime.now()}\n")
    
    # Create app context
    app = create_app()
    
    with app.app_context():
        # Initialize sync service
        sync_service = FedExShipmentSync(app.config)
        
        # Ask for hours back
        try:
            hours = int(input("How many hours back to sync? (default: 24): ") or "24")
        except ValueError:
            hours = 24
        
        print(f"\n🔍 Syncing FedEx shipments from last {hours} hours...")
        print("-" * 60)
        
        # Run sync
        result = sync_service.sync_recent_shipments(
            hours=hours,
            instance_id=None  # Will use default
        )
        
        # Display results
        print("\n" + "=" * 60)
        print("SYNC RESULTS")
        print("=" * 60)
        
        if result['success']:
            print(f"✅ SUCCESS")
            print(f"   Imported: {result['imported']} new packages")
            print(f"   Skipped:  {result['skipped']} duplicates")
        else:
            print(f"❌ FAILED")
            print(f"   Error: {result.get('error', 'Unknown error')}")
        
        print("\n" + "=" * 60)
        print(f"Completed: {datetime.now()}")
        print("=" * 60)

if __name__ == "__main__":
    main()