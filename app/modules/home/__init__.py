# app/modules/home/__init__.py
"""
Home module - Default landing page for all users
All users have access to this module by default (G0 permission)
"""

from flask import Blueprint

bp = Blueprint("home", __name__, url_prefix="/home", template_folder="templates")

from app.modules.home import views