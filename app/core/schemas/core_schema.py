# app/core/schemas/core_schema.py
"""
Core database schema - Users, authentication, permissions, audit logs
"""

CORE_SCHEMA = """
-- Users table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'users')
BEGIN
    CREATE TABLE users (
        id INT IDENTITY(1,1) PRIMARY KEY,
        username NVARCHAR(255) NOT NULL UNIQUE,
        password_hash NVARCHAR(255) NOT NULL,
        permission_level NVARCHAR(50),
        first_name NVARCHAR(255),
        last_name NVARCHAR(255),
        email NVARCHAR(255),
        phone NVARCHAR(50),
        department NVARCHAR(255),
        is_active BIT DEFAULT 1,
        created_at DATETIME2 DEFAULT GETDATE(),
        updated_at DATETIME2 DEFAULT GETDATE(),
        last_login DATETIME2,
        created_by INT,
        updated_by INT
    )
    
    CREATE INDEX idx_users_username ON users(username)
    CREATE INDEX idx_users_email ON users(email)
    CREATE INDEX idx_users_permission_level ON users(permission_level)
END
GO

-- Audit logs table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'audit_logs')
BEGIN
    CREATE TABLE audit_logs (
        id INT IDENTITY(1,1) PRIMARY KEY,
        user_id INT,
        action NVARCHAR(100) NOT NULL,
        entity_type NVARCHAR(100),
        entity_id INT,
        details NVARCHAR(MAX),
        ip_address NVARCHAR(50),
        user_agent NVARCHAR(500),
        timestamp DATETIME2 DEFAULT GETDATE(),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    
    CREATE INDEX idx_audit_user_id ON audit_logs(user_id)
    CREATE INDEX idx_audit_timestamp ON audit_logs(timestamp)
    CREATE INDEX idx_audit_action ON audit_logs(action)
END
GO

-- Sessions table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'sessions')
BEGIN
    CREATE TABLE sessions (
        id INT IDENTITY(1,1) PRIMARY KEY,
        session_id NVARCHAR(255) NOT NULL UNIQUE,
        user_id INT NOT NULL,
        data NVARCHAR(MAX),
        created_at DATETIME2 DEFAULT GETDATE(),
        expires_at DATETIME2 NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    
    CREATE INDEX idx_sessions_user_id ON sessions(user_id)
    CREATE INDEX idx_sessions_expires_at ON sessions(expires_at)
END
GO

-- User capabilities table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'user_capabilities')
BEGIN
    CREATE TABLE user_capabilities (
        id INT IDENTITY(1,1) PRIMARY KEY,
        user_id INT NOT NULL,
        capability NVARCHAR(100) NOT NULL,
        granted_by INT,
        granted_at DATETIME2 DEFAULT GETDATE(),
        expires_at DATETIME2,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (granted_by) REFERENCES users(id)
    )
    
    CREATE INDEX idx_capabilities_user_id ON user_capabilities(user_id)
    CREATE INDEX idx_capabilities_capability ON user_capabilities(capability)
END
GO
"""


def initialize_core_schema():
    """Initialize core database schema."""
    from app.core.database import execute_script
    execute_script("core", CORE_SCHEMA)
    print("   ✅ users, audit_logs, sessions, user_capabilities tables created")