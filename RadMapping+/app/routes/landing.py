from flask import Blueprint, render_template, session, redirect, url_for
from app.middleware import with_supabase_auth
from app.supabase_client import get_supabase_client
landing_bp = Blueprint('landing', __name__)

@landing_bp.route('/landing')
@with_supabase_auth
def landing():
    supabase = get_supabase_client()
    return render_template("landing.html")
