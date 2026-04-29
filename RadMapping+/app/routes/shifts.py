# RadMapping+/app/routes/shifts.py

from flask import Blueprint, render_template, request, jsonify
import json
import time
from datetime import datetime, timedelta
from collections import defaultdict
from app.supabase_client import get_supabase_client
from app.time_utils import eastern_now
from app.middleware import with_supabase_auth
from app.supabase_helper import fetch_all_rows

shifts_bp = Blueprint("shifts", __name__)


def get_prev_week_same_day_and_hour(dt):
    return dt.date().isoformat(), dt.hour


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
DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def weekday_key(dt):
    try:
        return DAY_KEYS[dt.weekday()]
    except Exception:
        return None


def weekday_name(dt):
    try:
        return dt.strftime("%A").lower()
    except Exception:
        return None


def normalize_modality_weights(weights):
    if not isinstance(weights, dict):
        return {}
    clean = {}
    total = 0.0
    for k, v in weights.items():
        try:
            val = float(v)
        except Exception:
            continue
        if val < 0:
            continue
        clean[str(k).upper()] = val
        total += val
    if total > 0:
        return {k: (v / total) for k, v in clean.items()}
    return {}


def extract_modality_weights(row):
    day_weights = {}
    if not isinstance(row, dict):
        return day_weights
    fallback = normalize_modality_weights(row.get("modality_weights") or {})
    if fallback:
        day_weights["_fallback"] = fallback
    return day_weights


def get_doc_modality_weights(weight_map, doc_id, dt):
    if doc_id is None:
        return {}
    doc_entry = weight_map.get(doc_id, {}) or {}
    day_key = weekday_name(dt)
    if day_key and doc_entry.get(day_key):
        return doc_entry[day_key]
    return doc_entry.get("_fallback", {})


def get_daily_rvu_value(rvu_row, dt=None):
    if not rvu_row:
        return 0.0

    key = weekday_key(dt) if dt else None
    if key:
        try:
            val = float(rvu_row.get(key)) if rvu_row.get(key) is not None else None
            if val and val != 0:
                return val
        except Exception:
            pass

    for k in DAY_KEYS:
        try:
            val = float(rvu_row.get(k)) if rvu_row.get(k) is not None else None
        except Exception:
            continue
        if val and val != 0:
            return val

    return 0.0


def uniform_modality_weights():
    if not MODALITY_RVU:
        return {}
    count = len(MODALITY_RVU.keys())
    if count <= 0:
        return {}
    weight = 1.0 / count
    return {mod: weight for mod in MODALITY_RVU.keys()}


def derive_demand_modality_weights(demand_rows):
    totals = defaultdict(float)
    for row in demand_rows:
        mod = (row.get("modality") or "").upper()
        if not mod:
            continue
        try:
            totals[mod] += float(row.get("total_rvus") or 0)
        except Exception:
            continue
    normalized = normalize_modality_weights(totals)
    return normalized


def compute_avg_rvu_per_case(weights):
    if not weights:
        return 0.0
    avg = 0.0
    for mod, weight in weights.items():
        try:
            w = float(weight)
        except Exception:
            continue
        if w <= 0:
            continue
        avg += w * float(MODALITY_RVU.get(str(mod).upper(), 0))
    return avg


def adjusted_rvu_from_metrics(base_rvu, volatility, weights, distribution_mode):
    try:
        base_val = float(base_rvu or 0)
    except Exception:
        base_val = 0.0
    try:
        vol_val = float(volatility or 0)
    except Exception:
        vol_val = 0.0
    mode = (distribution_mode or "normal").lower()
    if mode == "worst":
        adjusted_rvu = max(0.0, base_val - vol_val)
    elif mode == "best":
        adjusted_rvu = base_val + vol_val
    else:
        adjusted_rvu = base_val
    return adjusted_rvu


def normalize_distribution_mode(mode):
    clean_mode = str(mode or "normal").lower()
    if clean_mode not in ("worst", "normal", "best"):
        return "normal"
    return clean_mode


def float_or_none(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def nonnegative_float(value, default=0.0):
    parsed = float_or_none(value)
    if parsed is None:
        return default
    return max(0.0, parsed)


def adjusted_trickle_rvus(
    total_rvus,
    base_rvus,
    trickle_multiplier,
    distribution_mode,
    trickle_added_rvus=None,
    dropped_rvus=None,
    avg_inherited_backlog_rvus=None,
):
    total_val = nonnegative_float(total_rvus)
    base_val = float_or_none(base_rvus)
    if base_val is None:
        base_val = max(0.0, total_val)
    else:
        base_val = max(0.0, base_val)

    tm_val = nonnegative_float(trickle_multiplier, 1.0)
    if tm_val <= 0:
        tm_val = 1.0

    inferred_trickle = max(0.0, total_val - base_val)
    added_val = float_or_none(trickle_added_rvus)
    inherited_val = float_or_none(avg_inherited_backlog_rvus)
    dropped_val = float_or_none(dropped_rvus)
    mode = normalize_distribution_mode(distribution_mode)

    if mode == "worst":
        candidates = [inferred_trickle]
        if inherited_val is not None:
            candidates.append(max(0.0, inherited_val))
        if added_val is not None:
            candidates.append(max(0.0, added_val))
        return max(candidates)

    if mode == "normal":
        if added_val is not None:
            return max(0.0, added_val)
        return inferred_trickle / tm_val

    if added_val is not None:
        if dropped_val is not None:
            return max(0.0, added_val - max(0.0, dropped_val))
        return max(0.0, added_val / tm_val)
    return inferred_trickle / (tm_val * tm_val)


def adjusted_expected_rvus(
    total_rvus,
    base_rvus,
    trickle_multiplier,
    distribution_mode,
    trickle_added_rvus=None,
    dropped_rvus=None,
    avg_inherited_backlog_rvus=None,
):
    try:
        total_val = float(total_rvus or 0)
    except Exception:
        total_val = 0.0
    try:
        base_val = float(base_rvus) if base_rvus is not None else None
    except Exception:
        base_val = None
    try:
        tm_val = float(trickle_multiplier) if trickle_multiplier is not None else 1.0
    except Exception:
        tm_val = 1.0
    if tm_val <= 0:
        tm_val = 1.0

    mode = normalize_distribution_mode(distribution_mode)
    if mode == "worst" and avg_inherited_backlog_rvus is None:
        return total_val

    base_for_adjustment = base_val if base_val is not None else max(0.0, total_val)
    return base_for_adjustment + adjusted_trickle_rvus(
        total_val,
        base_for_adjustment,
        tm_val,
        mode,
        trickle_added_rvus=trickle_added_rvus,
        dropped_rvus=dropped_rvus,
        avg_inherited_backlog_rvus=avg_inherited_backlog_rvus,
    )


def adjusted_trickle_display(
    total_rvus,
    base_rvus,
    trickle_multiplier,
    distribution_mode,
    trickle_added_rvus=None,
    dropped_rvus=None,
    avg_inherited_backlog_rvus=None,
):
    base_val = nonnegative_float(base_rvus)
    if base_val <= 0:
        return max(1.0, nonnegative_float(trickle_multiplier, 1.0))
    adjusted_total = adjusted_expected_rvus(
        total_rvus,
        base_val,
        trickle_multiplier,
        distribution_mode,
        trickle_added_rvus=trickle_added_rvus,
        dropped_rvus=dropped_rvus,
        avg_inherited_backlog_rvus=avg_inherited_backlog_rvus,
    )
    return max(1.0, adjusted_total / base_val)


def get_rvu_bg_color_class(ratio):
    if ratio is not None:
        if ratio < 0.5:
            return "bg-red-50"
        elif ratio < 0.7:
            return "bg-red-200"
        elif ratio <= 1.0:
            return "bg-yellow-100"
        else:
            return "bg-green-100"
    return "bg-gray-100"


US_STATES = [
    "Alabama",
    "Alaska",
    "Arizona",
    "Arkansas",
    "California",
    "Colorado",
    "Connecticut",
    "Delaware",
    "Florida",
    "Georgia",
    "Hawaii",
    "Idaho",
    "Illinois",
    "Indiana",
    "Iowa",
    "Kansas",
    "Kentucky",
    "Louisiana",
    "Maine",
    "Maryland",
    "Massachusetts",
    "Michigan",
    "Minnesota",
    "Mississippi",
    "Missouri",
    "Montana",
    "Nebraska",
    "Nevada",
    "New Hampshire",
    "New Jersey",
    "New Mexico",
    "New York",
    "North Carolina",
    "North Dakota",
    "Ohio",
    "Oklahoma",
    "Oregon",
    "Pennsylvania",
    "Puerto Rico",
    "Rhode Island",
    "South Carolina",
    "South Dakota",
    "Tennessee",
    "Texas",
    "Utah",
    "Vermont",
    "Virginia",
    "Washington",
    "District of Columbia",
    "West Virginia",
    "Wisconsin",
    "Wyoming",
]

# Study-sized RVU chunks per modality (minimum contribution unit)
MODALITY_RVU = {
    "XR": 0.2,
    "CT": 1.1,
    "US": 0.5,
    "MRI": 1.4,
    "MG": 0.8,
    "NM": 2.5,
    "PT": 2.5,
    "IR": 4.0,
    "RF": 0.7,
    "SC": 0.6,
    "OT": 0.3,
    "XA": 0.8,
    "ECG": 0.2,
}

# Feature flag: global coverage filters are shown, then loaded lazily on first use.
COVERAGE_FILTERS_ENABLED = True

# Soft-preference tuning: modalities with a weight below this threshold are
# treated as "last resort" for allocation. We still allow allocating to them
# if nothing else can take the chunk, but we prefer higher-weight modalities.
SOFT_WEIGHT_THRESHOLD = 0.01  # 1%


def modality_chunk(mod):
    if not mod:
        return 0.2
    return float(MODALITY_RVU.get(str(mod).upper(), 0.2))


def build_week_hour_slots(start_of_week, end_of_week):
    hour_slots_by_day = defaultdict(list)
    current_day = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    while current_day <= end_of_week.replace(hour=0, minute=0, second=0, microsecond=0):
        current_hour = current_day.replace(hour=0)
        while current_hour < current_day + timedelta(days=1):
            hour_slots_by_day[current_day.date()].append(
                {
                    "datetime": current_hour,
                    "label": current_hour.strftime("%I %p").lstrip("0"),
                    "hour": current_hour.hour,
                    "date": current_hour.strftime("%Y-%m-%d"),
                    "day_label": current_day.strftime("%A"),
                }
            )
            current_hour += timedelta(hours=1)
        current_day += timedelta(days=1)

    all_hour_slots = [
        slot for day_slots in hour_slots_by_day.values() for slot in day_slots
    ]
    return hour_slots_by_day, all_hour_slots


def fetch_week_doctors_by_hour(supabase, start_of_week, end_of_week):
    start_date_str = start_of_week.strftime("%Y-%m-%d")
    end_date_str = end_of_week.strftime("%Y-%m-%d")
    hour_slots_by_day, all_hour_slots = build_week_hour_slots(
        start_of_week, end_of_week
    )

    query = (
        supabase.table("monthly_schedule")
        .select("*, radiologists(*)")
        .lte("start_date", end_date_str)
        .gte("end_date", start_date_str)
    )

    batch_size = 1000
    offset = 0
    schedule_rows = []
    while True:
        res = query.range(offset, offset + batch_size - 1).execute()
        batch = res.data or []
        schedule_rows.extend(batch)
        if len(batch) < batch_size:
            break
        offset += batch_size

    doctors_on_shift = []
    for entry in schedule_rows:
        if not (
            entry.get("radiologists")
            and entry.get("start_time")
            and entry.get("end_time")
        ):
            continue

        doc = entry["radiologists"]
        start_date = entry.get("start_date") or start_date_str
        end_date = entry.get("end_date") or end_date_str

        try:
            shift_start_dt = datetime.strptime(
                f"{start_date} {entry['start_time']}", "%Y-%m-%d %H:%M:%S"
            )
            shift_end_dt = datetime.strptime(
                f"{end_date} {entry['end_time']}", "%Y-%m-%d %H:%M:%S"
            )
            if shift_end_dt < shift_start_dt:
                shift_end_dt += timedelta(days=1)

            break_start_dt = None
            break_end_dt = None
            if entry.get("break_start") and entry.get("break_end"):
                break_start_dt = datetime.strptime(
                    f"{start_date} {entry['break_start']}", "%Y-%m-%d %H:%M:%S"
                )
                break_end_dt = datetime.strptime(
                    f"{start_date} {entry['break_end']}", "%Y-%m-%d %H:%M:%S"
                )
                if break_end_dt < break_start_dt:
                    break_end_dt += timedelta(days=1)

            full_doc_info = doc.copy()
            full_doc_info.update(
                {
                    "start_time": entry["start_time"],
                    "end_time": entry["end_time"],
                    "start_date": start_date,
                    "end_date": end_date,
                    "start_dt": shift_start_dt,
                    "end_dt": shift_end_dt,
                    "break_start_dt": break_start_dt,
                    "break_end_dt": break_end_dt,
                }
            )
            doctors_on_shift.append(full_doc_info)
        except Exception as e:
            print(f"Error parsing datetime for doc {doc.get('name', 'Unknown')}: {e}")

    doctors_by_hour = defaultdict(list)
    for doc in doctors_on_shift:
        for slot in all_hour_slots:
            slot_start = slot["datetime"]
            slot_end = slot_start + timedelta(hours=1)

            is_on_break = False
            if doc.get("break_start_dt") and doc.get("break_end_dt"):
                break_start_on_slot_day = datetime.combine(
                    slot_start.date(), doc["break_start_dt"].timetz()
                )
                break_end_on_slot_day = datetime.combine(
                    slot_start.date(), doc["break_end_dt"].timetz()
                )

                if doc["break_end_dt"].date() > doc["break_start_dt"].date():
                    break_end_on_slot_day += timedelta(days=1)

                is_on_break = (
                    break_start_on_slot_day < slot_end
                    and break_end_on_slot_day > slot_start
                )

            is_on_shift = doc["start_dt"] < slot_end and doc["end_dt"] > slot_start

            if is_on_shift and not is_on_break:
                doctors_by_hour[slot_start].append(doc)

    return {
        "all_hour_slots": all_hour_slots,
        "doctors_by_hour": doctors_by_hour,
        "doctors_on_shift": doctors_on_shift,
        "schedule_rows_count": len(schedule_rows),
    }


def is_active_facility_assignment(row):
    return str(row.get("can_read", "")).strip().lower() == "true"


def get_assignment_facility_name(row):
    facility = row.get("facilities") or {}
    if not isinstance(facility, dict):
        return ""
    return str(facility.get("name") or "").strip()


@shifts_bp.route("/shifts")
@with_supabase_auth
def shifts():
    route_started = time.perf_counter()
    timings = []

    def mark_timing(label):
        timings.append((label, time.perf_counter() - route_started))

    supabase = get_supabase_client()

    date_str = request.args.get("date")
    distribution_mode = normalize_distribution_mode(
        request.args.get("distribution_mode")
    )
    print(f"Shifts date param: {date_str}")
    if date_str:
        now = datetime.strptime(date_str, "%Y-%m-%d")
    else:
        now = eastern_now().replace(tzinfo=None)

    start_of_week = now - timedelta(days=now.weekday())
    end_of_week = start_of_week + timedelta(days=6)

    start_date_str = start_of_week.strftime("%Y-%m-%d")
    end_date_str = end_of_week.strftime("%Y-%m-%d")

    prev_week_start = (start_of_week - timedelta(weeks=1)).strftime("%Y-%m-%d")
    next_week_start = (start_of_week + timedelta(weeks=1)).strftime("%Y-%m-%d")

    hour_slots_by_day = defaultdict(list)
    current_day = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    while current_day <= end_of_week.replace(hour=0, minute=0, second=0, microsecond=0):
        current_hour = current_day.replace(hour=0)
        while current_hour < current_day + timedelta(days=1):
            hour_slots_by_day[current_day.date()].append(
                {
                    "datetime": current_hour,
                    "label": current_hour.strftime("%I %p").lstrip("0"),
                    "hour": current_hour.hour,
                    "date": current_hour.strftime("%Y-%m-%d"),
                    "day_label": current_day.strftime("%A"),
                }
            )
            current_hour += timedelta(hours=1)
        current_day += timedelta(days=1)
    mark_timing("hour_slots")
    query = (
        supabase.table("monthly_schedule")
        .select("*, radiologists(*)")
        .lte("start_date", end_date_str)
        .gte("end_date", start_date_str)
    )

    # Paginate to avoid 1000-row default limit
    batch_size = 1000
    offset = 0
    schedule_rows = []
    while True:
        res = query.range(offset, offset + batch_size - 1).execute()
        batch = res.data or []
        schedule_rows.extend(batch)
        if len(batch) < batch_size:
            break
        offset += batch_size

    doctors_on_shift = []
    for entry in schedule_rows:
        if (
            entry.get("radiologists")
            and entry.get("start_time")
            and entry.get("end_time")
        ):
            doc = entry["radiologists"]

            start_date = entry.get("start_date") or start_date_str
            end_date = entry.get("end_date") or end_date_str

            try:
                shift_start_dt = datetime.strptime(
                    f"{start_date} {entry['start_time']}", "%Y-%m-%d %H:%M:%S"
                )
                shift_end_dt = datetime.strptime(
                    f"{end_date} {entry['end_time']}", "%Y-%m-%d %H:%M:%S"
                )
                if shift_end_dt < shift_start_dt:
                    shift_end_dt += timedelta(days=1)

                break_start_dt = None
                break_end_dt = None
                if entry.get("break_start") and entry.get("break_end"):
                    break_start_dt_candidate = datetime.strptime(
                        f"{start_date} {entry['break_start']}", "%Y-%m-%d %H:%M:%S"
                    )
                    break_end_dt_candidate = datetime.strptime(
                        f"{start_date} {entry['break_end']}", "%Y-%m-%d %H:%M:%S"
                    )
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
                    "break_end_dt": break_end_dt,
                }
                full_doc_info = doc.copy()
                full_doc_info.update(doc_schedule_details)
                doctors_on_shift.append(full_doc_info)

            except Exception as e:
                print(
                    f"Error parsing datetime for doc {doc.get('name', 'Unknown')}: {e}"
                )

    doctors_by_hour = defaultdict(list)
    for doc in doctors_on_shift:
        for day, hour_slots in hour_slots_by_day.items():
            for slot in hour_slots:
                slot_start = slot["datetime"]
                slot_end = slot_start + timedelta(hours=1)

                is_on_break = False
                if doc.get("break_start_dt") and doc.get("break_end_dt"):
                    break_start_on_slot_day = datetime.combine(
                        slot_start.date(), doc["break_start_dt"].timetz()
                    )
                    break_end_on_slot_day = datetime.combine(
                        slot_start.date(), doc["break_end_dt"].timetz()
                    )

                    if doc["break_end_dt"].date() > doc["break_start_dt"].date():
                        break_end_on_slot_day += timedelta(days=1)

                    is_on_break = (
                        break_start_on_slot_day < slot_end
                        and break_end_on_slot_day > slot_start
                    )

                is_on_shift = doc["start_dt"] < slot_end and doc["end_dt"] > slot_start

                if is_on_shift and not is_on_break:
                    doctors_by_hour[slot_start].append(doc)
    mark_timing(f"schedule rows={len(schedule_rows)} on_shift={len(doctors_on_shift)}")

    all_hour_slots = [
        slot for day_slots in hour_slots_by_day.values() for slot in day_slots
    ]

    prev_dates_hours_map = {}
    for slot in all_hour_slots:
        prev_date_str, prev_hour_int = get_prev_week_same_day_and_hour(slot["datetime"])
        if prev_date_str is not None:
            prev_dates_hours_map[(slot["datetime"], (prev_date_str, prev_hour_int))] = (
                True
            )

    unique_prev_keys = list({pair for _, pair in prev_dates_hours_map.keys()})

    # Paginate capacity_per_hour by date to avoid 1000 row limit
    cap_dates = [d for d, _ in unique_prev_keys] or ["1900-01-01"]
    cap_rows_all = []
    _offset = 0
    _batch = 1000
    while True:
        _res = (
            supabase.table("capacity_per_hour")
            .select(
                "date",
                "hour",
                "total_rvus",
                "trickle_multiplier",
                "base_total_rvus",
                "trickle_added_rvus",
                "dropped_rvus",
                "avg_arriving_rvus",
                "avg_inherited_backlog_rvus",
                "doctor_capacity_worst_rvus",
                "doctor_capacity_normal_rvus",
                "doctor_capacity_best_rvus",
            )
            .in_("date", cap_dates)
            .range(_offset, _offset + _batch - 1)
            .execute()
        )
        _data = _res.data or []
        cap_rows_all.extend(_data)
        if len(_data) < _batch:
            break
        _offset += _batch
    mark_timing(f"capacity rows={len(cap_rows_all)}")

    historical_rvu_lookup = {}
    trickle_multiplier_lookup = {}
    backlog_lookup = {}
    doctor_capacity_lookup = {}
    for row in cap_rows_all:
        d = row.get("date")
        h = row.get("hour")
        try:
            h_int = int(h) if not isinstance(h, (int, float)) else int(h)
        except Exception:
            try:
                hs = str(h).strip()
                if "." in hs:
                    hs = hs.split(".")[0]
                h_int = int(hs)
            except Exception:
                continue
        historical_rvu_lookup[(d, h_int)] = adjusted_expected_rvus(
            row.get("total_rvus"),
            row.get("base_total_rvus"),
            row.get("trickle_multiplier"),
            distribution_mode,
            trickle_added_rvus=row.get("trickle_added_rvus"),
            dropped_rvus=row.get("dropped_rvus"),
            avg_inherited_backlog_rvus=row.get("avg_inherited_backlog_rvus"),
        )
        trickle_multiplier_lookup[(d, h_int)] = adjusted_trickle_display(
            row.get("total_rvus"),
            row.get("base_total_rvus"),
            row.get("trickle_multiplier"),
            distribution_mode,
            trickle_added_rvus=row.get("trickle_added_rvus"),
            dropped_rvus=row.get("dropped_rvus"),
            avg_inherited_backlog_rvus=row.get("avg_inherited_backlog_rvus"),
        )
        backlog_lookup[(d, h_int)] = adjusted_trickle_rvus(
            row.get("total_rvus"),
            row.get("base_total_rvus"),
            row.get("trickle_multiplier"),
            distribution_mode,
            trickle_added_rvus=row.get("trickle_added_rvus"),
            dropped_rvus=row.get("dropped_rvus"),
            avg_inherited_backlog_rvus=row.get("avg_inherited_backlog_rvus"),
        )
        if distribution_mode == "worst":
            doctor_capacity_lookup[(d, h_int)] = float(
                row.get("doctor_capacity_worst_rvus") or 0.0
            )
        elif distribution_mode == "best":
            doctor_capacity_lookup[(d, h_int)] = float(
                row.get("doctor_capacity_best_rvus") or 0.0
            )
        else:
            doctor_capacity_lookup[(d, h_int)] = float(
                row.get("doctor_capacity_normal_rvus") or 0.0
            )

    # # Optional debug: summarize fetched rows per date
    dbg = request.args.get("debug")
    if dbg and str(dbg).lower() in ("1", "true", "yes"):
        try:
            from collections import Counter

            fac_counts = Counter([r.get("date") for r in breakdown_rows_all])
            cap_counts = Counter([k[0] for k in historical_rvu_lookup.keys()])
            print(
                f"[shifts][DEBUG] capacity_per_hour_breakdown counts: {dict(fac_counts)}"
            )
            print(
                f"[shifts][DEBUG] capacity_per_hour dates present: {sorted(set(cap_counts.elements()))}"
            )
        except Exception as _e:
            print(f"[shifts][DEBUG] counting error: {_e}")

    # Compute per-slot historical expected and stored doctor capacity
    hourly_rvu_stats = {}

    for slot in all_hour_slots:
        slot_dt = slot["datetime"]
        prev_d, prev_h = get_prev_week_same_day_and_hour(slot_dt)

        hist = historical_rvu_lookup.get((prev_d, prev_h)) if prev_d else None
        eff = doctor_capacity_lookup.get((prev_d, prev_h), 0.0) if prev_d else 0.0
        tm = trickle_multiplier_lookup.get((prev_d, prev_h), 1.0) if prev_d else 1.0
        bl = backlog_lookup.get((prev_d, prev_h), 0.0) if prev_d else 0.0

        hourly_rvu_stats[slot_dt] = {
            "historical": hist,
            "current": eff,
            "trickle_multiplier": tm,
            "backlog": bl,
        }

    mark_timing("stored_effective_supply")

    # Debug: per-day coverage summary
    if dbg and str(dbg).lower() in ("1", "true", "yes"):
        try:
            for day, slots in hour_slots_by_day.items():
                tiles = 0
                with_docs = 0
                with_demand = 0
                for slot in slots:
                    tiles += 1
                    if doctors_by_hour.get(slot["datetime"]):
                        with_docs += 1
                    prev_d, prev_h = get_prev_week_same_day_and_hour(slot["datetime"])
                    if breakdown_by_date_hour.get(
                        (prev_d, prev_h)
                    ) or breakdown_by_date.get(prev_d):
                        with_demand += 1
                print(
                    f"[shifts][DEBUG] {day.isoformat()} tiles={tiles} doctors_hours={with_docs} demand_hours={with_demand}"
                )
        except Exception as _e:
            print(f"[shifts][DEBUG] per-day summary error: {_e}")

    weekly_data_by_day_and_color = {}
    for day, hour_slots in hour_slots_by_day.items():
        filtered_day_slots = [
            slot
            for slot in hour_slots
            if doctors_by_hour.get(slot["datetime"])
            or (
                hourly_rvu_stats.get(slot["datetime"])
                and (
                    hourly_rvu_stats[slot["datetime"]]["current"] is not None
                    or hourly_rvu_stats[slot["datetime"]]["historical"] is not None
                )
            )
        ]

        def sort_key(slot):
            stats = hourly_rvu_stats.get(slot["datetime"])
            if not stats or stats["historical"] is None or stats["historical"] <= 0:
                if not stats or stats["current"] is None:
                    return -2
                return -1
            if stats["current"] is None:
                return -1

            return stats["current"] / stats["historical"]

        sorted_day_slots = sorted(filtered_day_slots, key=sort_key)

        grouped_slots_by_color = defaultdict(list)
        for slot in sorted_day_slots:
            stats = hourly_rvu_stats.get(slot["datetime"])
            current = stats["current"] if stats else None
            expected = stats["historical"] if stats else None
            ratio = (
                (current / expected)
                if current is not None and expected and expected > 0
                else None
            )
            color_class = get_rvu_bg_color_class(ratio)
            grouped_slots_by_color[color_class].append(slot)

        if grouped_slots_by_color:
            weekly_data_by_day_and_color[day] = dict(grouped_slots_by_color)
    sorted_days = sorted(weekly_data_by_day_and_color.keys())
    sorted_weekly_data_by_day_and_color = {
        day: weekly_data_by_day_and_color[day] for day in sorted_days
    }

    all_facilities_res = supabase.table("facilities").select("name").execute()
    all_facility_names = sorted(
        [f["name"].strip() for f in (all_facilities_res.data or []) if f.get("name")]
    )
    mark_timing(f"facility names={len(all_facility_names)}")

    template_payload = {
        "weekly_data_by_day_and_color": sorted_weekly_data_by_day_and_color,
        "hourly_rvu_stats": hourly_rvu_stats,
        "start_date": start_of_week.strftime("%B %d, %Y"),
        "end_date": end_of_week.strftime("%B %d, %Y"),
        "selected_date": now.strftime("%Y-%m-%d"),
        "distribution_mode": distribution_mode,
        "prev_week_start": prev_week_start,
        "next_week_start": next_week_start,
        "doctors_by_hour": doctors_by_hour,
        "coverage_filters_enabled": COVERAGE_FILTERS_ENABLED,
        "datetime": datetime,
        "now": now,
        "eastern_today": eastern_now().date(),
        "all_facility_names": all_facility_names,
        "uncovered_states_by_hour": {},
        "covered_states_by_hour": {},
        "facility_names_by_hour": {},
    }

    rendered = render_template("shifts.html", **template_payload)
    mark_timing(f"render bytes={len(rendered)}")
    print(
        "[shifts][timing] "
        + " | ".join(f"{label}: {elapsed:.3f}s" for label, elapsed in timings)
        + f" | total: {time.perf_counter() - route_started:.3f}s"
    )
    return rendered


@shifts_bp.route("/shifts/coverage_filters")
@with_supabase_auth
def coverage_filters():
    route_started = time.perf_counter()
    timings = []

    def mark_timing(label):
        timings.append((label, time.perf_counter() - route_started))

    supabase = get_supabase_client()
    date_str = request.args.get("date")
    if date_str:
        try:
            now = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "Invalid date"}), 400
    else:
        now = eastern_now().replace(tzinfo=None)

    start_of_week = now - timedelta(days=now.weekday())
    end_of_week = start_of_week + timedelta(days=6)

    week_data = fetch_week_doctors_by_hour(supabase, start_of_week, end_of_week)
    all_hour_slots = week_data["all_hour_slots"]
    doctors_by_hour = week_data["doctors_by_hour"]
    doctors_on_shift = week_data["doctors_on_shift"]
    mark_timing(
        f"schedule rows={week_data['schedule_rows_count']} on_shift={len(doctors_on_shift)}"
    )

    doctor_ids = list({doc["id"] for doc in doctors_on_shift if doc.get("id")})

    certifications = []
    if doctor_ids:
        cert_res = (
            supabase.table("certifications")
            .select("radiologist_id,state")
            .in_("radiologist_id", doctor_ids)
            .execute()
        )
        certifications = cert_res.data or []
    mark_timing(f"certs={len(certifications)}")

    doctor_states = {}
    for cert in certifications:
        rid = str(cert["radiologist_id"]).strip()
        state = cert["state"]
        if rid not in doctor_states:
            doctor_states[rid] = set()
        if state:
            doctor_states[rid].add(state.strip().title())

    facility_assignments_data = []
    if doctor_ids:
        _offset = 0
        _batch = 1000
        while True:
            _res = (
                supabase.table("doctor_facility_assignments")
                .select("radiologist_id, can_read, facilities(name)")
                .in_("radiologist_id", doctor_ids)
                .range(_offset, _offset + _batch - 1)
                .execute()
            )
            _data = _res.data or []
            facility_assignments_data.extend(_data)
            if len(_data) < _batch:
                break
            _offset += _batch

    facility_map = defaultdict(list)
    for row in facility_assignments_data:
        if not is_active_facility_assignment(row):
            continue
        rad_id = str(row.get("radiologist_id") or "").strip()
        facility_name = get_assignment_facility_name(row)
        if rad_id and facility_name:
            facility_map[rad_id].append(facility_name)
    mark_timing(f"assignments={len(facility_assignments_data)}")

    all_facilities_res = supabase.table("facilities").select("name").execute()
    all_facility_names = sorted(
        [f["name"].strip() for f in (all_facilities_res.data or []) if f.get("name")]
    )
    mark_timing(f"facilities={len(all_facility_names)}")

    hours = {}
    for slot in all_hour_slots:
        slot_dt = slot["datetime"]
        slot_doctors = doctors_by_hour.get(slot_dt, [])
        covered_states = set()
        facility_names = set()

        for doc in slot_doctors:
            doc_id = str(doc["id"]).strip()
            covered_states.update(doctor_states.get(doc_id, set()))
            facility_names.update(facility_map.get(doc_id, []))

        covered = sorted(covered_states)
        hours[slot_dt.isoformat()] = {
            "covered_states": covered,
            "uncovered_states": sorted(set(US_STATES) - set(covered)),
            "facility_names": sorted(facility_names),
        }

    payload = {
        "all_states": sorted(US_STATES),
        "all_facility_names": all_facility_names,
        "hours": hours,
    }
    mark_timing(f"payload hours={len(hours)}")
    print(
        "[shifts][coverage_timing] "
        + " | ".join(f"{label}: {elapsed:.3f}s" for label, elapsed in timings)
        + f" | total: {time.perf_counter() - route_started:.3f}s"
    )
    return jsonify(payload)


@shifts_bp.route("/shifts/hour_detail", methods=["GET", "POST"])
@with_supabase_auth
def hour_detail():
    """
    Returns granular demand for a given date/hour from capacity_per_hour_breakdown
    along with scheduled coverage (doctors on shift who can read by state).

    Query params:
      - date: YYYY-MM-DD
      - hour: 0-23
    """
    supabase = get_supabase_client()

    # Accept both GET query params and POSTed JSON for simulations/overrides
    base_overrides = {}
    distribution_mode = "normal"
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        date_str = payload.get("date")
        hour = payload.get("hour")
        try:
            hour = int(hour) if hour is not None else None
        except Exception:
            hour = None
        bo = payload.get("base_overrides") or {}
        distribution_mode = payload.get("distribution_mode") or "normal"
        # Normalize override keys to str for consistent lookups
        if isinstance(bo, dict):
            try:
                base_overrides = {
                    str(k): float(v) for k, v in bo.items() if v is not None
                }
            except Exception:
                base_overrides = {str(k): v for k, v in bo.items()}
    else:
        date_str = request.args.get("date")
        hour = request.args.get("hour", type=int)
        distribution_mode = request.args.get("distribution_mode") or "normal"
        # Optional overrides via query string as JSON: overrides={"doc_id": 0}
        try:
            import json as _json

            q_over = request.args.get("overrides")
            if q_over:
                d = _json.loads(q_over)
                if isinstance(d, dict):
                    base_overrides = {
                        str(k): float(v) for k, v in d.items() if v is not None
                    }
        except Exception:
            base_overrides = {}
    if not date_str or hour is None:
        return jsonify({"error": "Missing date or hour"}), 400

    distribution_mode = normalize_distribution_mode(distribution_mode)

    # 1) State/modality demand for this hour (EXPECTED = same day/hour)
    prev_date_str, prev_hour_int = get_prev_week_same_day_and_hour(
        datetime.strptime(f"{date_str} {hour:02d}:00:00", "%Y-%m-%d %H:%M:%S")
    )
    print(
        f"[hour_detail] incoming date={date_str} hour={hour}; expected_source date={prev_date_str} hour={prev_hour_int}"
    )
    breakdown_res = (
        supabase.table("capacity_per_hour_breakdown")
        .select("state,total_rvus,modality,base_rvus,trickle_multiplier")
        .eq("date", prev_date_str)
        .eq("hour", prev_hour_int)
        .execute()
    )
    breakdown_rows = breakdown_res.data or []
    print(f"[hour_detail] capacity_per_hour_breakdown rows: {len(breakdown_rows)}")

    # Potential fallback: if no rows for the exact hour, try the nearest hour on the same date,
    # and scale the distribution to the expected total from capacity_per_hour for the requested hour.
    fallback_info = {"used": False}
    if not breakdown_rows:
        print(
            "[hour_detail] No breakdown rows found for expected HOUR. Attempting nearest-hour fallback on same date…"
        )

        # Fetch day data and group by hour
        day_res = (
            supabase.table("capacity_per_hour_breakdown")
            .select("state,total_rvus,modality,hour,base_rvus,trickle_multiplier")
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
            breakdown_rows = by_hour.get(nearest_hour, [])
            fallback_info = {
                "used": True,
                "source": {"date": prev_date_str, "hour": nearest_hour},
                "reason": "nearest_hour_same_date",
            }
            print(
                f"[hour_detail] Fallback using nearest hour {nearest_hour} with {len(breakdown_rows)} rows."
            )
        else:
            print(
                "[hour_detail] No breakdown rows for any hour on the date; returning empty payload."
            )
            return jsonify(
                {
                    "date": date_str,
                    "hour": hour,
                    "expected_source": {"date": prev_date_str, "hour": prev_hour_int},
                    "fallback": {"used": False, "reason": "no_rows_on_date"},
                    "total_expected_rvus": 0,
                    "by_state": [],
                    "by_state_merged": [],
                    "by_modality": [],
                    "state_breakdown": {},
                    "modality_breakdown": {},
                    "supply_overall_rvus": 0,
                    "supply_licensed_rvus": 0,
                    "supply_effective_allocated_rvus": 0,
                    "doctor_allocations": [],
                }
            )

    # 2) Adjust demand per distribution_mode while keeping some trickle in every mode.
    # Breakdown rows do not expose the full hourly trickle columns, so this falls back
    # to scaling the inferred trickle component from total/base/multiplier.
    for row in breakdown_rows:
        row["total_rvus"] = adjusted_expected_rvus(
            row.get("total_rvus"),
            row.get("base_rvus"),
            row.get("trickle_multiplier"),
            distribution_mode,
        )

    # 3) Determine doctors on shift for this specific hour
    #    Reuse the same logic as the weekly view but constrained to one hour window
    window_start = datetime.strptime(
        f"{date_str} {hour:02d}:00:00", "%Y-%m-%d %H:%M:%S"
    )
    window_end = window_start + timedelta(hours=1)

    sched_q = (
        supabase.table("monthly_schedule")
        .select("*, radiologists(*)")
        .lte("start_date", date_str)
        .gte("end_date", date_str)
    )
    sched_res = sched_q.execute()
    print(f"[hour_detail] schedule rows in date range: {len(sched_res.data or [])}")

    on_shift = []
    for entry in sched_res.data or []:
        try:
            if not (
                entry.get("radiologists")
                and entry.get("start_time")
                and entry.get("end_time")
            ):
                continue
            doc = entry["radiologists"].copy()
            start_date = entry.get("start_date") or date_str
            end_date = entry.get("end_date") or date_str
            shift_start_dt = datetime.strptime(
                f"{start_date} {entry['start_time']}", "%Y-%m-%d %H:%M:%S"
            )
            shift_end_dt = datetime.strptime(
                f"{end_date} {entry['end_time']}", "%Y-%m-%d %H:%M:%S"
            )
            if shift_end_dt < shift_start_dt:
                shift_end_dt += timedelta(days=1)

            break_start_dt = None
            break_end_dt = None
            if entry.get("break_start") and entry.get("break_end"):
                bstart = datetime.strptime(
                    f"{start_date} {entry['break_start']}", "%Y-%m-%d %H:%M:%S"
                )
                bend = datetime.strptime(
                    f"{start_date} {entry['break_end']}", "%Y-%m-%d %H:%M:%S"
                )
                if bend < bstart:
                    bend += timedelta(days=1)
                break_start_dt, break_end_dt = bstart, bend

            is_on_break = False
            if break_start_dt and break_end_dt:
                # Map break times onto the hour window's day
                bstart_on_day = datetime.combine(
                    window_start.date(), break_start_dt.timetz()
                )
                bend_on_day = datetime.combine(
                    window_start.date(), break_end_dt.timetz()
                )
                if bend_on_day < bstart_on_day:
                    bend_on_day += timedelta(days=1)
                is_on_break = bstart_on_day < window_end and bend_on_day > window_start

            is_on_shift = shift_start_dt < window_end and shift_end_dt > window_start

            if is_on_shift and not is_on_break:
                doc.update({"_start_dt": shift_start_dt, "_end_dt": shift_end_dt})
                on_shift.append(doc)
        except Exception:
            continue

    doctor_ids = [d.get("id") for d in on_shift if d.get("id") is not None]

    # 4) RVU supply numbers based on metrics (same logic as page)
    metrics_res = (
        supabase.table("rad_metrics").select("radiologist_id,rvu,volatility").execute()
    )
    metrics_rows = {row["radiologist_id"]: row for row in (metrics_res.data or [])}

    # 5) Modality weights for doctors on this hour
    modality_weights = {}
    if doctor_ids:

        def try_fetch_weights(table_name):
            try:
                res = (
                    supabase.table(table_name)
                    .select("radiologist_id,modality_weights")
                    .in_("radiologist_id", doctor_ids)
                    .execute()
                )
                return res.data or []
            except Exception:
                return []

        weight_rows = []
        for t in (
            "radiologist_modality_weights",
            "modality_weights",
            "rad_modality_weights",
        ):
            if not weight_rows:
                weight_rows = try_fetch_weights(t)
        for row in weight_rows:
            rid = row.get("radiologist_id")
            if rid is None:
                continue
            parsed = extract_modality_weights(row)
            if parsed:
                modality_weights[rid] = parsed

    def latest_nonzero_rvu(rvu_row, weights, distribution_mode):
        if not rvu_row:
            return 0.0
        base_rvu = rvu_row.get("rvu") if rvu_row is not None else 0
        volatility = rvu_row.get("volatility") if rvu_row is not None else 0
        return adjusted_rvu_from_metrics(
            base_rvu, volatility, weights, distribution_mode
        )

    demand_modality_weights = derive_demand_modality_weights(breakdown_rows)
    uniform_weights = uniform_modality_weights()

    supply_overall = 0
    for d in on_shift:
        did = d.get("id")
        conversion_weights = get_doc_modality_weights(
            modality_weights, did, window_start
        )
        if not conversion_weights:
            conversion_weights = demand_modality_weights or uniform_weights
        rr = metrics_rows.get(did)
        supply_overall += latest_nonzero_rvu(rr, conversion_weights, distribution_mode)

    # Helper to normalize state values to 2-letter codes
    STATE_NAME_TO_CODE = {
        "Alabama": "AL",
        "Alaska": "AK",
        "Arizona": "AZ",
        "Arkansas": "AR",
        "California": "CA",
        "Colorado": "CO",
        "Connecticut": "CT",
        "Delaware": "DE",
        "Florida": "FL",
        "Georgia": "GA",
        "Hawaii": "HI",
        "Idaho": "ID",
        "Illinois": "IL",
        "Indiana": "IN",
        "Iowa": "IA",
        "Kansas": "KS",
        "Kentucky": "KY",
        "Louisiana": "LA",
        "Maine": "ME",
        "Maryland": "MD",
        "Massachusetts": "MA",
        "Michigan": "MI",
        "Minnesota": "MN",
        "Mississippi": "MS",
        "Missouri": "MO",
        "Montana": "MT",
        "Nebraska": "NE",
        "Nevada": "NV",
        "New Hampshire": "NH",
        "New Jersey": "NJ",
        "New Mexico": "NM",
        "New York": "NY",
        "North Carolina": "NC",
        "North Dakota": "ND",
        "Ohio": "OH",
        "Oklahoma": "OK",
        "Oregon": "OR",
        "Pennsylvania": "PA",
        "Rhode Island": "RI",
        "South Carolina": "SC",
        "South Dakota": "SD",
        "Tennessee": "TN",
        "Texas": "TX",
        "Utah": "UT",
        "Vermont": "VT",
        "Virginia": "VA",
        "Washington": "WA",
        "District of Columbia": "DC",
        "West Virginia": "WV",
        "Wisconsin": "WI",
        "Wyoming": "WY",
        "Puerto Rico": "PR",
        "District Of Columbia": "DC",
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
    licensed_ids = set()
    licensed_by_state = defaultdict(set)
    cert_rows = []
    if doctor_ids:
        # Do not filter by state here; certs may be stored as names or codes.
        cert_res = (
            supabase.table("certifications")
            .select("radiologist_id,state")
            .in_("radiologist_id", doctor_ids)
            .execute()
        )
        cert_rows = cert_res.data or []
        print(f"[hour_detail] certifications rows: {len(cert_rows)}")
        for c in cert_rows:
            rid = c.get("radiologist_id")
            st = to_state_code(c.get("state"))
            if rid is not None:
                licensed_ids.add(rid)
                if st:
                    licensed_by_state[st].add(rid)

    doctor_states_display = defaultdict(set)
    for cert in cert_rows:
        rid = str(cert.get("radiologist_id")).strip()
        state = cert.get("state")
        if rid and state:
            doctor_states_display[rid].add(str(state).strip().title())

    covered_states_set = set()
    state_doctor_map = defaultdict(list)
    for doc in on_shift:
        doc_id = str(doc.get("id", "")).strip()
        doc_name = doc.get("name", "").strip()
        for state in doctor_states_display.get(doc_id, set()):
            covered_states_set.add(state)
            if doc_name:
                state_doctor_map[state].append(doc_name)

    uncovered_states = sorted(set(US_STATES) - covered_states_set)
    covered_states = sorted(set(US_STATES) - set(uncovered_states))

    facility_assignments_data = fetch_all_rows(
        "doctor_facility_assignments", "radiologist_id, can_read, facilities(name)"
    )
    facility_map = defaultdict(list)
    for row in facility_assignments_data:
        if not is_active_facility_assignment(row):
            continue
        rad_id = str(row.get("radiologist_id", "")).strip()
        facility_name = get_assignment_facility_name(row)
        if rad_id and facility_name:
            facility_map[rad_id].append(facility_name)

    all_facilities_res = supabase.table("facilities").select("name").execute()
    all_facility_names = sorted(
        [f["name"].strip() for f in (all_facilities_res.data or []) if f.get("name")]
    )

    fac_map = defaultdict(list)
    for doc in on_shift:
        doc_id = str(doc.get("id", "")).strip()
        doc_name = doc.get("name", "").strip()
        for fac in facility_map.get(doc_id, []):
            fac_map[fac].append(doc_name)

    facility_doctor_map = {fac: fac_map.get(fac, []) for fac in all_facility_names}

    supply_licensed = 0
    for d in on_shift:
        if d.get("id") in licensed_ids:
            did = d.get("id")
            conversion_weights = get_doc_modality_weights(
                modality_weights, did, window_start
            )
            if not conversion_weights:
                conversion_weights = demand_modality_weights or uniform_weights
            rr = metrics_rows.get(did)
            supply_licensed += latest_nonzero_rvu(
                rr, conversion_weights, distribution_mode
            )

    # Prepare demand groups for allocation and build state breakdowns
    # 6) Assemble state breakdowns
    by_state_mod = defaultdict(float)
    by_modality_totals = defaultdict(float)
    by_state_totals = defaultdict(float)
    state_breakdown = defaultdict(lambda: defaultdict(float))
    modality_breakdown = defaultdict(lambda: defaultdict(float))
    for row in breakdown_rows:
        expected = float(row.get("total_rvus") or 0)
        if expected <= 0:
            continue
        modality = row.get("modality")
        state = to_state_code(row.get("state"))
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
        if total <= 0:
            continue
        by_state_payload.append(
            {"state": st, "modality": mod, "expected_rvus": float(total)}
        )

    by_state_merged_payload = [
        {"state": st, "expected_rvus": float(total)}
        for st, total in by_state_totals.items()
        if total > 0
    ]
    by_modality_payload = [
        {"modality": m, "expected_rvus": float(v)}
        for m, v in by_modality_totals.items()
        if v > 0
    ]

    # If we used fallback from a different hour, optionally scale to match the expected total
    # from capacity_per_hour for the requested hour.
    total_expected = float(
        sum((float(r.get("total_rvus") or 0) for r in breakdown_rows))
    )
    if fallback_info.get("used"):
        # Fetch tile expected from capacity_per_hour for prev_date_str/prev_hour_int
        cap_row = (
            supabase.table("capacity_per_hour")
            .select(
                "total_rvus,base_total_rvus,trickle_multiplier,trickle_added_rvus,dropped_rvus,avg_arriving_rvus,avg_inherited_backlog_rvus"
            )
            .eq("date", prev_date_str)
            .eq("hour", prev_hour_int)
            .execute()
        )
        cap_total = None
        if cap_row.data:
            try:
                cap_data = (cap_row.data or [{}])[0]
                cap_total = adjusted_expected_rvus(
                    cap_data.get("total_rvus"),
                    cap_data.get("base_total_rvus"),
                    cap_data.get("trickle_multiplier"),
                    distribution_mode,
                    trickle_added_rvus=cap_data.get("trickle_added_rvus"),
                    dropped_rvus=cap_data.get("dropped_rvus"),
                    avg_inherited_backlog_rvus=cap_data.get(
                        "avg_inherited_backlog_rvus"
                    ),
                )
            except Exception:
                cap_total = None
        print(
            f"[hour_detail] Tile expected (capacity_per_hour) for scaling: {cap_total}"
        )
        if cap_total is not None and total_expected > 0:
            scale = cap_total / total_expected
            print(
                f"[hour_detail] Applying scale factor {scale:.4f} to fallback breakdown rows"
            )
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

    # 7) Doctor-by-doctor allocation details
    # Build demand groups: one per (state, modality), with base demand (and track remaining for reference)
    groups = []
    scale_factor = (
        float(fallback_info.get("scale_factor") or 1.0)
        if fallback_info.get("used") and fallback_info.get("scaled_to_expected")
        else 1.0
    )
    for row in breakdown_rows:
        mod = (row.get("modality") or "").upper() or None
        remaining = float(row.get("total_rvus") or 0) * scale_factor
        st = to_state_code(row.get("state"))
        groups.append(
            {
                "state": st,
                "mod": mod,
                # Preserve original demand as base for proportional distribution
                "base": remaining,
                "remaining": remaining,
            }
        )
    # Index groups by modality
    groups_by_mod = defaultdict(list)
    for g in groups:
        groups_by_mod[g["mod"]].append(g)

    doctor_allocations = []
    matched_supply_detail = 0.0

    # Helper to get doc base RVU
    def latest_nonzero_rvu(rr, weights, distribution_mode):
        if not rr:
            return 0.0
        return adjusted_rvu_from_metrics(
            rr.get("rvu"), rr.get("volatility"), weights, distribution_mode
        )

    # Iterate doctors on this hour
    EPS = 1e-6
    for d in on_shift:
        did = d.get("id")
        name = d.get("name")
        rr = metrics_rows.get(did) if did is not None else None
        conversion_weights = get_doc_modality_weights(
            modality_weights, did, window_start
        )
        if not conversion_weights:
            conversion_weights = demand_modality_weights or uniform_weights
        original_base = latest_nonzero_rvu(rr, conversion_weights, distribution_mode)
        base = original_base
        # Apply temporary simulation override if provided (no upper clamp per request)
        if did is not None and str(did) in base_overrides:
            try:
                ov = float(base_overrides[str(did)])
                if not (ov >= 0):
                    ov = 0.0
                base = adjusted_rvu_from_metrics(
                    ov,
                    rr.get("volatility") if rr else 0.0,
                    conversion_weights,
                    distribution_mode,
                )
            except Exception:
                base = original_base
        doc_weights = get_doc_modality_weights(modality_weights, did, window_start)
        if not doc_weights:
            mods_present = {g["mod"] for g in groups if g["mod"]}
            if mods_present:
                uniform = 1.0 / len(mods_present)
                doc_weights = {m: uniform for m in mods_present}
            else:
                doc_weights = {}

        lic_states = licensed_by_state
        # Aggregate per (state, modality) to avoid duplicate keys in UI
        per_key_amounts = {}
        per_key_meta = {}
        remaining_cap = base

        # PASS 1: coverage-first, chunked by modality RVU (soft modality preferences)
        while remaining_cap > EPS:
            # Total chunkable gap per modality for this doctor
            gap_by_mod = {}
            for mod, lst in groups_by_mod.items():
                ch = modality_chunk(mod)
                if ch <= EPS:
                    continue
                sum_gap = 0.0
                for g in lst:
                    st = g.get("state")
                    if st and did not in lic_states.get(st, set()):
                        continue
                    gap = float(g.get("remaining", 0.0))
                    if gap + EPS >= ch:
                        sum_gap += gap
                if sum_gap > EPS:
                    gap_by_mod[mod] = sum_gap
            if not gap_by_mod:
                break

            # Prefer modalities with higher weight first; if none meet threshold, fall back
            def _pick_mod(prefer_threshold=True):
                mods = list(gap_by_mod.keys())
                if prefer_threshold:
                    preferred = [
                        m
                        for m in mods
                        if (doc_weights.get(m, 0.0) >= SOFT_WEIGHT_THRESHOLD)
                    ]
                    if preferred:
                        mods = preferred

                def _score(m):
                    w = doc_weights.get(m, 0.0)
                    return gap_by_mod[m] * (w if w > 0 else 1e-9)

                return max(mods, key=_score)

            try:
                sel_mod = _pick_mod(True)
            except ValueError:
                sel_mod = _pick_mod(False)
            ch = modality_chunk(sel_mod)
            if remaining_cap + EPS < ch:
                break
            # choose group with max remaining gap in sel_mod
            cand = []
            for g in groups_by_mod.get(sel_mod, []):
                st = g.get("state")
                if st and did not in lic_states.get(st, set()):
                    continue
                if float(g.get("remaining", 0.0)) + EPS >= ch:
                    cand.append(g)
            if not cand:
                del gap_by_mod[sel_mod]
                if not gap_by_mod:
                    break
                continue
            best = max(cand, key=lambda gg: float(gg.get("remaining", 0.0)))
            best["remaining"] = max(0.0, float(best.get("remaining", 0.0)) - ch)
            matched_supply_detail += ch
            remaining_cap -= ch
            key = (best["state"], (sel_mod or ""))
            per_key_amounts[key] = per_key_amounts.get(key, 0.0) + float(ch)
            if key not in per_key_meta:
                per_key_meta[key] = {
                    "state": best.get("state"),
                    "modality": (sel_mod or ""),
                }

        # PASS 2: overflow coverage-aware with cap and round-robin (soft preferences)
        if remaining_cap > EPS:
            OVERFILL_CAP_R = 1.5
            per_group_chunks = {}
            MAX_CHUNKS_PER_GROUP_PER_DOC = 3
            # ensure groups carry overfill marker
            for lst in groups_by_mod.values():
                for g in lst:
                    if "overfill" not in g:
                        g["overfill"] = 0.0
            while remaining_cap > EPS:

                def _pick_overflow(allow_low_weight: bool):
                    best_g = None
                    best_mod = None
                    best_ch = 0.0
                    best_score = None
                    for mod, lst in groups_by_mod.items():
                        w = doc_weights.get(mod, 0.0)
                        if (w < SOFT_WEIGHT_THRESHOLD) and not allow_low_weight:
                            continue
                        ch = modality_chunk(mod)
                        if remaining_cap + EPS < ch:
                            continue
                        for g in lst:
                            st = g.get("state")
                            if st and did not in lic_states.get(st, set()):
                                continue
                            base_val = float(g.get("base", 0.0))
                            if base_val <= EPS:
                                continue
                            over = float(g.get("overfill", 0.0))
                            rem = float(g.get("remaining", 0.0))
                            covered = max(0.0, base_val - rem) + over
                            R = covered / max(base_val, EPS)
                            if R >= OVERFILL_CAP_R - 1e-9:
                                continue
                            key = (g["state"], mod)
                            if (
                                per_group_chunks.get(key, 0)
                                >= MAX_CHUNKS_PER_GROUP_PER_DOC
                            ):
                                continue
                            score = (R, -w)
                            if best_score is None or score < best_score:
                                best_score = score
                                best_g, best_mod, best_ch = g, mod, ch
                    return best_g, best_mod, best_ch

                g, mod, best_ch = _pick_overflow(False)
                if g is None:
                    g, mod, best_ch = _pick_overflow(True)
                if g is None:
                    break
                g["overfill"] = float(g.get("overfill", 0.0)) + best_ch
                if g.get("remaining", 0.0) > 0:
                    g["remaining"] = max(0.0, float(g.get("remaining", 0.0)) - best_ch)
                matched_supply_detail += best_ch
                remaining_cap -= best_ch
                key = (g["state"], (mod or ""))
                per_key_amounts[key] = per_key_amounts.get(key, 0.0) + float(best_ch)
                if key not in per_key_meta:
                    per_key_meta[key] = {
                        "state": g.get("state"),
                        "modality": (mod or ""),
                    }

        # Materialize aggregated allocations and filter small values
        allocs = []
        for key, amt in per_key_amounts.items():
            meta = per_key_meta.get(key, {})
            allocs.append({**meta, "allocated_rvus": float(amt)})

        contributed = float(sum(a.get("allocated_rvus", 0.0) for a in allocs))
        # Prepare modality weights list for UI (sorted desc)
        mw_list = []
        try:
            if doc_weights:
                mw_list = [
                    {"modality": str(k), "weight": float(v)}
                    for k, v in doc_weights.items()
                    if v is not None
                ]
                mw_list.sort(key=lambda x: x.get("weight", 0.0), reverse=True)
        except Exception:
            mw_list = []

        doctor_allocations.append(
            {
                "id": did,
                "name": name,
                "base_rvu": base,
                "original_base_rvu": original_base,
                "contributing_rvus": contributed,
                "unused_rvus": max(0.0, float(base - contributed)),
                "allocations": allocs,
                "modality_weights": mw_list,
            }
        )

    # Convert breakdown dicts to lists for JSON friendliness
    state_breakdown_list = {
        st: [{"modality": md, "expected_rvus": float(val)} for md, val in mods.items()]
        for st, mods in state_breakdown.items()
    }
    modality_breakdown_list = {
        md: [{"state": st, "expected_rvus": float(val)} for st, val in states.items()]
        for md, states in modality_breakdown.items()
    }

    # Fetch hourly trickle_multiplier from capacity_per_hour for display
    hour_trickle_multiplier = 1.0
    try:
        tm_res = (
            supabase.table("capacity_per_hour")
            .select(
                "total_rvus,base_total_rvus,trickle_multiplier,trickle_added_rvus,dropped_rvus,avg_arriving_rvus,avg_inherited_backlog_rvus"
            )
            .eq("date", prev_date_str)
            .eq("hour", prev_hour_int)
            .execute()
        )
        if tm_res.data:
            tm_data = tm_res.data[0]
            hour_trickle_multiplier = adjusted_trickle_display(
                tm_data.get("total_rvus"),
                tm_data.get("base_total_rvus"),
                tm_data.get("trickle_multiplier"),
                distribution_mode,
                trickle_added_rvus=tm_data.get("trickle_added_rvus"),
                dropped_rvus=tm_data.get("dropped_rvus"),
                avg_inherited_backlog_rvus=tm_data.get("avg_inherited_backlog_rvus"),
            )
    except Exception:
        hour_trickle_multiplier = 1.0

    payload = {
        "date": date_str,
        "hour": hour,
        "expected_source": {"date": prev_date_str, "hour": prev_hour_int},
        "fallback": fallback_info,
        "applied_overrides": base_overrides,
        "total_expected_rvus": total_expected,
        "trickle_multiplier": hour_trickle_multiplier,
        "distribution_mode": distribution_mode,
        "by_state": by_state_payload,
        "by_state_merged": by_state_merged_payload,
        "by_modality": by_modality_payload,
        "state_breakdown": state_breakdown_list,
        "modality_breakdown": modality_breakdown_list,
        "covered_states": covered_states,
        "uncovered_states": uncovered_states,
        "state_doctor_map": dict(state_doctor_map),
        "facility_doctor_map": facility_doctor_map,
        "supply_overall_rvus": supply_overall,
        "supply_licensed_rvus": supply_licensed,
        "supply_effective_allocated_rvus": matched_supply_detail,
        "doctor_allocations": doctor_allocations,
    }
    # Optional debug: log full distribution details
    dbg = request.args.get("debug")
    if dbg and str(dbg).lower() in ("1", "true", "yes"):
        try:
            print("[hour_detail][DEBUG] payload doctor_allocations:")
            print(
                json.dumps(
                    {
                        "date": date_str,
                        "hour": hour,
                        "expected_total": total_expected,
                        "effective_allocated": matched_supply_detail,
                        "allocations": doctor_allocations,
                    },
                    ensure_ascii=False,
                    default=str,
                )
            )
        except Exception as _e:
            print(f"[hour_detail][DEBUG] logging error: {_e}")
    print(
        f"[hour_detail] response summary: expected={total_expected:.2f}, states={len(by_state_payload)}, on_shift={len(on_shift)}"
    )
    return jsonify(payload)
