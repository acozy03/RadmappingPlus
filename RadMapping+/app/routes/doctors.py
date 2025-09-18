from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from app.admin_required import admin_required
from app.supabase_client import get_supabase_client
from app.middleware import with_supabase_auth
from app.audit_log import log_audit_action 
from datetime import datetime, timedelta
from calendar import monthrange
import uuid
from threading import Thread
from postgrest import APIError
doctors_bp = Blueprint('doctors', __name__)

@doctors_bp.route('/doctors')
@with_supabase_auth
def doctor_list():
    supabase = get_supabase_client()
    page = request.args.get('page', 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page

    all_doctors_res = supabase.table("radiologists").select("*").order("name").execute()
    all_doctors = all_doctors_res.data

    user_email = session["user"]["email"]
    pinned_res = supabase.table("pinned_doctors") \
        .select("doctor_id") \
        .eq("user_id", user_email) \
        .execute()
    pinned_doctor_ids = [p["doctor_id"] for p in pinned_res.data]

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
@with_supabase_auth
def search_doctors():
    supabase = get_supabase_client()
    page = request.args.get('page', 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page
    search_term = request.args.get('search', '')
    status = request.args.get('status', 'all')

    user_email = session["user"]["email"]
    pinned_res = supabase.table("pinned_doctors") \
        .select("doctor_id") \
        .eq("user_id", user_email) \
        .execute()
    pinned_doctor_ids = [p["doctor_id"] for p in pinned_res.data]

    base_query = supabase.table("radiologists").select("*")
    if search_term:
        base_query = base_query.or_(f"name.ilike.%{search_term}%")
    if status == 'active':
        base_query = base_query.eq('active_status', True)
    elif status == 'inactive':
        base_query = base_query.eq('active_status', False)

    all_matching = base_query.execute().data

    pinned_doctors = [doc for doc in all_matching if str(doc["id"]) in pinned_doctor_ids]
    unpinned_doctors = [doc for doc in all_matching if str(doc["id"]) not in pinned_doctor_ids]

    pinned_doctors = sorted(pinned_doctors, key=lambda d: d["name"])
    unpinned_doctors = sorted(unpinned_doctors, key=lambda d: d["name"])

    if page == 1:
      
        remaining_slots = per_page - len(pinned_doctors)
        visible_doctors = pinned_doctors + unpinned_doctors[:max(0, remaining_slots)]
    else:
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

@with_supabase_auth
def get_latest_monthly_rvu_column(row):
    month_order = ["dec", "nov", "oct", "sep", "aug", "jul", "jun", "may", "apr", "mar", "feb", "jan"]  # Reverse order for latest first
    for month in month_order:
        if row.get(month) is not None:
            if row.get(month) != 0:
                return month, row[month]
    return None, None


@doctors_bp.route('/doctors/<string:rad_id>')
@with_supabase_auth
def doctor_profile(rad_id):
    supabase = get_supabase_client()
    now = datetime.now()
    today_str = datetime.now().strftime("%Y-%m-%d")
    year = request.args.get("year", default=now.year, type=int)
    month = request.args.get("month", default=now.month, type=int)
    
    prev_month = month - 1 if month > 1 else 12
    prev_year = year - 1 if month == 1 else year
    next_month = month + 1 if month < 12 else 1
    next_year = year + 1 if month == 12 else year

    now = datetime(year, month, 1)
    days_in_month = monthrange(year, month)[1]

    try:
        doctor_res = supabase.table("radiologists").select("*").eq("id", rad_id).single().execute()
        doctor = doctor_res.data
        print(f"Loaded doctor with id {rad_id}: {doctor}")
    except APIError as e:
        print(f"Failed to load doctor with id {rad_id}:", e)
        return render_template("errors/404.html", message="Doctor not found"), 404

    schedule_res = supabase.table("monthly_schedule") \
        .select("*") \
        .eq("radiologist_id", rad_id) \
        .lte("start_date", f"{year}-{month:02d}-{days_in_month}") \
        .gte("end_date", f"{year}-{month:02d}-01") \
        .execute()

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
        .order("state", desc=False) \
        .execute()

    certifications = certs_res.data

    doctor_specialty = None
    for cert in reversed(certifications):
        if cert.get('specialty'):
            doctor_specialty = cert['specialty']
            break

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

    all_facilities_res = supabase.table("facilities").select("*").order("name").execute()
    all_facilities = all_facilities_res.data

    assigned_facility_ids = {assignment["facilities"]["id"] for assignment in assigned_facilities}
    available_facilities = [fac for fac in all_facilities if fac["id"] not in assigned_facility_ids]

    rvu_rows = supabase.table("rad_avg_monthly_rvu") \
        .select("*") \
        .eq("radiologist_id", rad_id) \
        .limit(1) \
        .execute() \
        .data

    rvu_row = rvu_rows[0] if rvu_rows else None

    if rvu_row:
        latest_rvu_col, rvu = get_latest_monthly_rvu_column(rvu_row)
    else:
        latest_rvu_col, rvu = None, None  



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
        doctor_specialties=doctor_specialties,
        rvu=rvu,
        latest_rvu_col=latest_rvu_col
    )

@doctors_bp.route('/doctors/<string:rad_id>/update_schedule', methods=["POST"])
@with_supabase_auth
@admin_required
def update_schedule(rad_id):
    supabase = get_supabase_client()
    date = request.form.get("date")
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")
    details = request.form.get("schedule_details")

    data = {
        "start_time": start_time or None,
        "end_time": end_time or None,
        "schedule_details": details or None
    }

    existing = supabase.table("monthly_schedule") \
        .select("id, start_time, end_time, schedule_details") \
        .eq("radiologist_id", rad_id) \
        .eq("start_date", date) \
        .eq("end_date", date).execute()

    if existing.data:
        old_data = existing.data[0]
      
        res = supabase.table("monthly_schedule").update(data) \
            .eq("id", old_data["id"]).execute()
        if not hasattr(res, "error"):
            log_audit_action(
                supabase=supabase,
                action="update",
                table_name="monthly_schedule",
                record_id=old_data["id"],
                user_email=session.get("user", {}).get("email", "unknown"),
                old_data=old_data,
                new_data={**data, "id": old_data["id"], "radiologist_id": rad_id, "start_date": date, "end_date": date}
            )
    else:
       
        new_id = str(uuid.uuid4())
        data["id"] = new_id
        data["radiologist_id"] = rad_id
        data["start_date"] = date
        data["end_date"] = date
        res = supabase.table("monthly_schedule").insert(data).execute()
        if not hasattr(res, "error"):
            log_audit_action(
                supabase=supabase,
                action="insert",
                table_name="monthly_schedule",
                record_id=new_id,
                user_email=session.get("user", {}).get("email", "unknown"),
                old_data=None,
                new_data=data
            )

    year = request.form.get("year")
    month = request.form.get("month")
    start_day = request.form.get("start_day")
    return redirect(url_for("monthly.monthly", year=year, month=month, start_day=start_day))

@doctors_bp.route('/doctors/<string:rad_id>/delete_schedule', methods=["POST"])
@with_supabase_auth
@admin_required
def delete_schedule(rad_id):
    supabase = get_supabase_client()
    date = request.form.get("date")
    year = request.form.get("year")
    month = request.form.get("month")
    start_day = request.form.get("start_day")

    old_data_res = supabase.table("monthly_schedule") \
        .select("*") \
        .eq("radiologist_id", rad_id) \
        .eq("start_date", date) \
        .eq("end_date", date) \
        .single().execute()
    old_data = old_data_res.data if old_data_res.data else None

    res = supabase.table("monthly_schedule").delete() \
        .eq("radiologist_id", rad_id).eq("start_date", date).eq("end_date", date).execute()

    if not hasattr(res, "error") and old_data:
        log_audit_action(
            supabase=supabase,
            action="delete",
            table_name="monthly_schedule",
            record_id=old_data["id"],
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=old_data,
            new_data=None
        )

    return redirect(url_for("monthly.monthly", year=year, month=month, start_day=start_day))

@doctors_bp.route('/doctors/<string:rad_id>/bulk_update_schedule', methods=["POST"])
@with_supabase_auth
@admin_required
def bulk_update_schedule(rad_id):
    supabase = get_supabase_client()
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
            .select("id, start_time, end_time, schedule_details") \
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
            old_data = existing.data[0]
            res = supabase.table("monthly_schedule").update(payload) \
                .eq("id", old_data["id"]).execute()
            if not hasattr(res, "error"):
                log_audit_action(
                    supabase=supabase,
                    action="update",
                    table_name="monthly_schedule",
                    record_id=old_data["id"],
                    user_email=session.get("user", {}).get("email", "unknown"),
                    old_data=old_data,
                    new_data={**payload, "id": old_data["id"]}
                )
        else:
            new_id = str(uuid.uuid4())
            payload["id"] = new_id
            res = supabase.table("monthly_schedule").insert(payload).execute()
            if not hasattr(res, "error"):
                log_audit_action(
                    supabase=supabase,
                    action="insert",
                    table_name="monthly_schedule",
                    record_id=new_id,
                    user_email=session.get("user", {}).get("email", "unknown"),
                    old_data=None,
                    new_data=payload
                )

    return redirect(url_for("doctors.doctor_profile", rad_id=rad_id))

@doctors_bp.route('/doctors/<string:rad_id>/update', methods=["POST"])
@with_supabase_auth
@admin_required
def update_doctor(rad_id):
    try:
        supabase = get_supabase_client()
        old_data = supabase.table("radiologists").select("*").eq("id", rad_id).single().execute().data
        
        data = {
            "name": request.form.get("name"),
            "email": request.form.get("email"),
            "phone": request.form.get("phone"),
            "pacs": request.form.get("pacs"),
            "modalities": request.form.get("modalities"),
            "primary_contact_method": request.form.get("primary_contact_method"),
            "timezone": request.form.get("timezone"),
            "active_status": True if request.form.get("active_status") == "true" else False,
            "stipulations": request.form.get("stipulations"),
            "reads_routines": request.form.get("reads_routines"),
            "reads_stats": request.form.get("reads_stats"), 
        }
        
        data = {k: v for k, v in data.items() if v is not None}
        
        rvu_val = request.form.get("rvu_score", "").strip()
        rvu_month = request.form.get("rvu_month", "").strip().lower()

        if rvu_month in ("", "none", None):
            rvu_month = datetime.now().strftime("%b").lower()

        old_rvu_data_res = supabase.table("rad_avg_monthly_rvu").select("*").eq("radiologist_id", rad_id).limit(1).execute()
        old_rvu_data = old_rvu_data_res.data[0] if old_rvu_data_res.data else None
        
        current_rvu = float(rvu_val) if rvu_val else None
        old_rvu_val = old_rvu_data.get(rvu_month) if old_rvu_data else None

        if current_rvu is not None and current_rvu != old_rvu_val:
            rad_info = supabase.table("radiologists").select("name").eq("id", rad_id).single().execute()
            rad_name = rad_info.data["name"] if rad_info.data else None

            if not old_rvu_data:
                supabase.table("rad_avg_monthly_rvu").insert({
                    "radiologist_id": rad_id,
                    "name": rad_name
                }).execute()
                old_rvu_data = None  
          
            rvu_payload = {
                "radiologist_id": rad_id,
                "name": rad_name,
                rvu_month: float(rvu_val)
            }
           
            rvu_res = supabase.table("rad_avg_monthly_rvu").upsert(rvu_payload, on_conflict="radiologist_id").execute()

            if not hasattr(rvu_res, "error"):
                log_audit_action(
                    supabase=supabase,
                    action="upsert",
                    table_name="rad_avg_monthly_rvu",
                    record_id=rad_id,
                    user_email=session.get("user", {}).get("email", "unknown"),
                    old_data=old_rvu_data,
                    new_data=rvu_payload
                )

        # New logic to check for changes before logging the main doctor update
        profile_changed = False
        if old_data:
            for key, value in data.items():
                if old_data.get(key) != value:
                    profile_changed = True
                    break

        if profile_changed:
            result = supabase.table("radiologists").update(data).eq("id", rad_id).execute()
            if not hasattr(result, "error"):
                log_audit_action(
                    supabase=supabase,
                    action="update",
                    table_name="radiologists",
                    record_id=rad_id,
                    user_email=session.get("user", {}).get("email", "unknown"),
                    old_data=old_data,
                    new_data=data
                )

        return redirect(url_for("doctors.doctor_profile", rad_id=rad_id))
    except Exception as e:
        return f"Error updating doctor: {str(e)}", 500

@doctors_bp.route('/doctors/add', methods=['POST'])
@with_supabase_auth
@admin_required
def add_doctor():
    supabase = get_supabase_client()
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
        "active_status": True if request.form.get("active_status") == "true" else False,
        "stipulations": request.form.get("stipulations"),
        "reads_routines": request.form.get("reads_routines"),
        "reads_stats": request.form.get("reads_stats"),
    }

    res = supabase.table("radiologists").insert(data).execute()

    if not hasattr(res, "error"):
        log_audit_action(
            supabase=supabase,
            action="insert",
            table_name="radiologists",
            record_id=new_id,
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=None,
            new_data=data
        )

    return redirect(url_for("doctors.doctor_profile", rad_id=new_id))

@doctors_bp.route('/doctors/<rad_id>/remove', methods=['POST'])
@with_supabase_auth
@admin_required
def remove_doctor(rad_id):
    supabase = get_supabase_client()
    old_data = supabase.table('radiologists').select('*').eq('id', rad_id).single().execute().data
    res = supabase.table('radiologists').delete().eq('id', rad_id).execute()
    supabase.table('rad_avg_monthly_rvu').delete().eq('radiologist_id', rad_id).execute()
    if not hasattr(res, "error"):
        log_audit_action(
            supabase=supabase,
            action="delete",
            table_name="radiologists",
            record_id=rad_id,
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=old_data,
            new_data=None
        )
    return redirect(url_for('doctors.doctor_list'))

@doctors_bp.route('/doctors/<string:rad_id>/add_facility', methods=['POST'])
@with_supabase_auth
@admin_required
def add_facility_assignment(rad_id):
    supabase = get_supabase_client()

    can_read = request.form.get("can_read", "false")  
    if can_read not in ["true", "pending", "false"]:
        return "Invalid can_read value", 400

    notes = request.form.get("notes", "")
    notes = None if notes == "None" else notes

    data = {
        "id": str(uuid.uuid4()),
        "radiologist_id": rad_id,
        "facility_id": request.form.get("facility_id"),
        "can_read": can_read,
        "notes": notes
    }

    res = supabase.table("doctor_facility_assignments").insert(data).execute()

    if not hasattr(res, "error"):
        log_audit_action(
            supabase=supabase,
            action="insert",
            table_name="doctor_facility_assignments",
            record_id=data["id"],
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=None,
            new_data=data
        )

    return redirect(url_for("doctors.doctor_profile", rad_id=rad_id))


@doctors_bp.route('/doctors/<string:doctor_id>/specialties')
@with_supabase_auth
@admin_required
def get_doctor_specialties(doctor_id):
    supabase = get_supabase_client()
    specialties_res = supabase.table("specialty_studies").select("*").order("name").execute()
    specialties = specialties_res.data
    perms_res = supabase.table("specialty_permissions") \
        .select("specialty_id, can_read") \
        .eq("radiologist_id", doctor_id) \
        .execute()
    perms = {p['specialty_id']: p['can_read'] for p in perms_res.data}
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
@with_supabase_auth
@admin_required
def update_doctor_specialties(doctor_id):
    supabase = get_supabase_client()
    data = request.get_json()
    specialty_ids = set(data.get('specialty_ids', []))
    specialties_res = supabase.table("specialty_studies").select("id").execute()
    all_specialty_ids = {s['id'] for s in specialties_res.data}
    perms_res = supabase.table("specialty_permissions") \
        .select("id, specialty_id, can_read") \
        .eq("radiologist_id", doctor_id) \
        .execute()
    perms_map = {p['specialty_id']: p for p in perms_res.data}

    for spec_id in all_specialty_ids:
        should_have = spec_id in specialty_ids
        if spec_id in perms_map:
            old_perm = perms_map[spec_id]
            if old_perm["can_read"] != should_have: 
                new_perm_data = {"can_read": should_have}
                res = supabase.table("specialty_permissions").update(new_perm_data).eq("id", old_perm["id"]).execute()
                if not hasattr(res, "error"):
                    log_audit_action(
                        supabase=supabase,
                        action="update",
                        table_name="specialty_permissions",
                        record_id=old_perm["id"],
                        user_email=session.get("user", {}).get("email", "unknown"),
                        old_data=old_perm,
                        new_data={**old_perm, **new_perm_data} 
                    )
        elif should_have:
            new_id = str(uuid.uuid4())
            new_perm_data = {
                "id": new_id,
                "radiologist_id": doctor_id,
                "specialty_id": spec_id,
                "can_read": True
            }
            res = supabase.table("specialty_permissions").insert(new_perm_data).execute()
            if not hasattr(res, "error"):
                log_audit_action(
                    supabase=supabase,
                    action="insert",
                    table_name="specialty_permissions",
                    record_id=new_id,
                    user_email=session.get("user", {}).get("email", "unknown"),
                    old_data=None,
                    new_data=new_perm_data
                )
    return jsonify({"status": "success"})


@doctors_bp.route('/doctors/<string:rad_id>/add_certification', methods=['POST'])
@with_supabase_auth
@admin_required
def add_certification(rad_id):
    supabase = get_supabase_client()
    data = {
        "id": str(uuid.uuid4()),
        "radiologist_id": rad_id,
        "state": request.form['state'],
        "expiration_date": request.form['expiration_date'],
        "status": request.form['status'],
        "specialty": request.form.get('specialty', ''),
        "tags": request.form.get('tags', ''),
    }
    res = supabase.table("certifications").insert(data).execute()

    if not hasattr(res, "error"):
        log_audit_action(
            supabase=supabase,
            action="insert",
            table_name="certifications",
            record_id=data["id"],
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=None,
            new_data=data
        )

    return redirect(url_for('doctors.doctor_profile', rad_id=rad_id))

@doctors_bp.route('/doctors/assignments/<string:assignment_id>/update', methods=["POST"])
@with_supabase_auth
@admin_required
def update_assignment(assignment_id):
    try:
        supabase = get_supabase_client()

        current_res = supabase.table("doctor_facility_assignments") \
            .select("*") \
            .eq("id", assignment_id) \
            .single() \
            .execute()

        if not current_res.data:
            return "Assignment not found", 404
        
        old_data = current_res.data
        can_read = request.form.get("can_read", "false")  
        if can_read not in ["true", "pending", "false"]:
            return "Invalid can_read value", 400

        notes = request.form.get("notes", "")
        notes = None if notes == "None" else notes

        update_data = {
            "can_read": can_read,
            "notes": notes,
            "radiologist_id": old_data["radiologist_id"] 
        }

        res = supabase.table("doctor_facility_assignments") \
            .update(update_data) \
            .eq("id", assignment_id) \
            .execute()

        if not hasattr(res, "error"):
            log_audit_action(
                supabase=supabase,
                action="update",
                table_name="doctor_facility_assignments",
                record_id=assignment_id,
                user_email=session.get("user", {}).get("email", "unknown"),
                old_data=old_data,
                new_data={**old_data, **update_data}
            )

        return redirect(request.referrer or url_for('doctors.doctor_profile', rad_id=old_data["radiologist_id"]))
    except Exception as e:
        return f"Error updating assignment: {str(e)}", 500


@doctors_bp.route('/doctors/assignments/<string:assignment_id>/delete', methods=["POST"])
@with_supabase_auth
@admin_required
def delete_assignment(assignment_id):
    try:
        supabase = get_supabase_client()
        
        old_data_res = supabase.table("doctor_facility_assignments") \
            .select("*") \
            .eq("id", assignment_id) \
            .single() \
            .execute()
        old_data = old_data_res.data if old_data_res.data else None
        
        result = supabase.table("doctor_facility_assignments") \
            .delete() \
            .eq("id", assignment_id) \
            .execute()
            
        if not hasattr(result, "error") and old_data:
            log_audit_action(
                supabase=supabase,
                action="delete",
                table_name="doctor_facility_assignments",
                record_id=assignment_id,
                user_email=session.get("user", {}).get("email", "unknown"),
                old_data=old_data,
                new_data=None
            )
        
        return redirect(request.referrer or url_for('doctors.doctor_profile'))
    except Exception as e:
        return f"Error deleting assignment: {str(e)}", 500 
    
from flask import Blueprint, request, jsonify
from app.radmapping_sync import process_cell_update

@doctors_bp.route('/doctors/radmapping-sync', methods=["POST"])
def radmapping_sync():
    try:
        data = request.get_json(force=True)
        print("🛰️ Received radmapping-sync request:", data)

        sheet_id = data.get("sheetId")
        row = data.get("row")
        col = data.get("col")

        if not sheet_id or not row or not col:
            print("Missing fields:", data)
            return jsonify({"error": "Missing required fields"}), 400
        result, status_code = process_cell_update(sheet_id, int(row), int(col))
        print("Sync success:", result)
        return jsonify(result), status_code

    except Exception as e:
        import traceback
        print("Exception occurred during radmapping_sync:")
        print(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500

@doctors_bp.route('/api/doctors', methods=['GET'])
# @with_supabase_auth
def get_doctors_api():
    """
    A public API endpoint to get doctor data from the radiologists table.
    """
    try:
        supabase = get_supabase_client()
        search_term = request.args.get('search', '')

        if not search_term:
            return jsonify({'error': 'No search term provided.'}), 400

        results = supabase.table("radiologists").select("*").ilike('name', f'%{search_term}%').execute()

        if results.data:
            return jsonify(results.data), 200
        else:
            return jsonify({'message': 'No doctors found.'}), 404

    except Exception as e:
        return jsonify({'error': str(e)}), 500