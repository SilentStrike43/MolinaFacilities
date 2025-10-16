# app/common/assets.py
from __future__ import annotations
from .storage import assets_db, ensure_assets_schema

def get_conn():
    """Legacy helper some ledger code imports."""
    return assets_db()

# keep a public ensure function so older imports still work
def ensure_assets_schema_if_needed():
    ensure_assets_schema()
