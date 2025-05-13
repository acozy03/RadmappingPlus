from functools import wraps
from flask import session, abort
from app.supabase_client import get_supabase_client

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = session.get("user")
        if not user:
            print("No user in session")
            abort(403)

        user_id = user.get("id")
        if not user_id:
            print("No user ID in session")
            abort(403)

        supabase = get_supabase_client()

        try:
            response = supabase.table("users").select("role").eq("id", user_id).single().execute()
            data = response.data

            if not data or data.get("role") != "admin":
                print("Role is not admin or missing")
                abort(403)
        except Exception as e:
            print(f"Error fetching role: {e}")
            abort(403)

        return f(*args, **kwargs)
    return decorated_function
