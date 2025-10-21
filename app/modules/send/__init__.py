from flask import Blueprint

bp = Blueprint("send", __name__, template_folder="templates")

# Ensure route modules are imported so their @bp.route decorators run
from . import views, reports
