# app/core/middleware.py
"""
Request lifecycle hooks.
Extracted from app.py to keep the factory lean.
"""
import logging
from datetime import datetime
from flask import session, redirect, url_for, flash

logger = logging.getLogger(__name__)


def register_middleware(app):
    """Attach before_request and after_request hooks to the Flask app."""

    @app.before_request
    def set_request_instance_context():
        from flask import request
        from app.core.instance_context import set_current_instance, clear_current_instance
        from app.modules.auth.security import current_user
        from app.core.database import get_db_connection

        clear_current_instance()

        cu = current_user()
        if not cu:
            return

        # Session-ID mismatch check (skip auth routes so login/logout always work)
        if not request.path.startswith('/auth/'):
            sid_in_url = request.args.get('sid', '')
            if sid_in_url:
                session_sid = session.get('session_id', '')
                if session_sid and sid_in_url != session_sid:
                    session.clear()
                    flash("Session mismatch — please sign in again.", "danger")
                    return redirect(url_for("auth.login"))

        # Force-logout check (set by L3/S1 via Support Tools)
        if cu.get('force_logout'):
            try:
                with get_db_connection("core") as conn:
                    c = conn.cursor()
                    c.execute("UPDATE users SET force_logout = FALSE WHERE id = %s", (cu['id'],))
                    c.close()
            except Exception:
                pass
            session.clear()
            flash("Your session was ended by an administrator.", "warning")
            return redirect(url_for("auth.login"))

        # Update last_seen (throttled: once per minute via session flag)
        _now = datetime.utcnow()
        _ls_key = '_ls_db'
        _prev_ls = session.get(_ls_key)
        if not _prev_ls or (_now - datetime.fromisoformat(_prev_ls)).seconds > 60:
            try:
                with get_db_connection("core") as conn:
                    c = conn.cursor()
                    c.execute("UPDATE users SET last_seen = %s WHERE id = %s", (_now, cu['id']))
                    c.close()
                session[_ls_key] = _now.isoformat()
            except Exception:
                pass

        # PRIORITY 1: Explicit instance_id in URL
        instance_id = request.args.get('instance_id', type=int)

        # PRIORITY 2: Persisted instance_id in session (for POST / redirects)
        if not instance_id and 'active_instance_id' in session:
            instance_id = session.get('active_instance_id')
            logger.debug(f"📦 Using session instance_id: {instance_id}")

        # PRIORITY 3: Default for S1/L3 → Sandbox; others → assigned instance
        if not instance_id and not request.path.startswith('/horizon'):
            perm_level = cu.get('permission_level', '')
            if perm_level in ['S1', 'A2', 'A1']:
                instance_id = 4
                logger.debug(f"🧪 Defaulting S1/L3 to Sandbox: {instance_id}")
            else:
                instance_id = cu.get('instance_id')
                logger.debug(f"👤 Using user's assigned instance: {instance_id}")

        if instance_id:
            set_current_instance(instance_id)

            # Log instance access when L3/S1 explicitly switches instances via URL
            prev_instance_id = session.get('active_instance_id')
            if (
                request.args.get('instance_id', type=int)
                and cu.get('permission_level') in ['A1', 'A2', 'S1']
                and instance_id != prev_instance_id
            ):
                try:
                    from app.core.audit import log_action
                    log_action(
                        cu,
                        "access_instance",
                        "instance_access",
                        f"Accessed instance {instance_id}",
                        instance_id=instance_id,
                    )
                except Exception:
                    pass

            session['active_instance_id'] = instance_id
            logger.debug(f"✅ Request instance context set: {instance_id}")
        else:
            logger.warning(f"⚠️ No instance context for user {cu.get('username')}")

    @app.after_request
    def clear_request_instance_context(response):
        from app.core.instance_context import clear_current_instance
        clear_current_instance()
        return response
