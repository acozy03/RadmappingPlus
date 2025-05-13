from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from app.admin_required import admin_required
from app.supabase_client import supabase
from datetime import datetime, timedelta
import uuid
from app.middleware import with_supabase_auth
from app.supabase_client import get_supabase_client
visualize_bp = Blueprint('visualize', __name__)


@visualize_bp.route('/visualize')
@with_supabase_auth
def visualize():
    supabase = get_supabase_client()
    return render_template('visualize.html')