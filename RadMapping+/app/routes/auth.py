from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify, session
import os

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login')
def login():
    return render_template(
        "login.html",
        SUPABASE_URL=os.environ.get("SUPABASE_URL"),
        SUPABASE_KEY=os.environ.get("SUPABASE_KEY")
    )

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@auth_bp.route('/session', methods=['POST'])
def set_session():
    data = request.get_json()

    # Basic validation
    if not data or not data.get("access_token") or not data.get("email"):
        return jsonify({"error": "Missing required data"}), 400

    # Only allow @vestatelemed.com users (extra safety)
    if not data["email"].endswith("@vestatelemed.com"):
        session.clear()
        return jsonify({"error": "Unauthorized domain"}), 403

    # Store the session
    session["user"] = {
        "email": data["email"],
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", "")
    }

    return jsonify({"status": "ok"})