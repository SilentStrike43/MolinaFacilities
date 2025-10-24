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
    L1_MODULE_ADMIN = "L1"  # Module Administrator
    L2_SYSTEM_ADMIN = "L2"  # Systems Administrator
    L3_APP_DEVELOPER = "L3"  # App Developer
    S1_SYSTEM = "S1"  # System Level

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
            "M1": "Send Module - Access to Send Module and its Insights",
            "M2": "Inventory Module - Access to Inventory module and its Insights",
            "M3A": "Fulfillment Customer - Access to New Request Form only",
            "M3B": "Fulfillment Service - Access to Service Queue and Archive",
            "M3C": "Fulfillment Manager - Full Fulfillment Module access",
            "L1": "Module Administrator - All modules, user management, Administration tab",
            "L2": "Systems Administrator - L1 + Audit Logs, Azure SQL Database management",
            "L3": "App Developer - L2 + Azure VM access, subscription management",
            "S1": "System - Full system access with all permissions"
        }
        return descriptions.get(level, "Unknown permission level")
    
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
        else:
            return [level]  # Module permissions are standalone
    
    @staticmethod
    def can_elevate_to(actor_level: str, target_level: str) -> bool:
        """Check if an actor can elevate someone to a target level"""
        # Parse permission levels
        actor = PermissionLevel.from_string(actor_level)
        target = PermissionLevel.from_string(target_level)
        
        if not actor or not target:
            return False
        
        # Elevation rules based on requirements
        elevation_rules = {
            "L1": ["L1"],  # Can only create other L1 admins
            "L2": ["L1", "L2"],  # Can elevate to L1 and L2
            "L3": ["L1", "L2", "L3"],  # Can elevate to L1, L2, and L3
            "S1": ["L1", "L2", "L3", "S1"]  # Can elevate to any level
        }
        
        # Only admin levels can elevate
        if actor_level not in elevation_rules:
            return False
        
        return target_level in elevation_rules[actor_level]
    
    @staticmethod
    def can_modify_user(actor_level: str, target_level: str) -> bool:
        """Check if an actor can modify a target user"""
        if not actor_level or not target_level:
            return False
        
        actor = PermissionLevel.from_string(actor_level)
        target = PermissionLevel.from_string(target_level)
        
        if not actor or not target:
            return False
        
        # Can only modify users at lower levels
        return actor.get_hierarchy_level() > target.get_hierarchy_level()
    
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
        """Get all effective permissions for a user"""
        result = {
            "can_send": False,
            "can_inventory": False,
            "can_fulfillment_customer": False,
            "can_fulfillment_service": False,
            "can_fulfillment_manager": False,
            "can_admin_users": False,
            "can_admin_system": False,
            "can_admin_developer": False,
            "is_system": False
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
        
        # Also check module permissions
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
        
        return result