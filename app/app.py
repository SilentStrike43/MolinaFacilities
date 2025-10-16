# app/app.py
from __future__ import annotations
import os, importlib
from flask import Flask, render_template, redirect, url_for, g, request
from app.common.security import current_user as _cu

# DB/bootstrap – optional while you finish refactors
try:
    from app.common.storage import init_all_dbs  # new name if present
except Exception:
    init_all_dbs = None

try:
    from app.common.users import ensure_user_schema, ensure_first_sysadmin, record_audit
except Exception:
    def ensure_user_schema(): ...
    def ensure_first_sysadmin(): ...
    def record_audit(*_a, **_k): ...

    # app/modules/tracking/views.py
from flask import Blueprint, redirect, url_for
tracking_bp = Blueprint("tracking", __name__)
@tracking_bp.route("/")
def index():
    return redirect(url_for("send.tracking"))

APP_VERSION = os.environ.get("APP_VERSION", "0.3.2_BETA")
BRAND_TEAL  = os.environ.get("BRAND_TEAL", "#00A3AD")

def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "facilities-key")
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="None",
    )

    # user + globals for templates
    @app.before_request
    def _bind_user():
        g._cu = _cu()

    @app.context_processor
    def _inject():
        return {"cu": _cu(), "APP_VERSION": APP_VERSION, "BRAND_TEAL": BRAND_TEAL}

    # audit minimal writes
    @app.after_request
    def _audit_posts(resp):
        try:
            u = _cu()
            if u and request.method in ("POST", "DELETE"):
                p = request.path
                if not p.startswith("/static") and p not in ("/healthz",):
                    record_audit(u, f"{request.method} {resp.status_code}", "web", f"path={p}")
        except Exception:
            pass
        return resp

    # DB boot (best-effort)
    try:
        if init_all_dbs:
            init_all_dbs()
    except Exception:
        pass
    try:
        ensure_user_schema()
        ensure_first_sysadmin()
    except Exception:
        pass

    # Resilient blueprint registration
    def _register(module_path: str, url_prefix: str, *bp_attr_candidates: str):
        try:
            mod = importlib.import_module(module_path)
        except ModuleNotFoundError:
            return False
        bp = None
        for name in bp_attr_candidates or ("bp",):
            bp = getattr(mod, name, None)
            if bp is not None:
                break
        if bp is None:
            return False
        app.register_blueprint(bp, url_prefix=url_prefix)
        return True

    # Register only the new, module-local blueprints.
    # (No legacy 'tracking' import — tracking lives under Send now.)
    _register("app.modules.auth.views",        "/auth",        "auth_bp", "bp")
    _register("app.modules.send.views",        "/send",        "send_bp", "bp")
    _register("app.modules.inventory.views",   "/inventory",   "inventory_bp", "bp")
    _register("app.modules.fulfillment.views", "/fulfillment", "fulfillment_bp", "bp")
    _register("app.modules.users.views",       "/users",       "users_bp", "bp")
    _register("app.modules.admin.views",       "/admin",       "admin_bp", "bp")
    # Keep this only if you still have a separate reports module
    _register("app.modules.reports.views",     "/reports",     "reports_bp", "bp")
    _register("app.modules.tracking.views", "/tracking", "tracking_bp", "bp")

    @app.route("/")
    def home():
        if not _cu():
            return redirect(url_for("auth.login"))
        return render_template("blank.html",
                               title="Facilities Portal",
                               message="Select a module from the navigation bar.")

    @app.route("/healthz")
    def health():
        return {"ok": True}, 200

    return app

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5955"))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host=host, port=port, debug=debug)