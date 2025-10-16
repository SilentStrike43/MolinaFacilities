# app/common/ui.py
from flask import url_for
from app.common.security import has_cap, has_any

def build_sidebar(user, *_):
    """
    Returns a list of sections:
    [{"title": "...", "items":[{"href": "...", "icon":"...", "label":"..."}]}]
    Only includes modules the user can access; elevated users see all.
    """
    sections = []

    # --- Operations (Mail) ---
    # Show if can_send
    if has_cap(user, "can_send"):
        sections.append({
            "title": "OPERATIONS",
            "items": [
                {"href": url_for("mail.index"), "icon": "bi-send", "label": "Send"},
                {"href": url_for("mail.tracking"), "icon": "bi-binoculars", "label": "Tracking"},
            ]
        })

    # --- Fulfillment center ---
    if has_any(user, "can_fulfillment_staff", "can_fulfillment_customer"):
        items = [
            {"href": url_for("fulfillment.request_form"), "icon": "bi-cloud-upload", "label": "Request Fulfillment"},
            {"href": url_for("fulfillment.queue"),         "icon": "bi-list-check",  "label": "Service Queue"},
            {"href": url_for("fulfillment.archive"),       "icon": "bi-archive",     "label": "Service Archive"},
        ]
        sections.append({"title": "FULFILLMENT CENTER", "items": items})

    # --- Inventory ---
    if has_cap(user, "can_asset"):
        sections.append({
            "title": "INVENTORY",
            "items": [
                {"href": url_for("inventory.index"),       "icon": "bi-box-seam",        "label": "Asset"},
                {"href": url_for("inventory.ledger_home"), "icon": "bi-journal-text",    "label": "Asset Ledger"},
            ]
        })

    # --- Reports (per module) ---
    report_items = []
    if has_cap(user, "can_send"):
        report_items.append({"href": url_for("mail.insights"), "icon": "bi-graph-up", "label": "Insights (Mail)"})
    if has_cap(user, "can_asset"):
        report_items.append({"href": url_for("inventory.insights"), "icon":"bi-clipboard-data","label":"Insights (Inventory)"})
    if has_any(user, "can_fulfillment_staff", "can_fulfillment_customer"):
        report_items.append({"href": url_for("fulfillment.insights"), "icon":"bi-clipboard-data","label":"Insights (Fulfillment)"})
    if report_items:
        sections.append({"title": "REPORTS", "items": report_items})

    # --- People ---
    if has_cap(user, "can_users") or (user and (user.get("is_admin") or user.get("is_sysadmin") or user.get("is_system"))):
        sections.append({
            "title": "PEOPLE",
            "items": [
                {"href": url_for("users.user_list"), "icon":"bi-people", "label":"Users"},
                {"href": url_for("users.manage"),    "icon":"bi-person-plus", "label":"Modify Users"},
            ]
        })

    # --- Admin ---
    if user and (user.get("is_admin") or user.get("is_sysadmin") or user.get("is_system")):
        sections.append({
            "title": "ADMIN",
            "items": [
                {"href": url_for("admin.modify_fields"), "icon":"bi-sliders", "label":"Fields"},
            ]
        })

    return sections