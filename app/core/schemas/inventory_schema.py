# app/core/schemas/inventory_schema.py
"""
Inventory module schema - Assets, stock, movements, ledger
"""

INVENTORY_SCHEMA = """
-- Assets table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'assets')
BEGIN
    CREATE TABLE assets (
        id INT IDENTITY(1,1) PRIMARY KEY,
        asset_code NVARCHAR(100) UNIQUE,
        name NVARCHAR(255) NOT NULL,
        description NVARCHAR(MAX),
        category NVARCHAR(100),
        subcategory NVARCHAR(100),
        manufacturer NVARCHAR(255),
        model NVARCHAR(255),
        serial_number NVARCHAR(255),
        quantity INT DEFAULT 0,
        min_quantity INT DEFAULT 0,
        max_quantity INT,
        unit NVARCHAR(50),
        unit_cost DECIMAL(10,2),
        location NVARCHAR(255),
        building NVARCHAR(100),
        room NVARCHAR(100),
        status NVARCHAR(50) DEFAULT 'active',
        condition_rating NVARCHAR(50),
        purchase_date DATE,
        warranty_expiration DATE,
        last_maintenance DATE,
        notes NVARCHAR(MAX),
        image_url NVARCHAR(500),
        created_by INT NOT NULL,
        created_at DATETIME2 DEFAULT GETDATE(),
        updated_at DATETIME2 DEFAULT GETDATE()
    )
    
    CREATE INDEX idx_assets_asset_code ON assets(asset_code)
    CREATE INDEX idx_assets_name ON assets(name)
    CREATE INDEX idx_assets_category ON assets(category)
    CREATE INDEX idx_assets_status ON assets(status)
    CREATE INDEX idx_assets_location ON assets(location)
END
GO

-- Inventory ledger table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'inventory_ledger')
BEGIN
    CREATE TABLE inventory_ledger (
        id INT IDENTITY(1,1) PRIMARY KEY,
        asset_id INT NOT NULL,
        transaction_type NVARCHAR(50) NOT NULL,
        quantity INT NOT NULL,
        quantity_before INT,
        quantity_after INT,
        from_location NVARCHAR(255),
        to_location NVARCHAR(255),
        reference_number NVARCHAR(100),
        reason NVARCHAR(255),
        notes NVARCHAR(MAX),
        performed_by INT NOT NULL,
        approved_by INT,
        timestamp DATETIME2 DEFAULT GETDATE(),
        FOREIGN KEY (asset_id) REFERENCES assets(id)
    )
    
    CREATE INDEX idx_ledger_asset_id ON inventory_ledger(asset_id)
    CREATE INDEX idx_ledger_timestamp ON inventory_ledger(timestamp)
    CREATE INDEX idx_ledger_transaction_type ON inventory_ledger(transaction_type)
END
GO

-- Asset maintenance table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'asset_maintenance')
BEGIN
    CREATE TABLE asset_maintenance (
        id INT IDENTITY(1,1) PRIMARY KEY,
        asset_id INT NOT NULL,
        maintenance_type NVARCHAR(100) NOT NULL,
        description NVARCHAR(MAX),
        performed_by NVARCHAR(255),
        cost DECIMAL(10,2),
        scheduled_date DATE,
        completed_date DATE,
        next_maintenance_date DATE,
        status NVARCHAR(50),
        notes NVARCHAR(MAX),
        created_by INT NOT NULL,
        created_at DATETIME2 DEFAULT GETDATE(),
        FOREIGN KEY (asset_id) REFERENCES assets(id)
    )
    
    CREATE INDEX idx_maintenance_asset_id ON asset_maintenance(asset_id)
    CREATE INDEX idx_maintenance_scheduled_date ON asset_maintenance(scheduled_date)
END
GO

-- Stock alerts table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'stock_alerts')
BEGIN
    CREATE TABLE stock_alerts (
        id INT IDENTITY(1,1) PRIMARY KEY,
        asset_id INT NOT NULL,
        alert_type NVARCHAR(50) NOT NULL,
        threshold_value INT,
        current_value INT,
        status NVARCHAR(50) DEFAULT 'active',
        acknowledged_by INT,
        acknowledged_at DATETIME2,
        resolved_at DATETIME2,
        created_at DATETIME2 DEFAULT GETDATE(),
        FOREIGN KEY (asset_id) REFERENCES assets(id)
    )
    
    CREATE INDEX idx_alerts_asset_id ON stock_alerts(asset_id)
    CREATE INDEX idx_alerts_status ON stock_alerts(status)
END
GO
"""


def initialize_inventory_schema():
    """Initialize inventory module schema."""
    from app.core.database import execute_script
    execute_script("inventory", INVENTORY_SCHEMA)
    print("   ✅ assets, inventory_ledger, asset_maintenance, stock_alerts tables created")