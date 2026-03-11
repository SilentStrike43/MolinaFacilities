# app/modules/inventory/storage.py
"""
Inventory storage - PostgreSQL Edition
"""
import logging
from app.core.database import get_db_connection

logger = logging.getLogger(__name__)


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

        # Create vendor_book table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vendor_book (
                id SERIAL PRIMARY KEY,
                instance_id INTEGER NOT NULL,
                contact_name VARCHAR(255),
                company VARCHAR(255) NOT NULL,
                address TEXT,
                phone VARCHAR(50),
                email VARCHAR(255),
                industry_type VARCHAR(100),
                notes TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                use_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_vendor_book_instance
            ON vendor_book(instance_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_vendor_book_company
            ON vendor_book(company)
        """)

        # Migrations for existing tables
        for migration_sql in [
            "ALTER TABLE assets ADD COLUMN IF NOT EXISTS vendor_id INTEGER",
        ]:
            try:
                cursor.execute(migration_sql)
            except Exception:
                pass

        cursor.close()

    logger.info("Inventory schema initialized")
