from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from app.admin_required import admin_required
from app.supabase_client import get_supabase_client
from app.middleware import with_supabase_auth
from app.license_sync import process_license_cell_update
from app.audit_log import log_audit_action
from app.supabase_helper import fetch_all_rows # Import the new function

from datetime import datetime
from threading import Thread
import uuid

licenses_bp = Blueprint('licenses', __name__)

US_STATES = [
    'Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado', 'Connecticut', 'Delaware', 'Florida', 'Georgia',
    'Hawaii', 'Idaho', 'Illinois', 'Indiana', 'Iowa', 'Kansas', 'Kentucky', 'Louisiana', 'Maine', 'Maryland', 'Massachusetts',
    'Michigan', 'Minnesota', 'Mississippi', 'Missouri', 'Montana', 'Nebraska', 'Nevada', 'New Hampshire', 'New Jersey',
    'New Mexico', 'New York', 'North Carolina', 'North Dakota', 'Ohio', 'Oklahoma', 'Oregon', 'Pennsylvania', 'Puerto Rico', 'Rhode Island',
    'South Carolina', 'South Dakota', 'Tennessee', 'Texas', 'Utah', 'Vermont', 'Virginia', 'Washington', 'West Virginia',
    'Wisconsin', 'Wyoming'
]


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
        "radiologist_id": request.form.get("radiologist_id") or None,
        "state": request.form.get("state") or None,
        "specialty": request.form.get("specialty") or None,
        "status": request.form.get("status") or None,
        "tags": request.form.get("tags") or None,
        "expiration_date": request.form.get("expiration_date") or None
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

    select_query = "*, radiologists(name, active_status)"

    all_certifications_from_db = fetch_all_rows(table="certifications", select_query=select_query)

    temp_query_data = all_certifications_from_db

    search_term = request.args.get('search', '').lower()
    state = request.args.get('state', '')
    doctor_status = request.args.get('status', 'all')

    filtered_certifications = []

    for cert in temp_query_data:
        match_search = True
        if search_term:
            state_match = cert.get('state', '').lower().startswith(search_term)
            specialty_match = cert.get('specialty', '').lower().startswith(search_term)
            tags_match = cert.get('tags', '').lower().startswith(search_term) if cert.get('tags') else False
            radiologist_name_match = cert.get('radiologists', {}).get('name', '').lower().startswith(search_term)
            
            if not (state_match or specialty_match or tags_match or radiologist_name_match):
                match_search = False

        match_state = True
        if state:
            if cert.get('state') != state:
                match_state = False
        
        match_doctor_status = True
        if doctor_status != 'all':
            active_status_str = str(cert.get('radiologists', {}).get('active_status', False)).lower()
            if active_status_str != doctor_status:
                match_doctor_status = False
        
        if match_search and match_state and match_doctor_status:
            filtered_certifications.append(cert)
            
    filtered_certifications.sort(key=lambda x: x.get('state', ''), reverse=False)


    total_count = len(filtered_certifications)

    return jsonify({
        'certifications': filtered_certifications, 
        'total_count': total_count,
        'current_page': 1, 
        'per_page': total_count 
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

    certs_res = supabase.table("certifications") \
        .select("*, radiologists(name)") \
        .order("expiration_date", desc=True) \
        .range(0, 0) \
        .execute()
    certifications = certs_res.data or []

    now = datetime.now()

    return render_template("licenses.html",
                           certifications=certifications,
                           radiologists=radiologists,
                           now=now,
                           total_count=0,
                           current_page=1,
                           us_states=US_STATES)


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
        print("Error in license_sync:", traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500