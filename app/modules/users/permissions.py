# app/modules/users/permissions.py
"""
Permission System with Hierarchical Levels
M1-M3: Module-level permissions
L1-L3: Administrative permissions
S1: System-level permissions
"""

import json
from typing import Dict, List, Optional, Tuple
from enum import Enum

class PermissionLevel(Enum):
    """Permission levels in hierarchical order"""
    # Module Permissions
    M1_SEND = "M1"  # Send Module Access
    M2_INVENTORY = "M2"  # Inventory Module Access
    M3A_FULFILLMENT_CUSTOMER = "M3A"  # Fulfillment Customer Access
    M3B_FULFILLMENT_SERVICE = "M3B"  # Fulfillment Service Access
    M3C_FULFILLMENT_MANAGER = "M3C"  # Fulfillment Full Access
    
    # Administrative Permissions
    L1_MODULE_ADMIN = "L1"  # Module Administrator (Instance-level)
    L2_SYSTEM_ADMIN = "L2"  # Systems Administrator (Multi-instance)
    L3_APP_OPERATOR = "L3"  # App Operator (Global/All instances)
    S1_SYSTEM = "S1"  # System Level (Unrestricted)

    @classmethod
    def from_string(cls, value: str) -> Optional['PermissionLevel']:
        """Convert string to PermissionLevel"""
        for level in cls:
            if level.value == value:
                return level
        return None
    
    def get_hierarchy_level(self) -> int:
        """Get numeric hierarchy level for comparison"""
        hierarchy = {
            "M1": 1, "M2": 1, "M3A": 1, "M3B": 1, "M3C": 2,
            "L1": 10, "L2": 20, "L3": 30, "S1": 100
        }
        return hierarchy.get(self.value, 0)
    
    def is_admin(self) -> bool:
        """Check if this is an admin-level permission"""
        return self.value in ["L1", "L2", "L3", "S1"]
    
    def is_module_permission(self) -> bool:
        """Check if this is a module-level permission"""
        return self.value.startswith("M")

class PermissionManager:
    """Manages user permissions and elevation"""
    
    @staticmethod
    def get_permission_description(level: str) -> str:
        """Get human-readable description of permission level"""
        descriptions = {
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
        return descriptions.get(level, "Unknown permission level")
    
    @staticmethod
    def get_permission_scope(level: str) -> str:
        """Get the scope/access level for a permission"""
        scopes = {
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
        return scopes.get(level, "Unknown")
    
    @staticmethod
    def get_included_permissions(level: str) -> List[str]:
        """Get all permissions included in a given level"""
        level_enum = PermissionLevel.from_string(level)
        if not level_enum:
            return []
        
        # Admin levels include all lower levels
        if level == "S1":
            return ["S1", "L3", "L2", "L1", "M1", "M2", "M3A", "M3B", "M3C"]
        elif level == "L3":
            return ["L3", "L2", "L1", "M1", "M2", "M3A", "M3B", "M3C"]
        elif level == "L2":
            return ["L2", "L1", "M1", "M2", "M3A", "M3B", "M3C"]
        elif level == "L1":
            return ["L1", "M1", "M2", "M3A", "M3B", "M3C"]
        elif level == "M3C":
            return ["M3C", "M3B", "M3A"]  # Manager includes service and customer
        elif level == "M3B":
            return ["M3B"]  # Service level only
        elif level == "M3A":
            return ["M3A"]  # Customer access only
        elif level == "M1":
            return ["M1"]  # Send module only
        elif level == "M2":
            return ["M2"]  # Inventory module only
        else:
            return []
    
    @staticmethod
    def can_elevate_to(actor_level: str, target_level: str) -> bool:
        """
        Check if an actor can elevate someone to a target level.
        
        Rules:
        - L1: Can only elevate to L1
        - L2: Can elevate to L1, L2
        - L3: Can elevate to L1, L2, L3
        - S1: Can elevate to any level (L1, L2, L3, S1)
        """
        actor = PermissionLevel.from_string(actor_level)
        target = PermissionLevel.from_string(target_level)
        
        if not actor or not target:
            return False
        
        # Elevation rules
        elevation_rules = {
            "L1": ["L1"],
            "L2": ["L1", "L2"],
            "L3": ["L1", "L2", "L3"],
            "S1": ["L1", "L2", "L3", "S1"]
        }
        
        # Only admin levels can elevate
        if actor_level not in elevation_rules:
            return False
        
        return target_level in elevation_rules[actor_level]
    
    @staticmethod
    def can_elevate_to(actor_level: str, target_level: str) -> bool:
        """
        Check if actor can elevate users to target_level.
        CRITICAL: Admins CANNOT elevate to their own level.
        
        Args:
            actor_level: Permission level of the user performing elevation (L1/L2/L3/S1)
            target_level: Permission level to elevate to
        
        Returns:
            bool: True if elevation is allowed
        
        Examples:
            - L1 can only grant module permissions (cannot create other L1s)
            - L2 can elevate to L1 (but not L2)
            - L3 can elevate to L1 or L2 (but not L3)
            - S1 can elevate to any level (including S1)
        """
        if not actor_level or not target_level:
            return False
        
        # Define level hierarchy
        level_hierarchy = {
            "": 0,        # Module user (no admin level)
            "L1": 1,      # Module Administrator
            "L2": 2,      # Systems Administrator
            "L3": 3,      # App Operator
            "S1": 4       # System
        }
        
        actor_rank = level_hierarchy.get(actor_level, 0)
        target_rank = level_hierarchy.get(target_level, 0)
        
        # Special case: S1 can elevate anyone to any level (including S1)
        if actor_level == "S1":
            return True
        
        # CRITICAL RULE: Cannot elevate to own level or higher
        # L1 cannot create L1 (can only grant module permissions)
        # L2 cannot create L2 (can only create L1)
        # L3 cannot create L3 (can only create L1 or L2)
        if target_rank >= actor_rank:
            return False
        
        # Can elevate to any level strictly below actor's level
        return target_rank < actor_rank
    
    @staticmethod
    def can_access_horizon(level: str) -> bool:
        """Check if user can access Horizon global admin"""
        return level in ["L3", "S1"]
    
    @staticmethod
    def can_manage_multiple_instances(level: str) -> bool:
        """Check if user can manage multiple instances"""
        return level in ["L2", "L3", "S1"]
    
    @staticmethod
    def parse_module_permissions(permissions_json: str) -> List[str]:
        """Parse module permissions from JSON string"""
        try:
            if not permissions_json:
                return []
            perms = json.loads(permissions_json)
            if isinstance(perms, list):
                return perms
            elif isinstance(perms, dict):
                # Convert old format to new
                result = []
                if perms.get("can_send") or perms.get("send"):
                    result.append("M1")
                if perms.get("can_asset") or perms.get("inventory"):
                    result.append("M2")
                if perms.get("can_fulfillment_customer") or perms.get("fulfillment_customer"):
                    result.append("M3A")
                if perms.get("can_fulfillment_staff") or perms.get("fulfillment_staff"):
                    result.append("M3B")
                if perms.get("can_fulfillment_manager"):
                    result.append("M3C")
                return result
            return []
        except:
            return []
    
    @staticmethod
    def format_permissions_for_storage(permissions: List[str]) -> str:
        """Format permissions list for database storage"""
        return json.dumps(permissions)
    
    @staticmethod
    def check_permission(user_data: dict, required_permission: str) -> bool:
        """Check if user has a specific permission"""
        # Get user's permission level
        user_level = user_data.get("permission_level", "")
        
        # Check if user's level includes the required permission
        if user_level:
            included = PermissionManager.get_included_permissions(user_level)
            if required_permission in included:
                return True
        
        # Check module permissions
        module_perms = PermissionManager.parse_module_permissions(
            user_data.get("module_permissions", "[]")
        )
        return required_permission in module_perms
    
    @staticmethod
    def get_effective_permissions(user_data: dict) -> Dict[str, bool]:
        """
        Get all effective permissions for a user.
        
        Returns a dictionary of boolean flags representing what the user can do.
        Considers both permission_level and module_permissions.
        """
        result = {
            # Module permissions
            "can_send": False,
            "can_inventory": False,
            "can_fulfillment_customer": False,
            "can_fulfillment_service": False,
            "can_fulfillment_manager": False,
            
            # Administrative permissions
            "can_admin_users": False,
            "can_admin_system": False,
            "can_admin_developer": False,
            "is_system": False,
            
            # Access scopes
            "can_access_horizon": False,
            "can_manage_multiple_instances": False
        }
        
        # Get user's permission level
        user_level = user_data.get("permission_level", "")
        
        if user_level:
            level_perms = PermissionManager.get_included_permissions(user_level)
            
            # Map to boolean flags
            result["can_send"] = "M1" in level_perms
            result["can_inventory"] = "M2" in level_perms
            result["can_fulfillment_customer"] = "M3A" in level_perms
            result["can_fulfillment_service"] = "M3B" in level_perms
            result["can_fulfillment_manager"] = "M3C" in level_perms
            result["can_admin_users"] = "L1" in level_perms
            result["can_admin_system"] = "L2" in level_perms
            result["can_admin_developer"] = "L3" in level_perms
            result["is_system"] = "S1" in level_perms
            
            # Access scopes
            result["can_access_horizon"] = user_level in ["L3", "S1"]
            result["can_manage_multiple_instances"] = user_level in ["L2", "L3", "S1"]
        
        # Also check module permissions (non-admin users)
        module_perms = PermissionManager.parse_module_permissions(
            user_data.get("module_permissions", "[]")
        )
        
        if "M1" in module_perms:
            result["can_send"] = True
        if "M2" in module_perms:
            result["can_inventory"] = True
        if "M3A" in module_perms:
            result["can_fulfillment_customer"] = True
        if "M3B" in module_perms:
            result["can_fulfillment_service"] = True
        if "M3C" in module_perms:
            result["can_fulfillment_manager"] = True
            result["can_fulfillment_service"] = True  # M3C includes M3B
            result["can_fulfillment_customer"] = True  # M3C includes M3A
        
        return result
    
    @staticmethod
    def get_user_display_level(user_data: dict) -> str:
        """Get user's primary display level (highest permission)"""
        level = user_data.get("permission_level", "")
        
        if level:
            return level
        
        # If no admin level, show highest module permission
        module_perms = PermissionManager.parse_module_permissions(
            user_data.get("module_permissions", "[]")
        )
        
        if "M3C" in module_perms:
            return "M3C"
        elif "M3B" in module_perms:
            return "M3B"
        elif "M3A" in module_perms:
            return "M3A"
        elif "M2" in module_perms:
            return "M2"
        elif "M1" in module_perms:
            return "M1"
        
        return "None"