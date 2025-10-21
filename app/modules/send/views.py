# app/modules/send/views.py
import datetime
from flask import render_template, request, redirect, url_for, flash

from . import bp  # Import bp from __init__.py - DO NOT redefine it

from app.core.auth import login_required, require_cap, current_user, record_audit

from .models import (
    ensure_schema, 
    peek_next_checkin_id, next_checkin_id,
    peek_next_package_id, next_package_id,
    PACKAGE_PREFIX
)
from .printing import drop_to_bartender
from .providers import guess_carrier, normalize_scanned

PACKAGE_TYPES = ["Box","Envelope","Packs","Tubes","Certified","Sensitive","Critical"]

# ---------- Send (print label) ----------
@bp.route("/", methods=["GET","POST"], endpoint="index")
@login_required
@require_cap("can_send")
def page():
    ensure_schema()
    today = datetime.date.today().isoformat()
    default_pkg_type = "Box"
    suggested_checkin = peek_next_checkin_id()
    suggested_package = peek_next_package_id(default_pkg_type)

    flashmsg = None
    if request.method == "POST":
        recipient_name = (request.form.get("RecipientName") or "").strip()
        tracking       = (request.form.get("TrackingNumber") or "").strip()
        checkin_date   = request.form.get("CheckInDate") or today
        pkg_type       = request.form.get("PackageType") or default_pkg_type

        raw_checkin = (request.form.get("CheckInID") or "").strip()
        checkin_id  = raw_checkin if raw_checkin.isdigit() else str(next_checkin_id())

        raw_pkgid   = (request.form.get("PackageID") or "").strip()
        package_id  = raw_pkgid if raw_pkgid else next_package_id(pkg_type)

        if not recipient_name or not tracking:
            flashmsg = ("Recipient and Tracking Number are required.", False)
        else:
            payload = {
                "CheckInDate": checkin_date,
                "CheckInID": checkin_id,
                "PackageType": pkg_type,
                "PackageID": package_id,
                "RecipientName": recipient_name,
                "TrackingNumber": tracking,
                "Template": "iOffice_Template.btw",
                "Printer":  ""
            }
            job = drop_to_bartender(payload, hint="manifest")
            record_audit(current_user(), "print_label", "send", 
                        f"CheckInID={checkin_id}, PackageID={package_id}")
            flashmsg = (f"Label queued successfully.", True)
            suggested_checkin = int(checkin_id) + 1
            suggested_package = peek_next_package_id(pkg_type)

    return render_template(
        "send/index.html",
        active="send",
        flashmsg=flashmsg,
        today=today,
        package_types=PACKAGE_TYPES,
        suggested_checkin=suggested_checkin,
        suggested_package=suggested_package,
        package_prefix=PACKAGE_PREFIX,
    )

# ---------- Tracking ----------
@bp.route("/tracking", methods=["GET","POST"])
@login_required
@require_cap("can_send")
def tracking():
    ctx = {
        "active": "send-tracking", 
        "result": None, 
        "error": None, 
        "external_url": None, 
        "carrier": None
    }
    
    if request.method == "POST":
        raw = (request.form.get("TrackingNumber") or "").strip()
        if not raw:
            ctx["error"] = "Enter a tracking number."
        else:
            normalized, forced = normalize_scanned(raw)
            carrier = forced or (guess_carrier(normalized) or "Unknown")
            payload = {"ok": True, "tracking": normalized, "carrier": carrier}
            t = normalized.replace(" ", "")
            ctx["result"] = payload
            ctx["carrier"] = carrier
            
            # Generate carrier URLs
            if carrier.lower() == "ups":
                ctx["external_url"] = f"https://www.ups.com/track?loc=en_US&tracknum={t}"
            elif carrier.lower() == "fedex":
                ctx["external_url"] = f"https://www.fedex.com/fedextrack/?trknbr={t}"
            elif carrier.lower() == "usps":
                ctx["external_url"] = f"https://tools.usps.com/go/TrackConfirmAction?tLabels={t}"
            elif carrier.lower() == "dhl":
                ctx["external_url"] = f"https://www.dhl.com/global-en/home/tracking/tracking-express.html?submit=1&tracking-id={t}"
            else:
                ctx["external_url"] = f"https://www.google.com/search?q={t}+tracking"
    
    return render_template("send/tracking.html", **ctx)