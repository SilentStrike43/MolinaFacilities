"""
Custom Jinja2 filters for Horizon module
"""
import logging

logger = logging.getLogger(__name__)

def format_number(value):
    """
    Format number with thousand separators.
    
    Examples:
        1000 -> 1,000
        1000000 -> 1,000,000
    """
    try:
        return "{:,}".format(int(value))
    except (ValueError, TypeError):
        return value


def format_bytes(bytes_value):
    """
    Format bytes into human-readable size.
    
    Examples:
        1024 -> 1 KB
        1048576 -> 1 MB
    """
    try:
        bytes_value = float(bytes_value)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024.0:
                return f"{bytes_value:.1f} {unit}"
            bytes_value /= 1024.0
        return f"{bytes_value:.1f} PB"
    except (ValueError, TypeError):
        return bytes_value


def format_percentage(value, total):
    """
    Calculate and format percentage.
    
    Examples:
        (50, 100) -> 50.0%
        (1, 3) -> 33.3%
    """
    try:
        if total == 0:
            return "0.0%"
        percentage = (float(value) / float(total)) * 100
        return f"{percentage:.1f}%"
    except (ValueError, TypeError, ZeroDivisionError):
        return "0.0%"


def status_badge(status):
    """
    Return Bootstrap badge class for status.
    
    Examples:
        'active' -> 'badge bg-success'
        'inactive' -> 'badge bg-secondary'
    """
    status_map = {
        'active': 'badge bg-success',
        'inactive': 'badge bg-secondary',
        'pending': 'badge bg-warning',
        'error': 'badge bg-danger',
        'disabled': 'badge bg-dark',
    }
    return status_map.get(str(status).lower(), 'badge bg-secondary')


def permission_badge(level):
    """
    Return CSS class string for a permission-level badge.

    Uses the perm-badge / perm-xx palette defined in horizon_base.html.
    Examples:
        'S1' -> 'perm-badge perm-s1'
        'A2' -> 'perm-badge perm-a2'
    """
    level_map = {
        'S1': 'perm-badge perm-s1',
        'A2': 'perm-badge perm-a2',
        'A1': 'perm-badge perm-a1',
        'O1': 'perm-badge perm-o1',
        'L2': 'perm-badge perm-l2',
        'L1': 'perm-badge perm-l1',
    }
    return level_map.get(str(level), 'perm-badge perm-m')


def register_filters(app):
    """
    Register all custom Jinja2 filters with the Flask app.
    
    Usage in app.py:
        from app.modules.horizon.filters import register_filters
        register_filters(app)
    
    Usage in templates:
        {{ 1000|format_number }}  -> 1,000
        {{ 1048576|format_bytes }} -> 1.0 MB
        {{ status|status_badge }} -> 'badge bg-success'
    """
    import json as _json
    app.jinja_env.filters['format_number'] = format_number
    app.jinja_env.filters['format_bytes'] = format_bytes
    app.jinja_env.filters['format_percentage'] = format_percentage
    app.jinja_env.filters['status_badge'] = status_badge
    app.jinja_env.filters['permission_badge'] = permission_badge
    app.jinja_env.filters['from_json'] = lambda s: (_json.loads(s) if s else [])
    
    # Also add global functions for templates
    app.jinja_env.globals['get_permission_display'] = get_permission_display
    app.jinja_env.globals['get_instance_name'] = get_instance_name


def get_permission_display(level):
    """Get human-readable permission level label."""
    levels = {
        'S1': 'System',
        'A2': 'Administrator',
        'A1': 'Operator',
        'O1': 'Org Owner',
        'L2': 'Instance Manager',
        'L1': 'Module Admin',
        '':   'Standard User',
    }
    return levels.get(level, 'Standard User')


def get_instance_name(instance_id):
    """
    Get instance name from ID.
    
    This is a template helper function.
    """
    try:
        from app.modules.horizon.models import get_instance_by_id
        instance = get_instance_by_id(instance_id)
        return instance.get('name', 'Unknown') if instance else 'Unknown'
    except Exception as e:
        logger.error(f"Error getting instance name for id={instance_id}: {e}")
        return 'Unknown'