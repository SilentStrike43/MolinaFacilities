# app/modules/send/printing.py
import os, json, uuid, datetime
from .models import jobs_db

SPOOL_DIR = os.path.join(os.path.dirname(__file__), "bt_spool")
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

def drop_to_bartender(payload: dict, hint: str = "manifest"):
    """Queue a label and record the job in this module's DB."""
    json_file = _spool_json(payload, hint or "manifest")
    con = jobs_db()
    con.execute("""
        INSERT INTO print_jobs(
          module, job_type, payload,
          checkin_date, checkin_id, package_type, package_id,
          recipient_name, tracking_number, status, printer, template
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        "mail", hint, json.dumps(payload, ensure_ascii=False),
        payload.get("CheckInDate",""),
        payload.get("CheckInID",""),
        payload.get("PackageType",""),
        payload.get("PackageID",""),
        payload.get("RecipientName",""),
        payload.get("TrackingNumber",""),
        payload.get("Status","queued"),
        payload.get("Printer",""),
        payload.get("Template",""),
    ))
    con.commit(); con.close()
    return {"json_file": json_file}