# RadMapping+/app/routes/shifts.py

from flask import Blueprint, render_template, session, request
from datetime import datetime, timedelta
from collections import defaultdict
from app.supabase_client import get_supabase_client
from app.middleware import with_supabase_auth
from calendar import monthrange
from app.supabase_helper import fetch_all_rows

shifts_bp = Blueprint('shifts', __name__)
def get_prev_week_same_day_and_hour(dt):
    prev_week_dt = dt - timedelta(weeks=1)
    return prev_week_dt.date().isoformat(), prev_week_dt.hour

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

# Helper: Determine background color class based on RVU ratio
def get_rvu_bg_color_class(ratio):
    if ratio is not None:
        if ratio <= 0.6:
            return 'bg-red-100'
        elif ratio <= 0.9:
            return 'bg-yellow-100'
        else:
            return 'bg-green-100'
    return 'bg-gray-100' # Default color for no ratio

# Add this near the top, after imports
US_STATES = [
    'Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado', 'Connecticut', 'Delaware', 'Florida', 'Georgia',
    'Hawaii', 'Idaho', 'Illinois', 'Indiana', 'Iowa', 'Kansas', 'Kentucky', 'Louisiana', 'Maine', 'Maryland', 'Massachusetts',
    'Michigan', 'Minnesota', 'Mississippi', 'Missouri', 'Montana', 'Nebraska', 'Nevada', 'New Hampshire', 'New Jersey',
    'New Mexico', 'New York', 'North Carolina', 'North Dakota', 'Ohio', 'Oklahoma', 'Oregon', 'Pennsylvania', 'Rhode Island',
    'South Carolina', 'South Dakota', 'Tennessee', 'Texas', 'Utah', 'Vermont', 'Virginia', 'Washington', 'West Virginia',
    'Wisconsin', 'Wyoming'
]

@shifts_bp.route('/shifts')
@with_supabase_auth
def shifts():
    supabase = get_supabase_client()
    
    # Get today's date and calculate the start and end of the current week (Mon-Sun)
    now = datetime.now()
    # Find the most recent Monday (or today if today is Monday)
    start_of_week = now - timedelta(days=now.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    
    start_date_str = start_of_week.strftime("%Y-%m-%d")
    end_date_str = end_of_week.strftime("%Y-%m-%d")

    # Define hour slots for the entire week (00:00 to 23:00 for each day)
    hour_slots_by_day = defaultdict(list)
    current_day = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    while current_day <= end_of_week.replace(hour=0, minute=0, second=0, microsecond=0):
        current_hour = current_day.replace(hour=0)
        while current_hour < current_day + timedelta(days=1):
            hour_slots_by_day[current_day.date()].append({
                "datetime": current_hour,
                "label": current_hour.strftime("%I %p").lstrip("0"),
                "hour": current_hour.hour,
                "date": current_hour.strftime("%Y-%m-%d"),
                "day_label": current_day.strftime("%A") # Full weekday name
            })
            current_hour += timedelta(hours=1)
        current_day += timedelta(days=1)

    # Fetch monthly schedule data for the entire week to get doctors on shift
    query = supabase.table("monthly_schedule") \
        .select("*, radiologists(*)") \
        .lte("start_date", end_date_str) \
        .gte("end_date", start_date_str) # Consider shifts that span across the week

    shift_res = query.execute()

    doctors_on_shift = []
    for entry in shift_res.data:
         if entry.get("radiologists") and entry.get("start_time") and entry.get("end_time"):
            doc = entry["radiologists"]
            
            start_date = entry.get("start_date") or start_date_str # Default to week start if dates missing
            end_date = entry.get("end_date") or end_date_str # Default to week end if dates missing

            try:
                # Need to handle shifts that start before the week or end after the week
                # and also shifts that span across midnight
                
                # Calculate actual start and end datetime objects, considering cross-midnight shifts
                shift_start_dt = datetime.strptime(f"{start_date} {entry['start_time']}", "%Y-%m-%d %H:%M:%S")
                shift_end_dt = datetime.strptime(f"{end_date} {entry['end_time']}", "%Y-%m-%d %H:%M:%S")
                if shift_end_dt < shift_start_dt:
                    shift_end_dt += timedelta(days=1) # Shift crosses midnight

                # Handle break times, also considering cross-midnight if applicable
                break_start_dt = None
                break_end_dt = None
                if entry.get("break_start") and entry.get("break_end"):
                     # Break times are usually within a single 24 hour period relative to the start of the shift day
                    break_start_dt_candidate = datetime.strptime(f"{start_date} {entry['break_start']}", "%Y-%m-%d %H:%M:%S")
                    break_end_dt_candidate = datetime.strptime(f"{start_date} {entry['break_end']}", "%Y-%m-%d %H:%M:%S")
                    if break_end_dt_candidate < break_start_dt_candidate:
                         break_end_dt_candidate += timedelta(days=1) # Break crosses midnight

                    break_start_dt = break_start_dt_candidate
                    break_end_dt = break_end_dt_candidate

                doc_schedule_details = {
                    "start_time": entry["start_time"],
                    "end_time": entry["end_time"],
                    "start_date": start_date,
                    "end_date": end_date,
                    "start_dt": shift_start_dt,
                    "end_dt": shift_end_dt,
                    "break_start_dt": break_start_dt,
                    "break_end_dt": break_end_dt
                }
                # Add the schedule details to the doctor object
                full_doc_info = doc.copy()
                full_doc_info.update(doc_schedule_details)
                doctors_on_shift.append(full_doc_info)

            except Exception as e:
                print(f"Error parsing datetime for doc {doc.get('name', 'Unknown')}: {e}")

    # Fill doctor shifts by hour for each day's slots
    doctors_by_hour = defaultdict(list) # Key: datetime object for the hour slot
    for doc in doctors_on_shift:
        for day, hour_slots in hour_slots_by_day.items():
            for slot in hour_slots:
                slot_start = slot["datetime"]
                slot_end = slot_start + timedelta(hours=1)
                
                # Check if doctor is on break during this slot
                is_on_break = False
                if doc.get("break_start_dt") and doc.get("break_end_dt"):
                    # Check if the hour slot overlaps with the doctor's break time.
                    # Need to consider the date of the slot relative to the shift start date for breaks that cross midnight.
                    # If the break crosses midnight, it applies to the day the shift started AND the following day.
                    
                    # Calculate the break start and end datetimes relative to the current slot's date
                    break_start_on_slot_day = datetime.combine(slot_start.date(), doc["break_start_dt"].timetz())
                    break_end_on_slot_day = datetime.combine(slot_start.date(), doc["break_end_dt"].timetz())
                    
                    if doc["break_end_dt"].date() > doc["break_start_dt"].date(): # Break crosses midnight relative to shift start day
                        break_end_on_slot_day += timedelta(days=1)

                    is_on_break = (break_start_on_slot_day < slot_end and break_end_on_slot_day > slot_start)


                # Check if doctor is on shift during this slot
                # A doctor is on shift during an hour slot if the slot overlaps with their shift time range.
                is_on_shift = (doc["start_dt"] < slot_end and doc["end_dt"] > slot_start)

                # Only add doctor if they're on shift and not on break during this specific hour slot
                if is_on_shift and not is_on_break:
                    doctors_by_hour[slot_start].append(doc)


    # Fetch all RVU rows for all doctors (consider filtering this too based on doctors_on_shift for efficiency)
    rvu_res = supabase.table("rad_avg_monthly_rvu").select("*").execute()
    rvu_rows = {row["radiologist_id"]: row for row in (rvu_res.data or [])}

    # Build hourly_rvu_stats: {slot_datetime: {"historical": val, "current": val}}
    all_hour_slots = [slot for day_slots in hour_slots_by_day.values() for slot in day_slots]

    # 1. Batch calculate all previous date/hour lookups
    prev_dates_hours_map = {}
    for slot in all_hour_slots:
        prev_date_str, prev_hour_int = get_prev_month_same_dow_and_hour(slot["datetime"])
        if prev_date_str is not None:
            prev_dates_hours_map[(slot["datetime"], (prev_date_str, prev_hour_int))] = True

    # Extract unique (date, hour) combinations
    unique_prev_keys = list({pair for _, pair in prev_dates_hours_map.keys()})

    # 2. Bulk fetch from Supabase
    historical_rvu_rows = supabase.table("capacity_per_hour")\
        .select("date", "hour", "total_rvus")\
        .in_("date", [d for d, _ in unique_prev_keys])\
        .in_("hour", [h for _, h in unique_prev_keys])\
        .execute()

    # 3. Build lookup dictionary
    historical_rvu_lookup = {
        (row["date"], int(row["hour"])): row["total_rvus"]
        for row in (historical_rvu_rows.data or [])
    }

    # 4. Calculate final hourly_rvu_stats
    hourly_rvu_stats = {}
    for slot in all_hour_slots:
        slot_dt = slot["datetime"]
        prev_date_str, prev_hour_int = get_prev_month_same_dow_and_hour(slot_dt)
        historical_rvu = None
        if prev_date_str is not None:
            historical_rvu = historical_rvu_lookup.get((prev_date_str, prev_hour_int))

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

    # Filter out hour slots where there are no doctors scheduled AND no RVU data exists
    # Group and sort hour slots by day, then by RVU ratio within the day
    # Then, group slots within each day by their calculated background color class
    weekly_data_by_day_and_color = {} # Key: day (date object), Value: { color_class: [slot, slot, ...]}
    for day, hour_slots in hour_slots_by_day.items():
        # Filter slots for the current day
        filtered_day_slots = [
            slot for slot in hour_slots 
            if doctors_by_hour.get(slot["datetime"]) or 
               (hourly_rvu_stats.get(slot["datetime"]) and (hourly_rvu_stats[slot["datetime"]]['current'] is not None or hourly_rvu_stats[slot["datetime"]]['historical'] is not None))
        ]

        # Define sort key for slots within the day (by ratio)
        def sort_key(slot):
            stats = hourly_rvu_stats.get(slot["datetime"])
            if not stats or stats["historical"] is None or stats["historical"] <= 0:
                if not stats or stats["current"] is None:
                     return -2
                return -1
            if stats["current"] is None:
                 return -1

            return (stats["current"] / stats["historical"])

        # Sort slots for the current day by ratio
        sorted_day_slots = sorted(filtered_day_slots, key=sort_key)
        
        # Group sorted slots by background color class
        grouped_slots_by_color = defaultdict(list)
        for slot in sorted_day_slots:
             stats = hourly_rvu_stats.get(slot["datetime"])
             current = stats['current'] if stats else None
             expected = stats['historical'] if stats else None
             ratio = (current / expected) if current is not None and expected and expected > 0 else None
             color_class = get_rvu_bg_color_class(ratio)
             grouped_slots_by_color[color_class].append(slot)

        # Add to the weekly data if there are any slots for this day
        if grouped_slots_by_color:
             weekly_data_by_day_and_color[day] = dict(grouped_slots_by_color) # Convert defaultdict to dict for template

    # Sort the days of the week (dictionary keys are date objects)
    sorted_days = sorted(weekly_data_by_day_and_color.keys())
    sorted_weekly_data_by_day_and_color = {day: weekly_data_by_day_and_color[day] for day in sorted_days}

    # Fetch all certifications for doctors scheduled this week
    doctor_ids = list({doc['id'] for doc in doctors_on_shift})
    cert_res = supabase.table("certifications").select("radiologist_id,state").in_("radiologist_id", doctor_ids).execute()
    certifications = cert_res.data or []
    # Build a mapping: doctor_id -> set(states)
    doctor_states = {}
    for cert in certifications:
        rid = str(cert['radiologist_id']).strip()  # Ensure string and trimmed
        state = cert['state']
        if rid not in doctor_states:
            doctor_states[rid] = set()
        if state:
            doctor_states[rid].add(state.strip().title())  # Normalize state name

    # For each hour slot, compute uncovered states
    uncovered_states_by_hour = {}
    for slot in all_hour_slots:
        slot_doctors = doctors_by_hour.get(slot['datetime'], [])
        covered_states = set()
        for doc in slot_doctors:
            doc_id = str(doc['id']).strip()  # Ensure string and trimmed
            covered_states.update(doctor_states.get(doc_id, set()))
        uncovered = sorted(set(US_STATES) - covered_states)
        uncovered_states_by_hour[slot['datetime'].isoformat()] = uncovered

    # For each hour slot, compute covered states as well
    covered_states_by_hour = {}
    for slot in all_hour_slots:
        uncovered = uncovered_states_by_hour[slot['datetime'].isoformat()]
        covered = sorted(set(US_STATES) - set(uncovered))
        covered_states_by_hour[slot['datetime'].isoformat()] = covered

    # For each hour slot, build a mapping: state name -> list of doctor names who cover that state
    state_doctor_map_by_hour = {}
    for slot in all_hour_slots:
        slot_dt = slot['datetime']
        slot_doctors = doctors_by_hour.get(slot_dt, [])  # Use datetime object
        state_doctor_map = {}

        for doc in slot_doctors:
            doc_states = doctor_states.get(str(doc['id']).strip(), set())
            for state in doc_states:
                name = doc.get('name')
                if name:
                    state_doctor_map.setdefault(state, []).append(str(name).strip())

        # Store under the string key
        state_doctor_map_by_hour[slot_dt.isoformat()] = state_doctor_map
    

        # Build mapping: facility name -> list of doctor names per hour
    # Get all doctor-facility assignments


    facility_assignments_data = fetch_all_rows("doctor_facility_assignments", "radiologist_id, facilities(name)")
    facility_map = defaultdict(list)
    for row in facility_assignments_data or []:
        rad_id = str(row["radiologist_id"]).strip()
        facility_name = row.get("facilities", {}).get("name")
        if rad_id and facility_name:
            facility_map[rad_id].append(facility_name.strip())

    
    # Step 1: Get all facility names
    all_facilities_res = supabase.table("facilities").select("name").execute()
    all_facility_names = sorted([
        f["name"].strip() for f in (all_facilities_res.data or []) if f.get("name")
    ])

    # Step 2: Build full map with empty lists for uncovered facilities
    facility_doctor_map_by_hour = {}
    for slot in all_hour_slots:
        slot_dt = slot["datetime"]
        slot_doctors = doctors_by_hour.get(slot_dt, [])
        fac_map = defaultdict(list)

        for doc in slot_doctors:
            doc_id = str(doc["id"]).strip()
            doc_name = doc.get("name", "").strip()
            for fac in facility_map.get(doc_id, []):
                fac_map[fac].append(doc_name)

        # Now include *all* facilities, even if uncovered
        complete_map = {fac: fac_map.get(fac, []) for fac in all_facility_names}
        facility_doctor_map_by_hour[slot_dt.isoformat()] = complete_map


    return render_template('shifts.html', 
                           weekly_data_by_day_and_color=sorted_weekly_data_by_day_and_color, # Pass grouped and sorted data
                           hourly_rvu_stats=hourly_rvu_stats,
                           start_date=start_of_week.strftime("%B %d, %Y"), # Pass week start date for header
                           end_date=end_of_week.strftime("%B %d, %Y"), # Pass week end date for header
                           doctors_by_hour=doctors_by_hour,
                           uncovered_states_by_hour=uncovered_states_by_hour,
                           covered_states_by_hour=covered_states_by_hour,
                           state_doctor_map_by_hour=state_doctor_map_by_hour,
                           facility_doctor_map_by_hour=facility_doctor_map_by_hour,
                           datetime=datetime
) 