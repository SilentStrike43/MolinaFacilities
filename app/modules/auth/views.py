# app/modules/auth/views.py
"""
Authentication routes
"""

import secrets
import string

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
    uid = session.get("uid")
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
        user_dict = authenticate_user(username, password)
        
        if user_dict:
            # Check if user is deleted
            if user_dict.get('deleted_at'):
                flash("This account has been deactivated.", "danger")
                return render_template("auth/login.html")

            # Generate session ID and set session
            sid = _generate_session_id()
            session.clear()
            session['user_id'] = user_dict['id']
            session['username'] = user_dict['username']
            session['session_id'] = sid
            session.permanent = True

            # Log sign-in event (appears in global audit logs for all users)
            from app.core.audit import log_action
            log_action(
                user_dict,
                'sign_in',
                'auth',
                f"Signed in from {request.remote_addr} — session {sid}",
                instance_id=user_dict.get('instance_id')
            )

            flash(f"Welcome back, {user_dict.get('first_name') or user_dict['username']}!", "success")

            # Redirect to home
            return redirect(url_for("home.index"))
        else:
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