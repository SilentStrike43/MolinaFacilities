"""
Quick SES connectivity test — run from repo root in PowerShell:
    python test_ses.py

Requires AWS credentials with ses:SendEmail permission.
On EB this uses the instance profile; locally it uses your AWS CLI credentials.
"""
import boto3
from botocore.exceptions import BotoCoreError, ClientError

TO      = "chris29960@live.com"
FROM    = "noreply@gridlineservice.com"
REGION  = "us-east-1"

client = boto3.client("ses", region_name=REGION)

try:
    response = client.send_email(
        Source=FROM,
        Destination={"ToAddresses": [TO]},
        Message={
            "Subject": {"Data": "Gridline SES Test", "Charset": "UTF-8"},
            "Body": {
                "Text": {"Data": "SES is working correctly.", "Charset": "UTF-8"},
                "Html": {"Data": "<p>SES is working correctly.</p>", "Charset": "UTF-8"},
            },
        },
    )
    print(f"OK — MessageId: {response['MessageId']}")
except (BotoCoreError, ClientError) as e:
    print(f"FAILED — {e}")
