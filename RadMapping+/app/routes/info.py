from flask import Blueprint, render_template, session, redirect, url_for, request
from app.admin_required import admin_required
from app.supabase_client import get_supabase_client
from datetime import datetime
import uuid
from app.middleware import with_supabase_auth
from app.audit_log import log_audit_action
import random

info_bp = Blueprint('info', __name__)

@info_bp.route('/info')
@with_supabase_auth
def info():
    supabase = get_supabase_client()
    articles_res = supabase.table("info_articles").select("*").order("title").execute()
    articles = articles_res.data or []

    # Define the static lists of available themes and icons for the forms
    available_themes = [
        "purple-blue",
        "orange-red",
        "green-emerald",
        "indigo-purple",
        "teal-cyan",
        "pink-rose",
        "amber-yellow",
        "red-pink",
    ]
    
    available_icons = [
        "fas fa-calendar-alt",
        "fas fa-comments",
        "fas fa-clock",
        "fas fa-moon",
        "fas fa-phone",
        "fas fa-file-alt",
        "fas fa-clipboard-check",
        "fas fa-exclamation-triangle",
        "fas fa-info-circle",
        "fas fa-heartbeat",
        "fas fa-hospital",
        "fas fa-user-md",
        "fas fa-tags",
    ]

    # Assign a random theme and icon if none are stored in the database
    for article in articles:
        article['theme'] = article.get('theme', random.choice(available_themes))
        article['icon'] = article.get('icon', random.choice(available_icons))
    
    return render_template("info.html", articles=articles, available_themes=available_themes, available_icons=available_icons)

@info_bp.route('/info/add', methods=['POST'])
@with_supabase_auth
@admin_required
def add_article():
    supabase = get_supabase_client()
    data = {
        "id": str(uuid.uuid4()),
        "title": request.form.get("title"),
        "content": request.form.get("content"),
        "category": request.form.get("category"),
        "theme": request.form.get("theme"),
        "icon": request.form.get("icon"),
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    res = supabase.table("info_articles").insert(data).execute()
    if not hasattr(res, 'error'):
        log_audit_action(
            supabase=supabase,
            action="insert",
            table_name="info_articles",
            record_id=data["id"],
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=None,
            new_data=data
        )
    return redirect(url_for("info.info"))

@info_bp.route('/info/<string:article_id>/edit', methods=['POST'])
@with_supabase_auth
@admin_required
def edit_article(article_id):
    supabase = get_supabase_client()
    data = {
        "title": request.form.get("title"),
        "content": request.form.get("content"),
        "category": request.form.get("category"),
        "theme": request.form.get("theme"),
        "icon": request.form.get("icon"),
        "updated_at": datetime.now().isoformat()
    }
    old_data = supabase.table("info_articles").select("*").eq("id", article_id).single().execute().data
    res = supabase.table("info_articles").update(data).eq("id", article_id).execute()
    if not hasattr(res, 'error'):
        log_audit_action(
            supabase=supabase,
            action="update",
            table_name="info_articles",
            record_id=article_id,
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=old_data,
            new_data=data
        )
    return redirect(url_for("info.info"))

@info_bp.route('/info/<string:article_id>/delete', methods=['POST'])
@with_supabase_auth
@admin_required
def delete_article(article_id):
    supabase = get_supabase_client()
    old_data = supabase.table("info_articles").select("*").eq("id", article_id).single().execute().data
    res = supabase.table("info_articles").delete().eq("id", article_id).execute()
    if not hasattr(res, 'error'):
        log_audit_action(
            supabase=supabase,
            action="delete",
            table_name="info_articles",
            record_id=article_id,
            user_email=session.get("user", {}).get("email", "unknown"),
            old_data=old_data,
            new_data=None
        )
    return redirect(url_for("info.info"))