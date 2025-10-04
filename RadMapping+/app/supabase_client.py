# app/supabase_client.py
import os
import logging
from supabase import create_client, Client

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
# Prefer SERVICE_ROLE key name; fall back to your existing env if needed
_SERVICE_KEY = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("SUPABASE_SUPER_KEY")
    or ""
)
_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

if not _SUPABASE_URL or not _SERVICE_KEY:
    logging.error("Supabase server credentials missing (SUPABASE_URL / SERVICE_ROLE_KEY).")

# Create a single admin/server client for the app lifetime.
_admin_client: Client | None = None
try:
    if _SUPABASE_URL and _SERVICE_KEY:
        _admin_client = create_client(_SUPABASE_URL, _SERVICE_KEY)
except Exception as e:
    logging.exception(f"Failed to create Supabase admin client: {e}")
    _admin_client = None


def get_supabase_client() -> Client:
    """
    Returns the server/admin Supabase client (uses service-role key).
    Do NOT mutate this client with user tokens; keep it stable.
    """
    if _admin_client is None:
        raise RuntimeError("Supabase admin client is not initialized. Check env vars.")
    return _admin_client


def get_user_supabase_client(access_token: str) -> Client:
    """
    If you occasionally need to call Supabase as the user, build a separate
    per-request client from the ANON key and set only the access token.
    Avoid storing or using refresh tokens on the server.
    """
    if not _SUPABASE_URL or not _ANON_KEY:
        raise RuntimeError("Supabase public credentials missing (SUPABASE_URL / ANON_KEY).")
    user_client = create_client(_SUPABASE_URL, _ANON_KEY)
    # Set only access token; refresh not needed server-side
    try:
        user_client.auth.set_session(access_token, "")
    except Exception as e:
        logging.exception(f"Failed to set user session on Supabase client: {e}")
        raise
    return user_client
