# app/core/config.py
"""
Application configuration.
All environment-driven settings live here, keeping app.py lean.
"""
import os


def configure_app(app):
    """Load all configuration into the Flask app instance."""
    _is_production = os.environ.get('FLASK_ENV') == 'production'
    _secret_key = os.environ.get('SECRET_KEY')
    if _is_production and not _secret_key:
        raise RuntimeError(
            "SECRET_KEY environment variable must be set in production. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    if not _secret_key:
        _secret_key = 'dev-only-insecure-key-NOT-for-production'

    app.config.update(
        SECRET_KEY=_secret_key,
        SESSION_COOKIE_SECURE=_is_production,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=28800,  # 8 hours
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

        # ── S3 — Fulfillment file storage ─────────────────────────
        # Set S3_FULFILLMENT_BUCKET via `eb setenv S3_FULFILLMENT_BUCKET=<bucket-name>`
        # When unset the app falls back to local filesystem storage (dev only).
        S3_FULFILLMENT_BUCKET=os.environ.get('S3_FULFILLMENT_BUCKET', ''),
        S3_BUCKET_REGION=os.environ.get('S3_BUCKET_REGION', 'us-east-1'),
    )

    # Ensure upload directory exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
