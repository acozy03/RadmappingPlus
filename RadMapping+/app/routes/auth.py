from flask import Blueprint, request, redirect, render_template, session, url_for, flash
from app.supabase_client import supabase

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        try:
            # Sign in with Supabase
            auth_response = supabase.auth.sign_in_with_password({
                "email": email,
                "password": password
            })

            # Get user and tokens
            user = auth_response.user
            access_token = auth_response.session.access_token
            refresh_token = auth_response.session.refresh_token

            # Default role fallback
            role = "user"

            # ✅ Get role from users table (not from metadata)
            try:
                db_response = supabase.table("users").select("role").eq("id", user.id).single().execute()
                if db_response.data:
                    role = db_response.data.get("role", "user")
            except Exception as e:
                pass

            # 🧠 Optionally: sync it into metadata for JWT visibility (not used for access control)
            try:
                current_user = supabase.auth.admin.get_user_by_id(user.id)
                current_metadata = current_user.user_metadata or {}
                updated_metadata = {**current_metadata, "role": role}
                supabase.auth.admin.update_user_by_id(
                    user.id,
                    {"user_metadata": updated_metadata}
                )
            except Exception as e:
                pass

            # ✅ Store session with correct role
            session["user"] = {
                "id": user.id,
                "email": user.email,
                "role": role,
                "access_token": access_token,
                "refresh_token": refresh_token
            }

            return redirect(url_for("daily.daily"))

        except Exception as e:
            flash('Invalid credentials', 'error')
            return render_template("login.html")

    return render_template("login.html")


@auth_bp.route('/logout')
def logout():
    try:
        supabase.auth.sign_out()
    except Exception:
        pass

    session.clear()
    return redirect(url_for("auth.login"))
