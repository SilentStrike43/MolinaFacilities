# app/core/config.py
"""
Application configuration.
All environment-driven settings live here, keeping app.py lean.
"""
import os


def configure_app(app):
    """Load all configuration into the Flask app instance."""
    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-secret-key-PLEASE-change-in-production-12345'),
        SESSION_COOKIE_SECURE=os.environ.get('FLASK_ENV') == 'production',
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=604800,
        MAX_CONTENT_LENGTH=50 * 1024 * 1024,
        UPLOAD_FOLDER=os.environ.get(
            'UPLOAD_FOLDER',
            os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'uploads')
        ),
        ENV=os.environ.get('FLASK_ENV', 'development'),
        LOG_LEVEL=os.environ.get('LOG_LEVEL', 'INFO'),

        # ── Carrier API ──────────────────────────────────────────
        USPS_CONSUMER_KEY=os.environ.get('USPS_CONSUMER_KEY'),
        USPS_CONSUMER_SECRET=os.environ.get('USPS_CONSUMER_SECRET'),
        USPS_API_URL=os.environ.get('USPS_API_URL', 'https://api.usps.com'),

        UPS_CLIENT_ID=os.environ.get('UPS_CLIENT_ID'),
        UPS_CLIENT_SECRET=os.environ.get('UPS_CLIENT_SECRET'),
        UPS_ACCOUNT_NUMBER=os.environ.get('UPS_ACCOUNT_NUMBER'),
        UPS_API_URL=os.environ.get('UPS_API_URL', 'https://onlinetools.ups.com/api'),

        FEDEX_SHIP_API_KEY=os.environ.get('FEDEX_SHIP_API_KEY'),
        FEDEX_SHIP_SECRET_KEY=os.environ.get('FEDEX_SHIP_SECRET_KEY'),
        FEDEX_ACCOUNT_NUMBER=os.environ.get('FEDEX_ACCOUNT_NUMBER'),
        FEDEX_TRACK_API_KEY=os.environ.get('FEDEX_TRACK_API_KEY'),
        FEDEX_TRACK_SECRET_KEY=os.environ.get('FEDEX_TRACK_SECRET_KEY'),
        FEDEX_API_URL=os.environ.get('FEDEX_API_URL', 'https://apis.fedex.com'),

        # ── Tracking ─────────────────────────────────────────────
        TRACKING_UPDATE_INTERVAL=int(os.environ.get('TRACKING_UPDATE_INTERVAL', 4)),
        TRACKING_CACHE_DURATION=int(os.environ.get('TRACKING_CACHE_DURATION', 30)),
        FEDEX_SYNC_ENABLED=os.environ.get('FEDEX_SYNC_ENABLED', 'false').lower() == 'true',
        FEDEX_SYNC_INTERVAL=int(os.environ.get('FEDEX_SYNC_INTERVAL', 30)),
    )

    # Ensure upload directory exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
