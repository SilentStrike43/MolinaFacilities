#!/usr/bin/env python3
"""
Test USPS API Authentication (OAuth 2.0)
"""

import os
import sys
import requests
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

def test_usps_auth_with_scope(consumer_key, consumer_secret, api_url):
    """OAuth with tracking scope"""
    print("\n🔐 OAuth 2.0 with tracking scope")
    
    try:
        response = requests.post(
            f"{api_url}/oauth2/v3/token",
            data={
                'grant_type': 'client_credentials',
                'client_id': consumer_key,
                'client_secret': consumer_secret,
                'scope': 'tracking'  # Required for tracking API
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=10
        )
        
        print(f"   Status: {response.status_code}")
        
        if response.status_code == 200:
            token_data = response.json()
            print(f"   ✅ Token obtained")
            print(f"   Token Type: {token_data.get('token_type')}")
            print(f"   Expires In: {token_data.get('expires_in')} seconds")
            print(f"   Scope: {token_data.get('scope', 'N/A')}")
            print(f"   Access Token: {token_data.get('access_token')[:30]}...")
            return token_data
        else:
            print(f"   ❌ Failed: {response.text}")
            return None
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return None


def test_usps_auth():
    """Test USPS OAuth 2.0 credentials"""
    
    consumer_key = os.getenv('USPS_CONSUMER_KEY')
    consumer_secret = os.getenv('USPS_CONSUMER_SECRET')
    api_url = os.getenv('USPS_API_URL', 'https://apis.usps.com')
    
    print("=" * 70)
    print("  USPS API Authentication Test")
    print("=" * 70)
    
    # Check credentials
    print(f"\n📋 Configuration:")
    print(f"   Consumer Key: {consumer_key[:20]}..." if consumer_key else "   Consumer Key: ❌ Missing")
    print(f"   Consumer Secret: {consumer_secret[:20]}..." if consumer_secret else "   Consumer Secret: ❌ Missing")
    print(f"   API URL: {api_url}")
    
    if not consumer_key or not consumer_secret:
        print("\n❌ Missing USPS credentials in .env!")
        return False
    
    # Get OAuth token with tracking scope
    print(f"\n🔍 Requesting OAuth token with tracking scope...")
    print(f"   Endpoint: {api_url}/oauth2/v3/token")
    
    token_data = test_usps_auth_with_scope(consumer_key, consumer_secret, api_url)
    
    if token_data:
        # Test tracking
        test_tracking(api_url, token_data['access_token'])
        return True
    else:
        print(f"\n❌ Authentication failed")
        return False


def test_tracking(api_url, access_token):
    """Test USPS tracking with sample number"""
    
    print("\n" + "=" * 70)
    print("  Testing USPS Tracking API")
    print("=" * 70)
    
    # Common USPS tracking number formats
    print("\n📝 USPS Tracking Number Formats:")
    print("   • 20-digit: 9400 1000 0000 0000 0000 00 (Priority/Express)")
    print("   • 22-digit: 9205 5000 0000 0000 0000 00 (Certified)")
    print("   • 26-digit: 420 xxxxx 9xxx xxxx xxxx xxxx xx (Priority)")
    
    test_tracking_number = input("\n🔍 Enter a USPS tracking number to test (or press Enter to skip): ").strip()
    
    if not test_tracking_number:
        print("   ⏭️  Skipping tracking test")
        return
    
    # Clean tracking number
    test_tracking_number = test_tracking_number.replace(' ', '').replace('-', '')
    
    print(f"\n🔍 Testing Tracking API...")
    print(f"   Tracking Number: {test_tracking_number}")
    
    try:
        tracking_url = f"{api_url}/tracking/v3/tracking/{test_tracking_number}"
        
        response = requests.get(
            tracking_url,
            headers={
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json'
            },
            timeout=15
        )
        
        print(f"   Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"\n✅ TRACKING SUCCESS!")
            
            if 'trackResults' in data and len(data['trackResults']) > 0:
                track_info = data['trackResults'][0]
                print(f"\n📦 Package Information:")
                print(f"   Tracking Number: {track_info.get('trackingNumber', 'N/A')}")
                print(f"   Status: {track_info.get('status', 'N/A')}")
                print(f"   Status Summary: {track_info.get('statusSummary', 'N/A')}")
                print(f"   Mail Class: {track_info.get('mailClass', 'N/A')}")
                print(f"   Service Type: {track_info.get('serviceType', 'N/A')}")
                
                # Destination
                if track_info.get('destinationCity'):
                    print(f"   Destination: {track_info.get('destinationCity', '')}, {track_info.get('destinationState', '')} {track_info.get('destinationZIP', '')}")
                
                # Latest event
                if 'events' in track_info and track_info['events']:
                    latest = track_info['events'][0]
                    print(f"\n📍 Latest Event:")
                    print(f"   Event: {latest.get('eventType', 'N/A')}")
                    print(f"   Time: {latest.get('eventTimestamp', 'N/A')}")
                    print(f"   Location: {latest.get('eventCity', 'N/A')}, {latest.get('eventState', 'N/A')}")
                
                print(f"\n✅ Tracking API is working correctly!")
                    
        elif response.status_code == 404:
            print(f"\n⚠️  Package not found")
            print(f"   • Tracking number doesn't exist")
            print(f"   • Package hasn't been scanned yet")
            print(f"   • Wrong tracking number format")
            
        elif response.status_code == 401:
            print(f"\n❌ Authentication error: {response.status_code}")
            print(f"   Response: {response.text[:500]}")
            print(f"\n💡 This might mean:")
            print(f"   • Token expired")
            print(f"   • Insufficient scope for tracking")
            
        else:
            print(f"\n⚠️  Tracking failed: {response.status_code}")
            print(f"   Response: {response.text[:500]}")
            
    except Exception as e:
        print(f"\n❌ Tracking error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("\n")
    success = test_usps_auth()
    print("\n" + "=" * 70)
    if success:
        print("  ✅ USPS API is fully configured and working!")
        print("  Ready to integrate with Send module")
    else:
        print("  ❌ USPS API configuration needs attention")
    print("=" * 70 + "\n")