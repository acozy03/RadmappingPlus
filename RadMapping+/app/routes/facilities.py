# app/routes/facilities.py
from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from app.admin_required import admin_required
from app.supabase_client import supabase # Assuming this is correctly configured from environment
import uuid
from app.middleware import with_supabase_auth
from app.supabase_client import get_supabase_client
from app.audit_log import log_audit_action

facilities_bp = Blueprint('facilities', __name__)

@facilities_bp.route('/facilities')
@with_supabase_auth
def facilities():
    supabase = get_supabase_client()
    page = request.args.get('page', 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page

    # Fetch all prioritized facility IDs
    prioritized_res = supabase.table("prioritized_facilities").select("facility_id").execute()
    prioritized_facility_ids = {p["facility_id"] for p in (prioritized_res.data or [])}

    # Build base query to get ALL facilities (no pagination yet)
    query = supabase.table("facilities").select("*")

    # Execute query to get all facilities BEFORE any pagination
    all_facilities_from_db = query.execute().data or []

    # Separate facilities into prioritized and unprioritized lists
    prioritized_facilities_list = []
    unprioritized_facilities_list = []
    for fac in all_facilities_from_db:
        if fac["id"] in prioritized_facility_ids:
            prioritized_facilities_list.append(fac)
        else:
            unprioritized_facilities_list.append(fac)

    # Sort prioritized facilities by name
    prioritized_facilities_list.sort(key=lambda f: f["name"].lower())
    # Sort unprioritized facilities by name
    unprioritized_facilities_list.sort(key=lambda f: f["name"].lower())

    # Combine them: prioritized first, then unprioritized
    sorted_facilities = prioritized_facilities_list + unprioritized_facilities_list
    total_count = len(sorted_facilities)

    # Apply pagination on the fully sorted list
    visible_facilities = sorted_facilities[offset:offset + per_page]

    return render_template("facility_list.html",
                         facilities=visible_facilities,
                         total_count=total_count,
                         current_page=page,
                         per_page=per_page,
                         prioritized_facility_ids=list(prioritized_facility_ids)) # Pass to template for UI display


@facilities_bp.route('/facilities/search', methods=["GET"])
@with_supabase_auth
def search_facilities():
    supabase = get_supabase_client()
    search_term = request.args.get('search', '')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 25))
    status = request.args.get('status', 'all')
    fetch_all = request.args.get('fetch_all', 'false').lower() == 'true' # New parameter

    # Fetch all prioritized facility IDs
    prioritized_res = supabase.table("prioritized_facilities").select("facility_id").execute()
    prioritized_facility_ids = {p["facility_id"] for p in (prioritized_res.data or [])}

    # Build base query to get ALL matching facilities (no pagination yet)
    query = supabase.table("facilities").select("*")
    if search_term:
        query = query.ilike("name", f"%{search_term}%")
    if status == "active":
        query = query.eq("active_status", "true")
    elif status == "inactive":
        query = query.eq("active_status", "false")

    # Execute query to get all matching facilities BEFORE any pagination
    all_matching_facilities = query.execute().data or []

    # Separate matching facilities into prioritized and unprioritized lists
    prioritized_matching_facilities = []
    unprioritized_matching_facilities = []
    for fac in all_matching_facilities:
        if fac["id"] in prioritized_facility_ids:
            prioritized_matching_facilities.append(fac)
        else:
            unprioritized_matching_facilities.append(fac)

    # Sort each group by name
    prioritized_matching_facilities.sort(key=lambda f: f["name"].lower())
    unprioritized_matching_facilities.sort(key=lambda f: f["name"].lower())

    # Combine them: prioritized first, then unprioritized
    sorted_matching_facilities = prioritized_matching_facilities + unprioritized_matching_facilities
    total_count = len(sorted_matching_facilities) # Total count of filtered and sorted facilities

    # Apply pagination ONLY if fetch_all is not true
    if not fetch_all:
        offset = (page - 1) * per_page
        visible_facilities = sorted_matching_facilities[offset:offset + per_page]
    else:
        # If fetch_all is true, return all sorted facilities
        visible_facilities = sorted_matching_facilities

    return jsonify({
        "facilities": visible_facilities,
        "total_count": total_count, # This is now the total count of filtered facilities
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

    # Validate that facility_ids_to_prioritize is a list
    if not isinstance(facility_ids_to_prioritize, list):
        return jsonify({'success': False, 'error': 'Invalid input: facility_ids must be a list.'}), 400

    # Optional: Add a limit to the number of prioritized facilities if needed (e.g., 15)
    # if len(facility_ids_to_prioritize) > 15:
    #     return jsonify({'success': False, 'error': 'Cannot prioritize more than 15 facilities.'}), 400

    try:
        # Delete all existing prioritized facilities (global update)
        # For a truly global update, we don't need a user_id filter.
        # This means all existing entries are removed and replaced by the new list.
        supabase.table("prioritized_facilities").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute() # Delete all

        # Insert new prioritized facilities
        if facility_ids_to_prioritize:
            new_priorities = [{
                "id": str(uuid.uuid4()), # Generate a new UUID for each entry
                "facility_id": fac_id
            } for fac_id in facility_ids_to_prioritize]

            supabase.table("prioritized_facilities").insert(new_priorities).execute()

        # Log audit action
        log_audit_action(
            supabase=supabase,
            action="update",
            table_name="prioritized_facilities",
            record_id="global_prioritization_update", # Use a generic ID for global changes
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data={"prioritized_facility_ids_before_update": None}, # Could fetch old for more detail
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

# The rest of your existing routes in facilities.py would follow here,
# unchanged unless they need to interact with prioritization directly (e.g., UI for prioritization).

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
        "active_status": "true" if request.form.get("active_status") == "true" else "false"
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