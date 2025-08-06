import os
import logging
import jwt
from flask import session, g, redirect, url_for
from supabase import create_client, Client

url = os.getenv("SUPABASE_URL", "").strip()
key = os.getenv("SUPABASE_KEY", "").strip()


if not url or not key:
    logging.error("Missing Supabase credentials")
    raise RuntimeError("Missing Supabase credentials.")

supabase: Client = create_client(url, key)

def get_supabase_client():
    if hasattr(g, "supabase_client"):
        return g.supabase_client

    if session.get("user") and not getattr(g, "supabase_session_set", False):
        access_token = session["user"].get("access_token")
        refresh_token = session["user"].get("refresh_token")

        if access_token and refresh_token:
            try:
                logging.debug("Attempting to set Supabase session with tokens")
                supabase.auth.set_session(access_token, refresh_token)
                g.supabase_session_set = True
                logging.debug("Successfully set Supabase session")
            except Exception as e:
                logging.error(f"Supabase session setting failed: {e}")
                session.clear()
        else:
            logging.warning("Missing or invalid access/refresh token.")
            session.clear()

    g.supabase_client = supabase
    return g.supabase_client
