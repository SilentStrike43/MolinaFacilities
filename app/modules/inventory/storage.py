# app/modules/inventory/storage.py
"""
Inventory storage - PostgreSQL Edition
"""
from app.core.database import get_db_connection


def ensure_schema():
    """Ensure inventory schema exists."""
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        
        # Create inventory_transactions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS inventory_transactions (
                id SERIAL PRIMARY KEY,
                transaction_date DATE NOT NULL,
                transaction_type VARCHAR(50) NOT NULL,
                asset_id INTEGER,
                sku VARCHAR(100),
                item_type VARCHAR(255),
                manufacturer VARCHAR(255),
                product_name VARCHAR(255),
                submitter_name VARCHAR(255),
                quantity INTEGER NOT NULL,
                notes TEXT,
                part_number VARCHAR(255),
                serial_number VARCHAR(255),
                location VARCHAR(255),
                status VARCHAR(50) DEFAULT 'completed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_transactions_date 
            ON inventory_transactions(transaction_date)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_transactions_asset_id 
            ON inventory_transactions(asset_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_transactions_sku 
            ON inventory_transactions(sku)
        """)
        
        cursor.close()
        print("✓ Inventory schema initialized")


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