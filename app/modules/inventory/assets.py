# app/modules/inventory/assets.py
"""
Inventory assets - PostgreSQL Edition
"""
from app.core.database import get_db_connection


def _conn():
    """Get database connection."""
    return get_db_connection("inventory").__enter__()


def ensure_schema():
    """Schema creation disabled - tables created via complete_schema_setup.py"""
    pass 