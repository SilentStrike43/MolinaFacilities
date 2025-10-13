# app/modules/reports/views.py
from flask import Blueprint, request, render_template, send_file, abort, redirect, url_for, Response
from app.common.storage import jobs_db, ensure_jobs_schema, ensure_inventory_schema
from app.common.printing import drop_to_bartender
import io, csv, json

reports_bp = Blueprint("reports", __name__, template_folder="../../templates")

# ---------- helpers ----------
def _filters_mail():
    return {
        "q": (request.args.get("q") or "").strip(),
        "tracking": (request.args.get("tracking") or "").strip(),
        "checkin_id": (request.args.get("checkin_id") or "").strip(),
        "ptype": (request.args.get("ptype") or "").strip(),
        "date_from": (request.args.get("date_from") or "").strip(),
        "date_to": (request.args.get("date_to") or "").strip(),
        "pii": request.args.get("pii"),
    }

def _build_where_mail(f):
    sql = "WHERE module='mail'"
    params = []
    if f["q"]:
        like = f"%{f['q']}%"
        sql += " AND (recipient_name LIKE ? OR tracking_number LIKE ? OR package_id LIKE ? OR checkin_id LIKE ? OR payload LIKE ?)"
        params += [like, like, like, like, like]
    if f["tracking"]:  sql += " AND tracking_number = ?"; params.append(f["tracking"])
    if f["checkin_id"]:sql += " AND checkin_id = ?";     params.append(f["checkin_id"])
    if f["ptype"]:     sql += " AND package_type = ?";   params.append(f["ptype"])
    if f["date_from"]: sql += " AND date(checkin_date) >= date(?)"; params.append(f["date_from"])
    if f["date_to"]:   sql += " AND date(checkin_date) <= date(?)"; params.append(f["date_to"])
    return sql, params

def _query_mail(f):
    ensure_jobs_schema()
    con = jobs_db()
    where, params = _build_where_mail(f)
    rows = con.execute(f"""
        SELECT id, ts_utc, checkin_id, package_type, package_id, recipient_name, tracking_number,
               checkin_date, status, printer, template, payload
        FROM print_jobs
        {where}
        ORDER BY ts_utc DESC
        LIMIT 1000
    """, params).fetchall()
    con.close()
    return rows

def _filters_inventory():
    return {
        "q": (request.args.get("q") or "").strip(),
        "inventory_id": (request.args.get("inventory_id") or "").strip(),
        "item_type": (request.args.get("item_type") or "").strip(),
        "manufacturer": (request.args.get("manufacturer") or "").strip(),
        "product_name": (request.args.get("product_name") or "").strip(),
        "submitter_name": (request.args.get("submitter_name") or "").strip(),
        "date_from": (request.args.get("date_from") or "").strip(),
        "date_to": (request.args.get("date_to") or "").strip(),
        "pii": request.args.get("pii"),
    }

def _build_where_inventory(f):
    sql = "WHERE 1=1"
    params = []
    if f["q"]:
        like = f"%{f['q']}%"
        sql += " AND (manufacturer LIKE ? OR product_name LIKE ? OR submitter_name LIKE ? OR item_type LIKE ? OR CAST(inventory_id AS TEXT) LIKE ? OR payload LIKE ?)"
        params += [like, like, like, like, like, like]
    if f["inventory_id"]: sql += " AND inventory_id = ?"; params.append(int(f["inventory_id"]))
    if f["item_type"]:    sql += " AND item_type = ?";    params.append(f["item_type"])
    if f["manufacturer"]: sql += " AND manufacturer LIKE ?"; params.append(f["manufacturer"] + "%")
    if f["product_name"]: sql += " AND product_name LIKE ?"; params.append(f["product_name"] + "%")
    if f["submitter_name"]: sql += " AND submitter_name LIKE ?"; params.append(f["submitter_name"] + "%")
    if f["date_from"]:    sql += " AND date(checkin_date) >= date(?)"; params.append(f["date_from"])
    if f["date_to"]:      sql += " AND date(checkin_date) <= date(?)"; params.append(f["date_to"])
    return sql, params

def _query_inventory(f):
    ensure_inventory_schema()
    con = jobs_db()
    where, params = _build_where_inventory(f)
    rows = con.execute(f"""
        SELECT id, ts_utc, checkin_date, inventory_id, item_type,
               manufacturer, product_name, submitter_name, notes,
               part_number, serial_number, count, location,
               template, printer, status, payload
        FROM inventory_reports
        {where}
        ORDER BY ts_utc DESC
        LIMIT 1000
    """, params).fetchall()
    con.close()
    return rows

# ---------- routes ----------
@reports_bp.route("/")
def root():
    return mail()

@reports_bp.route("/mail")
def mail():
    f = _filters_mail()
    rows = _query_mail(f)
    return render_template("inventory/reports_tabs.html",
                           active="insights", tab="mail", rows=rows, **f)

@reports_bp.route("/inventory")
def inventory():
    f = _filters_inventory()
    rows = _query_inventory(f)
    return render_template("reports_inventory.html",
                           active="insights", rows=rows, **f)

# ----- CSV (mail) -----
@reports_bp.route("/export/mail.csv")
def export_mail():
    f = _filters_mail(); rows = _query_mail(f)
    out = io.StringIO(); w = csv.writer(out)
    headers = ["id","ts_utc","checkin_id","package_type","package_id","recipient_name","tracking_number","checkin_date","status","printer","template"]
    w.writerow(headers)
    for r in rows: w.writerow([r[h] for h in headers])
    mem = io.BytesIO(out.getvalue().encode("utf-8")); mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="mail_reports.csv")

# ----- CSV (inventory) -----
@reports_bp.route("/export/inventory.csv")
def export_inventory():
    f = _filters_inventory(); rows = _query_inventory(f)
    out = io.StringIO(); w = csv.writer(out)
    headers = ["id","ts_utc","checkin_date","inventory_id","item_type","manufacturer","product_name","submitter_name","notes","part_number","serial_number","count","location","template","printer","status"]
    w.writerow(headers)
    for r in rows: w.writerow([r[h] for h in headers])
    mem = io.BytesIO(out.getvalue().encode("utf-8")); mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="inventory_reports.csv")

# ----- Edit / Delete / Reprint (MAIL) -----
@reports_bp.route("/mail/<int:rid>/edit", methods=["GET","POST"])
def edit_mail(rid: int):
    ensure_jobs_schema(); con = jobs_db()
    if request.method == "POST":
        form = request.form
        con.execute("""
            UPDATE print_jobs SET
              checkin_date=?, checkin_id=?, package_type=?, package_id=?,
              recipient_name=?, tracking_number=?, status=?, printer=?, template=?
            WHERE id=?
        """, (
            form.get("checkin_date"), form.get("checkin_id"), form.get("package_type"), form.get("package_id"),
            form.get("recipient_name"), form.get("tracking_number"), form.get("status"),
            form.get("printer"), form.get("template"), rid
        ))
        con.commit(); con.close()
        return redirect(url_for("reports.mail"))
    row = con.execute("SELECT * FROM print_jobs WHERE id=?", (rid,)).fetchone(); con.close()
    if not row: abort(404)
    return render_template("reports_edit_mail.html", row=row)

@reports_bp.route("/mail/<int:rid>/delete", methods=["POST"])
def delete_mail(rid: int):
    ensure_jobs_schema(); con = jobs_db()
    con.execute("DELETE FROM print_jobs WHERE id=?", (rid,)); con.commit(); con.close()
    return redirect(url_for("reports.mail"))

@reports_bp.route("/mail/<int:rid>/reprint", methods=["POST"])
def reprint_mail(rid: int):
    ensure_jobs_schema()
    con = jobs_db()
    row = con.execute("SELECT payload FROM print_jobs WHERE id=?", (rid,)).fetchone()
    con.close()
    if not row: abort(404)
    payload = json.loads(row["payload"] or "{}")
    drop_to_bartender(payload, hint="manifest", module="mail")
    return redirect(url_for("reports.mail"))

# ----- Edit / Delete / Reprint (INVENTORY) -----
@reports_bp.route("/inventory/<int:rid>/edit", methods=["GET","POST"])
def edit_inventory(rid: int):
    ensure_inventory_schema(); con = jobs_db()
    if request.method == "POST":
        f = request.form
        con.execute("""
            UPDATE inventory_reports SET
              checkin_date=?, inventory_id=?, item_type=?, manufacturer=?, product_name=?, submitter_name=?, notes=?,
              part_number=?, serial_number=?, count=?, location=?, status=?, printer=?, template=?
            WHERE id=?
        """, (
            f.get("checkin_date"), f.get("inventory_id"), f.get("item_type"), f.get("manufacturer"),
            f.get("product_name"), f.get("submitter_name"), f.get("notes"),
            f.get("part_number") or "N/A", f.get("serial_number") or "N/A",
            int(f.get("count") or 0), f.get("location"),
            f.get("status"), f.get("printer"), f.get("template"), rid
        ))
        con.commit(); con.close()
        return redirect(url_for("reports.inventory"))
    row = con.execute("SELECT * FROM inventory_reports WHERE id=?", (rid,)).fetchone(); con.close()
    if not row: abort(404)
    return render_template("reports_edit_inventory.html", row=row)

@reports_bp.route("/inventory/<int:rid>/delete", methods=["POST"])
def delete_inventory(rid: int):
    ensure_inventory_schema(); con = jobs_db()
    con.execute("DELETE FROM inventory_reports WHERE id=?", (rid,)); con.commit(); con.close()
    return redirect(url_for("reports.inventory"))

@reports_bp.route("/inventory/<int:rid>/reprint", methods=["POST"])
def reprint_inventory(rid: int):
    ensure_inventory_schema()
    con = jobs_db()
    row = con.execute("SELECT payload FROM inventory_reports WHERE id=?", (rid,)).fetchone()
    con.close()
    if not row: abort(404)
    payload = json.loads(row["payload"] or "{}")
    drop_to_bartender(payload, hint="inventory", module="inventory")
    return redirect(url_for("reports.inventory"))

# ----- JSON payload views -----
@reports_bp.route("/json/mail/<int:job_id>")
def json_view_mail(job_id: int):
    ensure_jobs_schema()
    con = jobs_db()
    row = con.execute("SELECT payload FROM print_jobs WHERE id=?", (job_id,)).fetchone()
    con.close()
    if not row: abort(404)
    return Response(row["payload"] or "{}", mimetype="application/json")

@reports_bp.route("/json/inventory/<int:rec_id>")
def json_view_inventory(rec_id: int):
    ensure_inventory_schema()
    con = jobs_db()
    row = con.execute("SELECT payload FROM inventory_reports WHERE id=?", (rec_id,)).fetchone()
    con.close()
    if not row: abort(404)
    return Response(row["payload"] or "{}", mimetype="application/json")

