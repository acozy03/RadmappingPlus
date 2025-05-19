from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify, session
import os
from app.supabase_client import get_supabase_client
auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login')
def login():
    return render_template(
        "login.html",
        SUPABASE_URL=os.environ.get("SUPABASE_URL"),
        SUPABASE_KEY=os.environ.get("SUPABASE_SUPER_KEY")
    )

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@auth_bp.route('/session', methods=['POST'])
def set_session():
    data = request.get_json()
    email = data.get("email")
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")

    if not data or not email or not access_token or not refresh_token:
        session.clear()
        return jsonify({"error": "Missing required session data"}), 400

    if not (email.endswith("@vestatelemed.com") or email.endswith("@vestasolutions.com")):
        session.clear()
        return jsonify({"error": "Unauthorized domain"}), 403

    role = "user"
    supabase = get_supabase_client()
    try:
        response = supabase.table("users").select("role").eq("email", email).single().execute()
        if response.data:
            role = response.data["role"]
    except Exception:
        pass  # fallback to "user"

    session["user"] = {
        "email": email,
        "role": role,
        "access_token": access_token,
        "refresh_token": refresh_token,
    }

    return jsonify({"status": "ok"}), 200
