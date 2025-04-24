from flask import Blueprint, render_template, session, redirect, url_for, request
from app.decorators import admin_required
from app.supabase_client import supabase
from datetime import datetime
import calendar
from calendar import monthrange
from datetime import datetime
from collections import defaultdict
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
        certifications=certifications
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

    return redirect(url_for("dashboard.doctor_profile", rad_id=rad_id))


@dashboard_bp.route('/doctors/<string:rad_id>/delete_schedule')
@login_required
def delete_schedule(rad_id):
    if session["user"]["role"] != "admin":
        return "Unauthorized", 403

    date = request.args.get("date")
    supabase.table("monthly_schedule").delete() \
        .eq("radiologist_id", rad_id).eq("date", date).execute()

    return redirect(url_for("dashboard.doctor_profile", rad_id=rad_id))


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
