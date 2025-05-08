# data_logger.py
import sqlite3
import datetime

DB_NAME = "database/bot_stats.db" # <-- MODIFIED HERE

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row # Allows accessing columns by name
    return conn

def log_user_activity(user_id, username=None):
    """Logs user's first appearance and updates last active timestamp."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Try to insert a new user, or ignore if user_id already exists
        cursor.execute("""
            INSERT OR IGNORE INTO users (user_id, username, first_seen_timestamp, last_active_timestamp)
            VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (user_id, username))
        
        # Update last_active_timestamp for existing user
        cursor.execute("""
            UPDATE users 
            SET last_active_timestamp = CURRENT_TIMESTAMP, username = COALESCE(?, username)
            WHERE user_id = ?
        """, (username, user_id))
        conn.commit()
        print(f"Activity logged for user_id: {user_id}")
    except sqlite3.Error as e:
        print(f"SQLite error in log_user_activity: {e}")
    finally:
        conn.close()

def log_quiz_start(user_id, unit_id, total_questions):
    """Logs the start of a new quiz session and returns the session ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    quiz_session_id = None
    try:
        log_user_activity(user_id) # Ensure user is in the users table and active
        cursor.execute("""
            INSERT INTO quiz_sessions (user_id, unit_id, total_questions_in_quiz, start_timestamp, status)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, 'started')
        """, (user_id, unit_id, total_questions))
        quiz_session_id = cursor.lastrowid
        conn.commit()
        print(f"Quiz session started: ID {quiz_session_id} for user {user_id}, unit {unit_id}")
    except sqlite3.Error as e:
        print(f"SQLite error in log_quiz_start: {e}")
    finally:
        conn.close()
    return quiz_session_id

def log_question_interaction(quiz_session_id, user_id, question_id, is_correct, attempts=1):
    """Logs a user's interaction with a specific question."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        log_user_activity(user_id) # Update user's last activity
        cursor.execute("""
            INSERT INTO question_interactions (quiz_session_id, user_id, question_id, is_correct, attempts_count, answer_timestamp)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (quiz_session_id, user_id, question_id, is_correct, attempts))
        conn.commit()
        print(f"Interaction logged for quiz {quiz_session_id}, question {question_id}, user {user_id}, correct: {is_correct}")
    except sqlite3.Error as e:
        print(f"SQLite error in log_question_interaction: {e}")
    finally:
        conn.close()

def log_quiz_end(quiz_session_id, score, status='completed'):
    """Logs the end of a quiz session, including the score and status."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE quiz_sessions 
            SET end_timestamp = CURRENT_TIMESTAMP, score = ?, status = ?
            WHERE quiz_session_id = ?
        """, (score, status, quiz_session_id))
        conn.commit()
        # Update user's last activity based on quiz end
        cursor.execute("SELECT user_id FROM quiz_sessions WHERE quiz_session_id = ?", (quiz_session_id,))
        user_data = cursor.fetchone()
        if user_data:
            log_user_activity(user_data['user_id'])
        print(f"Quiz session ended: ID {quiz_session_id}, score {score}, status {status}")
    except sqlite3.Error as e:
        print(f"SQLite error in log_quiz_end: {e}")
    finally:
        conn.close()

# --- Example Usage (conceptual - to be integrated into bot logic) ---
# if __name__ == '__main__':
#     # This part is for testing the logger functions directly.
#     # In a real bot, these functions would be called from your bot's handlers.

#     # Initialize DB and tables (run db_setup.py first if not done)
#     # from db_setup import create_connection, create_tables
#     # conn_setup = create_connection()
#     # if conn_setup:
#     #     create_tables(conn_setup)
#     #     conn_setup.close()

#     # Simulate bot events
#     test_user_id1 = 1001
#     test_user_id2 = 1002
#     test_username1 = "testuser_alpha"

#     # User 1 starts activity
#     log_user_activity(test_user_id1, test_username1)

#     # User 1 starts a quiz
#     quiz_id_user1 = log_quiz_start(user_id=test_user_id1, unit_id="Unit1_Math", total_questions=10)

#     if quiz_id_user1:
#         # User 1 answers some questions
#         log_question_interaction(quiz_id_user1, test_user_id1, "Q1", True)
#         log_question_interaction(quiz_id_user1, test_user_id1, "Q2", False)
#         log_question_interaction(quiz_id_user1, test_user_id1, "Q3", True)
        
#         # User 1 finishes the quiz
#         log_quiz_end(quiz_id_user1, score=2, status='completed') # 2 out of 3 answered correctly in this example

#     # User 2 starts activity and a quiz
#     log_user_activity(test_user_id2, "testuser_beta")
#     quiz_id_user2 = log_quiz_start(user_id=test_user_id2, unit_id="Unit2_Science", total_questions=5)
#     if quiz_id_user2:
#         log_question_interaction(quiz_id_user2, test_user_id2, "SciQ1", True)
#         # User 2 abandons the quiz (example)
#         log_quiz_end(quiz_id_user2, score=0, status='abandoned')

#     print("\n--- Querying some data for verification ---")
#     conn_verify = get_db_connection()
#     c_verify = conn_verify.cursor()
    
#     print("\nUsers:")
#     for row in c_verify.execute("SELECT * FROM users"):
#         print(dict(row))

#     print("\nQuiz Sessions:")
#     for row in c_verify.execute("SELECT * FROM quiz_sessions"):
#         print(dict(row))

#     print("\nQuestion Interactions:")
#     for row in c_verify.execute("SELECT * FROM question_interactions"):
#         print(dict(row))
        
#     conn_verify.close()

