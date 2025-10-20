# app/modules/inventory/views.py - COMPLETE WITH CATEGORY SYSTEM
import os
import json
import datetime
import sqlite3
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from app.core.auth import login_required, require_asset, current_user, record_audit

# module-local DB
from app.modules.inventory.storage import inventory_db, ensure_schema
from app.modules.inventory.assets import db as assets_db, ensure_schema as ensure_assets_schema

inventory_bp = Blueprint("inventory", __name__, url_prefix="/inventory", template_folder="templates")
bp = inventory_bp

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
    """Get a flat list of all categories and subcategories for dropdowns."""
    categories = []
    for main_key, main_cat in INVENTORY_CATEGORIES.items():
        # Add main category
        categories.append({
            "value": main_key,
            "label": f"{main_key} - {main_cat['name']}",
            "prefix": main_key,
            "is_main": True
        })
        # Add subcategories
        for sub_key, sub_name in main_cat["subcategories"].items():
            categories.append({
                "value": sub_key,
                "label": f"  └─ {sub_key} - {sub_name}",
                "prefix": sub_key,
                "is_main": False
            })
    return categories

def generate_next_sku(category_prefix: str) -> str:
    """
    Generate the next SKU for a given category prefix.
    Format: {PREFIX}-{7-digit-number}
    Example: 101-0000001, 101-0000002, etc.
    """
    con = assets_db()
    
    # Find the highest SKU number for this prefix
    pattern = f"{category_prefix}-%"
    row = con.execute("""
        SELECT sku FROM assets 
        WHERE sku LIKE ? 
        ORDER BY sku DESC 
        LIMIT 1
    """, (pattern,)).fetchone()
    
    con.close()
    
    if row and row["sku"]:
        # Extract the number part and increment
        try:
            parts = row["sku"].split("-")
            if len(parts) == 2:
                current_num = int(parts[1])
                next_num = current_num + 1
            else:
                next_num = 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1
    
    # Format: PREFIX-NNNNNNN (7 digits)
    return f"{category_prefix}-{next_num:07d}"

def get_category_info(sku: str) -> dict:
    """Get category information from SKU."""
    if not sku or "-" not in sku:
        return {"category": "Unknown", "subcategory": "Unknown"}
    
    prefix = sku.split("-")[0]
    
    # Check if it's a subcategory
    for main_key, main_cat in INVENTORY_CATEGORIES.items():
        if prefix in main_cat["subcategories"]:
            return {
                "category": main_cat["name"],
                "subcategory": main_cat["subcategories"][prefix],
                "prefix": prefix
            }
        elif prefix == main_key:
            return {
                "category": main_cat["name"],
                "subcategory": "General",
                "prefix": prefix
            }
    
    return {"category": "Unknown", "subcategory": "Unknown", "prefix": prefix}

# ---------- Helper functions ----------
def create_asset(data: dict) -> int:
    """Create a new asset in the master table."""
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
        data.get("manufacturer") or "",
        data.get("part_number") or "",
        data.get("serial_number") or "",
        data.get("pii") or "",
        data.get("notes") or "",
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
    
    # Convert Row to dict for easier access
    asset_dict = dict(asset)
    cat_info = get_category_info(asset_dict.get("sku", ""))
    
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
        asset_dict.get("manufacturer") or "",
        asset_dict.get("product") or "",
        username,
        f"{action}: {note}" if note else action,
        asset_dict.get("part_number") or "N/A",
        asset_dict.get("serial_number") or "N/A",
        qty,
        asset_dict.get("location") or "",
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
@inventory_bp.route("/asset", methods=["GET", "POST"])
@login_required
@require_asset
def asset():
    """Asset - Add New Asset with category-based SKU system."""
    cu = current_user()
    today = datetime.date.today().isoformat()
    flashmsg = None
    
    categories = get_all_categories_flat()
    
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
        like = f"%{q}%"
        params.extend([like, like, like, like])
    
    sql += " ORDER BY id DESC LIMIT 100"
    rows = con.execute(sql, params).fetchall()
    con.close()
    
    # Get next SKU for preview (default to Electronics)
    default_category = "101"
    next_sku_preview = generate_next_sku(default_category)

    if request.method == "POST":
        mode = request.form.get("_mode")
        
        if mode == "create":
            # Get form data
            category_code = (request.form.get("Category") or "").strip()
            product = (request.form.get("ProductName") or "").strip()
            manufacturer = (request.form.get("Manufacturer") or "").strip()
            location = (request.form.get("Location") or "").strip()
            qty = int(request.form.get("Count") or 0)
            uom = request.form.get("UOM", "EA").strip() or "EA"
            part_number = (request.form.get("PartNumber") or "").strip()
            serial_number = (request.form.get("SerialNumber") or "").strip()
            pii = (request.form.get("PII") or "").strip()
            notes = (request.form.get("Notes") or "").strip()
            
            # Validation
            if not category_code or not product or not location:
                flashmsg = ("Category, Product Name, and Location are required.", False)
            elif qty <= 0:
                flashmsg = ("Quantity must be greater than 0.", False)
            else:
                # Generate SKU based on category
                sku = generate_next_sku(category_code)
                cat_info = get_category_info(sku)
                
                # Create asset
                asset_data = {
                    "sku": sku,
                    "product": product,
                    "uom": uom,
                    "location": location,
                    "qty_on_hand": qty,
                    "manufacturer": manufacturer,
                    "part_number": part_number or "N/A",
                    "serial_number": serial_number or "N/A",
                    "pii": pii,
                    "notes": notes,
                    "status": "active"
                }
                asset_id = create_asset(asset_data)
                
                # Record initial check-in
                record_initial_checkin(asset_id, qty, cu.get("username", ""), "Initial inventory entry")
                
                # Queue label
                try:
                    label_data = {
                        "CheckInDate": today,
                        "InventoryID": str(asset_id),
                        "SKU": sku,
                        "ItemType": f"{cat_info['category']} - {cat_info['subcategory']}",
                        "Manufacturer": manufacturer,
                        "ProductName": product,
                        "SubmitterName": cu.get("username", "System"),
                        "Location": location,
                        "PartNumber": part_number or "N/A",
                        "SerialNumber": serial_number or "N/A",
                        "PII": pii
                    }
                    label_file = queue_asset_label(label_data)
                    flashmsg = (f"✅ Asset #{asset_id} created with SKU {sku}. Label: {os.path.basename(label_file)}", True)
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
        return {
            "success": True,
            "sku": next_sku,
            "category": cat_info["category"],
            "subcategory": cat_info["subcategory"]
        }
    except Exception as e:
        return {"success": False, "error": str(e)}, 400

@inventory_bp.route("/insights")
@login_required
@require_asset
def insights():
    """Inventory insights/reports page."""
    f = {k:(request.args.get(k) or "").strip() for k in
         ["q","inventory_id","product_name","manufacturer","item_type",
          "submitter_name","date_from","date_to"]}
    
    con = inventory_db()
    sql = "SELECT * FROM inventory_reports WHERE 1=1"
    params = []
    
    def add_like(field, val):
        nonlocal sql, params
        if val:
            sql += f" AND {field} LIKE ?"
            params.append(f"%{val}%")
    
    add_like("submitter_name", f["submitter_name"])
    add_like("product_name", f["product_name"])
    add_like("manufacturer", f["manufacturer"])
    add_like("item_type", f["item_type"])
    
    if f["inventory_id"]:
        sql += " AND inventory_id = ?"
        params.append(f["inventory_id"])
    
    if f["q"]:
        add_like("(notes || ' ' || product_name || ' ' || manufacturer)", f["q"])
    
    if f["date_from"]:
        sql += " AND date(ts_utc) >= date(?)"
        params.append(f["date_from"])
    
    if f["date_to"]:
        sql += " AND date(ts_utc) <= date(?)"
        params.append(f["date_to"])
    
    sql += " ORDER BY ts_utc DESC LIMIT 2000"
    rows = con.execute(sql, params).fetchall()
    con.close()
    
    return render_template("inventory/insights.html", active="insights", tab="inventory", rows=rows, **f)

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