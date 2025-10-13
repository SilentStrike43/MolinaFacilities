# app/modules/tracking/views.py
from flask import Blueprint, request, render_template
import json, time
from .providers import guess_carrier, fetch_status
from ...common.storage import cache_db

tracking_bp = Blueprint("tracking", __name__, template_folder="../../templates")

def cache_get(tracking: str):
    con = cache_db()
    row = con.execute("SELECT carrier, payload, updated FROM cache WHERE tracking=?", (tracking,)).fetchone()
    con.close()
    return row

def cache_set(tracking: str, carrier: str, payload_json: str):
    con = cache_db()
    con.execute(
        "REPLACE INTO cache(tracking, carrier, payload, updated) VALUES (?,?,?, strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
        (tracking, carrier, payload_json)
    )
    con.commit()
    con.close()

@tracking_bp.route("/", methods=["GET", "POST"])
def page():
    ctx = {"active": "tracking", "result": None, "error": None}
    if request.method == "POST":
        tracking = (request.form.get("TrackingNumber") or "").strip()
        if not tracking:
            ctx["error"] = "Enter a tracking number."
        else:
            cached = cache_get(tracking)
            if cached:
                try:
                    ctx["result"] = json.loads(cached["payload"])
                except Exception:
                    ctx["result"] = {"ok": False, "error": "Cache decode error"}
            else:
                carrier = guess_carrier(tracking) or "Unknown"
                resp = fetch_status(carrier, tracking)
                if resp.get("ok"):
                    cache_set(tracking, carrier, json.dumps(resp, ensure_ascii=False))
                    ctx["result"] = resp
                else:
                    ctx["error"] = resp.get("error", "Lookup failed.")
    return render_template("tracking.html", **ctx)
