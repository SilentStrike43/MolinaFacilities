# app/app.py
from flask import Flask, render_template, redirect, url_for
import os

app = Flask(__name__)
app.secret_key = "facilities-key"  # flashes/sessions

# --- init DBs / seed first account ---
from app.common.storage import init_all_dbs
from app.common.users import ensure_user_schema, ensure_first_sysadmin
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

app.register_blueprint(auth_bp,      url_prefix="/auth")
app.register_blueprint(mail_bp,      url_prefix="/mail")
app.register_blueprint(inventory_bp, url_prefix="/inventory")
app.register_blueprint(reports_bp,   url_prefix="/reports")
app.register_blueprint(admin_bp,     url_prefix="/admin")
app.register_blueprint(tracking_bp,  url_prefix="/tracking")
app.register_blueprint(users_bp,     url_prefix="/users")

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

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5955"))
    app.run(host=host, port=port, debug=True)