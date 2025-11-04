# RadMapping+/app/routes/shifts.py

from flask import Blueprint, render_template, session, request, jsonify
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


@shifts_bp.route('/shifts/hour_detail')
@with_supabase_auth
def hour_detail():
    """
    Returns granular demand for a given date/hour from facility_capacity_per_hour
    along with scheduled coverage (doctors on shift who can read by facility/state).

    Query params:
      - date: YYYY-MM-DD
      - hour: 0-23
    """
    supabase = get_supabase_client()

    date_str = request.args.get('date')
    hour = request.args.get('hour', type=int)
    if not date_str or hour is None:
        return jsonify({"error": "Missing date or hour"}), 400

    # 1) Facility-level demand for this hour (EXPECTED = previous week's same day/hour)
    prev_date_str, prev_hour_int = get_prev_week_same_day_and_hour(
        datetime.strptime(f"{date_str} {hour:02d}:00:00", "%Y-%m-%d %H:%M:%S")
    )
    print(f"[hour_detail] incoming date={date_str} hour={hour}; expected_source date={prev_date_str} hour={prev_hour_int}")
    fcap_res = (
        supabase
        .table("facility_capacity_per_hour")
        .select("facility_id,total_rvus,modality")
        .eq("date", prev_date_str)
        .eq("hour", prev_hour_int)
        .execute()
    )
    facility_rows = fcap_res.data or []
    print(f"[hour_detail] facility_capacity_per_hour rows: {len(facility_rows)}")

    # Potential fallback: if no rows for the exact hour, try the nearest hour on the same prior-week date,
    # and scale the distribution to the expected total from capacity_per_hour for the requested hour.
    fallback_info = {"used": False}
    if not facility_rows:
        print("[hour_detail] No facility rows found for expected prior-week HOUR. Attempting nearest-hour fallback on same date…")

        # Fetch day data and group by hour
        day_res = (
            supabase
            .table("facility_capacity_per_hour")
            .select("facility_id,total_rvus,modality,hour")
            .eq("date", prev_date_str)
            .execute()
        )
        day_rows = day_res.data or []
        print(f"[hour_detail] Fallback day rows on {prev_date_str}: {len(day_rows)}")

        by_hour = defaultdict(list)
        for r in day_rows:
            try:
                by_hour[int(r.get("hour"))].append(r)
            except Exception:
                continue

        if by_hour:
            hours_available = sorted(by_hour.keys())
            nearest_hour = min(hours_available, key=lambda h: abs(h - prev_hour_int))
            facility_rows = by_hour.get(nearest_hour, [])
            fallback_info = {"used": True, "source": {"date": prev_date_str, "hour": nearest_hour}, "reason": "nearest_hour_same_date"}
            print(f"[hour_detail] Fallback using nearest hour {nearest_hour} with {len(facility_rows)} rows.")
        else:
            print("[hour_detail] No facility rows for any hour on the prior-week date; returning empty payload.")
            return jsonify({
                "date": date_str,
                "hour": hour,
                "expected_source": {"date": prev_date_str, "hour": prev_hour_int},
                "fallback": {"used": False, "reason": "no_rows_on_date"},
                "total_expected_rvus": 0,
                "facilities": [],
                "by_state": [],
                "supply_overall_rvus": 0,
                "supply_licensed_rvus": 0,
                "supply_facility_authorized_rvus": 0
            })

    facility_ids = list({row["facility_id"] for row in facility_rows if row.get("facility_id")})

    # 2) Facility metadata (name, state/location)
    fac_meta = {}
    if facility_ids:
        fac_res = (
            supabase
            .table("facilities")
            .select("id,name,location")
            .in_("id", facility_ids)
            .execute()
        )
        for r in (fac_res.data or []):
            fac_meta[r["id"]] = {"name": r.get("name"), "state": r.get("location")}
        print(f"[hour_detail] facilities meta fetched: {len(fac_meta)} for {len(facility_ids)} ids")

    # 3) Determine doctors on shift for this specific hour
    #    Reuse the same logic as the weekly view but constrained to one hour window
    window_start = datetime.strptime(f"{date_str} {hour:02d}:00:00", "%Y-%m-%d %H:%M:%S")
    window_end = window_start + timedelta(hours=1)

    sched_q = (
        supabase
        .table("monthly_schedule")
        .select("*, radiologists(*)")
        .lte("start_date", date_str)
        .gte("end_date", date_str)
    )
    sched_res = sched_q.execute()
    print(f"[hour_detail] schedule rows in date range: {len(sched_res.data or [])}")

    on_shift = []
    for entry in (sched_res.data or []):
        try:
            if not (entry.get("radiologists") and entry.get("start_time") and entry.get("end_time")):
                continue
            doc = entry["radiologists"].copy()
            start_date = entry.get("start_date") or date_str
            end_date = entry.get("end_date") or date_str
            shift_start_dt = datetime.strptime(f"{start_date} {entry['start_time']}", "%Y-%m-%d %H:%M:%S")
            shift_end_dt = datetime.strptime(f"{end_date} {entry['end_time']}", "%Y-%m-%d %H:%M:%S")
            if shift_end_dt < shift_start_dt:
                shift_end_dt += timedelta(days=1)

            break_start_dt = None
            break_end_dt = None
            if entry.get("break_start") and entry.get("break_end"):
                bstart = datetime.strptime(f"{start_date} {entry['break_start']}", "%Y-%m-%d %H:%M:%S")
                bend = datetime.strptime(f"{start_date} {entry['break_end']}", "%Y-%m-%d %H:%M:%S")
                if bend < bstart:
                    bend += timedelta(days=1)
                break_start_dt, break_end_dt = bstart, bend

            is_on_break = False
            if break_start_dt and break_end_dt:
                # Map break times onto the hour window's day
                bstart_on_day = datetime.combine(window_start.date(), break_start_dt.timetz())
                bend_on_day = datetime.combine(window_start.date(), break_end_dt.timetz())
                if bend_on_day < bstart_on_day:
                    bend_on_day += timedelta(days=1)
                is_on_break = (bstart_on_day < window_end and bend_on_day > window_start)

            is_on_shift = (shift_start_dt < window_end and shift_end_dt > window_start)

            if is_on_shift and not is_on_break:
                doc.update({
                    "_start_dt": shift_start_dt,
                    "_end_dt": shift_end_dt
                })
                on_shift.append(doc)
        except Exception:
            continue

    doctor_ids = [d.get("id") for d in on_shift if d.get("id") is not None]

    # 4) RVU supply numbers based on monthly averages (same logic as page)
    rvu_res = supabase.table("rad_avg_monthly_rvu").select("*").execute()
    rvu_rows = {row["radiologist_id"]: row for row in (rvu_res.data or [])}

    def latest_nonzero_rvu(rvu_row):
        months = ["dec", "nov", "oct", "sep", "aug", "jul", "jun", "may", "apr", "mar", "feb", "jan"]
        for m in months:
            val = rvu_row.get(m)
            if val is not None and val != 0:
                return val
        return 0

    supply_overall = 0
    for d in on_shift:
        rr = rvu_rows.get(d.get("id"))
        if rr:
            supply_overall += latest_nonzero_rvu(rr)

    # 5) Facility and state authorization among scheduled doctors
    facility_authorized_ids = set()
    from collections import defaultdict as _dd
    fac_auth_map = _dd(set)
    if doctor_ids and facility_ids:
        dfa_res = (
            supabase
            .table("doctor_facility_assignments")
            .select("radiologist_id,facility_id,can_read")
            .in_("radiologist_id", doctor_ids)
            .in_("facility_id", facility_ids)
            .execute()
        )
        print(f"[hour_detail] doctor_facility_assignments rows: {len(dfa_res.data or [])}")
        for row in (dfa_res.data or []):
            can_read_val = str(row.get("can_read")).strip().lower()
            if can_read_val == "true" or can_read_val == "1" or can_read_val == "t":
                rid = row.get("radiologist_id")
                fid = row.get("facility_id")
                if rid is not None and fid in fac_auth_map:
                    fac_auth_map[fid].add(rid)
                    facility_authorized_ids.add(rid)

    supply_facility_auth = 0
    for d in on_shift:
        if d.get("id") in facility_authorized_ids:
            rr = rvu_rows.get(d.get("id"))
            if rr:
                supply_facility_auth += latest_nonzero_rvu(rr)

    # Helper to normalize facility/cert state values to 2-letter codes
    STATE_NAME_TO_CODE = {
        'Alabama':'AL','Alaska':'AK','Arizona':'AZ','Arkansas':'AR','California':'CA','Colorado':'CO','Connecticut':'CT','Delaware':'DE','Florida':'FL','Georgia':'GA',
        'Hawaii':'HI','Idaho':'ID','Illinois':'IL','Indiana':'IN','Iowa':'IA','Kansas':'KS','Kentucky':'KY','Louisiana':'LA','Maine':'ME','Maryland':'MD','Massachusetts':'MA',
        'Michigan':'MI','Minnesota':'MN','Mississippi':'MS','Missouri':'MO','Montana':'MT','Nebraska':'NE','Nevada':'NV','New Hampshire':'NH','New Jersey':'NJ','New Mexico':'NM',
        'New York':'NY','North Carolina':'NC','North Dakota':'ND','Ohio':'OH','Oklahoma':'OK','Oregon':'OR','Pennsylvania':'PA','Rhode Island':'RI','South Carolina':'SC',
        'South Dakota':'SD','Tennessee':'TN','Texas':'TX','Utah':'UT','Vermont':'VT','Virginia':'VA','Washington':'WA','West Virginia':'WV','Wisconsin':'WI','Wyoming':'WY',
        'Puerto Rico':'PR','District Of Columbia':'DC','District of Columbia':'DC'
    }
    def to_state_code(val):
        if not val:
            return None
        s = str(val).strip()
        if not s:
            return None
        if len(s) == 2:
            return s.upper()
        return STATE_NAME_TO_CODE.get(s.title(), s.upper())

    # States covered by scheduled doctors
    states_needed = list({to_state_code(fac_meta.get(fid, {}).get("state")) for fid in facility_ids if fac_meta.get(fid, {}).get("state")})
    licensed_ids = set()
    licensed_by_state = defaultdict(set)
    if doctor_ids and states_needed:
        cert_res = (
            supabase
            .table("certifications")
            .select("radiologist_id,state")
            .in_("radiologist_id", doctor_ids)
            .in_("state", states_needed)
            .execute()
        )
        print(f"[hour_detail] certifications rows (filtered to states with demand): {len(cert_res.data or [])}")
        for c in (cert_res.data or []):
            rid = c.get("radiologist_id")
            st = to_state_code(c.get("state"))
            if rid is not None:
                licensed_ids.add(rid)
                if st:
                    licensed_by_state[st].add(rid)

    supply_licensed = 0
    for d in on_shift:
        if d.get("id") in licensed_ids:
            rr = rvu_rows.get(d.get("id"))
            if rr:
                supply_licensed += latest_nonzero_rvu(rr)

    # 6) Assemble facility/state breakdowns
    # Aggregate facilities by facility only; keep per-modality breakdown under each
    facilities_agg = {}
    state_totals = defaultdict(float)
    for row in facility_rows:
        fid = row.get("facility_id")
        expected = float(row.get("total_rvus") or 0)
        modality = row.get("modality")
        meta = fac_meta.get(fid, {})
        state = to_state_code(meta.get("state"))
        state_totals[state] += expected
        if fid not in facilities_agg:
            # Readers count: authorized AND licensed for the facility state
            auth_set = fac_auth_map.get(fid, set())
            lic_set = licensed_by_state.get(state, set()) if state else set()
            readers_count = len(auth_set & lic_set) if auth_set else 0

            facilities_agg[fid] = {
                "facility_id": fid,
                "facility_name": meta.get("name"),
                "state": state,
                "expected_rvus": 0.0,
                "scheduled_reader_count": readers_count,
                "modalities": {}
            }
        facilities_agg[fid]["expected_rvus"] += expected
        if modality:
            facilities_agg[fid]["modalities"][modality] = facilities_agg[fid]["modalities"].get(modality, 0.0) + expected

    # Convert modality dicts to lists for JSON friendliness
    facilities_payload = []
    for fac in facilities_agg.values():
        fac_copy = fac.copy()
        fac_copy["modalities"] = [
            {"modality": m, "expected_rvus": v} for m, v in fac.get("modalities", {}).items()
        ]
        facilities_payload.append(fac_copy)

    # Build state+modality breakdown
    by_state_mod = defaultdict(float)
    by_modality_totals = defaultdict(float)
    by_state_totals = defaultdict(float)
    state_breakdown = defaultdict(lambda: defaultdict(float))
    modality_breakdown = defaultdict(lambda: defaultdict(float))
    for row in facility_rows:
        fid = row.get("facility_id")
        expected = float(row.get("total_rvus") or 0)
        modality = row.get("modality")
        meta = fac_meta.get(fid, {})
        state = to_state_code(meta.get("state"))
        key = (state, modality)
        by_state_mod[key] += expected
        if modality:
            by_modality_totals[modality] += expected
        if state:
            by_state_totals[state] += expected
        if state and modality:
            state_breakdown[state][modality] += expected
            modality_breakdown[modality][state] += expected

    by_state_payload = []  # legacy: state+modality (no longer used by UI)
    for (st, mod), total in by_state_mod.items():
        by_state_payload.append({
            "state": st,
            "modality": mod,
            "expected_rvus": float(total)
        })

    by_state_merged_payload = [
        {"state": st, "expected_rvus": float(total)} for st, total in by_state_totals.items()
    ]
    by_modality_payload = [
        {"modality": m, "expected_rvus": float(v)} for m, v in by_modality_totals.items()
    ]

    # If we used fallback from a different hour, optionally scale to match the expected total
    # from capacity_per_hour for the requested hour.
    total_expected = float(sum((float(r.get("total_rvus") or 0) for r in facility_rows)))
    if fallback_info.get("used"):
        # Fetch tile expected from capacity_per_hour for prev_date_str/prev_hour_int
        cap_row = (
            supabase
            .table("capacity_per_hour")
            .select("total_rvus")
            .eq("date", prev_date_str)
            .eq("hour", prev_hour_int)
            .execute()
        )
        cap_total = None
        if cap_row.data:
            try:
                cap_total = float((cap_row.data or [{}])[0].get("total_rvus") or 0)
            except Exception:
                cap_total = None
        print(f"[hour_detail] Tile expected (capacity_per_hour) for scaling: {cap_total}")
        if cap_total is not None and total_expected > 0:
            scale = cap_total / total_expected
            print(f"[hour_detail] Applying scale factor {scale:.4f} to fallback facility rows")
            for f in facilities_payload:
                f["expected_rvus"] = float(f.get("expected_rvus", 0)) * scale
                for md in f.get("modalities", []):
                    md["expected_rvus"] = float(md.get("expected_rvus", 0)) * scale
            for s in by_state_payload:
                s["expected_rvus"] = float(s["expected_rvus"]) * scale
            for s in by_state_merged_payload:
                s["expected_rvus"] = float(s["expected_rvus"]) * scale
            for m in by_modality_payload:
                m["expected_rvus"] = float(m["expected_rvus"]) * scale
            # Scale breakdown maps
            for st, mods in state_breakdown.items():
                for md in list(mods.keys()):
                    mods[md] = float(mods[md]) * scale
            for md, states in modality_breakdown.items():
                for st in list(states.keys()):
                    states[st] = float(states[st]) * scale
            total_expected = cap_total
            fallback_info["scaled_to_expected"] = True
            fallback_info["scale_factor"] = scale
        else:
            fallback_info["scaled_to_expected"] = False

    # Convert breakdown dicts to lists for JSON friendliness
    state_breakdown_list = {
        st: [
            {"modality": md, "expected_rvus": float(val)} for md, val in mods.items()
        ]
        for st, mods in state_breakdown.items()
    }
    modality_breakdown_list = {
        md: [
            {"state": st, "expected_rvus": float(val)} for st, val in states.items()
        ]
        for md, states in modality_breakdown.items()
    }

    payload = {
        "date": date_str,
        "hour": hour,
        "expected_source": {"date": prev_date_str, "hour": prev_hour_int},
        "fallback": fallback_info,
        "total_expected_rvus": total_expected,
        "facilities": facilities_payload,
        "by_state": by_state_payload,
        "by_state_merged": by_state_merged_payload,
        "by_modality": by_modality_payload,
        "state_breakdown": state_breakdown_list,
        "modality_breakdown": modality_breakdown_list,
        "supply_overall_rvus": supply_overall,
        "supply_licensed_rvus": supply_licensed,
        "supply_facility_authorized_rvus": supply_facility_auth
    }
    print(f"[hour_detail] response summary: expected={total_expected:.2f}, facilities={len(facilities_payload)}, states={len(by_state_payload)}, on_shift={len(on_shift)}")
    return jsonify(payload)
