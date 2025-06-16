from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
import os
import logging
from app.supabase_client import get_supabase_client 
from app.middleware import with_supabase_auth

audit_bp = Blueprint('audit', __name__)

@with_supabase_auth
@audit_bp.route("/audit")
def view_audit_log():
    supabase = get_supabase_client()
    logs = supabase.table("audit_log").select("*").order("timestamp", desc=True).limit(100).execute().data
    return render_template("audit.html", logs=logs)
