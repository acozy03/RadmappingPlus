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

    data = worksheet.get_all_values()
    headers = data[0]
    rows = data[1:]

    radiologists = supabase.table("radiologists").select("id", "name").execute().data
    if not radiologists:
        raise RuntimeError("❌ No radiologists found in Supabase.")

    name_map = {r["name"].strip(): r["id"] for r in radiologists}
    name_list = list(name_map.keys())

    keywords = {"OFF", "VACATION", "REACH AS NEEDED"}
    time_pattern = re.compile(r'(\d{1,2}(?::?\d{2})?\s*(?:am|pm))\s*[-–—]\s*(\d{1,2}(?::?\d{2})?\s*(?:am|pm))', re.IGNORECASE)
    lone_time_pattern = re.compile(r'(?<![-–—])\b(\d{1,2}(?::?\d{2})?\s*(?:am|pm))\b(?!\s*[-–—])', re.IGNORECASE)

    def parse_time(t):
        t = t.lower().replace(" ", "")
        for fmt in ("%I%p", "%I:%M%p", "%I%M%p"):
            try:
                return datetime.strptime(t, fmt).time()
            except ValueError:
                continue
        return None

    def extract_all_times(cell_value):
        def remove_prn_parens(text):
            return re.sub(r'\(([^)]*PRN[^)]*)\)', '', text, flags=re.IGNORECASE)

        stripped = remove_prn_parens(cell_value)

        matches = []

        for match in time_pattern.finditer(stripped):
            start_time = parse_time(match.group(1))
            end_time = parse_time(match.group(2))
            if start_time and end_time:
                matches.append((match.start(), start_time))
                matches.append((match.end(), end_time))

        for match in lone_time_pattern.finditer(stripped):
            t = parse_time(match.group(1))
            if not t:
                continue
            if not any(abs(match.start() - m[0]) <= 1 for m in matches):
                matches.append((match.start(), t))

        matches.sort(key=lambda x: x[0])
        return [t for _, t in matches]



    schedule_rows = []

    for row_idx, row in enumerate(rows):
        if not row or len(row) < 2 or not row[1].strip():
            continue

        raw_name = row[1].split("-")[0].strip()
        result = process.extractOne(raw_name, name_list)
        if not result or result[1] < 80:
            print(f"[Row {row_idx}] No confident match for: '{raw_name}'")
            continue

        rad_id = name_map[result[0]]

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

            if row_idx == 10:
                print(f"[Row {row_idx}, Col {col_idx}] Parsed times: {times} from '{cell_value}'")

            if len(times) >= 2:
                start_time, end_time = times[0], times[-1]
                break_start = break_end = None

                if len(times) == 4:
                    t1, t2, t3, t4 = times
                    gap = datetime.combine(date, t3) - datetime.combine(date, t2)
                    if gap.total_seconds() > 0:
                        break_start = t2
                        break_end = t3

                crosses_midnight = datetime.combine(date, end_time) < datetime.combine(date, start_time)
                end_date = date + timedelta(days=1) if crosses_midnight else date

                schedule_rows.append({
                    "id": str(uuid.uuid4()),
                    "radiologist_id": rad_id,
                    "radiologist_name": result[0],
                    "start_date": date.isoformat(),
                    "start_time": start_time.strftime("%H:%M:%S"),
                    "end_date": end_date.isoformat(),
                    "end_time": end_time.strftime("%H:%M:%S"),
                    "break_start": break_start.strftime("%H:%M:%S") if break_start else None,
                    "break_end": break_end.strftime("%H:%M:%S") if break_end else None,
                    "schedule_details": cell_value,
                })

            elif any(kw in upper_val for kw in keywords):
                schedule_rows.append({
                    "id": str(uuid.uuid4()),
                    "radiologist_id": rad_id,
                    "radiologist_name": result[0],
                    "start_date": date.isoformat(),
                    "start_time": None,
                    "end_date": date.isoformat(),
                    "end_time": None,
                    "break_start": None,
                    "break_end": None,
                    "schedule_details": cell_value.title(),
                })
            else:
                print(f"Unrecognized content: '{cell_value}' (Row {row_idx}, Col {col_idx})")
                schedule_rows.append({
                    "id": str(uuid.uuid4()),
                    "radiologist_id": rad_id,
                    "radiologist_name": result[0],
                    "start_date": date.isoformat(),
                    "start_time": None,
                    "end_date": date.isoformat(),
                    "end_time": None,
                    "break_start": None,
                    "break_end": None,
                    "schedule_details": cell_value,
                })

    try:
        month_name, year = worksheet.title.strip().split()
        month_num = list(calendar.month_name).index(month_name)
        year = int(year)
        first_day = datetime(year, month_num, 1).date()
        last_day = datetime(year, month_num, calendar.monthrange(year, month_num)[1]).date()

        supabase.table("monthly_schedule") \
            .delete() \
            .gte("start_date", first_day.isoformat()) \
            .lte("start_date", last_day.isoformat()) \
            .execute()
        print(f"Old entries for {worksheet.title} deleted.")
    except Exception as e:
        print(f"Failed to parse sheet title '{worksheet.title}': {e}")

    if schedule_rows:
        print("Inserting rows...")
        supabase.table("monthly_schedule").insert(schedule_rows).execute()
        print(f"Inserted {len(schedule_rows)} schedule rows.")
    else:
        print("No valid schedule entries found.")

    return {
        "deleted_month": sheet_name,
        "rows_inserted": len(schedule_rows)
    }
