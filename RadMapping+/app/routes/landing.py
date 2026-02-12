from flask import Blueprint, render_template
from app.middleware import with_supabase_auth
landing_bp = Blueprint('landing', __name__)

@landing_bp.route('/landing')
@with_supabase_auth
def landing():
    return render_template("landing.html")
