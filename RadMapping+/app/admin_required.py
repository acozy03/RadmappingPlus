from functools import wraps
from flask import session, abort

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = session.get("user")
        if not user or user.get("role") != "admin":
            abort(403)
        return f(*args, **kwargs)
    return decorated_function