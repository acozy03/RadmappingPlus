from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from app.admin_required import admin_required
from app.supabase_client import supabase
from datetime import datetime, timedelta
import uuid
from app.middleware import with_supabase_auth
from app.supabase_client import get_supabase_client
licenses_bp = Blueprint('licenses', __name__)


@licenses_bp.route('/doctors/<string:rad_id>/licenses/<string:cert_id>/delete', methods=["POST"])
@with_supabase_auth
def delete_certification(rad_id, cert_id):
    supabase = get_supabase_client()
    if session["user"]["role"] != "admin":
        return "Unauthorized", 403

    supabase.table("certifications").delete().eq("id", cert_id).execute()

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
    supabase.table("certifications").update(data).eq("id", license_id).execute()
    return jsonify({"status": "success"})

@licenses_bp.route('/licenses/search', methods=["GET"])
@with_supabase_auth
def search_licenses():
    supabase = get_supabase_client()
    page = request.args.get('page', 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page
    
    # Get filter parameters
    search_term = request.args.get('search', '')
    doctor_id = request.args.get('doctor', '')
    status = request.args.get('status', 'all')
    
    # Build query
    query = supabase.table("certifications").select("*, radiologists(name)")
    
    if search_term:
        query = query.ilike('state', f'%{search_term}%')
    if doctor_id:
        query = query.eq('radiologist_id', doctor_id)
    if status != 'all':
        query = query.eq('status', status)
    
    # Get total count for pagination
    count_res = query.execute()
    total_count = len(count_res.data)
    
    # Get paginated results with sorting
    query = query.order("expiration_date", desc=True) \
                .range(offset, offset + per_page - 1)
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
    # Fetch all radiologists for the doctor dropdown
    rads_res = supabase.table("radiologists").select("id, name").order("name").execute()
    radiologists = rads_res.data or []

    # Handle Add License form submission
    if request.method == "POST":
        doctor_id = request.form.get("doctor")
        print("Doctor ID:", doctor_id)
        state = request.form.get("state")
        print("State:", state)
        expiration_date = request.form.get("exp")
        print("Expiration Date:", expiration_date)
        specialty = request.form.get("specialty")

        # If blank, pull specialty from an existing cert for that doctor
        if not specialty:
            existing = supabase.table("certifications") \
                .select("specialty") \
                .eq("radiologist_id", doctor_id) \
                .neq("specialty", None) \
                .limit(1) \
                .execute()
            if existing.data:
                specialty = existing.data[0]["specialty"]

        print("Specialty:", specialty)
        tags = request.form.get("tags")
        print("Tags:", tags)
        status = request.form.get("status")
        print("Status:", status)
        if doctor_id and state and expiration_date:
            res = supabase.table("certifications").insert({
                "id": str(uuid.uuid4()),
                "radiologist_id": doctor_id,
                "state": state,
                "expiration_date": expiration_date,
                "specialty": specialty,
                "tags": tags,
                "status": status
            }).execute()
            print("Insert response:", res)
        return redirect(url_for("licenses.licenses_page"))
       
    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page

    # Get total count for pagination
    count_res = supabase.table("certifications").select("*", count='exact').execute()
    total_count = count_res.count

    # Fetch paginated licenses with radiologist names
    certs_res = supabase.table("certifications") \
        .select("*, radiologists(name)") \
        .order("expiration_date", desc=True) \
        .range(offset, offset + per_page - 1) \
        .execute()
    certifications = certs_res.data or []

    # Get current date for expiration checking
    now = datetime.now()
    
    return render_template("licenses.html", 
                         certifications=certifications, 
                         radiologists=radiologists,
                         now=now,
                         total_count=total_count,
                         current_page=page,
                         per_page=per_page)