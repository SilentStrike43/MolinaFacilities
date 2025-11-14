"""
Instance-aware query builders
Ensures all queries are automatically filtered by instance_id
"""

from app.core.instance_context import get_current_instance
import logging

logger = logging.getLogger(__name__)


def add_instance_filter(base_where: str = "", params: list = None) -> tuple:
    """
    Add instance_id filter to WHERE clause
    
    Args:
        base_where: Existing WHERE conditions (without WHERE keyword)
        params: Existing parameter list
    
    Returns:
        (complete_where_clause, updated_params)
    
    Example:
        where, params = add_instance_filter("status = %s", ['active'])
        # Returns: ("instance_id = %s AND status = %s", [4, 'active'])
    """
    if params is None:
        params = []
    
    instance_id = get_current_instance()
    
    # Build WHERE clause
    if base_where:
        where_clause = f"instance_id = %s AND ({base_where})"
    else:
        where_clause = "instance_id = %s"
    
    # Add instance_id as first parameter
    all_params = [instance_id] + params
    
    return where_clause, all_params


def build_select(table: str, columns: str = "*", where: str = "", 
                params: list = None, order_by: str = "") -> tuple:
    """
    Build instance-aware SELECT query
    
    Returns: (sql, params)
    """
    where_clause, all_params = add_instance_filter(where, params)
    
    sql = f"SELECT {columns} FROM {table} WHERE {where_clause}"
    
    if order_by:
        sql += f" ORDER BY {order_by}"
    
    return sql, all_params


def build_insert(table: str, columns: list, values: list) -> tuple:
    """
    Build instance-aware INSERT query
    Automatically adds instance_id
    
    Returns: (sql, params)
    """
    instance_id = get_current_instance()
    
    # Add instance_id to columns and values
    all_columns = ['instance_id'] + columns
    all_values = [instance_id] + values
    
    placeholders = ', '.join(['%s'] * len(all_columns))
    columns_str = ', '.join(all_columns)
    
    sql = f"INSERT INTO {table} ({columns_str}) VALUES ({placeholders})"
    
    return sql, all_values


def build_update(table: str, set_clause: str, set_params: list,
                where: str = "", where_params: list = None) -> tuple:
    """
    Build instance-aware UPDATE query
    
    Returns: (sql, all_params)
    """
    where_clause, all_where_params = add_instance_filter(where, where_params)
    
    sql = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"
    all_params = set_params + all_where_params
    
    return sql, all_params


def build_delete(table: str, where: str = "", params: list = None) -> tuple:
    """
    Build instance-aware DELETE query
    
    Returns: (sql, params)
    """
    where_clause, all_params = add_instance_filter(where, params)
    
    sql = f"DELETE FROM {table} WHERE {where_clause}"
    
    return sql, all_params