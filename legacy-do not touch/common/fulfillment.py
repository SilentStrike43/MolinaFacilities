# app/common/fulfillment.py
import json
from typing import Optional, Iterable, Dict, Any
from .storage import fulfillment_db

def create_request(service_id: str, requester: str, files_json: Optional[dict] = None):
    con = fulfillment_db()
    con.execute("""
        INSERT INTO fulfillment_requests(service_id, requester, status, files_json)
        VALUES(?,?, 'Submitted', ?)
    """, (service_id, requester, json.dumps(files_json or {}, ensure_ascii=False)))
    con.commit(); con.close()

def update_request_status(req_id: int, status: str, staff_member: Optional[str] = None, completed_utc: Optional[str] = None):
    con = fulfillment_db()
    con.execute("""
        UPDATE fulfillment_requests
           SET status=?,
               staff_member=COALESCE(?, staff_member),
               completed_utc=COALESCE(?, completed_utc)
         WHERE id=?
    """, (status, staff_member, completed_utc, req_id))
    con.commit(); con.close()

def list_requests(limit: int = 500) -> Iterable[Dict[str, Any]]:
    con = fulfillment_db()
    rows = con.execute("SELECT * FROM fulfillment_requests ORDER BY date_submitted DESC LIMIT ?", (limit,)).fetchall()
    con.close()
    return rows
