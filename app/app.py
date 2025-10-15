# app/app.py
from __future__ import annotations
import os
from flask import Flask, render_template, redirect, url_for, g, request

from app.common.security import current_user as _cu
from app.common.storage import init_all_dbs
from app.common.users import ensure_user_schema, ensure_first_sysadmin, record_audit

APP_VERSION = "0.3.2_BETA"
BRAND_TEAL = os.environ.get("BRAND_TEAL", "#00A3AD")  # corporate teal default

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "facilities-key")
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="None",
)

# --- Template globals & request user binding -------------------------------

@app.before_request
def _bind_user():
    # always expose the current user on g
    g._cu = _cu()

@app.context_processor
def _inject_globals():
    # single, unified context processor
    return {
        "cu": _cu(),
        "APP_VERSION": APP_VERSION,
        "BRAND_TEAL": BRAND_TEAL,
    }

# --- Minimal but useful auditing -------------------------------------------

@app.after_request
def _audit_posts(resp):
    try:
        u = _cu()
        if u and request.method in ("POST", "DELETE"):
            path = request.path
            if not path.startswith("/static") and path not in ("/healthz",):
                record_audit(u, f"{request.method} {resp.status_code}", "web", f"path={path}")
    except Exception:
        # never break responses because of audit logging
        pass
    return resp

# --- DB bootstrap -----------------------------------------------------------

init_all_dbs()
ensure_user_schema()
ensure_first_sysadmin()

# --- Blueprints -------------------------------------------------------------

from app.modules.auth.views import auth_bp
from app.modules.mail.views import mail_bp
from app.modules.inventory.views import inventory_bp
from app.modules.reports.views import reports_bp
from app.modules.admin.views import admin_bp
from app.modules.tracking.views import tracking_bp
from app.modules.users.views import users_bp
from app.modules.fulfillment.views import fulfillment_bp

# Import the ledger routes so they attach to inventory_bp (no separate BP)
# The module defines routes on inventory_bp at import time.
from app.modules.inventory import ledger_views  # noqa: F401

# Optional: fulfillment insights routes if present
try:
    from app.modules.reports.fulfillment_views import reports_f_bp
except Exception:
    reports_f_bp = None

app.register_blueprint(auth_bp,      url_prefix="/auth")
app.register_blueprint(mail_bp,      url_prefix="/mail")
app.register_blueprint(inventory_bp, url_prefix="/inventory")
app.register_blueprint(reports_bp,   url_prefix="/reports")
app.register_blueprint(admin_bp,     url_prefix="/admin")
app.register_blueprint(tracking_bp,  url_prefix="/tracking")
app.register_blueprint(users_bp,     url_prefix="/users")
app.register_blueprint(fulfillment_bp, url_prefix="/fulfillment")
if reports_f_bp:
    app.register_blueprint(reports_f_bp)

# --- Routes ----------------------------------------------------------------

@app.route("/")
def home():
    if not _cu():
        return redirect(url_for("auth.login"))
    return render_template(
        "blank.html",
        title="Facilities Portal",
        message="Use the tabs above to open a module."
    )

@app.route("/healthz")
def health():
    return {"ok": True}, 200

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5955"))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host=host, port=port, debug=debug)