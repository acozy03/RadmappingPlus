from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
import os
import logging
from app.supabase_client import get_supabase_client
from app.middleware import with_supabase_auth
from app.supabase_helper import fetch_all_rows
from datetime import datetime, timedelta

audit_bp = Blueprint('audit', __name__)

def fetch_audit_logs_with_date_range(start_date_str: str, end_date_str: str):
    supabase = get_supabase_client()
    
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").isoformat()
    end_date = (datetime.strptime(end_date_str, "%Y-%m-%d") + timedelta(days=1)).isoformat()
    
    query = supabase.table("audit_log") \
        .select("*") \
        .gte("timestamp", start_date) \
        .lt("timestamp", end_date) \
        .order("timestamp", desc=True)
    
    res = query.execute()
    return res.data or []

@with_supabase_auth
@audit_bp.route("/audit")
def view_audit_log():
    supabase = get_supabase_client()
    
    count_res = supabase.table("audit_log").select("id", count="exact").execute()
    total_count = count_res.count if count_res else 0
    
    logs = []
    
    return render_template("audit.html", logs=logs, total_count=total_count, per_page=50)

@with_supabase_auth
@audit_bp.route("/audit/search", methods=["GET"])
def search_audit_log():
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    if not start_date_str or not end_date_str:
        return jsonify({"error": "Missing start_date or end_date parameter"}), 400
        
    try:
        logs = fetch_audit_logs_with_date_range(start_date_str, end_date_str)
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

    return jsonify(logs)
