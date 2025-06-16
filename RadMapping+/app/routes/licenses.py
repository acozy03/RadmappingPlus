from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from app.admin_required import admin_required
from app.supabase_client import get_supabase_client
from app.middleware import with_supabase_auth
from app.license_sync import process_license_cell_update
from app.audit_log import log_audit_action

from datetime import datetime
from threading import Thread
import uuid

licenses_bp = Blueprint('licenses', __name__)


@licenses_bp.route('/doctors/<string:rad_id>/licenses/<string:cert_id>/delete', methods=["POST"])
@with_supabase_auth
def delete_certification(rad_id, cert_id):
    supabase = get_supabase_client()
    if session["user"]["role"] != "admin":
        return "Unauthorized", 403

    old_data = supabase.table("certifications").select("*").eq("id", cert_id).single().execute().data
    res = supabase.table("certifications").delete().eq("id", cert_id).execute()

    if not hasattr(res, "error"):
        log_audit_action(
            supabase=supabase,
            action="delete",
            table_name="certifications",
            record_id=cert_id,
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=old_data,
            new_data=None
        )

    return redirect(url_for('licenses.licenses_page'))


@licenses_bp.route('/licenses/<string:license_id>/update', methods=["POST"])
@with_supabase_auth
@admin_required
def update_license(license_id):
    supabase = get_supabase_client()

    data = {
        "radiologist_id": request.form.get("radiologist_id"),
        "state": request.form.get("state"),
        "specialty": request.form.get("specialty"),
        "status": request.form.get("status"),
        "tags": request.form.get("tags"),
        "expiration_date": request.form.get("expiration_date")
    }

    old_data = supabase.table("certifications").select("*").eq("id", license_id).single().execute().data
    res = supabase.table("certifications").update(data).eq("id", license_id).execute()

    if not hasattr(res, "error"):
        log_audit_action(
            supabase=supabase,
            action="update",
            table_name="certifications",
            record_id=license_id,
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=old_data,
            new_data=data
        )

    return jsonify({"status": "success"})


@licenses_bp.route('/licenses/search', methods=["GET"])
@with_supabase_auth
def search_licenses():
    supabase = get_supabase_client()
    page = request.args.get('page', 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page

    search_term = request.args.get('search', '')
    doctor_id = request.args.get('doctor', '')
    status = request.args.get('status', 'all')

    query = supabase.table("certifications").select("*, radiologists(name)")

    if search_term:
        query = query.ilike('state', f'%{search_term}%')
    if doctor_id:
        query = query.eq('radiologist_id', doctor_id)
    if status != 'all':
        query = query.eq('status', status)

    count_res = query.execute()
    total_count = len(count_res.data)

    query = query.order("expiration_date", desc=True).range(offset, offset + per_page - 1)
    results = query.execute()

    return jsonify({
        'certifications': results.data,
        'total_count': total_count,
        'current_page': page,
        'per_page': per_page
    })


@licenses_bp.route('/licenses', methods=["GET", "POST"])
@with_supabase_auth
def licenses_page():
    supabase = get_supabase_client()
    rads_res = supabase.table("radiologists").select("id, name, active_status").order("name").execute()
    radiologists = rads_res.data or []

    if request.method == "POST":
        doctor_id = request.form.get("doctor")
        state = request.form.get("state")
        expiration_date = request.form.get("exp")
        specialty = request.form.get("specialty")

        if not specialty:
            existing = supabase.table("certifications") \
                .select("specialty") \
                .eq("radiologist_id", doctor_id) \
                .neq("specialty", None) \
                .limit(1).execute()
            if existing.data:
                specialty = existing.data[0]["specialty"]

        tags = request.form.get("tags")
        status = request.form.get("status")

        if doctor_id and state and expiration_date:
            new_cert = {
                "id": str(uuid.uuid4()),
                "radiologist_id": doctor_id,
                "state": state,
                "expiration_date": expiration_date,
                "specialty": specialty,
                "tags": tags,
                "status": status
            }
            res = supabase.table("certifications").insert(new_cert).execute()

            if not hasattr(res, "error"):
                log_audit_action(
                    supabase=supabase,
                    action="insert",
                    table_name="certifications",
                    record_id=new_cert["id"],
                    user_email=session.get("user", {}).get("email", "unknown"),
                    old_data=None,
                    new_data=new_cert
                )

        return redirect(url_for("licenses.licenses_page"))

    page = request.args.get('page', 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page

    count_res = supabase.table("certifications").select("*", count='exact').execute()
    total_count = count_res.count

    certs_res = supabase.table("certifications") \
        .select("*, radiologists(name)") \
        .order("expiration_date", desc=True) \
        .range(offset, offset + per_page - 1) \
        .execute()
    certifications = certs_res.data or []

    now = datetime.now()

    return render_template("licenses.html",
                           certifications=certifications,
                           radiologists=radiologists,
                           now=now,
                           total_count=total_count,
                           current_page=page,
                           per_page=per_page)


@licenses_bp.route('/licenses/license-sync', methods=["POST"])
def license_sync():
    try:
        data = request.get_json(force=True)
        sheet_id = data.get("sheetId")
        row = data.get("row")
        col = data.get("col")

        if not sheet_id or not row or not col:
            return jsonify({"error": "Missing required fields"}), 400

        def run_in_background():
            process_license_cell_update(sheet_id, row)

        Thread(target=run_in_background).start()
        return jsonify({"status": "License sync started"}), 202

    except Exception as e:
        import traceback
        print("❌ Error in license_sync:", traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500
