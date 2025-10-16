# app/common/printing.py
from __future__ import annotations
import os, json, datetime, uuid
from .storage import (
    jobs_db,
    ensure_jobs_schema,
    ensure_inventory_schema,
)

# Single shared BarTender drop (same path you had)
SPOOL_DIR = r"C:\BTManifest\BTInvDrop"
os.makedirs(SPOOL_DIR, exist_ok=True)

def _get(d: dict, key: str, default=""):
    v = d.get(key)
    return default if v is None else v

def _spool_json(payload: dict, hint: str):
    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    name = f"{ts}_{hint}_{uuid.uuid4().hex[:8]}.json"
    path = os.path.join(SPOOL_DIR, name)
    tmp  = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path

# --- loggers ------------------------------------------------------------------
def log_mail_job(payload: dict, hint: str):
    ensure_jobs_schema()
    con = jobs_db()
    con.execute("""
        INSERT INTO print_jobs(
            module, job_type, payload,
            checkin_date, checkin_id, package_type, package_id, recipient_name,
            tracking_number, status, printer, template
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        "mail", hint, json.dumps(payload, ensure_ascii=False),
        _get(payload,"CheckInDate"),
        _get(payload,"CheckInID"),
        _get(payload,"PackageType"),
        _get(payload,"PackageID"),
        _get(payload,"RecipientName"),
        _get(payload,"TrackingNumber"),
        _get(payload,"Status","queued"),
        _get(payload,"Printer"),
        _get(payload,"Template"),
    ))
    con.commit(); con.close()

def log_inventory_job(payload: dict, hint: str):
    ensure_inventory_schema()
    con = jobs_db()
    con.execute("""
        INSERT INTO inventory_reports(
          checkin_date, inventory_id, item_type, manufacturer,
          product_name, submitter_name, notes, part_number,
          serial_number, count, location, template, printer, status, payload
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        _get(payload,"CheckInDate"),
        int(_get(payload,"InventoryID",0) or 0),
        _get(payload,"ItemType"),
        _get(payload,"Manufacturer"),
        _get(payload,"ProductName"),
        _get(payload,"SubmitterName"),
        _get(payload,"Notes"),
        _get(payload,"PartNumber","N/A"),
        _get(payload,"SerialNumber","N/A"),
        int(_get(payload,"Count",0) or 0),
        _get(payload,"Location"),
        _get(payload,"Template"),
        _get(payload,"Printer"),
        _get(payload,"Status","queued"),
        json.dumps(payload, ensure_ascii=False)
    ))
    con.commit(); con.close()

# --- public entry -------------------------------------------------------------
def drop_to_bartender(payload: dict, hint: str, module: str):
    """
    Spool a JSON and log to insights db. Module decides which table to log to.
    """
    if module == "inventory":
        json_file = _spool_json(payload, "inventory")
        log_inventory_job(payload, "inventory")
        return {"json_file": json_file}
    else:
        json_file = _spool_json(payload, hint or "manifest")
        log_mail_job(payload, hint or "manifest")
        return {"json_file": json_file}