# app/app.py  (header/boot section only)
from flask import Flask, render_template, redirect, url_for, g, request
import os
from app.common.security import current_user as _cu
from app.common.storage import init_all_dbs
from app.common.users import ensure_user_schema, ensure_first_sysadmin, record_audit

APP_VERSION = "0.3.2_BETA"

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "facilities-key")
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="None",
)

# make user and version available to templates
@app.before_request
def _bind_user():
    g._cu = _cu()

@app.context_processor
def _inject():
    return {"cu": _cu(), "APP_VERSION": APP_VERSION}

# minimal *useful* audit: log every authenticated POST (create/update/delete/exports)
@app.after_request
def _audit_posts(resp):
    try:
        u = _cu()
        if u and request.method in ("POST", "DELETE"):
            path = request.path
            # ignore static and health
            if not path.startswith("/static") and path not in ("/healthz",):
                record_audit(u, f"{request.method} {resp.status_code}", "web", f"path={path}")
    except Exception:
        pass
    return resp

# DB init
init_all_dbs()
ensure_user_schema()
ensure_first_sysadmin()

# --- Blueprints (existing + new) ---
from app.modules.auth.views import auth_bp
from app.modules.mail.views import mail_bp
from app.modules.inventory.views import inventory_bp
from app.modules.reports.views import reports_bp
from app.modules.admin.views import admin_bp
from app.modules.tracking.views import tracking_bp
from app.modules.users.views import users_bp
from app.modules.fulfillment.views import fulfillment_bp   # NEW

app.register_blueprint(auth_bp,      url_prefix="/auth")
app.register_blueprint(mail_bp,      url_prefix="/mail")
app.register_blueprint(inventory_bp, url_prefix="/inventory")
app.register_blueprint(reports_bp,   url_prefix="/reports")
app.register_blueprint(admin_bp,     url_prefix="/admin")
app.register_blueprint(tracking_bp,  url_prefix="/tracking")
app.register_blueprint(users_bp,     url_prefix="/users")
app.register_blueprint(fulfillment_bp, url_prefix="/fulfillment")  # NEW

@app.route("/")
def home():
    # if not logged in, go to login
    from app.common.security import current_user
    if not current_user():
        return redirect(url_for("auth.login"))
    return render_template("blank.html",
                           title="Facilities Portal",
                           message="Select a module from the navigation bar.")

@app.route("/healthz")
def health():
    return {"ok": True}, 200

BRAND_TEAL = os.environ.get("BRAND_TEAL", "#00A3AD")  # DO NOT TOUCH OR I'LL KILL YOU!

@app.context_processor
def _inject():
    return {
        "cu": _cu(),
        "0.2.7_BETA": APP_VERSION,
        "BRAND_TEAL": BRAND_TEAL,
    }

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5955"))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host=host, port=port, debug=debug)