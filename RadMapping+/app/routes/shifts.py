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

# not being used 
# def get_prev_month_same_dow_and_hour(dt):
#     year = dt.year
#     month = dt.month
#     day = dt.day
#     hour = dt.hour
#     if month == 1:
#         prev_month = 12
#         prev_year = year - 1
#     else:
#         prev_month = month - 1
#         prev_year = year
#     first_day_prev_month = datetime(prev_year, prev_month, 1)
#     days_in_prev_month = monthrange(prev_year, prev_month)[1]
#     candidates = []
#     for d in range(1, days_in_prev_month + 1):
#         candidate = datetime(prev_year, prev_month, d)
#         if candidate.weekday() == dt.weekday():
#             candidates.append(candidate)
#     if not candidates:
#         return None, hour
#     week_of_month = (dt.day - 1) // 7
#     if week_of_month < len(candidates):
#         chosen = candidates[week_of_month]
#     else:
#         chosen = candidates[-1]
#     return chosen.date().isoformat(), hour

# Helper: Get latest non-zero monthly RVU for a doctor
def get_latest_nonzero_rvu(rvu_row):
    months = ["dec", "nov", "oct", "sep", "aug", "jul", "jun", "may", "apr", "mar", "feb", "jan"]
    for m in months:
        val = rvu_row.get(m)
        if val is not None and val != 0:
            return val
    return 0

def get_rvu_bg_color_class(ratio):
    if ratio is not None:
        if ratio <= 0.6:
            return 'bg-red-100'
        elif ratio <= 0.9:
            return 'bg-yellow-100'
        else:
            return 'bg-green-100'
    return 'bg-gray-100' 
US_STATES = [
    'Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado', 'Connecticut', 'Delaware', 'Florida', 'Georgia',
    'Hawaii', 'Idaho', 'Illinois', 'Indiana', 'Iowa', 'Kansas', 'Kentucky', 'Louisiana', 'Maine', 'Maryland', 'Massachusetts',
    'Michigan', 'Minnesota', 'Mississippi', 'Missouri', 'Montana', 'Nebraska', 'Nevada', 'New Hampshire', 'New Jersey',
    'New Mexico', 'New York', 'North Carolina', 'North Dakota', 'Ohio', 'Oklahoma', 'Oregon', 'Pennsylvania', 'Puerto Rico', 'Rhode Island',
    'South Carolina', 'South Dakota', 'Tennessee', 'Texas', 'Utah', 'Vermont', 'Virginia', 'Washington', 'West Virginia',
    'Wisconsin', 'Wyoming'
]

@shifts_bp.route('/shifts')
@with_supabase_auth
def shifts():
    supabase = get_supabase_client()
    
    date_str = request.args.get('date')
    if date_str:
        now = datetime.strptime(date_str, '%Y-%m-%d')
    else:
        now = datetime.now()
    
    start_of_week = now - timedelta(days=now.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    
    start_date_str = start_of_week.strftime("%Y-%m-%d")
    end_date_str = end_of_week.strftime("%Y-%m-%d")

    prev_week_start = (start_of_week - timedelta(weeks=1)).strftime('%Y-%m-%d')
    next_week_start = (start_of_week + timedelta(weeks=1)).strftime('%Y-%m-%d')

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
                "day_label": current_day.strftime("%A") 
            })
            current_hour += timedelta(hours=1)
        current_day += timedelta(days=1)
    query = supabase.table("monthly_schedule") \
        .select("*, radiologists(*)") \
        .lte("start_date", end_date_str) \
        .gte("end_date", start_date_str) 

    shift_res = query.execute()

    doctors_on_shift = []
    for entry in shift_res.data:
         if entry.get("radiologists") and entry.get("start_time") and entry.get("end_time"):
            doc = entry["radiologists"]
            
            start_date = entry.get("start_date") or start_date_str 
            end_date = entry.get("end_date") or end_date_str 

            try:
                shift_start_dt = datetime.strptime(f"{start_date} {entry['start_time']}", "%Y-%m-%d %H:%M:%S")
                shift_end_dt = datetime.strptime(f"{end_date} {entry['end_time']}", "%Y-%m-%d %H:%M:%S")
                if shift_end_dt < shift_start_dt:
                    shift_end_dt += timedelta(days=1) 

                break_start_dt = None
                break_end_dt = None
                if entry.get("break_start") and entry.get("break_end"):
                    break_start_dt_candidate = datetime.strptime(f"{start_date} {entry['break_start']}", "%Y-%m-%d %H:%M:%S")
                    break_end_dt_candidate = datetime.strptime(f"{start_date} {entry['break_end']}", "%Y-%m-%d %H:%M:%S")
                    if break_end_dt_candidate < break_start_dt_candidate:
                         break_end_dt_candidate += timedelta(days=1) 

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
                full_doc_info = doc.copy()
                full_doc_info.update(doc_schedule_details)
                doctors_on_shift.append(full_doc_info)

            except Exception as e:
                print(f"Error parsing datetime for doc {doc.get('name', 'Unknown')}: {e}")

    doctors_by_hour = defaultdict(list) 
    for doc in doctors_on_shift:
        for day, hour_slots in hour_slots_by_day.items():
            for slot in hour_slots:
                slot_start = slot["datetime"]
                slot_end = slot_start + timedelta(hours=1)
                
                is_on_break = False
                if doc.get("break_start_dt") and doc.get("break_end_dt"):
                    
                    break_start_on_slot_day = datetime.combine(slot_start.date(), doc["break_start_dt"].timetz())
                    break_end_on_slot_day = datetime.combine(slot_start.date(), doc["break_end_dt"].timetz())
                    
                    if doc["break_end_dt"].date() > doc["break_start_dt"].date(): 
                        break_end_on_slot_day += timedelta(days=1)

                    is_on_break = (break_start_on_slot_day < slot_end and break_end_on_slot_day > slot_start)

                is_on_shift = (doc["start_dt"] < slot_end and doc["end_dt"] > slot_start)

                if is_on_shift and not is_on_break:
                    doctors_by_hour[slot_start].append(doc)


    rvu_res = supabase.table("rad_avg_monthly_rvu").select("*").execute()
    rvu_rows = {row["radiologist_id"]: row for row in (rvu_res.data or [])}

    all_hour_slots = [slot for day_slots in hour_slots_by_day.values() for slot in day_slots]

    prev_dates_hours_map = {}
    for slot in all_hour_slots:
        prev_date_str, prev_hour_int = get_prev_week_same_day_and_hour(slot["datetime"])
        if prev_date_str is not None:
            prev_dates_hours_map[(slot["datetime"], (prev_date_str, prev_hour_int))] = True

    unique_prev_keys = list({pair for _, pair in prev_dates_hours_map.keys()})

    historical_rvu_rows = supabase.table("capacity_per_hour")\
        .select("date", "hour", "total_rvus")\
        .in_("date", [d for d, _ in unique_prev_keys])\
        .in_("hour", [h for _, h in unique_prev_keys])\
        .execute()

    historical_rvu_lookup = {
        (row["date"], int(row["hour"])): row["total_rvus"]
        for row in (historical_rvu_rows.data or [])
    }

    hourly_rvu_stats = {}
    for slot in all_hour_slots:
        slot_dt = slot["datetime"]
        prev_date_str, prev_hour_int = get_prev_week_same_day_and_hour(slot_dt)
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

    weekly_data_by_day_and_color = {} 
    for day, hour_slots in hour_slots_by_day.items():
        filtered_day_slots = [
            slot for slot in hour_slots 
            if doctors_by_hour.get(slot["datetime"]) or 
               (hourly_rvu_stats.get(slot["datetime"]) and (hourly_rvu_stats[slot["datetime"]]['current'] is not None or hourly_rvu_stats[slot["datetime"]]['historical'] is not None))
        ]

        def sort_key(slot):
            stats = hourly_rvu_stats.get(slot["datetime"])
            if not stats or stats["historical"] is None or stats["historical"] <= 0:
                if not stats or stats["current"] is None:
                     return -2
                return -1
            if stats["current"] is None:
                 return -1

            return (stats["current"] / stats["historical"])

        sorted_day_slots = sorted(filtered_day_slots, key=sort_key)
        
        grouped_slots_by_color = defaultdict(list)
        for slot in sorted_day_slots:
             stats = hourly_rvu_stats.get(slot["datetime"])
             current = stats['current'] if stats else None
             expected = stats['historical'] if stats else None
             ratio = (current / expected) if current is not None and expected and expected > 0 else None
             color_class = get_rvu_bg_color_class(ratio)
             grouped_slots_by_color[color_class].append(slot)

        if grouped_slots_by_color:
             weekly_data_by_day_and_color[day] = dict(grouped_slots_by_color) 
    sorted_days = sorted(weekly_data_by_day_and_color.keys())
    sorted_weekly_data_by_day_and_color = {day: weekly_data_by_day_and_color[day] for day in sorted_days}

    doctor_ids = list({doc['id'] for doc in doctors_on_shift})
    cert_res = supabase.table("certifications").select("radiologist_id,state").in_("radiologist_id", doctor_ids).execute()
    certifications = cert_res.data or []
    doctor_states = {}
    for cert in certifications:
        rid = str(cert['radiologist_id']).strip()  
        state = cert['state']
        if rid not in doctor_states:
            doctor_states[rid] = set()
        if state:
            doctor_states[rid].add(state.strip().title())  

    uncovered_states_by_hour = {}
    for slot in all_hour_slots:
        slot_doctors = doctors_by_hour.get(slot['datetime'], [])
        covered_states = set()
        for doc in slot_doctors:
            doc_id = str(doc['id']).strip()  # Ensure string and trimmed
            covered_states.update(doctor_states.get(doc_id, set()))
        uncovered = sorted(set(US_STATES) - covered_states)
        uncovered_states_by_hour[slot['datetime'].isoformat()] = uncovered

    covered_states_by_hour = {}
    for slot in all_hour_slots:
        uncovered = uncovered_states_by_hour[slot['datetime'].isoformat()]
        covered = sorted(set(US_STATES) - set(uncovered))
        covered_states_by_hour[slot['datetime'].isoformat()] = covered

    state_doctor_map_by_hour = {}
    for slot in all_hour_slots:
        slot_dt = slot['datetime']
        slot_doctors = doctors_by_hour.get(slot_dt, []) 
        state_doctor_map = {}

        for doc in slot_doctors:
            doc_states = doctor_states.get(str(doc['id']).strip(), set())
            for state in doc_states:
                name = doc.get('name')
                if name:
                    state_doctor_map.setdefault(state, []).append(str(name).strip())

        state_doctor_map_by_hour[slot_dt.isoformat()] = state_doctor_map


    facility_assignments_data = fetch_all_rows("doctor_facility_assignments", "radiologist_id, can_read, facilities(name)")

    facility_map = defaultdict(list)
    for row in facility_assignments_data:
        if str(row.get("can_read")).strip().lower() != "true":
            continue 

        rad_id = str(row["radiologist_id"]).strip()
        facility_name = row.get("facilities", {}).get("name")
        if rad_id and facility_name:
            facility_map[rad_id].append(facility_name.strip())

    all_facilities_res = supabase.table("facilities").select("name").execute()
    all_facility_names = sorted([
        f["name"].strip() for f in (all_facilities_res.data or []) if f.get("name")
    ])

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

        complete_map = {fac: fac_map.get(fac, []) for fac in all_facility_names}
        facility_doctor_map_by_hour[slot_dt.isoformat()] = complete_map


    return render_template('shifts.html', 
                           weekly_data_by_day_and_color=sorted_weekly_data_by_day_and_color, 
                           hourly_rvu_stats=hourly_rvu_stats,
                           start_date=start_of_week.strftime("%B %d, %Y"),
                           end_date=end_of_week.strftime("%B %d, %Y"), 
                           prev_week_start=prev_week_start,
                           next_week_start=next_week_start,
                           doctors_by_hour=doctors_by_hour,
                           uncovered_states_by_hour=uncovered_states_by_hour,
                           covered_states_by_hour=covered_states_by_hour,
                           state_doctor_map_by_hour=state_doctor_map_by_hour,
                           facility_doctor_map_by_hour=facility_doctor_map_by_hour,
                           datetime=datetime,
                           now=now
)