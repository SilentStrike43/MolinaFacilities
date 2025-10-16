# app/modules/send/views.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
import json, datetime
from ...common.security import login_required, current_user
from .storage import (
    ensure_schema, PACKAGE_TYPES, PACKAGE_PREFIX,
    peek_next_checkin_id, next_checkin_id,
    peek_next_package_id, next_package_id,
    cache_get, cache_set, query_print_jobs
)
from .providers import guess_carrier, normalize_scanned
from .spooler import drop_to_bartender_send

send_bp = Blueprint("send", __name__, template_folder="../../templates")

bp = send_bp


ensure_schema()  # make sure our DB exists when imported

def _require_send():
    u = current_user()
    if not u:
        return False, redirect(url_for("auth.login"))
    if u.get("can_send") or u.get("is_admin") or u.get("is_sysadmin") or u.get("is_system"):
        return True, None
    flash("Send access required.", "danger")
    return False, redirect(url_for("home"))

# ---------- Label printing ----------
@send_bp.route("/", methods=["GET","POST"])
@login_required
def page():
    ok, resp = _require_send()
    if not ok: return resp

    today = datetime.date.today().isoformat()
    suggested_checkin = peek_next_checkin_id()
    default_pkg_type = "Box"
    suggested_package = peek_next_package_id(default_pkg_type)

    flashmsg = None
    if request.method == "POST":
        recipient_name = (request.form.get("RecipientName") or "").strip()
        tracking       = (request.form.get("TrackingNumber") or "").strip().replace(" ", "")
        checkin_date   = request.form.get("CheckInDate") or today
        pkg_type       = request.form.get("PackageType") or default_pkg_type

        raw_checkin = (request.form.get("CheckInID") or "").strip()
        if raw_checkin.isdigit():
            checkin_id = raw_checkin
        else:
            checkin_id = str(next_checkin_id())

        raw_pkgid = (request.form.get("PackageID") or "").strip()
        package_id = raw_pkgid if raw_pkgid else next_package_id(pkg_type)

        if not recipient_name or not tracking:
            flashmsg = ("Recipient and Tracking Number are required.", False)
        else:
            u = current_user() or {}
            submitter = " ".join(x for x in [(u.get("first_name") or "").strip(), (u.get("last_name") or "").strip()] if x) or (u.get("username") or "Unknown")

            payload = {
                "CheckInDate": checkin_date,
                "CheckInID": checkin_id,
                "PackageType": pkg_type,
                "PackageID": package_id,
                "RecipientName": recipient_name,
                "TrackingNumber": tracking,
                "Template": "iOffice_Template.btw",
                "Printer": ""
            }
            job = drop_to_bartender_send(payload, submitter_name=submitter, hint="manifest")
            flashmsg = (f"Queued: JSON={job['json_file']}", True)
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
def _carrier_track_url(carrier: str, tracking: str) -> str:
    t = (tracking or "").strip().replace(" ", "")
    c = (carrier or "").lower()
    if c == "ups":   return f"https://www.ups.com/track?loc=en_US&tracknum={t}"
    if c == "fedex": return f"https://www.fedex.com/fedextrack/?trknbr={t}"
    if c == "usps":  return f"https://tools.usps.com/go/TrackConfirmAction?tLabels={t}"
    if c == "dhl":   return f"https://www.dhl.com/global-en/home/tracking/tracking-express.html?submit=1&tracking-id={t}"
    return f"https://www.google.com/search?q={t}+tracking"

@send_bp.route("/tracking", methods=["GET","POST"])
@login_required
def tracking():
    ok, resp = _require_send()
    if not ok: return resp

    ctx = {"active": "send-tracking", "result": None, "error": None, "external_url": None, "carrier": None}
    if request.method == "POST":
        raw = (request.form.get("TrackingNumber") or "").strip()
        if not raw:
            ctx["error"] = "Enter a tracking number."
        else:
            normalized, forced_carrier = normalize_scanned(raw)
            cached = cache_get(normalized)
            if cached:
                try:
                    payload = json.loads(cached["payload"])
                except Exception:
                    payload = {"ok": False}
                carrier = forced_carrier or cached["carrier"]
            else:
                carrier = forced_carrier or (guess_carrier(normalized) or "Other")
                payload = {"ok": True, "tracking": normalized, "carrier": carrier}
                cache_set(normalized, carrier, json.dumps(payload))
            ctx["result"] = payload
            ctx["carrier"] = carrier
            ctx["external_url"] = _carrier_track_url(carrier, normalized)

    return render_template("send/tracking.html", **ctx)

# ---------- Module-local insights (replaces legacy /reports for Send) ----------
@send_bp.route("/insights", methods=["GET"])
@login_required
def insights():
    ok, resp = _require_send()
    if not ok: return resp

    q = (request.args.get("q") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to   = (request.args.get("date_to") or "").strip()
    carrier   = (request.args.get("carrier") or "").strip()

    rows = query_print_jobs({"q": q, "date_from": date_from, "date_to": date_to, "carrier": carrier}, limit=2000)
    carriers = ["USPS","UPS","FedEx","DHL","Other"]
    return render_template("send/insights.html",
        active="send-insights",
        rows=rows, q=q, date_from=date_from, date_to=date_to, carrier=carrier, carriers=carriers
    )

@send_bp.route("/insights.csv", methods=["GET"])
@login_required
def insights_export():
    ok, resp = _require_send()
    if not ok: return resp

    import io, csv
    q = (request.args.get("q") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to   = (request.args.get("date_to") or "").strip()
    carrier   = (request.args.get("carrier") or "").strip()
    rows = query_print_jobs({"q": q, "date_from": date_from, "date_to": date_to, "carrier": carrier}, limit=100000)

    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["ts_utc","submitter_name","item_type","carrier","tracking","to_name"])
    for r in rows:
        w.writerow([r["ts_utc"], r["submitter_name"], r["item_type"], r["carrier"], r["tracking_number"], r["to_name"]])
    mem = io.BytesIO(out.getvalue().encode("utf-8")); mem.seek(0)

    from flask import send_file
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="send_insights_mail.csv")