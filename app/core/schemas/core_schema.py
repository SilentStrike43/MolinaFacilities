# app/core/schemas/core_schema.py
"""Core schema - users and system tables in dbo schema"""

CORE_SCHEMA = """
-- Users table (in dbo schema, no prefix needed)
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'users' AND schema_id = SCHEMA_ID('dbo'))
BEGIN
    CREATE TABLE dbo.users (
        id INT IDENTITY(1,1) PRIMARY KEY,
        username NVARCHAR(100) UNIQUE NOT NULL,
        password_hash NVARCHAR(255) NOT NULL,
        full_name NVARCHAR(255),
        email NVARCHAR(255),
        phone NVARCHAR(50),
        role NVARCHAR(50) DEFAULT 'user',
        location NVARCHAR(50) DEFAULT 'NY',
        position NVARCHAR(255),
        department NVARCHAR(255),
        is_active BIT DEFAULT 1,
        module_permissions NVARCHAR(MAX) DEFAULT '[]',
        created_at DATETIME2 DEFAULT GETDATE(),
        updated_at DATETIME2 DEFAULT GETDATE(),
        last_login DATETIME2,
        last_modified_by INT,
        last_modified_at DATETIME2
    )
    
    CREATE INDEX idx_users_username ON dbo.users(username)
    CREATE INDEX idx_users_role ON dbo.users(role)
    CREATE INDEX idx_users_is_active ON dbo.users(is_active)
END
GO

-- Audit log table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'audit_log' AND schema_id = SCHEMA_ID('dbo'))
BEGIN
    CREATE TABLE dbo.audit_log (
        id INT IDENTITY(1,1) PRIMARY KEY,
        user_id INT,
        username NVARCHAR(100),
        action NVARCHAR(100) NOT NULL,
        module NVARCHAR(100),
        details NVARCHAR(MAX),
        ip_address NVARCHAR(50),
        user_agent NVARCHAR(500),
        timestamp DATETIME2 DEFAULT GETDATE()
    )
    
    CREATE INDEX idx_audit_user_id ON dbo.audit_log(user_id)
    CREATE INDEX idx_audit_action ON dbo.audit_log(action)
    CREATE INDEX idx_audit_timestamp ON dbo.audit_log(timestamp)
END
GO
"""


def initialize_core_schema():
    """Initialize core module schema."""
    from app.core.database import execute_script
    execute_script("core", CORE_SCHEMA)
    print("   ✅ core (dbo) schema tables created")