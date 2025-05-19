import os
import logging
import jwt
from flask import session, g, redirect, url_for
from supabase import create_client, Client

# Load and create Supabase client once
url = os.getenv("SUPABASE_URL", "").strip()
key = os.getenv("SUPABASE_KEY", "").strip()

if not url or not key:
    raise RuntimeError("Missing Supabase credentials.")

supabase: Client = create_client(url, key)

from flask import redirect, url_for

def get_supabase_client():
    if hasattr(g, "supabase_client"):
        return g.supabase_client

    if session.get("user") and not getattr(g, "supabase_session_set", False):
        access_token = session["user"].get("access_token")
        refresh_token = session["user"].get("refresh_token")

        if access_token and refresh_token:
            try:
                supabase.auth.set_session(access_token, refresh_token)
                g.supabase_session_set = True
            except Exception as e:
                logging.warning(f"Supabase session setting failed: {e}")
                session.clear()
                # Optional: redirect now or let route handler deal with it
        else:
            logging.warning("Missing or invalid access/refresh token.")
            session.clear()

    if session.get("user"):
        email = session["user"].get("email")
        if email:
            try:
                response = supabase.table("users").select("role").eq("email", email).single().execute()
                if response.data:
                    new_role = response.data["role"]
                    if session["user"].get("role") != new_role:
                        session["user"]["role"] = new_role
            except Exception as e:
                logging.warning(f"Failed to refresh role for {email}: {e}")

    g.supabase_client = supabase
    return g.supabase_client
