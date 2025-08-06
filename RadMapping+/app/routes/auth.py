from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
import os
import logging
from app.supabase_client import get_supabase_client 

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login')
def login():
    logging.info(f"--- Entering /auth/login ---")
    logging.info(f"Session content before login redirect check: {dict(session)}")
    next_url = session.pop('redirect_after_login', url_for('landing.landing'))
    
    logging.info(f"Login route accessed. 'redirect_after_login' popped from session: {next_url}")
    logging.info(f"Session content after popping redirect_after_login: {dict(session)}")

    return render_template(
        "login.html",
        SUPABASE_URL=os.environ.get("SUPABASE_URL"),
        SUPABASE_KEY=os.environ.get("SUPABASE_SUPER_KEY"),
        next_url=next_url 
    )

@auth_bp.route('/callback')
def callback():
    logging.info("--- Entering /auth/callback ---")
    access_token = request.args.get('access_token')
    refresh_token = request.args.get('refresh_token')
    next_url = request.args.get('next', url_for('landing.landing'))

    logging.info(f"Callback received: access_token present={bool(access_token)}, refresh_token present={bool(refresh_token)}, next_url={next_url}")

    if access_token and refresh_token:
        session['access_token'] = access_token
        session['refresh_token'] = refresh_token
        session['redirect_after_login'] = next_url 

        logging.info(f"Tokens and next_url stored in session. Redirecting to /auth/login for session sync.")
        logging.info(f"Session content after callback: {dict(session)}")
        return redirect(url_for('auth.login'))
    else:
        logging.warning("Callback received without expected access_token or refresh_token. Redirecting to login.")
        return redirect(url_for('auth.login'))

@auth_bp.route('/logout')
def logout():
    logging.info("--- Entering /auth/logout ---")
    logging.info(f"Session content on logout entry: {dict(session)}")

    if request.referrer:
        session['redirect_after_login'] = request.referrer
        logging.info(f"Logout: Storing referrer '{request.referrer}' in session['redirect_after_login'].")
    else:
        logging.warning("Logout: request.referrer is empty. Cannot store previous page for redirect.")
        session['redirect_after_login'] = url_for('landing.landing') 
        logging.info(f"Logout: Storing default landing page '{session['redirect_after_login']}' in session['redirect_after_login'] as fallback.")

    if 'user' in session:
        del session['user']
        logging.info("Removed 'user' key from session.")
    if 'access_token' in session: 
        del session['access_token']
    if 'refresh_token' in session:
        del session['refresh_token']
        

    logging.info(f"Session content after removing user data (before redirect): {dict(session)}")

    return redirect(url_for("auth.login"))


@auth_bp.route('/session', methods=['POST'])
def set_session():
    logging.info("--- Entering /auth/session (POST) ---")

    data = request.get_json()
    email = data.get("email")
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")

    if not access_token and 'access_token' in session:
        access_token = session.pop('access_token') 
        logging.info("Retrieved access_token from session.")
    if not refresh_token and 'refresh_token' in session:
        refresh_token = session.pop('refresh_token') 
        logging.info("Retrieved refresh_token from session.")

    if not email and 'user' in session and 'email' in session['user']:
        email = session['user']['email']
        logging.info("Retrieved email from existing 'user' in session.")

    if not email or not access_token or not refresh_token:
        logging.warning("Missing required session data (email/tokens) for set_session. Clearing session.")
        session.clear()
        return jsonify({"error": "Missing required session data"}), 400

    if not (email.endswith("@vestatelemed.com") or email.endswith("@vestasolutions.com")):
        logging.warning(f"Unauthorized domain for email: {email} during set_session. Clearing session.")
        session.clear()
        return jsonify({"error": "Unauthorized domain"}), 403

    role = "user"
    supabase = get_supabase_client()
    try:
        response = supabase.table("users").select("role").eq("email", email).single().execute()
        if response.data:
            role = response.data["role"]
            logging.info(f"User role retrieved: {role} for {email}.")
    except Exception as e:
        logging.error(f"Error fetching user role for {email}: {e}")
        pass
    
    temp_redirect_url = session.get('redirect_after_login', 'Not found in session before set.')
    logging.info(f"/auth/session: 'redirect_after_login' found in session before setting new user session: {temp_redirect_url}")

    session["user"] = {
        "email": email,
        "role": role,
        "access_token": access_token,
        "refresh_token": refresh_token,
    }
    
    logging.info(f"Session set successfully for user: {email}.")
    logging.info(f"Session content after successful set_session: {dict(session)}")
    return jsonify({"status": "ok"}), 200