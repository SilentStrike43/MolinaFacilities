# app/modules/mail/__init__.py
from flask import Blueprint
from .views import send_bp  # re-export for app.register_blueprint
bp = Blueprint("mail", __name__, template_folder="templates", static_folder="static")
from . import views, reports, tracking   # routes