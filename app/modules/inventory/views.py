# app/modules/inventory/views.py
import os
import json
import datetime
import logging
from flask import render_template, request, redirect, url_for, flash, jsonify

from app.modules.auth.security import login_required, require_asset, current_user, record_audit
from app.core.database import get_db_connection

from . import bp

inventory_bp = bp

logger = logging.getLogger(__name__)

# ========== HELPER FUNCTIONS ==========

def get_instance_context():
    """Get instance context for sandbox detection."""
    cu = current_user()
    instance_id = (
        request.args.get('instance_id', type=int) or 
        request.form.get('instance_id', type=int) or 
        cu.get('instance_id')
    )
    is_sandbox = (instance_id == 4)
    return instance_id, is_sandbox

def redirect_with_instance(endpoint, **kwargs):
    """Redirect preserving instance_id."""
    instance_id, _ = get_instance_context()
    if instance_id:
        kwargs['instance_id'] = instance_id
    return redirect(url_for(endpoint, **kwargs))

# ---------- CATEGORY AND SKU SYSTEM ----------
INVENTORY_CATEGORIES = {
    "100": {
        "name": "Electronics",
        "prefix": "100",
        "subcategories": {
            "101": "Monitors",
            "102": "Laptops",
            "103": "Desktops",
            "104": "Tablets",
            "105": "Smartphones",
            "106": "Printers",
            "107": "Scanners",
            "108": "Projectors",
            "109": "Cameras",
            "110": "Accessories"
        }
    },
    "200": {
        "name": "Automotive Parts",
        "prefix": "200",
        "subcategories": {
            "201": "Engine Components",
            "202": "Brake Systems",
            "203": "Electrical Parts",
            "204": "Filters",
            "205": "Belts and Hoses",
            "206": "Lighting",
            "207": "Body Parts",
            "208": "Tools",
            "209": "Fluids",
            "210": "General"
        }
    },
    "300": {
        "name": "Medical Equipment",
        "prefix": "300",
        "subcategories": {
            "301": "Diagnostic Equipment",
            "302": "Patient Monitoring",
            "303": "Surgical Instruments",
            "304": "Lab Equipment",
            "305": "Mobility Aids",
            "306": "PPE",
            "307": "First Aid Supplies",
            "308": "Sterilization Equipment",
            "309": "Examination Tools",
            "310": "General Medical"
        }
    },
    "400": {
        "name": "Clothing and Apparel",
        "prefix": "400",
        "subcategories": {
            "401": "Uniforms",
            "402": "Safety Apparel",
            "403": "Corporate Wear",
            "404": "Outerwear",
            "405": "Footwear",
            "406": "Accessories",
            "407": "Headwear",
            "408": "Promotional Apparel",
            "409": "Seasonal",
            "410": "General Apparel"
        }
    },
    "500": {
        "name": "Company Memorabilia",
        "prefix": "500",
        "subcategories": {
            "501": "Awards and Trophies",
            "502": "Branded Merchandise",
            "503": "Gifts",
            "504": "Promotional Items",
            "505": "Corporate Art",
            "506": "Historical Items",
            "507": "Event Materials",
            "508": "Marketing Collateral",
            "509": "Signage",
            "510": "General Memorabilia"
        }
    },
    "600": {
        "name": "Office Supplies",
        "prefix": "600",
        "subcategories": {
            "601": "Writing Instruments",
            "602": "Paper Products",
            "603": "Filing and Storage",
            "604": "Desk Accessories",
            "605": "Binding and Laminating",
            "606": "Presentation Supplies",
            "607": "Cleaning Supplies",
            "608": "Breakroom Supplies",
            "609": "Shipping Supplies",
            "610": "General Office"
        }
    },
    "700": {
        "name": "Furniture",
        "prefix": "700",
        "subcategories": {
            "701": "Desks",
            "702": "Chairs",
            "703": "Tables",
            "704": "Filing Cabinets",
            "705": "Shelving",
            "706": "Conference Room",
            "707": "Reception Furniture",
            "708": "Storage Units",
            "709": "Modular Furniture",
            "710": "General Furniture"
        }
    },
    "800": {
        "name": "Hardware Supplies and Materials",
        "prefix": "800",
        "subcategories": {
            "801": "Fasteners",
            "802": "Tools",
            "803": "Building Materials",
            "804": "Electrical Supplies",
            "805": "Plumbing Supplies",
            "806": "HVAC Components",
            "807": "Safety Equipment",
            "808": "Maintenance Supplies",
            "809": "Construction Equipment",
            "810": "General Hardware"
        }
    }
}

def get_all_categories_flat():
    """Return flat list of all categories for dropdown."""
    categories = []
    for cat_key, cat_data in INVENTORY_CATEGORIES.items():
        for sub_key, sub_name in cat_data["subcategories"].items():
            categories.append({
                "code": sub_key,
                "name": f"{cat_data['name']} - {sub_name}",
                "category": cat_data["name"],
                "subcategory": sub_name
            })
    return categories

def get_category_info(sku: str) -> dict:
    """Extract category information from SKU."""
    if not sku or len(sku) < 3:
        return {"category": "Unknown", "subcategory": "Unknown"}
    
    category_code = sku[:3]
    
    for cat_key, cat_data in INVENTORY_CATEGORIES.items():
        if category_code in cat_data["subcategories"]:
            return {
                "category": cat_data["name"],
                "subcategory": cat_data["subcategories"][category_code],
                "code": category_code
            }
    
    return {"category": "Unknown", "subcategory": "Unknown", "code": category_code}

def generate_next_sku(category_code: str) -> str:
    """Generate next SKU for given category code."""
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        
        prefix = category_code
        cursor.execute("""
            SELECT sku FROM assets 
            WHERE sku LIKE %s 
            ORDER BY sku DESC LIMIT 1
        """, (f"{prefix}-%",))
        
        result = cursor.fetchone()
        cursor.close()
        
        if result:
            last_sku = result['sku']
            try:
                last_num = int(last_sku.split("-")[1])
                next_num = last_num + 1
            except:
                next_num = 1
        else:
            next_num = 1
        
        return f"{prefix}-{next_num:06d}"

def create_asset(data: dict) -> int:
    """Create new asset in database."""
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO assets(sku, product, uom, location, qty_on_hand, manufacturer, part_number, serial_number, pii, notes, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            data.get("sku", ""),
            data.get("product", ""),
            data.get("uom", "EA"),
            data.get("location", ""),
            int(data.get("qty_on_hand", 0)),
            data.get("manufacturer", ""),
            data.get("part_number", ""),
            data.get("serial_number", ""),
            data.get("pii", ""),
            data.get("notes", ""),
            data.get("status", "active")
        ))
        
        result = cursor.fetchone()
        asset_id = result['id']
        cursor.close()
        return asset_id

def record_initial_checkin(asset_id: int, qty: int, username: str, note: str = "Initial inventory"):
    """Record initial check-in to ledger and log to insights."""
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO asset_ledger(asset_id, action, qty, username, note)
            VALUES (%s, 'CHECKIN', %s, %s, %s)
        """, (asset_id, qty, username, note))
        conn.commit()
        cursor.close()
    
    log_to_insights(asset_id, "CHECKIN", qty, username, note)

def log_to_insights(asset_id: int, action: str, qty: int, username: str, note: str = ""):
    """Log asset movements to insights for reporting."""
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM assets WHERE id=%s", (asset_id,))
        asset = cursor.fetchone()
        cursor.close()
    
    if not asset:
        return
    
    asset_dict = dict(asset)
    cat_info = get_category_info(asset_dict.get("sku", ""))
    
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO inventory_reports(
                checkin_date, inventory_id, item_type, manufacturer, product_name,
                submitter_name, notes, part_number, serial_number, count, location, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            datetime.date.today().isoformat(),
            asset_id,
            f"{cat_info['category']} - {cat_info['subcategory']}",
            asset_dict.get("manufacturer", ""),
            asset_dict.get("product", ""),
            username,
            f"{action}: {note}" if note else action,
            asset_dict.get("part_number", "N/A"),
            asset_dict.get("serial_number", "N/A"),
            qty,
            asset_dict.get("location", ""),
            "completed"
        ))
        conn.commit()
        cursor.close()

# ---------- ROUTES ----------

@bp.route("/asset", methods=["GET", "POST"])
@login_required
@require_asset
def asset():
    """Asset Management - Add/Edit Assets with category-based SKU system."""
    cu = current_user()
    instance_id, is_sandbox = get_instance_context()
    
    today = datetime.date.today().isoformat()
    flashmsg = None
    
    categories = get_all_categories_flat()
    
    default_category = "101"
    next_sku_preview = generate_next_sku(default_category)
    
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        
        q = (request.args.get("q") or "").strip()
        status_filter = request.args.get("status", "active")
        
        sql = "SELECT * FROM assets WHERE 1=1"
        params = []
        
        if status_filter != "all":
            sql += " AND status = %s"
            params.append(status_filter)
        
        if q:
            sql += " AND (product LIKE %s OR sku LIKE %s OR location LIKE %s OR manufacturer LIKE %s)"
            params.extend([f"%{q}%"] * 4)
        
        sql += " ORDER BY id DESC LIMIT 100"
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()
    
    if request.method == "POST":
        mode = request.form.get("mode", "create")
        
        if mode == "create":
            category = request.form.get("Category", "101")
            sku = generate_next_sku(category)
            product = (request.form.get("ProductName") or "").strip()
            manufacturer = (request.form.get("Manufacturer") or "").strip()
            location = (request.form.get("Location") or "").strip()
            qty = int(request.form.get("QtyOnHand", 0))
            part_number = (request.form.get("PartNumber") or "").strip()
            serial_number = (request.form.get("SerialNumber") or "").strip()
            pii = (request.form.get("PII") or "").strip()
            notes = (request.form.get("Notes") or "").strip()
            username = cu.get("username", "System")
            
            if not product:
                flashmsg = ("Product name is required.", False)
            else:
                try:
                    cat_info = get_category_info(sku)
                    asset_data = {
                        "sku": sku,
                        "product": product,
                        "manufacturer": manufacturer,
                        "location": location,
                        "qty_on_hand": qty,
                        "part_number": part_number,
                        "serial_number": serial_number,
                        "pii": pii,
                        "notes": notes,
                        "status": "active"
                    }
                    
                    asset_id = create_asset(asset_data)
                    record_initial_checkin(asset_id, qty, username, "Initial inventory")
                    
                    record_audit(cu, "create_asset", "inventory", 
                                f"Created asset #{asset_id}, SKU {sku}: {product}")
                    
                    flashmsg = (f"✅ Asset #{asset_id} created successfully! SKU: {sku}", True)
                    
                except Exception as e:
                    flashmsg = (f"❌ Error creating asset: {str(e)}", False)
                    record_audit(cu, "create_asset_error", "inventory", f"Asset creation error: {str(e)}")
    
        elif mode == "update":
            asset_id = int(request.form.get("id") or 0)
            product = (request.form.get("ProductName") or "").strip()
            manufacturer = (request.form.get("Manufacturer") or "").strip()
            location = (request.form.get("Location") or "").strip()
            uom = request.form.get("UOM", "EA").strip() or "EA"
            notes = (request.form.get("Notes") or "").strip()
            status = request.form.get("Status", "active")
            
            with get_db_connection("inventory") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE assets 
                    SET product=%s, manufacturer=%s, uom=%s, location=%s, notes=%s, status=%s
                    WHERE id=%s
                """, (product, manufacturer, uom, location, notes, status, asset_id))
                conn.commit()
                cursor.close()
            
            record_audit(cu, "update_asset", "inventory", f"Updated asset #{asset_id}")
            flashmsg = (f"✅ Asset #{asset_id} updated successfully.", True)

    edit_id = request.args.get("edit", type=int)
    edit = None
    if edit_id:
        with get_db_connection("inventory") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM assets WHERE id=%s", (edit_id,))
            edit = cursor.fetchone()
            cursor.close()

    return render_template(
        "inventory/asset.html",
        active="inventory",
        flashmsg=flashmsg,
        today=today,
        categories=categories,
        next_sku_preview=next_sku_preview,
        rows=rows,
        q=q,
        status=status_filter,
        edit=edit,
        is_sandbox=is_sandbox,
        instance_id=instance_id
    )

@inventory_bp.route("/asset/<int:asset_id>/delete", methods=["POST"])
@login_required
@require_asset
def delete_asset(asset_id: int):
    """Delete asset (L1+ only)."""
    cu = current_user()
    
    permission_level = cu.get('permission_level', '')
    if permission_level not in ['L1', 'L2', 'L3', 'S1']:
        return jsonify({"success": False, "error": "Only L1+ administrators can delete assets"}), 403
    
    try:
        with get_db_connection("inventory") as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT sku, product FROM assets WHERE id = %s", (asset_id,))
            asset = cursor.fetchone()
            
            if not asset:
                return jsonify({"success": False, "error": "Asset not found"}), 404
            
            cursor.execute("""
                UPDATE assets 
                SET status = 'deleted',
                    notes = CONCAT(notes, '\nDELETED BY: ', %s, ' ON: ', CURRENT_TIMESTAMP)
                WHERE id = %s
            """, (cu['username'], asset_id))
            
            conn.commit()
            cursor.close()
        
        record_audit(cu, "delete_asset", "inventory", 
                    f"Deleted asset #{asset_id}: {asset['sku']} - {asset['product']}")
        
        return jsonify({"success": True, "message": "Asset deleted successfully"})
        
    except Exception as e:
        logger.error(f"Error deleting asset: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@inventory_bp.route("/asset/<int:aid>/edit")
@login_required
@require_asset
def asset_edit(aid: int):
    instance_id, _ = get_instance_context()
    if instance_id:
        return redirect(url_for("inventory.asset", edit=aid, instance_id=instance_id))
    return redirect(url_for("inventory.asset", edit=aid))

@inventory_bp.route("/api/next-sku/<category>")
@login_required
@require_asset
def get_next_sku(category: str):
    """API endpoint to get next SKU for a category (for AJAX)."""
    try:
        next_sku = generate_next_sku(category)
        cat_info = get_category_info(next_sku)
        return jsonify({
            "success": True,
            "sku": next_sku,
            "category": cat_info["category"],
            "subcategory": cat_info["subcategory"]
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@bp.route("/insights")
@login_required
@require_asset
def insights():
    """Asset Analytics - Real insights with charts, trends, and alerts."""
    cu = current_user()
    instance_id, is_sandbox = get_instance_context()
    
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                COUNT(DISTINCT asset_id) as unique_assets,
                COUNT(*) as total_movements,
                SUM(CASE WHEN action='CHECKIN' THEN qty ELSE 0 END) as total_checkins,
                SUM(CASE WHEN action='CHECKOUT' THEN qty ELSE 0 END) as total_checkouts,
                COUNT(DISTINCT username) as active_users
            FROM asset_ledger
            WHERE ts_utc >= CURRENT_DATE - INTERVAL '30 days'
        """)
        summary = cursor.fetchone()
        
        cursor.execute("""
            SELECT 
                DATE(ts_utc) as date,
                SUM(CASE WHEN action='CHECKIN' THEN 1 ELSE 0 END) as checkins,
                SUM(CASE WHEN action='CHECKOUT' THEN 1 ELSE 0 END) as checkouts,
                SUM(CASE WHEN action='ADJUST' THEN 1 ELSE 0 END) as adjustments
            FROM asset_ledger
            WHERE ts_utc >= CURRENT_DATE - INTERVAL '14 days'
            GROUP BY DATE(ts_utc)
            ORDER BY date ASC
        """)
        activity_trend = cursor.fetchall()
        
        cursor.execute("""
            SELECT 
                a.sku,
                a.product,
                a.qty_on_hand,
                COUNT(*) as total_movements,
                SUM(CASE WHEN l.action='CHECKIN' THEN 1 ELSE 0 END) as checkins,
                SUM(CASE WHEN l.action='CHECKOUT' THEN 1 ELSE 0 END) as checkouts
            FROM asset_ledger l
            JOIN assets a ON l.asset_id = a.id
            WHERE l.ts_utc >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY a.id, a.sku, a.product, a.qty_on_hand
            ORDER BY total_movements DESC
            LIMIT 10
        """)
        top_assets = cursor.fetchall()
        
        cursor.execute("""
            SELECT 
                username,
                COUNT(*) as total_actions,
                SUM(CASE WHEN action='CHECKIN' THEN 1 ELSE 0 END) as checkins,
                SUM(CASE WHEN action='CHECKOUT' THEN 1 ELSE 0 END) as checkouts,
                MAX(ts_utc) as last_activity
            FROM asset_ledger
            WHERE ts_utc >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY username
            ORDER BY total_actions DESC
            LIMIT 10
        """)
        user_stats = cursor.fetchall()
        
        cursor.execute("""
            SELECT 
                sku,
                product,
                manufacturer,
                location,
                qty_on_hand
            FROM assets
            WHERE qty_on_hand <= 5 AND status = 'active'
            ORDER BY qty_on_hand ASC
            LIMIT 20
        """)
        low_stock = cursor.fetchall()
        
        cursor.execute("""
            SELECT 
                LEFT(sku, 3) as category_code,
                COUNT(*) as asset_count,
                SUM(qty_on_hand) as total_quantity
            FROM assets
            WHERE status = 'active'
            GROUP BY LEFT(sku, 3)
            ORDER BY asset_count DESC
        """)
        category_breakdown = cursor.fetchall()
        
        for cat in category_breakdown:
            code = cat['category_code']
            cat_info = get_category_info(f"{code}-000001")
            cat['category_name'] = cat_info.get('category', 'Unknown')
        
        cursor.execute("""
            SELECT 
                l.ts_utc as timestamp,
                l.action,
                l.qty,
                l.username,
                a.sku,
                a.product
            FROM asset_ledger l
            JOIN assets a ON l.asset_id = a.id
            WHERE l.ts_utc >= NOW() - INTERVAL '24 hours'
            ORDER BY l.ts_utc DESC
            LIMIT 15
        """)
        recent_activity = cursor.fetchall()
        
        cursor.close()
    
    return render_template(
        "inventory/insights.html",
        active="insights_inv",
        summary=summary,
        activity_trend=activity_trend,
        top_assets=top_assets,
        user_stats=user_stats,
        low_stock=low_stock,
        category_breakdown=category_breakdown,
        recent_activity=recent_activity,
        is_sandbox=is_sandbox,
        instance_id=instance_id
    )

@inventory_bp.route("/insights/export")
@login_required
@require_asset
def insights_export():
    """Export inventory insights as CSV."""
    import io
    import csv
    from flask import send_file
    
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM inventory_reports ORDER BY ts_utc DESC")
        rows = cursor.fetchall()
        cursor.close()
    
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["ts_utc","inventory_id","product_name","manufacturer","item_type","submitter_name","notes","count","location"])
    for r in rows:
        row_dict = dict(zip([col[0] for col in r.cursor_description], r)) if hasattr(r, 'cursor_description') else dict(r)
        w.writerow([row_dict.get("ts_utc"), row_dict.get("inventory_id"), row_dict.get("product_name"), 
                    row_dict.get("manufacturer"), row_dict.get("item_type"), row_dict.get("submitter_name"), 
                    row_dict.get("notes"), row_dict.get("count", ""), row_dict.get("location", "")])
    
    mem = io.BytesIO(out.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="insights_inventory.csv")

@bp.route("/ledger")
@login_required
@require_asset
def ledger():
    """Asset Ledger - Track all asset movements (check-ins, check-outs, adjustments)."""
    cu = current_user()
    instance_id, is_sandbox = get_instance_context()
    
    search = request.args.get('search', '').strip()
    action_filter = request.args.get('action_filter', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        
        sql = """
            SELECT 
                l.id,
                l.asset_id,
                l.action,
                l.qty as quantity,
                l.username as actor,
                l.note as notes,
                l.ts_utc as timestamp,
                a.sku as inventory_id,
                a.product as product_name,
                a.manufacturer,
                a.location,
                a.qty_on_hand as current_quantity
            FROM asset_ledger l
            JOIN assets a ON l.asset_id = a.id
            WHERE 1=1
        """
        params = []
        
        if search:
            sql += " AND (a.sku LIKE %s OR a.product LIKE %s OR l.username LIKE %s)"
            search_term = f"%{search}%"
            params.extend([search_term, search_term, search_term])
        
        if action_filter:
            sql += " AND l.action = %s"
            params.append(action_filter.upper())
        
        if date_from:
            sql += " AND DATE(l.ts_utc) >= %s"
            params.append(date_from)
        
        if date_to:
            sql += " AND DATE(l.ts_utc) <= %s"
            params.append(date_to)
        
        sql += " ORDER BY l.ts_utc DESC LIMIT 200"
        
        cursor.execute(sql, params)
        ledger_entries = cursor.fetchall()
        
        cursor.execute("""
            SELECT 
                COUNT(CASE WHEN action = 'CHECKIN' AND DATE(ts_utc) = CURRENT_DATE THEN 1 END) as check_ins_today,
                COUNT(CASE WHEN action = 'CHECKOUT' AND DATE(ts_utc) = CURRENT_DATE THEN 1 END) as check_outs_today,
                COUNT(CASE WHEN action = 'ADJUST' AND DATE(ts_utc) = CURRENT_DATE THEN 1 END) as adjustments_today
            FROM asset_ledger
        """)
        stats = cursor.fetchone()
        
        cursor.execute("""
            SELECT id, sku as inventory_id, product as product_name 
            FROM assets 
            WHERE status = 'active'
            ORDER BY sku
        """)
        assets = cursor.fetchall()
        
        cursor.close()
    
    return render_template(
        "inventory/ledger.html",
        active="ledger",
        ledger_entries=ledger_entries,
        stats=stats,
        assets=assets,
        is_sandbox=is_sandbox,
        instance_id=instance_id
    )

@bp.route("/ledger/quick-entry", methods=["POST"])
@login_required
@require_asset
def quick_ledger_entry():
    """Quick add ledger entry from the ledger page."""
    cu = current_user()
    instance_id, _ = get_instance_context()
    
    asset_id = request.form.get("asset_id", type=int)
    action = request.form.get("action", "").strip().upper()
    quantity = request.form.get("quantity", type=int)
    notes = request.form.get("notes", "").strip()
    username = cu.get("username", "System")
    
    action_map = {
        "CHECK_IN": "CHECKIN",
        "CHECK_OUT": "CHECKOUT",
        "ADJUST": "ADJUST"
    }
    action = action_map.get(action, action)
    
    if not asset_id or not action or not quantity:
        flash("❌ Asset, action, and quantity are required.", "danger")
        return redirect_with_instance('inventory.ledger')
    
    try:
        with get_db_connection("inventory") as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT qty_on_hand, product, sku FROM assets WHERE id = %s", (asset_id,))
            asset = cursor.fetchone()
            
            if not asset:
                flash("❌ Asset not found.", "danger")
                return redirect_with_instance('inventory.ledger')
            
            current_qty = asset['qty_on_hand']
            
            if action == 'CHECKIN':
                new_qty = current_qty + quantity
            elif action == 'CHECKOUT':
                new_qty = current_qty - quantity
                if new_qty < 0:
                    flash("❌ Cannot check out more than available quantity.", "danger")
                    return redirect_with_instance('inventory.ledger')
            else:
                new_qty = quantity
            
            cursor.execute("""
                INSERT INTO asset_ledger (asset_id, action, qty, username, note, ts_utc)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            """, (asset_id, action, quantity, username, notes))
            
            cursor.execute("""
                UPDATE assets 
                SET qty_on_hand = %s 
                WHERE id = %s
            """, (new_qty, asset_id))
            
            conn.commit()
            cursor.close()
        
        log_to_insights(asset_id, action, quantity, username, notes)
        
        record_audit(cu, "ledger_entry", "inventory", 
                    f"{action} {quantity} units of {asset['product']} (SKU: {asset['sku']})")
        
        flash(f"✅ Ledger entry added! {action}: {quantity} units", "success")
        
    except Exception as e:
        logger.error(f"Error adding ledger entry: {e}")
        flash(f"❌ Error: {str(e)}", "danger")
    
    return redirect_with_instance('inventory.ledger')

@bp.route("/ledger/export")
@login_required
@require_asset
def export_ledger():
    """Export ledger as CSV."""
    import io
    import csv
    from flask import send_file
    
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                l.ts_utc,
                a.sku as inventory_id,
                a.product as product_name,
                a.manufacturer,
                l.action,
                l.qty as quantity,
                l.username as actor,
                l.note as notes
            FROM asset_ledger l
            JOIN assets a ON l.asset_id = a.id
            ORDER BY l.ts_utc DESC
        """)
        rows = cursor.fetchall()
        cursor.close()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Timestamp", "Inventory ID", "Product", "Manufacturer", "Action", "Quantity", "Actor", "Notes"])
    
    for row in rows:
        writer.writerow([
            row['ts_utc'],
            row['inventory_id'],
            row['product_name'],
            row['manufacturer'],
            row['action'],
            row['quantity'],
            row['actor'],
            row['notes'] or ''
        ])
    
    mem = io.BytesIO(output.getvalue().encode('utf-8'))
    mem.seek(0)
    
    filename = f"asset_ledger_{datetime.date.today().isoformat()}.csv"
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name=filename)

@bp.route("/ledger/<int:entry_id>/delete", methods=["POST"])
@login_required
@require_asset
def delete_ledger_entry(entry_id: int):
    """Delete a ledger entry (L1+ only)."""
    cu = current_user()
    
    permission_level = cu.get('permission_level', '')
    if permission_level not in ['L1', 'L2', 'L3', 'S1']:
        return jsonify({"success": False, "error": "Only L1+ administrators can delete ledger entries"}), 403
    
    try:
        with get_db_connection("inventory") as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT l.*, a.sku, a.product 
                FROM asset_ledger l
                JOIN assets a ON l.asset_id = a.id
                WHERE l.id = %s
            """, (entry_id,))
            entry = cursor.fetchone()
            
            if not entry:
                return jsonify({"success": False, "error": "Entry not found"}), 404
            
            cursor.execute("DELETE FROM asset_ledger WHERE id = %s", (entry_id,))
            
            conn.commit()
            cursor.close()
        
        record_audit(cu, "delete_ledger_entry", "inventory", 
                    f"Deleted ledger entry #{entry_id} for {entry['product']}")
        
        return jsonify({"success": True, "message": "Ledger entry deleted successfully"})
        
    except Exception as e:
        logger.error(f"Error deleting ledger entry: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@bp.route("/ledger/<int:entry_id>/edit", methods=["GET", "POST"])
@login_required
@require_asset
def edit_ledger_entry(entry_id: int):
    """Edit a ledger entry (L1+ only)."""
    cu = current_user()
    
    permission_level = cu.get('permission_level', '')
    if permission_level not in ['L1', 'L2', 'L3', 'S1']:
        flash("Only L1+ administrators can edit ledger entries", "danger")
        return redirect_with_instance('inventory.ledger')
    
    if request.method == "POST":
        try:
            notes = request.form.get("notes", "").strip()
            
            with get_db_connection("inventory") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE asset_ledger 
                    SET note = %s 
                    WHERE id = %s
                """, (notes, entry_id))
                conn.commit()
                cursor.close()
            
            record_audit(cu, "edit_ledger_entry", "inventory", f"Edited ledger entry #{entry_id}")
            flash("✅ Ledger entry updated successfully", "success")
            
        except Exception as e:
            logger.error(f"Error editing ledger entry: {e}")
            flash(f"❌ Error: {str(e)}", "danger")
        
        return redirect_with_instance('inventory.ledger')
    
    return redirect_with_instance('inventory.ledger')