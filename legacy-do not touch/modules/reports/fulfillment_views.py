# app/modules/reports/fulfillment_views.py
from flask import Blueprint, render_template, request, send_file
import io, csv
from ...common.security import login_required, require_admin, current_user
from ...common.fulfillment import search_archive

reports_f_bp = Blueprint("reports_fulfillment", __name__, template_folder="../../templates")

@reports_f_bp.route("/reports/fulfillment")
@login_required
def fulfillment_report():
    q         = (request.args.get("q") or "").strip()
    requester = (request.args.get("requester") or "").strip()
    status    = (request.args.get("status") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to   = (request.args.get("date_to") or "").strip()

    rows = search_archive(q, requester, status, date_from, date_to, limit=3000)
    return render_template("reports_fulfillment.html",
                           active="insights", tab="fulfillment",
                           rows=rows, q=q, requester=requester, status=status,
                           date_from=date_from, date_to=date_to)

@reports_f_bp.route("/reports/fulfillment.csv")
@login_required
def fulfillment_report_csv():
    q         = (request.args.get("q") or "").strip()
    requester = (request.args.get("requester") or "").strip()
    status    = (request.args.get("status") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to   = (request.args.get("date_to") or "").strip()
    rows = search_archive(q, requester, status, date_from, date_to, limit=100000)

    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["ServiceID","Description","Requester","Submitted","Status","FulfilledBy","Completed","Files(JSON)"])
    for r in rows:
        w.writerow([r["service_id"], r["description"], r["requester_name"], r["submitted_at"],
                    r["status"], r["fulfilled_by"], r["completed_at"], r["files_json"]])
    mem = io.BytesIO(out.getvalue().encode("utf-8")); mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="fulfillment_insights.csv")
