# app/modules/home/views.py
"""
Home module views - Landing page accessible to all users
"""

from flask import Blueprint, render_template, redirect, url_for
from app.modules.auth.security import login_required, current_user
from app.modules.users.permissions import PermissionManager

bp = Blueprint("home", __name__, url_prefix="/home", template_folder="templates")


@bp.route("/")
@bp.route("/index")
@login_required
def index():
    """
    Home page - accessible to all authenticated users.
    Shows personalized dashboard based on user's permissions.
    """
    cu = current_user()
    
    if not cu:
        return redirect(url_for("auth.login"))
    
    # Get user's effective permissions
    effective_perms = PermissionManager.get_effective_permissions(cu)
    
    # Check if user has any module access
    has_modules = (
        effective_perms.get("can_send") or
        effective_perms.get("can_inventory") or
        effective_perms.get("can_asset") or
        effective_perms.get("can_fulfillment_customer") or
        effective_perms.get("can_fulfillment_service") or
        effective_perms.get("can_fulfillment_manager") or
        effective_perms.get("can_admin_users") or
        cu.get("permission_level")
    )
    
    # Get module-specific metrics if user has access
    metrics = {}
    
    # Send module metrics
    if effective_perms.get("can_send") or cu.get("permission_level"):
        try:
            from app.modules.send.storage import get_package_stats
            metrics['send'] = get_package_stats()
        except:
            metrics['send'] = None
    
    # Inventory module metrics
    if effective_perms.get("can_inventory") or cu.get("permission_level"):
        try:
            from app.modules.inventory.storage import get_inventory_summary
            metrics['inventory'] = get_inventory_summary()
        except:
            metrics['inventory'] = None
    
    # Fulfillment module metrics
    if effective_perms.get("can_fulfillment_service") or effective_perms.get("can_fulfillment_manager") or cu.get("permission_level"):
        try:
            from app.modules.fulfillment.storage import get_queue_stats
            metrics['fulfillment'] = get_queue_stats()
        except:
            metrics['fulfillment'] = None
    
    # Format user display name
    if cu.get('first_name') and cu.get('last_name'):
        display_name = f"{cu['first_name']} {cu['last_name']}"
    elif cu.get('first_name'):
        display_name = cu['first_name']
    else:
        display_name = cu['username']
    
    return render_template(
        "home/index.html",
        active="home",
        display_name=display_name,
        has_modules=has_modules,
        metrics=metrics,
        **effective_perms
    )