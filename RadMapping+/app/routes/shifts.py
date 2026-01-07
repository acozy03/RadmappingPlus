# RadMapping+/app/routes/shifts.py

from flask import Blueprint, render_template, session, request, jsonify
import json
from datetime import datetime, timedelta
from collections import defaultdict
from app.supabase_client import get_supabase_client
from app.middleware import with_supabase_auth
from calendar import monthrange
from app.supabase_helper import fetch_all_rows

shifts_bp = Blueprint('shifts', __name__)
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

def get_rvu_bg_color_class(ratio):
    if ratio is not None:
        if ratio < 0.5:
            return 'bg-red-50'
        elif ratio < 0.7:
            return 'bg-red-200'
        elif ratio <= 1.0:
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

# Soft-preference tuning: modalities with a weight below this threshold are
# treated as "last resort" for allocation. We still allow allocating to them
# if nothing else can take the chunk, but we prefer higher-weight modalities.
SOFT_WEIGHT_THRESHOLD = 0.01  # 1%

def modality_chunk(mod):
    if not mod:
        return 0.2
    return float(MODALITY_RVU.get(str(mod).upper(), 0.2))

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


    metrics_res = supabase.table("rad_metrics").select("radiologist_id,rvu,volatility").execute()
    metrics_rows = {row["radiologist_id"]: row for row in (metrics_res.data or [])}

    all_hour_slots = [slot for day_slots in hour_slots_by_day.values() for slot in day_slots]

    prev_dates_hours_map = {}
    for slot in all_hour_slots:
        prev_date_str, prev_hour_int = get_prev_week_same_day_and_hour(slot["datetime"])
        if prev_date_str is not None:
            prev_dates_hours_map[(slot["datetime"], (prev_date_str, prev_hour_int))] = True

    unique_prev_keys = list({pair for _, pair in prev_dates_hours_map.keys()})

    # Paginate capacity_per_hour by date to avoid 1000 row limit
    cap_dates = [d for d, _ in unique_prev_keys] or ["1900-01-01"]
    cap_rows_all = []
    _offset = 0
    _batch = 1000
    while True:
        _res = (
            supabase
            .table("capacity_per_hour")
            .select("date", "hour", "total_rvus")
            .in_("date", cap_dates)
            .range(_offset, _offset + _batch - 1)
            .execute()
        )
        _data = _res.data or []
        cap_rows_all.extend(_data)
        if len(_data) < _batch:
            break
        _offset += _batch

    historical_rvu_lookup = {}
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
        historical_rvu_lookup[(d, h_int)] = row.get("total_rvus")

    # --- New effective capacity computation ---
    # We will estimate per-hour supply by allocating each on-shift doctor's
    # overall RVU across state/modality demand using their modality mix
    # and licensure constraints. Demand source = same day+hour
    # capacity_per_hour_breakdown distribution.

    # 1) Prefetch state/modality demand rows for all (date,hour) pairs
    prev_dates = list({d for d, _ in unique_prev_keys})
    prev_hours = list({h for _, h in unique_prev_keys})
    # Note: some deployments store the "hour" column as text. Using an IN filter with
    # integer hours can silently return no rows, which makes weekly tiles show 0 even
    # though per-hour modal fallback finds day data.
    # To avoid type-mismatch issues, prefetch by date only and handle hours in-memory.
    breakdown_rows_all = []
    if prev_dates:
        _offset = 0
        _batch = 1000
        while True:
            _res = (
                supabase
                .table("capacity_per_hour_breakdown")
                .select("date,hour,state,modality,total_rvus")
                .in_("date", prev_dates)
                .range(_offset, _offset + _batch - 1)
                .execute()
            )
            _data = _res.data or []
            breakdown_rows_all.extend(_data)
            if len(_data) < _batch:
                break
            _offset += _batch

    # Robust hour parser: handle numeric, zero-padded strings, and float-ish strings
    def parse_hour(val):
        try:
            if isinstance(val, (int, float)):
                return int(val)
            s = str(val).strip()
            if not s:
                return None
            if "." in s:
                s = s.split(".")[0]
            return int(s)
        except Exception:
            return None

    # Group by (date,hour) and by date (for nearest-hour fallback)
    breakdown_by_date_hour = defaultdict(list)
    breakdown_by_date = defaultdict(list)
    for r in breakdown_rows_all:
        h = parse_hour(r.get("hour"))
        d = r.get("date")
        if d is None:
            continue
        if h is not None:
            breakdown_by_date_hour[(d, h)].append(r)
        breakdown_by_date[d].append(r)

    # Optional debug: summarize fetched rows per date
    dbg = request.args.get('debug')
    if dbg and str(dbg).lower() in ("1", "true", "yes"):
        try:
            from collections import Counter
            fac_counts = Counter([r.get("date") for r in breakdown_rows_all])
            cap_counts = Counter([k[0] for k in historical_rvu_lookup.keys()])
            print(f"[shifts][DEBUG] capacity_per_hour_breakdown counts: {dict(fac_counts)}")
            print(f"[shifts][DEBUG] capacity_per_hour dates present: {sorted(set(cap_counts.elements()))}")
        except Exception as _e:
            print(f"[shifts][DEBUG] counting error: {_e}")

    # 2) Prefetch authorizations, certifications, and modality weights for any doctor on this week
    week_doctor_ids = list({d['id'] for d in doctors_on_shift if d.get('id') is not None})

    # Certifications by state
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

    alloc_doctor_states = defaultdict(set)  # doctor_id -> set(state_code)
    if week_doctor_ids:
        cert_all = (
            supabase
            .table("certifications")
            .select("radiologist_id,state")
            .in_("radiologist_id", week_doctor_ids)
            .execute()
        )
        for c in (cert_all.data or []):
            rid = c.get("radiologist_id")
            st = to_state_code(c.get("state"))
            if rid is not None and st:
                alloc_doctor_states[rid].add(st)

    # Modality weights: attempt common table names; fall back to empty
    modality_weights = {}
    if week_doctor_ids:
        def try_fetch_weights(table_name):
            try:
                res = (
                    supabase
                    .table(table_name)
                    .select("radiologist_id,modality_weights")
                    .in_("radiologist_id", week_doctor_ids)
                    .execute()
                )
                return res.data or []
            except Exception:
                return []

        weight_rows = []
        for t in ("radiologist_modality_weights", "modality_weights", "rad_modality_weights"):
            if not weight_rows:
                weight_rows = try_fetch_weights(t)
        for row in weight_rows:
            rid = row.get("radiologist_id")
            if rid is None:
                continue
            parsed = extract_modality_weights(row)
            if parsed:
                modality_weights[rid] = parsed

    # Helper: allocate supply for a given slot
    def compute_effective_supply(slot_dt):
        # Demand groups for same day+hour
        prev_date_str, prev_hour_int = get_prev_week_same_day_and_hour(slot_dt)
        historical_rvu = None
        if prev_date_str is not None:
            historical_rvu = historical_rvu_lookup.get((prev_date_str, prev_hour_int))
        demand_rows = breakdown_by_date_hour.get((prev_date_str, prev_hour_int), [])
        scale_factor = 1.0
        if not demand_rows:
            # nearest hour on same date fallback
            day_rows = breakdown_by_date.get(prev_date_str, [])
            if day_rows:
                by_hour = defaultdict(list)
                for r in day_rows:
                    ph = parse_hour(r.get("hour"))
                    if ph is None:
                        continue
                    by_hour[ph].append(r)
                if by_hour:
                    hours_available = sorted(by_hour.keys())
                    nearest_hour = min(hours_available, key=lambda h: abs(h - prev_hour_int))
                    demand_rows = by_hour.get(nearest_hour, [])
                    # scale distribution to expected total for target hour
                    hist_total = historical_rvu_lookup.get((prev_date_str, prev_hour_int))
                    sum_nearest = sum(float(x.get("total_rvus") or 0) for x in demand_rows)
                    if hist_total is not None and sum_nearest > 0:
                        scale_factor = float(hist_total) / float(sum_nearest)

        # Build group list: (state_code, modality, base_demand, remaining_demand)
        groups = []
        for r in demand_rows:
            mod = (r.get("modality") or "").upper() or None
            dem = float(r.get("total_rvus") or 0) * scale_factor
            st = to_state_code(r.get("state"))
            if dem <= 0:
                continue
            groups.append({
                "state": st,
                "mod": mod,
                # Keep the original demand as base for proportional distribution,
                # even if we allow overfilling beyond historical demand.
                "base": dem,
                "remaining": dem
            })

        # Prepare doctor list for this slot
        slot_doctors = doctors_by_hour.get(slot_dt, [])

        # Per-doctor RVU base from monthly averages
        demand_modality_weights = derive_demand_modality_weights(demand_rows)
        uniform_weights = uniform_modality_weights()

        def doc_rvu(did):
            rr = metrics_rows.get(did, {})
            try:
                base_rvu = float(rr.get("rvu") or 0)
            except Exception:
                base_rvu = 0.0
            try:
                volatility = float(rr.get("volatility") or 0)
            except Exception:
                volatility = 0.0
            conversion_weights = get_doc_modality_weights(modality_weights, did, slot_dt)
            if not conversion_weights:
                conversion_weights = demand_modality_weights or uniform_weights
            return adjusted_rvu_from_metrics(base_rvu, volatility, conversion_weights, "normal")

        # Multi-pass allocation with rebalancing across modalities
        matched_supply = 0.0
        if not groups or not slot_doctors:
            return historical_rvu, 0.0

        # Index groups by modality for quick access and initialize per-group gap
        groups_by_mod = defaultdict(list)
        for g in groups:
            g["gap"] = float(g.get("base", 0.0))
            groups_by_mod[g["mod"]].append(g)

        EPS = 1e-6

        for d in slot_doctors:
            did = d.get("id")
            if did is None:
                continue
            base = float(doc_rvu(did))
            if base <= 0:
                continue

            remaining_cap = base

            # Determine licensed states
            lic_states = alloc_doctor_states.get(did, set())

            # Doctor modality distribution; if missing, spread uniformly over present modalities
            base_weights = get_doc_modality_weights(modality_weights, did, slot_dt)
            if not base_weights:
                mods_present = {g["mod"] for g in groups if g["mod"]}
                if mods_present:
                    w = 1.0 / len(mods_present)
                    base_weights = {m: w for m in mods_present}
                else:
                    base_weights = {}

            # PASS 1: coverage-first with soft modality preferences.
            # Prefer modalities with higher doctor weight; fall back if none fit.
            while remaining_cap > EPS:
                # Build total gap per modality limited to whole chunks and eligibility
                gap_by_mod = {}
                for mod, lst in groups_by_mod.items():
                    ch = modality_chunk(mod)
                    if ch <= EPS:
                        continue
                    gap_sum = 0.0
                    for g in lst:
                        if not g["state"] or g["state"] in lic_states:
                            gap = float(g.get("gap", 0.0))
                            if gap + EPS >= ch:
                                gap_sum += gap
                    if gap_sum > EPS:
                        gap_by_mod[mod] = gap_sum
                if not gap_by_mod:
                    break
                # pick modality using weighted score (gap * weight),
                # preferring weights >= SOFT_WEIGHT_THRESHOLD first
                def pick_mod(prefer_threshold=True):
                    candidates = list(gap_by_mod.keys())
                    if prefer_threshold:
                        preferred = [m for m in candidates if (base_weights.get(m, 0.0) >= SOFT_WEIGHT_THRESHOLD)]
                        if preferred:
                            candidates = preferred
                    # score: gap * max(weight, tiny)
                    def score(m):
                        w = base_weights.get(m, 0.0)
                        return gap_by_mod[m] * (w if w > 0 else 1e-9)
                    return max(candidates, key=score)

                try:
                    sel_mod = pick_mod(True)
                except ValueError:
                    # no candidates after thresholding; fall back to any
                    sel_mod = pick_mod(False)
                ch = modality_chunk(sel_mod)
                if remaining_cap + EPS < ch:
                    break
                # choose group with max gap within modality that fits a chunk
                candidates = [
                    g for g in groups_by_mod.get(sel_mod, [])
                    if (not g["state"] or g["state"] in lic_states) and (float(g.get("gap", 0.0)) + EPS >= ch)
                ]
                if not candidates:
                    # nothing fits in this modality; remove and continue
                    del gap_by_mod[sel_mod]
                    if not gap_by_mod:
                        break
                    continue
                best = max(candidates, key=lambda gg: float(gg.get("gap", 0.0)))
                best["gap"] = max(0.0, float(best.get("gap", 0.0)) - ch)
                matched_supply += ch
                remaining_cap -= ch

            # PASS 2: overflow with coverage-aware round-robin and soft preferences
            if remaining_cap > EPS:
                OVERFILL_CAP_R = 1.5  # do not overflow a group beyond 150% coverage
                # track per-doctor per-group chunk count to avoid spamming one target
                per_group_chunks = {}
                MAX_CHUNKS_PER_GROUP_PER_DOC = 3
                while remaining_cap > EPS:
                    # gather candidates across all modalities the doctor is eligible for and that fit a chunk
                    def pick_overflow(allow_low_weight: bool):
                        best = (None, None, None)
                        best_score = None
                        for mod, lst in groups_by_mod.items():
                            w = base_weights.get(mod, 0.0)
                            if (w < SOFT_WEIGHT_THRESHOLD) and not allow_low_weight:
                                continue
                            ch = modality_chunk(mod)
                            if remaining_cap + EPS < ch:
                                continue
                            for g in lst:
                                if g.get("state") and g.get("state") not in lic_states:
                                    continue
                                base_val = float(g.get("base", 0.0))
                                if base_val <= EPS:
                                    continue
                                over = float(g.get("overfill", 0.0))
                                gap = float(g.get("gap", 0.0))
                                covered = max(0.0, base_val - gap) + over
                                R = covered / max(base_val, EPS)
                                if R >= OVERFILL_CAP_R - 1e-9:
                                    continue
                                key = (g["state"], mod)
                                if per_group_chunks.get(key, 0) >= MAX_CHUNKS_PER_GROUP_PER_DOC:
                                    continue
                                # Prefer lower coverage; tie-break by weight (higher is better)
                                score = (R, -w)
                                if best_score is None or score < best_score:
                                    best_score = score
                                    best = (g, mod, ch)
                        return best

                    g = mod = None
                    # First try with weight threshold
                    g, mod, best_ch = pick_overflow(False)
                    if g is None:
                        # Fallback: allow low-weight modalities as last resort
                        g, mod, best_ch = pick_overflow(True)
                    if g is None:
                        break
                    g["overfill"] = float(g.get("overfill", 0.0)) + best_ch
                    # Also reduce gap if any remains (keeps coverage monotonic up)
                    if g.get("gap", 0.0) > 0:
                        g["gap"] = max(0.0, float(g.get("gap", 0.0)) - best_ch)
                    matched_supply += best_ch
                    remaining_cap -= best_ch
                    key = (g["state"], mod)
                    per_group_chunks[key] = per_group_chunks.get(key, 0) + 1

        return historical_rvu, matched_supply

    # Compute per-slot historical expected and new current (effective supply)
    hourly_rvu_stats = {}
    for slot in all_hour_slots:
        slot_dt = slot["datetime"]
        hist, eff = compute_effective_supply(slot_dt)
        hourly_rvu_stats[slot_dt] = {"historical": hist, "current": eff}

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
                    if breakdown_by_date_hour.get((prev_d, prev_h)) or breakdown_by_date.get(prev_d):
                        with_demand += 1
                print(f"[shifts][DEBUG] {day.isoformat()} tiles={tiles} doctors_hours={with_docs} demand_hours={with_demand}")
        except Exception as _e:
            print(f"[shifts][DEBUG] per-day summary error: {_e}")

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


@shifts_bp.route('/shifts/hour_detail', methods=["GET", "POST"])
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
        date_str = payload.get('date')
        hour = payload.get('hour')
        try:
            hour = int(hour) if hour is not None else None
        except Exception:
            hour = None
        bo = payload.get('base_overrides') or {}
        distribution_mode = payload.get("distribution_mode") or "normal"
        # Normalize override keys to str for consistent lookups
        if isinstance(bo, dict):
            try:
                base_overrides = {str(k): float(v) for k, v in bo.items() if v is not None}
            except Exception:
                base_overrides = {str(k): v for k, v in bo.items()}
    else:
        date_str = request.args.get('date')
        hour = request.args.get('hour', type=int)
        distribution_mode = request.args.get("distribution_mode") or "normal"
        # Optional overrides via query string as JSON: overrides={"doc_id": 0}
        try:
            import json as _json
            q_over = request.args.get('overrides')
            if q_over:
                d = _json.loads(q_over)
                if isinstance(d, dict):
                    base_overrides = {str(k): float(v) for k, v in d.items() if v is not None}
        except Exception:
            base_overrides = {}
    if not date_str or hour is None:
        return jsonify({"error": "Missing date or hour"}), 400

    distribution_mode = str(distribution_mode or "normal").lower()
    if distribution_mode not in ("worst", "normal", "best"):
        distribution_mode = "normal"

    # 1) State/modality demand for this hour (EXPECTED = same day/hour)
    prev_date_str, prev_hour_int = get_prev_week_same_day_and_hour(
        datetime.strptime(f"{date_str} {hour:02d}:00:00", "%Y-%m-%d %H:%M:%S")
    )
    print(f"[hour_detail] incoming date={date_str} hour={hour}; expected_source date={prev_date_str} hour={prev_hour_int}")
    breakdown_res = (
        supabase
        .table("capacity_per_hour_breakdown")
        .select("state,total_rvus,modality")
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
        print("[hour_detail] No breakdown rows found for expected HOUR. Attempting nearest-hour fallback on same date…")

        # Fetch day data and group by hour
        day_res = (
            supabase
            .table("capacity_per_hour_breakdown")
            .select("state,total_rvus,modality,hour")
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
            fallback_info = {"used": True, "source": {"date": prev_date_str, "hour": nearest_hour}, "reason": "nearest_hour_same_date"}
            print(f"[hour_detail] Fallback using nearest hour {nearest_hour} with {len(breakdown_rows)} rows.")
        else:
            print("[hour_detail] No breakdown rows for any hour on the date; returning empty payload.")
            return jsonify({
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
                "doctor_allocations": []
            })

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

    # 4) RVU supply numbers based on metrics (same logic as page)
    metrics_res = supabase.table("rad_metrics").select("radiologist_id,rvu,volatility").execute()
    metrics_rows = {row["radiologist_id"]: row for row in (metrics_res.data or [])}

    # 5) Modality weights for doctors on this hour
    modality_weights = {}
    if doctor_ids:
        def try_fetch_weights(table_name):
            try:
                res = (
                    supabase
                    .table(table_name)
                    .select("radiologist_id,modality_weights")
                    .in_("radiologist_id", doctor_ids)
                    .execute()
                )
                return res.data or []
            except Exception:
                return []
        weight_rows = []
        for t in ("radiologist_modality_weights", "modality_weights", "rad_modality_weights"):
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
        return adjusted_rvu_from_metrics(base_rvu, volatility, weights, distribution_mode)

    demand_modality_weights = derive_demand_modality_weights(breakdown_rows)
    uniform_weights = uniform_modality_weights()

    supply_overall = 0
    for d in on_shift:
        did = d.get("id")
        conversion_weights = get_doc_modality_weights(modality_weights, did, window_start)
        if not conversion_weights:
            conversion_weights = demand_modality_weights or uniform_weights
        rr = metrics_rows.get(did)
        supply_overall += latest_nonzero_rvu(rr, conversion_weights, distribution_mode)

    # Helper to normalize state values to 2-letter codes
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
    licensed_ids = set()
    licensed_by_state = defaultdict(set)
    if doctor_ids:
        # Do not filter by state here; certs may be stored as names or codes.
        cert_res = (
            supabase
            .table("certifications")
            .select("radiologist_id,state")
            .in_("radiologist_id", doctor_ids)
            .execute()
        )
        print(f"[hour_detail] certifications rows: {len(cert_res.data or [])}")
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
            did = d.get("id")
            conversion_weights = get_doc_modality_weights(modality_weights, did, window_start)
            if not conversion_weights:
                conversion_weights = demand_modality_weights or uniform_weights
            rr = metrics_rows.get(did)
            supply_licensed += latest_nonzero_rvu(rr, conversion_weights, distribution_mode)

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
        by_state_payload.append({
            "state": st,
            "modality": mod,
            "expected_rvus": float(total)
        })

    by_state_merged_payload = [
        {"state": st, "expected_rvus": float(total)} for st, total in by_state_totals.items()
        if total > 0
    ]
    by_modality_payload = [
        {"modality": m, "expected_rvus": float(v)} for m, v in by_modality_totals.items()
        if v > 0
    ]

    # If we used fallback from a different hour, optionally scale to match the expected total
    # from capacity_per_hour for the requested hour.
    total_expected = float(sum((float(r.get("total_rvus") or 0) for r in breakdown_rows)))
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
            print(f"[hour_detail] Applying scale factor {scale:.4f} to fallback breakdown rows")
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
    scale_factor = float(fallback_info.get("scale_factor") or 1.0) if fallback_info.get("used") and fallback_info.get("scaled_to_expected") else 1.0
    for row in breakdown_rows:
        mod = (row.get("modality") or "").upper() or None
        remaining = float(row.get("total_rvus") or 0) * scale_factor
        st = to_state_code(row.get("state"))
        groups.append({
            "state": st,
            "mod": mod,
            # Preserve original demand as base for proportional distribution
            "base": remaining,
            "remaining": remaining
        })
    # Index groups by modality
    groups_by_mod = defaultdict(list)
    for g in groups:
        groups_by_mod[g["mod"]].append(g)

    doctor_allocations = []
    ALLOCATION_EPS = 0.0  # include all allocations; UI filters small values for display
    matched_supply_detail = 0.0
    # Helper to get doc base RVU
    def latest_nonzero_rvu(rr, weights, distribution_mode):
        if not rr:
            return 0.0
        return adjusted_rvu_from_metrics(rr.get("rvu"), rr.get("volatility"), weights, distribution_mode)

    # Iterate doctors on this hour
    EPS = 1e-6
    for d in on_shift:
        did = d.get("id")
        name = d.get("name")
        rr = metrics_rows.get(did) if did is not None else None
        conversion_weights = get_doc_modality_weights(modality_weights, did, window_start)
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
                base = adjusted_rvu_from_metrics(ov, rr.get("volatility") if rr else 0.0, conversion_weights, distribution_mode)
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
                    preferred = [m for m in mods if (doc_weights.get(m, 0.0) >= SOFT_WEIGHT_THRESHOLD)]
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
                    "modality": (sel_mod or "")
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
                            if per_group_chunks.get(key, 0) >= MAX_CHUNKS_PER_GROUP_PER_DOC:
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
                        "modality": (mod or "")
                    }

        # Materialize aggregated allocations and filter small values
        allocs = []
        for key, amt in per_key_amounts.items():
            meta = per_key_meta.get(key, {})
            allocs.append({
                **meta,
                "allocated_rvus": float(amt)
            })

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

        doctor_allocations.append({
            "id": did,
            "name": name,
            "base_rvu": base,
            "original_base_rvu": original_base,
            "contributing_rvus": contributed,
            "unused_rvus": max(0.0, float(base - contributed)),
            "allocations": allocs,
            "modality_weights": mw_list
        })

    algorithm_summary = [
        "Start with same day/hour state+modality RVU demand.",
        "For each on-shift doctor, take latest non-zero monthly RVU as hourly base.",
        "Split the base by the doctor’s modality weights (normalized).",
        "Within each modality portion, allocate across states where the doctor is licensed.",
        "Cap each state/modality allocation at remaining demand so supply never exceeds demand.",
        "Effective supply is the sum of all allocated RVUs across doctors."
    ]

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
        "applied_overrides": base_overrides,
        "total_expected_rvus": total_expected,
        "by_state": by_state_payload,
        "by_state_merged": by_state_merged_payload,
        "by_modality": by_modality_payload,
        "state_breakdown": state_breakdown_list,
        "modality_breakdown": modality_breakdown_list,
        "supply_overall_rvus": supply_overall,
        "supply_licensed_rvus": supply_licensed,
        "supply_effective_allocated_rvus": matched_supply_detail,
        "doctor_allocations": doctor_allocations
    }
    # Optional debug: log full distribution details
    dbg = request.args.get('debug')
    if dbg and str(dbg).lower() in ("1", "true", "yes"): 
        try:
            print("[hour_detail][DEBUG] payload doctor_allocations:")
            print(json.dumps({
                "date": date_str,
                "hour": hour,
                "expected_total": total_expected,
                "effective_allocated": matched_supply_detail,
                "allocations": doctor_allocations
            }, ensure_ascii=False, default=str))
        except Exception as _e:
            print(f"[hour_detail][DEBUG] logging error: {_e}")
    print(f"[hour_detail] response summary: expected={total_expected:.2f}, states={len(by_state_payload)}, on_shift={len(on_shift)}")
    return jsonify(payload)
