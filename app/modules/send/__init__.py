from flask import Blueprint

bp = Blueprint("send", __name__, template_folder="templates", url_prefix="/send")

# Import routes so decorators are registered
# NOTE: Only import views.py since it contains all main routes including API endpoints
from . import views

# Conditional imports for additional modules if they exist
try:
    from . import reports
except ImportError:
    pass

try:
    from . import sync_routes
except ImportError:
    pass

# DO NOT import 'api' module - it likely duplicates routes from views.py