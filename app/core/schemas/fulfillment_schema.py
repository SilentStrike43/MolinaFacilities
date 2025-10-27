# app/core/schemas/fulfillment_schema.py
"""
Fulfillment module schema - Service requests, printing, copying, work orders
"""

FULFILLMENT_SCHEMA = """
-- Service requests table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'service_requests')
BEGIN
    CREATE TABLE service_requests (
        id INT IDENTITY(1,1) PRIMARY KEY,
        request_number NVARCHAR(100) UNIQUE,
        title NVARCHAR(255) NOT NULL,
        description NVARCHAR(MAX),
        request_type NVARCHAR(100) NOT NULL,
        category NVARCHAR(100),
        priority NVARCHAR(50) DEFAULT 'normal',
        status NVARCHAR(50) DEFAULT 'pending',
        requester_id INT NOT NULL,
        requester_name NVARCHAR(255),
        requester_email NVARCHAR(255),
        requester_phone NVARCHAR(50),
        department NVARCHAR(255),
        location NVARCHAR(255),
        building NVARCHAR(100),
        room NVARCHAR(100),
        assigned_to INT,
        due_date DATETIME2,
        estimated_cost DECIMAL(10,2),
        actual_cost DECIMAL(10,2),
        created_at DATETIME2 DEFAULT GETDATE(),
        updated_at DATETIME2 DEFAULT GETDATE(),
        started_at DATETIME2,
        completed_at DATETIME2,
        approved_at DATETIME2,
        approved_by INT,
        cancelled_at DATETIME2,
        cancelled_by INT,
        cancellation_reason NVARCHAR(MAX)
    )
    
    CREATE INDEX idx_requests_request_number ON service_requests(request_number)
    CREATE INDEX idx_requests_status ON service_requests(status)
    CREATE INDEX idx_requests_requester_id ON service_requests(requester_id)
    CREATE INDEX idx_requests_assigned_to ON service_requests(assigned_to)
    CREATE INDEX idx_requests_created_at ON service_requests(created_at)
END
GO

-- Request comments table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'request_comments')
BEGIN
    CREATE TABLE request_comments (
        id INT IDENTITY(1,1) PRIMARY KEY,
        request_id INT NOT NULL,
        user_id INT NOT NULL,
        comment_text NVARCHAR(MAX) NOT NULL,
        is_internal BIT DEFAULT 0,
        created_at DATETIME2 DEFAULT GETDATE(),
        FOREIGN KEY (request_id) REFERENCES service_requests(id) ON DELETE CASCADE
    )
    
    CREATE INDEX idx_comments_request_id ON request_comments(request_id)
    CREATE INDEX idx_comments_created_at ON request_comments(created_at)
END
GO

-- Request attachments table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'request_attachments')
BEGIN
    CREATE TABLE request_attachments (
        id INT IDENTITY(1,1) PRIMARY KEY,
        request_id INT NOT NULL,
        filename NVARCHAR(255) NOT NULL,
        file_path NVARCHAR(500) NOT NULL,
        file_size INT,
        mime_type NVARCHAR(100),
        uploaded_by INT NOT NULL,
        uploaded_at DATETIME2 DEFAULT GETDATE(),
        FOREIGN KEY (request_id) REFERENCES service_requests(id) ON DELETE CASCADE
    )
    
    CREATE INDEX idx_attachments_request_id ON request_attachments(request_id)
END
GO

-- Print jobs table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'print_jobs')
BEGIN
    CREATE TABLE print_jobs (
        id INT IDENTITY(1,1) PRIMARY KEY,
        request_id INT,
        job_number NVARCHAR(100),
        job_type NVARCHAR(50) NOT NULL,
        document_name NVARCHAR(255),
        pages INT,
        copies INT DEFAULT 1,
        color BIT DEFAULT 0,
        double_sided BIT DEFAULT 0,
        paper_size NVARCHAR(50),
        finishing NVARCHAR(100),
        special_instructions NVARCHAR(MAX),
        status NVARCHAR(50) DEFAULT 'pending',
        estimated_completion DATETIME2,
        completed_at DATETIME2,
        created_by INT NOT NULL,
        created_at DATETIME2 DEFAULT GETDATE(),
        FOREIGN KEY (request_id) REFERENCES service_requests(id)
    )
    
    CREATE INDEX idx_print_jobs_status ON print_jobs(status)
    CREATE INDEX idx_print_jobs_created_at ON print_jobs(created_at)
END
GO

-- Request status history table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'request_status_history')
BEGIN
    CREATE TABLE request_status_history (
        id INT IDENTITY(1,1) PRIMARY KEY,
        request_id INT NOT NULL,
        previous_status NVARCHAR(50),
        new_status NVARCHAR(50) NOT NULL,
        changed_by INT NOT NULL,
        notes NVARCHAR(MAX),
        timestamp DATETIME2 DEFAULT GETDATE(),
        FOREIGN KEY (request_id) REFERENCES service_requests(id) ON DELETE CASCADE
    )
    
    CREATE INDEX idx_history_request_id ON request_status_history(request_id)
    CREATE INDEX idx_history_timestamp ON request_status_history(timestamp)
END
GO
"""


def initialize_fulfillment_schema():
    """Initialize fulfillment module schema."""
    from app.core.database import execute_script
    execute_script("fulfillment", FULFILLMENT_SCHEMA)
    print("   ✅ service_requests, request_comments, request_attachments, print_jobs, request_status_history tables created")