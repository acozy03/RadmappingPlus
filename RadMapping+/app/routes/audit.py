from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
import os
import logging
from app.supabase_client import get_supabase_client 
from app.middleware import with_supabase_auth
from app.supabase_helper import fetch_all_rows
audit_bp = Blueprint('audit', __name__)

@with_supabase_auth
@audit_bp.route("/audit")
def view_audit_log():
    supabase = get_supabase_client()
    logs = fetch_all_rows("audit_log", select_query="*")
    logs.sort(key=lambda x: x['timestamp'], reverse=True) 
    return render_template("audit.html", logs=logs)
