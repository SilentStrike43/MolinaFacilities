# app/modules/admin/__init__.py
from flask import Blueprint
bp = Blueprint("admin", __name__, template_folder="templates", static_folder="static")
from . import views
