from datetime import datetime, timedelta
import logging
import uuid

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from app.admin_required import admin_required
from app.audit_log import log_audit_action
from app.middleware import with_supabase_auth
from app.supabase_client import get_supabase_client

vacations_bp = Blueprint("vacations", __name__)
VALID_VACATION_STATUSES = {"pending", "approved", "rejected", "cancelled"}


def _parse_form_boolean(field_name: str) -> bool:
    value = request.form.get(field_name)
    return value in {"on", "true", "1", "yes"}


def _build_vacation_payload() -> dict:
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")
    half_day = _parse_form_boolean("half_day")
    status = (request.form.get("status") or "pending").strip().lower()

    if status not in VALID_VACATION_STATUSES:
        status = "pending"

    if half_day and start_date:
        end_date = start_date

    return {
        "radiologist_id": request.form.get("radiologist_id"),
        "start_date": start_date,
        "end_date": end_date,
        "comments": request.form.get("comments"),
        "half_day": half_day,
        "status": status,
    }


def _validate_vacation_payload(data: dict) -> bool:
    start_date = data.get("start_date")
    end_date = data.get("end_date")

    if not start_date or not end_date:
        return False

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        return False

    if end < start:
        return False

    if data.get("half_day") and start != end:
        return False

    return True


@vacations_bp.route("/vacations")
@with_supabase_auth
def vacations_page():
    supabase = get_supabase_client()

    logging.info("Fetching doctors and vacations for vacations_page.")

    doctors_res = supabase.table("radiologists").select("*").order("name").execute()
    doctors = doctors_res.data
    logging.info("Fetched %d doctors.", len(doctors))

    vacations_res = supabase.table("vacations").select("*, radiologists(*)").execute()
    vacations = vacations_res.data
    logging.info("Fetched %d vacations from Supabase.", len(vacations))

    processed_vacations = []
    for vacation in vacations:
        logging.info(
            "Processing vacation ID: %s, Raw Start Date: %s, Raw End Date: %s",
            vacation.get("id"),
            vacation.get("start_date"),
            vacation.get("end_date"),
        )

        if vacation.get("start_date"):
            try:
                vacation["start_date"] = datetime.strptime(vacation["start_date"], "%Y-%m-%d")
            except ValueError as error:
                logging.error(
                    "Error converting start_date '%s' for vacation %s: %s",
                    vacation.get("start_date"),
                    vacation.get("id"),
                    error,
                )
                vacation["start_date"] = None

        if vacation.get("end_date"):
            try:
                vacation["end_date"] = datetime.strptime(vacation["end_date"], "%Y-%m-%d")
            except ValueError as error:
                logging.error(
                    "Error converting end_date '%s' for vacation %s: %s",
                    vacation.get("end_date"),
                    vacation.get("id"),
                    error,
                )
                vacation["end_date"] = None

        vacation["half_day"] = bool(vacation.get("half_day"))
        vacation["status"] = (vacation.get("status") or "pending").lower()
        processed_vacations.append(vacation)

    today = datetime.now().date()
    month_start = today.replace(day=1)
    next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    month_end = next_month - timedelta(days=1)

    for vacation in processed_vacations:
        start = vacation.get("start_date").date() if vacation.get("start_date") else None
        end = vacation.get("end_date").date() if vacation.get("end_date") else None
        vacation["is_active_this_month"] = bool(start and end and start <= month_end and end >= month_start)
        vacation["is_upcoming"] = bool(start and start > today)

    return render_template(
        "vacations.html",
        doctors=doctors,
        vacations=processed_vacations,
        today=today,
        month_start=month_start,
        month_end=month_end,
    )


@vacations_bp.route("/vacations/add", methods=["POST"])
@with_supabase_auth
@admin_required
def add_vacation():
    supabase = get_supabase_client()
    data = {"id": str(uuid.uuid4()), **_build_vacation_payload()}

    if not _validate_vacation_payload(data):
        logging.warning("Invalid vacation payload on add: %s", data)
        return redirect(url_for("vacations.vacations_page"))

    result = supabase.table("vacations").insert(data).execute()

    if not hasattr(result, "error"):
        log_audit_action(
            supabase=supabase,
            action="insert",
            table_name="vacations",
            record_id=data["id"],
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=None,
            new_data=data,
        )

    return redirect(url_for("vacations.vacations_page"))


@vacations_bp.route("/vacations/update", methods=["POST"])
@with_supabase_auth
@admin_required
def update_vacation():
    supabase = get_supabase_client()
    vacation_id = request.form.get("vacation_id")

    old_data = supabase.table("vacations").select("*").eq("id", vacation_id).single().execute().data

    data = _build_vacation_payload()

    if not _validate_vacation_payload(data):
        logging.warning("Invalid vacation payload on update (%s): %s", vacation_id, data)
        return redirect(url_for("vacations.vacations_page"))

    result = supabase.table("vacations").update(data).eq("id", vacation_id).execute()

    if not hasattr(result, "error"):
        log_audit_action(
            supabase=supabase,
            action="update",
            table_name="vacations",
            record_id=vacation_id,
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=old_data,
            new_data=data,
        )

    return redirect(url_for("vacations.vacations_page"))


@vacations_bp.route("/vacations/delete", methods=["POST"])
@with_supabase_auth
@admin_required
def delete_vacation():
    supabase = get_supabase_client()
    vacation_id = request.json.get("vacation_id")

    old_data = supabase.table("vacations").select("*").eq("id", vacation_id).single().execute().data
    result = supabase.table("vacations").delete().eq("id", vacation_id).execute()

    if not hasattr(result, "error"):
        log_audit_action(
            supabase=supabase,
            action="delete",
            table_name="vacations",
            record_id=vacation_id,
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=old_data,
            new_data=None,
        )

    return jsonify({"status": "success"})
