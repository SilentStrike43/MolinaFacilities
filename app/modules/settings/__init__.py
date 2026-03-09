from flask import Blueprint

bp = Blueprint("settings", __name__, url_prefix="/settings", template_folder="templates")

from . import views  # noqa: F401, E402
