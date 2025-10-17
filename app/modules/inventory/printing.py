# app/modules/inventory/printing.py
import os, json, uuid, datetime
from .models import inventory_db

SPOOL_DIR = os.path.join(os.path.dirname(__file__), "bt_spool")
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

def queue_inventory_label(payload: dict):
    json_file = _spool_json(payload, "inventory")
    con = inventory_db()
    con.execute("""
      INSERT INTO inventory_reports(
        checkin_date, inventory_id, item_type, manufacturer, product_name,
        submitter_name, notes, part_number, serial_number, count, location,
        template, printer, status, payload
      ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        payload.get("CheckInDate",""),
        int(payload.get("InventoryID") or 0),
        payload.get("ItemType",""),
        payload.get("Manufacturer",""),
        payload.get("ProductName",""),
        payload.get("SubmitterName",""),
        payload.get("Notes",""),
        payload.get("PartNumber","N/A"),
        payload.get("SerialNumber","N/A"),
        int(payload.get("Count") or 0),
        payload.get("Location",""),
        payload.get("Template",""),
        payload.get("Printer",""),
        payload.get("Status","queued"),
        json.dumps(payload, ensure_ascii=False)
    ))
    con.commit(); con.close()
    return {"json_file": json_file}