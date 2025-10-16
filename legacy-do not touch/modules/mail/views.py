# app/modules/mail/views.py
from flask import Blueprint, render_template, request
import json, datetime
from ...common.printing import drop_to_bartender
from ...common.storage import (
    jobs_db,
    next_checkin_id, peek_next_checkin_id,
    next_package_id, peek_next_package_id,
    PACKAGE_PREFIX,
)
from ..tracking.providers import guess_carrier, normalize_scanned
from ...common.storage import cache_db

mail_bp = Blueprint("mail", __name__, template_folder="../../templates")

PACKAGE_TYPES = ["Box","Envelope","Packs","Tubes","Certified","Sensitive","Critical"]

# ---------- SEND ----------
@mail_bp.route("/", methods=["GET", "POST"])
def page():
    today = datetime.date.today().isoformat()
    suggested_checkin = peek_next_checkin_id()
    default_pkg_type = "Box"
    suggested_package = peek_next_package_id(default_pkg_type)

    flashmsg = None
    if request.method == "POST":
        recipient_name = (request.form.get("RecipientName") or "").strip()
        tracking       = (request.form.get("TrackingNumber") or "").strip()
        checkin_date   = request.form.get("CheckInDate") or today
        pkg_type       = request.form.get("PackageType") or default_pkg_type

        # CheckInID: provided digits or next
        raw_checkin = (request.form.get("CheckInID") or "").strip()
        if raw_checkin.isdigit():
            checkin_id = raw_checkin
        else:
            checkin_id = str(next_checkin_id())

        # PackageID: manual override or generated per type
        raw_pkgid = (request.form.get("PackageID") or "").strip()
        package_id = raw_pkgid if raw_pkgid else next_package_id(pkg_type)

        if not recipient_name or not tracking:
            flashmsg = ("Recipient and Tracking Number are required.", False)
        else:
            payload = {
                "CheckInDate":   checkin_date,
                "CheckInID":     checkin_id,
                "PackageType":   pkg_type,
                "PackageID":     package_id,
                "RecipientName": recipient_name,
                "TrackingNumber": tracking,
                "Template": "iOffice_Template.btw",
                "Printer":  ""
            }
            job = drop_to_bartender(payload, hint="manifest", module="mail")
            flashmsg = (f"Queued: JSON={job['json_file']}", True)
            suggested_checkin = int(checkin_id) + 1
            suggested_package = peek_next_package_id(pkg_type)

    return render_template(
        "mail/index.html",
        active="send",
        flashmsg=flashmsg,
        today=today,
        package_types=PACKAGE_TYPES,
        suggested_checkin=suggested_checkin,
        suggested_package=suggested_package,
        package_prefix=PACKAGE_PREFIX,
    )

# ---------- Tracking (Send → Tracking) ----------
def _carrier_track_url(carrier: str, tracking: str) -> str:
    t = tracking.strip().replace(" ", "")
    c = (carrier or "").lower()
    if c == "ups":
        return f"https://www.ups.com/track?loc=en_US&tracknum={t}"
    if c == "fedex":
        return f"https://www.fedex.com/fedextrack/?trknbr={t}"
    if c == "usps":
        return f"https://tools.usps.com/go/TrackConfirmAction?tLabels={t}"
    if c == "dhl":
        return f"https://www.dhl.com/global-en/home/tracking/tracking-express.html?submit=1&tracking-id={t}"
    return f"https://www.google.com/search?q={t}+tracking"

def _cache_get(tracking: str):
    con = cache_db()
    row = con.execute("SELECT carrier, payload, updated FROM cache WHERE tracking=?", (tracking,)).fetchone()
    con.close()
    return row

def _cache_set(tracking: str, carrier: str, payload_json: str):
    con = cache_db()
    con.execute(
        "REPLACE INTO cache(tracking, carrier, payload, updated) VALUES (?,?,?, strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
        (tracking, carrier, payload_json)
    )
    con.commit(); con.close()

@mail_bp.route("/tracking", methods=["GET", "POST"])
def tracking():
    ctx = {"active": "send-tracking", "result": None, "error": None, "external_url": None, "carrier": None}
    if request.method == "POST":
        raw = (request.form.get("TrackingNumber") or "").strip()
        if not raw:
            ctx["error"] = "Enter a tracking number."
        else:
            normalized, forced_carrier = normalize_scanned(raw)
            cached = _cache_get(normalized)
            if cached:
                try:
                    payload = json.loads(cached["payload"])
                except Exception:
                    payload = {"ok": False}
                carrier = forced_carrier or cached["carrier"]
            else:
                carrier = forced_carrier or (guess_carrier(normalized) or "Unknown")
                payload = {"ok": True, "tracking": normalized, "carrier": carrier}
                _cache_set(normalized, carrier, json.dumps(payload))
            ctx["result"] = payload
            ctx["carrier"] = carrier
            ctx["external_url"] = _carrier_track_url(carrier, normalized)
    return render_template("mail/tracking.html", **ctx)

