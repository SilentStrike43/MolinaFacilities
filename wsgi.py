# wsgi.py
"""
WSGI entry point for gunicorn and Azure App Service.

This module is intentionally separate from app/app.py so that
`application = create_app()` is only executed by the WSGI server —
never on a bare `import app.app`.

gunicorn usage:
    gunicorn wsgi:application

Azure App Service:
    Set startup command to:  gunicorn --bind=0.0.0.0:8000 wsgi:application
"""
from app.app import create_app

application = create_app()
