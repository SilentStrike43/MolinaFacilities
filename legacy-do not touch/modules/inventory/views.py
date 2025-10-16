# app/modules/inventory/views.py
from flask import Blueprint, render_template, request
import datetime
from ...common.printing import drop_to_bartender
from ...common.storage import peek_next_inventory_id, next_inventory_id

inventory_bp = Blueprint("inventory", __name__, template_folder="../../templates")

ITEM_TYPES = ["Part","Equipment","Sensitive","Supplies","Accessory","Critical"]

@inventory_bp.route("/", methods=["GET", "POST"])
def index():
    msg, ok = None, True
    today = datetime.date.today().isoformat()
    suggested_id = peek_next_inventory_id()

    if request.method == "POST":
        checkin_date   = (request.form.get("CheckInDate") or today).strip()
        inventory_id   = (request.form.get("InventoryID") or "").strip()
        item_type      = (request.form.get("ItemType") or "").strip()
        manufacturer   = (request.form.get("Manufacturer") or "").strip()
        product_name   = (request.form.get("ProductName") or "").strip()
        submitter_name = (request.form.get("SubmitterName") or "").strip()
        notes          = (request.form.get("Notes") or "").strip()

        part_number    = (request.form.get("PartNumber") or "").strip()
        serial_number  = (request.form.get("SerialNumber") or "").strip()
        count_str      = (request.form.get("Count") or "").strip()
        location       = (request.form.get("Location") or "").strip()

        # validations
        if not count_str.isdigit() or int(count_str) <= 0:
            msg, ok = "Count is required and must be a positive number.", False
        elif not location:
            msg, ok = "Location is required.", False
        elif not item_type or item_type not in ITEM_TYPES:
            msg, ok = "Select a valid Item Type.", False
        elif not manufacturer or not product_name or not submitter_name:
            msg, ok = "Manufacturer, Product Name, and Submitter are required.", False
        else:
            inv_id_val = int(inventory_id) if inventory_id.isdigit() else next_inventory_id()
            if not part_number and not serial_number:
                part_number, serial_number = "N/A", "N/A"
            payload = {
                "CheckInDate":   checkin_date,
                "InventoryID":   inv_id_val,
                "ItemType":      item_type,
                "Manufacturer":  manufacturer,
                "ProductName":   product_name,
                "SubmitterName": submitter_name,
                "Notes":         notes,
                "PartNumber":    part_number,
                "SerialNumber":  serial_number,
                "Count":         int(count_str),
                "Location":      location,
                "Printer":       ""
            }
            job = drop_to_bartender(payload, hint="inventory", module="inventory")
            msg, ok = f"Inventory queued. JSON file: {job['json_file']}", True
            suggested_id = inv_id_val + 1

    return render_template(
        "inventory/index.html",
        active="asset",
        flashmsg=(msg, ok),
        today=today,
        suggested_id=suggested_id,
        item_types=ITEM_TYPES
    )