# app/modules/reports/views.py
from __future__ import annotations
from flask import Blueprint, render_template, request, send_file
from ...common.security import login_required, require_insights
from ...common.storage import insights_db
import io, csv

reports_bp = Blueprint("reports", __name__, template_folder="../../templates")

# ---------- MAIL ----------
def _mail_filters():
    q = (request.args.get("q") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to   = (request.args.get("date_to") or "").strip()
    carrier   = (request.args.get("carrier") or "").strip()
    return q, date_from, date_to, carrier

def _query_mail():
    con = insights_db()
    q, date_from, date_to, carrier = _mail_filters()
    sql = "SELECT * FROM print_jobs WHERE 1=1"
    params = []
    if q:
        like = f"%{q}%"
        sql += " AND (to_name LIKE ? OR submitter_name LIKE ? OR tracking LIKE ?)"
        params += [like, like, like]
    if date_from:
        sql += " AND date(ts_utc) >= date(?)"; params.append(date_from)
    if date_to:
        sql += " AND date(ts_utc) <= date(?)"; params.append(date_to)
    if carrier:
        sql += " AND carrier = ?"; params.append(carrier)
    sql += " ORDER BY ts_utc DESC LIMIT 2000"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return rows

@reports_bp.route("/insights/mail")
@login_required
@require_insights
def mail():
    q, date_from, date_to, carrier = _mail_filters()
    rows = _query_mail()
    carriers = ["USPS","UPS","FedEx","Other"]
    return render_template("reports_mail.html", active="insights", tab="mail",
                           rows=rows, q=q, date_from=date_from, date_to=date_to, carrier=carrier, carriers=carriers)

@reports_bp.route("/insights/mail.csv")
@login_required
@require_insights
def export_mail():
    rows = _query_mail()
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["ts_utc","submitter_name","item_type","carrier","tracking","to_name"])
    for r in rows:
        w.writerow([r["ts_utc"], r["submitter_name"], r["item_type"], r["carrier"], r["tracking"], r["to_name"]])
    mem = io.BytesIO(out.getvalue().encode("utf-8")); mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="insights_mail.csv")


# ---------- INVENTORY ----------
def _inv_filters():
    f = {k:(request.args.get(k) or "").strip() for k in
         ["q","inventory_id","product_name","manufacturer","item_type","submitter_name","pii","date_from","date_to"]}
    return f

def _query_inventory(f):
    con = insights_db()
    sql = "SELECT * FROM inventory_reports WHERE 1=1"
    params = []
    def like(field,val):
        nonlocal sql, params
        if val: sql += f" AND {field} LIKE ?"; params.append(f"%{val}%")
    like("submitter_name", f["submitter_name"])
    like("product_name", f["product_name"])
    like("manufacturer", f["manufacturer"])
    like("item_type", f["item_type"])
    if f["inventory_id"]:
        sql += " AND inventory_id = ?"; params.append(f["inventory_id"])
    if f["pii"]:
        sql += " AND pii = ?"; params.append(f["pii"])
    if f["q"]:
        like("(notes || ' ' || product_name || ' ' || manufacturer)", f["q"])
    if f["date_from"]:
        sql += " AND date(ts_utc) >= date(?)"; params.append(f["date_from"])
    if f["date_to"]:
        sql += " AND date(ts_utc) <= date(?)"; params.append(f["date_to"])
    sql += " ORDER BY ts_utc DESC LIMIT 2000"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return rows

@reports_bp.route("/insights/inventory")
@login_required
@require_insights
def inventory():
    f = _inv_filters()
    rows = _query_inventory(f)
    return render_template("reports_inventory.html", active="insights", tab="inventory", rows=rows, **f)

@reports_bp.route("/insights/inventory.csv")
@login_required
@require_insights
def export_inventory():
    f = _inv_filters()
    rows = _query_inventory(f)
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["ts_utc","inventory_id","product_name","manufacturer","item_type","submitter_name","pii","notes"])
    for r in rows:
        w.writerow([r["ts_utc"], r["inventory_id"], r["product_name"], r["manufacturer"],
                    r["item_type"], r["submitter_name"], r["pii"], r["notes"]])
    mem = io.BytesIO(out.getvalue().encode("utf-8")); mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="insights_inventory.csv")