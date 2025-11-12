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
    g
)
from app.modules.auth.security import login_required, current_user
from app.modules.users.permissions import PermissionManager

bp = Blueprint("home", __name__, url_prefix="/home", template_folder="templates")


@bp.route('/')
@login_required
def index():
    """Home dashboard - uses sandbox layout for sandbox instance."""
    from flask import g
    from app.modules.auth.security import get_user_instance_context
    from app.core.database import get_db_connection
    
    cu = current_user()
    instance_id = request.args.get('instance_id', type=int)
    
    # Get enhanced context
    if instance_id is not None:
        user_context = get_user_instance_context(instance_id)
        
        if not user_context:
            flash('Access denied to this instance.', 'danger')
            return redirect(url_for('auth.logout'))
        
        # Check if sandbox
        is_sandbox = False
        try:
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT is_sandbox FROM instances WHERE id = %s", (instance_id,))
                inst = cursor.fetchone()
                cursor.close()
                if inst:
                    is_sandbox = inst['is_sandbox']
        except:
            pass
        
        g.cu = user_context
        
        # CHOOSE TEMPLATE BASED ON SANDBOX
        if is_sandbox:
            # Use sandbox layout (dark theme)
            return render_template(
                'home/sandbox_index.html',  # New sandbox-specific template
                active='home',
                cu=user_context,
                instance_id=instance_id
            )
        else:
            # Use regular layout (light theme)
            return render_template(
                'home/index.html',
                active='home',
                cu=user_context,
                instance_id=instance_id
            )
    
    # Redirect logic (same as before)
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