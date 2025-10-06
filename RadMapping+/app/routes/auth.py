# app/routes/auth.py
from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
import os
import logging
from app.supabase_client import get_supabase_client

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login")
def login():
    """
    Render login page. Pass anon key to browser so Supabase JS can handle OAuth.
    """
    logging.info("--- Entering /auth/login ---")
    next_url = request.args.get("next") or session.pop("redirect_after_login", url_for("landing.landing"))

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")  # anon key

    if not supabase_url or not supabase_key:
        logging.error("Missing SUPABASE_URL or SUPABASE_KEY in env.")
        return "Server misconfigured: missing Supabase public credentials.", 500

    return render_template(
        "login.html",
        SUPABASE_URL=supabase_url,
        SUPABASE_KEY=supabase_key,
        next_url=next_url,
    )


@auth_bp.route("/session", methods=["POST"])
def set_session():
    logging.info("--- Entering /auth/session (POST) ---")
    data = request.get_json(silent=True) or {}
    access_token = data.get("access_token")

    if not access_token:
        session.clear()
        return jsonify({"error": "Missing access_token"}), 400

    supabase = get_supabase_client()
    try:
        user_res = supabase.auth.get_user(access_token)

        # Handle object vs dict shapes from supabase-py
        u = getattr(user_res, "user", None) or getattr(user_res, "data", None) or user_res
        email = getattr(u, "email", None)
        if not email and isinstance(u, dict):
            email = u.get("email") or (u.get("user_metadata") or {}).get("email")
        if not email:
            raise ValueError("Email not found on Supabase user")

        # Extract optional profile information for UI enrichment
        metadata = {}
        if hasattr(u, "user_metadata") and getattr(u, "user_metadata"):
            metadata = getattr(u, "user_metadata") or {}
        elif isinstance(u, dict):
            metadata = u.get("user_metadata") or {}

        full_name = metadata.get("full_name") or metadata.get("name")
        avatar_url = metadata.get("avatar_url") or metadata.get("picture")
        if not full_name and email:
            full_name = email.split("@")[0]
    except Exception as e:
        logging.error(f"Failed to fetch/parse user from access_token: {e}")
        session.clear()
        return jsonify({"error": "Invalid token"}), 401

    # Look up role in your users table
    role = "user"
    try:
        resp = supabase.table("users").select("role").eq("email", email).single().execute()
        if getattr(resp, "data", None) and "role" in resp.data:
            role = resp.data["role"]
    except Exception as e:
        logging.error(f"Role lookup failed for {email}: {e}")

    session["user"] = {
        "email": email,
        "role": role,
        "name": full_name,
        "avatar_url": avatar_url,
    }
    logging.info(f"Session established for {email} with role={role}")
    return jsonify({"status": "ok", "role": role}), 200


@auth_bp.route("/logout")
def logout():
    """
    Clear Flask session and send user back to login.
    """
    logging.info("--- Entering /auth/logout ---")
    next_url = request.referrer or url_for("landing.landing")
    session["redirect_after_login"] = next_url

    session.clear()
    return redirect(url_for("auth.login", next=next_url))
