# app/core/database.py
"""
Azure SQL Database utilities with connection pooling and proper error handling.
Supports 4 separate databases: core (users), send (mail), inventory, fulfillment.
"""

import os
import pyodbc
import logging
import threading
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Thread-local storage for connection management
_thread_local = threading.local()


class DatabaseError(Exception):
    """Base exception for database operations."""
    pass


class AzureSQLPool:
    """Connection pool for Azure SQL databases."""
    
    def __init__(self, connection_string: str, pool_size: int = 5):
        self.connection_string = connection_string
        self.pool_size = pool_size
        self._pool: List[pyodbc.Connection] = []
        self._lock = threading.Lock()
    
    def get_connection(self) -> pyodbc.Connection:
        """Get a connection from the pool or create a new one."""
        with self._lock:
            if self._pool:
                return self._pool.pop()
            
            try:
                conn = pyodbc.connect(self.connection_string)
                return conn
            except pyodbc.Error as e:
                logger.error(f"Failed to create database connection: {e}")
                raise DatabaseError(f"Database connection failed: {e}")
    
    def return_connection(self, conn: pyodbc.Connection):
        """Return a connection to the pool."""
        try:
            # Check if connection is still valid
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            
            with self._lock:
                if len(self._pool) < self.pool_size:
                    self._pool.append(conn)
                else:
                    conn.close()
        except:
            try:
                conn.close()
            except:
                pass
    
    def close_all(self):
        """Close all connections in the pool."""
        with self._lock:
            for conn in self._pool:
                try:
                    conn.close()
                except:
                    pass
            self._pool.clear()


# Global connection pools
_pools: Dict[str, AzureSQLPool] = {}
_pool_lock = threading.Lock()


def get_connection_string(db_name: str) -> str:
    """
    Get connection string for a database.
    
    Args:
        db_name: Database name (core, send, inventory, fulfillment)
    
    Returns:
        Connection string from environment variables
    """
    env_map = {
        "core": "DB_CORE_CONNECTION_STRING",
        "send": "DB_SEND_CONNECTION_STRING",
        "inventory": "DB_INVENTORY_CONNECTION_STRING",
        "fulfillment": "DB_FULFILLMENT_CONNECTION_STRING"
    }
    
    env_var = env_map.get(db_name)
    if not env_var:
        raise ValueError(f"Unknown database: {db_name}")
    
    conn_str = os.environ.get(env_var)
    if not conn_str:
        raise DatabaseError(f"Environment variable {env_var} not set")
    
    return conn_str


def get_pool(db_name: str) -> AzureSQLPool:
    """Get or create a connection pool for a database."""
    with _pool_lock:
        if db_name not in _pools:
            conn_str = get_connection_string(db_name)
            _pools[db_name] = AzureSQLPool(conn_str)
        return _pools[db_name]


@contextmanager
def get_db_connection(db_name: str = "core"):
    """
    Context manager for database connections with automatic cleanup.
    
    Usage:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users")
            users = cursor.fetchall()
    
    Args:
        db_name: Database name (core, send, inventory, fulfillment)
    """
    pool = get_pool(db_name)
    conn = pool.get_connection()
    
    try:
        yield conn
    except pyodbc.IntegrityError as e:
        try:
            conn.rollback()
        except:
            pass
        logger.warning(f"Integrity error in {db_name}: {e}")
        raise DatabaseError(f"Data integrity violation: {e}")
    except pyodbc.OperationalError as e:
        try:
            conn.rollback()
        except:
            pass
        logger.error(f"Operational error in {db_name}: {e}")
        raise DatabaseError(f"Database operation failed: {e}")
    except Exception as e:
        try:
            conn.rollback()
        except:
            pass
        logger.error(f"Unexpected error in {db_name}: {e}", exc_info=True)
        raise DatabaseError(f"Database error: {e}")
    finally:
        pool.return_connection(conn)


def execute_query(
    db_name: str,
    query: str,
    params: Optional[tuple] = None,
    fetch_one: bool = False,
    fetch_all: bool = False,
    commit: bool = False
) -> Optional[Any]:
    """
    Execute a database query with proper error handling.
    
    Args:
        db_name: Database name (core, send, inventory, fulfillment)
        query: SQL query to execute
        params: Query parameters (always use parameterized queries!)
        fetch_one: Return single row
        fetch_all: Return all rows
        commit: Commit the transaction
    
    Returns:
        Query results or None
    """
    params = params or ()
    
    try:
        with get_db_connection(db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            
            if fetch_one:
                result = cursor.fetchone()
                cursor.close()
                return result
            elif fetch_all:
                result = cursor.fetchall()
                cursor.close()
                return result
            elif commit:
                conn.commit()
                # Get last inserted ID if available
                try:
                    cursor.execute("SELECT @@IDENTITY")
                    last_id = cursor.fetchone()[0]
                    cursor.close()
                    return last_id
                except:
                    cursor.close()
                    return None
            
            cursor.close()
            return None
    
    except DatabaseError:
        raise
    except Exception as e:
        logger.error(f"Query execution failed in {db_name}: {e}\nQuery: {query[:200]}")
        raise DatabaseError(f"Failed to execute query: {e}")


def execute_script(db_name: str, script: str):
    """
    Execute a SQL script (for schema initialization).
    SQL Server uses GO batches, not semicolons.
    
    Args:
        db_name: Database name
        script: SQL script to execute
    """
    try:
        with get_db_connection(db_name) as conn:
            cursor = conn.cursor()
            
            # Split by GO statements (SQL Server batch separator)
            batches = [batch.strip() for batch in script.split('GO') if batch.strip()]
            
            for batch in batches:
                if batch:
                    try:
                        cursor.execute(batch)
                        conn.commit()
                    except pyodbc.Error as e:
                        logger.error(f"Error executing batch: {batch[:200]}")
                        raise
            
            cursor.close()
            logger.info(f"Successfully executed script on {db_name}")
    except Exception as e:
        logger.error(f"Failed to execute script on {db_name}: {e}")
        raise DatabaseError(f"Script execution failed: {e}")


def table_exists(db_name: str, table_name: str) -> bool:
    """Check if a table exists in the database."""
    try:
        query = """
            SELECT COUNT(*) 
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_NAME = ?
        """
        result = execute_query(db_name, query, (table_name,), fetch_one=True)
        return result[0] > 0 if result else False
    except:
        return False


def initialize_database():
    """Initialize all database schemas for production."""
    print("\n" + "=" * 70)
    print("INITIALIZING ALL DATABASE SCHEMAS")
    print("=" * 70)
    
    # Initialize Core/Users Database
    print("\n📦 Initializing Core Database (users)...")
    try:
        from app.core.schemas.core_schema import initialize_core_schema
        initialize_core_schema()
    except Exception as e:
        print(f"   ❌ Error: {e}")
        raise
    
    # Initialize Send/Mail Module
    print("\n📦 Initializing Send Module (mail)...")
    try:
        from app.core.schemas.send_schema import initialize_send_schema
        initialize_send_schema()
    except Exception as e:
        print(f"   ❌ Error: {e}")
        raise
    
    # Initialize Inventory Module
    print("\n📦 Initializing Inventory Module...")
    try:
        from app.core.schemas.inventory_schema import initialize_inventory_schema
        initialize_inventory_schema()
    except Exception as e:
        print(f"   ❌ Error: {e}")
        raise
    
    # Initialize Fulfillment Module
    print("\n📦 Initializing Fulfillment Module...")
    try:
        from app.core.schemas.fulfillment_schema import initialize_fulfillment_schema
        initialize_fulfillment_schema()
    except Exception as e:
        print(f"   ❌ Error: {e}")
        raise
    
    print("\n" + "=" * 70)
    print("✅ DATABASE INITIALIZATION COMPLETE!")
    print("=" * 70)


def create_users_table():
    """Create basic users table if schema function doesn't exist."""
    schema = """
    IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'users')
    BEGIN
        CREATE TABLE users (
            id INT IDENTITY(1,1) PRIMARY KEY,
            username NVARCHAR(255) NOT NULL UNIQUE,
            password_hash NVARCHAR(255) NOT NULL,
            permission_level NVARCHAR(50),
            first_name NVARCHAR(255),
            last_name NVARCHAR(255),
            email NVARCHAR(255),
            created_at DATETIME2 DEFAULT GETDATE(),
            updated_at DATETIME2 DEFAULT GETDATE()
        )
    END
    """
    execute_script("core", schema)


def create_send_tables():
    """Create basic send/mail tables if schema function doesn't exist."""
    schema = """
    IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'packages')
    BEGIN
        CREATE TABLE packages (
            id INT IDENTITY(1,1) PRIMARY KEY,
            tracking_number NVARCHAR(255),
            recipient NVARCHAR(255),
            status NVARCHAR(50),
            created_at DATETIME2 DEFAULT GETDATE()
        )
    END
    """
    execute_script("send", schema)


def create_inventory_tables():
    """Create basic inventory tables if schema function doesn't exist."""
    schema = """
    IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'assets')
    BEGIN
        CREATE TABLE assets (
            id INT IDENTITY(1,1) PRIMARY KEY,
            name NVARCHAR(255),
            quantity INT,
            created_at DATETIME2 DEFAULT GETDATE()
        )
    END
    """
    execute_script("inventory", schema)


def create_fulfillment_tables():
    """Create basic fulfillment tables if schema function doesn't exist."""
    schema = """
    IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'requests')
    BEGIN
        CREATE TABLE requests (
            id INT IDENTITY(1,1) PRIMARY KEY,
            title NVARCHAR(255),
            status NVARCHAR(50),
            created_at DATETIME2 DEFAULT GETDATE()
        )
    END
    """
    execute_script("fulfillment", schema)


def cleanup_all_pools():
    """Close all connection pools. Call this on app shutdown."""
    with _pool_lock:
        for pool in _pools.values():
            pool.close_all()
        _pools.clear()
        logger.info("All database connection pools closed")