from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from app.admin_required import admin_required
from app.supabase_client import supabase
from datetime import datetime
import uuid
from app.middleware import with_supabase_auth
from app.supabase_client import get_supabase_client
info_bp = Blueprint('info', __name__)

@info_bp.route('/info')
@with_supabase_auth
def info():
    supabase = get_supabase_client()
    return render_template("info.html")
