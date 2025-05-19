# RadMapping+/app/routes/shifts.py

from flask import Blueprint, render_template, session, request
from datetime import datetime, timedelta
from collections import defaultdict
from app.supabase_client import get_supabase_client
from app.middleware import with_supabase_auth
from calendar import monthrange

shifts_bp = Blueprint('shifts', __name__)

# Helper functions from daily.py (assuming they are needed for RVU calculation)
def get_prev_month_same_dow_and_hour(dt):
    # dt: datetime object for the current slot
    # Find the previous month
    year = dt.year
    month = dt.month
    day = dt.day
    hour = dt.hour
    # Go to previous month
    if month == 1:
        prev_month = 12
        prev_year = year - 1
    else:
        prev_month = month - 1
        prev_year = year
    # Find all days in prev month with same weekday as dt
    first_day_prev_month = datetime(prev_year, prev_month, 1)
    days_in_prev_month = monthrange(prev_year, prev_month)[1]
    candidates = []
    for d in range(1, days_in_prev_month + 1):
        candidate = datetime(prev_year, prev_month, d)
        if candidate.weekday() == dt.weekday():
            candidates.append(candidate)
    # Pick the candidate closest to the same day-of-month, or just the first if none
    if not candidates:
        return None, hour
    # Try to match the same week of the month
    week_of_month = (dt.day - 1) // 7
    if week_of_month < len(candidates):
        chosen = candidates[week_of_month]
    else:
        chosen = candidates[-1]
    return chosen.date().isoformat(), hour

# Helper: Get latest non-zero monthly RVU for a doctor
def get_latest_nonzero_rvu(rvu_row):
    # rvu_row: dict with keys jan, feb, ..., dec
    # Find the latest non-zero value, starting from dec to jan
    months = ["dec", "nov", "oct", "sep", "aug", "jul", "jun", "may", "apr", "mar", "feb", "jan"]
    for m in months:
        val = rvu_row.get(m)
        if val is not None and val != 0:
            return val
    return 0


@shifts_bp.route('/shifts')
@with_supabase_auth
def shifts():
    supabase = get_supabase_client()
    
    # Get today's date
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    base_date = datetime.strptime(today, "%Y-%m-%d")
    
    # Define hour slots for today (00:00 to 23:00)
    hour_slots = []
    current_hour = base_date.replace(hour=0, minute=0, second=0, microsecond=0)
    while current_hour < base_date + timedelta(days=1):
        hour_slots.append({
            "datetime": current_hour,
            "label": current_hour.strftime("%I %p").lstrip("0"),
            "hour": current_hour.hour,
            "date": current_hour.strftime("%Y-%m-%d"),
            "day_label": "Today" # Since we only show today on this page
        })
        current_hour += timedelta(hours=1)

    # Fetch monthly schedule data for today to get doctors on shift
    query = supabase.table("monthly_schedule") \
        .select("*, radiologists(*)") \
        .lte("start_date", today) \
        .gte("end_date", today)
    
    shift_res = query.execute()

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
                
                # Handle break times (though not used for RVU calculation here, good to have)
                break_start_dt = None
                break_end_dt = None
                if entry.get("break_start") and entry.get("break_end"):
                    break_start_dt = datetime.strptime(f"{start_date} {entry['break_start']}", "%Y-%m-%d %H:%M:%S")
                    break_end_dt = datetime.strptime(f"{start_date} {entry['break_end']}", "%Y-%m-%d %H:%M:%S")
                    if break_end_dt < break_start_dt:
                        break_end_dt += timedelta(days=1)

                doc.update({
                    "start_time": entry["start_time"],
                    "end_time": entry["end_time"],
                    "start_date": start_date,
                    "end_date": end_date,
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                    "break_start_dt": break_start_dt,
                    "break_end_dt": break_end_dt
                })
                doctors_on_shift.append(doc)
            except Exception as e:
                print(f"Error parsing datetime for doc {doc.get('name', 'Unknown')}: {e}")

    # Fill doctor shifts by hour for today's slots
    doctors_by_hour = defaultdict(list)
    for doc in doctors_on_shift:
        for slot in hour_slots:
            slot_start = slot["datetime"]
            slot_end = slot_start + timedelta(hours=1)
            
            # Check if doctor is on break during this slot
            is_on_break = False
            if doc.get("break_start_dt") and doc.get("break_end_dt"):
                is_on_break = (doc["break_start_dt"] < slot_end and doc["break_end_dt"] > slot_start)
            
            # Only add doctor if they're on shift and not on break
            if doc["start_dt"] < slot_end and doc["end_dt"] > slot_start and not is_on_break:
                doctors_by_hour[slot_start].append(doc)

    # Fetch all RVU rows for all doctors (consider filtering this too based on doctors_on_shift for efficiency)
    rvu_res = supabase.table("rad_avg_monthly_rvu").select("*").execute()
    rvu_rows = {row["radiologist_id"]: row for row in (rvu_res.data or [])}

    # Build hourly_rvu_stats: {slot_datetime: {"historical": val, "current": val}}
    hourly_rvu_stats = {}
    for slot in hour_slots:
        slot_dt = slot["datetime"]
        # 1. Historical RVU
        prev_date, prev_hour = get_prev_month_same_dow_and_hour(slot_dt)
        historical_rvu = None
        if prev_date is not None:
            # Assuming 'capacity_per_hour' table has historical data
            cap_res = supabase.table("capacity_per_hour").select("total_rvus").eq("date", prev_date).eq("hour", prev_hour).execute()
            if cap_res.data and len(cap_res.data) > 0:
                historical_rvu = cap_res.data[0]["total_rvus"]
        # 2. Current total RVU (only sum RVU for doctors currently included after modality filter)
        slot_doctors = doctors_by_hour.get(slot_dt, [])
        current_total_rvu = 0
        for doc in slot_doctors:
            rvu_row = rvu_rows.get(doc["id"])
            if rvu_row:
                current_total_rvu += get_latest_nonzero_rvu(rvu_row)
        hourly_rvu_stats[slot_dt] = {
            "historical": historical_rvu,
            "current": current_total_rvu
        }

    # Sort hour_slots by the ratio of current RVU to historical capacity (ascending)
    # Shifts needing most attention (lowest ratio or missing historical/current) first
    def sort_key(slot):
        stats = hourly_rvu_stats.get(slot["datetime"])
        if not stats or stats["historical"] is None or stats["historical"] <= 0:
            # Put hours with no historical data or zero expected capacity first (need attention)
            if not stats or stats["current"] is None:
                 # Also prioritize if no current data
                 return -2 # Higher priority than just missing historical
            return -1
        if stats["current"] is None:
             return -1 # Also prioritize if no current data but have historical

        return (stats["current"] / stats["historical"]) # Sort by ratio

    # Filter out hour slots where there are no doctors scheduled after applying the modality filter
    # and no RVU data exists.
    filtered_hour_slots = [slot for slot in hour_slots if doctors_by_hour.get(slot["datetime"]) or hourly_rvu_stats.get(slot["datetime"]) and (hourly_rvu_stats[slot["datetime"]]['current'] is not None or hourly_rvu_stats[slot["datetime"]]['historical'] is not None)]

    sorted_hour_slots = sorted(filtered_hour_slots, key=sort_key)


    return render_template('shifts.html', 
                           hour_slots=sorted_hour_slots, 
                           hourly_rvu_stats=hourly_rvu_stats,
                           today=today,
                           doctors_by_hour=doctors_by_hour) 