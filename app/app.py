# app/app.py
from flask import Flask, render_template, redirect, url_for, request, g
import os
from app.core.auth import current_user, record_audit
from app.core.ui import inject_globals

# app/app.py
def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "facilities-key")

    # In dev (no HTTPS), do not mark the cookie Secure, or it won't stick.
    SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "0") == "1"
    app.config.update(
        SESSION_COOKIE_SECURE=SECURE_COOKIES,              # set to True only behind HTTPS/reverse proxy
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE=("None" if SECURE_COOKIES else "Lax"),
    )

    # template globals
    app.context_processor(inject_globals)

    @app.before_request
    def _bind_user():
        g._cu = current_user()

    @app.after_request
    def _audit_posts(resp):
        try:
            u = current_user()
            if u and request.method in ("POST","DELETE"):
                p = request.path
                if not p.startswith("/static") and p not in ("/healthz",):
                    record_audit(u, f"{request.method} {resp.status_code}", "web", f"path={p}")
        except Exception:
            pass
        return resp

    # ---- Blueprints (new-only) ----
    from app.modules.auth.views import bp as auth_bp
    from app.modules.send.views import bp as send_bp
    from app.modules.inventory.views import bp as inventory_bp
    from app.modules.inventory.ledger_views import bp as asset_ledger_bp
    from app.modules.fulfillment.views import bp as fulfillment_bp
    from app.modules.users.views import bp as users_bp
    from app.modules.admin.views import bp as admin_bp
    # (if you split insights into module pages, register those blueprints too)

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(send_bp, url_prefix="/send")
    app.register_blueprint(inventory_bp, url_prefix="/inventory")
    app.register_blueprint(asset_ledger_bp, url_prefix="/asset-ledger")
    app.register_blueprint(fulfillment_bp, url_prefix="/fulfillment")
    app.register_blueprint(users_bp, url_prefix="/users")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    from app.modules.auth.models import ensure_user_schema, ensure_first_sysadmin
    ensure_user_schema()
    ensure_first_sysadmin()  # reads ADMIN_PASSWORD env var if set (see below)

    @app.get("/debug/whoami")
    def whoami():
        from flask import session
        return {
            "uid": session.get("uid"),
            "username": session.get("username")
        }, 200

    @app.route("/")
    def home():
        if not current_user():
            return redirect(url_for("auth.login"))
        return render_template("blank.html", title="Facilities Portal", message="Select a module from the navigation bar.")

    @app.route("/healthz")
    def health(): return {"ok": True}, 200

    return app

# dev entry
if __name__ == "__main__":
    app = create_app()
    app.run(host=os.environ.get("HOST","127.0.0.1"),
            port=int(os.environ.get("PORT","5955")),
            debug=os.environ.get("FLASK_DEBUG","1")=="1")