"""
FedEx Label Reprint Utility
Uses Gridline .env credentials to retrieve and print shipping labels

Usage:
    python fedex_label_reprint.py <tracking_number>
    python fedex_label_reprint.py 886207861398

Options:
    --save      Save ZPL to file instead of printing
    --printer   Specify printer IP (default: prints to file)
"""

import os
import sys
import base64
import socket
import requests
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# =============================================================================
# CONFIGURATION (loaded from .env)
# =============================================================================
FEDEX_API_URL = os.getenv('FEDEX_API_URL', 'https://apis.fedex.com')
FEDEX_API_KEY = os.getenv('FEDEX_SHIP_API_KEY')
FEDEX_SECRET_KEY = os.getenv('FEDEX_SHIP_SECRET_KEY')
FEDEX_ACCOUNT_NUMBER = os.getenv('FEDEX_ACCOUNT_NUMBER')

# Printer settings (modify these for your setup)
PRINTER_IP = None  # Set to your Zebra's IP, e.g., "192.168.1.100"
PRINTER_PORT = 9100


def get_access_token():
    """Authenticate with FedEx and get OAuth token"""
    
    url = f"{FEDEX_API_URL}/oauth/token"
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    payload = {
        "grant_type": "client_credentials",
        "client_id": FEDEX_API_KEY,
        "client_secret": FEDEX_SECRET_KEY
    }
    
    print("Authenticating with FedEx...")
    response = requests.post(url, headers=headers, data=payload)
    
    if response.status_code != 200:
        print(f"Authentication failed: {response.status_code}")
        print(response.text)
        return None
    
    token = response.json().get('access_token')
    print("Authentication successful!")
    return token


def get_label_by_tracking(tracking_number, auth_token):
    """Retrieve shipping label using tracking number"""
    
    # Try the Track Document endpoint first
    url = f"{FEDEX_API_URL}/track/v1/trackingnumbers/{tracking_number}/documents"
    
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "X-locale": "en_US"
    }
    
    # Request for label document
    payload = {
        "trackingInfo": [
            {
                "trackingNumberInfo": {
                    "trackingNumber": tracking_number
                }
            }
        ],
        "labelSpecification": {
            "imageType": "ZPLII",
            "labelStockType": "STOCK_4X6"
        }
    }
    
    print(f"Requesting label for tracking: {tracking_number}")
    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code == 200:
        return response.json(), "track"
    
    print(f"Track endpoint returned: {response.status_code}")
    
    # Try Ship Document retrieval endpoint
    url = f"{FEDEX_API_URL}/ship/v1/shipments/documents"
    
    payload = {
        "accountNumber": {
            "value": FEDEX_ACCOUNT_NUMBER
        },
        "trackingNumber": tracking_number,
        "labelResponseOptions": "LABEL",
        "labelSpecification": {
            "imageType": "ZPLII",
            "labelStockType": "STOCK_4X6"
        }
    }
    
    print("Trying ship documents endpoint...")
    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code == 200:
        return response.json(), "ship"
    
    print(f"Ship endpoint returned: {response.status_code}")
    print(response.text)
    
    # Try the retrieve endpoint for completed shipments
    url = f"{FEDEX_API_URL}/ship/v1/shipments/results"
    
    payload = {
        "accountNumber": {
            "value": FEDEX_ACCOUNT_NUMBER
        },
        "jobId": tracking_number,
        "labelResponseOptions": "LABEL",
        "labelSpecification": {
            "imageType": "ZPLII",
            "labelStockType": "STOCK_4X6"
        }
    }
    
    print("Trying shipment results endpoint...")
    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code == 200:
        return response.json(), "results"
    
    print(f"Results endpoint returned: {response.status_code}")
    print(response.text)
    
    return None, None


def extract_zpl_from_response(data, endpoint_type):
    """Extract ZPL code from FedEx API response"""
    
    try:
        if endpoint_type == "track":
            # Track endpoint structure
            documents = data.get('output', {}).get('documents', [])
            if documents:
                encoded = documents[0].get('encodedLabel') or documents[0].get('document')
                if encoded:
                    return base64.b64decode(encoded).decode('utf-8')
        
        elif endpoint_type == "ship":
            # Ship documents endpoint structure
            output = data.get('output', {})
            
            # Try different response structures
            if 'transactionShipments' in output:
                shipments = output['transactionShipments']
                if shipments:
                    pieces = shipments[0].get('pieceResponses', [])
                    if pieces:
                        docs = pieces[0].get('packageDocuments', [])
                        if docs:
                            encoded = docs[0].get('encodedLabel')
                            if encoded:
                                return base64.b64decode(encoded).decode('utf-8')
            
            # Alternative structure
            if 'documents' in output:
                docs = output['documents']
                if docs:
                    encoded = docs[0].get('encodedLabel')
                    if encoded:
                        return base64.b64decode(encoded).decode('utf-8')
        
        elif endpoint_type == "results":
            # Results endpoint structure
            output = data.get('output', {})
            if 'transactionShipments' in output:
                shipments = output['transactionShipments']
                if shipments:
                    pieces = shipments[0].get('pieceResponses', [])
                    if pieces:
                        docs = pieces[0].get('packageDocuments', [])
                        if docs:
                            encoded = docs[0].get('encodedLabel')
                            if encoded:
                                return base64.b64decode(encoded).decode('utf-8')
        
        # Debug: print structure if extraction failed
        print("\nResponse structure (for debugging):")
        print_dict_structure(data)
        
    except Exception as e:
        print(f"Error extracting ZPL: {e}")
    
    return None


def print_dict_structure(d, indent=0):
    """Helper to visualize API response structure"""
    for key, value in d.items():
        if isinstance(value, dict):
            print("  " * indent + f"{key}:")
            print_dict_structure(value, indent + 1)
        elif isinstance(value, list):
            print("  " * indent + f"{key}: [list with {len(value)} items]")
            if value and isinstance(value[0], dict):
                print_dict_structure(value[0], indent + 1)
        else:
            val_preview = str(value)[:50] + "..." if len(str(value)) > 50 else str(value)
            print("  " * indent + f"{key}: {val_preview}")


def send_to_printer(zpl_code, printer_ip, port=9100):
    """Send ZPL directly to network printer"""
    
    print(f"Sending to printer at {printer_ip}:{port}...")
    
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(10)
            s.connect((printer_ip, port))
            s.sendall(zpl_code.encode('utf-8'))
        print("Label sent successfully!")
        return True
    except socket.timeout:
        print(f"Connection timed out - is the printer on and reachable?")
    except ConnectionRefusedError:
        print(f"Connection refused - check printer IP and port")
    except Exception as e:
        print(f"Print error: {e}")
    
    return False


def save_zpl_to_file(zpl_code, tracking_number):
    """Save ZPL to file for manual printing"""
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"label_{tracking_number}_{timestamp}.zpl"
    
    with open(filename, 'w') as f:
        f.write(zpl_code)
    
    print(f"Label saved to: {filename}")
    print(f"\nTo print manually:")
    print(f"  Network: copy {filename} to \\\\PRINTER_IP\\port")
    print(f"  Windows: copy {filename} LPT1 (if USB)")
    print(f"  Mac/Linux: lpr -P Zebra_Printer -o raw {filename}")
    
    return filename


def main():
    # Check for tracking number argument
    if len(sys.argv) < 2:
        print("Usage: python fedex_label_reprint.py <tracking_number> [--printer IP]")
        print("Example: python fedex_label_reprint.py 886207861398")
        print("         python fedex_label_reprint.py 886207861398 --printer 192.168.1.100")
        sys.exit(1)
    
    tracking_number = sys.argv[1]
    
    # Check for printer IP argument
    printer_ip = PRINTER_IP
    if '--printer' in sys.argv:
        idx = sys.argv.index('--printer')
        if idx + 1 < len(sys.argv):
            printer_ip = sys.argv[idx + 1]
    
    # Validate environment
    if not FEDEX_API_KEY or not FEDEX_SECRET_KEY:
        print("ERROR: FedEx credentials not found in .env file")
        print("Make sure your .env contains:")
        print("  FEDEX_SHIP_API_KEY=...")
        print("  FEDEX_SHIP_SECRET_KEY=...")
        print("  FEDEX_ACCOUNT_NUMBER=...")
        sys.exit(1)
    
    print("=" * 60)
    print("FedEx Label Reprint Utility")
    print("=" * 60)
    print(f"Tracking Number: {tracking_number}")
    print(f"Account Number:  {FEDEX_ACCOUNT_NUMBER}")
    print(f"API URL:         {FEDEX_API_URL}")
    print(f"Printer IP:      {printer_ip or 'Not set (will save to file)'}")
    print("=" * 60)
    
    # Step 1: Authenticate
    token = get_access_token()
    if not token:
        print("Failed to authenticate with FedEx")
        sys.exit(1)
    
    # Step 2: Get label
    response_data, endpoint_type = get_label_by_tracking(tracking_number, token)
    
    if not response_data:
        print("\nFailed to retrieve label from FedEx")
        print("Possible reasons:")
        print("  - Tracking number not found")
        print("  - Shipment not associated with your account")
        print("  - Label data has expired (typically 14-30 days)")
        sys.exit(1)
    
    # Step 3: Extract ZPL
    zpl_code = extract_zpl_from_response(response_data, endpoint_type)
    
    if not zpl_code:
        print("\nCould not extract ZPL from response")
        print("The shipment may not have label data available")
        
        # Save raw response for debugging
        import json
        debug_file = f"debug_response_{tracking_number}.json"
        with open(debug_file, 'w') as f:
            json.dump(response_data, f, indent=2)
        print(f"Raw response saved to: {debug_file}")
        sys.exit(1)
    
    print(f"\nLabel retrieved successfully! ({len(zpl_code)} bytes)")
    
    # Step 4: Print or save
    if printer_ip:
        send_to_printer(zpl_code, printer_ip)
    else:
        save_zpl_to_file(zpl_code, tracking_number)
    
    print("\nDone!")


if __name__ == "__main__":
    main()
