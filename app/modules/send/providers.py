# app/modules/send/providers.py
import re, time
from typing import Optional, Dict, Tuple

CARRIER_RULES = [
    ("UPS",   re.compile(r"^1Z[0-9A-Z]{16}$", re.I)),
    ("UPS",   re.compile(r"^\d{9}$")),
    ("FedEx", re.compile(r"^\d{12,15}$")),
    ("USPS",  re.compile(r"^\d{20,22}$")),
    ("USPS",  re.compile(r"^[A-Z]{2}\d{9}US$", re.I)),
    ("DHL",   re.compile(r"^(JD|JJD)\d+", re.I)),
    ("DHL",   re.compile(r"^\d{10}$")),
]

def normalize_scanned(tracking: str) -> Tuple[str, Optional[str]]:
    s = tracking.strip().replace(" ", "")
    if len(s) >= 20:
        m = re.search(r"(\d{12})$", s)
        if m:
            return m.group(1), "FedEx"
    return s, None

def guess_carrier(tracking: str) -> Optional[str]:
    s = tracking.strip().replace(" ", "")
    for name, rx in CARRIER_RULES:
        if rx.match(s):
            return name
    return None

def fetch_status(carrier: str, tracking: str) -> Dict:
    # placeholder; real carrier lookups would go here
    time.sleep(0.05)
    return {
        "ok": True,
        "carrier": carrier,
        "tracking": tracking,
        "status": "In Transit",
        "last_scan": "Sorting Facility",
        "eta": "",
        "raw": {}
    }