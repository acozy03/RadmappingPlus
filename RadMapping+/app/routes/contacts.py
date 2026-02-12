from flask import Blueprint, render_template, session, redirect, url_for, request
from app.admin_required import admin_required
from app.supabase_client import get_supabase_client
from app.middleware import with_supabase_auth
from datetime import datetime
import uuid
import logging
from app.audit_log import log_audit_action

contacts_bp = Blueprint('contacts', __name__)


@contacts_bp.route('/contacts')
@with_supabase_auth
def contacts():
    try:
        supabase = get_supabase_client()
 
        result = supabase.table("vesta_contacts").select("*").execute()
        
        if hasattr(result, 'error'):
     
            return render_template("contacts.html", contacts=[], departments=[], error="Error fetching contacts")
        
        departments = sorted(set(contact['department'] for contact in result.data))
            
        return render_template("contacts.html", contacts=result.data, departments=departments)
    except Exception as e:
        logging.error(f"Exception in contacts route: {str(e)}")
        return render_template("contacts.html", contacts=[], departments=[], error=str(e))

@contacts_bp.route('/contacts/add', methods=['POST'])
@with_supabase_auth
@admin_required
def add_contact():
    try:
        supabase = get_supabase_client()
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
        result = supabase.table("vesta_contacts").insert(data).execute()
        if not hasattr(result, 'error'):
            log_audit_action(
                supabase=supabase,
                action="insert",
                table_name="vesta_contacts",
                record_id=data["id"],
                user_email=session.get("user", {}).get("email", "unknown"),
                old_data=None,
                new_data=data
            )

        if hasattr(result, 'error'):
            
            return redirect(url_for("contacts.contacts"))
        return redirect(url_for("contacts.contacts"))
    except Exception:
       
        return redirect(url_for("contacts.contacts"))

@contacts_bp.route('/contacts/<string:contact_id>/edit', methods=['POST'])
@with_supabase_auth
@admin_required
def edit_contact(contact_id):
    try:
        supabase = get_supabase_client()
        data = {
            "name": request.form.get("name"),
            "department": request.form.get("department"),
            "contact_number": request.form.get("contact_number"),
            "extension_number": request.form.get("extension_number"),
            "email": request.form.get("email"),
            "additional_info": request.form.get("additional_info"),
            "updated_at": datetime.now().isoformat()
        }
        old_data = supabase.table("vesta_contacts").select("*").eq("id", contact_id).single().execute().data

        result = supabase.table("vesta_contacts").update(data).eq("id", contact_id).execute()
        if not hasattr(result, 'error'):
            log_audit_action(
                supabase=supabase,
                action="update",
                table_name="vesta_contacts",
                record_id=contact_id,
                user_email=session.get("user", {}).get("email", "unknown"),
                old_data=old_data,
                new_data=data
            )

        if hasattr(result, 'error'):
            logging.error(f"Error editing contact: {result.error}")
        return redirect(url_for("contacts.contacts"))
    except Exception as e:
        logging.error(f"Exception in edit_contact: {str(e)}")
        return redirect(url_for("contacts.contacts"))

@contacts_bp.route('/contacts/<string:contact_id>/delete', methods=['POST'])
@with_supabase_auth
@admin_required
def delete_contact(contact_id):
    try:
        supabase = get_supabase_client()
        old_data = supabase.table("vesta_contacts").select("*").eq("id", contact_id).single().execute().data
        result = supabase.table("vesta_contacts").delete().eq("id", contact_id).execute()
        
        if not hasattr(result, 'error'):
            log_audit_action(
                supabase=supabase,
                action="delete",
                table_name="vesta_contacts",
                record_id=contact_id,
                user_email=session.get("user", {}).get("email", "unknown"),
                old_data=old_data,
                new_data=None
            )
        if hasattr(result, 'error'):
            logging.error(f"Error deleting contact: {result.error}")
        return redirect(url_for("contacts.contacts"))
    except Exception as e:
        logging.error(f"Exception in delete_contact: {str(e)}")
        return redirect(url_for("contacts.contacts"))