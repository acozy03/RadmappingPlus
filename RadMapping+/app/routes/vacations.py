from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from app.admin_required import admin_required
from app.supabase_client import supabase
from datetime import datetime, timedelta
import uuid
from app.middleware import with_supabase_auth
from app.supabase_client import get_supabase_client

vacations_bp = Blueprint('vacations', __name__)


@vacations_bp.route('/vacations')
@with_supabase_auth
def vacations_page():
    supabase = get_supabase_client()
    # Fetch all doctors
    doctors_res = supabase.table("radiologists").select("*").order("name").execute()
    doctors = doctors_res.data

    # Fetch all vacations
    vacations_res = supabase.table("vacations").select("*, radiologists(*)").execute()
    vacations = vacations_res.data

    return render_template("vacations.html", doctors=doctors, vacations=vacations)

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
    supabase.table("vacations").insert(data).execute()
    return redirect(url_for("vacations.vacations_page"))

@vacations_bp.route('/vacations/update', methods=['POST'])
@with_supabase_auth
@admin_required
def update_vacation():
    supabase = get_supabase_client()
    vacation_id = request.form.get("vacation_id")
    data = {
        "radiologist_id": request.form.get("radiologist_id"),
        "start_date": request.form.get("start_date"),
        "end_date": request.form.get("end_date"),
        "comments": request.form.get("comments")
    }
    supabase.table("vacations").update(data).eq("id", vacation_id).execute()
    return redirect(url_for("vacations.vacations_page"))

@vacations_bp.route('/vacations/delete', methods=['POST'])
@with_supabase_auth
@admin_required
def delete_vacation():
    supabase = get_supabase_client()
    vacation_id = request.json.get("vacation_id")
    supabase.table("vacations").delete().eq("id", vacation_id).execute()
    return jsonify({"status": "success"})