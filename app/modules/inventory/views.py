# app/modules/inventory/views.py
"""
Inventory Module Views - Instance-Aware Edition
Uses middleware-based instance context instead of manual instance_id handling
"""

import os
import json
import datetime
import logging
from flask import render_template, request, redirect, url_for, flash, jsonify

from app.modules.auth.security import login_required, require_asset, current_user, record_audit, require_cap
from app.core.database import get_db_connection
from app.core.instance_queries import build_insert, build_update, add_instance_filter
from app.core.instance_context import get_current_instance

from . import bp

inventory_bp = bp

logger = logging.getLogger(__name__)

# ========== HELPER FUNCTIONS ==========

def get_instance_context():
    """Get instance context from middleware (set automatically per request)."""
    try:
        instance_id = get_current_instance()
        is_sandbox = (instance_id == 4)
        return instance_id, is_sandbox
    except RuntimeError:
        # Fallback if middleware didn't set context
        cu = current_user()
        instance_id = cu.get('instance_id') if cu else None
        is_sandbox = (instance_id == 4)
        return instance_id, is_sandbox


INDUSTRY_TYPES = [
    "Medical", "Hardware", "Logistics", "Office Supplies", "Industrial",
    "Automotive", "Technological", "Government", "Entertainment",
    "Heavy Industry", "Repairs", "Retail", "Internal", "Other",
]

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
    """Generate next SKU for given category code, scoped to the current instance.

    Only counts assets that have not been deleted (status != 'deleted'), so that
    removing an asset frees its SKU number for reassignment.
    """
    instance_id, _ = get_instance_context()
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT sku FROM assets
            WHERE sku LIKE %s
            AND instance_id = %s
            AND status != 'deleted'
            ORDER BY sku DESC LIMIT 1
        """, (f"{category_code}-%", instance_id))

        result = cursor.fetchone()
        cursor.close()

        if result:
            try:
                last_num = int(result['sku'].split("-")[1])
                next_num = last_num + 1
            except (IndexError, ValueError):
                next_num = 1
        else:
            next_num = 1

        return f"{category_code}-{next_num:06d}"


def create_asset(data: dict) -> int:
    """Create new asset in database (instance-aware)."""
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()

        # Use instance-aware insert
        columns = [
            'sku', 'product', 'uom', 'location', 'qty_on_hand',
            'manufacturer', 'part_number', 'serial_number', 'pii', 'notes', 'status'
        ]

        values = [
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
        ]

        if data.get("vendor_id"):
            columns.append("vendor_id")
            values.append(int(data["vendor_id"]))

        # build_insert automatically adds instance_id
        sql, params = build_insert('assets', columns, values)
        sql += " RETURNING id"

        cursor.execute(sql, params)
        result = cursor.fetchone()
        asset_id = result['id']

        conn.commit()
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
    """Log asset movements to insights for reporting (instance-aware)."""
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        
        # Get asset info with instance filter
        where_clause, params = add_instance_filter("id=%s", [asset_id])
        cursor.execute(f"SELECT * FROM assets WHERE {where_clause}", params)
        asset = cursor.fetchone()
        
        if not asset:
            cursor.close()
            return
        
        asset_dict = dict(asset)
        cat_info = get_category_info(asset_dict.get("sku", ""))
        
        cursor.execute("""
            INSERT INTO inventory_transactions(
                transaction_date, transaction_type, asset_id, sku,
                item_type, manufacturer, product_name,
                submitter_name, notes, part_number, serial_number,
                quantity, location, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            datetime.date.today(),
            action,
            asset_id,
            asset_dict.get("sku", ""),
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

        # Build WHERE conditions with explicit instance_id for JOIN query
        conditions = ["a.instance_id = %s"]
        params = [instance_id]

        if status_filter != "all":
            conditions.append("a.status = %s")
            params.append(status_filter)

        if q:
            conditions.append(
                "(a.product ILIKE %s OR a.sku ILIKE %s OR a.location ILIKE %s "
                "OR a.manufacturer ILIKE %s OR v.company ILIKE %s)"
            )
            params.extend([f"%{q}%"] * 5)

        where_clause = " AND ".join(conditions)

        cursor.execute(f"""
            SELECT a.*, v.company AS vendor_company, v.contact_name AS vendor_contact
            FROM assets a
            LEFT JOIN vendor_book v ON a.vendor_id = v.id AND v.is_active = TRUE
            WHERE {where_clause}
            ORDER BY a.id DESC LIMIT 100
        """, params)
        rows = cursor.fetchall()
        cursor.close()
    
    if request.method == "POST":
        mode = request.form.get("mode", "create")
        
        if mode == "create":
            category = request.form.get("category", "101")
            sku = generate_next_sku(category)
            product = (request.form.get("ProductName") or "").strip()
            manufacturer = (request.form.get("Manufacturer") or "").strip()
            location = (request.form.get("Location") or "").strip()
            qty = int(request.form.get("InitialQty", 0))
            part_number = (request.form.get("PartNumber") or "").strip()
            serial_number = (request.form.get("SerialNumber") or "").strip()
            pii = (request.form.get("PII") or "").strip()
            notes = (request.form.get("Notes") or "").strip()
            username = cu.get("username", "System")

            # Vendor handling
            vendor_id = (request.form.get("vendor_id") or "").strip() or None
            vendor_name = (request.form.get("vendor_name") or "").strip()
            save_new_vendor = request.form.get("save_new_vendor") == "1"

            if not product:
                flashmsg = ("Product name is required.", False)
            else:
                try:
                    # If user typed a new vendor name and confirmed saving it
                    if vendor_name and not vendor_id and save_new_vendor:
                        with get_db_connection("inventory") as vconn:
                            vcursor = vconn.cursor()
                            vcursor.execute("""
                                INSERT INTO vendor_book (instance_id, company, is_active)
                                VALUES (%s, %s, TRUE) RETURNING id
                            """, (instance_id, vendor_name))
                            row = vcursor.fetchone()
                            vendor_id = str(row['id']) if row else None
                            vconn.commit()
                            vcursor.close()

                    # Increment use_count for an existing vendor
                    if vendor_id:
                        with get_db_connection("inventory") as vconn:
                            vcursor = vconn.cursor()
                            vcursor.execute("""
                                UPDATE vendor_book SET use_count = use_count + 1,
                                updated_at = CURRENT_TIMESTAMP
                                WHERE id = %s AND instance_id = %s
                            """, (int(vendor_id), instance_id))
                            vconn.commit()
                            vcursor.close()

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
                        "status": "active",
                        "vendor_id": vendor_id,
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

            # Vendor handling for update
            vendor_id = (request.form.get("vendor_id") or "").strip() or None
            vendor_name = (request.form.get("vendor_name") or "").strip()
            save_new_vendor = request.form.get("save_new_vendor") == "1"

            if vendor_name and not vendor_id and save_new_vendor:
                with get_db_connection("inventory") as vconn:
                    vcursor = vconn.cursor()
                    vcursor.execute("""
                        INSERT INTO vendor_book (instance_id, company, is_active)
                        VALUES (%s, %s, TRUE) RETURNING id
                    """, (instance_id, vendor_name))
                    row = vcursor.fetchone()
                    vendor_id = str(row['id']) if row else None
                    vconn.commit()
                    vcursor.close()

            # Use instance-aware update
            set_clause = "product=%s, manufacturer=%s, uom=%s, location=%s, notes=%s, status=%s, vendor_id=%s"
            set_params = [product, manufacturer, uom, location, notes, status,
                          int(vendor_id) if vendor_id else None]

            sql, params = build_update(
                table='assets',
                set_clause=set_clause,
                set_params=set_params,
                where="id=%s",
                where_params=[asset_id]
            )

            with get_db_connection("inventory") as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                conn.commit()
                cursor.close()

            record_audit(cu, "update_asset", "inventory", f"Updated asset #{asset_id}")
            flashmsg = (f"✅ Asset #{asset_id} updated successfully.", True)

    edit_id = request.args.get("edit", type=int)
    edit = None
    if edit_id:
        with get_db_connection("inventory") as conn:
            cursor = conn.cursor()
            where_clause, params = add_instance_filter("a.id=%s", [edit_id])
            cursor.execute(f"""
                SELECT a.*, v.company AS vendor_company, v.contact_name AS vendor_contact
                FROM assets a
                LEFT JOIN vendor_book v ON a.vendor_id = v.id AND v.is_active = TRUE
                WHERE {where_clause}
            """, params)
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
        industry_types=INDUSTRY_TYPES,
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
    if permission_level not in ['L1', 'L2', 'O1', 'A1', 'A2', 'S1']:
        return jsonify({"success": False, "error": "Only L1+ administrators can delete assets"}), 403
    
    try:
        with get_db_connection("inventory") as conn:
            cursor = conn.cursor()
            
            # Get asset info with instance filter
            where_clause, params = add_instance_filter("id = %s", [asset_id])
            cursor.execute(f"SELECT sku, product FROM assets WHERE {where_clause}", params)
            asset = cursor.fetchone()
            
            if not asset:
                return jsonify({"success": False, "error": "Asset not found"}), 404
            
            # Soft delete with instance filter
            set_clause = "status = 'deleted', notes = CONCAT(notes, %s)"
            set_params = [f"\nDELETED BY: {cu['username']} ON: {datetime.datetime.now().isoformat()}"]
            
            sql, params = build_update(
                table='assets',
                set_clause=set_clause,
                set_params=set_params,
                where="id = %s",
                where_params=[asset_id]
            )
            
            cursor.execute(sql, params)
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
    """Redirect to asset page with edit parameter."""
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


@bp.route("/vendor-book", methods=["GET", "POST"])
@login_required
@require_asset
def vendor_book():
    """Vendor Book — manage suppliers and vendors linked to inventory assets."""
    cu = current_user()
    instance_id, is_sandbox = get_instance_context()

    flashmsg = None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            company = (request.form.get("Company") or "").strip()
            if not company:
                flashmsg = ("Company name is required.", False)
            else:
                with get_db_connection("inventory") as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO vendor_book
                            (instance_id, contact_name, company, address, phone, email, industry_type, notes)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        instance_id,
                        (request.form.get("ContactName") or "").strip() or None,
                        company,
                        (request.form.get("Address") or "").strip() or None,
                        (request.form.get("Phone") or "").strip() or None,
                        (request.form.get("Email") or "").strip() or None,
                        request.form.get("IndustryType") or None,
                        (request.form.get("Notes") or "").strip() or None,
                    ))
                    conn.commit()
                    cursor.close()
                record_audit(cu, "add_vendor", "inventory", f"Added vendor: {company}")
                flashmsg = (f"✅ Vendor '{company}' added!", True)

        elif action == "edit":
            vendor_id = int(request.form.get("VendorID") or 0)
            company = (request.form.get("Company") or "").strip()
            if not company:
                flashmsg = ("Company name is required.", False)
            else:
                with get_db_connection("inventory") as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE vendor_book
                        SET contact_name=%s, company=%s, address=%s, phone=%s,
                            email=%s, industry_type=%s, notes=%s,
                            updated_at=CURRENT_TIMESTAMP
                        WHERE id=%s AND instance_id=%s
                    """, (
                        (request.form.get("ContactName") or "").strip() or None,
                        company,
                        (request.form.get("Address") or "").strip() or None,
                        (request.form.get("Phone") or "").strip() or None,
                        (request.form.get("Email") or "").strip() or None,
                        request.form.get("IndustryType") or None,
                        (request.form.get("Notes") or "").strip() or None,
                        vendor_id, instance_id,
                    ))
                    conn.commit()
                    cursor.close()
                record_audit(cu, "edit_vendor", "inventory", f"Updated vendor #{vendor_id}: {company}")
                flashmsg = (f"✅ Vendor updated.", True)

        elif action == "delete":
            vendor_id = int(request.form.get("VendorID") or 0)
            with get_db_connection("inventory") as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE vendor_book SET is_active=FALSE, updated_at=CURRENT_TIMESTAMP WHERE id=%s AND instance_id=%s",
                    (vendor_id, instance_id)
                )
                conn.commit()
                cursor.close()
            record_audit(cu, "delete_vendor", "inventory", f"Deleted vendor #{vendor_id}")
            flashmsg = ("✅ Vendor removed.", True)

        return redirect(url_for("inventory.vendor_book"))

    # GET
    q = (request.args.get("q") or "").strip()
    sort = request.args.get("sort", "company")
    sort_map = {"company": "company ASC", "usage": "use_count DESC", "recent": "updated_at DESC"}
    order_by = sort_map.get(sort, "company ASC")

    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        if q:
            cursor.execute(f"""
                SELECT * FROM vendor_book
                WHERE instance_id=%s AND is_active=TRUE
                AND (company ILIKE %s OR contact_name ILIKE %s OR industry_type ILIKE %s)
                ORDER BY {order_by}
            """, (instance_id, f"%{q}%", f"%{q}%", f"%{q}%"))
        else:
            cursor.execute(f"""
                SELECT * FROM vendor_book
                WHERE instance_id=%s AND is_active=TRUE
                ORDER BY {order_by}
            """, (instance_id,))
        vendors = cursor.fetchall()
        cursor.close()

    return render_template(
        "inventory/vendor_book.html",
        active="inventory-vendor-book",
        vendors=vendors,
        flashmsg=flashmsg,
        q=q,
        sort=sort,
        industry_types=INDUSTRY_TYPES,
        is_sandbox=is_sandbox,
        instance_id=instance_id,
    )


@bp.route("/api/vendor-search")
@login_required
@require_asset
def api_vendor_search():
    """API: search vendor book for autocomplete (returns JSON)."""
    instance_id, _ = get_instance_context()
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify([])
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, company, contact_name, industry_type
            FROM vendor_book
            WHERE instance_id=%s AND is_active=TRUE
            AND (company ILIKE %s OR contact_name ILIKE %s)
            ORDER BY use_count DESC, company ASC
            LIMIT 10
        """, (instance_id, f"%{q}%", f"%{q}%"))
        rows = cursor.fetchall()
        cursor.close()
    return jsonify([dict(r) for r in rows])


@bp.route("/insights")
@login_required
@require_cap("can_inventory")
def insights():
    """Inventory insights and analytics dashboard"""
    cu = current_user()
    instance_id, is_sandbox = get_instance_context()

    from datetime import timedelta, date as _date
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    if not date_from:
        date_from = (_date.today() - timedelta(days=30)).isoformat()
    if not date_to:
        date_to = _date.today().isoformat()

    try:
        with get_db_connection("inventory") as conn:
            cursor = conn.cursor()

            # === Unique active assets ===
            where_assets, p = add_instance_filter("status = 'active'", [])
            cursor.execute(f"SELECT COUNT(*) as cnt FROM assets WHERE {where_assets}", p)
            unique_assets = (cursor.fetchone() or {}).get('cnt', 0)

            # === Movement totals from asset_ledger (JOIN assets for instance filter) ===
            where_mvmt, p = add_instance_filter(
                "DATE(al.ts_utc) >= %s AND DATE(al.ts_utc) <= %s",
                [date_from, date_to]
            )
            cursor.execute(f"""
                SELECT
                    COUNT(*) as total_movements,
                    COUNT(CASE WHEN al.action = 'CHECKIN'  THEN 1 END) as total_checkins,
                    COUNT(CASE WHEN al.action = 'CHECKOUT' THEN 1 END) as total_checkouts,
                    COUNT(DISTINCT al.username) as active_users
                FROM asset_ledger al
                JOIN assets a ON al.asset_id = a.id
                WHERE {where_mvmt}
            """, p)
            mvmt = cursor.fetchone() or {}
            summary = {
                'unique_assets':    unique_assets,
                'total_movements':  mvmt.get('total_movements', 0),
                'total_checkins':   mvmt.get('total_checkins', 0),
                'total_checkouts':  mvmt.get('total_checkouts', 0),
                'active_users':     mvmt.get('active_users', 0),
            }

            # === Category Breakdown (group by 3-digit SKU prefix) ===
            where_cat, p = add_instance_filter("status = 'active'", [])
            cursor.execute(f"""
                SELECT SPLIT_PART(sku, '-', 1) as prefix, COUNT(*) as asset_count
                FROM assets
                WHERE {where_cat}
                GROUP BY prefix
                ORDER BY asset_count DESC
                LIMIT 10
            """, p)
            raw_cats = cursor.fetchall()
            prefix_to_name = {c['code']: c['category'] for c in get_all_categories_flat()}
            category_breakdown = [
                {
                    'category_name': prefix_to_name.get(row['prefix'], f"Category {row['prefix']}"),
                    'asset_count': row['asset_count']
                }
                for row in raw_cats
            ]

            # === Top Assets by movement count ===
            where_top, p = add_instance_filter(
                "DATE(al.ts_utc) >= %s AND DATE(al.ts_utc) <= %s",
                [date_from, date_to]
            )
            cursor.execute(f"""
                SELECT a.product, a.sku, a.qty_on_hand, COUNT(al.id) as total_movements
                FROM asset_ledger al
                JOIN assets a ON al.asset_id = a.id
                WHERE {where_top}
                GROUP BY a.id, a.product, a.sku, a.qty_on_hand
                ORDER BY total_movements DESC
                LIMIT 10
            """, p)
            top_assets = cursor.fetchall()

            # === User Activity Leaderboard ===
            where_usr, p = add_instance_filter(
                "DATE(al.ts_utc) >= %s AND DATE(al.ts_utc) <= %s",
                [date_from, date_to]
            )
            cursor.execute(f"""
                SELECT
                    al.username,
                    COUNT(CASE WHEN al.action = 'CHECKIN'  THEN 1 END) as checkins,
                    COUNT(CASE WHEN al.action = 'CHECKOUT' THEN 1 END) as checkouts,
                    COUNT(*) as total_actions
                FROM asset_ledger al
                JOIN assets a ON al.asset_id = a.id
                WHERE {where_usr}
                GROUP BY al.username
                ORDER BY total_actions DESC
                LIMIT 10
            """, p)
            user_stats = cursor.fetchall()

            # === Low Stock Alerts (qty_on_hand < 10) ===
            where_low, p = add_instance_filter("status = 'active' AND qty_on_hand < %s", [10])
            cursor.execute(f"""
                SELECT product, sku, location, qty_on_hand
                FROM assets
                WHERE {where_low}
                ORDER BY qty_on_hand ASC
                LIMIT 20
            """, p)
            low_stock = cursor.fetchall()

            # === Recent Activity (last 24h) ===
            where_rec, p = add_instance_filter("al.ts_utc >= NOW() - INTERVAL '24 hours'", [])
            cursor.execute(f"""
                SELECT al.action, a.product, al.username, al.qty, al.ts_utc as timestamp
                FROM asset_ledger al
                JOIN assets a ON al.asset_id = a.id
                WHERE {where_rec}
                ORDER BY al.ts_utc DESC
                LIMIT 20
            """, p)
            recent_activity = cursor.fetchall()

            # === Activity Trend (per-day checkins/checkouts/adjustments) ===
            where_trend, p = add_instance_filter(
                "DATE(al.ts_utc) >= %s AND DATE(al.ts_utc) <= %s",
                [date_from, date_to]
            )
            cursor.execute(f"""
                SELECT
                    DATE(al.ts_utc) as date,
                    COUNT(CASE WHEN al.action = 'CHECKIN'  THEN 1 END) as checkins,
                    COUNT(CASE WHEN al.action = 'CHECKOUT' THEN 1 END) as checkouts,
                    COUNT(CASE WHEN al.action = 'ADJUST'   THEN 1 END) as adjustments
                FROM asset_ledger al
                JOIN assets a ON al.asset_id = a.id
                WHERE {where_trend}
                GROUP BY DATE(al.ts_utc)
                ORDER BY date
            """, p)
            trend_rows = cursor.fetchall()
            activity_trend = [
                {
                    'date': row['date'].isoformat() if hasattr(row['date'], 'isoformat') else str(row['date']),
                    'checkins':    row['checkins'] or 0,
                    'checkouts':   row['checkouts'] or 0,
                    'adjustments': row['adjustments'] or 0,
                }
                for row in trend_rows
            ]

            cursor.close()

        record_audit(cu, "view_insights", "inventory",
                     f"Viewed insights: {date_from} to {date_to}")

        return render_template(
            "inventory/insights.html",
            active="inventory-insights",
            summary=summary,
            category_breakdown=category_breakdown,
            top_assets=top_assets,
            user_stats=user_stats,
            low_stock=low_stock,
            recent_activity=recent_activity,
            activity_trend=activity_trend,
            date_from=date_from,
            date_to=date_to,
            is_sandbox=is_sandbox,
            instance_id=instance_id if is_sandbox else None
        )

    except Exception as e:
        logger.error(f"Insights error: {e}", exc_info=True)
        flash(f"Error loading insights: {str(e)}", "danger")
        return redirect(url_for("inventory.asset"))


@inventory_bp.route("/insights/export")
@login_required
@require_asset
def insights_export():
    """Export asset ledger as CSV."""
    import io
    import csv
    from flask import send_file

    # Filter ledger by instance (via JOIN to assets)
    where_clause, params = add_instance_filter("1=1", [])

    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT
                al.ts_utc,
                a.sku          AS inventory_id,
                a.product      AS product_name,
                a.manufacturer,
                a.location,
                al.action      AS item_type,
                al.username    AS submitter_name,
                al.note        AS notes,
                al.qty         AS count
            FROM asset_ledger al
            JOIN assets a ON al.asset_id = a.id
            WHERE {where_clause}
            ORDER BY al.ts_utc DESC
        """, params)
        rows = cursor.fetchall()
        cursor.close()

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["ts_utc", "inventory_id", "product_name", "manufacturer",
                "location", "action", "submitter_name", "notes", "qty"])
    for r in rows:
        row_dict = dict(r)
        w.writerow([
            row_dict.get("ts_utc"), row_dict.get("inventory_id"),
            row_dict.get("product_name"), row_dict.get("manufacturer"),
            row_dict.get("location"), row_dict.get("item_type"),
            row_dict.get("submitter_name"), row_dict.get("notes"),
            row_dict.get("count", "")
        ])
    
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
        
        # Build WHERE conditions (instance added automatically)
        conditions = ["1=1"]
        params = []
        
        if search:
            conditions.append("(a.sku ILIKE %s OR a.product ILIKE %s OR l.username ILIKE %s)")
            search_term = f"%{search}%"
            params.extend([search_term, search_term, search_term])
        
        if action_filter:
            conditions.append("l.action = %s")
            params.append(action_filter.upper())
        
        if date_from:
            conditions.append("DATE(l.ts_utc) >= %s")
            params.append(date_from)
        
        if date_to:
            conditions.append("DATE(l.ts_utc) <= %s")
            params.append(date_to)
        
        where_base = " AND ".join(conditions)
        
        # Add instance filter to the JOIN
        where_clause, all_params = add_instance_filter(where_base, params)
        
        sql = f"""
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
            WHERE {where_clause}
            ORDER BY l.ts_utc DESC LIMIT 200
        """
        
        cursor.execute(sql, all_params)
        ledger_entries = cursor.fetchall()
        
        # Get today's stats with instance filter
        stats_where, stats_params = add_instance_filter(
            "DATE(al.ts_utc) = CURRENT_DATE",
            []
        )
        
        cursor.execute(f"""
            SELECT 
                COUNT(CASE WHEN al.action = 'CHECKIN' THEN 1 END) as check_ins_today,
                COUNT(CASE WHEN al.action = 'CHECKOUT' THEN 1 END) as check_outs_today,
                COUNT(CASE WHEN al.action = 'ADJUST' THEN 1 END) as adjustments_today
            FROM asset_ledger al
            JOIN assets a ON al.asset_id = a.id
            WHERE {stats_where}
        """, stats_params)
        stats = cursor.fetchone()
        
        # Get assets list with instance filter
        assets_where, assets_params = add_instance_filter("status = 'active'", [])
        
        cursor.execute(f"""
            SELECT id, sku as inventory_id, product as product_name 
            FROM assets 
            WHERE {assets_where}
            ORDER BY sku
        """, assets_params)
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
        return redirect(url_for('inventory.ledger'))
    
    try:
        with get_db_connection("inventory") as conn:
            cursor = conn.cursor()
            
            # Get asset with instance filter
            where_clause, params = add_instance_filter("id = %s", [asset_id])
            cursor.execute(f"""
                SELECT qty_on_hand, product, sku FROM assets WHERE {where_clause}
            """, params)
            asset = cursor.fetchone()
            
            if not asset:
                flash("❌ Asset not found.", "danger")
                return redirect(url_for('inventory.ledger'))
            
            current_qty = asset['qty_on_hand']
            
            if action == 'CHECKIN':
                new_qty = current_qty + quantity
            elif action == 'CHECKOUT':
                new_qty = current_qty - quantity
                if new_qty < 0:
                    flash("❌ Cannot check out more than available quantity.", "danger")
                    return redirect(url_for('inventory.ledger'))
            else:
                new_qty = quantity
            
            cursor.execute("""
                INSERT INTO asset_ledger (asset_id, action, qty, username, note, ts_utc)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            """, (asset_id, action, quantity, username, notes))
            
            # Update with instance filter
            set_clause = "qty_on_hand = %s"
            set_params = [new_qty]
            
            sql, params = build_update(
                table='assets',
                set_clause=set_clause,
                set_params=set_params,
                where="id = %s",
                where_params=[asset_id]
            )
            
            cursor.execute(sql, params)
            
            conn.commit()
            cursor.close()
        
        log_to_insights(asset_id, action, quantity, username, notes)
        
        record_audit(cu, "ledger_entry", "inventory", 
                    f"{action} {quantity} units of {asset['product']} (SKU: {asset['sku']})")
        
        flash(f"✅ Ledger entry added! {action}: {quantity} units", "success")
        
    except Exception as e:
        logger.error(f"Error adding ledger entry: {e}")
        flash(f"❌ Error: {str(e)}", "danger")
    
    return redirect(url_for('inventory.ledger'))


@bp.route("/ledger/export")
@login_required
@require_asset
def export_ledger():
    """Export ledger as CSV."""
    import io
    import csv
    from flask import send_file
    
    # Use instance filter
    where_clause, params = add_instance_filter("1=1", [])
    
    with get_db_connection("inventory") as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
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
            WHERE {where_clause}
            ORDER BY l.ts_utc DESC
        """, params)
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
    if permission_level not in ['L1', 'L2', 'O1', 'A1', 'A2', 'S1']:
        return jsonify({"success": False, "error": "Only L1+ administrators can delete ledger entries"}), 403
    
    try:
        with get_db_connection("inventory") as conn:
            cursor = conn.cursor()
            
            # Get entry with instance filter via asset
            cursor.execute("""
                SELECT l.*, a.sku, a.product, a.instance_id
                FROM asset_ledger l
                JOIN assets a ON l.asset_id = a.id
                WHERE l.id = %s
            """, (entry_id,))
            entry = cursor.fetchone()
            
            if not entry:
                return jsonify({"success": False, "error": "Entry not found"}), 404
            
            # Verify instance access
            try:
                current_instance = get_current_instance()
                if entry['instance_id'] != current_instance:
                    return jsonify({"success": False, "error": "Access denied"}), 403
            except RuntimeError:
                pass
            
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
    if permission_level not in ['L1', 'L2', 'O1', 'A1', 'A2', 'S1']:
        flash("Only L1+ administrators can edit ledger entries", "danger")
        return redirect(url_for('inventory.ledger'))
    
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
        
        return redirect(url_for('inventory.ledger'))
    
    return redirect(url_for('inventory.ledger'))