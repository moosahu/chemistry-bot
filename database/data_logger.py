# data_logger.py
import psycopg2
import psycopg2.extras # For DictCursor
import datetime
import os

# Import connection details from db_setup
from db_setup import get_db_connection_string, create_connection as get_raw_connection # Renaming to avoid conflict if any

def get_db_connection():
    """Establishes a connection to the PostgreSQL database and returns a cursor that returns dicts."""
    conn_string = get_db_connection_string()
    conn = psycopg2.connect(conn_string)
    return conn

def log_user_activity(user_id, username=None):
    """Logs user's first appearance and updates last active timestamp in PostgreSQL."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Upsert logic for PostgreSQL
        # Insert new user or update last_active_timestamp and username if they exist
        cursor.execute("""
            INSERT INTO users (user_id, username, first_seen_timestamp, last_active_timestamp)
            VALUES (%s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id)
            DO UPDATE SET 
                last_active_timestamp = CURRENT_TIMESTAMP,
                username = COALESCE(EXCLUDED.username, users.username);
        """, (user_id, username))
        
        conn.commit()
        print(f"Activity logged for user_id: {user_id} in PostgreSQL")
    except psycopg2.Error as e:
        print(f"PostgreSQL error in log_user_activity: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def log_quiz_start(user_id, unit_id, total_questions):
    """Logs the start of a new quiz session and returns the session ID from PostgreSQL."""
    conn = None
    quiz_session_id = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        log_user_activity(user_id) # Ensure user is in the users table and active
        
        cursor.execute("""
            INSERT INTO quiz_sessions (user_id, unit_id, total_questions_in_quiz, start_timestamp, status)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP, 'started')
            RETURNING quiz_session_id;
        """, (user_id, unit_id, total_questions))
        
        quiz_session_id_tuple = cursor.fetchone()
        if quiz_session_id_tuple:
            quiz_session_id = quiz_session_id_tuple[0]
        conn.commit()
        print(f"Quiz session started in PostgreSQL: ID {quiz_session_id} for user {user_id}, unit {unit_id}")
    except psycopg2.Error as e:
        print(f"PostgreSQL error in log_quiz_start: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
    return quiz_session_id

def log_question_interaction(quiz_session_id, user_id, question_id, is_correct, attempts=1):
    """Logs a user's interaction with a specific question in PostgreSQL."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        log_user_activity(user_id) # Update user's last activity
        
        cursor.execute("""
            INSERT INTO question_interactions (quiz_session_id, user_id, question_id, is_correct, attempts_count, answer_timestamp)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        """, (quiz_session_id, user_id, question_id, is_correct, attempts))
        conn.commit()
        print(f"Interaction logged in PostgreSQL for quiz {quiz_session_id}, question {question_id}, user {user_id}, correct: {is_correct}")
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
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor) # Use DictCursor here for fetching user_id by name
        
        cursor.execute("""
            UPDATE quiz_sessions 
            SET end_timestamp = CURRENT_TIMESTAMP, score = %s, status = %s
            WHERE quiz_session_id = %s
        """, (score, status, quiz_session_id))
        
        # Update user's last activity based on quiz end
        cursor.execute("SELECT user_id FROM quiz_sessions WHERE quiz_session_id = %s", (quiz_session_id,))
        user_data = cursor.fetchone()
        if user_data:
            log_user_activity(user_data['user_id'])
            
        conn.commit()
        print(f"Quiz session ended in PostgreSQL: ID {quiz_session_id}, score {score}, status {status}")
    except psycopg2.Error as e:
        print(f"PostgreSQL error in log_quiz_end: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    # This part is for testing the logger functions directly.
    # Ensure db_setup.py has been run for PostgreSQL to create tables.

    print("Attempting to run PostgreSQL data_logger test script...")
    
    # Initialize DB and tables (run db_setup.py first if not done)
    # This assumes db_setup.py when run as __main__ handles table creation.
    # For this test, we assume tables exist.

    test_user_id1 = 2001
    test_user_id2 = 2002
    test_username1 = "pg_user_alpha"

    # User 1 starts activity
    log_user_activity(test_user_id1, test_username1)

    # User 1 starts a quiz
    quiz_id_user1 = log_quiz_start(user_id=test_user_id1, unit_id="Unit1_PG_Math", total_questions=10)

    if quiz_id_user1:
        log_question_interaction(quiz_id_user1, test_user_id1, "PG_Q1", True)
        log_question_interaction(quiz_id_user1, test_user_id1, "PG_Q2", False)
        log_question_interaction(quiz_id_user1, test_user_id1, "PG_Q3", True)
        log_quiz_end(quiz_id_user1, score=2, status='completed')

    log_user_activity(test_user_id2, "pg_user_beta")
    quiz_id_user2 = log_quiz_start(user_id=test_user_id2, unit_id="Unit2_PG_Science", total_questions=5)
    if quiz_id_user2:
        log_question_interaction(quiz_id_user2, test_user_id2, "PG_SciQ1", True)
        log_quiz_end(quiz_id_user2, score=0, status='abandoned')

    print("\n--- Querying some data from PostgreSQL for verification ---")
    conn_verify = None
    try:
        conn_verify = get_db_connection()
        c_verify = conn_verify.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        print("\nUsers:")
        c_verify.execute("SELECT * FROM users ORDER BY user_id DESC LIMIT 5")
        for row in c_verify.fetchall():
            print(dict(row))

        print("\nQuiz Sessions:")
        c_verify.execute("SELECT * FROM quiz_sessions ORDER BY quiz_session_id DESC LIMIT 5")
        for row in c_verify.fetchall():
            print(dict(row))

        print("\nQuestion Interactions:")
        c_verify.execute("SELECT * FROM question_interactions ORDER BY interaction_id DESC LIMIT 5")
        for row in c_verify.fetchall():
            print(dict(row))
            
    except psycopg2.Error as e:
        print(f"PostgreSQL error during verification query: {e}")
    finally:
        if conn_verify:
            conn_verify.close()
    print("PostgreSQL data_logger test script finished.")

