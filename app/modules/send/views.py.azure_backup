# app/modules/send/views.py
import datetime
from flask import render_template, request, redirect, url_for, flash, jsonify 

from . import bp

from app.modules.auth.security import (
    login_required, require_cap, current_user, 
    record_audit, get_user_location
)
from app.core.database import get_db_connection

from .models import (
    ensure_schema, 
    peek_next_checkin_id, next_checkin_id,
    peek_next_package_id, next_package_id,
    PACKAGE_PREFIX
)
from .providers import guess_carrier, normalize_scanned

PACKAGE_TYPES = ["Box","Envelope","Packs","Tubes","Certified","Sensitive","Critical"]

# ---------- Send (create package) ----------

@bp.route("/next-id")
@login_required
def get_next_id():
    """Get next package ID for a given type."""
    pkg_type = request.args.get('type', 'Box')
    next_id = peek_next_package_id(pkg_type)
    return jsonify({'next_id': next_id})


@bp.route("/", methods=["GET","POST"], endpoint="index")
@login_required
@require_cap("can_send")
def page():
    """Send package - Create shipping records."""
    ensure_schema()
    today = datetime.date.today().isoformat()
    default_pkg_type = "Box"
    suggested_checkin = peek_next_checkin_id()
    suggested_package = peek_next_package_id(default_pkg_type)

    if request.method == "POST":
        # Get form data
        checkin_date = request.form.get("CheckInDate", today)
        checkin_id = next_checkin_id()
        pkg_type = request.form.get("PackageType", default_pkg_type)
        package_id = next_package_id(pkg_type)
        recipient_name = request.form.get("RecipientName", "")
        tracking = request.form.get("TrackingNumber", "")
        address_line1 = request.form.get("AddressLine1", "")
        address_line2 = request.form.get("AddressLine2", "")
        city = request.form.get("City", "")
        state = request.form.get("State", "")
        zip_code = request.form.get("ZipCode", "")
        
        # Build full address
        address_parts = [address_line1, address_line2, city, state, zip_code]
        full_address = ", ".join([p for p in address_parts if p])
        
        # Get user info
        cu = current_user()
        user_location = get_user_location(cu)
        submitter_name = f"{cu.get('first_name', '')} {cu.get('last_name', '')}".strip() or cu.get('username', 'Unknown')
        
        # Guess carrier from tracking number
        carrier = guess_carrier(tracking) if tracking else "Unknown"
        
        try:
            # Insert into package_manifest
            with get_db_connection("send") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO package_manifest (
                        checkin_date, checkin_id, package_type, package_id,
                        recipient_name, recipient_address, tracking_number,
                        carrier, submitter_name, location, created_by
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    checkin_date, checkin_id, pkg_type, package_id,
                    recipient_name, full_address, tracking,
                    carrier, submitter_name, user_location, cu['id']
                ))
                conn.commit()
                cursor.close()
            
            # Record audit
            record_audit(cu, "create_package", "send", 
                        f"Created package {package_id} for {recipient_name}")
            
            # Show success message
            flash(f"✅ Package {package_id} created successfully!", "success")
            
            # Redirect to clear form (POST-REDIRECT-GET pattern)
            return redirect(url_for("send.index"))
            
        except Exception as e:
            flash(f"❌ Error creating package: {str(e)}", "danger")
            return redirect(url_for("send.index"))
    
    # GET request
    return render_template(
        "send/index.html",
        active="send",
        today=today,
        suggested_checkin=suggested_checkin,
        suggested_package=suggested_package,
        package_types=PACKAGE_TYPES
    )


# ---------- Tracking ----------
@bp.route("/tracking", methods=["GET","POST"])
@login_required
@require_cap("can_send")
def tracking():
    """Track packages by tracking number."""
    ctx = {
        "active": "send", 
        "page": "tracking",
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