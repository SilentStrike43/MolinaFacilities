# app/modules/auth/views.py
"""
Authentication routes
"""

import secrets
import string
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify

# Import from users.models (correct database)
from app.modules.users.models import (
    get_user_by_id,
    create_user,
)

bp = Blueprint("auth", __name__, url_prefix="/auth", template_folder="templates")

# ---- Helper Functions ----

_SESSION_ID_ALPHABET = string.ascii_lowercase + string.digits

def _generate_session_id():
    """Generate a cryptographically random 18-character a-z0-9 session ID."""
    return ''.join(secrets.choice(_SESSION_ID_ALPHABET) for _ in range(18))

def row_to_dict(row):
    """Convert psycopg2 row to dictionary."""
    if row is None:
        return None
    return dict(row)

def get_current_user():
    """Get current logged-in user from session"""
    uid = session.get("user_id")
    if not uid:
        return None

    row = get_user_by_id(uid)
    if not row:
        return None

    return row_to_dict(row)

def record_audit(user, action, source, details=""):
    """Stub audit function - implement later if needed"""
    pass

# ---- Routes ----

@bp.route("/login", methods=["GET", "POST"])
def login():
    """User login."""
    
    if session.get("user_id"):
        return redirect(url_for("home.index"))
    
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        
        if not username or not password:
            flash("Please enter both username and password.", "danger")
            return render_template("auth/login.html")
        
        # Authenticate
        from app.modules.users.models import authenticate_user
        from app.core.audit import log_action
        result = authenticate_user(username, password)

        # Account locked
        if isinstance(result, dict) and result.get('locked'):
            locked_until = result['locked_until']
            log_action(
                {'id': None, 'username': username, 'permission_level': ''},
                'login_blocked',
                'auth',
                f"Login attempt on locked account '{username}' from {request.remote_addr}"
            )
            flash(
                f"This account is temporarily locked after too many failed attempts. "
                f"Try again after {locked_until.strftime('%H:%M UTC')}.",
                "danger"
            )
            return render_template("auth/login.html")

        if result:
            user_dict = result
            # Generate session ID and set session
            sid = _generate_session_id()
            session.clear()
            session['user_id'] = user_dict['id']
            session['username'] = user_dict['username']
            session['session_id'] = sid
            session.permanent = True

            log_action(
                user_dict,
                'sign_in',
                'auth',
                f"Signed in from {request.remote_addr} — session {sid}",
                instance_id=user_dict.get('instance_id')
            )

            flash(f"Welcome back, {user_dict.get('first_name') or user_dict['username']}!", "success")
            return redirect(url_for("home.index"))

        else:
            # Log the failed attempt (use a stub user dict so log_action doesn't choke)
            log_action(
                {'id': None, 'username': username, 'permission_level': ''},
                'login_failed',
                'auth',
                f"Failed login attempt for '{username}' from {request.remote_addr}"
            )
            flash("Invalid username or password.", "danger")
            return render_template("auth/login.html")
    
    return render_template("auth/login.html")

@bp.route("/logout")
def logout():
    """Logout handler"""
    user = get_current_user()
    if user:
        from app.core.audit import log_action
        log_action(
            user,
            'sign_out',
            'auth',
            f"Signed out — session {session.get('session_id', '')}",
            instance_id=user.get('instance_id')
        )

    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/idle-logout", methods=["POST"])
def idle_logout():
    """Called by the client-side idle timer when the session times out."""
    user = get_current_user()
    if user:
        from app.core.audit import log_action
        log_action(
            user,
            'sign_out',
            'auth',
            f"Idle timeout — signed out automatically after 15 minutes of inactivity — session {session.get('session_id', '')}",
            instance_id=user.get('instance_id')
        )

    session.clear()
    return jsonify({"success": True})


@bp.route("/keep-alive", methods=["POST"])
def keep_alive():
    """Ping to reset the server-side session expiry."""
    user = get_current_user()
    if not user:
        return jsonify({"ok": False}), 401
    session.modified = True
    return jsonify({"ok": True})

@bp.route("/change-password", methods=["GET", "POST"])
def change_password():
    """Password changes are disabled — users must submit a request."""
    user = get_current_user()
    if not user:
        flash("Please login first", "warning")
        return redirect(url_for("auth.login"))
    flash("Password changes must be submitted via the request system.", "info")
    return redirect(url_for("users.submit_request"))


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    """
    Password reset via emailed token.

    GET  — validate token, show reset form (or error if expired/used).
    POST — validate token again, hash and save new password, mark token used.

    Tokens expire after 1 hour. Expired/used attempts are audit-logged.
    """
    from app.core.database import get_db_connection
    from app.core.audit import log_action
    import bcrypt

    # ── Validate token ────────────────────────────────────────────────────────
    with get_db_connection("core") as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM password_reset_tokens WHERE token = %s",
            (token,)
        )
        tok = cur.fetchone()
        cur.close()

    if not tok:
        log_action(
            {'id': None, 'username': 'unknown', 'permission_level': ''},
            'reset_token_invalid', 'auth',
            f"Invalid password reset token used from {request.remote_addr}"
        )
        flash("This reset link is invalid.", "danger")
        return render_template("auth/reset_password.html", token_invalid=True)

    if tok['used_at']:
        flash("This reset link has already been used. Please submit a new request.", "warning")
        return render_template("auth/reset_password.html", token_invalid=True)

    if datetime.utcnow() > tok['expires_at']:
        log_action(
            {'id': tok['user_id'], 'username': tok['username'], 'permission_level': ''},
            'reset_token_expired', 'auth',
            f"Expired password reset token used by {tok['username']} from {request.remote_addr}"
        )
        flash("This reset link has expired. Please submit a new password reset request.", "warning")
        return render_template("auth/reset_password.html", token_invalid=True, token_expired=True)

    # ── Token is valid ────────────────────────────────────────────────────────
    if request.method == "POST":
        new_password = request.form.get("new_password", "").strip()
        confirm      = request.form.get("confirm_password", "").strip()

        if not new_password or len(new_password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return render_template("auth/reset_password.html", token=token)

        if new_password != confirm:
            flash("Passwords do not match.", "danger")
            return render_template("auth/reset_password.html", token=token)

        hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()

        with get_db_connection("core") as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (hashed, tok['user_id'])
            )
            cur.execute("""
                UPDATE password_reset_tokens
                SET used_at = CURRENT_TIMESTAMP, used_from_ip = %s
                WHERE id = %s
            """, (request.remote_addr, tok['id']))
            cur.close()

        log_action(
            {'id': tok['user_id'], 'username': tok['username'], 'permission_level': ''},
            'password_reset_completed', 'auth',
            f"Password reset completed for {tok['username']} from {request.remote_addr}"
        )

        flash("Your password has been reset. Please sign in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", token=token)