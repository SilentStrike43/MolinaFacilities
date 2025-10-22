# app/modules/users/views.py
import json
from flask import Blueprint, render_template, request, redirect, url_for, flash

from app.modules.auth.security import (
    login_required, 
    require_admin, 
    current_user, 
    record_audit,
)

from app.modules.users.models import (
    get_user_by_id,
    create_user as core_create_user,
    set_password,
    users_db
)

users_bp = Blueprint("users", __name__, url_prefix="/users", template_folder="templates")
bp = users_bp

# ---------- Database helpers ----------
def get_db():
    """Get users database connection."""
    from app.modules.users.models import users_db
    return users_db()

def list_users(include_system=False):
    """List all users."""
    con = get_db()
    if include_system:
        rows = con.execute("SELECT * FROM users ORDER BY username").fetchall()
    else:
        rows = con.execute("""
            SELECT * FROM users 
            WHERE username NOT IN ('system', 'sysadmin')
            ORDER BY username
        """).fetchall()
    con.close()
    return rows

def create_user(data: dict) -> int:
    """Create a new user with profile and caps."""
    username = data["username"]
    password = data["password"]
    
    # Build caps dict with BOTH new and legacy names for compatibility
    caps = {
        # New standard names (can_*)
        "can_send": bool(data.get("can_send")),
        "can_asset": bool(data.get("can_asset")),
        "can_inventory": bool(data.get("can_asset")),  # Inventory = assets
        "can_insights": bool(data.get("can_insights")),
        "can_users": bool(data.get("can_users")),
        "can_fulfillment_staff": bool(data.get("can_fulfillment_staff")),
        "can_fulfillment_customer": bool(data.get("can_fulfillment_customer")),
        
        # Legacy names for backward compatibility
        "send": bool(data.get("can_send")),
        "asset": bool(data.get("can_asset")),
        "inventory": bool(data.get("can_asset")),
        "insights": bool(data.get("can_insights")),
        "users": bool(data.get("can_users")),
        "fulfillment_staff": bool(data.get("can_fulfillment_staff")),
        "fulfillment_customer": bool(data.get("can_fulfillment_customer")),
    }
    
    con = get_db()
    from werkzeug.security import generate_password_hash
    cur = con.execute("""
        INSERT INTO users(username, password_hash, caps, is_admin, is_sysadmin)
        VALUES (?,?,?,?,?)
    """, (username, generate_password_hash(password), json.dumps(caps), 0, 0))
    uid = cur.lastrowid
    con.commit()
    con.close()
    return uid

def delete_user(uid: int):
    """Soft delete a user by setting a deleted flag (or hard delete if preferred)."""
    con = get_db()
    con.execute("DELETE FROM users WHERE id=?", (uid,))
    con.commit()
    con.close()

# ---------- Permission helpers ----------
def _can_view_users(u) -> bool:
    if not u:
        return False
    caps = {}
    try:
        caps = json.loads(u.get("caps") or "{}")
    except:
        pass
    return bool(
        caps.get("users") or 
        u.get("is_admin") or 
        u.get("is_sysadmin")
    )

def _can_edit_users(u) -> bool:
    if not u:
        return False
    return bool(
        u.get("is_admin") or 
        u.get("is_sysadmin") or 
        _can_view_users(u)
    )

def _can_set_fulfillment(u) -> bool:
    if not u:
        return False
    return bool(u.get("is_admin") or u.get("is_sysadmin"))

def _update_user_partial(uid: int, data: dict):
    """Update only allowed columns."""
    # Parse existing caps
    u = get_user_by_id(uid)
    if not u:
        return
    
    try:
        caps = json.loads(u["caps"] or "{}")
    except:
        caps = {}
    
    # Update caps
    if "can_send" in data:
        caps["can_send"] = bool(data["can_send"])
    if "can_asset" in data:
        caps["inventory"] = bool(data["can_asset"])
    if "can_insights" in data:
        caps["insights"] = bool(data["can_insights"])
    if "can_users" in data:
        caps["users"] = bool(data["can_users"])
    if "can_fulfillment_staff" in data:
        caps["fulfillment_staff"] = bool(data["can_fulfillment_staff"])
    if "can_fulfillment_customer" in data:
        caps["fulfillment_customer"] = bool(data["can_fulfillment_customer"])
    
    con = get_db()
    con.execute("UPDATE users SET caps=? WHERE id=?", (json.dumps(caps), uid))
    con.commit()
    con.close()

# ---------- Routes ----------
@users_bp.route("/")
@login_required
def user_list():
    u = current_user()
    if not _can_view_users(u):
        flash("You don't have access to Users.", "danger")
        return redirect(url_for("home"))

    q = (request.args.get("q") or "").strip().lower()
    include_inactive = bool(request.args.get("all"))

    rows = list_users(include_system=False)
    
    # Simple client-side filtering
    filtered = []
    for r in rows:
        if q:
            searchable = " ".join([
                r["username"] or "",
                str(r.get("id", ""))
            ]).lower()
            if q not in searchable:
                continue
        filtered.append(r)

    return render_template("users/list.html",
                           active="users", tab="list",
                           rows=filtered, q=q, show_all=include_inactive)

@users_bp.route("/manage", methods=["GET", "POST"])
@login_required
def manage():
    cu = current_user()
    if not _can_edit_users(cu):
        flash("You don't have permission to modify users.", "danger")
        return redirect(url_for("users.user_list"))

    if request.method == "POST":
        uid = int(request.form.get("uid") or 0)
        target = get_user_by_id(uid)
        if not target:
            flash("User not found.", "warning")
            return redirect(url_for("users.manage"))

        # Build payload
        payload = {
            "can_send":     1 if request.form.get("can_send") else 0,
            "can_asset":    1 if request.form.get("can_asset") else 0,
            "can_insights": 1 if request.form.get("can_insights") else 0,
            "can_users":    1 if request.form.get("can_users") else 0,
        }

        # Fulfillment flags only if admin/sysadmin
        if _can_set_fulfillment(cu):
            payload["can_fulfillment_staff"] = 1 if request.form.get("can_fulfillment_staff") else 0
            payload["can_fulfillment_customer"] = 1 if request.form.get("can_fulfillment_customer") else 0

        _update_user_partial(uid, payload)
        record_audit(cu, "update_user", "users", f"Updated user {target['username']}")
        flash("User saved.", "success")
        return redirect(url_for("users.manage"))

    rows = list_users(include_system=False)
    
    # FIXED: Convert sqlite3.Row objects to dicts and parse caps for display
    display_rows = []
    for row in rows:
        # CRITICAL: Must convert Row to dict FIRST
        row_dict = dict(row)
        
        # Now safely modify the dict
        try:
            caps = json.loads(row_dict.get("caps") or "{}")
            row_dict["can_send"] = caps.get("can_send", False)
            row_dict["can_asset"] = caps.get("inventory", False)
            row_dict["can_insights"] = caps.get("insights", False)
            row_dict["can_users"] = caps.get("users", False)
            row_dict["can_fulfillment_staff"] = caps.get("fulfillment_staff", False)
            row_dict["can_fulfillment_customer"] = caps.get("fulfillment_customer", False)
        except Exception as e:
            # If caps parsing fails, default to False
            row_dict["can_send"] = False
            row_dict["can_asset"] = False
            row_dict["can_insights"] = False
            row_dict["can_users"] = False
            row_dict["can_fulfillment_staff"] = False
            row_dict["can_fulfillment_customer"] = False
        
        display_rows.append(row_dict)
    
    return render_template("users/manage.html",
                           active="users", tab="manage",
                           rows=display_rows,
                           can_set_fulfillment=_can_set_fulfillment(cu))

@users_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    cu = current_user()
    if not _can_edit_users(cu):
        flash("You don't have permission to create users.", "danger")
        return redirect(url_for("users.user_list"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()
        
        if not username or not password:
            flash("Username and password are required.", "danger")
            return redirect(url_for("users.create"))

        data = {
            "username": username,
            "password": password,
            "can_send":     1 if request.form.get("can_send") else 0,
            "can_asset":    1 if request.form.get("can_asset") else 0,
            "can_insights": 1 if request.form.get("can_insights") else 0,
            "can_users":    1 if request.form.get("can_users") else 0,
            "can_fulfillment_staff": 1 if (_can_set_fulfillment(cu) and request.form.get("can_fulfillment_staff")) else 0,
            "can_fulfillment_customer": 1 if (_can_set_fulfillment(cu) and request.form.get("can_fulfillment_customer")) else 0,
        }
        
        create_user(data)
        record_audit(cu, "create_user", "users", f"Created user {username}")
        flash("User created.", "success")
        return redirect(url_for("users.manage"))

    return render_template("users/create.html", active="users", tab="manage")

@users_bp.route("/<int:uid>/delete", methods=["POST"])
@login_required
def delete(uid: int):
    cu = current_user()
    if not _can_edit_users(cu):
        flash("You don't have permission to deactivate users.", "danger")
        return redirect(url_for("users.user_list"))
    
    u = get_user_by_id(uid)
    if not u:
        flash("User not found.", "warning")
        return redirect(url_for("users.manage"))
    
    delete_user(uid)
    record_audit(cu, "delete_user", "users", f"Deleted user {u['username']}")
    flash("User deactivated.", "success")
    return redirect(url_for("users.manage"))