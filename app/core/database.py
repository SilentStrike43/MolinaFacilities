# app/core/database.py
"""
Azure SQL Database utilities with connection pooling and proper error handling.
Supports 4 separate databases: core (users), send (mail), inventory, fulfillment.

Production-optimized version with:
- Retry logic for transient failures
- Larger connection pools
- Performance monitoring
- Better error handling
"""

import os
import pyodbc
import logging
import threading
import time
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Thread-local storage for connection management
_thread_local = threading.local()


class DatabaseError(Exception):
    """Base exception for database operations."""
    pass


class ConnectionMetrics:
    """Track connection pool performance metrics."""
    
    def __init__(self):
        self._lock = threading.Lock()
        self.total_connections = 0
        self.active_connections = 0
        self.failed_connections = 0
        self.retry_attempts = 0
        self.total_queries = 0
        self.avg_connection_time = 0.0
        
    def record_connection(self, duration: float, success: bool = True):
        """Record a connection attempt."""
        with self._lock:
            self.total_connections += 1
            if success:
                # Update rolling average
                self.avg_connection_time = (
                    (self.avg_connection_time * (self.total_connections - 1) + duration) 
                    / self.total_connections
                )
            else:
                self.failed_connections += 1
    
    def record_retry(self):
        """Record a retry attempt."""
        with self._lock:
            self.retry_attempts += 1
    
    def record_query(self):
        """Record a query execution."""
        with self._lock:
            self.total_queries += 1
    
    def get_stats(self) -> dict:
        """Get current metrics."""
        with self._lock:
            return {
                "total_connections": self.total_connections,
                "active_connections": self.active_connections,
                "failed_connections": self.failed_connections,
                "retry_attempts": self.retry_attempts,
                "total_queries": self.total_queries,
                "avg_connection_time_ms": round(self.avg_connection_time * 1000, 2),
                "success_rate": round(
                    ((self.total_connections - self.failed_connections) / self.total_connections * 100)
                    if self.total_connections > 0 else 0, 2
                )
            }


class AzureSQLPool:
    """Connection pool for Azure SQL databases with retry logic."""
    
    def __init__(self, connection_string: str, pool_size: int = 15):
        self.connection_string = connection_string
        self.pool_size = pool_size
        self._pool: List[pyodbc.Connection] = []
        self._lock = threading.Lock()
        self.metrics = ConnectionMetrics()
        
        # Retry configuration
        self.max_retries = 3
        self.base_retry_delay = 0.5  # seconds
        self.max_retry_delay = 5.0   # seconds
    
    def get_connection(self) -> pyodbc.Connection:
        """Get a connection from the pool or create a new one with retry logic."""
        # Try to get from pool first
        with self._lock:
            if self._pool:
                conn = self._pool.pop()
                # Validate connection before returning
                if self._validate_connection(conn):
                    self.metrics.active_connections += 1
                    return conn
                else:
                    # Connection is stale, try to close it
                    try:
                        conn.close()
                    except:
                        pass
        
        # No valid connection in pool, create a new one
        return self._create_connection_with_retry()
    
    def _validate_connection(self, conn: pyodbc.Connection) -> bool:
        """Check if a connection is still valid."""
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            return True
        except:
            return False
    
    def _create_connection_with_retry(self) -> pyodbc.Connection:
        """Create a new connection with exponential backoff retry."""
        retry_delay = self.base_retry_delay
        
        for attempt in range(self.max_retries):
            start_time = time.time()
            
            try:
                conn = pyodbc.connect(self.connection_string)
                duration = time.time() - start_time
                
                self.metrics.record_connection(duration, success=True)
                self.metrics.active_connections += 1
                
                logger.debug(f"Connection created successfully in {duration:.3f}s")
                return conn
                
            except pyodbc.Error as e:
                duration = time.time() - start_time
                self.metrics.record_connection(duration, success=False)
                
                error_code = e.args[0] if e.args else None
                
                # Check if error is transient (retryable)
                transient_errors = [
                    '08001',  # SQL Server connection failure
                    '08S01',  # Communication link failure
                    '40197',  # Service unavailable
                    '40501',  # Service busy
                    '40613',  # Database unavailable
                    '49918',  # Cannot process request
                    '49919',  # Cannot process create or update
                    '49920',  # Cannot process delete
                ]
                
                is_transient = error_code in transient_errors
                
                if attempt < self.max_retries - 1 and is_transient:
                    self.metrics.record_retry()
                    logger.warning(
                        f"Connection attempt {attempt + 1}/{self.max_retries} failed "
                        f"(error: {error_code}). Retrying in {retry_delay:.1f}s..."
                    )
                    time.sleep(retry_delay)
                    # Exponential backoff with jitter
                    retry_delay = min(retry_delay * 2, self.max_retry_delay)
                else:
                    logger.error(
                        f"Failed to create database connection after {attempt + 1} attempts: {e}"
                    )
                    raise DatabaseError(f"Database connection failed: {e}")
        
        # Should never reach here, but just in case
        raise DatabaseError("Failed to create connection after all retries")
    
    def return_connection(self, conn: pyodbc.Connection):
        """Return a connection to the pool."""
        self.metrics.active_connections -= 1
        
        try:
            # Validate before returning to pool
            if not self._validate_connection(conn):
                conn.close()
                return
            
            with self._lock:
                if len(self._pool) < self.pool_size:
                    self._pool.append(conn)
                else:
                    # Pool is full, close the connection
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
            self.metrics.active_connections = 0


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
            # Production: 15 connections per pool
            # Local dev: Can reduce to 5 by setting environment variable
            pool_size = int(os.environ.get('DB_POOL_SIZE', '15'))
            _pools[db_name] = AzureSQLPool(conn_str, pool_size=pool_size)
            logger.info(f"Created connection pool for '{db_name}' database (size: {pool_size})")
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
            cursor.close()
    
    Args:
        db_name: Database name (core, send, inventory, fulfillment)
    """
    pool = get_pool(db_name)
    conn = None
    
    try:
        conn = pool.get_connection()
        yield conn
    except pyodbc.IntegrityError as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        logger.warning(f"Integrity error in {db_name}: {e}")
        raise DatabaseError(f"Data integrity violation: {e}")
    except pyodbc.OperationalError as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        logger.error(f"Operational error in {db_name}: {e}")
        raise DatabaseError(f"Database operation failed: {e}")
    except pyodbc.ProgrammingError as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        logger.error(f"Programming error in {db_name}: {e}")
        raise DatabaseError(f"Database query error: {e}")
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        logger.error(f"Unexpected error in {db_name}: {e}", exc_info=True)
        raise DatabaseError(f"Database error: {e}")
    finally:
        if conn:
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
        db_name: Database name
        query: SQL query to execute
        params: Query parameters
        fetch_one: Return single row
        fetch_all: Return all rows
        commit: Commit transaction
    
    Returns:
        Query results or None
    """
    pool = get_pool(db_name)
    pool.metrics.record_query()
    
    with get_db_connection(db_name) as conn:
        cursor = conn.cursor()
        
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        
        result = None
        if fetch_one:
            result = cursor.fetchone()
        elif fetch_all:
            result = cursor.fetchall()
        
        if commit:
            conn.commit()
        
        cursor.close()
        return result


def execute_script(db_name: str, script: str) -> None:
    """Execute a SQL script (for migrations/schema updates)."""
    with get_db_connection(db_name) as conn:
        cursor = conn.cursor()
        
        # Split script into statements (simple approach)
        statements = [s.strip() for s in script.split('GO') if s.strip()]
        
        for statement in statements:
            if statement:
                cursor.execute(statement)
        
        conn.commit()
        cursor.close()


def get_pool_metrics(db_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get connection pool performance metrics.
    
    Args:
        db_name: Specific database name, or None for all databases
    
    Returns:
        Dictionary of metrics
    """
    if db_name:
        pool = get_pool(db_name)
        return {db_name: pool.metrics.get_stats()}
    else:
        # Get metrics for all pools
        metrics = {}
        with _pool_lock:
            for name, pool in _pools.items():
                metrics[name] = pool.metrics.get_stats()
        return metrics


def cleanup_all_pools():
    """Close all connection pools. Call this on app shutdown."""
    with _pool_lock:
        for name, pool in _pools.items():
            logger.info(f"Closing connection pool: {name}")
            pool.close_all()
        _pools.clear()
        logger.info("All database connection pools closed")


# Schema creation helpers (for initialization)
def create_core_tables():
    """Create basic core tables if schema function doesn't exist."""
    schema = """
    IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'users')
    BEGIN
        CREATE TABLE users (
            id INT IDENTITY(1,1) PRIMARY KEY,
            username NVARCHAR(255) UNIQUE,
            password_hash NVARCHAR(255),
            created_at DATETIME2 DEFAULT GETDATE()
        )
    END
    """
    execute_script("core", schema)


def create_send_tables():
    """Create basic send tables if schema function doesn't exist."""
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