import os
import logging
import jwt
from flask import session, g
from supabase import create_client, Client

# Load and create Supabase client once
url = os.getenv("SUPABASE_URL", "").strip()
key = os.getenv("SUPABASE_KEY", "").strip()

if not url or not key:
    raise RuntimeError("Missing Supabase credentials.")

supabase: Client = create_client(url, key)

def get_supabase_client():
    """Returns the Supabase client, sets session once per request if needed."""
    # Cache the client in `g` so it's reused within a single request
    if hasattr(g, "supabase_client"):
        return g.supabase_client

    if session.get("user") and not getattr(g, "supabase_session_set", False):
        access_token = session["user"].get("access_token")
        refresh_token = session["user"].get("refresh_token")

        if access_token and refresh_token:
            try:
                # Optional debug-only JWT decode (safe, no verify)
                if os.getenv("FLASK_ENV") == "development":
                    decoded_token = jwt.decode(access_token, options={"verify_signature": False})
                    logging.debug(f"JWT Role: {decoded_token.get('user_metadata', {}).get('role')}")
            except Exception as e:
                logging.warning(f"JWT decode failed: {e}")

            # Set session once per request
            supabase.auth.set_session(access_token, refresh_token)
            g.supabase_session_set = True

    g.supabase_client = supabase
    return g.supabase_client
