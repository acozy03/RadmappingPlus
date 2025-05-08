from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from app.admin_required import admin_required
from app.supabase_client import supabase
from datetime import datetime, timedelta
import uuid

licenses_bp = Blueprint('licenses', __name__)

def login_required(view_func):
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("auth.login"))
        return view_func(*args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper

@licenses_bp.route('/doctors/<string:rad_id>/licenses/<string:cert_id>/delete', methods=["POST"])
@login_required
def delete_certification(rad_id, cert_id):
    if session["user"]["role"] != "admin":
        return "Unauthorized", 403

    supabase.table("certifications").delete().eq("id", cert_id).execute()

    return redirect(url_for('doctors.doctor_profile', rad_id=rad_id))

@licenses_bp.route('/licenses/<string:license_id>/update', methods=["POST"])
@login_required
@admin_required
def update_license(license_id):
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
@login_required
def search_licenses():
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
@login_required
def licenses_page():
    # Fetch all radiologists for the doctor dropdown
    rads_res = supabase.table("radiologists").select("id, name").order("name").execute()
    radiologists = rads_res.data or []

    # Handle Add License form submission
    if request.method == "POST":
        doctor_id = request.form.get("doctor")
        state = request.form.get("state")
        expiration_date = request.form.get("exp")
        specialty = request.form.get("specialty")
        tags = request.form.get("tags")
        status = request.form.get("status")
        if doctor_id and state and expiration_date:
            supabase.table("certifications").insert({
                "id": str(uuid.uuid4()),
                "radiologist_id": doctor_id,
                "state": state,
                "expiration_date": expiration_date,
                "specialty": specialty,
                "tags": tags,
                "status": status
            }).execute()
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