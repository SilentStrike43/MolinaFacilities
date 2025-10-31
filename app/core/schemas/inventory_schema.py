# app/core/schemas/inventory_schema.py
"""Inventory module schema - using inventory. schema prefix"""

INVENTORY_SCHEMA = """
-- Create schema if it doesn't exist
IF NOT EXISTS (SELECT * FROM sys.schemas WHERE name = 'inventory')
BEGIN
    EXEC('CREATE SCHEMA inventory')
END
GO

-- Assets table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'assets' AND schema_id = SCHEMA_ID('inventory'))
BEGIN
    CREATE TABLE inventory.assets (
        id INT IDENTITY(1,1) PRIMARY KEY,
        sku NVARCHAR(100) UNIQUE,
        product NVARCHAR(255) NOT NULL,
        uom NVARCHAR(50) DEFAULT 'EA',
        location NVARCHAR(255),
        qty_on_hand INT DEFAULT 0,
        manufacturer NVARCHAR(255),
        part_number NVARCHAR(255),
        serial_number NVARCHAR(255),
        pii NVARCHAR(MAX),
        notes NVARCHAR(MAX),
        status NVARCHAR(50) DEFAULT 'active',
        created_at DATETIME2 DEFAULT GETDATE(),
        updated_at DATETIME2 DEFAULT GETDATE()
    )
    
    CREATE INDEX idx_assets_sku ON inventory.assets(sku)
    CREATE INDEX idx_assets_product ON inventory.assets(product)
    CREATE INDEX idx_assets_status ON inventory.assets(status)
    CREATE INDEX idx_assets_location ON inventory.assets(location)
END
GO

-- Asset movements table (ledger)
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'asset_movements' AND schema_id = SCHEMA_ID('inventory'))
BEGIN
    CREATE TABLE inventory.asset_movements (
        id INT IDENTITY(1,1) PRIMARY KEY,
        asset_id INT NOT NULL,
        movement_type NVARCHAR(50) NOT NULL,
        quantity INT NOT NULL,
        qty_before INT NOT NULL,
        qty_after INT NOT NULL,
        performed_by NVARCHAR(255),
        notes NVARCHAR(MAX),
        timestamp DATETIME2 DEFAULT GETDATE(),
        FOREIGN KEY (asset_id) REFERENCES inventory.assets(id) ON DELETE CASCADE
    )
    
    CREATE INDEX idx_movements_asset_id ON inventory.asset_movements(asset_id)
    CREATE INDEX idx_movements_timestamp ON inventory.asset_movements(timestamp)
    CREATE INDEX idx_movements_type ON inventory.asset_movements(movement_type)
END
GO

-- Inventory transactions table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'inventory_transactions' AND schema_id = SCHEMA_ID('inventory'))
BEGIN
    CREATE TABLE inventory.inventory_transactions (
        id INT IDENTITY(1,1) PRIMARY KEY,
        transaction_date DATE NOT NULL,
        transaction_type NVARCHAR(50) NOT NULL,
        asset_id INT,
        sku NVARCHAR(100),
        item_type NVARCHAR(255),
        manufacturer NVARCHAR(255),
        product_name NVARCHAR(255),
        submitter_name NVARCHAR(255),
        quantity INT NOT NULL,
        notes NVARCHAR(MAX),
        part_number NVARCHAR(255),
        serial_number NVARCHAR(255),
        location NVARCHAR(255),
        status NVARCHAR(50) DEFAULT 'completed',
        created_at DATETIME2 DEFAULT GETDATE()
    )
    
    CREATE INDEX idx_transactions_date ON inventory.inventory_transactions(transaction_date)
    CREATE INDEX idx_transactions_asset_id ON inventory.inventory_transactions(asset_id)
    CREATE INDEX idx_transactions_sku ON inventory.inventory_transactions(sku)
END
GO
"""


def initialize_inventory_schema():
    """Initialize inventory module schema."""
    from app.core.database import execute_script
    execute_script("core", INVENTORY_SCHEMA)  # ← Changed from "inventory" to "core"
    print("   ✅ inventory schema tables created")