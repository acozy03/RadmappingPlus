from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from app.admin_required import admin_required
# from app.supabase_client import supabase # This 'supabase' is likely unused and can be removed
from datetime import datetime, timedelta # Import datetime
import uuid
from app.middleware import with_supabase_auth
from app.supabase_client import get_supabase_client
import logging # Import logging
from app.audit_log import log_audit_action
vacations_bp = Blueprint('vacations', __name__)

@vacations_bp.route('/vacations')
@with_supabase_auth
def vacations_page():
    supabase = get_supabase_client()
    
    logging.info("Fetching doctors and vacations for vacations_page.")

    # Fetch all doctors
    doctors_res = supabase.table("radiologists").select("*").order("name").execute()
    doctors = doctors_res.data
    logging.info(f"Fetched {len(doctors)} doctors.")

    # Fetch all vacations
    vacations_res = supabase.table("vacations").select("*, radiologists(*)").execute()
    vacations = vacations_res.data
    logging.info(f"Fetched {len(vacations)} vacations from Supabase.")

    # Convert start_date and end_date strings to datetime objects for template rendering
    processed_vacations = []
    for vacation in vacations:
        # Create a mutable copy if you're modifying elements directly in the list
        # For simplicity, if we append to new list, we don't need shallow copy.
        # If modifying in place within the original list, use vacation = vacation.copy()
        
        # Log the raw dates before conversion
        logging.info(f"Processing vacation ID: {vacation.get('id')}, Raw Start Date: {vacation.get('start_date')}, Raw End Date: {vacation.get('end_date')}")

        if vacation.get("start_date"):
            try:
                # Assuming format is 'YYYY-MM-DD' from database
                vacation["start_date"] = datetime.strptime(vacation["start_date"], "%Y-%m-%d")
                logging.info(f"Converted start_date: {vacation['start_date']}")
            except ValueError as e:
                logging.error(f"Error converting start_date '{vacation.get('start_date')}' for vacation {vacation.get('id')}: {e}")
                vacation["start_date"] = None # Set to None or handle as invalid
        if vacation.get("end_date"):
            try:
                vacation["end_date"] = datetime.strptime(vacation["end_date"], "%Y-%m-%d")
                logging.info(f"Converted end_date: {vacation['end_date']}")
            except ValueError as e:
                logging.error(f"Error converting end_date '{vacation.get('end_date')}' for vacation {vacation.get('id')}: {e}")
                vacation["end_date"] = None # Set to None or handle as invalid
        processed_vacations.append(vacation) # Append to a new list if you want to avoid modifying original list in place

    today = datetime.now().date()
    month_start = today.replace(day=1)
    next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    month_end = next_month - timedelta(days=1)

    for v in processed_vacations:
        start = v.get("start_date").date() if v.get("start_date") else None
        end = v.get("end_date").date() if v.get("end_date") else None
        v["is_active_this_month"] = bool(start and end and start <= month_end and end >= month_start)
        v["is_upcoming"] = bool(start and start > today)

    return render_template(
        "vacations.html",
        doctors=doctors,
        vacations=processed_vacations,
        today=today,
        month_start=month_start,
        month_end=month_end
    )


@vacations_bp.route('/vacations/add', methods=['POST'])
@with_supabase_auth
@admin_required
def add_vacation():
    supabase = get_supabase_client()
    data = {
        "id": str(uuid.uuid4()),
        "radiologist_id": request.form.get("radiologist_id"),
        "start_date": request.form.get("start_date"),
        "end_date": request.form.get("end_date"),
        "comments": request.form.get("comments")
    }
    result = supabase.table("vacations").insert(data).execute()

    if not hasattr(result, 'error'):
        log_audit_action(
            supabase=supabase,
            action="insert",
            table_name="vacations",
            record_id=data["id"],
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=None,
            new_data=data
        )

    return redirect(url_for("vacations.vacations_page"))


@vacations_bp.route('/vacations/update', methods=['POST'])
@with_supabase_auth
@admin_required
def update_vacation():
    supabase = get_supabase_client()
    vacation_id = request.form.get("vacation_id")

    old_data = supabase.table("vacations").select("*").eq("id", vacation_id).single().execute().data

    data = {
        "radiologist_id": request.form.get("radiologist_id"),
        "start_date": request.form.get("start_date"),
        "end_date": request.form.get("end_date"),
        "comments": request.form.get("comments")
    }

    result = supabase.table("vacations").update(data).eq("id", vacation_id).execute()

    if not hasattr(result, 'error'):
        log_audit_action(
            supabase=supabase,
            action="update",
            table_name="vacations",
            record_id=vacation_id,
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=old_data,
            new_data=data
        )

    return redirect(url_for("vacations.vacations_page"))


@vacations_bp.route('/vacations/delete', methods=['POST'])
@with_supabase_auth
@admin_required
def delete_vacation():
    supabase = get_supabase_client()
    vacation_id = request.json.get("vacation_id")

    old_data = supabase.table("vacations").select("*").eq("id", vacation_id).single().execute().data
    result = supabase.table("vacations").delete().eq("id", vacation_id).execute()

    if not hasattr(result, 'error'):
        log_audit_action(
            supabase=supabase,
            action="delete",
            table_name="vacations",
            record_id=vacation_id,
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=old_data,
            new_data=None
        )

    return jsonify({"status": "success"})
