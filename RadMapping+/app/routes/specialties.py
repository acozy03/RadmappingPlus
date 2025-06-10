from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from app.admin_required import admin_required
from app.supabase_client import supabase
import uuid
from app.middleware import with_supabase_auth
from app.supabase_client import get_supabase_client
specialties_bp = Blueprint('specialties', __name__)


@specialties_bp.route('/specialties')
@with_supabase_auth
def specialties():
    supabase = get_supabase_client()
    user_email = session["user"]["email"]
    pinned_res = supabase.table("pinned_doctors") \
        .select("doctor_id") \
        .eq("user_id", user_email) \
        .execute()
    pinned_doctor_ids = [p["doctor_id"] for p in pinned_res.data]

    # Get all specialties with their descriptions
    specialties_res = supabase.table("specialty_studies").select("*").order("name").execute()
    specialties = specialties_res.data

    # Strip newlines from the 'name' field
    for specialty in specialties:
        if 'name' in specialty and isinstance(specialty['name'], str):
            specialty['name'] = specialty['name'].replace('\n', ' ').replace('\r', ' ').strip()


    # Get all doctors
    doctors_res = supabase.table("radiologists").select("*").order("name").execute()
    doctors = doctors_res.data

    # Get all specialty permissions
    permissions_res = supabase.table("specialty_permissions") \
        .select("*, radiologists(id, name), specialty_studies(id, name)") \
        .execute()
    permissions = permissions_res.data

    # Create a mapping for easy lookup of permissions
    permission_map = {}
    for perm in permissions:
        rad_id = perm["radiologist_id"]
        spec_id = perm["specialty_id"]
        if rad_id not in permission_map:
            permission_map[rad_id] = {}
        permission_map[rad_id][spec_id] = perm["can_read"]

    # Search logic
    search = request.args.get('search', '').strip().lower()
    if search:
        filtered_doctors = [doc for doc in doctors if search in doc['name'].lower()]
        sorted_doctors = sorted(filtered_doctors, key=lambda doc: str(doc['id']) not in pinned_doctor_ids)
        visible_doctors = sorted_doctors  # Show all matches, no pagination
        page = 1
        total_pages = 1
    else:
        # Assuming `doctors` is a list of dicts and already sorted with pinned first
        sorted_doctors = sorted(doctors, key=lambda doc: str(doc['id']) not in pinned_doctor_ids)
        page = int(request.args.get('page', 1))
        page_size = 15
        total_doctors = len(sorted_doctors)
        start = (page - 1) * page_size
        end = start + page_size
        visible_doctors = sorted_doctors[start:end]
        total_pages = (total_doctors + page_size - 1) // page_size

    return render_template("specialties.html",
                           doctors=visible_doctors,
                           specialties=specialties,
                           permission_map=permission_map,
                           pinned_doctors=pinned_doctor_ids,
                           page=page,
                           total_pages=total_pages)


@specialties_bp.route('/specialties/add', methods=['POST'])
@with_supabase_auth
@admin_required
def add_specialty():
    supabase = get_supabase_client()
    data = {
        "id": str(uuid.uuid4()),
        "name": request.form.get("name"),
        "description": request.form.get("description")
    }
    supabase.table("specialty_studies").insert(data).execute()
    return redirect(url_for("specialties.specialties"))

@specialties_bp.route('/specialties/<string:specialty_id>/delete', methods=['POST'])
@with_supabase_auth
@admin_required
def delete_specialty(specialty_id):
    supabase = get_supabase_client()
    # First delete all permissions for this specialty
    supabase.table("specialty_permissions").delete().eq("specialty_id", specialty_id).execute()
    # Then delete the specialty itself
    supabase.table("specialty_studies").delete().eq("id", specialty_id).execute()
    return redirect(url_for("specialties.specialties"))

@specialties_bp.route('/specialties/<string:specialty_id>/doctors')
@with_supabase_auth
def doctors_for_specialty(specialty_id):
    supabase = get_supabase_client()
    # Get all permissions for this specialty where can_read is True
    permissions_res = supabase.table("specialty_permissions") \
        .select("*, radiologists(id, name, email, active_status)") \
        .eq("specialty_id", specialty_id) \
        .eq("can_read", True) \
        .execute()
    doctors = [perm["radiologists"] for perm in permissions_res.data if perm.get("radiologists")]
    return jsonify(doctors)

@specialties_bp.route('/specialties/permissions/update', methods=['POST'])
@with_supabase_auth
@admin_required
def update_specialty_permission():
    supabase = get_supabase_client()
    radiologist_id = request.form.get("radiologist_id")
    specialty_id = request.form.get("specialty_id")
    can_read = request.form.get("can_read") == "true"
    
    # Check if permission already exists
    existing = supabase.table("specialty_permissions") \
        .select("id") \
        .eq("radiologist_id", radiologist_id) \
        .eq("specialty_id", specialty_id) \
        .execute()

    if existing.data:
        # Update existing permission
        supabase.table("specialty_permissions").update({
            "can_read": can_read
        }).eq("id", existing.data[0]["id"]).execute()
    else:
        # Create new permission
        supabase.table("specialty_permissions").insert({
            "id": str(uuid.uuid4()),
            "radiologist_id": radiologist_id,
            "specialty_id": specialty_id,
            "can_read": can_read
        }).execute()

    return jsonify({"status": "success"})

@specialties_bp.route('/specialties/search', methods=["GET"])
@with_supabase_auth
def search_specialties_doctors():
    supabase = get_supabase_client()
    user_email = session["user"]["email"]
    pinned_res = supabase.table("pinned_doctors") \
        .select("doctor_id") \
        .eq("user_id", user_email) \
        .execute()
    pinned_doctor_ids = [p["doctor_id"] for p in pinned_res.data]

    # Get all specialties with their descriptions
    specialties_res = supabase.table("specialty_studies").select("*").order("name").execute()
    specialties = specialties_res.data

    # Get all doctors
    doctors_res = supabase.table("radiologists").select("*").order("name").execute()
    doctors = doctors_res.data

    # Get all specialty permissions
    permissions_res = supabase.table("specialty_permissions") \
        .select("*, radiologists(id, name), specialty_studies(id, name)") \
        .execute()
    permissions = permissions_res.data

    # Create a mapping for easy lookup of permissions
    permission_map = {}
    for perm in permissions:
        rad_id = perm["radiologist_id"]
        spec_id = perm["specialty_id"]
        if rad_id not in permission_map:
            permission_map[rad_id] = {}
        permission_map[rad_id][spec_id] = perm["can_read"]

    # Search logic
    search = request.args.get('search', '').strip().lower()
    if search:
        filtered_doctors = [doc for doc in doctors if search in doc['name'].lower()]
        sorted_doctors = sorted(filtered_doctors, key=lambda doc: str(doc['id']) not in pinned_doctor_ids)
        visible_doctors = sorted_doctors  # Show all matches, no pagination
    else:
        sorted_doctors = sorted(doctors, key=lambda doc: str(doc['id']) not in pinned_doctor_ids)
        visible_doctors = sorted_doctors

    return jsonify({
        'doctors': visible_doctors,
        'specialties': specialties,
        'permission_map': permission_map,
        'pinned_doctors': pinned_doctor_ids
    })


@specialties_bp.route('/specialties/<string:specialty_id>/doctors/all')
@with_supabase_auth
@admin_required
def get_all_specialty_doctors(specialty_id):
    supabase = get_supabase_client()
    # Get all doctors
    doctors_res = supabase.table("radiologists").select("*").order("name").execute()
    doctors = doctors_res.data
    # Get all permissions for this specialty
    perms_res = supabase.table("specialty_permissions") \
        .select("radiologist_id, can_read") \
        .eq("specialty_id", specialty_id) \
        .execute()
    perms = {p['radiologist_id']: p['can_read'] for p in perms_res.data}
    # Build response
    result = []
    for doc in doctors:
        result.append({
            'id': doc['id'],
            'name': doc['name'],
            'email': doc.get('email', ''),
            'assigned': perms.get(doc['id'], False)
        })
    return jsonify({'doctors': result})

@specialties_bp.route('/specialties/<string:specialty_id>/doctors/update', methods=['POST'])
@with_supabase_auth
@admin_required
def update_specialty_doctors(specialty_id):
    supabase = get_supabase_client()
    data = request.get_json()
    doctor_ids = set(data.get('doctor_ids', []))
    # Get all doctors
    doctors_res = supabase.table("radiologists").select("id").execute()
    all_doctor_ids = {d['id'] for d in doctors_res.data}
    # Get current permissions
    perms_res = supabase.table("specialty_permissions") \
        .select("id, radiologist_id") \
        .eq("specialty_id", specialty_id) \
        .execute()
    perms = {p['radiologist_id']: p['id'] for p in perms_res.data}
    # Update or create permissions
    for doc_id in all_doctor_ids:
        should_have = doc_id in doctor_ids
        if doc_id in perms:
            supabase.table("specialty_permissions").update({"can_read": should_have}).eq("id", perms[doc_id]).execute()
        elif should_have:
            supabase.table("specialty_permissions").insert({
                "id": str(uuid.uuid4()),
                "radiologist_id": doc_id,
                "specialty_id": specialty_id,
                "can_read": True
            }).execute()
    return jsonify({"status": "success"})