# DO NOT create a Blueprint here
from flask import render_template
from . import bp                      # <— this was missing

from app.modules.auth.security import require_cap

@bp.get("/")
@require_cap("can_send")
def page():
    return render_template("mail/index.html", active="send")

@bp.route("/insights")
def insights():
    # temporary: route exists so navbar works; send users to Tracking for now
    return redirect(url_for("send.tracking"))

from .printing import drop_to_bartender
from .providers import guess_carrier, normalize_scanned

bp = Blueprint("send", __name__, template_folder="../templates")

PACKAGE_TYPES = ["Box","Envelope","Packs","Tubes","Certified","Sensitive","Critical"]

# ---------- Send (print label) ----------
@bp.route("/", methods=["GET","POST"])
@login_required
@require_cap("can_send")
def page():
    ensure_schema()  # make sure our DB exists
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

# ---------- Tracking ----------
@bp.route("/tracking", methods=["GET","POST"])
@login_required
@require_cap("can_send")
def tracking():
    ctx = {"active": "send-tracking", "result": None, "error": None, "external_url": None, "carrier": None}
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
    return render_template("mail/tracking.html", **ctx)