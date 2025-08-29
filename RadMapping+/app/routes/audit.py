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
    
    # Initial page load will fetch a small batch to quickly render the page
    page = request.args.get('page', 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page
    
    # First, get the total count to show on the front end for pagination purposes
    count_res = supabase.table("audit_log").select("id", count="exact").execute()
    total_count = count_res.count if count_res else 0
    
    logs_res = supabase.table("audit_log").select("*").order("timestamp", desc=True).range(offset, offset + per_page - 1).execute()
    logs = logs_res.data or []
    
    return render_template("audit.html", logs=logs, total_count=total_count, per_page=per_page, page=page)

@with_supabase_auth
@audit_bp.route("/audit/load_more", methods=["GET"])
def load_more_audit_log():
    supabase = get_supabase_client()
    page = request.args.get('page', 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page
    
    logs_res = supabase.table("audit_log").select("*").order("timestamp", desc=True).range(offset, offset + per_page - 1).execute()
    logs = logs_res.data or []
    
    # Return as JSON for the JavaScript to handle
    return jsonify(logs)