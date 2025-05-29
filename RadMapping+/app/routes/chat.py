from flask import Blueprint, json, render_template, session, redirect, url_for, request, jsonify, has_app_context
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
import re
import logging
from typing import Dict, List, Any, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

chat_bp = Blueprint('chat', __name__)

# Constants
MAX_CHAT_MEMORY = 10
MAX_RETRY_ATTEMPTS = 3
QUERY_TIMEOUT = 30  # seconds

def get_chat_memory():
    """Get or create chat memory for the current session."""
    if 'chat_memory' not in session:
        session['chat_memory'] = []
    return session['chat_memory']

def add_to_chat_memory(role: str, content: str):
    """Add a message to the chat memory."""
    memory = get_chat_memory()
    memory.append({
        "role": role, 
        "content": content,
        "timestamp": datetime.now().isoformat()
    })
    # Keep only last MAX_CHAT_MEMORY messages
    if len(memory) > MAX_CHAT_MEMORY:
        memory = memory[-MAX_CHAT_MEMORY:]
    session['chat_memory'] = memory
    return memory

def format_chat_history() -> str:
    """Format chat history for the prompt."""
    memory = get_chat_memory()
    if not memory:
        return ""
    
    history = "Previous conversation context:\n"
    for msg in memory[-5:]:  # Only use last 5 messages for context
        history += f"{msg['role']}: {msg['content']}\n"
    return history

def validate_sql_query(query: str) -> tuple[bool, str]:
    """Validate SQL query for safety and basic syntax."""
    query_lower = query.lower().strip()
    
    # Check for dangerous operations
    dangerous_keywords = ['drop', 'delete', 'truncate', 'alter', 'create', 'insert', 'update']
    for keyword in dangerous_keywords:
        if f' {keyword} ' in f' {query_lower} ':
            return False, f"Dangerous operation detected: {keyword}"
    
    # Check for basic SQL structure
    if not query_lower.startswith('select'):
        return False, "Query must start with SELECT"
    
    # Check for balanced parentheses
    if query.count('(') != query.count(')'):
        return False, "Unbalanced parentheses in query"
    
    return True, "Valid"

def extract_sql_from_response(response_text: str) -> Optional[str]:
    """Extract SQL query from LLM response with multiple fallback methods."""
    # Method 1: Look for ```sql blocks
    sql_match = re.search(r'```sql\s*(.*?)\s*```', response_text, re.DOTALL | re.IGNORECASE)
    if sql_match:
        return sql_match.group(1).strip().rstrip(';')
    
    # Method 2: Look for any code blocks
    code_match = re.search(r'```\s*(.*?)\s*```', response_text, re.DOTALL)
    if code_match:
        potential_sql = code_match.group(1).strip().rstrip(';')
        if potential_sql.lower().startswith('select'):
            return potential_sql
    
    # Method 3: Look for SELECT statements in plain text
    select_match = re.search(r'(SELECT.*?)(?:\n\n|\Z)', response_text, re.DOTALL | re.IGNORECASE)
    if select_match:
        return select_match.group(1).strip().rstrip(';')
    
    return None

def get_sample_rows():
    """Get sample rows with better error handling."""
    supabase = get_supabase_client()
    samples = {}
    tables = [
        "radiologists", "facilities", "monthly_schedule", "specialty_studies", 
        "rad_avg_monthly_rvu", "capacity_per_hour", "doctor_facility_assignments", 
        "pinned_doctors", "certifications", "vesta_contacts", "vacations"
    ]
    
    for table in tables:
        try:
            result = supabase.table(table).select("*").limit(2).execute()
            samples[table] = result.data if result.data else []
        except Exception as e:
            logger.error(f"Error loading samples from {table}: {e}")
            samples[table] = []
    
    return samples

def create_enhanced_schema() -> str:
    """Create enhanced schema with examples and constraints."""
    base_schema = """
    Database Schema for Radiology Management System:

    TABLES AND RELATIONSHIPS:

    1. radiologists (Main doctor information)
       - id: uuid (PRIMARY KEY)
       - name: text (Doctor's full name)
       - pacs: text (PACS system identifier)
       - primary_contact_method: text
       - phone: text
       - email: text
       - active_status: bool ('TRUE', 'FALSE')
       - schedule_info_est: text
       - additional_info: text
       - modalities: text (comma-separated list)
       - timezone: text
       - reads_stats: text ('YES', 'NO')
       - reads_routines: text ('NO', 'NO')
       - stipulations: text

    2. facilities (Imaging facilities)
       - id: uuid (PRIMARY KEY)
       - name: text (Facility name)
       - pacs: text
       - location: text
       - modalities: text (comma-separated)
       - tat_definition: text (turnaround time)
       - active_status: text ('true', 'false')

    3. monthly_schedule (Doctor schedules)
       - id: uuid (PRIMARY KEY)
       - radiologist_id: uuid (FOREIGN KEY -> radiologists.id)
       - start_time: time (shift start)
       - end_time: time (shift end)
       - schedule_details: text (may contain 'off', 'vacation', etc.)
       - break_start: time
       - break_end: time
       - start_date: date (individual shift start)
       - end_date: date (invidivudal shift end)

    4. rad_avg_monthly_rvu (Monthly RVU averages)
       - radiologist_id: uuid (FOREIGN KEY -> radiologists.id)
       - jan through dec: float8 (average RVUs per month, may be NULL)

    5. specialty_studies (Available specialties studies. i.e. 'CT', 'MRI', etc.)
       - id: uuid (PRIMARY KEY)
       - name: text (specialty name)
       - description: text

    6. specialty_permissions (Which doctors can read which specialty exams, HAS NOTHING TO DO WITH STATE CERTIFICATIONS AND FACILITIES)
       - id: uuid (PRIMARY KEY)
       - radiologist_id: uuid (FOREIGN KEY -> radiologists.id)
       - specialty_id: uuid (FOREIGN KEY -> specialty_studies.id)
       - can_read: boolean (permission flag)

    7. doctor_facility_assignments (Doctor-facility relationships)
       - id: uuid (PRIMARY KEY)
       - radiologist_id: uuid (FOREIGN KEY -> radiologists.id)
       - facility_id: uuid (FOREIGN KEY -> facilities.id)
       - notes: text
       - can_read: text ('true', 'false', 'pending')

    8. capacity_per_hour (Historical capacity data, used for RVU calculations that do not pertain to a specific doctor)
       - id: int (PRIMARY KEY)
       - date: date
       - hour: int (0-23)
       - total_rvus: float8

    9. vacations (Doctor vacation periods)
       - id: uuid (PRIMARY KEY)
       - radiologist_id: uuid (FOREIGN KEY -> radiologists.id)
       - start_date: date
       - end_date: date
       - comments: text

    10. certifications (Doctor certifications by state)
        - id: uuid (PRIMARY KEY)
        - radiologist_id: uuid (FOREIGN KEY -> radiologists.id)
        - state: text
        - expiration_date: date
        - status: text ('Active', 'Expired')
        - specialty: text
        - tags: text

    QUERY GUIDELINES:
    - Always use JOINs instead of subqueries when possible for better performance
    - DO NOT QUERY THE specialties_permissions or specialty_studies TABLE UNLESS SPECIALTY OR SPECIALTIES IS MENTIONED IN THE QUESTION
    - Use ILIKE with wildcards (%) for case-insensitive text searches
    - For name searches, search by last name only with wildcards
    - Handle NULL values with COALESCE() or IS NOT NULL checks
    - Schedule logic: doctor is scheduled only if start_time AND end_time are NOT NULL
    - Exclude schedule rows with 'off', 'vacation', 'not scheduled' in schedule_details
    - For time calculations across midnight, handle end_time < start_time case
    - DO NOT USE LIMIT in queries unless a specific limit is requested or implied by the question 
    - When asked a question involving relative date expressions (e.g., "today", "yesterday", "this week", "last month"), interpret them using the current system date and convert them into explicit date filters in the generated SQL. Ensure proper handling of timezones and boundaries (e.g., for "today" use start_date = CURRENT_DATE). Make sure to account for shifts overlapping into different days. REFER TO EXAMPLES BELOW..
    - When asked a question about who can read where, always check the certifications table and NOT specialty_permissions table. The specialty_permissions table is only used to check if a doctor can read a specific specialty exam, NOT to check if they can read at a specific facility.
    Examples:
    - "Who is working today at 2am?" -> WHERE ((ms.start_date = CURRENT_DATE AND ((ms.start_time <= '02:00:00' AND ms.end_time > '02:00:00' AND ms.end_time > ms.start_time) OR (ms.start_time <= '02:00:00' AND ms.end_time < ms.start_time))) OR (ms.start_date = CURRENT_DATE - INTERVAL '1 day' AND ms.start_time IS NOT NULL AND ms.end_time IS NOT NULL AND ms.end_time < ms.start_time AND '02:00:00' < ms.end_time)) AND ms.start_time IS NOT NULL AND ms.end_time IS NOT NULL AND ms.schedule_details NOT ILIKE '%off%' AND ms.schedule_details NOT ILIKE '%vacation%' AND ms.schedule_details NOT ILIKE '%not scheduled%'
    - "Coverage this week" → filter using `start_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '6 days'`.
    - "Which doctors are scheduled to work on [insert speficic date for tomorrow]?" -> WHERE ((ms.start_date = CURRENT_DATE + INTERVAL '1 day' AND ms.start_time IS NOT NULL AND ms.end_time IS NOT NULL) OR (ms.start_date = CURRENT_DATE AND ms.start_time IS NOT NULL AND ms.end_time IS NOT NULL AND ms.end_time < ms.start_time)) AND ms.schedule_details NOT ILIKE '%off%' AND ms.schedule_details NOT ILIKE '%vacation%' AND ms.schedule_details NOT ILIKE '%not scheduled%'

    """
    
    if has_app_context():
        try:
            sample_rows = get_sample_rows()
            for table, rows in sample_rows.items():
                if rows:  # Only add if we have data
                    base_schema += f"\n\nSample data from {table}:\n"
                    for i, row in enumerate(rows[:2]):  # Limit to 2 samples
                        base_schema += f"Row {i+1}: {json.dumps(row, indent=2, default=str)}\n"
        except Exception as e:
            logger.error(f"Error adding sample data to schema: {e}")
    
    return base_schema

def initialize_llama_index(force_rebuild: bool = False):
    """Initialize LlamaIndex with better error handling."""
    try:
        # Create storage directory if it doesn't exist
        os.makedirs("index_store", exist_ok=True)
        
        # Check if we should rebuild or load existing index
        index_exists = os.path.exists("index_store/index.json")
        
        if not force_rebuild and index_exists:
            try:
                storage_context = StorageContext.from_defaults(persist_dir="index_store")
                index = load_index_from_storage(storage_context)
                logger.info("Loaded existing LlamaIndex")
                return index
            except Exception as e:
                logger.warning(f"Failed to load existing index, rebuilding: {e}")
        
        # Create new index
        logger.info("Creating new LlamaIndex...")
        
        # Initialize LLM with better settings
        llm = LlamaOpenAI(
            model="gpt-4o",
            temperature=0.2,  # Lower temperature for more consistent SQL generation
            api_key=os.getenv("OPENAI_API_KEY"),
            organization=os.getenv("OPENAI_ORG_ID"),
            max_tokens=1000
        )
        
        # Create enhanced schema document
        schema_content = create_enhanced_schema()
        
        # Write to temporary file
        schema_file = "temp_schema.txt"
        with open(schema_file, "w", encoding="utf-8") as f:
            f.write(schema_content)
        
        try:
            # Create and store the index
            documents = SimpleDirectoryReader(input_files=[schema_file]).load_data()
            index = VectorStoreIndex.from_documents(documents, service_context=llm)
            index.storage_context.persist(persist_dir="index_store")
            logger.info("Successfully created and stored new index")
        finally:
            # Clean up temporary file
            if os.path.exists(schema_file):
                os.remove(schema_file)
        
        return index
        
    except Exception as e:
        logger.error(f"Error initializing LlamaIndex: {e}")
        raise

# Initialize the index when the module loads
try:
    index = initialize_llama_index()
except Exception as e:
    logger.error(f"Failed to initialize index on startup: {e}")
    index = None

def execute_query_with_retry(supabase, sql_query: str, max_retries: int = 2) -> tuple[bool, Any, str]:
    """Execute SQL query with retry logic and better error handling."""
    for attempt in range(max_retries + 1):
        try:
            logger.info(f"Executing SQL (attempt {attempt + 1}): {sql_query}")
            result = supabase.rpc('execute_sql', {'query': sql_query}).execute()
            
            if result.data is not None:
                return True, result.data, ""
            else:
                return False, None, "Query executed but returned no data"
                
        except Exception as e:
            error_msg = str(e).lower()
            
            # Check for specific error types that shouldn't be retried
            non_retryable_errors = [
                'syntax error', 'column does not exist', 'table does not exist',
                'permission denied', 'invalid input syntax'
            ]
            
            if any(err in error_msg for err in non_retryable_errors):
                return False, None, f"SQL Error: {str(e)}"
            
            if attempt == max_retries:
                return False, None, f"Query failed after {max_retries + 1} attempts: {str(e)}"
            
            logger.warning(f"Query attempt {attempt + 1} failed, retrying: {e}")
    
    return False, None, "Maximum retry attempts exceeded"

def create_enhanced_prompt(rewritten_question: str, chat_history: str) -> str:
    """Create an enhanced prompt for better SQL generation."""
    return f"""
You are an expert PostgreSQL query generator for a radiology management system.

CONTEXT:
{chat_history}

CURRENT QUESTION: {rewritten_question}

RULES FOR SQL GENERATION:
1. Generate ONLY valid PostgreSQL SELECT statements
2. Use exact table and column names from the schema
3. Always use proper JOINs (never implicit joins)
4. Handle NULL values appropriately with COALESCE() or IS NOT NULL
5. Use ILIKE with % wildcards for text searches
6. For doctor names, search by last name only with wildcards
7. Return meaningful columns (names, not UUIDs unless specifically requested)
8. For RVU calculations: Use COALESCE(month_column, 0) before summing
9. For schedules: Only consider rows where start_time AND end_time are NOT NULL
10. Exclude schedule rows where schedule_details contains 'off', 'vacation', or 'not scheduled'
11. For specialty permissions: Check can_read = true in specialty_permissions table
12. Limit results to reasonable numbers (use LIMIT if appropriate)

RESPONSE FORMAT:
Respond with ONLY the SQL query wrapped in ```sql``` code blocks.
No explanations, no additional text, just the SQL query.

Generate the SQL query now:
"""

@chat_bp.route('/chat/rebuild_index', methods=['POST'])
@admin_required
def rebuild_index():
    global index
    try:
        index = initialize_llama_index(force_rebuild=True)
        return jsonify({'success': True, 'message': 'Index rebuilt successfully.'})
    except Exception as e:
        logger.error(f"Error rebuilding index: {e}")
        return jsonify({'error': str(e)}), 500

@chat_bp.route('/chat', methods=['POST'])
@with_supabase_auth
def chat():
    if index is None:
        return jsonify({'error': 'Chat system is not properly initialized. Please contact an administrator.'}), 500
    
    supabase = get_supabase_client()
    data = request.get_json()
    question = data.get('question', '').strip()
    
    if not question:
        return jsonify({'error': 'Question cannot be empty'}), 400
    
    # Add user question to chat memory
    add_to_chat_memory("user", question)
    # Step 1: Reword the question using OpenAI
    try:
        client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            organization=os.getenv("OPENAI_ORG_ID")
        )

        clarification_prompt = f"""
    You are a question rewriting assistant for a SQL query generator. 
    Your job is to rephrase or clarify the user's question to make it more explicit, grammatically correct, and unambiguous, 
    so that a database system can generate an appropriate SQL query from it.

    Make sure to:
    - Add necessary context if it’s missing
    - Turn vague references like "today", "tomorrow", "next week" into explicit terms
    - Specify entities like "doctors", "shifts", or "facilities" when needed
    - Avoid adding explanations or comments

    Original question: "{question}"
    Rewritten question:
    """

        clarification_response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You improve user questions for SQL generation clarity."},
                {"role": "user", "content": clarification_prompt}
            ],
            temperature=0.3,
            max_tokens=100
        )

        rewritten_question = clarification_response.choices[0].message.content.strip()
        logger.info(f"[🔁] Rewritten question: {rewritten_question}")
    except Exception as e:
        logger.warning(f"Rewriting failed, using original question: {e}")
        rewritten_question = question

    try:
        # Create query engine with optimized settings
        query_engine = index.as_query_engine(
            similarity_top_k=5,  # Get more context
            response_mode="compact",  # More focused responses
            streaming=False
        )
        
        # Create enhanced prompt
        chat_history = format_chat_history()
        enhanced_prompt = create_enhanced_prompt(rewritten_question, chat_history)
        
        # Get SQL query from LlamaIndex with retry logic
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                response = query_engine.query(enhanced_prompt)
                response_text = str(response)
                
                # Extract SQL query
                sql_query = extract_sql_from_response(response_text)
                
                if not sql_query:
                    if attempt == MAX_RETRY_ATTEMPTS - 1:
                        error_msg = "Could not extract valid SQL query from response"
                        add_to_chat_memory("assistant", error_msg)
                        return jsonify({'error': error_msg, 'llm_response': response_text}), 400
                    continue
                
                # Validate SQL query
                is_valid, validation_msg = validate_sql_query(sql_query)
                if not is_valid:
                    if attempt == MAX_RETRY_ATTEMPTS - 1:
                        error_msg = f"Generated invalid SQL: {validation_msg}"
                        add_to_chat_memory("assistant", error_msg)
                        return jsonify({'error': error_msg, 'sql_query': sql_query}), 400
                    continue
                
                # Execute query with retry logic
                success, result_data, error_msg = execute_query_with_retry(supabase, sql_query)
                
                if not success:
                    if attempt == MAX_RETRY_ATTEMPTS - 1:
                        add_to_chat_memory("assistant", error_msg)
                        return jsonify({'error': error_msg, 'sql_query': sql_query}), 400
                    continue
                
                # Successfully executed query
                break
                
            except Exception as e:
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    error_msg = f"Error generating or executing query: {str(e)}"
                    logger.error(error_msg)
                    add_to_chat_memory("assistant", error_msg)
                    return jsonify({'error': error_msg}), 500
                continue
        
        # Format results using OpenAI
        try:
            client = OpenAI(
                api_key=os.getenv("OPENAI_API_KEY"),
                organization=os.getenv("OPENAI_ORG_ID")
            )
            
            format_prompt = f"""
            Original question: {question}
            
            SQL Query executed: {sql_query}
            
            Query results:
            {json.dumps(result_data, indent=2, default=str)}
            
            Please format these results into a clear, natural language response that directly answers the original question.
            
            Guidelines:
            - Be concise but complete
            - If multiple results, organize them clearly
            - Include relevant details but avoid overwhelming information
            - If no results found, explain what this means
            - Use bullet points or numbering for multiple items when appropriate
            """
            
            format_response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that formats database query results into clear, natural language responses for a radiology management system."},
                    {"role": "user", "content": format_prompt}
                ],
                temperature=0.3,
                max_tokens=1000
            )
            
            formatted_response = format_response.choices[0].message.content
            
            # Add assistant response to chat memory
            add_to_chat_memory("assistant", formatted_response)
            
            return jsonify({
                'response': formatted_response,
                'results': result_data,
                
            })
            
        except Exception as e:
            logger.error(f"Error formatting response: {e}")
            # Fallback to basic formatting
            fallback_response = f"I found {len(result_data)} result(s) for your query."
            add_to_chat_memory("assistant", fallback_response)
            return jsonify({
                'response': fallback_response,
                'results': result_data,
                
            })

    except Exception as e:
        logger.error(f"Unexpected error in chat endpoint: {e}")
        error_response = 'An unexpected error occurred while processing your request. Please try again.'
        add_to_chat_memory("assistant", error_response)
        return jsonify({'error': error_response}), 500

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
    return jsonify({'success': True, 'message': 'Chat history cleared successfully'})

@chat_bp.route('/chat/status', methods=['GET'])
@with_supabase_auth
def get_chat_status():
    """Get the current status of the chat system."""
    return jsonify({
        'index_initialized': index is not None,
        'memory_size': len(get_chat_memory()),
        'max_memory': MAX_CHAT_MEMORY
    })