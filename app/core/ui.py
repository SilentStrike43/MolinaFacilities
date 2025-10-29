# app/core/ui.py - FIXED VERSION
"""
UI context processor - injects global variables and user permissions into templates
"""

import os
import json
from flask import g

from app.modules.auth.security import current_user
from app.modules.users.permissions import PermissionManager

APP_VERSION = os.environ.get("APP_VERSION", "0.4.0")
BRAND_TEAL = os.environ.get("BRAND_TEAL", "#00A3AD")

def get_user_permission_level(user_data):
    """Get the effective permission level for a user - matches backend logic"""
    if not user_data:
        return None
    
    # Check for system flag first
    try:
        caps = json.loads(user_data.get("caps", "{}") or "{}")
        if caps.get("is_system"):
            return "S1"
    except:
        pass
    
    # Check explicit permission_level field
    if user_data.get("permission_level"):
        return user_data["permission_level"]
    
    # Legacy compatibility - map old flags to new levels
    if user_data.get("is_sysadmin"):
        return "L2"
    elif user_data.get("is_admin"):
        return "L1"
    
    return None

def inject_globals():
    """Inject global variables into all templates."""
    from flask import g
    from app.modules.auth.security import current_user
    
    # Get current user (will use cached version if available)
    cu = current_user()
    
    if cu:
        # Get permission level
        permission_level = cu.get('permission_level', '')
        
        # Parse module permissions - CRITICAL FIX
        try:
            module_perms_raw = cu.get('module_permissions', '[]')
            if isinstance(module_perms_raw, str):
                module_perms = json.loads(module_perms_raw or '[]')
            elif isinstance(module_perms_raw, list):
                module_perms = module_perms_raw
            else:
                module_perms = []
        except Exception as e:
            print(f"ERROR parsing module_permissions: {e}")
            print(f"Raw value: {cu.get('module_permissions')}")
            module_perms = []
        
        # Check if elevated (admin level)
        elevated = permission_level in ['L1', 'L2', 'L3', 'S1']
        
        # CRITICAL FIX: Use PermissionManager for consistent permission checking
        effective_perms = PermissionManager.get_effective_permissions(cu)
        
        # Module permissions - use effective permissions from PermissionManager
        can_send = effective_perms['can_send'] or elevated
        can_inventory = effective_perms['can_inventory'] or elevated
        can_asset = effective_perms['can_inventory'] or elevated
        
        # Fulfillment permissions
        can_fulfillment_customer = effective_perms['can_fulfillment_customer'] or elevated
        can_fulfillment_service = effective_perms['can_fulfillment_service'] or elevated
        can_fulfillment_manager = effective_perms['can_fulfillment_manager'] or elevated
        
        # Admin permissions
        can_admin_users = elevated
        can_view_audit_logs = permission_level in ['L2', 'L3', 'S1']
        can_manage_system = permission_level in ['L3', 'S1']
        
        # Debug output (remove after testing)
        if not elevated:
            print(f"DEBUG: User {cu.get('username')} - Module Perms: {module_perms}")
            print(f"DEBUG: Effective Perms: {effective_perms}")
            print(f"DEBUG: can_fulfillment_manager = {can_fulfillment_manager}")
        
        return {
            'cu': cu,
            'current_user': cu,
            'elevated': elevated,
            'can_send': can_send,
            'can_inventory': can_inventory,
            'can_asset': can_asset,
            'can_fulfillment_customer': can_fulfillment_customer,
            'can_fulfillment_service': can_fulfillment_service,
            'can_fulfillment_manager': can_fulfillment_manager,
            'can_admin_users': can_admin_users,
            'can_view_audit_logs': can_view_audit_logs,
            'can_manage_system': can_manage_system,
            'APP_VERSION': APP_VERSION,
            'BRAND_TEAL': BRAND_TEAL,
        }
    else:
        # User not logged in
        return {
            'cu': None,
            'current_user': None,
            'elevated': False,
            'can_send': False,
            'can_inventory': False,
            'can_asset': False,
            'can_fulfillment_customer': False,
            'can_fulfillment_service': False,
            'can_fulfillment_manager': False,
            'can_admin_users': False,
            'can_view_audit_logs': False,
            'can_manage_system': False,
            'APP_VERSION': APP_VERSION,
            'BRAND_TEAL': BRAND_TEAL,
        }