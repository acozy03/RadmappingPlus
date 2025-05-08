from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from app.admin_required import admin_required
from app.supabase_client import supabase
from datetime import datetime, timedelta
from calendar import monthrange
import uuid

doctors_bp = Blueprint('doctors', __name__)

def login_required(view_func):
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("auth.login"))
        return view_func(*args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper

@doctors_bp.route('/doctors')
@login_required
def doctor_list():
    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page

    # Get all doctors for the modal
    all_doctors_res = supabase.table("radiologists").select("*").order("name").execute()
    all_doctors = all_doctors_res.data

    # Get pinned doctors for the current user using their email
    user_email = session["user"]["email"]
    pinned_res = supabase.table("pinned_doctors") \
        .select("doctor_id") \
        .eq("user_id", user_email) \
        .execute()
    pinned_doctor_ids = [p["doctor_id"] for p in pinned_res.data]

    # Sort doctors so pinned appear first
    sorted_doctors = sorted(all_doctors, key=lambda doc: str(doc['id']) not in pinned_doctor_ids)
    total_count = len(sorted_doctors)
    start = (page - 1) * per_page
    end = start + per_page
    visible_doctors = sorted_doctors[start:end]

    return render_template("doctor_list.html",
                         doctors=visible_doctors,
                         total_count=total_count,
                         current_page=page,
                         per_page=per_page,
                         pinned_doctors=pinned_doctor_ids,
                         all_doctors=all_doctors)

@doctors_bp.route('/doctors/search', methods=["GET"])
@login_required
def search_doctors():
    page = request.args.get('page', 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page
    search_term = request.args.get('search', '')
    status = request.args.get('status', 'all')

    # Get pinned doctors for the current user using their email
    user_email = session["user"]["email"]
    pinned_res = supabase.table("pinned_doctors") \
        .select("doctor_id") \
        .eq("user_id", user_email) \
        .execute()
    pinned_doctor_ids = [p["doctor_id"] for p in pinned_res.data]

    # Build base query for all filters
    base_query = supabase.table("radiologists").select("*")
    if search_term:
        base_query = base_query.or_(f"name.ilike.%{search_term}%")
    if status == 'active':
        base_query = base_query.eq('active_status', True)
    elif status == 'inactive':
        base_query = base_query.eq('active_status', False)

    # Get all matching doctors (for total count)
    all_matching = base_query.execute().data

    # Separate pinned and unpinned
    pinned_doctors = [doc for doc in all_matching if str(doc["id"]) in pinned_doctor_ids]
    unpinned_doctors = [doc for doc in all_matching if str(doc["id"]) not in pinned_doctor_ids]

    # Sort both lists alphabetically by name
    pinned_doctors = sorted(pinned_doctors, key=lambda d: d["name"])
    unpinned_doctors = sorted(unpinned_doctors, key=lambda d: d["name"])

    # Pagination logic
    if page == 1:
        # First page: pinned + fill with unpinned
        remaining_slots = per_page - len(pinned_doctors)
        visible_doctors = pinned_doctors + unpinned_doctors[:max(0, remaining_slots)]
    else:
        # Subsequent pages: only unpinned, skipping those already shown
        start = (page - 1) * per_page - len(pinned_doctors)
        end = start + per_page
        visible_doctors = unpinned_doctors[start:end]

    total_count = len(all_matching)

    return jsonify({
        'doctors': visible_doctors,
        'total_count': total_count,
        'current_page': page,
        'per_page': per_page
    })

@doctors_bp.route('/doctors/<string:rad_id>')
@login_required
def doctor_profile(rad_id):
    now = datetime.now()
    today_str = datetime.now().strftime("%Y-%m-%d")
    # Grab query params or fallback to current
    year = request.args.get("year", default=now.year, type=int)
    month = request.args.get("month", default=now.month, type=int)
    print(now)
    # Get month calendar navigation
    prev_month = month - 1 if month > 1 else 12
    prev_year = year - 1 if month == 1 else year
    next_month = month + 1 if month < 12 else 1
    next_year = year + 1 if month == 12 else year

    # For calendar rendering
    now = datetime(year, month, 1)
    days_in_month = monthrange(year, month)[1]

    # Get doctor and schedule
    doctor = supabase.table("radiologists").select("*").eq("id", rad_id).single().execute().data
    schedule_res = supabase.table("monthly_schedule") \
        .select("*") \
        .eq("radiologist_id", rad_id) \
        .lte("start_date", f"{year}-{month:02d}-{days_in_month}") \
        .gte("end_date", f"{year}-{month:02d}-01") \
        .execute()

    # Build calendar for the month, mapping each day to the schedule entry if it covers that day
    calendar = {}
    for entry in schedule_res.data:
        start = datetime.strptime(entry["start_date"], "%Y-%m-%d")
        end = datetime.strptime(entry["end_date"], "%Y-%m-%d")
        for n in range((end - start).days + 1):
            date = (start + timedelta(days=n)).strftime("%Y-%m-%d")
            calendar[date] = entry

    certs_res = supabase.table("certifications") \
    .select("*") \
    .eq("radiologist_id", rad_id) \
    .order("expiration_date", desc=True) \
    .execute()

    from pprint import pprint
    #pprint(certs_res.model_dump())
    certifications = certs_res.data
    #print(certifications)

    # Extract the most recent non-empty specialty from certifications
    doctor_specialty = None
    for cert in reversed(certifications):
        if cert.get('specialty'):
            doctor_specialty = cert['specialty']
            break

    # Fetch specialties from specialty_permissions
    specialty_perms = supabase.table("specialty_permissions") \
        .select("*, specialty_studies(name, description)") \
        .eq("radiologist_id", rad_id) \
        .eq("can_read", True) \
        .execute().data
    doctor_specialties = [perm["specialty_studies"] for perm in specialty_perms if perm.get("specialty_studies")]

    facility_res = supabase.table("doctor_facility_assignments") \
    .select("*, facilities(*)") \
    .eq("radiologist_id", rad_id).execute()

    assigned_facilities = facility_res.data

    # Get all facilities for the add facility dropdown
    all_facilities_res = supabase.table("facilities").select("*").order("name").execute()
    all_facilities = all_facilities_res.data

    # Filter out already assigned facilities
    assigned_facility_ids = {assignment["facilities"]["id"] for assignment in assigned_facilities}
    available_facilities = [fac for fac in all_facilities if fac["id"] not in assigned_facility_ids]

    return render_template("doctor_profile.html",
        doctor=doctor,
        now=now,
        year=year,
        month=month,
        days_in_month=days_in_month,
        schedule=schedule_res.data,
        calendar=calendar,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
        today_str=today_str,
        certifications=certifications,
        assigned_facilities=assigned_facilities,
        available_facilities=available_facilities,
        doctor_specialty=doctor_specialty,
        doctor_specialties=doctor_specialties
    )

@doctors_bp.route('/doctors/<string:rad_id>/update_schedule', methods=["POST"])
@login_required
def update_schedule(rad_id):
    if session["user"]["role"] != "admin":
        return "Unauthorized", 403

    date = request.form.get("date")
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")
    details = request.form.get("schedule_details")

    data = {
        "start_time": start_time or None,
        "end_time": end_time or None,
        "schedule_details": details or None
    }

    # Check if a schedule entry already exists for this doctor on this date
    existing = supabase.table("monthly_schedule") \
        .select("id") \
        .eq("radiologist_id", rad_id) \
        .eq("start_date", date) \
        .eq("end_date", date).execute()

    if existing.data:
        # Update existing entry
        supabase.table("monthly_schedule").update(data) \
            .eq("id", existing.data[0]["id"]).execute()
    else:
        # Insert new entry
        data["radiologist_id"] = rad_id
        data["start_date"] = date
        data["end_date"] = date
        supabase.table("monthly_schedule").insert(data).execute()

    year = request.form.get("year")
    month = request.form.get("month")
    start_day = request.form.get("start_day")
    return redirect(url_for("monthly.monthly", year=year, month=month, start_day=start_day))

@doctors_bp.route('/doctors/<string:rad_id>/delete_schedule', methods=["POST"])
@login_required
def delete_schedule(rad_id):
    if session["user"]["role"] != "admin":
        return "Unauthorized", 403

    date = request.form.get("date")
    year = request.form.get("year")
    month = request.form.get("month")
    start_day = request.form.get("start_day")
    supabase.table("monthly_schedule").delete() \
        .eq("radiologist_id", rad_id).eq("start_date", date).eq("end_date", date).execute()

    return redirect(url_for("monthly.monthly", year=year, month=month, start_day=start_day))

@doctors_bp.route('/doctors/<string:rad_id>/bulk_update_schedule', methods=["POST"])
@login_required
def bulk_update_schedule(rad_id):
    if session["user"]["role"] != "admin":
        return "Unauthorized", 403

    dates = request.form.get("dates", "").split(",")
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")
    notes = request.form.get("schedule_details")

    if not dates or not start_time or not end_time:
        return "Missing data", 400

    for date in dates:
        if not date:
            continue
        existing = supabase.table("monthly_schedule") \
            .select("id") \
            .eq("radiologist_id", rad_id) \
            .eq("start_date", date) \
            .eq("end_date", date).execute()

        payload = {
            "radiologist_id": rad_id,
            "start_date": date,
            "end_date": date,
            "start_time": start_time,
            "end_time": end_time,
            "schedule_details": notes
        }

        if existing.data:
            supabase.table("monthly_schedule").update(payload) \
                .eq("id", existing.data[0]["id"]).execute()
        else:
            supabase.table("monthly_schedule").insert(payload).execute()

    return redirect(url_for("doctors.doctor_profile", rad_id=rad_id))

@doctors_bp.route('/doctors/<string:rad_id>/update', methods=["POST"])
@login_required
def update_doctor(rad_id):
    if session["user"]["role"] != "admin":
        return "Unauthorized", 403

    data = {
        "email": request.form.get("email"),
        "phone": request.form.get("phone"),
        "pacs": request.form.get("pacs"),
        "modalities": request.form.get("modalities"),
        "primary_contact_method": request.form.get("primary_contact_method"),
        "timezone": request.form.get("timezone"),
        "active_status": True if request.form.get("active_status") == "true" else False
    }

    supabase.table("radiologists").update(data).eq("id", rad_id).execute()

    return redirect(url_for("doctors.doctor_profile", rad_id=rad_id))

@doctors_bp.route('/doctors/add', methods=['POST'])
@login_required
@admin_required
def add_doctor():
    # Generate a new UUID for the doctor
    new_id = str(uuid.uuid4())
    
    data = {
        "id": new_id,
        "name": request.form.get("name"),
        "email": request.form.get("email"),
        "phone": request.form.get("phone"),
        "pacs": request.form.get("pacs"),
        "primary_contact_method": request.form.get("primary_contact_method"),
        "modalities": request.form.get("modalities"),
        "timezone": request.form.get("timezone"),
        "additional_info": request.form.get("additional_info"),
        "active_status": True if request.form.get("active_status") == "true" else False
    }

    # Insert the new doctor into the database
    supabase.table("radiologists").insert(data).execute()

    return redirect(url_for("doctors.doctor_profile", rad_id=new_id))

@doctors_bp.route('/doctors/<rad_id>/remove', methods=['POST'])
@admin_required
def remove_doctor(rad_id):
    supabase.table('radiologists').delete().eq('id', rad_id).execute()
    return redirect(url_for('doctors.doctor_list'))

@doctors_bp.route('/doctors/<string:rad_id>/add_facility', methods=['POST'])
@login_required
@admin_required
def add_facility_assignment(rad_id):
    data = {
        "id": str(uuid.uuid4()),
        "radiologist_id": rad_id,
        "facility_id": request.form.get("facility_id"),
        "can_read": "can_read" in request.form,
        "does_stats": "does_stats" in request.form,
        "does_routines": "does_routines" in request.form,
        "stipulations": request.form.get("stipulations", ""),
        "notes": request.form.get("notes", "")
    }
    
    supabase.table("doctor_facility_assignments").insert(data).execute()
    return redirect(url_for("doctors.doctor_profile", rad_id=rad_id))

@doctors_bp.route('/doctors/<string:doctor_id>/specialties')
@login_required
@admin_required
def get_doctor_specialties(doctor_id):
    # Get all specialties
    specialties_res = supabase.table("specialty_studies").select("*").order("name").execute()
    specialties = specialties_res.data
    # Get all permissions for this doctor
    perms_res = supabase.table("specialty_permissions") \
        .select("specialty_id, can_read") \
        .eq("radiologist_id", doctor_id) \
        .execute()
    perms = {p['specialty_id']: p['can_read'] for p in perms_res.data}
    # Build response
    result = []
    for spec in specialties:
        result.append({
            'id': spec['id'],
            'name': spec['name'],
            'description': spec.get('description', ''),
            'assigned': perms.get(spec['id'], False)
        })
    return jsonify({'specialties': result})

@doctors_bp.route('/doctors/<string:doctor_id>/specialties/update', methods=['POST'])
@login_required
@admin_required
def update_doctor_specialties(doctor_id):
    data = request.get_json()
    specialty_ids = set(data.get('specialty_ids', []))
    # Get all specialties
    specialties_res = supabase.table("specialty_studies").select("id").execute()
    all_specialty_ids = {s['id'] for s in specialties_res.data}
    # Get current permissions
    perms_res = supabase.table("specialty_permissions") \
        .select("id, specialty_id") \
        .eq("radiologist_id", doctor_id) \
        .execute()
    perms = {p['specialty_id']: p['id'] for p in perms_res.data}
    # Update or create permissions
    for spec_id in all_specialty_ids:
        should_have = spec_id in specialty_ids
        if spec_id in perms:
            supabase.table("specialty_permissions").update({"can_read": should_have}).eq("id", perms[spec_id]).execute()
        elif should_have:
            supabase.table("specialty_permissions").insert({
                "id": str(uuid.uuid4()),
                "radiologist_id": doctor_id,
                "specialty_id": spec_id,
                "can_read": True
            }).execute()
    return jsonify({"status": "success"})

@doctors_bp.route('/doctors/<string:rad_id>/licenses/<string:cert_id>/delete', methods=["POST"])
@login_required
def delete_certification(rad_id, cert_id):
    if session["user"]["role"] != "admin":
        return "Unauthorized", 403

    supabase.table("certifications").delete().eq("id", cert_id).execute()

    return redirect(url_for('doctors.doctor_profile', rad_id=rad_id))

@doctors_bp.route('/doctors/<string:rad_id>/add_certification', methods=['POST'])
@login_required
def add_certification(rad_id):
    if session["user"]["role"] != "admin":
        return "Unauthorized", 403

    data = {
        "id": str(uuid.uuid4()),
        "radiologist_id": rad_id,
        "state": request.form['state'],
        "expiration_date": request.form['expiration_date'],
        "status": request.form['status'],
        "specialty": request.form.get('specialty', ''),
        "tags": request.form.get('tags', ''),
    }
    supabase.table("certifications").insert(data).execute()

    return redirect(url_for('doctors.doctor_profile', rad_id=rad_id))

@doctors_bp.route('/doctors/assignments/<string:assignment_id>/update', methods=['POST'])
@login_required
def update_assignment(assignment_id):
    if session["user"]["role"] != "admin":
        return "Unauthorized", 403

    # Always map explicitly:
    can_read = 'can_read' in request.form  # True if checkbox was checked, False if missing
    does_stats = 'does_stats' in request.form
    does_routines = 'does_routines' in request.form
    stipulations = request.form.get('stipulations', '')
    notes = request.form.get('notes', '')

    supabase.table("doctor_facility_assignments").update({
        "can_read": can_read,
        "does_stats": does_stats,
        "does_routines": does_routines,
        "stipulations": stipulations,
        "notes": notes,
    }).eq("id", assignment_id).execute()

    return redirect(request.referrer or url_for('doctors.doctor_profile'))

@doctors_bp.route('/doctors/assignments/<string:assignment_id>/delete', methods=['POST'])
@login_required
def delete_assignment(assignment_id):
    if session["user"]["role"] != "admin":
        return "Unauthorized", 403

    supabase.table("doctor_facility_assignments").delete().eq("id", assignment_id).execute()
    return redirect(request.referrer or url_for('doctors.doctor_profile')) 