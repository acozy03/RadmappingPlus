def run_google_sheet_sync(sheet_name: str = "March 2025"):
    import os
    import re
    import uuid
    import calendar
    import gspread
    import google.auth
    from datetime import datetime, timedelta
    from dateutil import parser
    from supabase import create_client, Client
    from rapidfuzz import process

    # ---- Supabase + Google Sheets ----
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SUPER_KEY", "").strip()
    if not url or not key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SUPER_KEY env vars.")

    supabase: Client = create_client(url, key)

    creds, _ = google.auth.default()
    gc = gspread.authorize(creds)

    sh = gc.open("Rad Monthy Schedule ")
    worksheet = sh.worksheet(sheet_name)

    data = worksheet.get_all_values()
    if not data or len(data) < 2:
        raise RuntimeError(f"Worksheet '{sheet_name}' has no data.")

    headers = data[0]
    rows = data[1:]

    # ---- Derive month/year from sheet title (source of truth) ----
    # Expected like: "January 2026"
    try:
        month_name, year_str = worksheet.title.strip().split()
        month_num = list(calendar.month_name).index(month_name)
        year = int(year_str)
        sheet_default_dt = datetime(year, month_num, 1)
    except Exception as e:
        raise RuntimeError(
            f"Failed to parse sheet title '{worksheet.title}'. "
            f"Expected format like 'January 2026'. Error: {e}"
        )

    # ---- Radiologists ----
    radiologists = supabase.table("radiologists").select("id", "name").execute().data
    if not radiologists:
        raise RuntimeError("❌ No radiologists found in Supabase.")

    name_map = {r["name"].strip(): r["id"] for r in radiologists}
    name_list = list(name_map.keys())

    # ---- Parsing helpers ----
    keywords = {"OFF", "VACATION", "REACH AS NEEDED"}

    time_pattern = re.compile(
        r'(\d{1,2}(?::?\d{2})?\s*(?:am|pm))\s*[-–—]\s*(\d{1,2}(?::?\d{2})?\s*(?:am|pm))',
        re.IGNORECASE
    )
    lone_time_pattern = re.compile(
        r'(?<![-–—])\b(\d{1,2}(?::?\d{2})?\s*(?:am|pm))\b(?!\s*[-–—])',
        re.IGNORECASE
    )

    def parse_time(t: str):
        t = t.lower().replace(" ", "")
        for fmt in ("%I%p", "%I:%M%p", "%I%M%p"):
            try:
                return datetime.strptime(t, fmt).time()
            except ValueError:
                continue
        return None

    def extract_all_times(cell_value: str):
        def remove_prn_parens(text: str) -> str:
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

    def parse_header_date(date_str: str):
        """
        Parse a column header into a date, forcing the year/month from the sheet title
        when headers omit them (e.g. '1/3', 'Jan 3', '3', 'Mon 3', etc).

        Strategy:
        1) Try dateutil parse with a default set to (sheet year/month/1).
        2) If that fails, try to extract a day number and build date(year, month, day).
        """
        s = (date_str or "").strip()
        if not s:
            raise ValueError("Empty header date string")

        # Most common: parser can handle it but may omit year; default anchors it.
        try:
            d = parser.parse(s, default=sheet_default_dt, fuzzy=True).date()
            # If header omitted year/month, this will now be correct.
            # If header included a conflicting year/month, it will respect it.
            # If you *always* want sheet title to win, uncomment the next line:
            d = d.replace(year=year, month=month_num)
            return d
        except Exception:
            # Fallback: grab first day-like number from header and force year/month
            m = re.search(r"\b([0-3]?\d)\b", s)
            if not m:
                raise
            day = int(m.group(1))
            return datetime(year, month_num, day).date()

    # ---- Build rows to insert ----
    schedule_rows = []

    for row_idx, row in enumerate(rows):
        if not row or len(row) < 2 or not str(row[1]).strip():
            continue

        raw_name = str(row[1]).split("-")[0].strip()
        result = process.extractOne(raw_name, name_list)
        if not result or result[1] < 80:
            print(f"[Row {row_idx}] No confident match for: '{raw_name}'")
            continue

        rad_id = name_map[result[0]]

        for col_idx, cell in enumerate(row[2:], start=2):
            cell_value = str(cell).strip()
            if not cell_value:
                continue

            date_str = headers[col_idx] if col_idx < len(headers) else ""
            try:
                date = parse_header_date(date_str)
            except Exception as e:
                print(f"Skipping invalid date header '{date_str}' (col {col_idx}): {e}")
                continue

            upper_val = cell_value.upper()
            times = extract_all_times(cell_value)

            # Debug hook if you want it:
            # if row_idx == 10:
            #     print(f"[Row {row_idx}, Col {col_idx}] Header '{date_str}' -> {date} | times={times} | cell='{cell_value}'")

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

    # ---- Delete existing rows for that month/year (based on sheet title) ----
    first_day = datetime(year, month_num, 1).date()
    last_day = datetime(year, month_num, calendar.monthrange(year, month_num)[1]).date()

    supabase.table("monthly_schedule") \
        .delete() \
        .gte("start_date", first_day.isoformat()) \
        .lte("start_date", last_day.isoformat()) \
        .execute()

    print(f"Old entries for {worksheet.title} deleted ({first_day} -> {last_day}).")

    # ---- Insert ----
    if schedule_rows:
        print("Inserting rows...")
        supabase.table("monthly_schedule").insert(schedule_rows).execute()
        print(f"Inserted {len(schedule_rows)} schedule rows.")
    else:
        print("No valid schedule entries found.")

    return {
        "deleted_month": worksheet.title,
        "rows_inserted": len(schedule_rows),
        "month_num": month_num,
        "year": year,
    }
