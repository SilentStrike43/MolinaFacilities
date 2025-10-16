# app/modules/send/spooler.py
import os, json, datetime, uuid
from .storage import insert_print_job
from .providers import guess_carrier

# Single shared BarTender drop — reuse your existing path
SPOOL_DIR = r"C:\BTManifest\BTInvDrop"
os.makedirs(SPOOL_DIR, exist_ok=True)

def _spool_json(payload: dict, hint: str) -> str:
    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    name = f"{ts}_{hint}_{uuid.uuid4().hex[:8]}.json"
    path = os.path.join(SPOOL_DIR, name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path

def drop_to_bartender_send(payload: dict, *, submitter_name: str, hint: str = "manifest"):
    """
    Spool JSON and log into this module's print_jobs table.
    """
    json_file = _spool_json(payload, hint or "manifest")
    carrier = guess_carrier(payload.get("TrackingNumber","") or "") or "Other"

    # Log normalized fields for module-local insights
    insert_print_job({
        "module": "send",
        "job_type": hint or "manifest",
        "payload": json.dumps(payload, ensure_ascii=False),

        "checkin_date": payload.get("CheckInDate"),
        "checkin_id": payload.get("CheckInID"),
        "package_type": payload.get("PackageType"),
        "package_id": payload.get("PackageID"),
        "recipient_name": payload.get("RecipientName"),
        "tracking_number": payload.get("TrackingNumber"),
        "status": payload.get("Status","queued"),
        "printer": payload.get("Printer"),
        "template": payload.get("Template"),

        "submitter_name": submitter_name,
        "item_type": "Package",
        "carrier": carrier,
        "to_name": payload.get("RecipientName"),
    })
    return {"json_file": json_file}
