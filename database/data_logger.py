# data_logger.py
import psycopg2
import psycopg2.extras # For DictCursor
import datetime
import os

# Import connection details from db_setup
# Assuming data_logger.py is in the same directory as db_setup.py
from db_setup import get_db_connection_string # MODIFIED: Removed relative import

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
        # print(f"Activity logged for user_id: {user_id} in PostgreSQL with details.")
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
        # Removed user_answer from query as it's not in the table schema provided earlier
        conn.commit()
        # print(f"Interaction logged in PostgreSQL for quiz {quiz_session_id}, question {question_id}, user {user_id}, correct: {is_correct}")
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
        log_question_interaction(quiz_session_id_user1, test_user_id1, "CHEM_Q101", True, user_answer="A")
        log_question_interaction(quiz_session_id_user1, test_user_id1, "CHEM_Q102", False, user_answer="C", attempts=2)
        log_question_interaction(quiz_session_id_user1, test_user_id1, "CHEM_Q103", True, user_answer="B")
        log_quiz_end(quiz_session_id_user1, score=2, status='completed')
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
    except psycopg2.Error as e:
        print(f"PostgreSQL error during verification query: {e}")
    finally:
        if conn_verify:
            conn_verify.close()
    print("PostgreSQL data_logger test script (enhanced) finished.")

