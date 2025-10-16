# app/common/paths.py
import os

APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(APP_ROOT, "data")
SPOOL_DIR = os.environ.get("BT_SPOOL_DIR", r"C:\BTManifest\BTInvDrop")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(SPOOL_DIR, exist_ok=True)
