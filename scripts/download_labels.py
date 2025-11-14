"""
Download FedEx labels with authentication
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.app import create_app
import requests

def get_fedex_token(config):
    """Get OAuth token"""
    response = requests.post(
        f"{config.get('FEDEX_API_URL')}/oauth/token",
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        data={
            'grant_type': 'client_credentials',
            'client_id': config.get('FEDEX_SHIP_API_KEY'),
            'client_secret': config.get('FEDEX_SHIP_SECRET_KEY')
        }
    )
    return response.json()['access_token']

def download_label(url, token, filename):
    """Download label PDF with authentication"""
    
    # The URL needs authentication header
    response = requests.get(
        url,
        headers={
            'Authorization': f'Bearer {token}'
        }
    )
    
    if response.status_code == 200:
        with open(filename, 'wb') as f:
            f.write(response.content)
        return True
    else:
        print(f"Error: {response.status_code}")
        print(f"Response: {response.text}")
        return False

def main():
    """Download labels"""
    
    print("=" * 60)
    print("Download FedEx Test Labels")
    print("=" * 60)
    
    app = create_app()
    
    with app.app_context():
        # Get token
        print("\n🔐 Authenticating...")
        token = get_fedex_token(app.config)
        print("✅ Authenticated")
        
        # Your label URLs from the output
        labels = [
            {
                'url': 'https://wwwtest.fedex.com/document/v1/cache/retrieve/SH,7a55cbee9e716ebc794947651838_SHIPPING_P?isLabel=true&autoPrint=false',
                'filename': 'test_label_1.pdf',
                'tracking': '794947651838'
            },
            {
                'url': 'https://wwwtest.fedex.com/document/v1/cache/retrieve/SH,4cb0587c76e85a92794947651908_SHIPPING_P?isLabel=true&autoPrint=false',
                'filename': 'test_label_2.pdf',
                'tracking': '794947651908'
            },
            {
                'url': 'https://wwwtest.fedex.com/document/v1/cache/retrieve/SH,9db5a7cb8374f58a794947651871_SHIPPING_P?isLabel=true&autoPrint=false',
                'filename': 'test_label_3.pdf',
                'tracking': '794947651871'
            }
        ]
        
        print("\n📥 Downloading labels...\n")
        
        for label in labels:
            print(f"Downloading {label['tracking']}...", end=" ")
            
            if download_label(label['url'], token, label['filename']):
                print(f"✅ Saved as {label['filename']}")
            else:
                print(f"❌ Failed")
        
        print("\n" + "=" * 60)
        print("✅ Download complete!")
        print("\nFiles saved:")
        for label in labels:
            if os.path.exists(label['filename']):
                size_kb = os.path.getsize(label['filename']) / 1024
                print(f"   • {label['filename']} ({size_kb:.1f} KB)")
        print("=" * 60)

if __name__ == "__main__":
    main()