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

        if user.get("role") == "admin":
            return f(*args, **kwargs)

        email = user.get("email")
        if not email:
            print("No email in session")
            abort(403)

        supabase = get_supabase_client()
        try:
            response = supabase.table("users").select("role").eq("email", email).limit(1).execute()
            role = response.data[0]["role"] if response.data else None
            if role != "admin":
                print(f"User {email} is not admin")
                abort(403)

            session["user"]["role"] = role
        except Exception as e:
            print(f"Error fetching role for {email}: {e}")
            abort(403)

        return f(*args, **kwargs)
    return decorated_function
