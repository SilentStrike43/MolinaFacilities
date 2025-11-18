# app/core/permissions/constants.py
"""
Permission system constants and mappings
"""

# Module-level permissions
MODULE_PERMISSIONS = {
    'M1': 'Send/Ledger Module',
    'M2': 'Inventory/Flow Module',
    'M3A': 'Fulfillment Customer',
    'M3B': 'Fulfillment Service',
    'M3C': 'Fulfillment Manager',
}

# Administrative levels
ADMIN_LEVELS = {
    'L1': 'Module Administrator',
    'L2': 'Systems Administrator',
    'L3': 'App Operator',
    'S1': 'System Administrator',
}

# Full permission descriptions
PERMISSION_DESCRIPTIONS = {
    # Module Permissions
    "M1": "Send Module - Access to Send/Ledger module and its insights",
    "M2": "Inventory Module - Access to Inventory/Flow module and its insights",
    "M3A": "Fulfillment Customer - Submit new fulfillment requests only",
    "M3B": "Fulfillment Service - Access to service queue, archive, and request management",
    "M3C": "Fulfillment Manager - Full fulfillment module access including insights and reports",
    
    # Administrative Permissions
    "L1": "Module Administrator - Manage users within assigned instance, full module access",
    "L2": "Systems Administrator - Manage multiple instances, database access, audit logs",
    "L3": "App Operator - Global oversight via Horizon, cross-instance analytics, instance creation",
    "S1": "System Administrator - Unrestricted system access, all permissions"
}

# Permission hierarchy (higher number = more powerful)
PERMISSION_HIERARCHY = {
    "": 0,        # No admin level
    "M1": 1,
    "M2": 1,
    "M3A": 1,
    "M3B": 1,
    "M3C": 2,
    "L1": 10,
    "L2": 20,
    "L3": 30,
    "S1": 100
}

# Permission scope mappings
PERMISSION_SCOPES = {
    "M1": "Module Access",
    "M2": "Module Access",
    "M3A": "Module Access",
    "M3B": "Module Access",
    "M3C": "Module Access",
    "L1": "Single Instance",
    "L2": "Multiple Instances",
    "L3": "All Instances (Global)",
    "S1": "System-Wide (Unrestricted)"
}