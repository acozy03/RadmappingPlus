from flask import Blueprint, render_template, session, redirect, url_for, request
from app.admin_required import admin_required
from app.supabase_client import supabase
from datetime import datetime, timedelta
from collections import defaultdict

daily_bp = Blueprint('daily', __name__)

def login_required(view_func):
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("auth.login"))
        return view_func(*args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper

@daily_bp.route('/daily')
@login_required
def daily():
    from collections import defaultdict
    from datetime import datetime, timedelta

    user = session.get("user")

    selected_timezone = request.args.get("timezone", "EST")
    timezone_offset = {
        'EST': 0,
        'CST': 1,
        'PST': 3,
        'UTC': 5
    }.get(selected_timezone, 0)

    date_str = request.args.get("date")
    now = datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.now()

    today = now.strftime("%Y-%m-%d")
    prev_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    next_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    base_date = datetime.strptime(today, "%Y-%m-%d")
    max_end_dt = base_date.replace(hour=0, minute=0, second=0, microsecond=0)

    # Pre-fetch schedule data
    shift_res = supabase.table("monthly_schedule") \
        .select("*, radiologists(*)") \
        .lte("start_date", today) \
        .gte("end_date", today) \
        .execute()

    doctors_on_shift = []

    for entry in shift_res.data:
        if entry.get("radiologists") and entry.get("start_time") and entry.get("end_time"):
            doc = entry["radiologists"]
            start_date = entry.get("start_date") or today
            end_date = entry.get("end_date") or today
            try:
                start_dt = datetime.strptime(f"{start_date} {entry['start_time']}", "%Y-%m-%d %H:%M:%S")
                end_dt = datetime.strptime(f"{end_date} {entry['end_time']}", "%Y-%m-%d %H:%M:%S")
                if end_dt < start_dt:
                    end_dt += timedelta(days=1)
                doc.update({
                    "start_time": entry["start_time"],
                    "end_time": entry["end_time"],
                    "schedule_details": entry.get("schedule_details", ""),
                    "start_date": start_date,
                    "end_date": end_date,
                    "start_dt": start_dt,
                    "end_dt": end_dt
                })
                doctors_on_shift.append(doc)
                if end_dt > max_end_dt:
                    max_end_dt = end_dt
            except Exception as e:
                print(f"Error parsing datetime for doc {doc.get('name', 'Unknown')}: {e}")

    # Build hour slots
    hour_slots = []
    current_hour = base_date.replace(hour=0, minute=0, second=0, microsecond=0)
    while current_hour < max_end_dt:
        hour_slots.append({
            "datetime": current_hour,
            "label": current_hour.strftime("%I %p").lstrip("0"),
            "hour": current_hour.hour,
            "date": current_hour.strftime("%Y-%m-%d"),
        })
        current_hour += timedelta(hours=1)

    # Label slots for today/tomorrow
    today_dt = datetime.strptime(today, "%Y-%m-%d")
    tomorrow_str = (today_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    for slot in hour_slots:
        if slot['date'] == today:
            slot['day_label'] = 'Today'
        elif slot['date'] == tomorrow_str:
            slot['day_label'] = 'Tomorrow'
        else:
            slot['day_label'] = slot['date']

    # Fill doctor shifts by hour
    doctors_by_hour = defaultdict(list)
    for doc in doctors_on_shift:
        for slot in hour_slots:
            slot_start = slot["datetime"]
            slot_end = slot_start + timedelta(hours=1)
            if doc["start_dt"] < slot_end and doc["end_dt"] > slot_start:
                doctors_by_hour[slot_start].append(doc)

    # All doctors by timezone
    all_doctors_res = supabase.table("radiologists").select("*").execute()
    all_doctors = all_doctors_res.data or []
    doctors_by_timezone = defaultdict(list)
    for doctor in all_doctors:
        tz = doctor.get("timezone", "Unknown")
        if tz is None:
            tz = "Unknown"
        doctors_by_timezone[tz].append(doctor)

    doctors_on_shift_ids = {doc["id"] for doc in doctors_on_shift if doc.get("id") is not None}
    doctors_currently_on_shift_ids = set()
    current_hour = datetime.now().hour
    for doc in doctors_on_shift:
        try:
            if doc.get("start_time") and doc.get("end_time"):
                start_hour = int(doc["start_time"].split(":")[0])
                end_hour = int(doc["end_time"].split(":")[0])
                if start_hour <= current_hour < end_hour and doc.get("id") is not None:
                    doctors_currently_on_shift_ids.add(doc["id"])
        except Exception as e:
            print("Error checking current shift:", e)

    return render_template("daily.html",
        user=user,
        today=today,
        prev_date=prev_date,
        next_date=next_date,
        doctors_on_shift=doctors_on_shift,
        doctors_by_hour=doctors_by_hour,
        doctors_by_timezone=dict(doctors_by_timezone),  # Convert defaultdict to dict
        doctors_on_shift_ids=list(doctors_on_shift_ids),  # Convert set to list
        doctors_currently_on_shift_ids=list(doctors_currently_on_shift_ids),  # Convert set to list
        selected_timezone=selected_timezone,
        timezone_offset=timezone_offset,
        hour_slots=hour_slots
    ) 