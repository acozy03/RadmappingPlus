from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
import os
import logging
from app.supabase_client import get_supabase_client
from app.middleware import with_supabase_auth
from app.supabase_helper import fetch_all_rows
from datetime import datetime, timedelta
from app.admin_required import admin_required
from app.audit_log import log_audit_action
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

@with_supabase_auth
@admin_required
@audit_bp.route("/audit/undo_delete/<string:audit_id>", methods=["POST"])
def undo_delete(audit_id):
    supabase = get_supabase_client()

    res = supabase.table("audit_log").select("*").eq("id", audit_id).single().execute()
    audit_entry = getattr(res, "data", None)
    if not audit_entry:
        return jsonify({"error": "Audit entry not found"}), 404
    if audit_entry.get("action") != "delete":
        return jsonify({"error": "Audit entry is not a delete"}), 400

    table_name = audit_entry["table_name"]
    record_id = audit_entry["record_id"]
    old_data = audit_entry.get("old_data") or {}
    user_email = session.get("user", {}).get("email", "unknown")

    try:
      cols_res = supabase.rpc("admin_table_columns", {"p_table": table_name}).execute()
      cols = set((cols_res.data or []))
    except Exception as e:
      return jsonify({"error": f"Could not read table columns for {table_name}: {e}"}), 500

    if not cols:
      return jsonify({"error": f"No columns found for {table_name}"}), 400

    filtered = {k: v for k, v in (old_data.items()) if k in cols}

    if "id" not in filtered:
      return jsonify({"error": "Cannot restore: primary key 'id' missing from audit old_data"}), 400

    try:
      insert_res = supabase.table(table_name).insert(filtered).execute()
      restored = insert_res.data[0] if insert_res and insert_res.data else {"id": record_id}

      log_audit_action(
          supabase=supabase,
          action="restore",
          table_name=table_name,
          record_id=record_id,
          user_email=user_email,
          old_data=None,
          new_data={"restored_record": {"id": restored.get("id", record_id)}},
      )
      return jsonify({"ok": True, "restored_id": restored.get("id", record_id)})

    except Exception as e:
      log_audit_action(
          supabase=supabase,
          action="restore_failed",
          table_name=table_name,
          record_id=record_id,
          user_email=user_email,
          old_data={"audit_id": audit_id},
          new_data={"error": str(e)},
      )
      return jsonify({"error": f"Restore failed: {e}"}), 400


