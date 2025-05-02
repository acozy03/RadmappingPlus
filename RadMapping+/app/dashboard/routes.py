from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from app.decorators import admin_required
from app.supabase_client import supabase
from datetime import datetime, timedelta
from calendar import monthrange
from collections import defaultdict
import uuid  
import calendar as pycalendar
import pytz
import ollama
import json

dashboard_bp = Blueprint('dashboard', __name__)

def login_required(view_func):
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("auth.login"))
        return view_func(*args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper

@dashboard_bp.route('/home')
@login_required
def home():
    from collections import defaultdict
    from datetime import datetime, timedelta

    user = session.get("user")

    # Get selected timezone from query params or default to EST
    selected_timezone = request.args.get("timezone", "EST")
    
    # Calculate timezone offset
    timezone_offset = {
        'EST': 0,
        'CST': 1,
        'PST': 3,
        'UTC': 5
    }.get(selected_timezone, 0)

    # Allow optional date navigation
    date_str = request.args.get("date")
    if date_str:
        now = datetime.strptime(date_str, "%Y-%m-%d")
    else:
        now = datetime.now()

    today = now.strftime("%Y-%m-%d")
    current_time = datetime.now().strftime("%H:%M")

    # Date navigation
    prev_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    next_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # Fetch shifts
    shift_res = supabase.table("monthly_schedule") \
        .select("*, radiologists(*)") \
        .eq("date", today) \
        .execute()

    doctors_by_hour = defaultdict(list)
    doctors_on_shift = []

    for entry in shift_res.data:
        if entry.get("radiologists") and entry.get("start_time") and entry.get("end_time"):
            doc = entry["radiologists"]
            doc.update({
                "start_time": entry["start_time"],
                "end_time": entry["end_time"]
            })
            doctors_on_shift.append(doc)

            try:
                start_hour = int(entry["start_time"].split(":")[0])
                end_hour = int(entry["end_time"].split(":")[0])
                for hour in range(start_hour, end_hour):
                    doctors_by_hour[hour].append(doc)
            except Exception as e:
                print("Shift hour error:", e)

    # Get all doctors
    all_doctors_res = supabase.table("radiologists").select("*").execute()
    all_doctors = all_doctors_res.data

    # Create timezone dictionary for all doctors
    doctors_by_timezone = defaultdict(list)
    for doctor in all_doctors:
        timezone = doctor.get("timezone", "Unknown")
        if timezone:
            doctors_by_timezone[timezone].append(doctor)

    # Create sets for doctors on shift today and currently on shift
    doctors_on_shift_ids = {doc["id"] for doc in doctors_on_shift}
    doctors_currently_on_shift_ids = set()

    # Get current hour
    current_hour = datetime.now().hour

    # Check which doctors are currently on shift
    for doc in doctors_on_shift:
        try:
            start_hour = int(doc["start_time"].split(":")[0])
            end_hour = int(doc["end_time"].split(":")[0])
            
            # Check if current hour falls within shift hours
            if start_hour <= current_hour < end_hour:
                doctors_currently_on_shift_ids.add(doc["id"])
        except Exception as e:
            print("Error checking current shift:", e)

    return render_template("home.html",
        user=user,
        today=today,
        prev_date=prev_date,
        next_date=next_date,
        doctors_on_shift=doctors_on_shift,
        doctors_by_hour=doctors_by_hour,
        doctors_by_timezone=doctors_by_timezone,
        doctors_on_shift_ids=doctors_on_shift_ids,
        doctors_currently_on_shift_ids=doctors_currently_on_shift_ids,
        selected_timezone=selected_timezone,
        timezone_offset=timezone_offset
    )

@dashboard_bp.route('/admin')
@admin_required
def admin():
    return "Admin-only page"

@dashboard_bp.route('/doctors')
@login_required
def doctor_list():
    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page

    # Get total count for pagination
    count_res = supabase.table("radiologists").select("*", count='exact').execute()
    total_count = count_res.count

    # Fetch paginated doctors
    response = supabase.table("radiologists") \
        .select("*") \
        .order("name") \
        .range(offset, offset + per_page - 1) \
        .execute()
    doctors = response.data

    return render_template("doctor_list.html", 
                         doctors=doctors,
                         total_count=total_count,
                         current_page=page,
                         per_page=per_page)

@dashboard_bp.route('/doctors/search', methods=["GET"])
@login_required
def search_doctors():
    page = request.args.get('page', 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page
    
    # Get search term
    search_term = request.args.get('search', '')
    
    # Build query
    query = supabase.table("radiologists").select("*")
    
    if search_term:
        query = query.or_(f"name.ilike.%{search_term}%")
    
    # Get total count for pagination
    count_res = query.execute()
    total_count = len(count_res.data)
    
    # Get paginated results
    query = query.order("name") \
                .range(offset, offset + per_page - 1)
    results = query.execute()
    
    return jsonify({
        'doctors': results.data,
        'total_count': total_count,
        'current_page': page,
        'per_page': per_page
    })

@dashboard_bp.route('/doctors/<string:rad_id>')
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
        .gte("date", f"{year}-{month:02d}-01") \
        .lte("date", f"{year}-{month:02d}-{days_in_month}") \
        .execute()

    calendar = {entry["date"]: entry for entry in schedule_res.data}
    print("RAD ID:", rad_id)

    certs_res = supabase.table("certifications") \
    .select("*") \
    .eq("radiologist_id", rad_id) \
    .order("expiration_date", desc=False) \
    .execute()

    from pprint import pprint
    pprint(certs_res.model_dump())
    certifications = certs_res.data
    print(certifications)

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
        available_facilities=available_facilities
    )

@dashboard_bp.route('/doctors/<string:rad_id>/update_schedule', methods=["POST"])
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
        .eq("date", date).execute()

    if existing.data:
        # Update existing entry
        supabase.table("monthly_schedule").update(data) \
            .eq("id", existing.data[0]["id"]).execute()
    else:
        # Insert new entry
        data["radiologist_id"] = rad_id
        data["date"] = date
        supabase.table("monthly_schedule").insert(data).execute()

    year = request.form.get("year")
    month = request.form.get("month")
    start_day = request.form.get("start_day")
    return redirect(url_for("dashboard.schedule", year=year, month=month, start_day=start_day))


@dashboard_bp.route('/doctors/<string:rad_id>/delete_schedule', methods=["POST"])
@login_required
def delete_schedule(rad_id):
    if session["user"]["role"] != "admin":
        return "Unauthorized", 403

    date = request.form.get("date")
    year = request.form.get("year")
    month = request.form.get("month")
    start_day = request.form.get("start_day")
    supabase.table("monthly_schedule").delete() \
        .eq("radiologist_id", rad_id).eq("date", date).execute()

    return redirect(url_for("dashboard.schedule", year=year, month=month, start_day=start_day))


@dashboard_bp.route('/doctors/<string:rad_id>/bulk_update_schedule', methods=["POST"])
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
            .eq("date", date).execute()

        payload = {
            "radiologist_id": rad_id,
            "date": date,
            "start_time": start_time,
            "end_time": end_time,
            "schedule_details": notes
        }

        if existing.data:
            supabase.table("monthly_schedule").update(payload) \
                .eq("id", existing.data[0]["id"]).execute()
        else:
            supabase.table("monthly_schedule").insert(payload).execute()

    return redirect(url_for("dashboard.doctor_profile", rad_id=rad_id))

@dashboard_bp.route('/facilities')
@login_required
def facilities():
    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page

    # Get total count for pagination
    count_res = supabase.table("facilities").select("*", count='exact').execute()
    total_count = count_res.count

    # Fetch paginated facilities
    res = supabase.table("facilities") \
        .select("*") \
        .order("name") \
        .range(offset, offset + per_page - 1) \
        .execute()
    facilities = res.data

    return render_template("facility_list.html", 
                         facilities=facilities,
                         total_count=total_count,
                         current_page=page,
                         per_page=per_page)

@dashboard_bp.route('/facilities/search', methods=["GET"])
@login_required
def search_facilities():
    search_term = request.args.get('search', '')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 25))
    status = request.args.get('status', 'all')
    
    offset = (page - 1) * per_page
    
    # Build the query
    query = supabase.table("facilities").select("*", count='exact')
    
    # Add search condition if search term exists
    if search_term:
        query = query.ilike('name', f'%{search_term}%')
    
    # Add status filter
    if status == 'active':
        query = query.eq('active_status', 'true')
    elif status == 'inactive':
        query = query.eq('active_status', 'false')
    
    # Add pagination
    query = query.range(offset, offset + per_page - 1)
    
    # Execute query
    result = query.execute()
    
    return jsonify({
        'facilities': result.data,
        'total_count': result.count,
        'current_page': page,
        'per_page': per_page
    })

@dashboard_bp.route('/facilities/<string:facility_id>')
@login_required
def facility_profile(facility_id):
    # Get facility info
    fac = supabase.table("facilities").select("*").eq("id", facility_id).single().execute().data

    # Get doctor assignments
    assignment_res = supabase.table("doctor_facility_assignments") \
        .select("*, radiologists(*)") \
        .eq("facility_id", facility_id).execute()

    # Get facility contacts
    contacts_res = supabase.table("facility_contact_assignments") \
        .select("*") \
        .eq("facility_id", facility_id) \
        .order("role") \
        .execute()
    
    return render_template("facility_profile.html",
        facility=fac,
        doctor_assignments=assignment_res.data,
        facility_contacts=contacts_res.data
    )

@dashboard_bp.route('/doctors/<string:rad_id>/update', methods=["POST"])
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

    return redirect(url_for("dashboard.doctor_profile", rad_id=rad_id))




@dashboard_bp.route('/dashboard/doctors/<rad_id>/add_certification', methods=['POST'])
@login_required
def add_certification(rad_id):
    data = {
        "id": str(uuid.uuid4()),
        "radiologist_id": rad_id,
        "state": request.form['state'],
        "expiration_date": request.form['expiration_date'],
        "status": request.form['status'],
        # 🆕 add these two:
        "specialty": request.form.get('specialty', ''),
        "tags": request.form.get('tags', ''),
    }
    supabase.table("certifications").insert(data).execute()

    return redirect(url_for('dashboard.doctor_profile', rad_id=rad_id))



@dashboard_bp.route('/dashboard/facility/<facility_id>/update', methods=['POST'])
@login_required
def update_facility(facility_id):
    form = request.form
    supabase.table('facilities').update({
        'location': form.get('location'),
        'pacs': form.get('pacs'),
        'tat_definition': form.get('tat_definition'),
        'modalities_assignment_period': form.get('modalities_assignment_period'),
        'active_status': 'true' if form.get('active_status') == 'true' else 'false',
    }).eq('id', facility_id).execute()
    return redirect(url_for('dashboard.facility_profile', facility_id=facility_id))


@dashboard_bp.route('/doctors/<string:rad_id>/licenses/<string:cert_id>/delete', methods=["POST"])
@login_required
def delete_certification(rad_id, cert_id):
    if session["user"]["role"] != "admin":
        return "Unauthorized", 403

    supabase.table("certifications").delete().eq("id", cert_id).execute()

    return redirect(url_for('dashboard.doctor_profile', rad_id=rad_id))

@dashboard_bp.route('/dashboard/assignments/<assignment_id>/update', methods=['POST'])
@login_required
def update_assignment(assignment_id):
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

    return redirect(request.referrer or url_for('dashboard.doctor_profile'))

@dashboard_bp.route('/dashboard/assignments/<assignment_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_assignment(assignment_id):
    supabase.table("doctor_facility_assignments").delete().eq("id", assignment_id).execute()
    return jsonify({"status": "success"})

@dashboard_bp.route('/licenses', methods=["GET", "POST"])
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
        return redirect(url_for("dashboard.licenses_page"))

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
        .order("expiration_date", desc=False) \
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

@dashboard_bp.route('/licenses/search', methods=["GET"])
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
    
    # Get paginated results
    query = query.order("expiration_date", desc=False) \
                .range(offset, offset + per_page - 1)
    results = query.execute()
    
    return jsonify({
        'certifications': results.data,
        'total_count': total_count,
        'current_page': page,
        'per_page': per_page
    })

@dashboard_bp.route('/chat', methods=['POST'])
@login_required
def chat():
    data = request.get_json()
    question = data.get('question', '')
    
    # Create schema description with accurate table information
    schema = """
    Tables in the database:
    1. vesta_contacts (
        id uuid,
        name text,
        department text,
        contact_number text,
        backup_number text,
        email text,
        additional_info text,
        created_at timestamptz,
        updated_at timestamptz
    )
    
    2. radiologists (
        id uuid,
        name text,
        pacs text,
        primary_contact_method text,
        phone text,
        email text,
        active_status bool,
        schedule_info_est text,
        additional_info text,
        credentialing_contact text,
        rad_guidelines text,
        modalities text,
        timezone text,
        reads_routines bool
    )
    
    3. certifications (
        id uuid,
        radiologist_id uuid REFERENCES radiologists(id),
        state text,
        expiration_date date,
        status text,
        specialty text,
        tags text
    )
    
    4. monthly_schedule (
        id uuid,
        radiologist_id uuid REFERENCES radiologists(id),
        date date,
        start_time time,
        end_time time,
        schedule_details text,
        notes text
    )
    
    5. specialty_studies (
        id uuid,
        name text,
        description text
    )
    
    6. specialty_permissions (
        id uuid,
        radiologist_id uuid REFERENCES radiologists(id),
        specialty_id uuid REFERENCES specialty_studies(id),
        can_read bool
    )
    
    7. facilities (
        id uuid,
        name text,
        pacs text,
        location text,
        modalities_assignment_period text,
        tat_definition text,
        active_status text
    )
    
    8. doctor_facility_assignments (
        id uuid,
        radiologist_id uuid REFERENCES radiologists(id),
        facility_id uuid REFERENCES facilities(id),
        can_read bool,
        stipulations text,
        does_stats bool,
        does_routines bool,
        notes text
    )
    
    9. facility_contact_assignments (
        id uuid,
        facility_id uuid REFERENCES facilities(id),
        contact_name text,
        email text,
        phone text,
        comments text,
        role text
    )
    
    10. vacations (
        id uuid,
        radiologist_id uuid REFERENCES radiologists(id),
        start_date date,
        end_date date,
        comments text
    )
    """
    
    # Format the schema as a string
    schema_str = f"Here is the database schema:\n{schema}"
    
    # Build the prompt
    prompt = f"""You are a helpful assistant for a medical radiology management system. 
    Use the following schema to answer questions about the database:
    
    {schema_str}
    
    Question: {question}
    
    If the question requires querying the database, respond with a SQL query that can be executed.
    The SQL query should:
    1. Use proper table names and column names exactly as shown in the schema
    2. Include necessary JOINs when querying related tables using the correct foreign key relationships
    3. Use proper PostgreSQL syntax and formatting
    4. Be wrapped in ```sql``` code blocks
    5. Consider data types (uuid, text, date, time, bool, timestamptz) when writing conditions
    6. DO NOT include semicolons at the end of queries
    
    If the question is about the schema or general information, provide a helpful response.
    """
    
    # Get response from Ollama
    response = ollama.chat(model='mistral', messages=[
        {
            'role': 'user',
            'content': prompt
        }
    ])
    
    # Extract the response text
    response_text = response['message']['content']
    
    # Check if the response contains a SQL query
    if '```sql' in response_text:
        try:
            # Extract the SQL query from the response and remove semicolon if present
            sql_query = response_text.split('```sql')[1].split('```')[0].strip()
            sql_query = sql_query.rstrip(';')  # Remove trailing semicolon if present
            
            # Log the query for debugging
            print(f"Executing SQL query: {sql_query}")
            
            # Execute the query using the execute_sql function
            result = supabase.rpc('execute_sql', {'query': sql_query}).execute()
            
            # Return both the explanation and the query results
            return jsonify({
                'explanation': response_text,
                'results': result.data
            })
        except Exception as e:
            print(f"Error executing query: {str(e)}")
            return jsonify({
                'error': f'Error executing query: {str(e)}',
                'explanation': response_text,
                'query': sql_query if 'sql_query' in locals() else None
            }), 500
    
    return jsonify({'response': response_text})


@dashboard_bp.route('/schedule')
@login_required
def schedule():
    now = datetime.now()
    year = request.args.get("year", default=now.year, type=int)
    month = request.args.get("month", default=now.month, type=int)
    start_day = request.args.get("start_day", default=1, type=int)
    days_in_month = monthrange(year, month)[1]

    # Show the full month
    window_dates = [datetime(year, month, d) for d in range(1, days_in_month + 1)]
    start_day = 1
    end_day = days_in_month

    # Get pagination parameters for doctors
    start_doctor = request.args.get('start_doctor', default=0, type=int)
    doctors_per_page = 15

    # Get all doctors first
    all_doctors_res = supabase.table("radiologists") \
        .select("*") \
        .order("name") \
        .execute()
    all_doctors = all_doctors_res.data
    total_doctors = len(all_doctors)

    # Get pinned doctors for the current user using their email
    user_email = session["user"]["email"]
    pinned_res = supabase.table("pinned_doctors") \
        .select("doctor_id") \
        .eq("user_id", user_email) \
        .execute()
    pinned_doctor_ids = [p["doctor_id"] for p in pinned_res.data]

    # Separate pinned and unpinned doctors
    pinned_doctors = [doc for doc in all_doctors if doc["id"] in pinned_doctor_ids]
    unpinned_doctors = [doc for doc in all_doctors if doc["id"] not in pinned_doctor_ids]

    # Handle pagination
    if start_doctor == 0:
        # First page: Show pinned doctors + fill remaining slots with unpinned
        if pinned_doctors:
            remaining_slots = doctors_per_page - len(pinned_doctors)
            if remaining_slots > 0:
                doctors = pinned_doctors + unpinned_doctors[:remaining_slots]
            else:
                doctors = pinned_doctors[:doctors_per_page]
        else:
            doctors = unpinned_doctors[:doctors_per_page]
    else:
        # Subsequent pages: Show unpinned doctors starting after those shown on first page
        if pinned_doctors:
            # Calculate how many unpinned doctors were shown on first page
            first_page_unpinned = max(0, doctors_per_page - len(pinned_doctors))
            # Start index for unpinned doctors
            unpinned_start = first_page_unpinned + (start_doctor - doctors_per_page)
            doctors = unpinned_doctors[unpinned_start:unpinned_start + doctors_per_page]
        else:
            # If no pinned doctors, regular pagination
            doctors = unpinned_doctors[start_doctor:start_doctor + doctors_per_page]

    # Get all schedules for the full month
    start_str = window_dates[0].strftime("%Y-%m-%d")
    end_str = window_dates[-1].strftime("%Y-%m-%d")
    schedule_res = supabase.table("monthly_schedule") \
        .select("*, radiologists(*)") \
        .gte("date", start_str) \
        .lte("date", end_str) \
        .execute()

    # Create a calendar dictionary for easy lookup
    calendar = defaultdict(dict)
    for entry in schedule_res.data:
        if entry.get("radiologists"):
            doc_id = entry["radiologists"]["id"]
            date = entry["date"]
            calendar[date][doc_id] = entry

    month_name = pycalendar.month_name[month]

    # Calculate total pages for pagination
    if pinned_doctors:
        # If we have pinned doctors, they take up the first page
        # Remaining unpinned doctors are spread across subsequent pages
        remaining_unpinned = len(unpinned_doctors)
        if len(pinned_doctors) < doctors_per_page:
            # Some unpinned doctors appear on first page
            remaining_unpinned -= (doctors_per_page - len(pinned_doctors))
        total_pages = 1 + max(0, (remaining_unpinned + doctors_per_page - 1) // doctors_per_page)
    else:
        # Regular pagination if no pinned doctors
        total_pages = (total_doctors + doctors_per_page - 1) // doctors_per_page

    return render_template("schedule.html",
        doctors=doctors,
        window_dates=window_dates,
        year=year,
        month=month,
        month_name=month_name,
        start_day=start_day,
        end_day=end_day,
        days_in_month=days_in_month,
        prev_start=1,
        next_start=1,
        calendar=calendar,
        datetime=datetime,
        start_doctor=start_doctor,
        total_doctors=total_doctors,
        total_pages=total_pages,
        min=min,
        all_doctors=all_doctors,
        pinned_doctors=pinned_doctor_ids)

@dashboard_bp.route('/schedule/pin', methods=['POST'])
@login_required
def pin_doctors():
    data = request.get_json()
    doctor_ids = data.get('doctor_ids', [])
    user_email = session["user"]["email"]
    
    if len(doctor_ids) > 15:
        return jsonify({'success': False, 'error': 'Cannot pin more than 15 doctors'})
    
    # Delete existing pins for this user
    supabase.table("pinned_doctors") \
        .delete() \
        .eq("user_id", user_email) \
        .execute()
    
    # Add new pins
    if doctor_ids:
        pins = [{
            "id": str(uuid.uuid4()),
            "user_id": user_email,
            "doctor_id": doctor_id
        } for doctor_id in doctor_ids]
        
        supabase.table("pinned_doctors").insert(pins).execute()
    
    return jsonify({'success': True})

@dashboard_bp.route('/schedule/search', methods=["GET"])
@login_required
def search_schedule():
    page = request.args.get('page', 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page
    
    # Get search term
    search_term = request.args.get('search', '')
    
    # Build query
    query = supabase.table("radiologists").select("*")
    
    if search_term:
        query = query.ilike('name', f'%{search_term}%')
    
    # Get total count for pagination
    count_res = query.execute()
    total_count = len(count_res.data)
    
    # Get paginated results
    query = query.order("name") \
                .range(offset, offset + per_page - 1)
    results = query.execute()
    
    return jsonify({
        'doctors': results.data,
        'total_count': total_count,
        'current_page': page,
        'per_page': per_page
    })

@dashboard_bp.route('/schedule/bulk', methods=['POST'])
@login_required
def bulk_schedule():
    if session["user"]["role"] != "admin":
        return "Unauthorized", 403

    print("Bulk Schedule Form Data:", request.form)
    
    doctor_id = request.form.get("doctor")
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")
    notes = request.form.get("schedule_details")

    print(f"Doctor ID: {doctor_id}")
    print(f"Start Date: {start_date}")
    print(f"End Date: {end_date}")
    print(f"Start Time: {start_time}")
    print(f"End Time: {end_time}")
    print(f"Notes: {notes}")

    # Check if it's a special case (OFF, VACATION, REACH AS NEEDED)
    is_special_case = notes in ['OFF', 'VACATION', 'REACH AS NEEDED']

    if not all([doctor_id, start_date, end_date]) or (not is_special_case and not all([start_time, end_time])):
        return "Missing data", 400

    # Convert dates to datetime objects
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    current = start

    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        print(f"Processing date: {date_str}")
        
        # Check if schedule already exists
        existing = supabase.table("monthly_schedule") \
            .select("id") \
            .eq("radiologist_id", doctor_id) \
            .eq("date", date_str).execute()

        payload = {
            "radiologist_id": doctor_id,
            "date": date_str,
            "start_time": start_time if not is_special_case else None,
            "end_time": end_time if not is_special_case else None,
            "schedule_details": notes
        }

        print(f"Payload: {payload}")

        if existing.data:
            print(f"Updating existing schedule for {date_str}")
            supabase.table("monthly_schedule").update(payload) \
                .eq("id", existing.data[0]["id"]).execute()
        else:
            print(f"Creating new schedule for {date_str}")
            supabase.table("monthly_schedule").insert(payload).execute()

        current += timedelta(days=1)

    return redirect(url_for("dashboard.schedule"))

@dashboard_bp.route('/schedule/pattern', methods=['POST'])
@login_required
def pattern_schedule():
    if session["user"]["role"] != "admin":
        return "Unauthorized", 403

    print("Pattern Schedule Form Data:", request.form)
    
    doctor_id = request.form.get("doctor")
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")
    days = request.form.getlist("days")  # Get list of selected days
    notes = request.form.get("schedule_details")

    print(f"Doctor ID: {doctor_id}")
    print(f"Start Date: {start_date}")
    print(f"End Date: {end_date}")
    print(f"Start Time: {start_time}")
    print(f"End Time: {end_time}")
    print(f"Days: {days}")
    print(f"Notes: {notes}")

    # Check if it's a special case (OFF, VACATION, REACH AS NEEDED)
    is_special_case = notes in ['OFF', 'VACATION', 'REACH AS NEEDED']

    if not all([doctor_id, start_date, end_date, days]) or (not is_special_case and not all([start_time, end_time])):
        return "Missing data", 400

    # Convert dates to datetime objects
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    current = start

    while current <= end:
        # Check if current day is in selected days
        if str(current.weekday()) in days:
            date_str = current.strftime("%Y-%m-%d")
            print(f"Processing date: {date_str}")
            
            # Check if schedule already exists
            existing = supabase.table("monthly_schedule") \
                .select("id") \
                .eq("radiologist_id", doctor_id) \
                .eq("date", date_str).execute()

            payload = {
                "radiologist_id": doctor_id,
                "date": date_str,
                "start_time": start_time if not is_special_case else None,
                "end_time": end_time if not is_special_case else None,
                "schedule_details": notes
            }

            print(f"Payload: {payload}")

            if existing.data:
                print(f"Updating existing schedule for {date_str}")
                supabase.table("monthly_schedule").update(payload) \
                    .eq("id", existing.data[0]["id"]).execute()
            else:
                print(f"Creating new schedule for {date_str}")
                supabase.table("monthly_schedule").insert(payload).execute()

        current += timedelta(days=1)

    return redirect(url_for("dashboard.schedule"))

@dashboard_bp.route('/info')
@login_required
def info():
    return render_template("info.html")

@dashboard_bp.route('/vacations')
@login_required
def vacations_page():
    # Fetch all doctors
    doctors_res = supabase.table("radiologists").select("*").order("name").execute()
    doctors = doctors_res.data

    # Fetch all vacations
    vacations_res = supabase.table("vacations").select("*, radiologists(*)").execute()
    vacations = vacations_res.data

    return render_template("vacations.html", doctors=doctors, vacations=vacations)

@dashboard_bp.route('/vacations/add', methods=['POST'])
@login_required
@admin_required
def add_vacation():
    data = {
        "id": str(uuid.uuid4()),
        "radiologist_id": request.form.get("radiologist_id"),
        "start_date": request.form.get("start_date"),
        "end_date": request.form.get("end_date"),
        "comments": request.form.get("comments")
    }
    supabase.table("vacations").insert(data).execute()
    return redirect(url_for("dashboard.vacations_page"))

@dashboard_bp.route('/vacations/update', methods=['POST'])
@login_required
@admin_required
def update_vacation():
    vacation_id = request.form.get("vacation_id")
    data = {
        "radiologist_id": request.form.get("radiologist_id"),
        "start_date": request.form.get("start_date"),
        "end_date": request.form.get("end_date"),
        "comments": request.form.get("comments")
    }
    supabase.table("vacations").update(data).eq("id", vacation_id).execute()
    return redirect(url_for("dashboard.vacations_page"))

@dashboard_bp.route('/vacations/delete', methods=['POST'])
@login_required
@admin_required
def delete_vacation():
    vacation_id = request.json.get("vacation_id")
    supabase.table("vacations").delete().eq("id", vacation_id).execute()
    return jsonify({"status": "success"})

@dashboard_bp.route('/landing')
@login_required
def landing():
    return render_template("landing.html")

@dashboard_bp.route('/contacts')
@login_required
def contacts():
    # Fetch contacts from the database
    response = supabase.table("vesta_contacts").select("*").order("department").execute()
    contacts = response.data

    # Get unique departments from contacts
    departments = sorted(set(contact["department"] for contact in contacts))
    
    return render_template("contacts.html", contacts=contacts, departments=departments)

@dashboard_bp.route('/contacts/add', methods=['POST'])
@login_required
@admin_required
def add_contact():
    data = {
        "id": str(uuid.uuid4()),
        "name": request.form.get("name"),
        "department": request.form.get("department"),
        "contact_number": request.form.get("contact_number"),
        "extension_number": request.form.get("extension_number"),
        "email": request.form.get("email"),
        "additional_info": request.form.get("additional_info"),
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    supabase.table("vesta_contacts").insert(data).execute()
    return redirect(url_for("dashboard.contacts"))

@dashboard_bp.route('/contacts/<string:contact_id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_contact(contact_id):
    data = {
        "name": request.form.get("name"),
        "department": request.form.get("department"),
        "contact_number": request.form.get("contact_number"),
        "extension_number": request.form.get("extension_number"),
        "email": request.form.get("email"),
        "additional_info": request.form.get("additional_info"),
        "updated_at": datetime.now().isoformat()
    }
    supabase.table("vesta_contacts").update(data).eq("id", contact_id).execute()
    return redirect(url_for("dashboard.contacts"))

@dashboard_bp.route('/contacts/<string:contact_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_contact(contact_id):
    supabase.table("vesta_contacts").delete().eq("id", contact_id).execute()
    return redirect(url_for("dashboard.contacts"))

# Add timezone conversion filter
@dashboard_bp.app_template_filter('convert_timezone')
def convert_timezone(time_str, target_tz):
    if not time_str:
        return ""
    try:
        # Parse the time string
        hour, minute = map(int, time_str.split(":"))
        # Create a datetime object for today with the given time
        dt = datetime.now().replace(hour=hour, minute=minute)
        
        # Convert to target timezone
        target_timezone = pytz.timezone(
            "America/New_York" if target_tz == "EST" else
            "America/Chicago" if target_tz == "CST" else
            "America/Los_Angeles" if target_tz == "PST" else
            "UTC"
        )
        
        # Convert the time
        converted_time = dt.astimezone(target_timezone)
        return converted_time.strftime("%I:%M %p")
    except Exception as e:
        print(f"Error converting timezone: {e}")
        return time_str

@dashboard_bp.route('/specialties')
@login_required
def specialties():
    user_email = session["user"]["email"]
    pinned_res = supabase.table("pinned_doctors") \
        .select("doctor_id") \
        .eq("user_id", user_email) \
        .execute()
    pinned_doctor_ids = [p["doctor_id"] for p in pinned_res.data]

    # Get all specialties with their descriptions
    specialties_res = supabase.table("specialty_studies").select("*").order("name").execute()
    specialties = specialties_res.data

    # Get all doctors
    doctors_res = supabase.table("radiologists").select("*").order("name").execute()
    doctors = doctors_res.data

    # Get all specialty permissions
    permissions_res = supabase.table("specialty_permissions") \
        .select("*, radiologists(id, name), specialty_studies(id, name)") \
        .execute()
    permissions = permissions_res.data


    # Create a mapping for easy lookup of permissions
    permission_map = {}
    for perm in permissions:
        rad_id = perm["radiologist_id"]
        spec_id = perm["specialty_id"]
        if rad_id not in permission_map:
            permission_map[rad_id] = {}
        permission_map[rad_id][spec_id] = perm["can_read"]

    # Assuming `doctors` is a list of dicts and already sorted with pinned first
    sorted_doctors = sorted(doctors, key=lambda doc: str(doc['id']) not in pinned_doctor_ids)

    # Limit to 15 doctors
    visible_doctors = sorted_doctors[:15]

    page = int(request.args.get('page', 1))
    page_size = 15
    total_doctors = len(sorted_doctors)
    start = (page - 1) * page_size
    end = start + page_size
    visible_doctors = sorted_doctors[start:end]

    return render_template("specialties.html",
                           doctors=visible_doctors,
                           specialties=specialties,
                           permission_map=permission_map,
                           pinned_doctors=pinned_doctor_ids,
                           page=page,
                           total_pages=(total_doctors + page_size - 1) // page_size)


@dashboard_bp.route('/specialties/add', methods=['POST'])
@login_required
@admin_required
def add_specialty():
    data = {
        "id": str(uuid.uuid4()),
        "name": request.form.get("name"),
        "description": request.form.get("description")
    }
    supabase.table("specialty_studies").insert(data).execute()
    return redirect(url_for("dashboard.specialties"))

@dashboard_bp.route('/specialties/<string:specialty_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_specialty(specialty_id):
    # First delete all permissions for this specialty
    supabase.table("specialty_permissions").delete().eq("specialty_id", specialty_id).execute()
    # Then delete the specialty itself
    supabase.table("specialty_studies").delete().eq("id", specialty_id).execute()
    return redirect(url_for("dashboard.specialties"))

@dashboard_bp.route('/specialties/permissions/update', methods=['POST'])
@login_required
@admin_required
def update_specialty_permission():
    radiologist_id = request.form.get("radiologist_id")
    specialty_id = request.form.get("specialty_id")
    can_read = request.form.get("can_read") == "true"
    
    # Check if permission already exists
    existing = supabase.table("specialty_permissions") \
        .select("id") \
        .eq("radiologist_id", radiologist_id) \
        .eq("specialty_id", specialty_id) \
        .execute()

    if existing.data:
        # Update existing permission
        supabase.table("specialty_permissions").update({
            "can_read": can_read
        }).eq("id", existing.data[0]["id"]).execute()
    else:
        # Create new permission
        supabase.table("specialty_permissions").insert({
            "id": str(uuid.uuid4()),
            "radiologist_id": radiologist_id,
            "specialty_id": specialty_id,
            "can_read": can_read
        }).execute()

    return jsonify({"status": "success"})

@dashboard_bp.route('/doctors/<string:rad_id>/add_facility', methods=['POST'])
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
    return redirect(url_for("dashboard.doctor_profile", rad_id=rad_id))

@dashboard_bp.route('/facilities/<string:facility_id>/contacts/add', methods=['POST'])
@login_required
@admin_required
def add_facility_contact(facility_id):
    data = {
        "id": str(uuid.uuid4()),
        "facility_id": facility_id,
        "contact_name": request.form.get("contact_name"),
        "role": request.form.get("role"),
        "email": request.form.get("email"),
        "phone": request.form.get("phone"),
        "comments": request.form.get("comments")
    }
    
    supabase.table("facility_contact_assignments").insert(data).execute()
    return redirect(url_for("dashboard.facility_profile", facility_id=facility_id))

@dashboard_bp.route('/facilities/<string:facility_id>/contacts/<string:contact_id>', methods=['POST'])
@login_required
@admin_required
def edit_facility_contact(facility_id, contact_id):
    data = {
        "contact_name": request.form.get("contact_name"),
        "role": request.form.get("role"),
        "email": request.form.get("email"),
        "phone": request.form.get("phone"),
        "comments": request.form.get("comments")
    }
    
    supabase.table("facility_contact_assignments").update(data).eq("id", contact_id).execute()
    return redirect(url_for("dashboard.facility_profile", facility_id=facility_id))

@dashboard_bp.route('/facility/<string:facility_id>/contact/<string:contact_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_facility_contact_api(facility_id, contact_id):
    try:
        print(f"Attempting to delete contact {contact_id} from facility {facility_id}")
        
        # First verify the contact exists and belongs to the facility
        verify = supabase.table("facility_contact_assignments")\
            .select("*")\
            .eq("id", contact_id)\
            .eq("facility_id", facility_id)\
            .execute()
            
        print(f"Verification result: {verify.data}")
        
        if not verify.data:
            print("Contact not found or doesn't belong to this facility")
            return jsonify({"success": False, "error": "Contact not found"}), 404

        # Proceed with deletion
        result = supabase.table("facility_contact_assignments")\
            .delete()\
            .eq("id", contact_id)\
            .eq("facility_id", facility_id)\
            .execute()
            
        print(f"Delete result: {result.data}")
        
        if result.data:
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": "Delete operation failed"}), 500
            
    except Exception as e:
        print(f"Error deleting contact: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@dashboard_bp.route('/doctors/add', methods=['POST'])
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

    return redirect(url_for("dashboard.doctor_profile", rad_id=new_id))

@dashboard_bp.route('/facilities/add', methods=['POST'])
@login_required
@admin_required
def add_facility():
    data = request.get_json()
    
    # Generate a new UUID for the facility
    new_id = str(uuid.uuid4())
    
    # Add the ID to the data
    data['id'] = new_id
    
    # Insert the new facility into the database
    supabase.table("facilities").insert(data).execute()
    
    return jsonify({"status": "success", "id": new_id})

