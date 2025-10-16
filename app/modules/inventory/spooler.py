# app/modules/inventory/spooler.py
import os, json, datetime, uuid
from .storage import insert_insight

SPOOL_DIR = r"C:\BTManifest\BTInvDrop"
os.makedirs(SPOOL_DIR, exist_ok=True)

def _spool_json(payload: dict, hint: str = "inventory") -> str:
    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    name = f"{ts}_{hint}_{uuid.uuid4().hex[:8]}.json"
    path = os.path.join(SPOOL_DIR, name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path

def drop_inventory_label(payload: dict, *, submitter_name: str):
    """
    Spool a label JSON and also log a minimal row into inventory_reports
    so Insights has data without requiring cross-module deps.
    """
    jf = _spool_json(payload, "inventory")
    insert_insight({
        "inventory_id":   payload.get("InventoryID"),
        "product_name":   payload.get("ProductName"),
        "manufacturer":   payload.get("Manufacturer"),
        "item_type":      payload.get("ItemType"),
        "submitter_name": submitter_name,
        "pii":            payload.get("PII"),
        "notes":          (payload.get("Notes") or ""),
    })
    return {"json_file": jf}