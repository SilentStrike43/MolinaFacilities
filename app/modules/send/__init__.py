from flask import Blueprint

bp = Blueprint("send", __name__, template_folder="templates", url_prefix="/send")

# Import routes so decorators are registered
from . import views
from . import api

# Conditional imports for additional modules if they exist
try:
    from . import reports
except ImportError:
    pass

try:
    from . import sync_routes
except ImportError:
    pass