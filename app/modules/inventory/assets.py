"""
Inventory assets - AZURE SQL ONLY
"""
from app.core.database import get_db_connection


def _conn():
    """Get database connection - Azure SQL only."""
    return get_db_connection("inventory").__enter__()


def ensure_schema():
    """Schema is managed by Azure SQL migrations, not application code."""
    pass


def db():
    return _conn()
