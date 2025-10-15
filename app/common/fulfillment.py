# app/common/fulfillment.py
import json, sqlite3
from typing import List, Optional, Dict
from .storage import get_conn

def archive_job_snapshot(
    *,
    service_id: str,
    description: str,
    requester_id: int,
    requester_name: str,
    submitted_at: str,       # ISO 8601
    status: str,             # Completed/Cancelled/...
    fulfilled_by_id: int = None,
    fulfilled_by: str = None,
    completed_at: str = None,
    files: Optional[List[Dict]] = None
) -> None:
    """
    Append a snapshot row into the hard 'fulfillment_archive' store.
    Safe: append-only.
    """
    con = get_conn("fulfillment")
    con.execute("""
        INSERT INTO fulfillment_archive(
          service_id, description, requester_id, requester_name, submitted_at,
          status, fulfilled_by_id, fulfilled_by, completed_at, files_json
        )
        VALUES(?,?,?,?,?,?,?,?,?,?)
    """, (
        service_id, description, requester_id, requester_name, submitted_at,
        status, fulfilled_by_id, fulfilled_by, completed_at, json.dumps(files or [])
    ))
    con.commit(); con.close()

def search_archive(
    q:str="", requester:str="", status:str="", date_from:str="", date_to:str="",
    limit:int=2000
):
    """
    Simple fulfillment archive finder for the new 'Insights (Fulfillment)' tab.
    """
    con = get_conn("fulfillment")
    sql = "SELECT * FROM fulfillment_archive WHERE 1=1"
    params = []
    if q:
        like = f"%{q}%"
        sql += " AND (service_id LIKE ? OR description LIKE ? OR requester_name LIKE ? OR fulfilled_by LIKE ?)"
        params += [like, like, like, like]
    if requester:
        sql += " AND requester_name LIKE ?"; params.append(f"%{requester}%")
    if status:
        sql += " AND status = ?"; params.append(status)
    if date_from:
        sql += " AND date(submitted_at) >= date(?)"; params.append(date_from)
    if date_to:
        sql += " AND date(submitted_at) <= date(?)"; params.append(date_to)
    sql += " ORDER BY submitted_at DESC LIMIT ?"; params.append(limit)
    rows = con.execute(sql, params).fetchall()
    con.close()
    return rows