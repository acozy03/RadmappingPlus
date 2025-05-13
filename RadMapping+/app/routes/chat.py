from flask import Blueprint, json, render_template, session, redirect, url_for, request, jsonify
from app.admin_required import admin_required
from app.supabase_client import supabase
from datetime import datetime
import uuid
import openai
from openai import OpenAI
import pandas as pd
import os
from app.supabase_client import get_supabase_client
from app.middleware import with_supabase_auth
chat_bp = Blueprint('chat', __name__)


def format_results_to_english(results):
    if not results:
        return "I couldn't find any matching records."

    # Unwrap first-level JSON arrays if present
    if isinstance(results, list) and len(results) == 1 and isinstance(results[0], dict):
        only_value = list(results[0].values())[0]
        if isinstance(only_value, list):
            results = only_value

    df = pd.DataFrame(results)
    num_results = len(df)

    summary = f"I found {num_results} result{'s' if num_results != 1 else ''}:\n"

    for idx, row in df.iterrows():
        summary += "\n"
        for column in df.columns:
            value = row[column]
            if not isinstance(value, (list, dict)) and pd.notna(value):
                summary += f"{column.replace('_', ' ').title()}: {value}\n"
            elif isinstance(value, (list, dict)):
                summary += f"{column.replace('_', ' ').title()}: {json.dumps(value)}\n"


    return summary


@chat_bp.route('/chat', methods=['POST'])
@with_supabase_auth
def chat():
    supabase = get_supabase_client()
    data = request.get_json()
    question = data.get('question', '')
    
    # Create schema description with accurate table information
    schema = """
    Tables in the database:
    1. rad_avg_monthly_rvu (
        radiologist_id uuid,
        jan float8,
        feb float8,
        mar float8,
        apr float8,
        may float8,
        jun float8,
        jul float8,
        aug float8,
        sep float8,
        oct float8,
        nov float8,
        dec float8
    )

    2. vesta_contacts (
        id uuid,
        name text,
        department text,
        contact_number text,
        extension_number text,
        email text,
        additional_info text,
        created_at timestamptz,
        updated_at timestamptz
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
        start_time time,
        end_time time,
        schedule_details text,
        start_date date,
        end_date date,
        break_start time,
        break_end time
    )

    5. users (
        id uuid,
        email text,
        password text,
        role text
    )

    6. radiologists (
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

    7. capacity_per_hour (
        date date,
        hour int4,
        total_rvus float8
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

    9. specialty_permissions (
        id uuid,
        radiologist_id uuid REFERENCES radiologists(id),
        specialty_id uuid REFERENCES specialty_studies(id),
        can_read bool
    )

    10. specialty_studies (
        id uuid,
        name text,
        description text
    )

    11. vacations (
        id uuid,
        radiologist_id uuid REFERENCES radiologists(id),
        start_date date,
        end_date date,
        comments text
    )

    12. facilities (
        id uuid,
        name text,
        pacs text,
        location text,
        modalities_assignment_period text,
        tat_definition text,
        active_status text,
        modalities text
    )

    13. facility_contact_assignments (
        id uuid,
        facility_id uuid REFERENCES facilities(id),
        contact_name text,
        email text,
        phone text,
        comments text,
        role text
    )

    14. pinned_doctors (
        id uuid,
        user_id uuid REFERENCES users(id),
        doctor_id uuid REFERENCES radiologists(id),
        created_at timestamptz
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
    
    try:
        client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            organization=os.getenv("OPENAI_ORG_ID")  # Make sure this is set correctly
        )
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant for a medical radiology management system."},
                {"role": "user", "content": prompt}
            ]
        )
        response_text = response.choices[0].message.content


        
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
                if result.data is None:
                    return jsonify({
                        'error': 'Query executed but returned no data.',
                        'response': response_text
                    }), 404
    
                # Format the results in plain English
                english_results = format_results_to_english(result.data)
                
                # Return both the SQL query and the natural language response
                return jsonify({
                    'response': english_results,
                    'results': result.data
                })

            except Exception as e:
                print(f"Error executing query: {str(e)}")
                return jsonify({
                    'error': f'I encountered an error while trying to find the information: {str(e)}',
                    'response': response_text
                }), 500
        
        return jsonify({'response': response_text})
        
    except Exception as e:
        print(f"Error with OpenAI API: {str(e)}")
        return jsonify({
            'error': f'I encountered an error while processing your request: {str(e)}'
        }), 500
