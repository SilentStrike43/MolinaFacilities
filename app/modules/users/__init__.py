# app/modules/users/__init__.py
from flask import Blueprint
bp = Blueprint("users", __name__, template_folder="templates", static_folder="static")
from . import views
