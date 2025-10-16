# app/modules/inventory/views.py
from __future__ import annotations
from flask import Blueprint, render_template, request, flash, redirect, url_for
import datetime, sqlite3

from ...common.security import login_required, require_asset
from ...common.printing import drop_to_bartender
from ...common.storage import insights_db

inventory_bp = Blueprint("inventory", __name__, template_folder="../../templates")

bp = inventory_bp

ITEM_TYPES = ["Part","Equipment","Sensitive","Supplies","Accessory","Critical"]


def _peek_next_inventory_id() -> int:
    """Suggest the next InventoryID based on max(inventory_id) in insights table."""
    con = insights_db()
    try:
        row = con.execute("SELECT COALESCE(MAX(inventory_id), 10000000) + 1 AS nxt FROM inventory_reports").fetchone()
        nxt = row["nxt"] if row else 10000001
    except sqlite3.OperationalError:
        # table may not exist yet; start a reasonable base
        nxt = 10000001
    finally:
        con.close()
    return int(nxt)


@inventory_bp.route("/", methods=["GET", "POST"])
@login_required
@require_asset
def index():
    """Asset — Add Item (queues an inventory label + writes Insights record)."""
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

        # minimal validation
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

    return render_template("inventory/print.html",
                           active="asset",
                           flashmsg=flashmsg)