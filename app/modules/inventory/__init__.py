# app/modules/inventory/__init__.py
from flask import Blueprint
from .views import inventory_bp  # re-export for app.register_blueprint
from .ledger_views import asset_ledger_bp

__all__ = ["inventory_bp", "asset_ledger_bp"]

bp = Blueprint("inventory", __name__, template_folder="templates", static_folder="static")
from . import views, ledger, reports  # registers routes