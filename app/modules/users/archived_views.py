@users_bp.route("/")
@login_required
def user_list():
    """
    List users - Instance-aware:
    - L1: Only see users in their own instance
    - L2: See users in instances they have access to
    - L3/S1: Can view specific instances when switched
    """
    from flask import session
    from app.core.database import get_db_connection
    
    cu = current_user()
    user_level = get_user_permission_level(cu)
    
    # Get instance context from URL, session, or user assignment
    instance_id = (
        request.args.get('instance_id', type=int) or 
        session.get('active_instance_id') or
        cu.get('instance_id')
    )
    
    logger.info(f"🔍 user_list: user={cu.get('username')}, level={user_level}, instance_id={instance_id}")
    
    # L3/S1 redirect ONLY if no instance context
    if user_level in ['L3', 'S1'] and not instance_id:
        flash("Please use Horizon Global Users for cross-instance user management.", "info")
        return redirect(url_for('horizon.global_users'))
    
    # L2 must have access to the requested instance
    if user_level == 'L2':
        accessible = get_accessible_instances(cu)
        
        if instance_id:
            # Verify L2 has access to this specific instance
            if not any(i['id'] == instance_id for i in accessible):
                flash("Access denied to this instance.", "danger")
                return redirect(url_for('users.index'))
        else:
            # No instance specified - show instance selector
            if len(accessible) == 1:
                # Only one instance - go directly to it
                instance_id = accessible[0]['id']
            else:
                # Multiple instances - show selector with user counts
                instance_stats = []
                for inst in accessible:
                    with get_db_connection("core") as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            SELECT COUNT(*) as count 
                            FROM users 
                            WHERE instance_id = %s 
                            AND deleted_at IS NULL
                            AND permission_level NOT IN ('L3', 'S1')
                        """, (inst['id'],))
                        count = cursor.fetchone()['count']
                        cursor.close()
                    
                    instance_stats.append({
                        'instance': inst,
                        'user_count': count
                    })
                
                return render_template(
                    "users/select_instance.html",
                    active="users",
                    instances=instance_stats
                )
    
    # L1 - force to own instance
    elif user_level == 'L1':
        instance_id = cu.get('instance_id')
        if not instance_id:
            flash("No instance assigned.", "danger")
            return redirect(url_for('home.index'))
    
    # Regular users without admin permissions
    elif not user_level:
        instance_id = cu.get('instance_id')
        if not instance_id:
            flash("No instance assigned.", "danger")
            return redirect(url_for('home.index'))
    
        # At this point, instance_id MUST be set
    if not instance_id:
        flash("No instance context available.", "danger")
        return redirect(url_for('home.index'))

    # Get instance info and users - SINGLE DATABASE CONNECTION BLOCK
    with get_db_connection("core") as conn:
        cursor = conn.cursor()
        
        # Get instance details
        cursor.execute("""
            SELECT id, name, display_name, is_active
            FROM instances 
            WHERE id = %s
        """, (instance_id,))
        instance = cursor.fetchone()
        
        if not instance:
            flash("Instance not found.", "danger")
            cursor.close()
            return redirect(url_for('home.index'))
        
        # Get users for this instance
        show_inactive = request.args.get('show_inactive') == 'true'
        
        # ✅ DEFINE params FIRST
        params = [instance_id, instance_id]
        
        # Query includes:
        # 1. Users whose home instance is this one
        # 2. L2 users who have multi-instance access to this instance
        query = """
            SELECT DISTINCT u.id, u.username, u.first_name, u.last_name, u.email, u.phone,
                u.permission_level, u.module_permissions, u.is_active,
                u.created_at, u.last_login, u.department, u.position
            FROM users u
            WHERE u.permission_level NOT IN ('L3', 'S1')
            AND (
                u.instance_id = %s
                OR (
                    u.permission_level = 'L2'
                    AND EXISTS (
                        SELECT 1 FROM user_instance_access uia
                        WHERE uia.user_id = u.id
                        AND uia.instance_id = %s
                    )
                )
            )
        """
        
        if not show_inactive:
            query += " AND u.deleted_at IS NULL AND u.is_active = true"
        
        query += " ORDER BY u.username"
        
        logger.info(f"🔍 Executing query for instance {instance_id}")
        cursor.execute(query, params)  # ✅ Now params is defined
        users = cursor.fetchall()
        cursor.close()

    # ✅ Process users to add display info
    processed_users = []
    for u in users:
        user_dict = dict(u)
        
        # Add permission description
        perm_level = user_dict.get('permission_level') or ''
        user_dict['permission_level_desc'] = PermissionManager.get_permission_description(perm_level)
        
        # Add effective permissions
        user_dict['effective_permissions'] = PermissionManager.get_effective_permissions(user_dict)
        
        processed_users.append(user_dict)

    logger.info(f"📋 User List: Found {len(processed_users)} users for instance {instance_id} ({instance['name']})")
    for u in processed_users:
        logger.info(f"   - {u['username']} ({u.get('permission_level') or 'Module User'})")

    return render_template(
        "users/list.html",
        active="users",
        rows=processed_users,
        instance=instance,
        instance_id=instance_id,
        show_inactive=show_inactive,
        can_manage=user_level in ['L1', 'L2', 'L3', 'S1'],
        can_create=can_create_users(cu),
        q=request.args.get('q', ''),
        show_all=show_inactive,
        cu=cu,
        is_sandbox=(instance.get('is_sandbox', False) if instance else False)
    )

@users_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    """Create new user (L1+ only) - instance-aware."""
    from flask import session
    from app.core.database import get_db_connection
    
    cu = current_user()
    
    if not can_create_users(cu):
        flash("You need L1 (Module Administrator) permissions or higher to create users.", "danger")
        return redirect(url_for("users.index"))
    
    user_level = get_user_permission_level(cu)
    
    # ✅ Get instance_id from URL or session
    instance_id = (
        request.args.get('instance_id', type=int) or 
        session.get('active_instance_id') or
        cu.get('instance_id')
    )
    
    logger.info(f"🔍 create_user: user={cu.get('username')}, level={user_level}, instance_id={instance_id}")
    
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        
        if not username or not password:
            flash("Username and password are required.", "danger")
            return redirect(url_for("users.create", instance_id=instance_id))
        
        # Check if username exists
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
            existing = cursor.fetchone()
            cursor.close()
        
        if existing:
            flash("Username already exists.", "danger")
            return redirect(url_for("users.create", instance_id=instance_id))
        
        # Collect module permissions
        module_perms = []
        if request.form.get("perm_m1"):
            module_perms.append("M1")
        if request.form.get("perm_m2"):
            module_perms.append("M2")
        if request.form.get("perm_m3a"):
            module_perms.append("M3A")
        if request.form.get("perm_m3b"):
            module_perms.append("M3B")
        if request.form.get("perm_m3c"):
            module_perms.append("M3C")
        
        # Validate instance access based on user level
        if user_level == 'L1':
            # L1 can only create users in their own instance
            instance_id = cu.get('instance_id')
        elif user_level == 'L2':
            # L2 must have access to the target instance
            if not instance_id:
                flash("Please specify an instance.", "danger")
                return redirect(url_for('users.index'))
            
            from app.core.instance_access import user_can_access_instance
            if not user_can_access_instance(cu, instance_id):
                flash("Access denied to this instance.", "danger")
                return redirect(url_for('users.index'))
        elif user_level in ['L3', 'S1']:
            # L3/S1 should use Horizon for global user creation
            if not instance_id:
                flash("Please use Horizon to create users across instances.", "info")
                return redirect(url_for('horizon.create_global_user'))
        
        if not instance_id:
            flash("No instance specified.", "danger")
            return redirect(url_for('users.index'))

        # Hash the password
        import hashlib
        pw_hash = hashlib.sha256(password.encode()).hexdigest()

        # Create user
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (
                    username, password_hash, first_name, last_name,
                    email, phone, department, position,
                    permission_level, module_permissions, instance_id,
                    is_active, created_at, created_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP, %s)
                RETURNING id
            """, (
                username, pw_hash,
                request.form.get("first_name", ""),
                request.form.get("last_name", ""),
                request.form.get("email", ""),
                request.form.get("phone", ""),
                request.form.get("department", ""),
                request.form.get("position", ""),
                "",  # permission_level (empty for module users)
                json.dumps(module_perms),
                instance_id,
                cu["id"]
            ))
            uid = cursor.fetchone()['id']
            conn.commit()
            cursor.close()

        record_audit(cu, "create_user", "users", 
                    f"Created user {username} in instance {instance_id} with permissions: {', '.join(module_perms)}")
        
        logger.info(f"✅ Created user: {username} (ID: {uid}) in instance {instance_id}")
        flash(f"User '{username}' created successfully.", "success")
        return redirect(url_for("users.index", instance_id=instance_id))
    
    # GET - show form
    accessible_instances = get_accessible_instances(cu)
    
    # Get instance info for display
    instance = None
    if instance_id:
        with get_db_connection("core") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, display_name 
                FROM instances 
                WHERE id = %s
            """, (instance_id,))
            instance = cursor.fetchone()
            cursor.close()
    
    return render_template("users/create.html",
                         active="users",
                         page="create",
                         instance_id=instance_id,
                         instance=instance,
                         instances=accessible_instances)


@users_bp.route("/edit/<int:uid>", methods=["GET","POST"])
@login_required
def edit_user(uid: int):
    """Edit user (admin only) - instance-aware."""
    cu = current_user()
    user_level = get_user_permission_level(cu)
    
    try:
        target = get_user_by_id(uid)
        
        if not target:
            flash("User not found.", "warning")
            return redirect(url_for("users.index"))
        
        target = row_to_dict(target)
        
        if not can_modify_user(cu, target):
            flash("You cannot modify users at your level or higher.", "danger")
            return redirect(url_for("users.index"))
        
        # Verify instance access
        if user_level == 'L1':
            if target.get('instance_id') != cu.get('instance_id'):
                flash("Access denied - user belongs to different instance.", "danger")
                return redirect(url_for('users.index', instance_id=cu.get('instance_id')))
        elif user_level == 'L2':
            from app.core.instance_access import user_can_access_instance
            if not user_can_access_instance(cu, target.get('instance_id')):
                flash("Access denied - user belongs to instance you cannot access.", "danger")
                return redirect(url_for('users.index'))
        
        if request.method == "POST":
            try:
                # Get form data
                first_name = request.form.get("first_name", "")
                last_name = request.form.get("last_name", "")
                email = request.form.get("email", "")
                phone = request.form.get("phone", "")
                department = request.form.get("department", "")
                position = request.form.get("position", "")
                
                # Get module permissions
                module_perms = []
                if request.form.get("perm_m1"):
                    module_perms.append("M1")
                if request.form.get("perm_m2"):
                    module_perms.append("M2")
                if request.form.get("perm_m3a"):
                    module_perms.append("M3A")
                if request.form.get("perm_m3b"):
                    module_perms.append("M3B")
                if request.form.get("perm_m3c"):
                    module_perms.append("M3C")
                
                # Update database
                with get_db_connection("core") as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE users 
                        SET first_name=%s, last_name=%s, email=%s, phone=%s, 
                            department=%s, position=%s, module_permissions=%s,
                            last_modified_by=%s, last_modified_at=%s
                        WHERE id = %s
                    """, (first_name, last_name, email, phone, 
                          department, position, json.dumps(module_perms),
                          cu["id"], datetime.utcnow(), uid))
                    
                    # Handle L2 multi-instance access
                    if target.get('permission_level') == 'L2':
                        from app.core.instance_access import sync_l2_instance_access
                        
                        instance_ids = request.form.getlist('instance_access[]')
                        instance_ids = [int(i) for i in instance_ids if i]
                        
                        sync_l2_instance_access(uid, instance_ids, cu["id"])
                    
                    conn.commit()
                    cursor.close()
                
                # Record audit
                record_audit(cu, "update_user", "users", f"Updated user {target['username']}")
                
                flash("User updated successfully.", "success")
                return redirect(url_for("users.index", instance_id=target.get('instance_id')))
                
            except Exception as e:
                logger.error(f"ERROR updating user: {e}")
                import traceback
                traceback.print_exc()
                flash(f"Error updating user: {str(e)}", "danger")
        
        # GET: Load data for form
        target["module_permissions_list"] = PermissionManager.parse_module_permissions(
            target.get("module_permissions", "[]")
        )
        
        # Get all instances for L2 selection
        all_instances = []
        user_instance_ids = []
        
        if target.get('permission_level') == 'L2':
            from app.core.instance_access import get_user_instances
            
            with get_db_connection("core") as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, name, display_name FROM instances ORDER BY name")
                all_instances = cursor.fetchall()
                cursor.close()
            
            user_instances = get_user_instances(target)
            user_instance_ids = [inst['id'] for inst in user_instances]
        
        return render_template("users/edit.html",
                             active="users",
                             page="edit",
                             user=target,
                             all_instances=all_instances,
                             user_instance_ids=user_instance_ids)
                             
    except Exception as e:
        logger.error(f"ERROR in edit_user route: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error loading user: {str(e)}", "danger")
        return redirect(url_for("users.index"))