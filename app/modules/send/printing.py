import os, json, datetime, uuid
from .storage import ensure_schema, jobs_db

SPOOL_DIR = os.environ.get("BT_SPOOL_DIR", r"C:\BTManifest\BTInvDrop")
os.makedirs(SPOOL_DIR, exist_ok=True)

def _spool_json(payload: dict, hint: str):
    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    name = f"{ts}_{hint}_{uuid.uuid4().hex[:8]}.json"
    path = os.path.join(SPOOL_DIR, name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path

def drop_to_bartender(payload: dict, hint: str):
    ensure_schema()
    con = jobs_db()
    con.execute("""
        INSERT INTO print_jobs(
            module, job_type, payload,
            checkin_date, checkin_id, package_type, package_id, recipient_name,
            tracking_number, status, printer, template,
            submitter_name, item_type, carrier, tracking, to_name
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        "mail", hint or "manifest", json.dumps(payload, ensure_ascii=False),
        payload.get("CheckInDate",""), payload.get("CheckInID",""),
        payload.get("PackageType",""), payload.get("PackageID",""),
        payload.get("RecipientName",""), payload.get("TrackingNumber",""),
        payload.get("Status","queued"), payload.get("Printer",""), payload.get("Template",""),
        payload.get("SubmitterName",""), payload.get("ItemType",""),
        payload.get("Carrier",""), payload.get("Tracking",""), payload.get("ToName",""),
    ))
    con.commit(); con.close()
    return {"json_file": _spool_json(payload, hint or "manifest")}