# app/core/module_access.py
"""
Module Access Control
Checks if instances and users have access to specific modules
"""

import logging
from app.core.database import get_db_connection

logger = logging.getLogger(__name__)

# Module definitions
MODULES = {
    'send': {
        'name': 'Shipping',
        'icon': 'bi-box-seam',
        'description': 'Package tracking and shipment management'
    },
    'inventory': {
        'name': 'Inventory',
        'icon': 'bi-archive',
        'description': 'Asset management and stock control'
    },
    'fulfillment': {
        'name': 'Fulfillment',
        'icon': 'bi-clipboard-check',
        'description': 'Service requests and order processing'
    }
}


def get_instance_modules(instance_id):
    """
    Get list of enabled modules for an instance.
    
    Returns:
        List of module codes (e.g., ['send', 'inventory'])
    """
    try:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT enabled_modules 
                FROM instances 
                WHERE id = %s
            """, (instance_id,))
            result = cursor.fetchone()
            cursor.close()
            
            if result and result['enabled_modules']:
                return list(result['enabled_modules'])
            
            # Default: all modules
            return ['send', 'inventory', 'fulfillment']
            
    except Exception as e:
        logger.error(f"Error getting instance modules: {e}")
        return ['send', 'inventory', 'fulfillment']


def instance_has_module(instance_id, module_code):
    """
    Check if an instance has access to a specific module.
    
    Args:
        instance_id: Instance ID
        module_code: Module code ('send', 'inventory', 'fulfillment')
        
    Returns:
        Boolean
    """
    enabled = get_instance_modules(instance_id)
    return module_code in enabled


def user_has_module_access(user_data, module_code):
    """
    Check if a user has access to a module.
    This combines:
    1. Instance-level module access (is the module enabled for their instance?)
    2. User-level permissions (do they have permission to use it?)
    
    Args:
        user_data: User dict
        module_code: Module code
        
    Returns:
        Boolean
    """
    if not user_data:
        return False
    
    # L3/S1 can access everything
    if user_data.get('permission_level') in ['L3', 'S1']:
        return True
    
    instance_id = user_data.get('instance_id')
    if not instance_id:
        return False
    
    # Check if instance has the module
    if not instance_has_module(instance_id, module_code):
        return False
    
    # Check user's individual permissions
    from app.core.permissions import PermissionManager
    effective_perms = PermissionManager.get_effective_permissions(user_data)
    
    # Map module codes to permission keys
    permission_map = {
        'send': 'can_send',
        'inventory': 'can_inventory',
        'fulfillment': 'can_fulfillment_customer'
    }
    
    perm_key = permission_map.get(module_code)
    if not perm_key:
        return False
    
    # L1-L2 automatically have access if instance has the module
    if user_data.get('permission_level') in ['L1', 'L2']:
        return True
    
    return effective_perms.get(perm_key, False)


def get_user_available_modules(user_data):
    """
    Get list of modules available to a user.
    
    Returns:
        List of module dicts with metadata
    """
    available = []
    
    for code, info in MODULES.items():
        if user_has_module_access(user_data, code):
            available.append({
                'code': code,
                'name': info['name'],
                'icon': info['icon'],
                'description': info['description']
            })
    
    return available