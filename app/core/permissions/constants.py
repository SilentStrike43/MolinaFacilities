# app/core/permissions/constants.py
"""
Permission system constants and mappings
"""

# Module-level permissions
MODULE_PERMISSIONS = {
    'M1':  'Send Operator',
    'M2':  'Flow Operator',
    'M3A': 'Fulfillment Customer',
    'M3B': 'Fulfillment Staff',
    'M3C': 'Fulfillment Manager',
}

# Administrative levels
ADMIN_LEVELS = {
    'L1': 'Module Administrator',
    'L2': 'Instance Administrator',
    'O1': 'Organization Owner',
    'A1': 'Gridline Operator',
    'A2': 'Gridline Platform Administrator',
    'S1': 'System Administrator',
}

# Full permission descriptions
PERMISSION_DESCRIPTIONS = {
    # Module Permissions
    "M1":  "Send Operator - Send Module Access",
    "M2":  "Flow Operator - Flow Module Access",
    "M3A": "Fulfillment Customer - Able to send Fulfillment Request Forms",
    "M3B": "Fulfillment Staff - Able to view Fulfillment Service Queue and Archive",
    "M3C": "Fulfillment Manager - All access to the Fulfillment Module",

    # Administrative Permissions
    "L1": "Module Administrator - Able to create and assign users to modules",
    "L2": "Instance Administrator - Able to control multiple instances and assign L1 to users",
    "O1": "Organization Owner - Same powers as L2; instance-elevation features pending",
    "A1": "Gridline Operator - Platform Support and Management",
    "A2": "Gridline Platform Administrator - Unrestricted Access except granting S1 or A2",
    "S1": "System Administrator - Unrestricted Access to the Platform",
}

# Permission hierarchy (higher number = more powerful)
PERMISSION_HIERARCHY = {
    "":    0,
    "M1":  1,
    "M2":  1,
    "M3A": 1,
    "M3B": 1,
    "M3C": 2,
    "L1":  10,
    "O1":  20,   # Organisation Owner — stale L2-equivalent
    "L2":  20,
    "A1":  30,   # Was L3 — Gridline Operator
    "A2":  50,   # New — Platform Administrator (S1 powers minus granting S1/A2)
    "S1":  100,
}

# Permission scope mappings
PERMISSION_SCOPES = {
    "M1":  "Module Access",
    "M2":  "Module Access",
    "M3A": "Module Access",
    "M3B": "Module Access",
    "M3C": "Module Access",
    "L1":  "Single Instance",
    "O1":  "Multiple Instances (Organization)",
    "L2":  "Multiple Instances",
    "A1":  "All Instances (Global)",
    "A2":  "All Instances (Global — Platform Admin)",
    "S1":  "System-Wide (Unrestricted)",
}

# Convenience sets used throughout the codebase
HORIZON_LEVELS      = {'A1', 'A2', 'S1'}             # Full Horizon access
MULTI_INST_LEVELS   = {'L2', 'O1', 'A1', 'A2', 'S1'} # Can access multiple instances
ALL_ADMIN_LEVELS    = {'L1', 'L2', 'O1', 'A1', 'A2', 'S1'}
SANDBOX_AUTO_LEVELS = {'A1', 'A2', 'S1'}              # Auto-assigned to Sandbox on elevation
