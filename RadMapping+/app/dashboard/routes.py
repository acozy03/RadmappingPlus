from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from app.decorators import admin_required
from app.supabase_client import supabase
from datetime import datetime, timedelta
from calendar import monthrange
from collections import defaultdict
import uuid  
import calendar as pycalendar
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
        doctors_currently_on_shift_ids=doctors_currently_on_shift_ids  
    )

@dashboard_bp.route('/admin')
@admin_required
def admin():
    return "Admin-only page"

@dashboard_bp.route('/doctors')
@login_required
def doctor_list():
    response = supabase.table("radiologists").select("*").execute()
    doctors = response.data
    return render_template("doctor_list.html", doctors=doctors)

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
        assigned_facilities=assigned_facilities
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
    res = supabase.table("facilities").select("*").order("name").execute()
    facilities = res.data
    return render_template("facility_list.html", facilities=facilities)

@dashboard_bp.route('/facilities/<string:facility_id>')
@login_required
def facility_profile(facility_id):
    fac = supabase.table("facilities").select("*").eq("id", facility_id).single().execute().data

    assignment_res = supabase.table("doctor_facility_assignments") \
        .select("*, radiologists(*)") \
        .eq("facility_id", facility_id).execute()

    from pprint import pprint
    pprint(assignment_res.data)
    
    return render_template("facility_profile.html",
        facility=fac,
        doctor_assignments=assignment_res.data


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
        'active_status': form.get('active_status') == 'true',
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

@dashboard_bp.route('/dashboard/assignments/<assignment_id>/delete')
@login_required
def delete_assignment(assignment_id):
    supabase.table('assignments').delete().eq('id', assignment_id).execute()
    return redirect(request.referrer or url_for('dashboard.home'))

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

    # Fetch all licenses with radiologist names
    certs_res = supabase.table("certifications").select("*, radiologists(name)").order("expiration_date", desc=False).execute()
    certifications = certs_res.data or []
    return render_template("licenses.html", certifications=certifications, radiologists=radiologists)


@dashboard_bp.route('/chat', methods=['POST'])
@login_required
def chat():
    from llama_index.core import Settings
    from llama_index.llms.openai import OpenAI
    import os

    # Get the user's question
    question = request.json.get('question')
    if not question:
        return jsonify({'error': 'No question provided'}), 400

    try:
        # Initialize OpenAI
        llm = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        Settings.llm = llm

        # Get database schema from Supabase
        tables = [
            "radiologists",
            "facilities",
            "certifications",
            "doctor_facility_assignments",
            "monthly_schedule",
            "vacations"
        ]

        # Get schema information for each table
        schema_info = {}
        for table in tables:
            response = supabase.table(table).select("*").limit(1).execute()
            if response.data:
                # Get column names from the first row
                schema_info[table] = list(response.data[0].keys())

        # Create a prompt that includes the schema information
        schema_prompt = "Database Schema:\n"
        for table, columns in schema_info.items():
            schema_prompt += f"\n{table} table columns: {', '.join(columns)}"

        # Create the full prompt
        full_prompt = f"{schema_prompt}\n\nQuestion: {question}\n\nPlease provide a SQL query to answer this question and explain the results."

        # Get response from OpenAI
        response = llm.complete(full_prompt)
        
        return jsonify({
            'answer': str(response),
            'sql_query': 'Generated based on Supabase schema'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

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

    # Get all doctors
    doctors_res = supabase.table("radiologists").select("*").order("name").execute()
    doctors = doctors_res.data

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
        datetime=datetime
    )

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