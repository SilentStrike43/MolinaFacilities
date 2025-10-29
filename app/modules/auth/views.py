# app/modules/auth/views.py - FIXED VERSION
"""
Authentication routes - Compatible with your existing app structure
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, session

# Import from users.models (correct database)
from app.modules.users.models import (
    get_user_by_username,
    get_user_by_id,
    create_user,
    set_password,
    verify_password,
)

bp = Blueprint("auth", __name__, url_prefix="/auth", template_folder="templates")

# ---- Helper Functions ----

def row_to_dict(row):
    """Convert sqlite3.Row to dictionary"""
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
            
            # Set session
            session.clear()
            session['user_id'] = user_dict['id']
            session['username'] = user_dict['username']
            session.permanent = True
            
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
    username = session.get("username", "unknown")
    
    record_audit(get_current_user(), "logout", "auth", f"User logged out: {username}")
    
    session.clear()
    flash("You have been logged out", "info")
    return redirect(url_for("auth.login"))

@bp.route("/change-password", methods=["GET", "POST"])
def change_password():
    """Change password page"""
    user = get_current_user()
    if not user:
        flash("Please login first", "warning")
        return redirect(url_for("auth.login"))
    
    if request.method == "POST":
        current_password = request.form.get("current_password") or ""
        new_password = request.form.get("new_password") or ""
        confirm_password = request.form.get("confirm_password") or ""
        
        # Validation
        if not current_password or not new_password or not confirm_password:
            flash("All fields are required", "warning")
            return render_template("auth/change_password.html")
        
        if new_password != confirm_password:
            flash("New passwords do not match", "danger")
            return render_template("auth/change_password.html")
        
        if len(new_password) < 8:
            flash("Password must be at least 8 characters", "warning")
            return render_template("auth/change_password.html")
        
        # Verify current password
        user_row = get_user_by_username(user['username'])
        if not user_row or not verify_password(user_row, current_password):
            flash("Current password is incorrect", "danger")
            return render_template("auth/change_password.html")
        
        # Update password
        try:
            set_password(user['id'], new_password)
            
            record_audit(user, "password_change", "auth", f"Password changed for user: {user['username']}")
            
            flash("Password changed successfully", "success")
            # After successful login
            return redirect(url_for("home.index"))
        
        except Exception as e:
            flash(f"Failed to change password: {str(e)}", "danger")
            return render_template("auth/change_password.html")
    
    # GET request
    return render_template("auth/change_password.html")