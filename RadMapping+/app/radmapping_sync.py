# radmapping_sync.py
import os
import io
import uuid
import openpyxl
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from supabase import create_client, Client
import json 

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SUPER_KEY")
SERVICE_ACCOUNT_INFO = {
  "type": "service_account",
  "project_id": "radmapping-458916",
  "private_key_id": "7930ade04026cc285775e8c8c054a4646a7b470d",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQCh5vTVz9+VOrdZ\nTknCK97EW665AC+hXkzxO3lKxwEUkIP7PTsUu3dMQFltKkvxh8w+pocWpn94ZY/3\nNjWUkQkCC/DdI1ZjWx3Y+tFRSUzxYj9B1qeoa3CAynhZIZlPtU1UWBlFMEEqL9kO\nG/FuqK1B5q8jga76gROX+b1WQHJOx+wzoHFxNwZ3bRPx7b9qkaitvhOHejp4P8QZ\ns9z9BSZLgfk9yGGpwliYm6p/sQ1v3MEr2XQxENhWw/rp1CX78NHAWco8i5CR2eiA\nuLQw5MrDrSHSiKoziBJJV43Iwe8P3l7Ls2OvYZbxFYbG3HT18uXjzLfaPl/ZVkOk\n++7/RRalAgMBAAECggEAAgeImyODbHXzdWmfUBFHthNmIciIUFADy+RQdWkAMPdM\nyDnwwyZEbQ7DcDRfBlSK8WAaAmUs5N/1CYbC7i1RPRbUOplmTFGIkr82H3w5PC9c\nlqEvsdNC8kJXdtqOdurRYNTH4E+mCXbXFC+ye44eudw/5sSJ4nb6vWVyg6HELQuc\nY2W+LZ7gQBkoe6fOOQzwi0hQznQV5Qfdthv+68MMDkaxPwZIcbuzO80OWbrzBvkX\nmkoGD9XNODGFsCXUQuUOxgH5a0dYP5LWXtkRbGDC8ztQQ3U80krce7RXTW3M9eRz\nO1fGoiVa1YXes4QwOTTrNuuJZzXINyD87XahN8CYcQKBgQDZfyNm23IBaQf67rXz\nSGQq6VdTKYlE7n/PI91AiTLWjd54Jy5uopFRk3W6UBzlRm7lczF1buXTZYxfu8xV\nZ2hTn0KmAW05eMvJrCziLeluNo14djHIhnr5FhJHuBLLxJa2xZSJeTGhFzYGUGUw\nsKEMk5BhV/40xsdq2kPIQY2fuQKBgQC+kEyPYT5wG4L9Bj6JBezMsedE4StHxVhE\nHuiFJ/Nmi2PFHFt6bJSaG1bQ7yJ9QnpMuO2wlaXwOIEH4kzeONDkoi6JRkE72yu+\nA08f70q5QwfS4MeaTfLWBkuo7Ak7YoYZNVRNsXBRMf/XSSiplOVFp0GwzZsvnmoO\nt9kgi5psTQKBgCqfMqXWfUnvdkPjgb6SQibyoU1Hx4G9p0hFg/dAq7jGBoHPU9cU\nfpvY5OpFBtSbb+IBKAEWYW2C6fZczBc0c4pnnF0BzJDFrlHwLr+INcWGZUTlDK56\nRCEKBT0OwogyF0LsB0bFfEdQUCL+oEXhZz4asOGSp9tZ1PyIl13oEsPpAoGAUfUJ\nmFjAW8LZUS0QVCoiL98LkgotbQ6o6ZNJeYs3GZE1dZ6+kSaFusmrSuyuLqUaqEiY\noWubFHeYtuVTHffdj5dY4F1AzRdz9qLBswBdaNQ1VzKpZenEWNwYSixJxCqZddoD\nye5YWfNhDxw9ysFo4c4PaJTk+1PsVSwoy+B+p7kCgYB1qfcI35RVfgWNWvzKqRsD\n8cQy7WEG9+00k90JptiACqHSoOiNUZEbX5bO6qpfZEHclikWGR9d0q7cdHMu8U2d\nbC1IxEQl5X0WRSAPhuveCm3dxtLA/U+bnL0ve1o+pilEHj8Q0jmbV1LsuFBWILjM\nIDv6bahoZXitQrVpDiAlTg==\n-----END PRIVATE KEY-----\n",
  "client_email": "radmapping-sync@radmapping-458916.iam.gserviceaccount.com",
  "client_id": "109723538318659414347",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/radmapping-sync%40radmapping-458916.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
creds = service_account.Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
drive = build("drive", "v3", credentials=creds)

def process_cell_update(sheet_id: str, row: int, col: int) -> dict:
    print(f"📥 Starting radmapping sync for sheet={sheet_id}, row={row}, col={col}")

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    creds = service_account.Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
    drive = build("drive", "v3", credentials=creds)
    temp_file = f"/tmp/radmapping_{uuid.uuid4()}.xlsx"

    print(f"📄 Downloading Google Sheet to {temp_file}...")
    request = drive.files().export_media(
        fileId=sheet_id,
        mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    with open(temp_file, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            print(f"⏳ Download progress: {int(status.progress() * 100)}%")

    wb = openpyxl.load_workbook(temp_file)
    ws = wb["RAD MAPPING "]
    os.remove(temp_file)
    print(f"🧹 Temp file deleted.")

    facility_name = str(ws.cell(row=row, column=1).value).strip().upper()
    if not facility_name:
        return {"error": "Missing facility name in column A"}, 400

    facilities = supabase.table("facilities").select("id, name").execute().data
    facility_lookup = {f["name"].strip().upper(): f["id"] for f in facilities}
    facility_id = facility_lookup.get(facility_name)
    if not facility_id:
        return {"error": f"Facility not found: {facility_name}"}, 404

    print(f"🏥 Matched facility: {facility_name} → {facility_id}")

    radiologists = supabase.table("radiologists").select("id, name").execute().data
    rad_lookup = {}
    for rad in radiologists:
        for part in rad["name"].upper().replace(",", "").split():
            rad_lookup.setdefault(part, []).append(rad["id"])

    seen_rads = set()
    new_assignments = []

    for col_idx in range(2, ws.max_column + 1):
        cell = ws.cell(row=row, column=col_idx)
        value = str(cell.value).strip() if cell.value else ""
        if not value:
            continue

        parts = value.split()
        name_part = parts[0].strip(",").upper()
        notes = " ".join(parts[1:]) if len(parts) > 1 else ""
        matching = rad_lookup.get(name_part, [])
        if len(matching) != 1:
            print(f"❌ Could not uniquely match doctor: {name_part}")
            continue

        rad_id = matching[0]
        seen_rads.add(rad_id)

        font_color = cell.font.color
        if font_color and font_color.type == "rgb":
            rgb = font_color.rgb.upper()
            print(f"🎨 Cell[{col_idx}] RGB: {rgb}")
            if rgb.startswith("FFFF0000"):
                can_read = "false"
            elif rgb.startswith("FF0000FF"):
                can_read = "pending"
            elif rgb.startswith("FFFF00FF"):
                can_read = "withdrawn"
            else:
                can_read = "true"
        else:
            can_read = "true"

        new_assignments.append({
            "radiologist_id": rad_id,
            "facility_id": facility_id,
            "can_read": can_read,
            "notes": notes
        })

    existing = supabase.table("doctor_facility_assignments") \
        .select("id, radiologist_id") \
        .eq("facility_id", facility_id).execute().data
    existing_rads = {a["radiologist_id"]: a["id"] for a in existing}

    # Delete removed ones
    for rad_id in existing_rads:
        if rad_id not in seen_rads:
            print(f"🗑️ Removing stale assignment for rad_id={rad_id}")
            supabase.table("doctor_facility_assignments") \
                .delete().eq("radiologist_id", rad_id).eq("facility_id", facility_id).execute()

    # Insert or update
    for a in new_assignments:
        print(f"📤 Inserting assignment: {a}")
        supabase.table("doctor_facility_assignments") \
            .delete().eq("radiologist_id", a["radiologist_id"]).eq("facility_id", a["facility_id"]).execute()

        supabase.table("doctor_facility_assignments").insert({
            "id": str(uuid.uuid4()),
            **a
        }).execute()

    return {
        "status": "success",
        "facility": facility_name,
        "assignments_updated": len(new_assignments),
        "assignments_removed": len(existing_rads) - len(seen_rads)
    }, 200
