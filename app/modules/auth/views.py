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
    """Login page and handler"""
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        
        if not username or not password:
            flash("Username and password are required", "warning")
            return render_template("auth/login.html")
        
        # Get user from database (returns sqlite3.Row)
        user_row = get_user_by_username(username)
        
        if not user_row or not verify_password(user_row, password):
            flash("Invalid username or password", "danger")
            record_audit(None, "failed_login", "auth", f"Failed login attempt for: {username}")
            return render_template("auth/login.html")
        
        # Successful login - convert to dict for easier access
        user = row_to_dict(user_row)
        
        session["uid"] = user["id"]
        session["username"] = user["username"]
        session.permanent = True
        
        # Get display name for greeting (these fields might not exist)
        first_name = user.get("first_name", "").strip() if "first_name" in user else ""
        last_name = user.get("last_name", "").strip() if "last_name" in user else ""
        
        if first_name and last_name:
            display_name = f"{first_name} {last_name}"
        elif first_name:
            display_name = first_name
        else:
            display_name = username
        
        flash(f"Welcome back, {display_name}!", "success")
        
        record_audit(user, "login", "auth", f"User logged in: {username}")
        
        return redirect(url_for("home"))
    
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
            return redirect(url_for("home"))
        
        except Exception as e:
            flash(f"Failed to change password: {str(e)}", "danger")
            return render_template("auth/change_password.html")
    
    # GET request
    return render_template("auth/change_password.html")