# app/core/database.py
"""
Centralized database utilities with proper error handling, connection pooling,
and security features. Use this instead of raw sqlite3 connections throughout the app.
"""

import sqlite3
import logging
import functools
import threading
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

# Thread-local storage for connection management
_thread_local = threading.local()


class DatabaseError(Exception):
    """Base exception for database operations."""
    pass


class ConnectionPool:
    """Simple connection pool for SQLite databases."""
    
    def __init__(self, db_path: str, max_connections: int = 5):
        self.db_path = Path(db_path)
        self.max_connections = max_connections
        self._pool: List[sqlite3.Connection] = []
        self._lock = threading.Lock()
        
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
    
    def get_connection(self) -> sqlite3.Connection:
        """Get a connection from the pool or create a new one."""
        with self._lock:
            if self._pool:
                return self._pool.pop()
            
            try:
                con = sqlite3.connect(
                    str(self.db_path),
                    check_same_thread=False,
                    timeout=30.0  # 30 second timeout for locks
                )
                con.row_factory = sqlite3.Row
                con.execute("PRAGMA foreign_keys = ON")
                con.execute("PRAGMA journal_mode = WAL")  # Write-Ahead Logging for better concurrency
                return con
            except sqlite3.Error as e:
                logger.error(f"Failed to create database connection to {self.db_path}: {e}")
                raise DatabaseError(f"Database connection failed: {e}")
    
    def return_connection(self, con: sqlite3.Connection):
        """Return a connection to the pool."""
        with self._lock:
            if len(self._pool) < self.max_connections:
                self._pool.append(con)
            else:
                try:
                    con.close()
                except Exception:
                    pass
    
    def close_all(self):
        """Close all connections in the pool."""
        with self._lock:
            for con in self._pool:
                try:
                    con.close()
                except Exception:
                    pass
            self._pool.clear()


# Global connection pools (lazy initialized)
_pools: Dict[str, ConnectionPool] = {}
_pool_lock = threading.Lock()


def get_pool(db_path: str) -> ConnectionPool:
    """Get or create a connection pool for a database."""
    with _pool_lock:
        if db_path not in _pools:
            _pools[db_path] = ConnectionPool(db_path)
        return _pools[db_path]


@contextmanager
def get_db_connection(db_path: str, commit: bool = False):
    """
    Context manager for database connections with automatic cleanup.
    
    Usage:
        with get_db_connection("path/to/db.sqlite", commit=True) as con:
            con.execute("INSERT INTO users (name) VALUES (?)", ("John",))
    
    Args:
        db_path: Path to the SQLite database
        commit: Whether to commit on successful exit (default: False)
    """
    pool = get_pool(db_path)
    con = pool.get_connection()
    
    try:
        yield con
        if commit:
            con.commit()
    except sqlite3.IntegrityError as e:
        con.rollback()
        logger.warning(f"Integrity error in {db_path}: {e}")
        raise DatabaseError(f"Data integrity violation: {e}")
    except sqlite3.OperationalError as e:
        con.rollback()
        logger.error(f"Operational error in {db_path}: {e}")
        raise DatabaseError(f"Database operation failed: {e}")
    except Exception as e:
        con.rollback()
        logger.error(f"Unexpected error in {db_path}: {e}", exc_info=True)
        raise DatabaseError(f"Database error: {e}")
    finally:
        pool.return_connection(con)


def execute_query(
    db_path: str,
    query: str,
    params: Optional[Tuple] = None,
    fetch_one: bool = False,
    fetch_all: bool = False,
    commit: bool = False
) -> Optional[Any]:
    """
    Execute a database query with proper error handling.
    
    Args:
        db_path: Path to the database
        query: SQL query to execute
        params: Query parameters (always use parameterized queries!)
        fetch_one: Return single row
        fetch_all: Return all rows
        commit: Commit the transaction
    
    Returns:
        Query results or None
    """
    params = params or ()
    
    # Validate that query uses parameterized form (basic check)
    if any(f"'{val}'" in query or f'"{val}"' in query for val in params if isinstance(val, str)):
        logger.warning(f"Potential SQL injection risk detected in query: {query[:100]}")
    
    try:
        with get_db_connection(db_path, commit=commit) as con:
            cursor = con.execute(query, params)
            
            if fetch_one:
                return cursor.fetchone()
            elif fetch_all:
                return cursor.fetchall()
            elif commit:
                return cursor.lastrowid
            return cursor
    
    except DatabaseError:
        raise
    except Exception as e:
        logger.error(f"Query execution failed: {e}\nQuery: {query[:200]}")
        raise DatabaseError(f"Failed to execute query: {e}")


def transaction(db_path: str):
    """
    Decorator for functions that need database transactions.
    
    Usage:
        @transaction("path/to/db.sqlite")
        def create_user(con, username, password):
            con.execute("INSERT INTO users ...", (username, password))
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with get_db_connection(db_path, commit=True) as con:
                return func(con, *args, **kwargs)
        return wrapper
    return decorator


def safe_execute_script(db_path: str, script: str):
    """
    Execute a SQL script with error handling (for migrations/setup).
    
    Args:
        db_path: Path to database
        script: SQL script to execute
    """
    try:
        with get_db_connection(db_path, commit=True) as con:
            con.executescript(script)
            logger.info(f"Successfully executed script on {db_path}")
    except Exception as e:
        logger.error(f"Failed to execute script on {db_path}: {e}")
        raise DatabaseError(f"Script execution failed: {e}")


def validate_db_exists(db_path: str) -> bool:
    """Check if database file exists and is accessible."""
    path = Path(db_path)
    if not path.exists():
        logger.warning(f"Database does not exist: {db_path}")
        return False
    
    try:
        with get_db_connection(db_path) as con:
            con.execute("SELECT 1")
        return True
    except Exception as e:
        logger.error(f"Database validation failed for {db_path}: {e}")
        return False


# Cleanup function for application shutdown
def cleanup_all_pools():
    """Close all connection pools. Call this on app shutdown."""
    with _pool_lock:
        for pool in _pools.values():
            pool.close_all()
        _pools.clear()
        logger.info("All database connection pools closed")


# Example usage patterns:
"""
# Pattern 1: Simple query with context manager
with get_db_connection(AUTH_DB) as con:
    user = con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

# Pattern 2: Execute with helper
user = execute_query(
    AUTH_DB,
    "SELECT * FROM users WHERE id = ?",
    (user_id,),
    fetch_one=True
)

# Pattern 3: Transaction decorator
@transaction(AUTH_DB)
def create_user(con, username, password):
    cursor = con.execute(
        "INSERT INTO users (username, password) VALUES (?, ?)",
        (username, password)
    )
    return cursor.lastrowid
"""