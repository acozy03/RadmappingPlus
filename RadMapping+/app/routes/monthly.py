from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from app.admin_required import admin_required
from datetime import datetime, timedelta
from calendar import monthrange
from collections import defaultdict
import uuid
import calendar as pycalendar
from app.middleware import with_supabase_auth
from app.supabase_helper import fetch_all_rows_monthly, fetch_schedule_data
from app.supabase_client import get_supabase_client

monthly_bp = Blueprint('monthly', __name__)

supabase = get_supabase_client()
@monthly_bp.route('/monthly')
@with_supabase_auth
def monthly():
    supabase = get_supabase_client()
    now = datetime.now()
    year = request.args.get("year", default=now.year, type=int)
    month = request.args.get("month", default=now.month, type=int)
    start_day = request.args.get("start_day", default=1, type=int)
    days_in_month = monthrange(year, month)[1]

    window_dates = [datetime(year, month, d) for d in range(1, days_in_month + 1)]
    start_day = 1
    end_day = days_in_month

    start_doctor = request.args.get('start_doctor', default=0, type=int)
    doctors_per_page = 200

    all_doctors = fetch_all_rows_monthly("radiologists", "*", filters={"active_status": True})

    total_doctors = len(all_doctors)
    
    user_email = session["user"]["email"]
    pinned_data = fetch_all_rows_monthly("pinned_doctors", "*", filters={"user_id": user_email})
    pinned_doctor_ids = [p["doctor_id"] for p in pinned_data]

    pinned_doctors = [doc for doc in all_doctors if doc["id"] in pinned_doctor_ids]
    unpinned_doctors = [doc for doc in all_doctors if doc["id"] not in pinned_doctor_ids]

    pinned_doctors = sorted(pinned_doctors, key=lambda d: d['name'])
    unpinned_doctors = sorted(unpinned_doctors, key=lambda d: d['name'])

    if start_doctor == 0:
        if pinned_doctors:
            remaining_slots = doctors_per_page - len(pinned_doctors)
            if remaining_slots > 0:
                doctors = pinned_doctors + unpinned_doctors[:remaining_slots]
            else:
                doctors = pinned_doctors[:doctors_per_page]
        else:
            doctors = unpinned_doctors[:doctors_per_page]
    else:
        if pinned_doctors:
            first_page_unpinned = max(0, doctors_per_page - len(pinned_doctors))
            # Start index for unpinned doctors
            unpinned_start = first_page_unpinned + (start_doctor - doctors_per_page)
            doctors = unpinned_doctors[unpinned_start:unpinned_start + doctors_per_page]
        else:
            doctors = unpinned_doctors[start_doctor:start_doctor + doctors_per_page]

    start_str = window_dates[0].strftime("%Y-%m-%d")
    end_str = window_dates[-1].strftime("%Y-%m-%d")
    visible_doctor_ids = [str(d["id"]) for d in doctors]

    schedule_data = fetch_schedule_data(visible_doctor_ids, start_str, end_str)

    calendar = defaultdict(dict)
    for entry in schedule_data:
        start = datetime.strptime(entry["start_date"], "%Y-%m-%d")
        end = datetime.strptime(entry["end_date"], "%Y-%m-%d")
        for n in range((end - start).days + 1):
            date = (start + timedelta(days=n)).strftime("%Y-%m-%d")
            doc_id = str(entry["radiologist_id"]).strip()
            calendar[date][doc_id] = entry

    month_name = pycalendar.month_name[month]

    if pinned_doctors:
        remaining_unpinned = len(unpinned_doctors)
        if len(pinned_doctors) < doctors_per_page:
            remaining_unpinned -= (doctors_per_page - len(pinned_doctors))
        total_pages = 1 + max(0, (remaining_unpinned + doctors_per_page - 1) // doctors_per_page)
    else:
        total_pages = (total_doctors + doctors_per_page - 1) // doctors_per_page

    return render_template("monthly.html",
        doctors=doctors,
        window_dates=window_dates,
        year=year,
        month=month,
        month_name=month_name,
        start_day=start_day,
        end_day=end_day,
        days_in_month=days_in_month,
        prev_start=1,
        next_start=1,
        calendar=calendar,
        datetime=datetime,
        start_doctor=start_doctor,
        total_doctors=total_doctors,
        total_pages=total_pages,
        min=min,
        all_doctors=all_doctors,
        pinned_doctors=pinned_doctor_ids)

@monthly_bp.route('/monthly/pin', methods=['POST'])
@with_supabase_auth
def pin_doctors():
    supabase = get_supabase_client()
    data = request.get_json()
    doctor_ids = data.get('doctor_ids', [])
    user_email = session["user"]["email"]
    
    if len(doctor_ids) > 15:
        return jsonify({'success': False, 'error': 'Cannot pin more than 15 doctors'})
    
    supabase.table("pinned_doctors") \
        .delete() \
        .eq("user_id", user_email) \
        .execute()
    
    if doctor_ids:
        pins = [{
            "id": str(uuid.uuid4()),
            "user_id": user_email,
            "doctor_id": doctor_id
        } for doctor_id in doctor_ids]
        
        supabase.table("pinned_doctors").insert(pins).execute()
    
    return jsonify({'success': True})

@monthly_bp.route('/monthly/search', methods=["GET"])
@with_supabase_auth
def search_schedule():
    supabase = get_supabase_client()
    from collections import defaultdict
    import calendar as pycalendar

    page = request.args.get('page', 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page

    search_term = request.args.get('search', '').strip()
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)

    query = supabase.table("radiologists").select("*")
    # Only include active doctors in search results
    query = query.eq("active_status", True)

    if search_term:
        query = query.ilike('name', f'%{search_term}%')

    full_result = query.execute()
    all_matches = full_result.data
    total_count = len(all_matches)

    paginated_matches = sorted(all_matches, key=lambda d: d['name'])[offset:offset + per_page]

    matched_ids = [doc["id"] for doc in paginated_matches]
    
    first_day = datetime(year, month, 1).date()
    last_day = datetime(year, month, pycalendar.monthrange(year, month)[1]).date()

    schedule_resp = supabase.table("monthly_schedule") \
        .select("*") \
        .gte("start_date", first_day.isoformat()) \
        .lte("start_date", last_day.isoformat()) \
        .in_("radiologist_id", matched_ids) \
        .execute()
    
    calendar_data = defaultdict(dict)
    for row in schedule_resp.data:
        calendar_data[row['start_date']][row['radiologist_id']] = row

    return jsonify({
        'doctors': paginated_matches,
        'total_count': total_count,
        'current_page': page,
        'per_page': per_page,
        'calendar': calendar_data
    })

@monthly_bp.route('/monthly/bulk', methods=['POST'])
@with_supabase_auth
def bulk_schedule():
    supabase = get_supabase_client()
    if session["user"]["role"] != "admin":
        return "Unauthorized", 403

 
    
    doctor_id = request.form.get("doctor")
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")
    notes = request.form.get("schedule_details")
    is_special_case = notes in ['OFF', 'VACATION', 'REACH AS NEEDED']

    if not all([doctor_id, start_date, end_date]) or (not is_special_case and not all([start_time, end_time])):
        return "Missing data", 400

    # Convert dates to datetime objects
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    current = start

    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
      
        existing = supabase.table("monthly_schedule") \
            .select("id") \
            .eq("radiologist_id", doctor_id) \
            .eq("start_date", date_str) \
            .eq("end_date", date_str).execute()

        payload = {
            "radiologist_id": doctor_id,
            "start_date": date_str,
            "end_date": date_str,
            "start_time": start_time if not is_special_case else None,
            "end_time": end_time if not is_special_case else None,
            "schedule_details": notes
        }

       
        if existing.data:
       
            supabase.table("monthly_schedule").update(payload) \
                .eq("id", existing.data[0]["id"]).execute()
        else:
          
            supabase.table("monthly_schedule").insert(payload).execute()

        current += timedelta(days=1)

    return redirect(url_for("monthly.monthly"))

@monthly_bp.route('/monthly/pattern', methods=['POST'])
@with_supabase_auth
def pattern_schedule():
    supabase = get_supabase_client()
    if session["user"]["role"] != "admin":
        return "Unauthorized", 403
    
    doctor_id = request.form.get("doctor")
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")
    days = request.form.getlist("days")  
    notes = request.form.get("schedule_details")

    is_special_case = notes in ['OFF', 'VACATION', 'REACH AS NEEDED']

    if not all([doctor_id, start_date, end_date, days]) or (not is_special_case and not all([start_time, end_time])):
        return "Missing data", 400

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    current = start

    while current <= end:
     
        if str(current.weekday()) in days:
            date_str = current.strftime("%Y-%m-%d")
            existing = supabase.table("monthly_schedule") \
                .select("id") \
                .eq("radiologist_id", doctor_id) \
                .eq("start_date", date_str) \
                .eq("end_date", date_str).execute()

            payload = {
                "radiologist_id": doctor_id,
                "start_date": date_str,
                "end_date": date_str,
                "start_time": start_time if not is_special_case else None,
                "end_time": end_time if not is_special_case else None,
                "schedule_details": notes
            }

         

            if existing.data:
              
                supabase.table("monthly_schedule").update(payload) \
                    .eq("id", existing.data[0]["id"]).execute()
            else:
               
                supabase.table("monthly_schedule").insert(payload).execute()

        current += timedelta(days=1)

    return redirect(url_for("monthly.monthly"))

@monthly_bp.route('/monthly/<string:rad_id>/delete_schedule', methods=["POST"])
@with_supabase_auth
def delete_schedule(rad_id):
    supabase = get_supabase_client()
    if session["user"]["role"] != "admin":
        return "Unauthorized", 403

    date = request.form.get("date")
    year = request.form.get("year")
    month = request.form.get("month")
    start_day = request.form.get("start_day")
    supabase.table("monthly_schedule").delete() \
        .eq("radiologist_id", rad_id).eq("start_date", date).eq("end_date", date).execute()

    return redirect(url_for("monthly.monthly", year=year, month=month, start_day=start_day))

@monthly_bp.route('/monthly/<string:rad_id>/update_schedule', methods=["POST"])
@with_supabase_auth
def update_schedule(rad_id):
    supabase = get_supabase_client()
    if session["user"]["role"] != "admin":
        return "Unauthorized", 403

    date = request.form.get("date")
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")
    details = request.form.get("schedule_details")

    data = {
        "start_time": start_time or None,
        "end_time": end_time or None,
        "schedule_details": details or None
    }

    existing = supabase.table("monthly_schedule") \
        .select("id") \
        .eq("radiologist_id", rad_id) \
        .eq("start_date", date) \
        .eq("end_date", date).execute()

    if existing.data:
        supabase.table("monthly_schedule").update(data) \
            .eq("id", existing.data[0]["id"]).execute()
    else:
        data["radiologist_id"] = rad_id
        data["start_date"] = date
        data["end_date"] = date
        supabase.table("monthly_schedule").insert(data).execute()

    year = request.form.get("year")
    month = request.form.get("month")
    start_day = request.form.get("start_day")
    return redirect(url_for("monthly.monthly", year=year, month=month, start_day=start_day))
