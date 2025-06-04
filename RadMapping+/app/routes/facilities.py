from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from app.admin_required import admin_required
from app.supabase_client import supabase
import uuid
from app.middleware import with_supabase_auth
from app.supabase_client import get_supabase_client

facilities_bp = Blueprint('facilities', __name__)



@facilities_bp.route('/facilities')
@with_supabase_auth
def facilities():
    supabase = get_supabase_client()
    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page

    # Get total count for pagination
    count_res = supabase.table("facilities").select("*", count='exact').execute()
    total_count = count_res.count

    # Fetch paginated facilities
    res = supabase.table("facilities") \
        .select("*", count='exact') \
        .order("name") \
        .order("id") \
        .range(offset, offset + per_page - 1) \
        .execute()

    facilities = res.data

    return render_template("facility_list.html", 
                         facilities=facilities,
                         total_count=total_count,
                         current_page=page,
                         per_page=per_page)

@facilities_bp.route('/facilities/search', methods=["GET"])
@with_supabase_auth
def search_facilities():
    supabase = get_supabase_client()
    search_term = request.args.get('search', '')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 25))
    status = request.args.get('status', 'all')

    offset = (page - 1) * per_page

    # Build base query
    query = supabase.table("facilities").select("*", count="exact")

    # Apply filters FIRST
    if search_term:
        query = query.ilike("name", f"%{search_term}%")
    if status == "active":
        query = query.eq("active_status", "true")
    elif status == "inactive":
        query = query.eq("active_status", "false")

    # THEN apply ordering
    query = query.order("name")


    # Finally paginate
    query = query.range(offset, offset + per_page - 1)

    # Execute and return
    result = query.execute()

    return jsonify({
        "facilities": result.data,
        "total_count": result.count,
        "current_page": page,
        "per_page": per_page
    })


@facilities_bp.route('/facilities/<string:facility_id>')
@with_supabase_auth
def facility_profile(facility_id):
    supabase = get_supabase_client()
    # Get facility info
    fac = supabase.table("facilities").select("*").eq("id", facility_id).single().execute().data

    # Get doctor assignments
    assignment_res = supabase.table("doctor_facility_assignments") \
        .select("*, radiologists(*)") \
        .eq("facility_id", facility_id).execute()

    assigned_radiologist_ids = {a["radiologist_id"] for a in assignment_res.data}
 
     # Get all radiologists
    all_rads_res = supabase.table("radiologists").select("id, name").order("name").execute()
    all_radiologists = all_rads_res.data or []
    available_radiologists = [r for r in all_radiologists if r["id"] not in assigned_radiologist_ids]
    # Get facility contacts
    contacts_res = supabase.table("facility_contact_assignments") \
        .select("*") \
        .eq("facility_id", facility_id) \
        .order("role") \
        .execute()
    
    return render_template("facility_profile.html",
        facility=fac,
        doctor_assignments=assignment_res.data,
        facility_contacts=contacts_res.data,
        available_radiologists=available_radiologists
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
    
    supabase.table("facility_contact_assignments").insert(data).execute()
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
    
    supabase.table("facility_contact_assignments").update(data).eq("id", contact_id).execute()
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

        # Proceed with deletion
        result = supabase.table("facility_contact_assignments")\
            .delete()\
            .eq("id", contact_id)\
            .eq("facility_id", facility_id)\
            .execute()
            
 
        
        if result.data:
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": "Delete operation failed"}), 500
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    
@facilities_bp.route('/facilities/add', methods=['POST'])
@with_supabase_auth
@admin_required
def add_facility():
    supabase = get_supabase_client()
    data = request.get_json()
    
    # Generate a new UUID for the facility
    new_id = str(uuid.uuid4())
    
    # Add the ID to the data
    data['id'] = new_id
    
    # Insert the new facility into the database
    supabase.table("facilities").insert(data).execute()
    
    return jsonify({"status": "success", "id": new_id})

@facilities_bp.route('/facilities/<facility_id>/bulk_update_assignments', methods=['POST'])
@with_supabase_auth
@admin_required
def bulk_update_assignments(facility_id):
    supabase = get_supabase_client()
    assignment_ids = request.form.getlist('assignment_ids')

    for assignment_id in assignment_ids:
        # Update assignment's can_read status
        can_read = request.form.get(f'can_read_{assignment_id}', 'true')
        supabase.table('doctor_facility_assignments').update({
            'can_read': can_read
        }).eq('id', assignment_id).execute()

        # Get corresponding radiologist ID from the assignment
        assignment = supabase.table('doctor_facility_assignments') \
            .select('radiologist_id') \
            .eq('id', assignment_id) \
            .single() \
            .execute()

        rad_id = assignment.data['radiologist_id']

        # Update fields on the radiologists table
        reads_stats = 'reads_stats_' + rad_id in request.form
        reads_routines = 'reads_routines_' + rad_id in request.form
        stipulations = request.form.get(f'stipulations_{rad_id}', '')

        supabase.table('radiologists').update({
            'reads_stats': 'YES' if reads_stats else 'NO',
            'reads_routines': 'YES' if reads_routines else 'NO',
            'stipulations': stipulations
        }).eq('id', rad_id).execute()

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
    supabase.table("doctor_facility_assignments").insert(data).execute()
    return redirect(url_for("facilities.facility_profile", facility_id=facility_id))


@facilities_bp.route('/facilities/<facility_id>/remove', methods=['POST'])
@with_supabase_auth
@admin_required
def remove_facility(facility_id):
    supabase = get_supabase_client()
    supabase.table('facilities').delete().eq('id', facility_id).execute()
    return redirect(url_for('facilities.facilities'))

@facilities_bp.route('/radmapping/facility/<facility_id>/update', methods=['POST'])
@with_supabase_auth
@admin_required
def update_facility(facility_id):
    supabase = get_supabase_client()
    form = request.form
    supabase.table('facilities').update({
        'name': form.get('name'),
        'location': form.get('location'),
        'pacs': form.get('pacs'),
        'tat_definition': form.get('tat_definition'),
        'modalities_assignment_period': form.get('assignment_period'),
        'modalities': form.get('assignment_type'),
        'active_status': 'true' if form.get('active_status') == 'true' else 'false',
    }).eq('id', facility_id).execute()
    return redirect(url_for('facilities.facility_profile', facility_id=facility_id))

@facilities_bp.route('/facilities/<string:facility_id>/assignments/<string:assignment_id>/remove', methods=['POST'])
@with_supabase_auth
@admin_required
def remove_assignment(facility_id, assignment_id):
    supabase = get_supabase_client()
    # Delete the assignment
    supabase.table("doctor_facility_assignments").delete().eq("id", assignment_id).execute()
    return redirect(url_for("facilities.facility_profile", facility_id=facility_id))