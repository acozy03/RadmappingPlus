from flask import Blueprint, request, redirect, render_template, session, url_for
from app.supabase_client import supabase
import logging 
import sys 

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger(__name__)
        logger.info("Logging in with email: %s", email)
        logger.info("Supabase client is: %s", type(supabase))
        print("some debug message", file=sys.stderr, flush=True)
        result = supabase.table("users").select("*").eq("email", email).execute()
        if not result.data:
            return "User not found", 401

        user = result.data[0]

        if user["password"] == password:
            session["user"] = {"email": user["email"], "role": user["role"]}
            return redirect(url_for("dashboard.daily"))

        return "Invalid credentials", 401

    return render_template("login.html")

@auth_bp.route('/logout')
def logout():
    session.pop("user", None)
    return redirect(url_for("auth.login"))