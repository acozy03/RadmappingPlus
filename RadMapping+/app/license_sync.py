import gspread
import uuid
from datetime import datetime
from flask import request, jsonify
from threading import Thread
from app.supabase_client import get_supabase_client
import google.auth


def process_license_cell_update(sheet_id, row, col):
    supabase = get_supabase_client()

    creds, _ = google.auth.default()
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)
    ws = sh.worksheet("License")

    data = ws.get_all_values()
    if row >= len(data):
        print(f"❌ Row {row} out of range")
        return

    headers = data[0]  # doctor names
    specialties = data[1]  # specialty row
    target_row = data[row]
    state = target_row[0].strip()

    # Load radiologists
    radiologists = supabase.table("radiologists").select("id", "name").execute().data

    updated_rows = []
    for col_idx in range(1, len(target_row)):
        raw_name = headers[col_idx].strip()
        specialty = specialties[col_idx].strip() if col_idx < len(specialties) else None
        cell_value = target_row[col_idx].strip()

        if not raw_name or not specialty or not cell_value:
            continue

        # Match radiologist
        match_id = None
        target = raw_name.lower().split()[0]
        for r in radiologists:
            parts = r['name'].strip().lower().split()
            if any(p.startswith(target) for p in parts):
                match_id = r['id']
                break

        if not match_id:
            print(f"❌ No match for: {raw_name}")
            continue

        # Parse expiration date
        try:
            exp_date = datetime.strptime(cell_value, "%m/%d/%Y").date()
        except Exception:
            continue

        status = "Expired" if exp_date < datetime.today().date() else "Active"

        updated_rows.append({
            "id": str(uuid.uuid4()),
            "radiologist_id": match_id,
            "state": state,
            "expiration_date": exp_date.isoformat(),
            "status": status,
            "specialty": specialty,
            "tags": None
        })

    affected_ids = {r["radiologist_id"] for r in updated_rows}
    for rad_id in affected_ids:
        supabase.table("certifications").delete().eq("radiologist_id", rad_id).eq("state", state).execute()

    if updated_rows:
        supabase.table("certifications").insert(updated_rows).execute()
        print(f"Synced {len(updated_rows)} certifications for state: {state}")
