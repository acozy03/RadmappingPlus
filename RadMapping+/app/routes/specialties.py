from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from app.admin_required import admin_required
from app.supabase_client import get_supabase_client
from app.middleware import with_supabase_auth
from app.audit_log import log_audit_action
import uuid

specialties_bp = Blueprint('specialties', __name__)


def _normalize_specialty_flags(specialties):
    for specialty in specialties:
        if 'name' in specialty and isinstance(specialty['name'], str):
            specialty['name'] = specialty['name'].replace('\n', ' ').replace('\r', ' ').strip()
        specialty['is_specialty'] = bool(specialty.get('is_specialty'))
    return specialties


@specialties_bp.route('/specialties')
@with_supabase_auth
def specialties():
    supabase = get_supabase_client()
    user_email = session["user"]["email"]
    pinned_res = supabase.table("pinned_doctors").select("doctor_id").eq("user_id", user_email).execute()
    pinned_doctor_ids = [p["doctor_id"] for p in pinned_res.data]

    specialties_res = supabase.table("specialty_studies").select("*").order("name").execute()
    specialties = _normalize_specialty_flags(specialties_res.data)

    doctors_res = supabase.table("radiologists").select("*").order("name").execute()
    doctors = doctors_res.data

    permissions_res = supabase.table("specialty_permissions") \
        .select("*, radiologists(id, name), specialty_studies(id, name)") \
        .execute()
    permissions = permissions_res.data

    permission_map = {}
    for perm in permissions:
        rad_id = perm["radiologist_id"]
        spec_id = perm["specialty_id"]
        if rad_id not in permission_map:
            permission_map[rad_id] = {}
        permission_map[rad_id][spec_id] = perm["can_read"]

    search = request.args.get('search', '').strip().lower()
    if search:
        filtered_doctors = [doc for doc in doctors if search in doc['name'].lower()]
        sorted_doctors = sorted(filtered_doctors, key=lambda doc: str(doc['id']) not in pinned_doctor_ids)
        visible_doctors = sorted_doctors
        page, total_pages = 1, 1
    else:
        sorted_doctors = sorted(doctors, key=lambda doc: str(doc['id']) not in pinned_doctor_ids)
        page = int(request.args.get('page', 1))
        page_size = 15
        start = (page - 1) * page_size
        end = start + page_size
        visible_doctors = sorted_doctors[start:end]
        total_pages = (len(sorted_doctors) + page_size - 1) // page_size

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
        "description": request.form.get("description"),
        "is_specialty": request.form.get("is_specialty") == "on"
    }
    res = supabase.table("specialty_studies").insert(data).execute()
    if not hasattr(res, "error"):
        log_audit_action(
            supabase=supabase,
            action="insert",
            table_name="specialty_studies",
            record_id=data["id"],
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=None,
            new_data=data
        )
    return redirect(url_for("specialties.specialties"))


@specialties_bp.route('/specialties/<string:specialty_id>/delete', methods=['POST'])
@with_supabase_auth
@admin_required
def delete_specialty(specialty_id):
    supabase = get_supabase_client()
    old_data = supabase.table("specialty_studies").select("*").eq("id", specialty_id).single().execute().data
    supabase.table("specialty_permissions").delete().eq("specialty_id", specialty_id).execute()
    res = supabase.table("specialty_studies").delete().eq("id", specialty_id).execute()
    if not hasattr(res, "error"):
        log_audit_action(
            supabase=supabase,
            action="delete",
            table_name="specialty_studies",
            record_id=specialty_id,
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=old_data,
            new_data=None
        )
    return redirect(url_for("specialties.specialties"))


@specialties_bp.route('/specialties/<string:specialty_id>/update', methods=['POST'])
@with_supabase_auth
@admin_required
def update_specialty(specialty_id):
    supabase = get_supabase_client()
    payload = request.get_json(silent=True) or {}

    name = (payload.get("name") or "").strip()
    if not name:
        return jsonify({"status": "error", "message": "Specialty name is required."}), 400

    update_data = {
        "name": name,
        "description": (payload.get("description") or "").strip() or None,
        "is_specialty": bool(payload.get("is_specialty"))
    }

    old_data = supabase.table("specialty_studies").select("*").eq("id", specialty_id).single().execute().data
    res = supabase.table("specialty_studies").update(update_data).eq("id", specialty_id).execute()

    if hasattr(res, "error") and res.error:
        return jsonify({"status": "error", "message": "Failed to update specialty."}), 500

    log_audit_action(
        supabase=supabase,
        action="update",
        table_name="specialty_studies",
        record_id=specialty_id,
        user_email=session.get("user", {}).get("email", "unknown"),
        old_data=old_data,
        new_data=update_data
    )

    return jsonify({"status": "success"})


@specialties_bp.route('/specialties/<string:specialty_id>/doctors')
@with_supabase_auth
def doctors_for_specialty(specialty_id):
    supabase = get_supabase_client()
    permissions_res = supabase.table("specialty_permissions") \
        .select("*, radiologists(id, name, email, active_status)") \
        .eq("specialty_id", specialty_id).eq("can_read", True).execute()
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

    existing = supabase.table("specialty_permissions") \
        .select("id, can_read") \
        .eq("radiologist_id", radiologist_id) \
        .eq("specialty_id", specialty_id) \
        .execute()

    if existing.data:
        perm_id = existing.data[0]["id"]
        old_can_read = existing.data[0]["can_read"]
        res = supabase.table("specialty_permissions").update({"can_read": can_read}).eq("id", perm_id).execute()
        if not hasattr(res, "error"):
            log_audit_action(
                supabase=supabase,
                action="update",
                table_name="specialty_permissions",
                record_id=perm_id,
                user_email=session.get("user", {}).get("email", "unknown"),
                old_data={"can_read": old_can_read},
                new_data={"can_read": can_read}
            )
    else:
        new_id = str(uuid.uuid4())
        new_perm = {
            "id": new_id,
            "radiologist_id": radiologist_id,
            "specialty_id": specialty_id,
            "can_read": can_read
        }
        res = supabase.table("specialty_permissions").insert(new_perm).execute()
        if not hasattr(res, "error"):
            log_audit_action(
                supabase=supabase,
                action="insert",
                table_name="specialty_permissions",
                record_id=new_id,
                user_email=session.get("user", {}).get("email", "unknown"),
                old_data=None,
                new_data=new_perm
            )

    return jsonify({"status": "success"})


@specialties_bp.route('/specialties/<string:specialty_id>/doctors/all')
@with_supabase_auth
@admin_required
def get_all_specialty_doctors(specialty_id):
    supabase = get_supabase_client()
    doctors_res = supabase.table("radiologists").select("*").order("name").execute()
    doctors = doctors_res.data
    perms_res = supabase.table("specialty_permissions") \
        .select("radiologist_id, can_read") \
        .eq("specialty_id", specialty_id).execute()
    perms = {p['radiologist_id']: p['can_read'] for p in perms_res.data}
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

    doctors_res = supabase.table("radiologists").select("id").execute()
    all_doctor_ids = {d['id'] for d in doctors_res.data}

    perms_res = supabase.table("specialty_permissions") \
        .select("id, radiologist_id, can_read") \
        .eq("specialty_id", specialty_id).execute()
    perms = {p['radiologist_id']: {"id": p["id"], "can_read": p["can_read"]} for p in perms_res.data}

    for doc_id in all_doctor_ids:
        should_have = doc_id in doctor_ids
        existing = perms.get(doc_id)

        if existing:
            if existing["can_read"] != should_have:
                supabase.table("specialty_permissions").update(
                    {"can_read": should_have}
                ).eq("id", existing["id"]).execute()
                log_audit_action(
                    supabase=supabase,
                    action="update",
                    table_name="specialty_permissions",
                    record_id=existing["id"],
                    user_email=session.get("user", {}).get("email", "unknown"),
                    old_data={"can_read": existing["can_read"]},
                    new_data={"can_read": should_have}
                )
        elif should_have:
            new_id = str(uuid.uuid4())
            new_perm = {
                "id": new_id,
                "radiologist_id": doc_id,
                "specialty_id": specialty_id,
                "can_read": True
            }
            supabase.table("specialty_permissions").insert(new_perm).execute()
            log_audit_action(
                supabase=supabase,
                action="insert",
                table_name="specialty_permissions",
                record_id=new_id,
                user_email=session.get("user", {}).get("email", "unknown"),
                old_data=None,
                new_data=new_perm
            )

    return jsonify({"status": "success"})


@specialties_bp.route('/specialties/search', methods=["GET"])
@with_supabase_auth
def search_specialties_doctors():
    supabase = get_supabase_client()
    user_email = session["user"]["email"]
    pinned_res = supabase.table("pinned_doctors").select("doctor_id").eq("user_id", user_email).execute()
    pinned_doctor_ids = [p["doctor_id"] for p in pinned_res.data]

    specialties_res = supabase.table("specialty_studies").select("*").order("name").execute()
    specialties = _normalize_specialty_flags(specialties_res.data)

    doctors_res = supabase.table("radiologists").select("*").order("name").execute()
    doctors = doctors_res.data

    permissions_res = supabase.table("specialty_permissions") \
        .select("*, radiologists(id, name), specialty_studies(id, name)") \
        .execute()
    permissions = permissions_res.data

    permission_map = {}
    for perm in permissions:
        rad_id = perm["radiologist_id"]
        spec_id = perm["specialty_id"]
        if rad_id not in permission_map:
            permission_map[rad_id] = {}
        permission_map[rad_id][spec_id] = perm["can_read"]

    search = request.args.get('search', '').strip().lower()
    if search:
        filtered_doctors = [doc for doc in doctors if search in doc['name'].lower()]
        sorted_doctors = sorted(filtered_doctors, key=lambda doc: str(doc['id']) not in pinned_doctor_ids)
    else:
        sorted_doctors = sorted(doctors, key=lambda doc: str(doc['id']) not in pinned_doctor_ids)

    return jsonify({
        'doctors': sorted_doctors,
        'specialties': specialties,
        'permission_map': permission_map,
        'pinned_doctors': pinned_doctor_ids
    })
