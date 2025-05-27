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
