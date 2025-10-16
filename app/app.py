# app/app.py
from flask import Flask, render_template, redirect, url_for, request, g
import os
from app.core.auth import current_user, record_audit
from app.core.ui import inject_globals

def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY","facilities-key")
    app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="None")

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