# app/modules/inventory/views.py
import os
import json
import datetime
import sqlite3
import logging
from flask import render_template, request, redirect, url_for, flash, jsonify

from app.modules.auth.security import login_required, require_asset, current_user

# Import the blueprint from __init__.py (DON'T create it here!)
from . import bp

# Create alias for compatibility with existing code
inventory_bp = bp

# module-local DB
from app.modules.inventory.storage import inventory_db, ensure_schema
from app.modules.inventory.assets import db as assets_db, ensure_schema as ensure_assets_schema

logger = logging.getLogger(__name__)

# Ensure schemas exist
ensure_schema()
ensure_assets_schema()

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
            "304": "Laboratory Equipment",
            "305": "Imaging Equipment",
            "306": "Therapy Equipment",
            "307": "Emergency Equipment",
            "308": "Sterilization Equipment",
            "309": "Dental Equipment",
            "310": "General Medical"
        }
    },
    "400": {
        "name": "Office Supplies",
        "prefix": "400",
        "subcategories": {
            "401": "Paper Products",
            "402": "Writing Instruments",
            "403": "Filing & Organization",
            "404": "Office Equipment",
            "405": "Desk Accessories",
            "406": "Mailing Supplies",
            "407": "Cleaning Supplies",
            "408": "Break Room Supplies",
            "409": "Technology Accessories",
            "410": "General Office"
        }
    },
    "500": {
        "name": "Furniture",
        "prefix": "500",
        "subcategories": {
            "501": "Desks",
            "502": "Chairs",
            "503": "Tables",
            "504": "Storage Cabinets",
            "505": "Shelving Units",
            "506": "Conference Room",
            "507": "Reception Area",
            "508": "Accessories",
            "509": "Ergonomic Equipment",
            "510": "General Furniture"
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
    con = assets_db()
    
    # Find highest SKU for this category
    prefix = category_code
    result = con.execute("""
        SELECT sku FROM assets 
        WHERE sku LIKE ? 
        ORDER BY sku DESC 
        LIMIT 1
    """, (f"{prefix}-%",)).fetchone()
    
    if result:
        # Extract number and increment
        last_sku = result["sku"]
        try:
            last_num = int(last_sku.split("-")[1])
            next_num = last_num + 1
        except:
            next_num = 1
    else:
        next_num = 1
    
    con.close()
    return f"{prefix}-{next_num:06d}"

def create_asset(data: dict) -> int:
    """Create new asset in database."""
    con = assets_db()
    cur = con.execute("""
        INSERT INTO assets(sku, product, uom, location, qty_on_hand, manufacturer, part_number, serial_number, pii, notes, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    asset_id = cur.lastrowid
    con.commit()
    con.close()
    return asset_id

def record_initial_checkin(asset_id: int, qty: int, username: str, note: str = "Initial inventory"):
    """Record initial check-in to ledger and log to insights."""
    con = assets_db()
    con.execute("""
        INSERT INTO asset_ledger(asset_id, action, qty, username, note)
        VALUES (?, 'CHECKIN', ?, ?, ?)
    """, (asset_id, qty, username, note))
    con.commit()
    con.close()
    
    log_to_insights(asset_id, "CHECKIN", qty, username, note)

def log_to_insights(asset_id: int, action: str, qty: int, username: str, note: str = ""):
    """Log asset movements to insights for reporting."""
    con = assets_db()
    asset = con.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
    con.close()
    
    if not asset:
        return
    
    cat_info = get_category_info(asset["sku"])
    
    con = inventory_db()
    con.execute("""
        INSERT INTO inventory_reports(
            checkin_date, inventory_id, item_type, manufacturer, product_name,
            submitter_name, notes, part_number, serial_number, count, location, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.date.today().isoformat(),
        asset_id,
        f"{cat_info['category']} - {cat_info['subcategory']}",
        asset.get("manufacturer", ""),
        asset["product"] or "",
        username,
        f"{action}: {note}" if note else action,
        asset.get("part_number", "N/A"),
        asset.get("serial_number", "N/A"),
        qty,
        asset["location"] or "",
        "completed"
    ))
    con.commit()
    con.close()

def queue_asset_label(data: dict):
    """Queue an asset label for BarTender printing."""
    try:
        BARTENDER_DROP = r"C:\BTManifest\BTInvDrop"
        os.makedirs(BARTENDER_DROP, exist_ok=True)
        
        import uuid
        ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        filename = f"{ts}_asset_{uuid.uuid4().hex[:8]}.json"
        filepath = os.path.join(BARTENDER_DROP, filename)
        
        # BarTender payload
        payload = {
            "CheckInDate": data.get("CheckInDate", datetime.date.today().isoformat()),
            "InventoryID": data.get("InventoryID", ""),
            "SKU": data.get("SKU", ""),
            "ItemType": data.get("ItemType", ""),
            "Manufacturer": data.get("Manufacturer", ""),
            "ProductName": data.get("ProductName", ""),
            "SubmitterName": data.get("SubmitterName", "System"),
            "Location": data.get("Location", ""),
            "PartNumber": data.get("PartNumber", "N/A"),
            "SerialNumber": data.get("SerialNumber", "N/A"),
            "PII": data.get("PII", "")
        }
        
        temp_path = filepath + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, filepath)
        
        logger.info(f"Label queued: {filename}")
        return filepath
        
    except Exception as e:
        logger.exception("queue_asset_label failed")
        raise

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
    con = assets_db()
    q = (request.args.get("q") or "").strip()
    status_filter = request.args.get("status", "active")
    
    sql = "SELECT * FROM assets WHERE 1=1"
    params = []
    
    if status_filter != "all":
        sql += " AND status = ?"
        params.append(status_filter)
    
    if q:
        sql += " AND (product LIKE ? OR sku LIKE ? OR location LIKE ? OR manufacturer LIKE ?)"
        params.extend([f"%{q}%"] * 4)
    
    sql += " ORDER BY id DESC LIMIT 100"
    rows = con.execute(sql, params).fetchall()
    con.close()
    
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
                    
                    # Queue label for printing
                    label_data = {
                        "CheckInDate": today,
                        "InventoryID": str(asset_id),
                        "SKU": sku,
                        "ItemType": f"{cat_info['category']} - {cat_info['subcategory']}",
                        "Manufacturer": manufacturer,
                        "ProductName": product,
                        "SubmitterName": username,
                        "Location": location,
                        "PartNumber": part_number or "N/A",
                        "SerialNumber": serial_number or "N/A",
                        "PII": pii
                    }
                    label_file = queue_asset_label(label_data)
                    
                    flashmsg = (f"Asset #{asset_id} created successfully! Label: {os.path.basename(label_file)}", True)
                    record_audit(cu, "create_asset", "inventory", f"Asset #{asset_id}, SKU {sku}: {product}")
                except Exception as e:
                    flashmsg = (f"⚠️ Asset #{asset_id} created but label failed: {str(e)}", False)
                    record_audit(cu, "create_asset_error", "inventory", f"Asset #{asset_id} label error: {str(e)}")
        
        elif mode == "update":
            asset_id = int(request.form.get("id") or 0)
            product = (request.form.get("ProductName") or "").strip()
            manufacturer = (request.form.get("Manufacturer") or "").strip()
            location = (request.form.get("Location") or "").strip()
            uom = request.form.get("UOM", "EA").strip() or "EA"
            notes = (request.form.get("Notes") or "").strip()
            status = request.form.get("Status", "active")
            
            con = assets_db()
            con.execute("""
                UPDATE assets 
                SET product=?, manufacturer=?, uom=?, location=?, notes=?, status=?
                WHERE id=?
            """, (product, manufacturer, uom, location, notes, status, asset_id))
            con.commit()
            con.close()
            
            record_audit(cu, "update_asset", "inventory", f"Updated asset #{asset_id}")
            flashmsg = (f"Asset #{asset_id} updated successfully.", True)

    # Check if editing
    edit_id = request.args.get("edit", type=int)
    edit = None
    if edit_id:
        con = assets_db()
        edit = con.execute("SELECT * FROM assets WHERE id=?", (edit_id,)).fetchone()
        con.close()

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
    
@inventory_bp.route("/asset/<int:aid>/delete", methods=["POST"])
@login_required
def asset_delete(aid: int):
    """Delete an asset (SysAdmin+ only) - Soft delete by marking as deleted"""
    cu = current_user()
    
    # Check if user is sysadmin
    if not (cu.get("is_sysadmin") or cu.get("is_admin")):
        flash("Only System Administrators can delete assets", "danger")
        return redirect(url_for("inventory.asset"))
    
    con = assets_db()
    asset = con.execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone()
    
    if not asset:
        con.close()
        flash("Asset not found", "warning")
        return redirect(url_for("inventory.asset"))
    
    # Soft delete - mark as deleted but keep in database
    con.execute("""
        UPDATE assets 
        SET status = 'deleted', 
            notes = COALESCE(notes, '') || ' [DELETED by ' || ? || ' on ' || datetime('now') || ']'
        WHERE id = ?
    """, (cu.get("username"), aid))
    
    con.commit()
    con.close()
    
    record_audit(cu, "delete_asset", "inventory", f"Deleted asset #{aid}: {asset['sku']} - {asset['product']}")
    flash(f"Asset {asset['sku']} deleted successfully. SKU sequence will continue.", "success")
    
    return redirect(url_for("inventory.asset"))

@inventory_bp.route("/insights")
@login_required
@require_asset
def insights():
    """Inventory Insights - Movement history and reports."""
    q = (request.args.get("q") or "").strip()
    
    # Query from ASSETS database, not inventory_reports
    con = assets_db()
    sql = """
        SELECT 
            a.id,
            a.sku,
            a.product,
            a.manufacturer,
            a.part_number,
            a.serial_number,
            a.location,
            a.uom,
            a.qty_on_hand,
            a.pii,
            a.notes,
            a.status,
            a.created_utc,
            (SELECT SUM(qty) FROM asset_ledger WHERE asset_id = a.id AND action = 'CHECKIN') as total_checkins,
            (SELECT SUM(qty) FROM asset_ledger WHERE asset_id = a.id AND action = 'CHECKOUT') as total_checkouts,
            (SELECT COUNT(*) FROM asset_ledger WHERE asset_id = a.id) as movement_count
        FROM assets a
        WHERE a.status != 'deleted'
    """
    
    params = []
    if q:
        sql += """ AND (
            a.sku LIKE ? OR 
            a.product LIKE ? OR 
            a.manufacturer LIKE ? OR 
            a.location LIKE ? OR
            a.part_number LIKE ? OR
            a.serial_number LIKE ?
        )"""
        params.extend([f"%{q}%"] * 6)
    
    sql += " ORDER BY a.created_utc DESC LIMIT 500"
    
    rows = con.execute(sql, params).fetchall()
    con.close()
    
    return render_template("inventory/insights.html", active="insights", rows=rows, q=q)

@inventory_bp.route("/insights/export")
@login_required
@require_asset
def insights_export():
    """Export inventory insights as CSV."""
    import io
    import csv
    from flask import send_file
    
    con = inventory_db()
    rows = con.execute("SELECT * FROM inventory_reports ORDER BY ts_utc DESC").fetchall()
    con.close()
    
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["ts_utc","inventory_id","product_name","manufacturer","item_type","submitter_name","notes","count","location"])
    for r in rows:
        w.writerow([r["ts_utc"], r["inventory_id"], r["product_name"], r["manufacturer"],
                    r["item_type"], r["submitter_name"], r["notes"], r.get("count", ""), r.get("location", "")])
    
    mem = io.BytesIO(out.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="insights_inventory.csv")