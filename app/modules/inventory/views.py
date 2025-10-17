# app/modules/inventory/views.py
import os
import json
import datetime
import sqlite3
from flask import Blueprint, render_template, request, redirect, url_for, flash

from app.core.auth import login_required, require_asset, current_user, record_audit

# module-local DB
from app.modules.inventory.storage import inventory_db, ensure_schema

inventory_bp = Blueprint("inventory", __name__, url_prefix="/inventory", template_folder="templates")
bp = inventory_bp

ITEM_TYPES = ["Part","Equipment","Sensitive","Supplies","Accessory","Critical"]

# Ensure schema exists
ensure_schema()

# ---------- Helper functions ----------
def _peek_next_inventory_id() -> int:
    """Suggest the next InventoryID based on max(inventory_id) in reports table."""
    con = inventory_db()
    try:
        row = con.execute("""
            SELECT COALESCE(MAX(inventory_id), 10000000) + 1 AS nxt 
            FROM inventory_reports
        """).fetchone()
        nxt = row["nxt"] if row else 10000001
    except sqlite3.OperationalError:
        nxt = 10000001
    finally:
        con.close()
    return int(nxt)

def drop_to_bartender(data: dict, hint: str = "inventory", module: str = "inventory"):
    """
    Spool a print job and insert into inventory_reports for tracking.
    """
    # Create spool directory
    spool_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "spool")
    os.makedirs(spool_dir, exist_ok=True)
    
    # Write JSON file
    import uuid
    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    filename = f"{ts}_{hint}_{uuid.uuid4().hex[:8]}.json"
    filepath = os.path.join(spool_dir, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    # Insert into database
    con = inventory_db()
    con.execute("""
        INSERT INTO inventory_reports(
            checkin_date, inventory_id, item_type, manufacturer, product_name,
            submitter_name, notes, part_number, serial_number, count, location,
            template, printer, status, payload
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        data.get("CheckInDate", ""),
        int(data.get("InventoryID") or 0),
        data.get("ItemType", ""),
        data.get("Manufacturer", ""),
        data.get("ProductName", ""),
        data.get("SubmitterName", ""),
        data.get("Notes", ""),
        data.get("PartNumber", "N/A"),
        data.get("SerialNumber", "N/A"),
        int(data.get("Count") or 0),
        data.get("Location", ""),
        data.get("Template", ""),
        data.get("Printer", ""),
        data.get("Status", "queued"),
        json.dumps(data, ensure_ascii=False)
    ))
    con.commit()
    con.close()
    
    return {"json_file": filepath}

# ---------- Routes ----------
@inventory_bp.route("/", methods=["GET", "POST"])
@login_required
@require_asset
def index():
    """Asset — Add Item (queues an inventory label)."""
    today = datetime.date.today().isoformat()
    suggested_id = _peek_next_inventory_id()
    flashmsg = None

    if request.method == "POST":
        data = {
            "CheckInDate":   request.form.get("CheckInDate") or today,
            "InventoryID":   (request.form.get("InventoryID") or "").strip(),
            "ItemType":      request.form.get("ItemType") or "",
            "Manufacturer":  (request.form.get("Manufacturer") or "").strip(),
            "ProductName":   (request.form.get("ProductName") or "").strip(),
            "SubmitterName": (request.form.get("SubmitterName") or "").strip(),
            "Notes":         (request.form.get("Notes") or "").strip(),
            "PartNumber":    (request.form.get("PartNumber") or "").strip() or "N/A",
            "SerialNumber":  (request.form.get("SerialNumber") or "").strip() or "N/A",
            "Count":         (request.form.get("Count") or "0").strip(),
            "Location":      (request.form.get("Location") or "").strip(),
            "Template":      "Inventory_Label.btw",
            "Printer":       "",
            "Status":        "queued",
        }

        # auto-assign InventoryID if empty/non-numeric
        if not data["InventoryID"].isdigit():
            data["InventoryID"] = str(_peek_next_inventory_id())

        # validation
        required = ["ItemType","Manufacturer","ProductName","SubmitterName","Count","Location"]
        missing = [k for k in required if not data[k]]
        if missing:
            flashmsg = (f"Missing: {', '.join(missing)}", False)
        else:
            drop_to_bartender(data, hint="inventory", module="inventory")
            flashmsg = ("Queued inventory label.", True)
            suggested_id = int(data["InventoryID"]) + 1

    return render_template(
        "inventory/index.html",
        active="asset",
        flashmsg=flashmsg,
        today=today,
        suggested_id=suggested_id,
        item_types=ITEM_TYPES,
    )

@inventory_bp.route("/print", methods=["GET", "POST"])
@login_required
@require_asset
def print_label():
    """Inventory — ad-hoc simple label."""
    flashmsg = None
    if request.method == "POST":
        payload = {
            "ItemSKU":   (request.form.get("ItemSKU") or "").strip(),
            "ItemName":  (request.form.get("ItemName") or "").strip(),
            "Count":     int(request.form.get("Count") or "1"),
            "Location":  (request.form.get("Location") or "").strip(),
            "Template":  "Inventory_Simple.btw",
            "Printer":   "",
            "Status":    "queued",
        }
        if not payload["ItemSKU"] or not payload["ItemName"]:
            flashmsg = ("Item SKU and Name are required.", False)
        else:
            drop_to_bartender(payload, hint="inventory_simple", module="inventory")
            flashmsg = ("Queued label for printing.", True)

    return render_template("inventory/print.html", active="asset", flashmsg=flashmsg)

@inventory_bp.route("/insights")
@login_required
@require_asset
def insights():
    """Inventory insights/reports page."""
    f = {k:(request.args.get(k) or "").strip() for k in
         ["q","inventory_id","product_name","manufacturer","item_type",
          "submitter_name","pii","date_from","date_to"]}
    
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
    
    con = inventory_db()
    rows = con.execute("SELECT * FROM inventory_reports ORDER BY ts_utc DESC").fetchall()
    con.close()
    
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["ts_utc","inventory_id","product_name","manufacturer","item_type","submitter_name","notes"])
    for r in rows:
        w.writerow([r["ts_utc"], r["inventory_id"], r["product_name"], r["manufacturer"],
                    r["item_type"], r["submitter_name"], r["notes"]])
    
    from flask import send_file
    mem = io.BytesIO(out.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="insights_inventory.csv")

# Stub routes for asset management
@inventory_bp.route("/asset")
@login_required
@require_asset
def asset():
    """Asset management page (stub)."""
    return render_template("blank.html", title="Asset Management", 
                          message="Asset management coming soon.")

@inventory_bp.route("/ledger")
@login_required
@require_asset
def ledger():
    """Asset ledger page (stub)."""
    return render_template("blank.html", title="Asset Ledger", 
                          message="Asset ledger coming soon.")