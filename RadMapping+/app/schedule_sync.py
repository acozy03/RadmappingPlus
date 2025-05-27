def run_google_sheet_sync(sheet_name: str = "March 2025"):
    import gspread
    from datetime import datetime, timedelta
    from dateutil import parser
    from supabase import create_client, Client
    import uuid
    from rapidfuzz import process
    import re
    import calendar
    from collections import defaultdict
    from app.supabase_client import get_supabase_client
    import google.auth
    import os 

    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SUPER_KEY", "").strip()

    supabase: Client = create_client(url, key)
    
    creds, _ = google.auth.default()
    gc = gspread.authorize(creds)

    sh = gc.open("Rad Monthy Schedule ")
    worksheet = sh.worksheet(sheet_name)

        # === Load Sheet Data ===
    data = worksheet.get_all_values()
    headers = data[0]
    rows = data[1:]

    # === Load Radiologists from Supabase ===
    radiologists = supabase.table("radiologists").select("id", "name").execute().data
    if not radiologists:
        raise RuntimeError("❌ No radiologists found in Supabase. Check your database and auth tokens.")


    name_map = {r["name"].strip(): r["id"] for r in radiologists}
    name_list = list(name_map.keys())

    # === Helpers ===
    keywords = {"OFF", "VACATION", "REACH AS NEEDED"}
    time_pattern = re.compile(
        r'(\d{1,2}(?::?\d{2})?\s*(?:am|pm))\s*[-–—]\s*(\d{1,2}(?::?\d{2})?\s*(?:am|pm))',
        re.IGNORECASE
    )

    def parse_time(t):
        t = t.lower().replace(" ", "")
        for fmt in ("%I%p", "%I:%M%p", "%I%M%p"):
            try:
                return datetime.strptime(t, fmt).time()
            except ValueError:
                continue
        return None

    def extract_all_times(cell_value):
        times = []
        for match in time_pattern.finditer(cell_value):
            start_time = parse_time(match.group(1))
            end_time = parse_time(match.group(2))
            if start_time and end_time:
                times.extend([start_time, end_time])
        return times

    # === Parse Logic ===
    schedule_rows = []

    for row_idx, row in enumerate(rows):
        if not row or len(row) < 2 or not row[1].strip():
            continue

        raw_name = row[1].split("-")[0].strip()
        result = process.extractOne(raw_name, name_list)
        if result:
            # Handle both 2-tuple and 3-tuple return formats from RapidFuzz
            match, score = result[:2]
            if score < 80:
                print(f"[Row {row_idx}] Low-confidence match for: '{raw_name}' → '{match}' (score: {score})")
                continue
            rad_id = name_map[match]
        else:
            print(f"[Row {row_idx}] No match found for: '{raw_name}'")
            continue


        for col_idx, cell in enumerate(row[2:], start=2):
            cell_value = str(cell).strip()
            if not cell_value:
                continue

            date_str = headers[col_idx]
            try:
                date = parser.parse(date_str).date()
            except Exception:
                print(f"Skipping invalid date header: {date_str}")
                continue

            upper_val = cell_value.upper()
            times = extract_all_times(cell_value)
            
            if len(times) == 2:
                # Regular shift: start_time to end_time
                start_time, end_time = times
                crosses_midnight = datetime.combine(date, end_time) < datetime.combine(date, start_time)
                end_date = date + timedelta(days=1) if crosses_midnight else date
                schedule_rows.append({
                    "id": str(uuid.uuid4()),
                    "radiologist_id": rad_id,
                    "start_date": date.isoformat(),
                    "start_time": start_time.strftime("%H:%M:%S"),
                    "end_date": end_date.isoformat(),
                    "end_time": end_time.strftime("%H:%M:%S"),
                    "break_start": None,
                    "break_end": None,
                    "schedule_details": cell_value,
                })
            elif len(times) == 3:
                # Sort times and use first and last times, ignore middle time
                sorted_times = sorted(times)
                start_time, _, end_time = sorted_times
                crosses_midnight = datetime.combine(date, end_time) < datetime.combine(date, start_time)
                end_date = date + timedelta(days=1) if crosses_midnight else date
                schedule_rows.append({
                    "id": str(uuid.uuid4()),
                    "radiologist_id": rad_id,
                    "start_date": date.isoformat(),
                    "start_time": start_time.strftime("%H:%M:%S"),
                    "end_date": end_date.isoformat(),
                    "end_time": end_time.strftime("%H:%M:%S"),
                    "break_start": None,
                    "break_end": None,
                    "schedule_details": cell_value,
                })
            elif len(times) == 4:
                # Sort times and use them as start_time, break_start, break_end, end_time
                sorted_times = sorted(times)
                start_time, break_start, break_end, end_time = sorted_times
                crosses_midnight = datetime.combine(date, end_time) < datetime.combine(date, start_time)
                end_date = date + timedelta(days=1) if crosses_midnight else date
                schedule_rows.append({
                    "id": str(uuid.uuid4()),
                    "radiologist_id": rad_id,
                    "start_date": date.isoformat(),
                    "start_time": start_time.strftime("%H:%M:%S"),
                    "end_date": end_date.isoformat(),
                    "end_time": end_time.strftime("%H:%M:%S"),
                    "break_start": break_start.strftime("%H:%M:%S"),
                    "break_end": break_end.strftime("%H:%M:%S"),
                    "schedule_details": cell_value,
                })
            elif any(kw in upper_val for kw in keywords):
                schedule_rows.append({
                    "id": str(uuid.uuid4()),
                    "radiologist_id": rad_id,
                    "start_date": date.isoformat(),
                    "start_time": None,
                    "end_date": date.isoformat(),
                    "end_time": None,
                    "break_start": None,
                    "break_end": None,
                    "schedule_details": cell_value.title(),
                })
            else:
                # Insert unrecognized content with schedule details
                print(f"⚠️ Unrecognized content, inserting anyway: '{cell_value}' (Row {row_idx}, Col {col_idx})")
                schedule_rows.append({
                    "id": str(uuid.uuid4()),
                    "radiologist_id": rad_id,
                    "start_date": date.isoformat(),
                    "start_time": None,
                    "end_date": date.isoformat(),
                    "end_time": None,
                    "break_start": None,
                    "break_end": None,
                    "schedule_details": cell_value,
                })

    # === Print debug sample ===
    reverse_name_map = {v: k for k, v in name_map.items()}
    parsed_by_doctor = defaultdict(list)
    for row in schedule_rows:
        doc_name = reverse_name_map.get(row["radiologist_id"], "Unknown")
        parsed_by_doctor[doc_name].append(row)

    # print("\n===== DEBUG: First 3 parsed shifts per doctor =====")
    # for doc_name, shifts in parsed_by_doctor.items():
    #     print(f"\nDoctor: {doc_name}")
    #     for shift in shifts[:3]:
    #         print(f"  - Start: {shift['start_date']} {shift['start_time']}, End: {shift['end_date']} {shift['end_time']}, Details: {shift['schedule_details']}")

    # === Delete existing entries for the month ===
    sheet_title = worksheet.title.strip()
    try:
        month_name, year = sheet_title.split()
        month_num = list(calendar.month_name).index(month_name)
        year = int(year)
        first_day = datetime(year, month_num, 1).date()
        last_day = datetime(year, month_num, calendar.monthrange(year, month_num)[1]).date()

        supabase.table("monthly_schedule") \
            .delete() \
            .gte("start_date", first_day.isoformat()) \
            .lte("start_date", last_day.isoformat()) \
            .execute()
        print(f"Old entries for {sheet_title} deleted.")
    except Exception as e:
        print(f"❌ Failed to parse month from sheet title '{sheet_title}': {e}")

    # === Insert parsed rows ===
    if schedule_rows:
        print("Fields in first row:", schedule_rows[0].keys())
        supabase.table("monthly_schedule").insert(schedule_rows).execute()
        print(f"✅ Inserted {len(schedule_rows)} schedule rows.")
    else:
        print("⚠️ No valid schedule entries found.")

    return {
        "deleted_month": sheet_name,
        "rows_inserted": len(schedule_rows)
    }