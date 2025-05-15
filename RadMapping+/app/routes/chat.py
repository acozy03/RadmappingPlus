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
from llama_index.core import (
    VectorStoreIndex,
    SimpleDirectoryReader,
    Settings,
    StorageContext,
    load_index_from_storage,
)
from llama_index.llms.openai import OpenAI as LlamaOpenAI
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.core.memory import ChatMemoryBuffer
import json

chat_bp = Blueprint('chat', __name__)

def get_chat_memory():
    """Get or create chat memory for the current session."""
    if 'chat_memory' not in session:
        session['chat_memory'] = []
    return session['chat_memory']

def add_to_chat_memory(role, content):
    """Add a message to the chat memory."""
    memory = get_chat_memory()
    memory.append({"role": role, "content": content})
    # Keep only last 10 messages to prevent session from getting too large
    if len(memory) > 10:
        memory = memory[-10:]
    session['chat_memory'] = memory
    return memory

def format_chat_history():
    """Format chat history for the prompt."""
    memory = get_chat_memory()
    if not memory:
        return ""
    
    history = "Previous conversation:\n"
    for msg in memory:
        history += f"{msg['role']}: {msg['content']}\n"
    return history

# Initialize LlamaIndex components
def initialize_llama_index():
    # Create storage directory if it doesn't exist
    if not os.path.exists("index_store"):
        os.makedirs("index_store")
    
    # Check if we have a stored index
    if os.path.exists("index_store/index.json"):
        # Load existing index
        storage_context = StorageContext.from_defaults(persist_dir="index_store")
        index = load_index_from_storage(storage_context)
    else:
        # Create schema description
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
        
        # Create a document with the schema
        with open("schema.txt", "w") as f:
            f.write(schema)
        
        # Initialize LlamaIndex components
        llm = LlamaOpenAI(
            model="gpt-3.5-turbo",
            temperature=0,
            api_key=os.getenv("OPENAI_API_KEY"),
            organization=os.getenv("OPENAI_ORG_ID")
        )
        
        service_context = llm
        
        # Create and store the index
        documents = SimpleDirectoryReader(input_files=["schema.txt"]).load_data()
        index = VectorStoreIndex.from_documents(documents, service_context=service_context)
        index.storage_context.persist(persist_dir="index_store")
        
        # Clean up temporary file
        os.remove("schema.txt")
    
    return index

# Initialize the index when the module loads
index = initialize_llama_index()

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

    print(summary)
    return summary

@chat_bp.route('/chat', methods=['POST'])
@with_supabase_auth
def chat():
    supabase = get_supabase_client()
    data = request.get_json()
    question = data.get('question', '')
    
    # Add user question to chat memory
    add_to_chat_memory("user", question)
    
    try:
        # Use LlamaIndex to understand the query and generate SQL
        query_engine = index.as_query_engine(
            similarity_top_k=3,
            response_mode="tree_summarize"
        )
        
        # Create a prompt that guides LlamaIndex to generate SQL
        prompt = f"""Given the database schema and the following question, generate a SQL query that answers the question.
        Follow these rules:
        1. Use exact table and column names as defined in the schema
        2. Use valid PostgreSQL syntax
        3. When using DISTINCT with ORDER BY:
           - Either include the ORDER BY expression in the SELECT list
           - Or use a subquery/CTE to calculate the ordering
        4. Consider data types (uuid, text, date, time, bool, timestamptz) when writing WHERE clauses
        5. Do not return UUIDs — only return meaningful text fields
        6. Use ILIKE AND wildcards (e.g. '%value%') when searching for specific names or text
        7. For schedule logic:
            - A doctor is scheduled ONLY if both start_time AND end_time are present
            - Ignore rows where schedule_details contains 'off', 'vacation', or 'not scheduled'
            - For time calculations, cast times to TIMESTAMP before subtracting
            - When calculating shift duration, use:
              CASE 
                WHEN end_time < start_time 
                THEN (CURRENT_DATE + end_time + INTERVAL '1 day') - (CURRENT_DATE + start_time)
                ELSE (CURRENT_DATE + end_time) - (CURRENT_DATE + start_time)
              END as shift_duration
        8. When answering questions about average RVUs:
               - The rad_avg_monthly_rvu table contains monthly data in individual columns (jan, feb, ..., dec).
               - Do NOT refer to a column called total_rvus – it does not exist.
               - Each monthly column is the average RVU score for that doctor for that month, and there are months that will be NULL so Use COALESCE() on each month before adding them. 
               - To calculate average RVU per month, sum the 12 monthly columns and divide by 12.
        9. When searching for a doctor by name, you must search only by last name and use wildcards, do not search by first name or full name.
        10. When asked a question about specialties and specialty permissions, you must check the can_read attribute in the specialty_permissions table before assuming a radiologist can read a certain specialty, it is a boolean column.
        {format_chat_history()}
        
        Question: {question}
        
        Respond with ONLY the SQL query, wrapped in ```sql code blocks."""
        
        # Get SQL query from LlamaIndex
        response = query_engine.query(prompt)
        response_text = str(response)
        
        if '```sql' in response_text:
            try:
                sql_query = response_text.split('```sql')[1].split('```')[0].strip().rstrip(';')
                print(f"Executing SQL query: {sql_query}")
                result = supabase.rpc('execute_sql', {'query': sql_query}).execute()

                if result.data is None:
                    return jsonify({
                        'error': 'Query executed but returned no data.',
                        'response': response_text
                    }), 404

                # Use OpenAI only for formatting the results in natural language
                client = OpenAI(
                    api_key=os.getenv("OPENAI_API_KEY"),
                    organization=os.getenv("OPENAI_ORG_ID")
                )
                
                format_prompt = f"""
                Original question: {question}
                
                Query results:
                {json.dumps(result.data, indent=2)}
                
                Format these results into a clear, natural language response that directly answers the original question.
                Focus on making the response easy to understand and relevant to what was asked, and if the response returns multiple rows, separate each row with a new line.
                If there are many results, summarize them appropriately.
                """
                
                format_response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that formats database query results into clear, natural language responses."},
                        {"role": "user", "content": format_prompt}
                    ]
                )
                
                formatted_response = format_response.choices[0].message.content
                print(formatted_response)
                # Add assistant response to chat memory
                add_to_chat_memory("assistant", formatted_response)
                
                return jsonify({
                    'response': formatted_response,
                    'results': result.data
                })

            except Exception as e:
                print(f"Error executing query: {str(e)}")
                error_response = f'I encountered an error while trying to find the information: {str(e)}'
                add_to_chat_memory("assistant", error_response)
                return jsonify({
                    'error': error_response,
                    'response': response_text
                }), 500

        return jsonify({'response': response_text})

    except Exception as e:
        print(f"Error with LlamaIndex or OpenAI API: {str(e)}")
        error_response = f'I encountered an error while processing your request: {str(e)}'
        add_to_chat_memory("assistant", error_response)
        return jsonify({
            'error': error_response
        }), 500

@chat_bp.route('/chat/history', methods=['GET'])
@with_supabase_auth
def get_chat_history():
    """Get the chat history for the current session."""
    memory = get_chat_memory()
    return jsonify({'history': memory})

@chat_bp.route('/chat/clear', methods=['POST'])
@with_supabase_auth
def clear_chat_history():
    """Clear the chat history for the current session."""
    session['chat_memory'] = []
    return jsonify({'success': True})