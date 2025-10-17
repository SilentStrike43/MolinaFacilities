# app/modules/inventory/views.py - DEBUGGING VERSION
# Replace the queue_asset_label function with this version that has detailed logging

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

# Set up logging
logger = logging.getLogger(__name__)

ITEM_TYPES = ["Part","Equipment","Sensitive","Supplies","Accessory","Critical"]

# Ensure schemas exist
ensure_schema()
ensure_assets_schema()

# ---------- Helper functions ----------
def _peek_next_inventory_id() -> int:
    """Suggest the next InventoryID based on max in assets table."""
    con = assets_db()
    try:
        row = con.execute("SELECT COALESCE(MAX(id), 10000000) + 1 AS nxt FROM assets").fetchone()
        nxt = row["nxt"] if row else 10000001
    except sqlite3.OperationalError:
        nxt = 10000001
    finally:
        con.close()
    return int(nxt)

def create_asset(data: dict) -> int:
    """Create a new asset in the master table."""
    con = assets_db()
    cur = con.execute("""
        INSERT INTO assets(sku, product, uom, location, qty_on_hand)
        VALUES (?, ?, ?, ?, ?)
    """, (
        data.get("sku", ""),
        data.get("product", ""),
        data.get("uom", "EA"),
        data.get("location", ""),
        int(data.get("qty_on_hand", 0))
    ))
    asset_id = cur.lastrowid
    con.commit()
    con.close()
    return asset_id

def record_initial_checkin(asset_id: int, qty: int, username: str, note: str = "Initial inventory"):
    """Record initial check-in to ledger and log to insights."""
    con = assets_db()
    
    # Record in asset_ledger
    con.execute("""
        INSERT INTO asset_ledger(asset_id, action, qty, username, note)
        VALUES (?, 'CHECKIN', ?, ?, ?)
    """, (asset_id, qty, username, note))
    
    con.commit()
    con.close()
    
    # Also log to insights (inventory_reports table)
    log_to_insights(asset_id, "CHECKIN", qty, username, note)

def log_to_insights(asset_id: int, action: str, qty: int, username: str, note: str = ""):
    """Log asset movements to insights for reporting."""
    # Get asset details
    con = assets_db()
    asset = con.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
    con.close()
    
    if not asset:
        return
    
    # Log to inventory_reports table
    con = inventory_db()
    con.execute("""
        INSERT INTO inventory_reports(
            inventory_id, item_type, manufacturer, product_name,
            submitter_name, notes, count, location, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        asset_id,
        "Asset Movement",
        "",
        asset["product"] or "",
        username,
        f"{action}: {note}" if note else action,
        qty,
        asset["location"] or "",
        "completed"
    ))
    con.commit()
    con.close()

def queue_asset_label(data: dict):
    """
    Queue an asset label for BarTender printing.
    DEBUGGING VERSION with extensive error handling and logging.
    """
    try:
        # Use company's BarTender drop folder
        BARTENDER_DROP = r"C:\BTManifest\BTInvDrop"
        
        # CHECK 1: Can we create the directory?
        try:
            os.makedirs(BARTENDER_DROP, exist_ok=True)
            logger.info(f"BarTender drop folder ready: {BARTENDER_DROP}")
            print(f"[DEBUG] BarTender drop folder: {BARTENDER_DROP}")
        except Exception as e:
            logger.error(f"Failed to create BarTender folder: {e}")
            print(f"[ERROR] Cannot create folder {BARTENDER_DROP}: {e}")
            raise
        
        # CHECK 2: Is the folder writable?
        if not os.access(BARTENDER_DROP, os.W_OK):
            error_msg = f"BarTender folder not writable: {BARTENDER_DROP}"
            logger.error(error_msg)
            print(f"[ERROR] {error_msg}")
            raise PermissionError(error_msg)
        
        # Generate filename
        import uuid
        ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        filename = f"{ts}_asset_{uuid.uuid4().hex[:8]}.json"
        filepath = os.path.join(BARTENDER_DROP, filename)
        
        print(f"[DEBUG] Will create file: {filepath}")
        
        # BarTender payload - MATCHES YOUR INTEGRATION BUILDER FIELDS
        payload = {
            "CheckInDate": data.get("CheckInDate", datetime.date.today().isoformat()),
            "InventoryID": data.get("InventoryID", ""),
            "ItemType": data.get("ItemType", "Asset"),
            "Manufacturer": data.get("Manufacturer", ""),
            "ProductName": data.get("ProductName", ""),
            "SubmitterName": data.get("SubmitterName", "System")
        }
        
        print(f"[DEBUG] Payload: {json.dumps(payload, indent=2)}")
        logger.info(f"Creating label for Asset {payload['InventoryID']}: {payload['ProductName']}")
        
        # CHECK 3: Can we write the file?
        temp_path = filepath + ".tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            print(f"[DEBUG] Temp file written: {temp_path}")
        except Exception as e:
            logger.error(f"Failed to write temp file: {e}")
            print(f"[ERROR] Cannot write temp file: {e}")
            raise
        
        # CHECK 4: Can we rename the file?
        try:
            os.replace(temp_path, filepath)
            print(f"[DEBUG] File created successfully: {filepath}")
            logger.info(f"Label file created: {filename}")
        except Exception as e:
            logger.error(f"Failed to rename file: {e}")
            print(f"[ERROR] Cannot rename file: {e}")
            raise
        
        # CHECK 5: Does the file exist?
        if os.path.exists(filepath):
            file_size = os.path.getsize(filepath)
            print(f"[SUCCESS] File exists! Size: {file_size} bytes")
            logger.info(f"Verified: {filename} ({file_size} bytes)")
        else:
            print(f"[WARNING] File doesn't exist after creation!")
            logger.warning(f"File not found after creation: {filepath}")
        
        # Log to database
        try:
            con = inventory_db()
            con.execute("""
                INSERT INTO inventory_reports(
                    checkin_date, inventory_id, item_type, manufacturer, product_name,
                    submitter_name, notes, status, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                payload["CheckInDate"],
                payload["InventoryID"],
                payload["ItemType"],
                payload["Manufacturer"],
                payload["ProductName"],
                payload["SubmitterName"],
                f"Asset label queued: {filename}",
                "queued",
                json.dumps(payload, ensure_ascii=False)
            ))
            con.commit()
            con.close()
            print(f"[DEBUG] Database log successful")
        except Exception as e:
            logger.error(f"Failed to log to database: {e}")
            print(f"[ERROR] Database logging failed: {e}")
            # Don't fail the whole operation if just logging fails
        
        return filepath
        
    except Exception as e:
        logger.exception("queue_asset_label failed")
        print(f"[FATAL ERROR] queue_asset_label failed: {e}")
        import traceback
        traceback.print_exc()
        # Re-raise so the calling code knows it failed
        raise

# ---------- Routes ----------

@inventory_bp.route("/asset", methods=["GET", "POST"])
@login_required
@require_asset
def asset():
    """Asset - Add New Asset (prints label and creates in ledger)."""
    cu = current_user()
    today = datetime.date.today().isoformat()
    next_id = _peek_next_inventory_id()
    flashmsg = None

    # Get existing assets for display
    con = assets_db()
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status", "active")
    
    sql = "SELECT * FROM assets WHERE 1=1"
    params = []
    
    if q:
        sql += " AND (product LIKE ? OR sku LIKE ? OR location LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like, like])
    
    sql += " ORDER BY id DESC LIMIT 100"
    rows = con.execute(sql, params).fetchall()
    con.close()

    if request.method == "POST":
        mode = request.form.get("_mode")
        
        if mode == "create":
            print("\n" + "="*80)
            print("[DEBUG] CREATE ASSET STARTED")
            print("="*80)
            
            # Create new asset
            sku = (request.form.get("SKU") or "").strip()
            product = (request.form.get("ProductName") or "").strip()
            location = (request.form.get("Location") or "").strip()
            qty = int(request.form.get("Quantity") or 0)
            uom = request.form.get("UOM", "EA").strip() or "EA"
            
            print(f"[DEBUG] Product: {product}")
            print(f"[DEBUG] Location: {location}")
            print(f"[DEBUG] Quantity: {qty}")
            
            if not product or not location:
                flashmsg = ("Product Name and Location are required.", False)
            elif qty <= 0:
                flashmsg = ("Quantity must be greater than 0.", False)
            else:
                # Create asset
                asset_data = {
                    "sku": sku or f"SKU-{next_id}",
                    "product": product,
                    "uom": uom,
                    "location": location,
                    "qty_on_hand": qty
                }
                asset_id = create_asset(asset_data)
                print(f"[DEBUG] Asset created with ID: {asset_id}")
                
                # Record initial check-in
                record_initial_checkin(
                    asset_id, 
                    qty, 
                    cu.get("username", ""), 
                    "Initial inventory entry"
                )
                print(f"[DEBUG] Initial check-in recorded")
                
                # MANDATORY: Queue label per company policy
                try:
                    label_data = {
                        "CheckInDate": today,
                        "InventoryID": str(asset_id),
                        "ItemType": request.form.get("ItemType", "Asset"),
                        "Manufacturer": request.form.get("Manufacturer", ""),
                        "ProductName": product,
                        "SubmitterName": cu.get("username", "System")
                    }
                    
                    print(f"[DEBUG] Calling queue_asset_label...")
                    label_file = queue_asset_label(label_data)
                    print(f"[DEBUG] Label queued successfully: {label_file}")
                    
                    flashmsg = (f"✅ Asset #{asset_id} created. Label file: {os.path.basename(label_file)}", True)
                    record_audit(cu, "create_asset", "inventory", f"Created asset #{asset_id}: {product}, label queued")
                    
                except Exception as e:
                    print(f"[ERROR] Label queueing failed: {e}")
                    import traceback
                    traceback.print_exc()
                    flashmsg = (f"⚠️ Asset #{asset_id} created but label printing failed: {str(e)}", False)
                    record_audit(cu, "create_asset_error", "inventory", f"Asset #{asset_id} created but label failed: {str(e)}")
                
                next_id += 1
            
            print("="*80)
            print("[DEBUG] CREATE ASSET FINISHED")
            print("="*80 + "\n")
        
        elif mode == "update":
            # Update existing asset
            asset_id = int(request.form.get("id") or 0)
            sku = (request.form.get("SKU") or "").strip()
            product = (request.form.get("ProductName") or "").strip()
            location = (request.form.get("Location") or "").strip()
            uom = request.form.get("UOM", "EA").strip() or "EA"
            
            con = assets_db()
            con.execute("""
                UPDATE assets 
                SET sku=?, product=?, uom=?, location=?
                WHERE id=?
            """, (sku, product, uom, location, asset_id))
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
        next_inv=next_id,
        item_types=ITEM_TYPES,
        rows=rows,
        q=q,
        status=status,
        edit=edit
    )

# ... rest of the routes remain the same ...

@inventory_bp.route("/asset/<int:aid>/edit")
@login_required
@require_asset
def asset_edit(aid: int):
    """Redirect to asset page with edit parameter."""
    return redirect(url_for("inventory.asset", edit=aid))

@inventory_bp.route("/ledger")
@login_required
@require_asset
def ledger():
    """Asset ledger - moved to asset_ledger blueprint."""
    return redirect(url_for("asset_ledger.ledger_home"))

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