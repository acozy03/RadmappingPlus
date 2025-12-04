# app/routes/ingest_capacity.py
from __future__ import annotations
import os, sys, math, csv, traceback
import pandas as pd
from datetime import datetime, date, time as dtime
from collections import defaultdict
from flask import Blueprint, request, jsonify
from dotenv import load_dotenv
from zoneinfo import ZoneInfo
from supabase import create_client, Client

# Optional fuzzy matching
try:
    from fuzzywuzzy import process, fuzz
except ImportError:
    process = None
    fuzz = None
    print("⚠️  fuzzywuzzy not installed. Fuzzy matching disabled.")

# -------------------------------
# Config / Env / Clients
# -------------------------------
load_dotenv()

INGEST_API_KEY = os.environ.get("INGEST_API_KEY") or ""
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SUPER_KEY = os.environ.get("SUPABASE_SUPER_KEY")
DEBUG_CAPACITY_LOG = 1

if not SUPABASE_URL or not SUPABASE_SUPER_KEY:
    print("❌ Missing SUPABASE_URL or SUPABASE_SUPER_KEY in env.", file=sys.stderr)
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SUPER_KEY)

UTC = ZoneInfo("UTC")
EASTERN = ZoneInfo("US/Eastern")  # Handles DST automatically

# Files for optional debugging
HITS_CSV   = "facility_fuzzy_hits.csv"
MISSES_CSV = "facility_fuzzy_misses.csv"
CACHE_CSV  = "facility_match_cache.csv"

# -------------------------------
# Modality RVU map / aliases
# -------------------------------
MODALITY_RVU = {
    "XR": 0.2, "CT": 1.1, "US": 0.5, "MRI": 1.4, "MG": 0.8,
    "NM": 2.5, "PT": 2.5, "IR": 4.0, "RF": 0.7, "SC": 0.6,
    "OT": 0.3, "XA": 0.8, "ECG": 0.2,
}
MODALITY_ALIAS = {
    # X-ray family
    "CR":"XR","DR":"XR","DX":"XR","XR":"XR","X-RAY":"XR","XRAY":"XR","RG":"XR","FS":"XR","FSR":"XR","KO":"XR","FXR":"XR","RAD":"XR","BD":"XR","BDM":"XR",
    # CT
    "CT":"CT","CAT":"CT","IC":"CT",
    # Ultrasound
    "US":"US","ULT":"US","ULTRASOUND":"US","ECHO":"US","IVUS":"US","VU":"US",
    # MRI
    "MR":"MRI","MRI":"MRI",
    # Mammography
    "MG":"MG","MAMMO":"MG","MMG":"MG",
    # Nuclear / PET
    "NM":"NM","PT":"NM","PET":"NM",
    # Interventional / Fluoro, etc.
    "IR":"IR","RF":"RF","SC":"SC","SD":"SC","OT":"OT","XA":"XA",
    # ECG
    "ECG":"ECG"
}

AUTO_ACCEPT_THRESHOLD = 90
SOFT_ACCEPT_MIN = 75

# -------------------------------
# Helpers
# -------------------------------
def norm_text(s: str) -> str:
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return ""
    return " ".join(str(s).strip().upper().split())

def canonical_modality(raw: str) -> str | None:
    t = norm_text(raw)
    if not t:
        return None
    return MODALITY_ALIAS.get(t, t if t in MODALITY_RVU else None)

def parse_time_utc_to_est_hour(full_date_utc: date, time_val) -> tuple[date, int]:
    """
    Take the report's calendar date (full_date_utc) + a time value (string/time/datetime/Excel float)
    and return the corresponding EST (date, hour).

    IMPORTANT: Year/Month/Day from the row is treated as the source of truth for the DATE.
    'time_val' only provides the clock time.
    """
    if isinstance(time_val, datetime):
        # Use ONLY the time component from the datetime, but force the date from full_date_utc.
        hh, mm, ss = time_val.hour, time_val.minute, time_val.second
        dt_utc = datetime(
            full_date_utc.year, full_date_utc.month, full_date_utc.day,
            hh, mm, ss, tzinfo=UTC
        )

    elif isinstance(time_val, dtime):
        # Plain time object → combine with row date
        dt_utc = datetime.combine(full_date_utc, time_val).replace(tzinfo=UTC)

    elif isinstance(time_val, (int, float)) and not math.isnan(time_val):
        # Excel serial time fraction (0–1 of the day)
        seconds = int(round(float(time_val) * 24 * 3600))
        hh = (seconds // 3600) % 24
        mm = (seconds % 3600) // 60
        ss = seconds % 60
        dt_utc = datetime(
            full_date_utc.year, full_date_utc.month, full_date_utc.day,
            hh, mm, ss, tzinfo=UTC
        )

    elif isinstance(time_val, str):
        s = time_val.strip()
        parsed_dt = None

        # Try common time formats first, using ONLY the time portion
        for fmt in ("%I:%M:%S %p", "%H:%M:%S", "%I:%M %p", "%H:%M", "%I %p", "%H"):
            try:
                parsed_dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue

        if parsed_dt is None:
            # Let pandas guess, but only use the time portion,
            # and still force the date from full_date_utc.
            parsed = pd.to_datetime(s, errors="raise")
            hh, mm, ss = parsed.hour, parsed.minute, parsed.second
        else:
            hh, mm, ss = parsed_dt.hour, parsed_dt.minute, parsed_dt.second

        dt_utc = datetime(
            full_date_utc.year, full_date_utc.month, full_date_utc.day,
            hh, mm, ss, tzinfo=UTC
        )

    else:
        raise TypeError(f"Unrecognized time type: {type(time_val)}")

    dt_est = dt_utc.astimezone(EASTERN)
    return dt_est.date(), dt_est.hour



def fetch_facilities_all():
    res = supabase.table("facilities").select("id,name,location").execute()
    data = res.data or []

    all_names: list[tuple[str, str]] = []
    by_norm: dict[str, list[str]] = defaultdict(list)

    for row in data:
        fid = row.get("id")
        nm = row.get("name") or ""
        nm_str = str(nm)
        all_names.append((nm_str, fid))
        by_norm[norm_text(nm_str)].append(fid)

    exact_unique: dict[str, str] = {
        k: v[0] for k, v in by_norm.items() if len(v) == 1
    }

    # ✅ Precompute candidate names once, instead of doing it per row later
    candidate_names = [nm for (nm, _) in all_names]

    print(
        f"📌 Facilities loaded: {len(data)} | "
        f"unique exact-name keys: {len(exact_unique)}"
    )
    return all_names, exact_unique, candidate_names

def load_cache() -> dict:
    cache = {}
    if os.path.exists(CACHE_CSV):
        try:
            df = pd.read_csv(CACHE_CSV)
            for _, r in df.iterrows():
                k = norm_text(r.get("excel_name")); v = r.get("facility_id")
                if k and isinstance(v, str):
                    cache[k] = v
            print(f"🗂️  Loaded cache entries: {len(cache)}")
        except Exception as e:
            print(f"⚠️  Could not read cache file {CACHE_CSV}: {e}")
    return cache

def append_cache(excel_name: str, facility_id: str):
    try:
        write_header = not os.path.exists(CACHE_CSV)
        with open(CACHE_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(["excel_name","facility_id"])
            w.writerow([excel_name, facility_id])
    except Exception as e:
        print(f"⚠️  Could not write cache {CACHE_CSV}: {e}")

def resolve_facility_uuid_name_only(
    excel_name: str,
    all_names: list[tuple[str, str]],
    exact_by_norm_name: dict[str, str],
    cache: dict,
    candidate_names: list[str] | None = None,
) -> tuple[str | None, str | None, int | None, str | None]:
    """
    Returns: (facility_uuid, matched_name, score, decision)
    decision ∈ { 'cache', 'exact', 'fuzzy_auto', 'fuzzy_soft', 'reject', None }
    """
    excel_norm = norm_text(excel_name)
    if not excel_norm:
        return None, None, None, None

    # 1) Cache hit
    if excel_norm in cache:
        return cache[excel_norm], excel_name, 100, "cache"

    # 2) Exact normalized name match
    if excel_norm in exact_by_norm_name:
        return exact_by_norm_name[excel_norm], excel_name, 100, "exact"

    # 3) Fuzzy match (if fuzzywuzzy available)
    if process is None:
        return None, None, None, None

    # ✅ Use precomputed candidate_names if provided
    if candidate_names is None:
        candidate_names = [nm for (nm, _) in all_names]

    best = process.extractOne(excel_name, candidate_names, scorer=fuzz.token_set_ratio)
    if not best:
        return None, None, None, None

    matched_name, score = best
    matched_uuid = next((fid for (nm, fid) in all_names if nm == matched_name), None)
    if matched_uuid is None:
        return None, None, None, None

    if score >= AUTO_ACCEPT_THRESHOLD:
        return matched_uuid, matched_name, int(score), "fuzzy_auto"
    elif score >= SOFT_ACCEPT_MIN:
        return matched_uuid, matched_name, int(score), "fuzzy_soft"
    else:
        return None, matched_name, int(score), "reject"

# -------------------------------
# Ingestion Core (rows → capacity tables)
# -------------------------------
REQUIRED_COLUMNS = [
    "Year", "MonthNum", "Day", "Received Time",
    "Modality", "Priority", "Facility State", "Facility Name"
]

def load_rows_to_capacity_tables(rows: list[dict]):
    """Accepts the DAX result rows (list[dict]) and writes capacity tables."""
    if not rows:
        print("No rows provided.")
        return

    df = pd.DataFrame(rows)

    # ✅ Normalize column names (e.g. "[Year]" → "Year")
    df.rename(columns={c: c.strip("[]") for c in df.columns}, inplace=True)

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Normalize names to what the logic expects
    df.rename(columns={
        "MonthNum": "Date - Month",
        "Facility Name": "Facility Name",
        "Facility State": "Facility State",
        "Received Time": "Received Time",
    }, inplace=True)

    # Coerce types
    df["Date - Month"] = df["Date - Month"].astype(int)
    df["Day"] = df["Day"].astype(int)
    df["Year"] = df["Year"].astype(int)

    _load_df_to_capacity_tables_core(df)


def _load_df_to_capacity_tables_core(df: pd.DataFrame):
    """
    Core ingestion logic.

    IMPORTANT: capacity_per_hour is now derived strictly as the sum of
    facility_capacity_per_hour across all facilities/mods for each (date, hour).
    """
    # Facility-level aggregation
    fac_mod_rvus: dict[tuple[date, int, str, str], float] = defaultdict(float)
    # Tracks which (date, hour) slots we touched (with matched facilities)
    hours_by_date: dict[date, set[int]] = defaultdict(set)

    # ✅ Load facilities & candidate names once
    all_fac_names, exact_by_norm, candidate_names = fetch_facilities_all()
    cache = load_cache()

    fuzzy_hits, fuzzy_misses = [], []

    # Main loop: aggregate facility-level RVUs
    for idx, row in df.iterrows():
        try:
            month_num = int(row.get("Date - Month"))
            day = int(row.get("Day"))
            year = int(row.get("Year"))
            full_date_utc = date(year, month_num, day)

            received_raw = row.get("Received Time")

            est_date, est_hour = parse_time_utc_to_est_hour(
                full_date_utc, received_raw
            )

            modality_raw = row.get("Modality")
            can_mod = canonical_modality(modality_raw)
            if not can_mod:
                if DEBUG_CAPACITY_LOG:
                    print(
                        f"[ROW {idx}] SKIP: no canonical modality | "
                        f"ymd={year}-{month_num:02d}-{day:02d} "
                        f"raw_rec={received_raw!r} est={est_date} {est_hour}:00 "
                        f"mod_raw={modality_raw!r}"
                    )
                continue

            rvu = float(MODALITY_RVU.get(can_mod, 0.0))

            excel_fac_name = row.get("Facility Name")
            if pd.isna(excel_fac_name) or not str(excel_fac_name).strip():
                fuzzy_misses.append({
                    "row": idx,
                    "excel_name": str(excel_fac_name),
                    "score": None,
                    "reason": "Missing Facility Name",
                })
                continue

            facility_uuid, matched_name, score, decision = resolve_facility_uuid_name_only(
                str(excel_fac_name), all_fac_names, exact_by_norm, cache, candidate_names
            )

            if not facility_uuid:
                # No facility match → no contribution to facility or global totals.
                fuzzy_misses.append({
                    "row": idx,
                    "excel_name": str(excel_fac_name),
                    "matched_db_name": matched_name,
                    "score": score,
                    "reason": "Rejected < threshold or no match",
                })
                continue

            # Facility + modality aggregation
            fac_mod_rvus[(est_date, est_hour, facility_uuid, can_mod)] += rvu
            hours_by_date[est_date].add(est_hour)

            # Update cache on good decisions
            if decision in {"cache", "exact", "fuzzy_auto", "fuzzy_soft"}:
                key = norm_text(str(excel_fac_name))
                if key not in cache:
                    cache[key] = facility_uuid
                    append_cache(str(excel_fac_name), facility_uuid)

            if decision in {"fuzzy_auto", "fuzzy_soft"}:
                fuzzy_hits.append({
                    "row": idx,
                    "excel_name": str(excel_fac_name),
                    "matched_db_name": matched_name,
                    "score": score,
                    "decision": decision,
                    "facility_id": facility_uuid,
                })

            if DEBUG_CAPACITY_LOG:
                print(
                    f"[ROW {idx}] FAC_AGG | "
                    f"source_date={year}-{month_num:02d}-{day:02d} "
                    f"raw_rec={received_raw!r} "
                    f"→ est_date={est_date}, est_hour={est_hour}, "
                    f"facility={facility_uuid}, modality={can_mod}, rvu={rvu}"
                )

        except Exception as e:
            print(f"[!] Skipping row {idx} due to error: {e}")
            continue

    # ---------------------------
    # Derive global rvus_by_hour from facility aggregates
    # ---------------------------
    rvus_by_hour: dict[tuple[date, int], float] = defaultdict(float)
    for (est_date_, est_hour, facility_id, modality), total_rvus in fac_mod_rvus.items():
        rvus_by_hour[(est_date_, est_hour)] += total_rvus

    # ---------------------------
    # Global deletes / inserts
    # ---------------------------
    for est_date_, hours in hours_by_date.items():
        hours_list = sorted(hours)
        print(f"🧹 (global) Deleting {len(hours_list)} hour slot(s) for {est_date_}: {hours_list}")
        supabase.table("capacity_per_hour") \
            .delete() \
            .eq("date", str(est_date_)) \
            .in_("hour", hours_list) \
            .execute()

    global_rows = []
    for (est_day, est_hour), total_rvus in rvus_by_hour.items():
        row_obj = {
            "date": str(est_day),
            "hour": int(est_hour),
            "total_rvus": round(float(total_rvus), 2),
        }
        global_rows.append(row_obj)

        if DEBUG_CAPACITY_LOG:
            print(
                f"[GLOBAL_CAPACITY_ROW] date={row_obj['date']} "
                f"hour={row_obj['hour']} total_rvus={row_obj['total_rvus']}"
            )

    if global_rows:
        res = supabase.table("capacity_per_hour").insert(global_rows).execute()
        print(f"✅ (global) Inserted {len(global_rows)} capacity_per_hour rows")
        if getattr(res, "error", None):
            print("⚠️ capacity_per_hour insert error:", res.error)

    # ---------------------------
    # Facility deletes / inserts
    # ---------------------------
    # Delete ALL facilities for any (date, hour) we touched
    for est_date_, hours in hours_by_date.items():
        hours_list = sorted(hours)
        print(
            f"🧹 (facility) Deleting ALL facilities for date={est_date_}, "
            f"hours={hours_list}"
        )
        supabase.table("facility_capacity_per_hour") \
            .delete() \
            .eq("date", str(est_date_)) \
            .in_("hour", hours_list) \
            .execute()

    # Batch insert for facility_capacity_per_hour
    facility_rows = [
        {
            "date": str(est_date_),
            "hour": int(est_hour),
            "facility_id": facility_id,
            "modality": modality,
            "total_rvus": round(float(total_rvus), 2),
        }
        for (est_date_, est_hour, facility_id, modality), total_rvus
        in fac_mod_rvus.items()
    ]

    if facility_rows:
        res = supabase.table("facility_capacity_per_hour").insert(facility_rows).execute()
        print(f"✅ (facility) Inserted {len(facility_rows)} facility_capacity_per_hour rows")
        if getattr(res, "error", None):
            print("⚠️ facility_capacity_per_hour insert error:", res.error)

    # ---------------------------
    # Fuzzy logs
    # ---------------------------
    if fuzzy_hits:
        pd.DataFrame(fuzzy_hits).to_csv(HITS_CSV, index=False)
    if fuzzy_misses:
        pd.DataFrame(fuzzy_misses).to_csv(MISSES_CSV, index=False)

    print("\n🎯 Done. Global + facility-by-modality tables updated.\n")
