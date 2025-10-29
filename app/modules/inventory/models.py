"""
Inventory models - AZURE SQL ONLY
"""
from app.core.database import get_db_connection


def ensure_schema():
    """Schema is managed by Azure SQL migrations, not application code."""
    pass


def list_assets():
    """Get all assets from the database."""
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM assets 
            WHERE status != 'deleted'
            ORDER BY product, sku
        """)
        rows = cursor.fetchall()
        cursor.close()
        return rows


def get_asset(asset_id: int):
    """Get a single asset by ID."""
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM assets WHERE id=?", (asset_id,))
        row = cursor.fetchone()
        cursor.close()
        return row


def record_movement(asset_id: int, action: str, qty: int, username: str, note: str = ""):
    """Record asset movement in ledger."""
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        
        # Insert movement
        cursor.execute("""
            INSERT INTO asset_ledger(asset_id, action, qty, username, note, ts_utc)
            VALUES (?, ?, ?, ?, ?, GETUTCDATE())
        """, (asset_id, action, qty, username, note))
        
        # Update asset quantity
        if action == "CHECKIN":
            cursor.execute("UPDATE assets SET qty_on_hand = qty_on_hand + ? WHERE id = ?", (qty, asset_id))
        elif action == "CHECKOUT":
            cursor.execute("UPDATE assets SET qty_on_hand = qty_on_hand - ? WHERE id = ?", (qty, asset_id))
        elif action == "ADJUST":
            cursor.execute("UPDATE assets SET qty_on_hand = ? WHERE id = ?", (qty, asset_id))
        
        conn.commit()
        cursor.close()


def list_movements(asset_id: int = None):
    """List asset movements."""
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        
        if asset_id:
            cursor.execute("""
                SELECT * FROM asset_ledger 
                WHERE asset_id = ? 
                ORDER BY ts_utc DESC
            """, (asset_id,))
        else:
            cursor.execute("""
                SELECT TOP 100 * FROM asset_ledger 
                ORDER BY ts_utc DESC
            """)
        
        rows = cursor.fetchall()
        cursor.close()
        return rows