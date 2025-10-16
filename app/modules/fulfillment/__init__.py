# app/modules/fulfillment/__init__.py
from flask import Blueprint
bp = Blueprint("fulfillment", __name__, template_folder="templates", static_folder="static")
from . import views, reports  # routes