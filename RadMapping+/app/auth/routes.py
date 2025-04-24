from flask import Blueprint, request, redirect, render_template, session, url_for
from app.supabase_client import supabase

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        result = supabase.table("users").select("*").eq("email", email).execute()
        if not result.data:
            return "User not found", 401

        user = result.data[0]

        if user["password"] == password:
            session["user"] = {"email": user["email"], "role": user["role"]}
            return redirect(url_for("dashboard.home"))

        return "Invalid credentials", 401

    return render_template("login.html")

@auth_bp.route('/logout')
def logout():
    session.pop("user", None)
    return redirect(url_for("auth.login"))