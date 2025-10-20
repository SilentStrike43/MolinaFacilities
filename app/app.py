# Add this to your app/app.py file
# Replace the existing @app.route("/") function with this:

@app.route("/")
def home():
    """Home page - dynamic dashboard with real data"""
    if not current_user():
        return redirect(url_for("auth.login"))
    
    user = current_user()
    
    # Initialize dashboard data
    dashboard_data = {
        'total_assets': 0,
        'pending_requests': 0,
        'shipments_this_month': 0,
        'completed_tasks': 0,
        'recent_activities': [],
        'my_tasks': [],
        'asset_trend': 0,
        'request_trend': 0,
    }
    
    # Get asset count if user has permission
    if user.get('can_asset') or user.get('is_admin') or user.get('is_sysadmin'):
        try:
            from app.modules.inventory.assets import db as assets_db
            con = assets_db()
            
            # Total assets
            result = con.execute("SELECT COUNT(*) as count FROM assets WHERE status='active'").fetchone()
            dashboard_data['total_assets'] = result['count'] if result else 0
            
            # Asset trend (compare to last month - simplified)
            result = con.execute("""
                SELECT COUNT(*) as count FROM asset_ledger 
                WHERE ts_utc >= date('now', '-30 days')
            """).fetchone()
            last_month = result['count'] if result else 0
            
            result = con.execute("""
                SELECT COUNT(*) as count FROM asset_ledger 
                WHERE ts_utc >= date('now', '-60 days') AND ts_utc < date('now', '-30 days')
            """).fetchone()
            prev_month = result['count'] if result else 1
            
            if prev_month > 0:
                dashboard_data['asset_trend'] = int(((last_month - prev_month) / prev_month) * 100)
            
            # Recent asset activities
            recent_assets = con.execute("""
                SELECT al.ts_utc, al.action, a.product, al.username, al.qty
                FROM asset_ledger al
                JOIN assets a ON al.asset_id = a.id
                ORDER BY al.ts_utc DESC
                LIMIT 5
            """).fetchall()
            
            for row in recent_assets:
                dashboard_data['recent_activities'].append({
                    'icon': 'box-seam',
                    'icon_bg': 'rgba(102, 126, 234, 0.1)',
                    'icon_color': '#667eea',
                    'title': f"{row['action'].title()} - {row['product']}",
                    'description': f"{row['qty']} unit(s) by {row['username']}",
                    'time': row['ts_utc'],
                    'type': 'asset'
                })
            
            con.close()
        except Exception as e:
            app.logger.error(f"Failed to load asset data: {e}")
    
    # Get fulfillment data if user has permission
    if user.get('can_fulfillment_staff') or user.get('can_fulfillment_customer') or user.get('is_admin') or user.get('is_sysadmin'):
        try:
            from app.modules.fulfillment.storage import queue_db
            con = queue_db()
            
            # Pending requests
            if user.get('can_fulfillment_staff') or user.get('is_admin') or user.get('is_sysadmin'):
                result = con.execute("""
                    SELECT COUNT(*) as count FROM fulfillment_requests 
                    WHERE is_archived=0 AND status NOT IN ('Completed', 'Cancelled')
                """).fetchone()
                dashboard_data['pending_requests'] = result['count'] if result else 0
                
                # My assigned tasks
                tasks = con.execute("""
                    SELECT id, description, status, date_submitted
                    FROM fulfillment_requests
                    WHERE is_archived=0 
                    AND (assigned_staff_name=? OR status='Received')
                    ORDER BY date_submitted DESC
                    LIMIT 5
                """, (user['username'],)).fetchall()
                
                for task in tasks:
                    dashboard_data['my_tasks'].append({
                        'id': task['id'],
                        'description': task['description'],
                        'status': task['status'],
                        'date': task['date_submitted']
                    })
            else:
                # Customer view - their own requests
                result = con.execute("""
                    SELECT COUNT(*) as count FROM fulfillment_requests 
                    WHERE requester_name=? AND is_archived=0
                """, (user['username'],)).fetchone()
                dashboard_data['pending_requests'] = result['count'] if result else 0
            
            # Completed this month
            result = con.execute("""
                SELECT COUNT(*) as count FROM fulfillment_requests
                WHERE status='Completed' 
                AND date(completed_at) >= date('now', 'start of month')
            """).fetchone()
            dashboard_data['completed_tasks'] = result['count'] if result else 0
            
            # Request trend
            this_month = con.execute("""
                SELECT COUNT(*) as count FROM fulfillment_requests
                WHERE date(date_submitted) >= date('now', 'start of month')
            """).fetchone()
            this_month_count = this_month['count'] if this_month else 0
            
            last_month = con.execute("""
                SELECT COUNT(*) as count FROM fulfillment_requests
                WHERE date(date_submitted) >= date('now', '-1 month', 'start of month')
                AND date(date_submitted) < date('now', 'start of month')
            """).fetchone()
            last_month_count = last_month['count'] if last_month else 1
            
            if last_month_count > 0:
                dashboard_data['request_trend'] = int(((this_month_count - last_month_count) / last_month_count) * 100)
            
            # Recent fulfillment activities
            recent_requests = con.execute("""
                SELECT id, description, status, requester_name, date_submitted
                FROM fulfillment_requests
                ORDER BY date_submitted DESC
                LIMIT 3
            """).fetchall()
            
            for row in recent_requests:
                dashboard_data['recent_activities'].append({
                    'icon': 'file-earmark-text',
                    'icon_bg': 'rgba(240, 147, 251, 0.1)',
                    'icon_color': '#f093fb',
                    'title': f"Request #{row['id']}",
                    'description': row['description'][:50] + ('...' if len(row['description']) > 50 else ''),
                    'time': row['date_submitted'],
                    'type': 'fulfillment',
                    'status': row['status']
                })
            
            con.close()
        except Exception as e:
            app.logger.error(f"Failed to load fulfillment data: {e}")
    
    # Get shipping data if user has permission
    if user.get('can_send') or user.get('is_admin') or user.get('is_sysadmin'):
        try:
            from app.modules.send.storage import send_db
            con = send_db()
            
            # Shipments this month
            result = con.execute("""
                SELECT COUNT(*) as count FROM send_log
                WHERE date(ts_utc) >= date('now', 'start of month')
            """).fetchone()
            dashboard_data['shipments_this_month'] = result['count'] if result else 0
            
            # Recent shipments
            recent_shipments = con.execute("""
                SELECT package_id, checkin_id, ts_utc
                FROM send_log
                ORDER BY ts_utc DESC
                LIMIT 2
            """).fetchall()
            
            for row in recent_shipments:
                dashboard_data['recent_activities'].append({
                    'icon': 'truck',
                    'icon_bg': 'rgba(79, 172, 254, 0.1)',
                    'icon_color': '#4facfe',
                    'title': 'Package Shipped',
                    'description': f"Package #{row['package_id']}",
                    'time': row['ts_utc'],
                    'type': 'shipment'
                })
            
            con.close()
        except Exception as e:
            app.logger.error(f"Failed to load shipping data: {e}")
    
    # Sort activities by time
    dashboard_data['recent_activities'].sort(
        key=lambda x: x.get('time', ''), 
        reverse=True
    )
    
    # Keep only top 10
    dashboard_data['recent_activities'] = dashboard_data['recent_activities'][:10]
    
    return render_template(
        "dashboard.html",
        title="Dashboard",
        data=dashboard_data
    )