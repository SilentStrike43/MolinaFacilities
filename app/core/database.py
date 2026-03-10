# app/core/database.py
"""
PostgreSQL Database utilities with connection pooling and proper error handling.
Supports 4 separate databases: core (users), send (mail), inventory, fulfillment.

Production-optimized version with:
- psycopg2 connection pooling
- Retry logic for transient failures
- Performance monitoring
- Better error handling
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
import psycopg2
import psycopg2.pool
import psycopg2.extras
import logging
import threading
import time
from typing import Optional, Dict, Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)


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


class PostgreSQLPool:
    """Connection pool for PostgreSQL databases with retry logic."""
    
    def __init__(self, connection_params: dict, pool_size: int = 15):
        self.connection_params = connection_params
        self.pool_size = pool_size
        self.metrics = ConnectionMetrics()
        
        # Retry configuration
        self.max_retries = 3
        self.base_retry_delay = 0.5
        self.max_retry_delay = 5.0
        
        # Create connection pool
        try:
            self.pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=2,
                maxconn=pool_size,
                **connection_params
            )
            logger.info(f"Created PostgreSQL connection pool (size: {pool_size})")
        except Exception as e:
            logger.error(f"Failed to create connection pool: {e}")
            raise DatabaseError(f"Connection pool creation failed: {e}")
    
    def get_connection(self):
        """Get a connection from the pool with retry logic."""
        retry_delay = self.base_retry_delay
        
        for attempt in range(self.max_retries):
            start_time = time.time()
            
            try:
                conn = self.pool.getconn()
                duration = time.time() - start_time
                
                self.metrics.record_connection(duration, success=True)
                self.metrics.active_connections += 1
                
                # Set default cursor factory for dict-like results
                conn.cursor_factory = psycopg2.extras.RealDictCursor
                
                logger.debug(f"Connection retrieved in {duration:.3f}s")
                return conn
                
            except psycopg2.OperationalError as e:
                duration = time.time() - start_time
                self.metrics.record_connection(duration, success=False)
                
                if attempt < self.max_retries - 1:
                    self.metrics.record_retry()
                    logger.warning(
                        f"Connection attempt {attempt + 1}/{self.max_retries} failed. "
                        f"Retrying in {retry_delay:.1f}s..."
                    )
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, self.max_retry_delay)
                else:
                    logger.error(f"Failed to get connection after {attempt + 1} attempts: {e}")
                    raise DatabaseError(f"Database connection failed: {e}")
            
            except Exception as e:
                logger.error(f"Unexpected error getting connection: {e}")
                raise DatabaseError(f"Connection error: {e}")
        
        raise DatabaseError("Failed to get connection after all retries")
    
    def return_connection(self, conn):
        """Return a connection to the pool."""
        try:
            self.metrics.active_connections -= 1
            self.pool.putconn(conn)
        except Exception as e:
            logger.error(f"Error returning connection to pool: {e}")
            try:
                conn.close()
            except:
                pass
    
    def close_all(self):
        """Close all connections in the pool."""
        try:
            self.pool.closeall()
            self.metrics.active_connections = 0
            logger.info("All connections closed")
        except Exception as e:
            logger.error(f"Error closing connections: {e}")


# Global connection pools
_pools: Dict[str, PostgreSQLPool] = {}
_pool_lock = threading.Lock()

def parse_connection_string(conn_str: str) -> dict:
    """
    Parse PostgreSQL connection string into parameters.
    
    Supports formats:
    - postgresql://user:pass@host:port/dbname
    - host=host port=port dbname=dbname user=user password=pass
    """
    if conn_str.startswith('postgresql://') or conn_str.startswith('postgres://'):
        # Parse URI format — append connect_timeout if not already present
        sep = '?' if '?' not in conn_str else '&'
        if 'connect_timeout' not in conn_str:
            conn_str = f"{conn_str}{sep}connect_timeout=5"
        return {'dsn': conn_str}
    else:
        # Parse key=value format
        params = {}
        for part in conn_str.split():
            if '=' in part:
                key, value = part.split('=', 1)
                params[key] = value
        params.setdefault('connect_timeout', 5)
        return params


def get_connection_params(db_name: str) -> dict:
    """
    Get connection parameters for a database.
    
    Args:
        db_name: Database name (core, send, inventory, fulfillment)
    
    Returns:
        Dictionary of connection parameters
    """
    env_map = {
        "core": "DATABASE_URL_CORE",
        "send": "DATABASE_URL_SEND",
        "inventory": "DATABASE_URL_INVENTORY",
        "fulfillment": "DATABASE_URL_FULFILLMENT"
    }
    
    # Try new PostgreSQL env vars first
    env_var = env_map.get(db_name)
    conn_str = os.environ.get(env_var) if env_var else None
    
    # Fallback to single DATABASE_URL with schema suffix
    if not conn_str:
        base_url = os.environ.get('DATABASE_URL')
        if base_url:
            # Use same database but different schemas
            params = parse_connection_string(base_url)
            params['options'] = f"-c search_path={db_name},public"
            return params
        else:
            raise DatabaseError(
                f"No database connection configured. "
                f"Set {env_var} or DATABASE_URL environment variable"
            )
    
    return parse_connection_string(conn_str)


def get_pool(db_name: str) -> PostgreSQLPool:
    """Get or create a connection pool for a database."""
    with _pool_lock:
        if db_name not in _pools:
            params = get_connection_params(db_name)
            pool_size = int(os.environ.get('DB_POOL_SIZE', '15'))
            _pools[db_name] = PostgreSQLPool(params, pool_size=pool_size)
            logger.info(f"Created pool for '{db_name}' database")
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
        conn.commit()  # Auto-commit on success
    except psycopg2.IntegrityError as e:
        if conn:
            conn.rollback()
        logger.warning(f"Integrity error in {db_name}: {e}")
        raise DatabaseError(f"Data integrity violation: {e}")
    except psycopg2.OperationalError as e:
        if conn:
            conn.rollback()
        logger.error(f"Operational error in {db_name}: {e}")
        raise DatabaseError(f"Database operation failed: {e}")
    except psycopg2.ProgrammingError as e:
        if conn:
            conn.rollback()
        logger.error(f"Programming error in {db_name}: {e}")
        raise DatabaseError(f"Database query error: {e}")
    except Exception as e:
        if conn:
            conn.rollback()
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
        
        cursor.close()
        return result


def execute_script(db_name: str, script: str) -> None:
    """Execute a SQL script (for migrations/schema updates)."""
    with get_db_connection(db_name) as conn:
        cursor = conn.cursor()
        cursor.execute(script)
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