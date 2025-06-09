from app.supabase_client import get_supabase_client

def fetch_all_rows(table: str, select_query: str = "*", batch_size: int = 1000):
    supabase = get_supabase_client()
    all_data = []
    offset = 0

    while True:
        res = supabase.table(table).select(select_query).range(offset, offset + batch_size - 1).execute()
        batch = res.data or []
        all_data.extend(batch)
        if len(batch) < batch_size:
            break
        offset += batch_size

    return all_data

def fetch_all_rows_monthly(table: str, select_query: str = "*", filters: dict = None, batch_size: int = 1000):
    supabase = get_supabase_client()
    all_data = []
    offset = 0

    while True:
        query = supabase.table(table).select(select_query)

        if filters:
            for key, value in filters.items():
                query = query.eq(key, value)

        query = query.range(offset, offset + batch_size - 1)
        res = query.execute()

        batch = res.data or []
        all_data.extend(batch)
        if len(batch) < batch_size:
            break
        offset += batch_size

    return all_data

def fetch_schedule_data(doctor_ids, start_date, end_date, batch_size=1000):
    """
    Fetch all schedule data for given doctors and date range, handling pagination
    This is specifically for the monthly schedule query that was hitting the 1000 row limit
    """
    supabase = get_supabase_client()
    all_data = []
    offset = 0
    
    while True:
        query = supabase.table("monthly_schedule") \
            .select("*, radiologists(*)") \
            .in_("radiologist_id", doctor_ids) \
            .lte("start_date", end_date) \
            .gte("end_date", start_date) \
            .range(offset, offset + batch_size - 1)
        
        res = query.execute()
        batch = res.data or []
        all_data.extend(batch)
        
    
        
        if len(batch) < batch_size:
            break
        offset += batch_size
    
    print(f"Total schedule entries fetched: {len(all_data)}")
    return all_data
