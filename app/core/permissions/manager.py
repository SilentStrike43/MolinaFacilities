# app/core/permissions/manager.py
"""
Permission System with Hierarchical Levels
M1-M3: Module-level permissions
L1, L2, O1: Instance-scope administrative permissions
A1, A2: Platform-scope administrative permissions
S1: System Administrator (unrestricted)
"""

import json
from typing import Dict, List, Optional
from enum import Enum

from .constants import (
    PERMISSION_DESCRIPTIONS, PERMISSION_SCOPES, PERMISSION_HIERARCHY,
    HORIZON_LEVELS, MULTI_INST_LEVELS, ALL_ADMIN_LEVELS, SANDBOX_AUTO_LEVELS,
)


class PermissionLevel(Enum):
    """Permission levels in hierarchical order"""
    # Module Permissions
    M1_SEND                    = "M1"
    M2_INVENTORY               = "M2"
    M3A_FULFILLMENT_CUSTOMER   = "M3A"
    M3B_FULFILLMENT_SERVICE    = "M3B"
    M3C_FULFILLMENT_MANAGER    = "M3C"

    # Administrative Permissions
    L1_MODULE_ADMIN            = "L1"
    L2_INSTANCE_ADMIN          = "L2"
    O1_ORG_OWNER               = "O1"   # stale — future organisation feature
    A1_GRIDLINE_OPERATOR       = "A1"   # was L3
    A2_PLATFORM_ADMIN          = "A2"   # new — S1 powers minus granting S1/A2
    S1_SYSTEM                  = "S1"

    @classmethod
    def from_string(cls, value: str) -> Optional['PermissionLevel']:
        for level in cls:
            if level.value == value:
                return level
        return None

    def get_hierarchy_level(self) -> int:
        return PERMISSION_HIERARCHY.get(self.value, 0)

    def is_admin(self) -> bool:
        return self.value in ALL_ADMIN_LEVELS

    def is_module_permission(self) -> bool:
        return self.value.startswith("M")


class PermissionManager:
    """Manages user permissions and elevation."""

    @staticmethod
    def get_permission_description(level: str) -> str:
        return PERMISSION_DESCRIPTIONS.get(level, "Unknown permission level")

    @staticmethod
    def get_permission_scope(level: str) -> str:
        return PERMISSION_SCOPES.get(level, "Unknown")

    @staticmethod
    def get_included_permissions(level: str) -> List[str]:
        """Return all permission codes implied by the given level."""
        if level == "S1":
            return ["S1", "A2", "A1", "L2", "O1", "L1", "M1", "M2", "M3A", "M3B", "M3C"]
        elif level == "A2":
            return ["A2", "A1", "L2", "O1", "L1", "M1", "M2", "M3A", "M3B", "M3C"]
        elif level == "A1":
            return ["A1", "L2", "O1", "L1", "M1", "M2", "M3A", "M3B", "M3C"]
        elif level in ("L2", "O1"):
            return ["L2", "O1", "L1", "M1", "M2", "M3A", "M3B", "M3C"]
        elif level == "L1":
            return ["L1", "M1", "M2", "M3A", "M3B", "M3C"]
        elif level == "M3C":
            return ["M3C", "M3B", "M3A"]
        elif level == "M3B":
            return ["M3B"]
        elif level == "M3A":
            return ["M3A"]
        elif level == "M1":
            return ["M1"]
        elif level == "M2":
            return ["M2"]
        return []

    @staticmethod
    def can_elevate_to(actor_level: str, target_level: str) -> bool:
        """
        Check if actor can elevate someone to target_level.

        Elevation rules:
          S1  → L1, L2, O1, A1, A2, S1  (unrestricted)
          A2  → L1, L2, O1, A1          (cannot grant S1 or A2)
          A1  → L1, L2, O1, A1
          L2  → L1, L2
          O1  → L1                       (stale — future: L2 within org)
          L1  → L1
        """
        if not actor_level or not target_level:
            return False

        elevation_rules: Dict[str, List[str]] = {
            "S1": ["L1", "L2", "O1", "A1", "A2", "S1"],
            "A2": ["L1", "L2", "O1", "A1"],           # cannot grant S1 or A2
            "A1": ["L1", "L2", "O1", "A1"],
            "L2": ["L1", "L2"],
            "O1": ["L1"],
            "L1": ["L1"],
        }

        return target_level in elevation_rules.get(actor_level, [])

    @staticmethod
    def can_modify_user(actor_level: str, target_level: str) -> bool:
        """
        Return True if actor can modify target_user.
        Uses strict rank comparison; S1 can modify anyone.
        """
        if not actor_level:
            return False
        if actor_level == "S1":
            return True

        actor_rank  = PERMISSION_HIERARCHY.get(actor_level, 0)
        target_rank = PERMISSION_HIERARCHY.get(target_level or "", 0)
        return actor_rank > target_rank

    @staticmethod
    def can_access_horizon(level: str) -> bool:
        return level in HORIZON_LEVELS

    @staticmethod
    def can_manage_multiple_instances(level: str) -> bool:
        return level in MULTI_INST_LEVELS

    @staticmethod
    def parse_module_permissions(permissions_json: str) -> List[str]:
        try:
            if not permissions_json:
                return []
            perms = json.loads(permissions_json)
            if isinstance(perms, list):
                return perms
            elif isinstance(perms, dict):
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
        except Exception:
            return []

    @staticmethod
    def format_permissions_for_storage(permissions: List[str]) -> str:
        return json.dumps(permissions)

    @staticmethod
    def check_permission(user_data: dict, required_permission: str) -> bool:
        user_level = user_data.get("permission_level", "")
        if user_level:
            if required_permission in PermissionManager.get_included_permissions(user_level):
                return True
        module_perms = PermissionManager.parse_module_permissions(
            user_data.get("module_permissions", "[]")
        )
        return required_permission in module_perms

    @staticmethod
    def get_effective_permissions(user_data: dict) -> Dict[str, bool]:
        result = {
            "can_send": False,
            "can_inventory": False,
            "can_fulfillment_customer": False,
            "can_fulfillment_service": False,
            "can_fulfillment_manager": False,
            "can_admin_users": False,
            "can_admin_system": False,
            "can_admin_developer": False,
            "is_system": False,
            "can_access_horizon": False,
            "can_manage_multiple_instances": False,
        }

        user_level = user_data.get("permission_level", "")
        if user_level:
            level_perms = PermissionManager.get_included_permissions(user_level)
            result["can_send"]                  = "M1"  in level_perms
            result["can_inventory"]             = "M2"  in level_perms
            result["can_fulfillment_customer"]  = "M3A" in level_perms
            result["can_fulfillment_service"]   = "M3B" in level_perms
            result["can_fulfillment_manager"]   = "M3C" in level_perms
            result["can_admin_users"]           = "L1"  in level_perms
            result["can_admin_system"]          = "L2"  in level_perms
            result["can_admin_developer"]       = "A1"  in level_perms
            result["is_system"]                 = user_level in ("A2", "S1")
            result["can_access_horizon"]        = user_level in HORIZON_LEVELS
            result["can_manage_multiple_instances"] = user_level in MULTI_INST_LEVELS

        module_perms = PermissionManager.parse_module_permissions(
            user_data.get("module_permissions", "[]")
        )
        if "M1"  in module_perms: result["can_send"]                 = True
        if "M2"  in module_perms: result["can_inventory"]            = True
        if "M3A" in module_perms: result["can_fulfillment_customer"] = True
        if "M3B" in module_perms: result["can_fulfillment_service"]  = True
        if "M3C" in module_perms:
            result["can_fulfillment_manager"]  = True
            result["can_fulfillment_service"]  = True
            result["can_fulfillment_customer"] = True

        return result

    @staticmethod
    def get_user_display_level(user_data: dict) -> str:
        level = user_data.get("permission_level", "")
        if level:
            return level
        module_perms = PermissionManager.parse_module_permissions(
            user_data.get("module_permissions", "[]")
        )
        for m in ("M3C", "M3B", "M3A", "M2", "M1"):
            if m in module_perms:
                return m
        return "None"
