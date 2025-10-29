"""
Inventory storage - AZURE SQL ONLY
"""
from app.core.database import get_db_connection


def ensure_schema():
    """Schema is managed by Azure SQL migrations, not application code."""
    pass


def inventory_db():
    """
    DEPRECATED: Legacy compatibility function.
    Returns a connection but caller must manage it properly.
    
    New code should use: with get_db_connection("inventory") as conn:
    """
    return get_db_connection("inventory").__enter__()


def insights_db():
    """
    DEPRECATED: Legacy compatibility function.
    Returns a connection but caller must manage it properly.
    
    New code should use: with get_db_connection("inventory") as conn:
    """
    return get_db_connection("inventory").__enter__()