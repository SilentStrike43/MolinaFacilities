# app/core/schemas/send_schema.py
"""Send module schema - using send. schema prefix"""

SEND_SCHEMA = """
-- Create schema if it doesn't exist
IF NOT EXISTS (SELECT * FROM sys.schemas WHERE name = 'send')
BEGIN
    EXEC('CREATE SCHEMA send')
END
GO

-- Counters table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'counters' AND schema_id = SCHEMA_ID('send'))
BEGIN
    CREATE TABLE send.counters (
        name NVARCHAR(100) PRIMARY KEY,
        value INT NOT NULL DEFAULT 0
    )
END
GO

-- Packages table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'packages' AND schema_id = SCHEMA_ID('send'))
BEGIN
    CREATE TABLE send.packages (
        id INT IDENTITY(1,1) PRIMARY KEY,
        tracking_number NVARCHAR(255) UNIQUE,
        recipient_name NVARCHAR(255) NOT NULL,
        recipient_email NVARCHAR(255),
        recipient_phone NVARCHAR(50),
        destination_address NVARCHAR(500),
        destination_city NVARCHAR(100),
        destination_state NVARCHAR(50),
        destination_zip NVARCHAR(20),
        destination_country NVARCHAR(100) DEFAULT 'USA',
        package_type NVARCHAR(100),
        weight DECIMAL(10,2),
        dimensions NVARCHAR(100),
        carrier NVARCHAR(100),
        service_level NVARCHAR(100),
        status NVARCHAR(50) DEFAULT 'pending',
        notes NVARCHAR(MAX),
        created_by INT NOT NULL,
        created_at DATETIME2 DEFAULT GETDATE(),
        updated_at DATETIME2 DEFAULT GETDATE(),
        shipped_at DATETIME2,
        delivered_at DATETIME2,
        estimated_delivery DATETIME2,
        cost DECIMAL(10,2)
    )
    
    CREATE INDEX idx_packages_tracking ON send.packages(tracking_number)
    CREATE INDEX idx_packages_status ON send.packages(status)
    CREATE INDEX idx_packages_created_at ON send.packages(created_at)
END
GO

-- Package events table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'package_events' AND schema_id = SCHEMA_ID('send'))
BEGIN
    CREATE TABLE send.package_events (
        id INT IDENTITY(1,1) PRIMARY KEY,
        package_id INT NOT NULL,
        event_type NVARCHAR(100) NOT NULL,
        event_description NVARCHAR(MAX),
        event_location NVARCHAR(255),
        created_at DATETIME2 DEFAULT GETDATE(),
        created_by INT,
        FOREIGN KEY (package_id) REFERENCES send.packages(id) ON DELETE CASCADE
    )
    
    CREATE INDEX idx_events_package_id ON send.package_events(package_id)
    CREATE INDEX idx_events_created_at ON send.package_events(created_at)
END
GO

-- Mail checkins table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'mail_checkins' AND schema_id = SCHEMA_ID('send'))
BEGIN
    CREATE TABLE send.mail_checkins (
        id INT IDENTITY(1,1) PRIMARY KEY,
        checkin_date DATE NOT NULL,
        checkin_id NVARCHAR(50) UNIQUE,
        recipient_name NVARCHAR(255) NOT NULL,
        mail_type NVARCHAR(100),
        carrier NVARCHAR(100),
        tracking_number NVARCHAR(255),
        notes NVARCHAR(MAX),
        status NVARCHAR(50) DEFAULT 'received',
        location NVARCHAR(100),
        created_by INT NOT NULL,
        received_at DATETIME2 DEFAULT GETDATE(),
        picked_up_at DATETIME2,
        picked_up_by NVARCHAR(255)
    )
    
    CREATE INDEX idx_checkins_checkin_id ON send.mail_checkins(checkin_id)
    CREATE INDEX idx_checkins_recipient ON send.mail_checkins(recipient_name)
    CREATE INDEX idx_checkins_status ON send.mail_checkins(status)
    CREATE INDEX idx_checkins_received_at ON send.mail_checkins(received_at)
END
GO

-- Package manifest table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'package_manifest' AND schema_id = SCHEMA_ID('send'))
BEGIN
    CREATE TABLE send.package_manifest (
        id INT IDENTITY(1,1) PRIMARY KEY,
        checkin_date DATE,
        checkin_id NVARCHAR(50),
        package_type NVARCHAR(100),
        package_id NVARCHAR(100) UNIQUE,
        recipient_name NVARCHAR(255) NOT NULL,
        recipient_address NVARCHAR(MAX),
        tracking_number NVARCHAR(255),
        carrier NVARCHAR(100),
        submitter_name NVARCHAR(255),
        location NVARCHAR(100),
        status NVARCHAR(50) DEFAULT 'created',
        created_by INT NOT NULL,
        ts_utc DATETIME2 DEFAULT GETUTCDATE()
    )
    
    CREATE INDEX idx_manifest_package_id ON send.package_manifest(package_id)
    CREATE INDEX idx_manifest_checkin_date ON send.package_manifest(checkin_date)
    CREATE INDEX idx_manifest_location ON send.package_manifest(location)
    CREATE INDEX idx_manifest_ts_utc ON send.package_manifest(ts_utc)
END
GO

-- Cache table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'cache' AND schema_id = SCHEMA_ID('send'))
BEGIN
    CREATE TABLE send.cache (
        tracking NVARCHAR(255) PRIMARY KEY,
        carrier NVARCHAR(100),
        payload NVARCHAR(MAX),
        updated DATETIME2 DEFAULT GETUTCDATE()
    )
    
    CREATE INDEX idx_cache_updated ON send.cache(updated)
END
GO
"""


def initialize_send_schema():
    """Initialize send/mail module schema."""
    from app.core.database import execute_script
    execute_script("core", SEND_SCHEMA)  # ← Changed from "send" to "core"
    print("   ✅ send schema tables created")