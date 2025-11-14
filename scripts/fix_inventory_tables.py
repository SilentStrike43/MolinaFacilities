from app.core.database import get_db_connection

# Fix inventory_reports table
with get_db_connection("inventory") as conn:
    cursor = conn.cursor()
    
    # Drop the old table
    cursor.execute("DROP TABLE IF EXISTS inventory_reports CASCADE")
    print("✅ Dropped old inventory_reports table")
    
    # Recreate with correct schema
    cursor.execute("""
        CREATE TABLE inventory_reports (
            id SERIAL PRIMARY KEY,
            instance_id INTEGER,
            report_type VARCHAR(100),
            sku VARCHAR(255),
            asset_name VARCHAR(255),
            quantity_change INTEGER,
            new_quantity INTEGER,
            location VARCHAR(100),
            notes TEXT,
            performed_by VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ts_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("✅ Created new inventory_reports table")
    
    # Create index
    cursor.execute("CREATE INDEX idx_reports_ts ON inventory_reports(ts_utc DESC)")
    print("✅ Created index")
    
    cursor.close()

exit()