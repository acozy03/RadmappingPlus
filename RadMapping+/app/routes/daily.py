from flask import Blueprint, render_template, session, request, jsonify
from app.supabase_client import get_supabase_client
from app.middleware import with_supabase_auth
from datetime import datetime, timedelta, timezone
from calendar import monthrange
from collections import defaultdict
import re
from app.schedule_sync import run_google_sheet_sync

daily_bp = Blueprint('daily', __name__)

def parse_time(base_date_str, time_str):
    for fmt in ("%Y-%m-%d %I%p", "%Y-%m-%d %I:%M%p", "%Y-%m-%d %I%M%p"):
        try:
            return datetime.strptime(f"{base_date_str} {time_str.upper()}", fmt)
        except ValueError:
            continue
    raise ValueError(f"Invalid time format: {time_str}")


def extract_prn_ranges(schedule_str, base_date_str):
    prn_ranges = []

    # Normalize newlines and em/en dashes
    normalized_str = schedule_str.replace('\n', ' ').replace('–', '-').replace('—', '-')

    # Find PRN blocks
    prn_blocks = re.findall(r'\(.*?PRN.*?\)', normalized_str, re.IGNORECASE)
    for block in prn_blocks:
        times = re.findall(r'(\d{1,2}(?::\d{2})?\s*[apAP][mM])', block)
        if len(times) % 2 == 0:
            for i in range(0, len(times), 2):
                try:
                    start = parse_time(base_date_str, times[i])
                    end = parse_time(base_date_str, times[i+1])
                    if end <= start:
                        end += timedelta(days=1)
                    prn_ranges.append((start, end))
                except Exception as e:
                    print(f"❌ Failed to parse PRN time range ({times[i]}–{times[i+1]}):", str(e))
    return prn_ranges


@daily_bp.route('/daily')
@with_supabase_auth
def daily():
    supabase = get_supabase_client()
    user = session.get("user")

    date_str = request.args.get("date", None)
    

    try:
        today_date = (
            datetime.strptime(date_str, "%Y-%m-%d").date()
            if date_str else
            datetime.now(timezone.utc).date()
        )
    except Exception as e:
        print(f"[⚠️] Invalid date_str format: {e}. Defaulting to today.")
        today_date = datetime.now(timezone.utc).date()

    today = today_date.strftime("%Y-%m-%d")
    prev_date = (today_date - timedelta(days=1)).strftime("%Y-%m-%d")
    next_date = (today_date + timedelta(days=1)).strftime("%Y-%m-%d")
    base_date = datetime.combine(today_date, datetime.min.time())
    max_end_dt = base_date


    # ✅ 2. Fetch today's shifts
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

                # Optional: handle break times
                break_start_dt, break_end_dt = None, None
                if entry.get("break_start") and entry.get("break_end"):
                    break_start_dt = datetime.strptime(f"{start_date} {entry['break_start']}", "%Y-%m-%d %H:%M:%S")
                    break_end_dt = datetime.strptime(f"{start_date} {entry['break_end']}", "%Y-%m-%d %H:%M:%S")
                    if break_end_dt < break_start_dt:
                        break_end_dt += timedelta(days=1)

                doc.update({
                    "start_time": entry["start_time"],
                    "end_time": entry["end_time"],
                    "schedule_details": entry.get("schedule_details", ""),
                    "start_date": start_date,
                    "end_date": end_date,
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                    "break_start_dt": break_start_dt,
                    "break_end_dt": break_end_dt
                })
                doc["prn_ranges"] = extract_prn_ranges(doc.get("schedule_details", ""), start_date)

                doctors_on_shift.append(doc)
                if end_dt > max_end_dt:
                    max_end_dt = end_dt
            except Exception as e:
                print(f"[❌] Error parsing shift time for doc {doc.get('name', 'Unknown')}: {e}")

        elif entry.get("radiologists"):
            doc = entry["radiologists"]
            start_date = entry.get("start_date") or today
            doc.update({
                "schedule_details": entry.get("schedule_details", ""),
                "start_date": start_date,
                "end_date": entry.get("end_date") or today,
                "start_dt": None,
                "end_dt": None,
                "break_start_dt": None,
                "break_end_dt": None
            })
            doc["prn_ranges"] = extract_prn_ranges(doc.get("schedule_details", ""), start_date)

            if doc["prn_ranges"]:  # ✅ Add only if it has PRN ranges
                doctors_on_shift.append(doc)

    # ✅ 3. Also include tomorrow's shifts that spill into today
    tomorrow_str = (today_date + timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow_shift_res = supabase.table("monthly_schedule") \
        .select("*, radiologists(*)") \
        .eq("start_date", tomorrow_str) \
        .execute()

    for entry in tomorrow_shift_res.data:
        if entry.get("radiologists") and entry.get("start_time") and entry.get("end_time"):
            doc = entry["radiologists"]
            try:
                start_dt = datetime.strptime(f"{tomorrow_str} {entry['start_time']}", "%Y-%m-%d %H:%M:%S")
                end_dt = datetime.strptime(f"{tomorrow_str} {entry['end_time']}", "%Y-%m-%d %H:%M:%S")
                if end_dt < start_dt:
                    end_dt += timedelta(days=1)
                if start_dt < max_end_dt:
                    doc.update({
                        "start_time": entry["start_time"],
                        "end_time": entry["end_time"],
                        "schedule_details": entry.get("schedule_details", ""),
                        "start_date": tomorrow_str,
                        "end_date": tomorrow_str,
                        "start_dt": start_dt,
                        "end_dt": end_dt
                    })
                    doctors_on_shift.append(doc)
            except Exception as e:
                print(f"[❌] Error parsing tomorrow's shift for {doc.get('name', 'Unknown')}: {e}")

    # ✅ 4. Build hour slots and related data
    hour_slots = []
    current_hour = base_date
    while current_hour < max_end_dt:
        hour_slots.append({
            "datetime": current_hour,
            "label": current_hour.strftime("%I %p").lstrip("0"),
            "hour": current_hour.hour,
            "date": current_hour.strftime("%Y-%m-%d"),
        })
        current_hour += timedelta(hours=1)

    today_str = today_date.strftime("%Y-%m-%d")
    tomorrow_str = (today_date + timedelta(days=1)).strftime("%Y-%m-%d")
    for slot in hour_slots:
        if slot['date'] == today_str:
            slot['day_label'] = 'Today'
        elif slot['date'] == tomorrow_str:
            slot['day_label'] = 'Tomorrow'
        else:
            slot['day_label'] = slot['date']

    # ✅ 5. Map doctors by hour
    doctors_by_hour = defaultdict(list)
    for doc in doctors_on_shift:
        for slot in hour_slots:
            slot_start = slot["datetime"]
            slot_end = slot_start + timedelta(hours=1)
            is_on_break = (
                doc.get("break_start_dt") and doc.get("break_end_dt") and
                doc["break_start_dt"] < slot_end and doc["break_end_dt"] > slot_start
            )
            if doc.get("start_dt") and doc.get("end_dt") and doc["start_dt"] < slot_end and doc["end_dt"] > slot_start and not is_on_break:

                doctors_by_hour[slot_start].append(doc)


    doctors_prn_by_hour = defaultdict(list)
    doctors_prn_with_routine_by_hour = defaultdict(list)

    for doc in doctors_on_shift:
        schedule_details = doc.get("schedule_details", "").lower()
        has_routine = "routine" in schedule_details

        for prn_start, prn_end in doc.get("prn_ranges", []):
            for slot in hour_slots:
                slot_start = slot["datetime"]
                slot_end = slot_start + timedelta(hours=1)
                if prn_start < slot_end and prn_end > slot_start:
                    doctors_prn_by_hour[slot_start].append(doc)
                    if has_routine:
                        doctors_prn_with_routine_by_hour[slot_start].append(doc)


    def deduplicate_doctors_by_hour(doctors_dict):
        for hour, docs in doctors_dict.items():
            seen = set()
            unique_docs = []
            for doc in docs:
                doc_id = doc.get("id")
                if doc_id and doc_id not in seen:
                    seen.add(doc_id)
                    unique_docs.append(doc)
            doctors_dict[hour] = unique_docs

    deduplicate_doctors_by_hour(doctors_prn_by_hour)
    deduplicate_doctors_by_hour(doctors_prn_with_routine_by_hour)


    all_doctors = (supabase.table("radiologists").select("*").execute().data or [])
    doctors_by_timezone = defaultdict(list)
    for doctor in all_doctors:
        tz = doctor.get("timezone", "Unknown") or "Unknown"
        doctors_by_timezone[tz].append(doctor)

    doctors_on_shift_ids = {doc["id"] for doc in doctors_on_shift if doc.get("id")}
    doctors_currently_on_shift_ids = {
        doc["id"]
        for doc in doctors_on_shift
        if doc.get("id") and
        doc.get("start_time") and doc.get("end_time") and
        int(doc["start_time"].split(":")[0]) <= datetime.now().hour < int(doc["end_time"].split(":")[0])
    }

    # ✅ 6. Compute RVU stats
    prev_date_hour_pairs = set()
    for slot in hour_slots:
        d, h = get_prev_week_same_day_and_hour(slot["datetime"])
        if d: prev_date_hour_pairs.add((d, h))

    dates_list = list({d for d, _ in prev_date_hour_pairs})
    hours_list = list({h for _, h in prev_date_hour_pairs})
    capacity_res = supabase.table("capacity_per_hour").select("date", "hour", "total_rvus")\
        .in_("date", dates_list).in_("hour", hours_list).execute()

    capacity_lookup = {
        (row["date"], int(row["hour"])): row["total_rvus"]
        for row in (capacity_res.data or [])
    }

    rvu_rows = {
        row["radiologist_id"]: row
        for row in (supabase.table("rad_avg_monthly_rvu").select("*").execute().data or [])
    }

    hourly_rvu_stats = {}
    for slot in hour_slots:
        dt = slot["datetime"]
        d, h = get_prev_week_same_day_and_hour(dt)
        historical_rvu = capacity_lookup.get((d, h)) if d else None
        current_total_rvu = sum(
            get_latest_nonzero_rvu(rvu_rows.get(doc["id"], {}))
            for doc in doctors_by_hour.get(dt, [])
        )
        hourly_rvu_stats[dt] = {
            "historical": historical_rvu,
            "current": current_total_rvu
        }

    # Render template
    return render_template("daily.html",
        user=user,
        today=today,
        prev_date=prev_date,
        next_date=next_date,
        hour_slots=hour_slots,
         doctors_prn_with_routine_by_hour=doctors_prn_with_routine_by_hour,
        doctors_prn_by_hour=doctors_prn_by_hour,
        doctors_on_shift=doctors_on_shift,
        doctors_by_hour=doctors_by_hour,
        doctors_by_timezone=dict(doctors_by_timezone),
        doctors_on_shift_ids=list(doctors_on_shift_ids),
        doctors_currently_on_shift_ids=list(doctors_currently_on_shift_ids),
        selected_timezone=request.args.get("timezone", "EST"),
        timezone_offset = {
    'EST': 0,
    'CST': -1,
    'PST': -3,
    'UTC': +5,
    'KST': +13
}.get(request.args.get("timezone", "EST"), 0),
        hourly_rvu_stats=hourly_rvu_stats,
        rvu_rows=rvu_rows,
        get_latest_nonzero_rvu=get_latest_nonzero_rvu,
        unique_doctors={doc["id"]: doc for doc in doctors_on_shift if doc.get("id")}
    )

def get_prev_week_same_day_and_hour(dt):
    prev_week_dt = dt - timedelta(weeks=1)
    return prev_week_dt.date().isoformat(), prev_week_dt.hour

# --- Helper functions ---
def get_prev_month_same_dow_and_hour(dt):
    year, month, hour = dt.year, dt.month, dt.hour
    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    days = monthrange(prev_year, prev_month)[1]
    candidates = [datetime(prev_year, prev_month, d) for d in range(1, days + 1) if datetime(prev_year, prev_month, d).weekday() == dt.weekday()]
    if not candidates:
        return None, hour
    week_of_month = (dt.day - 1) // 7
    chosen = candidates[week_of_month] if week_of_month < len(candidates) else candidates[-1]
    return chosen.date().isoformat(), hour

def get_latest_nonzero_rvu(rvu_row):
    for m in ["dec", "nov", "oct", "sep", "aug", "jul", "jun", "may", "apr", "mar", "feb", "jan"]:
        val = rvu_row.get(m)
        if val: return val
    return 0

@daily_bp.route("/daily/schedule-sync", methods=["POST"])
def sync_schedule():
    from flask import current_app
    token = request.headers.get("Authorization")
    sheet_name = request.json.get("sheet_name")

    print(f"[📥] Incoming sync request for: {sheet_name}")
    if token != "Bearer YOUR_SECRET_TOKEN":
        print("❌ Unauthorized request")
        return jsonify({"error": "unauthorized"}), 403

    if not sheet_name:
        print("❌ No sheet_name provided")
        return jsonify({"error": "sheet_name not provided"}), 400

    try:
        result = run_google_sheet_sync(sheet_name=sheet_name)
        print(f"✅ Sync successful for {sheet_name}: {result['rows_inserted']} rows inserted.")
        return jsonify({"status": "success", "details": result}), 200
    except Exception as e:
        print(f"❌ Sync failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500