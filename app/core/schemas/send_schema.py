# app/core/schemas/send_schema.py
"""
Send/Mail module schema - Package tracking, shipping labels, delivery
"""

SEND_SCHEMA = """
-- Packages table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'packages')
BEGIN
    CREATE TABLE packages (
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
    
    CREATE INDEX idx_packages_tracking ON packages(tracking_number)
    CREATE INDEX idx_packages_status ON packages(status)
    CREATE INDEX idx_packages_created_at ON packages(created_at)
    CREATE INDEX idx_packages_created_by ON packages(created_by)
END
GO

-- Package events table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'package_events')
BEGIN
    CREATE TABLE package_events (
        id INT IDENTITY(1,1) PRIMARY KEY,
        package_id INT NOT NULL,
        event_type NVARCHAR(100) NOT NULL,
        event_description NVARCHAR(500),
        location NVARCHAR(255),
        timestamp DATETIME2 DEFAULT GETDATE(),
        created_by INT,
        FOREIGN KEY (package_id) REFERENCES packages(id) ON DELETE CASCADE
    )
    
    CREATE INDEX idx_events_package_id ON package_events(package_id)
    CREATE INDEX idx_events_timestamp ON package_events(timestamp)
END
GO

-- Mail check-ins table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'mail_checkins')
BEGIN
    CREATE TABLE mail_checkins (
        id INT IDENTITY(1,1) PRIMARY KEY,
        recipient_name NVARCHAR(255) NOT NULL,
        recipient_id NVARCHAR(100),
        mail_type NVARCHAR(100),
        sender NVARCHAR(255),
        received_at DATETIME2 DEFAULT GETDATE(),
        picked_up_at DATETIME2,
        picked_up_by INT,
        location NVARCHAR(255),
        notes NVARCHAR(MAX),
        created_by INT NOT NULL,
        status NVARCHAR(50) DEFAULT 'pending_pickup'
    )
    
    CREATE INDEX idx_checkins_recipient ON mail_checkins(recipient_name)
    CREATE INDEX idx_checkins_status ON mail_checkins(status)
    CREATE INDEX idx_checkins_received_at ON mail_checkins(received_at)
END
GO
"""


def initialize_send_schema():
    """Initialize send/mail module schema."""
    from app.core.database import execute_script
    execute_script("send", SEND_SCHEMA)
    print("   ✅ packages, package_events, mail_checkins tables created")