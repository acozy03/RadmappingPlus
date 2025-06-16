from supabase import Client
from datetime import datetime, timezone

def log_audit_action(
    supabase: Client,
    action: str,
    table_name: str,
    record_id: str,
    user_email: str,
    old_data: dict = None,
    new_data: dict = None,
):
    def enrich_with_names(data: dict) -> dict:
        enriched = dict(data)
        try:
            # Radiologist name lookup
            rad_id = data.get("radiologist_id")
            if rad_id:
                rad_res = supabase.table("radiologists").select("name").eq("id", rad_id).limit(1).execute()
                if rad_res.data:
                    enriched["radiologist_name"] = rad_res.data[0]["name"]

            # Facility name lookup
            fac_id = data.get("facility_id")
            if fac_id:
                fac_res = supabase.table("facilities").select("name").eq("id", fac_id).limit(1).execute()
                if fac_res.data:
                    enriched["facility_name"] = fac_res.data[0]["name"]
        except Exception as e:
            print(f"⚠️ Failed to enrich audit log with names: {e}")
        return enriched

    try:
        enriched_old = enrich_with_names(old_data or {})
        enriched_new = enrich_with_names(new_data or {})

        log_entry = {
            "action": action,
            "table_name": table_name,
            "record_id": record_id,
            "user_email": user_email,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "old_data": enriched_old,
            "new_data": enriched_new,
        }

        supabase.table("audit_log").insert(log_entry).execute()
    except Exception as e:
        print(f"⚠️ Failed to write audit log: {e}")
