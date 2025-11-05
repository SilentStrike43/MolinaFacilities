# app/modules/inventory/models.py
"""
Inventory models - PostgreSQL Edition
"""
from app.core.database import get_db_connection


def ensure_schema():
    """Ensure inventory schema exists."""
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        
        # Create asset_ledger table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS asset_ledger (
                id SERIAL PRIMARY KEY,
                asset_id INTEGER NOT NULL,
                action VARCHAR(50) NOT NULL,
                qty INTEGER NOT NULL,
                username VARCHAR(255),
                note TEXT,
                ts_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ledger_asset 
            ON asset_ledger(asset_id)
        """)
        
        cursor.close()


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
        return [dict(row) for row in rows]


def get_asset(asset_id: int):
    """Get a single asset by ID."""
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM assets WHERE id=%s", (asset_id,))
        row = cursor.fetchone()
        cursor.close()
        return dict(row) if row else None


def record_movement(asset_id: int, action: str, qty: int, username: str, note: str = ""):
    """Record asset movement in ledger."""
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        
        # Insert movement
        cursor.execute("""
            INSERT INTO asset_ledger(asset_id, action, qty, username, note, ts_utc)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        """, (asset_id, action, qty, username, note))
        
        # Update asset quantity
        if action == "CHECKIN":
            cursor.execute("UPDATE assets SET qty_on_hand = qty_on_hand + %s WHERE id = %s", (qty, asset_id))
        elif action == "CHECKOUT":
            cursor.execute("UPDATE assets SET qty_on_hand = qty_on_hand - %s WHERE id = %s", (qty, asset_id))
        elif action == "ADJUST":
            cursor.execute("UPDATE assets SET qty_on_hand = %s WHERE id = %s", (qty, asset_id))
        
        cursor.close()


def list_movements(asset_id: int = None):
    """List asset movements."""
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        
        if asset_id:
            cursor.execute("""
                SELECT * FROM asset_ledger 
                WHERE asset_id = %s 
                ORDER BY ts_utc DESC
            """, (asset_id,))
        else:
            cursor.execute("""
                SELECT * FROM asset_ledger 
                ORDER BY ts_utc DESC
                LIMIT 100
            """)
        
        rows = cursor.fetchall()
        cursor.close()
        return [dict(row) for row in rows]