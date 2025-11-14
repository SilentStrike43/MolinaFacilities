"""
Generate test shipping labels for FedEx validation
Creates Express and SmartPost shipments for FedEx Label Analysis Group
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.app import create_app
import requests
from datetime import datetime

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

def create_express_shipment(token, api_url, account_number):
    """Create a FedEx Express (2Day) test shipment"""
    
    payload = {
        "labelResponseOptions": "URL_ONLY",
        "requestedShipment": {
            "shipper": {
                "contact": {
                    "personName": "Express Test Shipper",
                    "phoneNumber": "5551234567",
                    "companyName": "GridLine Services Test"
                },
                "address": {
                    "streetLines": ["1234 Express Lane"],
                    "city": "Memphis",
                    "stateOrProvinceCode": "TN",
                    "postalCode": "38125",
                    "countryCode": "US",
                    "residential": False
                }
            },
            "recipients": [{
                "contact": {
                    "personName": "Express Test Recipient",
                    "phoneNumber": "5559876543",
                    "companyName": "Test Recipient Express Inc"
                },
                "address": {
                    "streetLines": ["456 Express Boulevard"],
                    "city": "New York",
                    "stateOrProvinceCode": "NY",
                    "postalCode": "10001",
                    "countryCode": "US",
                    "residential": False
                }
            }],
            "shipDateStamp": datetime.now().strftime("%Y-%m-%d"),
            "serviceType": "FEDEX_2_DAY",  # EXPRESS SERVICE
            "packagingType": "YOUR_PACKAGING",
            "pickupType": "USE_SCHEDULED_PICKUP",
            "blockInsightVisibility": False,
            "shippingChargesPayment": {
                "paymentType": "SENDER"
            },
            "labelSpecification": {
                "imageType": "PDF",
                "labelStockType": "PAPER_85X11_TOP_HALF_LABEL"
            },
            "requestedPackageLineItems": [{
                "weight": {
                    "units": "LB",
                    "value": 5.0
                },
                "dimensions": {
                    "length": 12,
                    "width": 10,
                    "height": 8,
                    "units": "IN"
                }
            }]
        },
        "accountNumber": {
            "value": account_number
        }
    }
    
    response = requests.post(
        f"{api_url}/ship/v1/shipments",
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        },
        json=payload
    )
    
    return response

def create_smartpost_shipment(token, api_url, account_number):
    """Create a FedEx SmartPost test shipment"""
    
    payload = {
        "labelResponseOptions": "URL_ONLY",
        "requestedShipment": {
            "shipper": {
                "contact": {
                    "personName": "SmartPost Test Shipper",
                    "phoneNumber": "5551234567",
                    "companyName": "GridLine Services Test"
                },
                "address": {
                    "streetLines": ["1234 SmartPost Road"],
                    "city": "Memphis",
                    "stateOrProvinceCode": "TN",
                    "postalCode": "38125",
                    "countryCode": "US",
                    "residential": False
                }
            },
            "recipients": [{
                "contact": {
                    "personName": "SmartPost Test Recipient",
                    "phoneNumber": "5559876543",
                    "companyName": ""
                },
                "address": {
                    "streetLines": ["789 SmartPost Circle"],
                    "city": "Los Angeles",
                    "stateOrProvinceCode": "CA",
                    "postalCode": "90001",
                    "countryCode": "US",
                    "residential": True  # SmartPost is typically residential
                }
            }],
            "shipDateStamp": datetime.now().strftime("%Y-%m-%d"),
            "serviceType": "SMART_POST",  # SMARTPOST SERVICE
            "packagingType": "YOUR_PACKAGING",
            "pickupType": "DROPOFF_AT_FEDEX_LOCATION",
            "blockInsightVisibility": False,
            "shippingChargesPayment": {
                "paymentType": "SENDER"
            },
            "smartPostInfoDetail": {
                "indicia": "PARCEL_SELECT",  # Required for SmartPost
                "ancillaryEndorsement": "ADDRESS_CORRECTION",
                "hubId": "5531",  # Memphis SmartPost Hub
                "customerManifestId": "SMARTPOST_TEST_001"
            },
            "labelSpecification": {
                "imageType": "PDF",
                "labelStockType": "PAPER_85X11_TOP_HALF_LABEL"
            },
            "requestedPackageLineItems": [{
                "weight": {
                    "units": "LB",
                    "value": 2.0  # SmartPost typically lighter packages
                },
                "dimensions": {
                    "length": 10,
                    "width": 8,
                    "height": 4,
                    "units": "IN"
                }
            }]
        },
        "accountNumber": {
            "value": account_number
        }
    }
    
    response = requests.post(
        f"{api_url}/ship/v1/shipments",
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        },
        json=payload
    )
    
    return response

def main():
    """Generate Express and SmartPost test labels for FedEx certification"""
    
    print("=" * 60)
    print("FedEx Certification Label Generator")
    print("Express + SmartPost Samples")
    print("=" * 60)
    
    app = create_app()
    
    with app.app_context():
        try:
            # Get token
            print("\n🔐 Authenticating with FedEx...")
            token = get_fedex_token(app.config)
            print("✅ Authentication successful")
            
            # Get account number
            account_number = app.config.get('FEDEX_ACCOUNT_NUMBER')
            if not account_number:
                print("❌ FEDEX_ACCOUNT_NUMBER not set in .env")
                return
            
            api_url = app.config.get('FEDEX_API_URL')
            
            results = []
            
            # 1. Create Express Label
            print("\n" + "=" * 60)
            print("📦 CREATING EXPRESS LABEL (FEDEX_2_DAY)")
            print("=" * 60)
            
            print("Creating FedEx Express shipment...")
            response = create_express_shipment(token, api_url, account_number)
            
            if response.status_code == 200:
                data = response.json()
                tracking = data['output']['transactionShipments'][0]['masterTrackingNumber']
                label_url = data['output']['transactionShipments'][0]['pieceResponses'][0]['packageDocuments'][0]['url']
                
                print(f"✅ Express Label Created Successfully!")
                print(f"   Tracking: {tracking}")
                print(f"   Service: FEDEX_2_DAY (Express)")
                print(f"   Label URL: {label_url}")
                
                results.append({
                    'type': 'EXPRESS',
                    'service': 'FEDEX_2_DAY',
                    'tracking': tracking,
                    'label_url': label_url
                })
            else:
                print(f"❌ Express Label Failed: {response.status_code}")
                print(f"   Error: {response.text}")
            
            # 2. Create SmartPost Label
            print("\n" + "=" * 60)
            print("📮 CREATING SMARTPOST LABEL")
            print("=" * 60)
            
            print("Creating FedEx SmartPost shipment...")
            response = create_smartpost_shipment(token, api_url, account_number)
            
            if response.status_code == 200:
                data = response.json()
                tracking = data['output']['transactionShipments'][0]['masterTrackingNumber']
                label_url = data['output']['transactionShipments'][0]['pieceResponses'][0]['packageDocuments'][0]['url']
                
                print(f"✅ SmartPost Label Created Successfully!")
                print(f"   Tracking: {tracking}")
                print(f"   Service: SMART_POST")
                print(f"   Label URL: {label_url}")
                
                results.append({
                    'type': 'SMARTPOST',
                    'service': 'SMART_POST',
                    'tracking': tracking,
                    'label_url': label_url
                })
            else:
                print(f"❌ SmartPost Label Failed: {response.status_code}")
                print(f"   Error: {response.text}")
            
            # Summary
            print("\n" + "=" * 60)
            print("CERTIFICATION LABELS GENERATED")
            print("=" * 60)
            
            if results:
                print(f"\n✅ {len(results)} label(s) created successfully!\n")
                
                for i, r in enumerate(results, 1):
                    print(f"{i}. {r['type']} LABEL ({r['service']})")
                    print(f"   Tracking: {r['tracking']}")
                    print(f"   Download: {r['label_url']}")
                    print()
                
                print("=" * 60)
                print("📧 SUBMISSION INSTRUCTIONS")
                print("=" * 60)
                print("\n1. Download both PDF labels from the URLs above")
                print("2. Email to: LabelAnalysisGroup@fedex.com")
                print("3. Subject: Label Validation - GridLine Services")
                print("4. Attach both PDF files:")
                print("   - Express Label (FEDEX_2_DAY)")
                print("   - SmartPost Label (SMART_POST)")
                print("\n5. In email body, include:")
                print("   - Your FedEx Account Number")
                print("   - Company Name: GridLine Services")
                print("   - Contact Email")
                print("   - Note: 'Certification label samples as requested'")
                
                print("\n" + "=" * 60)
                print("⏰ TIMELINE")
                print("=" * 60)
                print("FedEx typically responds within 3-5 business days")
                print("Check your email for certification approval")
                print("=" * 60)
                
            else:
                print("\n❌ No labels were created successfully")
                print("Please check the error messages above and try again")
            
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()