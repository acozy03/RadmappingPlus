# app/routes/facilities.py
from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from app.admin_required import admin_required
from app.supabase_client import supabase # Assuming this is correctly configured from environment
import uuid
from app.middleware import with_supabase_auth
from app.supabase_client import get_supabase_client
from app.audit_log import log_audit_action
import time 
from flask import g
facilities_bp = Blueprint('facilities', __name__)

_cached_prioritized_facility_ids = None
_last_prioritized_fetch_time = 0
CACHE_EXPIRATION_SECONDS = 300 # Cache for 5 minutes (adjust as needed)

def _get_prioritized_facility_ids_cached(supabase_client):
    global _cached_prioritized_facility_ids, _last_prioritized_fetch_time

    current_time = time.time()
    # Refresh cache if it's empty or expired
    if _cached_prioritized_facility_ids is None or (current_time - _last_prioritized_fetch_time > CACHE_EXPIRATION_SECONDS):
        print("Refreshing prioritized facility IDs cache...")
        prioritized_res = supabase_client.table("prioritized_facilities").select("facility_id").execute()
        _cached_prioritized_facility_ids = {p["facility_id"] for p in (prioritized_res.data or [])}
        _last_prioritized_fetch_time = current_time
    return _cached_prioritized_facility_ids

@facilities_bp.route('/facilities')
@with_supabase_auth
def facilities():
    supabase = get_supabase_client()
    page = request.args.get('page', 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page
    status = request.args.get('status', 'active')

    # Use the cached version
    prioritized_facility_ids = _get_prioritized_facility_ids_cached(supabase)

    base_query = supabase.table("facilities").select("*")

    if status == "active":
        base_query = base_query.eq("active_status", "true")
    elif status == "inactive":
        base_query = base_query.eq("active_status", "false")

    all_facilities_from_db_raw = base_query.execute().data or []

    prioritized_facilities_list = []
    unprioritized_facilities_list = []
    for fac in all_facilities_from_db_raw:
        if fac["id"] in prioritized_facility_ids:
            prioritized_facilities_list.append(fac)
        else:
            unprioritized_facilities_list.append(fac)

    prioritized_facilities_list.sort(key=lambda f: f["name"].lower())
    unprioritized_facilities_list.sort(key=lambda f: f["name"].lower())

    sorted_facilities = prioritized_facilities_list + unprioritized_facilities_list
    total_count = len(sorted_facilities)

    visible_facilities = sorted_facilities[offset:offset + per_page]

    return render_template("facility_list.html",
                         facilities=visible_facilities,
                         total_count=total_count,
                         current_page=page,
                         per_page=per_page,
                         prioritized_facility_ids=list(prioritized_facility_ids))


@facilities_bp.route('/facilities/search', methods=["GET"])
@with_supabase_auth
def search_facilities():
    # It's crucial that get_supabase_client() is called here
    # as it sets the session for the current request.
    # The actual supabase client instance is then stored on 'g'.
    # We will time the *first* Supabase interaction in this function,
    # which will include the cost of set_session if it hasn't happened yet.
    
    function_start_time = time.time()

    # Call get_supabase_client() which handles session setting and client caching
    # for the current request context (g object).
    start_supabase_client_access = time.time()
    supabase = get_supabase_client() # This call might include set_session
    time_to_get_supabase_client = time.time() - start_supabase_client_access
    print(f"Time to get/initialize Supabase client (includes set_session if first access): {time_to_get_supabase_client:.4f}s")

    search_term_name = request.args.get('search_name', '').strip()
    state_filter = request.args.get('state', '').strip().upper()
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 25))
    status = request.args.get('status', 'all')
    fetch_all = request.args.get('fetch_all', 'false').lower() == 'true'

    # The prioritized IDs cache is independent of the user session setup,
    # so its timing remains separate and valid.
    start_time_cache = time.time()
    prioritized_facility_ids = _get_prioritized_facility_ids_cached(supabase) # Pass the obtained client
    print(f"Time to fetch prioritized IDs (cached): {time.time() - start_time_cache:.4f}s")

    # --- Detailed timing for actual query object building ---
    query_object_build_start_time = time.time() # This is the true start for query object building

    step_start = time.time()
    query = supabase.table("facilities").select("id, name, location, active_status")
    print(f"  - Time for .select() method call: {time.time() - step_start:.4f}s")

    if search_term_name:
        step_start = time.time()
        query = query.ilike("name", f"%{search_term_name}%")
        print(f"  - Time for .ilike() method call: {time.time() - step_start:.4f}s")

    if state_filter:
        step_start = time.time()
        query = query.eq("location", state_filter)
        print(f"  - Time for .eq('location') method call: {time.time() - step_start:.4f}s")

    if status == "active":
        step_start = time.time()
        query = query.eq("active_status", "true")
        print(f"  - Time for .eq('active_status') method call: {time.time() - step_start:.4f}s")
    elif status == "inactive":
        step_start = time.time()
        query = query.eq("active_status", "false")
        print(f"  - Time for .eq('active_status') method call: {time.time() - step_start:.4f}s")

    print(f"Total time to build Supabase query object (in Python): {time.time() - query_object_build_start_time:.4f}s")
    # --- End detailed timing for query object building ---


    start_time_meta_query = time.time()
    all_matching_meta = query.execute().data or []
    print(f"Time for initial filtered metadata query (DB roundtrip): {time.time() - start_time_meta_query:.4f}s")
    print(f"Number of matching metadata records: {len(all_matching_meta)}")

    start_time_sort = time.time()
    prioritized_matching_facilities_meta = []
    unprioritized_matching_facilities_meta = []
    for fac_meta in all_matching_meta:
        if fac_meta["id"] in prioritized_facility_ids:
            prioritized_matching_facilities_meta.append(fac_meta)
        else:
            unprioritized_matching_facilities_meta.append(fac_meta)

    prioritized_matching_facilities_meta.sort(key=lambda f: f["name"].lower())
    unprioritized_matching_facilities_meta.sort(key=lambda f: f["name"].lower())

    sorted_matching_facilities_meta = prioritized_matching_facilities_meta + unprioritized_matching_facilities_meta
    total_count = len(sorted_matching_facilities_meta)
    print(f"Time for Python-side prioritization and sorting: {time.time() - start_time_sort:.4f}s")

    start_time_ids = time.time()
    visible_facilities_ids = []
    
    if fetch_all: # If fetching all, we don't need to do a second query with `in_`
        # Instead, the `sorted_matching_facilities_meta` already contains
        # all the filtered and sorted data needed if fetch_all is true.
        visible_facilities = sorted_matching_facilities_meta
        total_count = len(visible_facilities) # Re-confirm total count
        print(f"Time for determining visible facility IDs (fetch_all): {time.time() - start_time_ids:.4f}s")
        print(f"Skipping full details fetch as fetch_all is true.")
    else:
        offset = (page - 1) * per_page
        visible_facilities_ids = [f["id"] for f in sorted_matching_facilities_meta[offset:offset + per_page]]
        print(f"Time for determining visible facility IDs: {time.time() - start_time_ids:.4f}s")

        # Log: Fetching full details for visible facilities
        start_time_full_details = time.time()
        visible_facilities = []
        if visible_facilities_ids: # This check is still important for paginated views
            print(f"DEBUG: Number of IDs for full details fetch: {len(visible_facilities_ids)}")
            print(f"DEBUG: Sample IDs: {visible_facilities_ids[:5]}")
            full_details_res = supabase.table("facilities").select("*").in_("id", visible_facilities_ids).execute()
            full_details_map = {fac["id"]: fac for fac in (full_details_res.data or [])}
            visible_facilities = [full_details_map[fac_id] for fac_id in visible_facilities_ids if fac_id in full_details_map]
        print(f"Time for fetching full details (DB roundtrip): {time.time() - start_time_full_details:.4f}s")

    # ... (rest of the function, including the final jsonify)
    return jsonify({
        "facilities": visible_facilities,
        "total_count": total_count, # Use the total_count from sorted_matching_facilities_meta
        "current_page": page,
        "per_page": per_page
    })

@facilities_bp.route('/facilities/prioritize', methods=['POST'])
@with_supabase_auth
@admin_required
def prioritize_facilities():
    supabase = get_supabase_client()
    data = request.get_json()
    facility_ids_to_prioritize = data.get('facility_ids', [])

    if not isinstance(facility_ids_to_prioritize, list):
        return jsonify({'success': False, 'error': 'Invalid input: facility_ids must be a list.'}), 400

    try:
        supabase.table("prioritized_facilities").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()

        if facility_ids_to_prioritize:
            new_priorities = [{
                "id": str(uuid.uuid4()),
                "facility_id": fac_id
            } for fac_id in facility_ids_to_prioritize]

            supabase.table("prioritized_facilities").insert(new_priorities).execute()

        # Invalidate the cache after an update
        global _cached_prioritized_facility_ids, _last_prioritized_fetch_time
        _cached_prioritized_facility_ids = None
        _last_prioritized_fetch_time = 0 # Forces a refresh on next call


        log_audit_action(
            supabase=supabase,
            action="update",
            table_name="prioritized_facilities",
            record_id="global_prioritization_update",
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data={"prioritized_facility_ids_before_update": None},
            new_data={"prioritized_facility_ids_after_update": facility_ids_to_prioritize}
        )

        return jsonify({'success': True}), 200
    except Exception as e:
        log_audit_action(
            supabase=supabase,
            action="error",
            table_name="prioritized_facilities",
            record_id="global_prioritization_error",
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=None,
            new_data={"error_message": str(e), "requested_ids": facility_ids_to_prioritize}
        )
        return jsonify({'success': False, 'error': str(e)}), 500

@facilities_bp.route('/facilities/<string:facility_id>')
@with_supabase_auth
def facility_profile(facility_id):
    supabase = get_supabase_client()
    # Get facility info
    fac = supabase.table("facilities").select("*").eq("id", facility_id).single().execute().data

    # Fetch all prioritized facility IDs to check if the current facility is prioritized
    prioritized_res = supabase.table("prioritized_facilities").select("facility_id").execute()
    prioritized_facility_ids = {p["facility_id"] for p in (prioritized_res.data or [])}


    assignment_res = supabase.table("doctor_facility_assignments") \
        .select("*, radiologists(*)") \
        .eq("facility_id", facility_id) \
        .execute()

    # Sort by radiologist name (case-insensitive)
    sorted_assignments = sorted(
        assignment_res.data,
        key=lambda a: (a.get("radiologists") or {}).get("name", "").lower()
    )

    print(f"Sorted assignments: {sorted_assignments}")
    assigned_radiologist_ids = {a["radiologist_id"] for a in sorted_assignments}

     # Get all radiologists
    all_rads_res = supabase.table("radiologists").select("id, name").order("name").execute()
    all_radiologists = all_rads_res.data or []
    available_radiologists = [r for r in all_radiologists if r["id"] not in assigned_radiologist_ids]
    
    # Get facility contacts
    contacts_res = supabase.table("facility_contact_assignments") \
        .select("*") \
        .eq("facility_id", facility_id) \
        .execute()

    contacts = contacts_res.data or []

    # Sort contacts by custom priority
    preferred_order = [
        "Primary Contact",
        "Secondary Contact",
        "Positive Findings",
        "Critical Finding",
        "Management Contact",
        "Facility Address",
        "Billing Contact",
        "Credentialing Contact"
    ]

    def sort_key(contact):
        try:
            return preferred_order.index(contact['role'])
        except ValueError:
            return 999  # unknown roles go to the end

    contacts.sort(key=sort_key)

    return render_template("facility_profile.html",
        facility=fac,
        doctor_assignments=sorted_assignments,
        facility_contacts=contacts,
        available_radiologists=available_radiologists,
        prioritized_facility_ids=list(prioritized_facility_ids) # Pass to template for UI display
    )


@facilities_bp.route('/facilities/<string:facility_id>/contacts/add', methods=['POST'])
@with_supabase_auth
@admin_required
def add_facility_contact(facility_id):
    supabase = get_supabase_client()
    data = {
        "id": str(uuid.uuid4()),
        "facility_id": facility_id,
        "text": request.form.get("text"),
        "role": request.form.get("role")
    }
    
    res = supabase.table("facility_contact_assignments").insert(data).execute()
    
    if not hasattr(res, "error"):
        log_audit_action(
            supabase=supabase,
            action="insert",
            table_name="facility_contact_assignments",
            record_id=data["id"],
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=None,
            new_data=data
        )

    return redirect(url_for("facilities.facility_profile", facility_id=facility_id))

@facilities_bp.route('/facilities/<string:facility_id>/contacts/<string:contact_id>', methods=['POST'])
@with_supabase_auth
@admin_required
def edit_facility_contact(facility_id, contact_id):
    supabase = get_supabase_client()
    data = {
        "text": request.form.get("text"),
        "role": request.form.get("role")
    }

    old_data = supabase.table("facility_contact_assignments").select("*").eq("id", contact_id).single().execute().data
    res = supabase.table("facility_contact_assignments").update(data).eq("id", contact_id).execute()
    
    if not hasattr(res, "error"):
        log_audit_action(
            supabase=supabase,
            action="update",
            table_name="facility_contact_assignments",
            record_id=contact_id,
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=old_data,
            new_data=data
        )

    return redirect(url_for("facilities.facility_profile", facility_id=facility_id))

@facilities_bp.route('/facility/<string:facility_id>/contact/<string:contact_id>', methods=['DELETE'])
@with_supabase_auth
@admin_required
def delete_facility_contact_api(facility_id, contact_id):
    try:
        supabase = get_supabase_client()
        
        # First verify the contact exists and belongs to the facility
        verify = supabase.table("facility_contact_assignments")\
            .select("*")\
            .eq("id", contact_id)\
            .eq("facility_id", facility_id)\
            .execute()
            
        if not verify.data:
            return jsonify({"success": False, "error": "Contact not found"}), 404

        old_data = verify.data[0] # Get old data before deletion
        result = supabase.table("facility_contact_assignments")\
            .delete()\
            .eq("id", contact_id)\
            .eq("facility_id", facility_id)\
            .execute()
            
        if result.data:
            log_audit_action(
                supabase=supabase,
                action="delete",
                table_name="facility_contact_assignments",
                record_id=contact_id,
                user_email=session.get("user", {}).get("email", "unknown"),
                old_data=old_data,
                new_data=None
            )
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": "Delete operation failed"}), 500
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@facilities_bp.route('/facilities/<facility_id>/bulk_update_assignments', methods=['POST'])
@with_supabase_auth
@admin_required
def bulk_update_assignments(facility_id):
    supabase = get_supabase_client()
    assignment_ids = request.form.getlist("assignment_ids[]") or request.form.getlist("assignment_ids")

    for assignment_id in assignment_ids:
        # Get old data for doctor_facility_assignments
        old_assignment_data = supabase.table('doctor_facility_assignments').select('*').eq('id', assignment_id).single().execute().data

        # Update assignment's can_read status
        can_read = request.form.get(f'can_read_{assignment_id}', 'true')
        notes = request.form.get(f'notes_{assignment_id}', '')
        
        new_assignment_data = {
            'can_read': can_read,
            'notes': notes
        }

        # Check if assignment data has actually changed before updating
        assignment_changed = False
        if old_assignment_data:
            if old_assignment_data.get('can_read') != new_assignment_data['can_read'] or \
               old_assignment_data.get('notes') != new_assignment_data['notes']:
                assignment_changed = True
        elif new_assignment_data['can_read'] != 'true' or new_assignment_data['notes'] != '': # New entry, consider if defaults changed
             assignment_changed = True


        if assignment_changed:
            assignment_res = supabase.table('doctor_facility_assignments').update(new_assignment_data).eq('id', assignment_id).execute()
            if not hasattr(assignment_res, "error"):
                log_audit_action(
                    supabase=supabase,
                    action="update",
                    table_name="doctor_facility_assignments",
                    record_id=assignment_id,
                    user_email=session.get("user", {}).get("email", "unknown"),
                    old_data=old_assignment_data,
                    new_data=new_assignment_data
                )

        # Get corresponding radiologist ID from the assignment
        rad_id = old_assignment_data['radiologist_id'] # Use old_assignment_data for rad_id

        # Get old data for radiologists
        old_radiologist_data = supabase.table('radiologists').select('*').eq('id', rad_id).single().execute().data

        # Update fields on the radiologists table
        reads_stats = 'reads_stats_' + rad_id in request.form
        reads_routines = 'reads_routines_' + rad_id in request.form
        stipulations = request.form.get(f'stipulations_{rad_id}', '')
        
        new_radiologist_data = {
            'reads_stats': 'YES' if reads_stats else 'NO',
            'reads_routines': 'YES' if reads_routines else 'NO',
            'stipulations': stipulations
        }

        # Check if radiologist data has actually changed before updating
        radiologist_changed = False
        if old_radiologist_data:
            if old_radiologist_data.get('reads_stats') != new_radiologist_data['reads_stats'] or \
               old_radiologist_data.get('reads_routines') != new_radiologist_data['reads_routines'] or \
               old_radiologist_data.get('stipulations') != new_radiologist_data['stipulations']:
                radiologist_changed = True
        
        if radiologist_changed:
            radiologist_res = supabase.table('radiologists').update(new_radiologist_data).eq('id', rad_id).execute()
            if not hasattr(radiologist_res, "error"):
                log_audit_action(
                    supabase=supabase,
                    action="update",
                    table_name="radiologists",
                    record_id=rad_id,
                    user_email=session.get("user", {}).get("email", "unknown"),
                    old_data=old_radiologist_data,
                    new_data=new_radiologist_data
                )

    return redirect(url_for('facilities.facility_profile', facility_id=facility_id))



@facilities_bp.route('/facilities/<facility_id>/assign_radiologist', methods=['POST'])
@with_supabase_auth
@admin_required
def assign_radiologist(facility_id):
    supabase = get_supabase_client()
    data = {
        "id": str(uuid.uuid4()),
        "radiologist_id": request.form.get("radiologist_id"),
        "facility_id": facility_id,
        "can_read": request.form.get("can_read", "empty"),
    }
    res = supabase.table("doctor_facility_assignments").insert(data).execute()

    if not hasattr(res, "error"):
        log_audit_action(
            supabase=supabase,
            action="insert",
            table_name="doctor_facility_assignments",
            record_id=data["id"],
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=None,
            new_data=data
        )

    return redirect(url_for("facilities.facility_profile", facility_id=facility_id))


@facilities_bp.route('/facilities/<facility_id>/remove', methods=['POST'])
@with_supabase_auth
@admin_required
def remove_facility(facility_id):
    supabase = get_supabase_client()
    old_data = supabase.table('facilities').select('*').eq('id', facility_id).single().execute().data
    res = supabase.table('facilities').delete().eq('id', facility_id).execute()

    if not hasattr(res, "error"):
        log_audit_action(
            supabase=supabase,
            action="delete",
            table_name="facilities",
            record_id=facility_id,
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=old_data,
            new_data=None
        )
    return redirect(url_for('facilities.facilities'))

@facilities_bp.route('/radmapping/facility/<facility_id>/update', methods=['POST'])
@with_supabase_auth
@admin_required
def update_facility(facility_id):
    supabase = get_supabase_client()
    form = request.form
    
    data = {
        'name': form.get('name'),
        'location': form.get('location'),
        'pacs': form.get('pacs'),
        'tat_definition': form.get('tat_definition'),
        'modalities_assignment_period': form.get('assignment_period'),
        'modalities': form.get('assignment_type'),
        'qa_criteria': form.get('qa_criteria'),
        'monitoring': form.get('monitoring'),
        'active_status': 'true' if form.get('active_status') == 'true' else 'false',
        'account_poc': form.get('account_poc')  
    }

    old_data = supabase.table('facilities').select('*').eq('id', facility_id).single().execute().data
    res = supabase.table('facilities').update(data).eq('id', facility_id).execute()

    if not hasattr(res, "error"):
        log_audit_action(
            supabase=supabase,
            action="update",
            table_name="facilities",
            record_id=facility_id,
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=old_data,
            new_data=data
        )
    return redirect(url_for('facilities.facility_profile', facility_id=facility_id))

@facilities_bp.route('/facilities/<string:facility_id>/assignments/<string:assignment_id>/remove', methods=['POST'])
@with_supabase_auth
@admin_required
def remove_assignment(facility_id, assignment_id):
    supabase = get_supabase_client()
    old_data = supabase.table("doctor_facility_assignments").select("*").eq("id", assignment_id).single().execute().data
    # Delete the assignment
    res = supabase.table("doctor_facility_assignments").delete().eq("id", assignment_id).execute()
    
    if not hasattr(res, "error"):
        log_audit_action(
            supabase=supabase,
            action="delete",
            table_name="doctor_facility_assignments",
            record_id=assignment_id,
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=old_data,
            new_data=None
        )
    return redirect(url_for("facilities.facility_profile", facility_id=facility_id))


@facilities_bp.route('/facilities/add', methods=['POST'])
@with_supabase_auth
@admin_required
def add_facility():
    supabase = get_supabase_client()
    # Generate a new UUID for the doctor
    new_id = str(uuid.uuid4())
    
    data = {
        "id": new_id,
        "name": request.form.get("name"),
        "pacs": request.form.get("pacs"),
        "location": request.form.get("location"),
        "modalities_assignment_period": request.form.get("modalities_assignment_period"),
        "tat_definition": request.form.get("tat_definition"),
        "modalities": request.form.get("modalities"),
        "active_status": "true" if request.form.get("active_status") == "true" else "false",
        "qa_criteria": request.form.get("qa_criteria"),
        "monitoring": request.form.get("monitoring"),
        "account_poc": request.form.get("account_poc")  
    }

    # Insert the new doctor into the database
    res = supabase.table("facilities").insert(data).execute()

    if not hasattr(res, "error"):
        log_audit_action(
            supabase=supabase,
            action="insert",
            table_name="facilities",
            record_id=new_id,
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=None,
            new_data=data
        )

    return redirect(url_for("facilities.facilities", rad_id=new_id))