# app/core/audit.py
"""
Central Audit Logging Utility

All modules should import and call log_action() to record events.
This is the single source of truth for writing to audit_logs.

Instance Audit Logs  -> audit_logs, filtered by instance_id
Global Audit Logs    -> audit_logs, filtered by module IN ('horizon', 'instance_access')
                        OR by permission_level IN ('L3', 'S1')
"""

import logging
from flask import request, session
from app.core.database import get_db_connection

logger = logging.getLogger(__name__)


def log_action(
    user_data,
    action: str,
    module: str,
    details: str,
    target_user_id: int = None,
    target_username: str = None,
    instance_id: int = None
):
    """
    Record an audit log entry.

    Args:
        user_data:        Current user dict (from current_user()). May be None for system events.
        action:           Short action name, e.g. 'create_shipment', 'submit_request'.
        module:           Module name, e.g. 'send', 'fulfillment', 'users', 'horizon',
                          'instance_access'.
        details:          Human-readable description of the event.
        target_user_id:   (optional) ID of the user being acted upon.
        target_username:  (optional) Username of the user being acted upon.
        instance_id:      (optional) Override instance_id. Auto-detected from request
                          context if not provided.
    """
    try:
        # Auto-detect instance_id from request context
        if instance_id is None:
            try:
                from app.core.instance_context import get_current_instance
                instance_id = get_current_instance()
            except Exception:
                pass

        # Safely extract user fields
        uid = None
        username = "system"
        permission_level = ""
        if user_data:
            uid = user_data.get("id")
            username = user_data.get("username", "system")
            permission_level = user_data.get("permission_level", "")

        # Safely extract request metadata
        ip_address = ""
        user_agent = ""
        session_id = ""
        try:
            if request:
                ip_address = request.remote_addr or ""
                user_agent = (request.headers.get("User-Agent", "") or "")[:500]
                session_id = session.get("session_id", "") or ""
        except RuntimeError:
            # Outside request context (e.g. scheduler)
            pass

        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO audit_logs (
                    user_id, username, action, module, details,
                    target_user_id, target_username, permission_level,
                    ip_address, user_agent, session_id,
                    instance_id, ts_utc
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                """,
                (
                    uid, username, action, module, details,
                    target_user_id, target_username, permission_level,
                    ip_address, user_agent, session_id,
                    instance_id,
                ),
            )
            cursor.close()

        logger.debug(f"Audit: [{module}] {username} → {action}: {details}")

    except Exception as e:
        # Audit failures must never crash the app
        logger.error(f"Audit log failed (action={action}, module={module}): {e}")
