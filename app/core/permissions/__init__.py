# app/core/permissions/__init__.py
"""
Core Permissions System
Handles all authorization logic for the application.
"""

from .manager import PermissionManager, PermissionLevel
from .decorators import (
    require_permission,
    require_admin_level,
    require_instance_access,
    require_instance_owner,
    require_any_permission
)
from .constants import (
    MODULE_PERMISSIONS,
    ADMIN_LEVELS,
    PERMISSION_DESCRIPTIONS,
    PERMISSION_HIERARCHY
)

__all__ = [
    # Core classes
    'PermissionManager',
    'PermissionLevel',
    
    # Decorators
    'require_permission',
    'require_admin_level',
    'require_instance_access',
    'require_instance_owner',
    'require_any_permission',
    
    # Constants
    'MODULE_PERMISSIONS',
    'ADMIN_LEVELS',
    'PERMISSION_DESCRIPTIONS',
    'PERMISSION_HIERARCHY',
]