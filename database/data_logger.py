# data_logger.py
import psycopg2
import psycopg2.extras # For DictCursor and json
import datetime
import os
import json # For serializing answers_details to JSON

# Import connection details from db_setup
from .db_setup import get_db_connection_string

def get_db_connection():
    """Establishes a connection to the PostgreSQL database."""
    conn_string = get_db_connection_string()
    conn = psycopg2.connect(conn_string)
    return conn

def log_user_activity(user_id, username=None, first_name=None, last_name=None, language_code=None):
    """Logs user's first appearance and updates last active/interaction timestamp and other details in PostgreSQL."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO users (user_id, username, first_name, last_name, language_code, first_seen_timestamp, last_active_timestamp, last_interaction_date)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id)
            DO UPDATE SET 
                username = COALESCE(EXCLUDED.username, users.username),
                first_name = COALESCE(EXCLUDED.first_name, users.first_name),
                last_name = COALESCE(EXCLUDED.last_name, users.last_name),
                language_code = COALESCE(EXCLUDED.language_code, users.language_code),
                last_active_timestamp = CURRENT_TIMESTAMP,
                last_interaction_date = CURRENT_TIMESTAMP;
        """, (user_id, username, first_name, last_name, language_code))
        
        conn.commit()
    except psycopg2.Error as e:
        print(f"PostgreSQL error in log_user_activity: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def log_quiz_start(user_id, quiz_name, total_questions, quiz_type="unknown"):
    """Logs the start of a new quiz session and returns the session ID from PostgreSQL."""
    conn = None
    quiz_session_id = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO quiz_sessions (user_id, unit_id, total_questions_in_quiz, start_timestamp, status, quiz_type)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP, 'started', %s)
            RETURNING quiz_session_id;
        """, (user_id, quiz_name, total_questions, quiz_type))
        
        quiz_session_id_tuple = cursor.fetchone()
        if quiz_session_id_tuple:
            quiz_session_id = quiz_session_id_tuple[0]
        conn.commit()
        print(f"Quiz session started in PostgreSQL: ID {quiz_session_id} for user {user_id}, quiz_name '{quiz_name}', type '{quiz_type}'")
    except psycopg2.Error as e:
        print(f"PostgreSQL error in log_quiz_start: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
    return quiz_session_id

def log_question_interaction(quiz_session_id, user_id, question_id, is_correct, user_answer=None, attempts=1):
    """Logs a user's interaction with a specific question in PostgreSQL."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO question_interactions (quiz_session_id, user_id, question_id, is_correct, attempts_count, answer_timestamp)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        """, (quiz_session_id, user_id, str(question_id), is_correct, attempts))
        conn.commit()
    except psycopg2.Error as e:
        print(f"PostgreSQL error in log_question_interaction: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def log_quiz_end(quiz_session_id, score, status='completed'):
    """Logs the end of a quiz session, including the score and status in PostgreSQL."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cursor.execute("""
            UPDATE quiz_sessions 
            SET end_timestamp = CURRENT_TIMESTAMP, score = %s, status = %s
            WHERE quiz_session_id = %s
            RETURNING user_id;
        """, (score, status, quiz_session_id))
        
        user_id_data = cursor.fetchone()
        conn.commit()

        if user_id_data and user_id_data['user_id']:
            log_user_activity(user_id_data['user_id'])
            
        print(f"Quiz session ended in PostgreSQL: ID {quiz_session_id}, score {score}, status {status}")
    except psycopg2.Error as e:
        print(f"PostgreSQL error in log_quiz_end: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# --- NEW FUNCTION --- 
def log_quiz_results(db_quiz_session_id, user_id, quiz_id_uuid, quiz_name, quiz_type, score, total_questions, percentage, answers_details):
    """
    Logs the detailed results of a completed quiz to the 'quiz_results' table in PostgreSQL.
    
    Args:
        db_quiz_session_id: The ID from the 'quiz_sessions' table (foreign key).
        user_id: The ID of the user who took the quiz.
        quiz_id_uuid: The UUID of the QuizLogic instance (for internal tracking).
        quiz_name: The name of the quiz.
        quiz_type: The type of the quiz (e.g., 'all_scope_quiz', 'unit_quiz').
        score: The user's score.
        total_questions: The total number of questions in the quiz.
        percentage: The user's percentage score.
        answers_details: A list of dictionaries containing details for each answer.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # IMPORTANT: This function assumes you have a 'quiz_results' table with the following (or similar) schema:
        # CREATE TABLE IF NOT EXISTS quiz_results (
        #     result_id SERIAL PRIMARY KEY,
        #     quiz_session_id INTEGER REFERENCES quiz_sessions(quiz_session_id) ON DELETE SET NULL,
        #     user_id BIGINT,
        #     quiz_logic_uuid VARCHAR(36),
        #     quiz_name VARCHAR(255),
        #     quiz_type VARCHAR(255),
        #     score INTEGER,
        #     total_questions INTEGER,
        #     percentage REAL,
        #     answers_details JSONB, -- Stores the list of answer details
        #     completion_timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        # );
        
        # Serialize answers_details to a JSON string for storing in JSONB column
        answers_details_json = json.dumps(answers_details)

        cursor.execute("""
            INSERT INTO quiz_results 
                (quiz_session_id, user_id, quiz_logic_uuid, quiz_name, quiz_type, 
                 score, total_questions, percentage, answers_details, completion_timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            RETURNING result_id;
        """, (db_quiz_session_id, user_id, quiz_id_uuid, quiz_name, quiz_type, 
              score, total_questions, percentage, answers_details_json))
        
        result_id_tuple = cursor.fetchone()
        conn.commit()
        if result_id_tuple:
            print(f"Quiz results logged to PostgreSQL: Result ID {result_id_tuple[0]} for session {db_quiz_session_id}, user {user_id}")
        else:
            print(f"Quiz results logged to PostgreSQL (no result_id returned) for session {db_quiz_session_id}, user {user_id}")

    except psycopg2.Error as e:
        print(f"PostgreSQL error in log_quiz_results: {e}")
        if conn:
            conn.rollback()
    except Exception as ex:
        print(f"An unexpected error occurred in log_quiz_results: {ex}")
        if conn:
            conn.rollback() # Rollback on general exceptions too
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    print("Attempting to run PostgreSQL data_logger test script (enhanced)...")
    test_user_id1 = 3001
    test_username1 = "pg_user_gamma"
    test_first_name1 = "Gamma"
    test_last_name1 = "User"
    test_lang_code1 = "ar"
    test_user_id2 = 3002
    log_user_activity(test_user_id1, test_username1, test_first_name1, test_last_name1, test_lang_code1)
    quiz_session_id_user1 = log_quiz_start(user_id=test_user_id1, quiz_name="Advanced Chemistry Quiz", total_questions=15, quiz_type="UNIT_QUIZ")
    if quiz_session_id_user1:
        log_question_interaction(quiz_session_id_user1, test_user_id1, "CHEM_Q101", True)
        log_question_interaction(quiz_session_id_user1, test_user_id1, "CHEM_Q102", False, attempts=2)
        log_question_interaction(quiz_session_id_user1, test_user_id1, "CHEM_Q103", True)
        log_quiz_end(quiz_session_id_user1, score=2, status='completed')
        
        # Test for new log_quiz_results function
        sample_answers_details = [
            {"question_id": "CHEM_Q101", "chosen_option_id": "A", "is_correct": True},
            {"question_id": "CHEM_Q102", "chosen_option_id": "C", "is_correct": False},
            {"question_id": "CHEM_Q103", "chosen_option_id": "B", "is_correct": True}
        ]
        log_quiz_results(
            db_quiz_session_id=quiz_session_id_user1,
            user_id=test_user_id1,
            quiz_id_uuid="test-uuid-12345", 
            quiz_name="Advanced Chemistry Quiz",
            quiz_type="UNIT_QUIZ",
            score=2,
            total_questions=3, # Assuming 3 questions were part of this result log for simplicity
            percentage=(2/3)*100,
            answers_details=sample_answers_details
        )

    log_user_activity(test_user_id2, "pg_user_delta")
    quiz_session_id_user2 = log_quiz_start(user_id=test_user_id2, quiz_name="General Knowledge", total_questions=5, quiz_type="RANDOM_ALL")
    if quiz_session_id_user2:
        log_question_interaction(quiz_session_id_user2, test_user_id2, "GK_Q01", True)
        log_quiz_end(quiz_session_id_user2, score=1, status='abandoned')

    print("\n--- Querying some data from PostgreSQL for verification (enhanced) ---")
    conn_verify = None
    try:
        conn_verify = get_db_connection()
        c_verify = conn_verify.cursor(cursor_factory=psycopg2.extras.DictCursor)
        print("\nUsers (last 5 interacted):")
        c_verify.execute("SELECT user_id, username, first_name, last_name, language_code, last_interaction_date FROM users ORDER BY last_interaction_date DESC LIMIT 5")
        for row in c_verify.fetchall():
            print(dict(row))
        print("\nQuiz Sessions (last 5):")
        c_verify.execute("SELECT quiz_session_id, user_id, unit_id as quiz_name, quiz_type, total_questions_in_quiz, score, status, start_timestamp, end_timestamp FROM quiz_sessions ORDER BY quiz_session_id DESC LIMIT 5")
        for row in c_verify.fetchall():
            print(dict(row))
        print("\nQuestion Interactions (last 5):")
        c_verify.execute("SELECT interaction_id, quiz_session_id, user_id, question_id, is_correct, attempts_count, answer_timestamp FROM question_interactions ORDER BY interaction_id DESC LIMIT 5")
        for row in c_verify.fetchall():
            print(dict(row))
        print("\nQuiz Results (last 5):") # New verification query
        c_verify.execute("SELECT result_id, quiz_session_id, user_id, quiz_name, score, percentage, completion_timestamp FROM quiz_results ORDER BY result_id DESC LIMIT 5")
        for row in c_verify.fetchall():
            print(dict(row))

    except psycopg2.Error as e:
        print(f"PostgreSQL error during verification query: {e}")
    finally:
        if conn_verify:
            conn_verify.close()
    print("PostgreSQL data_logger test script (enhanced) finished.")

