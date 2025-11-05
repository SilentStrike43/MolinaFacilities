# app/modules/inventory/views.py
import os
import json
import datetime
import logging
from flask import render_template, request, redirect, url_for, flash, jsonify

from app.modules.auth.security import login_required, require_asset, current_user, record_audit
from app.core.database import get_db_connection

# Import the blueprint from __init__.py (DON'T create it here!)
from . import bp

# Create alias for compatibility with existing code
inventory_bp = bp

logger = logging.getLogger(__name__)

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
    
    # SKU format: XXX-NNNNNN (e.g., 101-000001)
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
        
        # Find highest SKU for this category
        prefix = category_code
        cursor.execute("""
            SELECT sku FROM assets 
            WHERE sku LIKE %s 
            ORDER BY sku DESC LIMIT 1
        """, (f"{prefix}-%",))
        
        result = cursor.fetchone()
        cursor.close()
        
        if result:
            # Extract number and increment
            last_sku = result['sku']  # ✅ FIXED: Use column name
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
        
        # Get last inserted ID
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
    # Get asset info
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM assets WHERE id=%s", (asset_id,))
        asset = cursor.fetchone()
        cursor.close()
    
    if not asset:
        return
    
    # Convert to dict
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

# ---------- Routes ----------

@bp.route("/asset", methods=["GET", "POST"])
@login_required
@require_asset
def asset():
    """Asset Management - Add/Edit Assets with category-based SKU system."""
    cu = current_user()
    today = datetime.date.today().isoformat()
    flashmsg = None
    
    categories = get_all_categories_flat()
    
    # Preview next SKU for default category
    default_category = "101"  # Monitors
    next_sku_preview = generate_next_sku(default_category)
    
    # Get existing assets for display
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
    
   # Handle POST
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

    # Check if editing
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
        active="asset",
        flashmsg=flashmsg,
        today=today,
        categories=categories,
        next_sku_preview=next_sku_preview,
        rows=rows,
        q=q,
        status=status_filter,
        edit=edit
    )

@inventory_bp.route("/asset/<int:aid>/edit")
@login_required
@require_asset
def asset_edit(aid: int):
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

@inventory_bp.route("/insights")
@login_required
@require_asset
def insights():
    """Inventory Insights - Movement history and reports."""
    f = {k:(request.args.get(k) or "").strip() for k in
         ["q","inventory_id","product_name","manufacturer","item_type",
          "submitter_name","date_from","date_to"]}
    
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        
        sql = "SELECT* FROM inventory_reports WHERE 1=1"
        params = []
        
        if f["submitter_name"]:
            sql += " AND submitter_name LIKE ?"
            params.append(f"%{f['submitter_name']}%")
        
        if f["product_name"]:
            sql += " AND product_name LIKE ?"
            params.append(f"%{f['product_name']}%")
        
        if f["manufacturer"]:
            sql += " AND manufacturer LIKE ?"
            params.append(f"%{f['manufacturer']}%")
        
        if f["item_type"]:
            sql += " AND item_type LIKE ?"
            params.append(f"%{f['item_type']}%")
        
        if f["inventory_id"]:
            sql += " AND inventory_id = ?"
            params.append(f["inventory_id"])
        
        if f["q"]:
            sql += " AND (notes LIKE ? OR product_name LIKE ? OR manufacturer LIKE ?)"
            params.extend([f"%{f['q']}%"] * 3)
        
        if f["date_from"]:
            sql += " AND DATE(ts_utc) >= ?"
            params.append(f["date_from"])
        
        if f["date_to"]:
            sql += " AND DATE(ts_utc) <= ?"
            params.append(f["date_to"])
        
        sql += " ORDER BY ts_utc DESC LIMIT 2000"
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()
    
    return render_template("inventory/insights.html", active="insights", tab="inventory", rows=rows, **f)

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