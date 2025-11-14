"""
Test FedEx API Authentication
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

def test_fedex_auth():
    """Test FedEx API credentials"""
    
    api_key = os.getenv('FEDEX_SHIP_API_KEY')
    secret_key = os.getenv('FEDEX_SHIP_SECRET_KEY')
    api_url = os.getenv('FEDEX_API_URL', 'https://apis.fedex.com')
    
    print("=" * 60)
    print("Testing FedEx API Authentication")
    print("=" * 60)
    
    # Check credentials exist
    print(f"\n📋 Credentials Check:")
    print(f"   API Key: {'✅ Set' if api_key else '❌ Missing'}")
    print(f"   Secret Key: {'✅ Set' if secret_key else '❌ Missing'}")
    print(f"   API URL: {api_url}")
    
    if not api_key or not secret_key:
        print("\n❌ Missing credentials in .env file!")
        print("Add these to your .env:")
        print("   FEDEX_SHIP_API_KEY=your_key_here")
        print("   FEDEX_SHIP_SECRET_KEY=your_secret_here")
        return
    
    # Test authentication
    print(f"\n🔐 Testing Authentication...")
    print(f"   Endpoint: {api_url}/oauth/token")
    
    try:
        response = requests.post(
            f"{api_url}/oauth/token",
            headers={
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            data={
                'grant_type': 'client_credentials',
                'client_id': api_key,
                'client_secret': secret_key
            },
            timeout=30
        )
        
        print(f"   Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"\n✅ SUCCESS! Token obtained")
            print(f"   Token Type: {data.get('token_type')}")
            print(f"   Expires In: {data.get('expires_in')} seconds")
            print(f"   Access Token: {data.get('access_token')[:20]}...")
            
        elif response.status_code == 401:
            print(f"\n❌ AUTHENTICATION FAILED (401)")
            print(f"   Your API credentials are invalid")
            print(f"   Response: {response.text}")
            
        elif response.status_code == 403:
            print(f"\n❌ FORBIDDEN (403)")
            print(f"   Your credentials might be:")
            print(f"   - For the wrong environment (test vs production)")
            print(f"   - Not activated yet")
            print(f"   - Missing required permissions")
            print(f"   Response: {response.text}")
            
        else:
            print(f"\n❌ ERROR: {response.status_code}")
            print(f"   Response: {response.text}")
            
    except Exception as e:
        print(f"\n❌ REQUEST FAILED: {e}")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    test_fedex_auth()