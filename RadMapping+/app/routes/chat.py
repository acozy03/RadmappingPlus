from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from app.admin_required import admin_required
from app.supabase_client import supabase
from datetime import datetime
import uuid
import ollama
chat_bp = Blueprint('chat', __name__)

def login_required(view_func):
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("auth.login"))
        return view_func(*args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper

@chat_bp.route('/chat', methods=['POST'])
@login_required
def chat():
    data = request.get_json()
    question = data.get('question', '')
    
    # Create schema description with accurate table information
    schema = """
    Tables in the database:
    1. vesta_contacts (
        id uuid,
        name text,
        department text,
        contact_number text,
        backup_number text,
        email text,
        additional_info text,
        created_at timestamptz,
        updated_at timestamptz
    )
    
    2. radiologists (
        id uuid,
        name text,
        pacs text,
        primary_contact_method text,
        phone text,
        email text,
        active_status bool,
        schedule_info_est text,
        additional_info text,
        credentialing_contact text,
        rad_guidelines text,
        modalities text,
        timezone text,
        reads_routines bool
    )
    
    3. certifications (
        id uuid,
        radiologist_id uuid REFERENCES radiologists(id),
        state text,
        expiration_date date,
        status text,
        specialty text,
        tags text
    )
    
    4. monthly_schedule (
        id uuid,
        radiologist_id uuid REFERENCES radiologists(id),
        date date,
        start_time time,
        end_time time,
        schedule_details text,
        notes text
    )
    
    5. specialty_studies (
        id uuid,
        name text,
        description text
    )
    
    6. specialty_permissions (
        id uuid,
        radiologist_id uuid REFERENCES radiologists(id),
        specialty_id uuid REFERENCES specialty_studies(id),
        can_read bool
    )
    
    7. facilities (
        id uuid,
        name text,
        pacs text,
        location text,
        modalities_assignment_period text,
        tat_definition text,
        active_status text
    )
    
    8. doctor_facility_assignments (
        id uuid,
        radiologist_id uuid REFERENCES radiologists(id),
        facility_id uuid REFERENCES facilities(id),
        can_read bool,
        stipulations text,
        does_stats bool,
        does_routines bool,
        notes text
    )
    
    9. facility_contact_assignments (
        id uuid,
        facility_id uuid REFERENCES facilities(id),
        contact_name text,
        email text,
        phone text,
        comments text,
        role text
    )
    
    10. vacations (
        id uuid,
        radiologist_id uuid REFERENCES radiologists(id),
        start_date date,
        end_date date,
        comments text
    )
    """
    
    # Format the schema as a string
    schema_str = f"Here is the database schema:\n{schema}"
    
    # Build the prompt
    prompt = f"""You are a helpful assistant for a medical radiology management system. 
    Use the following schema to answer questions about the database:
    
    {schema_str}
    
    Question: {question}
    
    If the question requires querying the database, respond with a SQL query that can be executed.
    The SQL query should:
    1. Use proper table names and column names exactly as shown in the schema
    2. Include necessary JOINs when querying related tables using the correct foreign key relationships
    3. Use proper PostgreSQL syntax and formatting
    4. Be wrapped in ```sql``` code blocks
    5. Consider data types (uuid, text, date, time, bool, timestamptz) when writing conditions
    6. DO NOT include semicolons at the end of queries
    
    If the question is about the schema or general information, provide a helpful response.
    """
    
    # Get response from Ollama
    response = ollama.chat(model='mistral', messages=[
        {
            'role': 'user',
            'content': prompt
        }
    ])
    
    # Extract the response text
    response_text = response['message']['content']
    
    # Check if the response contains a SQL query
    if '```sql' in response_text:
        try:
            # Extract the SQL query from the response and remove semicolon if present
            sql_query = response_text.split('```sql')[1].split('```')[0].strip()
            sql_query = sql_query.rstrip(';')  # Remove trailing semicolon if present
            
            # Log the query for debugging
            print(f"Executing SQL query: {sql_query}")
            
            # Execute the query using the execute_sql function
            result = supabase.rpc('execute_sql', {'query': sql_query}).execute()
            
            # Return both the explanation and the query results
            return jsonify({
                'explanation': response_text,
                'results': result.data
            })
        except Exception as e:
            print(f"Error executing query: {str(e)}")
            return jsonify({
                'error': f'Error executing query: {str(e)}',
                'explanation': response_text,
                'query': sql_query if 'sql_query' in locals() else None
            }), 500
    
    return jsonify({'response': response_text})
