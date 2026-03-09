# app/modules/home/views.py
"""
Home module views - Landing page accessible to all users
"""

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,  # ← ADD THIS
    g,
    session
)
from app.modules.auth.security import login_required, current_user
from app.core.permissions import PermissionManager

bp = Blueprint("home", __name__, url_prefix="/home", template_folder="templates")


@bp.route('/')
@login_required
def index():
    """Home dashboard - uses sandbox layout for sandbox instance."""
    from flask import g
    from app.modules.auth.security import get_user_instance_context
    from app.core.database import get_db_connection
    from app.core.permissions import PermissionManager
    
    cu = current_user()
    
    # PRIORITY ORDER: URL param → session → user default
    instance_id = (
        request.args.get('instance_id', type=int) or 
        session.get('active_instance_id') or 
        cu.get('instance_id')
    )
    
    # 🔥 CRITICAL: Persist instance_id to session when provided via URL
    if request.args.get('instance_id', type=int):
        session['active_instance_id'] = instance_id
        session.modified = True  # Force session save
    
    # Get enhanced context
    if instance_id is not None:
        user_context = get_user_instance_context(instance_id)
        
        if not user_context:
            flash('Access denied to this instance.', 'danger')
            return redirect(url_for('auth.logout'))
        
        # Check if sandbox
        is_sandbox = False
        instance_name = "Unknown Instance"
        try:
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT is_sandbox, name, display_name 
                    FROM instances 
                    WHERE id = %s
                """, (instance_id,))
                inst = cursor.fetchone()
                cursor.close()
                if inst:
                    is_sandbox = inst['is_sandbox']
                    instance_name = inst['display_name'] or inst['name']
        except:
            pass
        
        g.cu = user_context
        
        # Get user's display name
        display_name = user_context.get('first_name') or user_context.get('username')
        
        # Get all effective permissions at once
        perms = PermissionManager.get_effective_permissions(user_context)

        # Check if elevated (admin level)
        elevated = user_context.get('permission_level') in ['L1', 'L2', 'L3', 'S1']

        # Extract module permissions
        can_send = perms['can_send']
        can_inventory = perms['can_inventory']
        can_asset = perms['can_inventory']  # Alias
        can_fulfillment_customer = perms['can_fulfillment_customer']
        can_fulfillment_service = perms['can_fulfillment_service']
        can_fulfillment_manager = perms['can_fulfillment_manager']
        can_admin_users = perms['can_admin_users'] or elevated
        
        # Check if user has ANY module access
        has_modules = (can_send or can_inventory or can_asset or 
                      can_fulfillment_customer or can_fulfillment_service or 
                      can_fulfillment_manager or can_admin_users or elevated)
        
        # Get module metrics if user has permissions
        metrics = {
            'send': None,
            'inventory': None,
            'fulfillment': None
        }
        
        if can_send or elevated:
            try:
                with get_db_connection("send") as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT 
                            COUNT(*) FILTER (WHERE status = 'pending') as pending,
                            COUNT(*) FILTER (WHERE status = 'shipped') as shipped
                        FROM package_manifest
                        WHERE instance_id = %s
                    """, (instance_id,))
                    result = cursor.fetchone()
                    cursor.close()
                    if result:
                        metrics['send'] = {
                            'pending': result['pending'] or 0,
                            'shipped': result['shipped'] or 0
                        }
            except:
                pass
        
        if can_inventory or can_asset or elevated:
            try:
                with get_db_connection("inventory") as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT
                            COUNT(*) as total_items,
                            COUNT(*) FILTER (WHERE quantity < 10) as low_stock
                        FROM assets
                        WHERE instance_id = %s
                    """, (instance_id,))
                    result = cursor.fetchone()
                    cursor.close()
                    if result:
                        metrics['inventory'] = {
                            'total_items': result['total_items'] or 0,
                            'low_stock': result['low_stock'] or 0
                        }
            except:
                pass
        
        if can_fulfillment_service or can_fulfillment_manager or elevated:
            try:
                with get_db_connection("fulfillment") as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT 
                            COUNT(*) FILTER (WHERE status IN ('pending', 'in_progress')) as queue,
                            COUNT(*) FILTER (WHERE status = 'completed') as completed
                        FROM service_requests
                        WHERE instance_id = %s
                    """, (instance_id,))
                    result = cursor.fetchone()
                    cursor.close()
                    if result:
                        metrics['fulfillment'] = {
                            'queue': result['queue'] or 0,
                            'completed': result['completed'] or 0
                        }
            except:
                pass
        
        # CHOOSE TEMPLATE BASED ON SANDBOX
        if is_sandbox:
            # Use sandbox layout (dark theme)
            return render_template(
                'home/sandbox_index.html',
                active='home',
                cu=user_context,
                instance_id=instance_id
            )
        else:
            # Use regular layout (light theme) with FULL CONTEXT
            return render_template(
                'home/index.html',
                active='home',
                cu=user_context,
                instance_id=instance_id,
                is_sandbox=is_sandbox,
                instance_name=instance_name,
                display_name=display_name,
                has_modules=has_modules,
                elevated=elevated,
                can_send=can_send,
                can_inventory=can_inventory,
                can_asset=can_asset,
                can_fulfillment_customer=can_fulfillment_customer,
                can_fulfillment_service=can_fulfillment_service,
                can_fulfillment_manager=can_fulfillment_manager,
                can_admin_users=can_admin_users,
                metrics=metrics
            )
    
    # Redirect logic for users without instance_id in URL
    perm_level = cu.get('permission_level')
    
    if perm_level in ['L3', 'S1']:
        try:
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM instances WHERE is_sandbox = true LIMIT 1")
                sandbox = cursor.fetchone()
                cursor.close()
                if sandbox:
                    return redirect(url_for('home.index', instance_id=sandbox['id']))
        except:
            pass
    
    # Fallback
    user_instance_id = cu.get('instance_id')
    if user_instance_id:
        return redirect(url_for('home.index', instance_id=user_instance_id))
    
    flash('No instance assigned.', 'warning')
    return redirect(url_for('auth.logout'))