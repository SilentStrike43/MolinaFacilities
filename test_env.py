from dotenv import load_dotenv
import os

load_dotenv()

print("Testing environment variables:")
print(f"DB_CORE_CONNECTION_STRING: {os.environ.get('DB_CORE_CONNECTION_STRING', 'NOT SET')[:50]}...")
print(f"FLASK_ENV: {os.environ.get('FLASK_ENV', 'NOT SET')}")
print(f"SECRET_KEY: {os.environ.get('SECRET_KEY', 'NOT SET')[:20]}...")