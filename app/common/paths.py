# app/common/paths.py
import os

BASE_DIR = os.environ.get("FAC_APP_DIR", r"C:\BTManifest")
FULFILL_DIR = os.path.join(BASE_DIR, "Fulfillment")
UPLOAD_DIR = os.path.join(FULFILL_DIR, "uploads")

# make sure directories exist
os.makedirs(UPLOAD_DIR, exist_ok=True)