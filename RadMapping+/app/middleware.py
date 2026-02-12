from functools import wraps
from flask import session, redirect, url_for

def with_supabase_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("auth.login"))
            
        return f(*args, **kwargs)
    return decorated_function 