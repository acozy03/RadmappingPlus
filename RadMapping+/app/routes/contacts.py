from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from app.admin_required import admin_required
from app.supabase_client import supabase
from datetime import datetime
import uuid

contacts_bp = Blueprint('contacts', __name__)

def login_required(view_func):
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("auth.login"))
        return view_func(*args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper

@contacts_bp.route('/contacts')
@login_required
def contacts():
    # Fetch contacts from the database
    response = supabase.table("vesta_contacts").select("*").order("department").execute()
    contacts = response.data

    # Get unique departments from contacts
    departments = sorted(set(contact["department"] for contact in contacts))
    
    return render_template("contacts.html", contacts=contacts, departments=departments)

@contacts_bp.route('/contacts/add', methods=['POST'])
@login_required
@admin_required
def add_contact():
    data = {
        "id": str(uuid.uuid4()),
        "name": request.form.get("name"),
        "department": request.form.get("department"),
        "contact_number": request.form.get("contact_number"),
        "extension_number": request.form.get("extension_number"),
        "email": request.form.get("email"),
        "additional_info": request.form.get("additional_info"),
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    supabase.table("vesta_contacts").insert(data).execute()
    return redirect(url_for("contacts.contacts"))

@contacts_bp.route('/contacts/<string:contact_id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_contact(contact_id):
    data = {
        "name": request.form.get("name"),
        "department": request.form.get("department"),
        "contact_number": request.form.get("contact_number"),
        "extension_number": request.form.get("extension_number"),
        "email": request.form.get("email"),
        "additional_info": request.form.get("additional_info"),
        "updated_at": datetime.now().isoformat()
    }
    supabase.table("vesta_contacts").update(data).eq("id", contact_id).execute()
    return redirect(url_for("contacts.contacts"))

@contacts_bp.route('/contacts/<string:contact_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_contact(contact_id):
    supabase.table("vesta_contacts").delete().eq("id", contact_id).execute()
    return redirect(url_for("contacts.contacts"))