import os
from supabase import create_client, Client

url = os.getenv("SUPABASE_URL", "").strip()
key = os.getenv("SUPABASE_KEY", "").strip()

if not url or not key:
    raise RuntimeError("Missing Supabase credentials.")

supabase: Client = create_client(url, key) 

print("Supabase client created successfully.")
