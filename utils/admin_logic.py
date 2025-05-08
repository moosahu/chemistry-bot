# admin_logic.py
import sqlite3
import datetime

DB_NAME = "database/bot_stats.db" # <-- MODIFIED HERE

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row # Allows accessing columns by name
    return conn

# --- Helper function for time filtering (to be implemented later) ---
def get_time_filter_condition(time_filter_str):
    """Returns a SQL condition string based on the time filter."""
    # Placeholder for now, will be developed in Stage 5 (Time Filtering)
    # Examples: " AND date_column >= date('now', '-7 days')"
    # For 'all_time', it will return an empty string.
    if time_filter_str == "today":
        return " AND DATE(users.last_active_timestamp) = DATE('now') " # Example for users table
    elif time_filter_str == "last_7_days":
        return " AND users.last_active_timestamp >= date('now', '-7 days') "
    elif time_filter_str == "last_30_days":
        return " AND users.last_active_timestamp >= date('now', '-30 days') "
    return "" # Default to all time

# --- 1. Usage Overview Statistics --- 

def get_total_users(time_filter="all_time"):
    """Calculates the total number of unique users."""
    # Note: time_filter for total users might mean users registered in that period,
    # or users active in that period. For now, let's count all users ever registered
    # if time_filter is 'all_time', or active users if a filter is applied.
    conn = get_db_connection()
    cursor = conn.cursor()
    total_users = 0
    try:
        # If we want total registered users, time filter on first_seen_timestamp
        # If we want total *active* users in period, time filter on last_active_timestamp
        # The current todo.md implies "إجمالي المستخدمين" is just the grand total.
        # "المستخدمون النشطون" is a separate metric.
        query = "SELECT COUNT(DISTINCT user_id) as total_users FROM users"
        # For now, total_users will ignore time_filter, as it usually means overall total.
        # Active users will use the time_filter.
        cursor.execute(query)
        result = cursor.fetchone()
        if result and result["total_users"] is not None:
            total_users = result["total_users"]
    except sqlite3.Error as e:
        print(f"SQLite error in get_total_users: {e}")
    finally:
        conn.close()
    return total_users

# More functions for other statistics will be added here.

# --- Example Usage (for testing this file directly) ---
# if __name__ == '__main__':
#     # Ensure db_setup.py has been run and data_logger.py has populated some data
#     # from db_setup import create_connection as cs_conn, create_tables as cs_tables
#     # conn_s = cs_conn()
#     # if conn_s: cs_tables(conn_s); conn_s.close()
#     # import data_logger
#     # data_logger.log_user_activity(1, "userA")
#     # data_logger.log_user_activity(2, "userB")
#     # data_logger.log_quiz_start(1, "U1", 10)

#     total_users_count = get_total_users()
#     print(f"Total Users: {total_users_count}")




def get_active_users(time_filter="last_7_days"):
    """Calculates the number of active users within a given time period."""
    conn = get_db_connection()
    cursor = conn.cursor()
    active_users = 0
    try:
        # Default to users active in the last 7 days if no specific filter is given for this metric
        # The time_filter_condition needs to be adapted for the 'users' table and 'last_active_timestamp'
        # For this specific function, let's construct the condition directly for clarity.
        
        # Determine the date condition based on the time_filter string
        date_condition = ""
        if time_filter == "today":
            date_condition = " DATE(last_active_timestamp) = DATE('now') "
        elif time_filter == "last_7_days":
            date_condition = " last_active_timestamp >= date('now', '-7 days') "
        elif time_filter == "last_30_days":
            date_condition = " last_active_timestamp >= date('now', '-30 days') "
        elif time_filter == "all_time": # All users who have ever been active
             date_condition = " 1=1 " # Or simply no WHERE clause if that's the definition
        else: # Default to last 7 days if an unrecognized filter is passed
            date_condition = " last_active_timestamp >= date('now', '-7 days') "
            
        query = f"SELECT COUNT(DISTINCT user_id) as active_users FROM users WHERE {date_condition}"
        cursor.execute(query)
        result = cursor.fetchone()
        if result and result["active_users"] is not None:
            active_users = result["active_users"]
    except sqlite3.Error as e:
        print(f"SQLite error in get_active_users: {e}")
    finally:
        conn.close()
    return active_users

def get_total_quizzes_taken(time_filter="all_time"):
    """Calculates the total number of quiz sessions initiated."""
    conn = get_db_connection()
    cursor = conn.cursor()
    total_quizzes = 0
    try:
        time_condition_str = ""
        if time_filter == "today":
            time_condition_str = " AND DATE(start_timestamp) = DATE('now') "
        elif time_filter == "last_7_days":
            time_condition_str = " AND start_timestamp >= date('now', '-7 days') "
        elif time_filter == "last_30_days":
            time_condition_str = " AND start_timestamp >= date('now', '-30 days') "
        
        query = f"SELECT COUNT(quiz_session_id) as total_quizzes FROM quiz_sessions WHERE 1=1 {time_condition_str}"
        cursor.execute(query)
        result = cursor.fetchone()
        if result and result["total_quizzes"] is not None:
            total_quizzes = result["total_quizzes"]
    except sqlite3.Error as e:
        print(f"SQLite error in get_total_quizzes_taken: {e}")
    finally:
        conn.close()
    return total_quizzes

def get_average_quizzes_per_user(time_filter="all_time"):
    """Calculates the average number of quizzes taken per user."""
    # This can be tricky with time filters. 
    # Does it mean average quizzes for users active in this period?
    # Or average quizzes taken in this period by users who took quizzes in this period?
    # For now, let's calculate: (total quizzes in period) / (users who took at least one quiz in period)
    conn = get_db_connection()
    cursor = conn.cursor()
    average_quizzes = 0
    try:
        time_condition_str = ""
        if time_filter == "today":
            time_condition_str = " AND DATE(start_timestamp) = DATE('now') "
        elif time_filter == "last_7_days":
            time_condition_str = " AND start_timestamp >= date('now', '-7 days') "
        elif time_filter == "last_30_days":
            time_condition_str = " AND start_timestamp >= date('now', '-30 days') "

        query = f"""
            SELECT 
                CAST(COUNT(quiz_session_id) AS REAL) / COUNT(DISTINCT user_id) as avg_quizzes
            FROM quiz_sessions 
            WHERE 1=1 {time_condition_str}
        """
        cursor.execute(query)
        result = cursor.fetchone()
        if result and result["avg_quizzes"] is not None:
            average_quizzes = round(result["avg_quizzes"], 2)
        elif time_filter != "all_time": # If there are no quizzes in the period, the avg is 0
             # Check if any quizzes at all for the period, if not, result might be None or division by zero if not handled by SQL
            cursor.execute(f"SELECT COUNT(quiz_session_id) as count FROM quiz_sessions WHERE 1=1 {time_condition_str}")
            if cursor.fetchone()['count'] == 0:
                average_quizzes = 0
        else: # all_time, and still no quizzes (empty db)
            average_quizzes = 0
            
    except sqlite3.Error as e:
        print(f"SQLite error in get_average_quizzes_per_user: {e}")
    finally:
        conn.close()
    return average_quizzes

# --- 2. Quiz Performance Statistics ---

def get_average_correct_answer_rate(time_filter="all_time", unit_id=None):
    """Calculates the average correct answer rate across all completed quizzes, optionally filtered by unit."""
    conn = get_db_connection()
    cursor = conn.cursor()
    avg_rate = 0.0
    try:
        time_condition_str = ""
        if time_filter == "today":
            time_condition_str = " AND DATE(qs.start_timestamp) = DATE('now') "
        elif time_filter == "last_7_days":
            time_condition_str = " AND qs.start_timestamp >= date('now', '-7 days') "
        elif time_filter == "last_30_days":
            time_condition_str = " AND qs.start_timestamp >= date('now', '-30 days') "
        
        unit_condition_str = ""
        if unit_id:
            unit_condition_str = f" AND qs.unit_id = '{unit_id}' " # Ensure unit_id is sanitized if user-provided

        # Calculates based on score / total_questions_in_quiz for completed quizzes
        # SUM(score) / SUM(total_questions_in_quiz) gives a weighted average.
        query = f"""
            SELECT 
                CASE 
                    WHEN SUM(qs.total_questions_in_quiz) > 0 
                    THEN CAST(SUM(qs.score) AS REAL) * 100.0 / SUM(qs.total_questions_in_quiz)
                    ELSE 0 
                END as avg_correct_rate
            FROM quiz_sessions qs
            WHERE qs.status = 'completed' AND qs.total_questions_in_quiz > 0 {time_condition_str} {unit_condition_str}
        """
        cursor.execute(query)
        result = cursor.fetchone()
        if result and result["avg_correct_rate"] is not None:
            avg_rate = round(result["avg_correct_rate"], 2)
    except sqlite3.Error as e:
        print(f"SQLite error in get_average_correct_answer_rate: {e}")
    finally:
        conn.close()
    return avg_rate

def get_popular_units(time_filter="all_time", limit=5):
    """Identifies the most popular units based on the number of times quizzes for them were taken."""
    conn = get_db_connection()
    cursor = conn.cursor()
    popular_units = []
    try:
        time_condition_str = ""
        if time_filter == "today":
            time_condition_str = " AND DATE(start_timestamp) = DATE('now') "
        elif time_filter == "last_7_days":
            time_condition_str = " AND start_timestamp >= date('now', '-7 days') "
        elif time_filter == "last_30_days":
            time_condition_str = " AND start_timestamp >= date('now', '-30 days') "

        query = f"""
            SELECT unit_id, COUNT(quiz_session_id) as quiz_count
            FROM quiz_sessions
            WHERE 1=1 {time_condition_str}
            GROUP BY unit_id
            ORDER BY quiz_count DESC
            LIMIT ?
        """
        cursor.execute(query, (limit,))
        results = cursor.fetchall()
        for row in results:
            popular_units.append({"unit_id": row["unit_id"], "quiz_count": row["quiz_count"]})
    except sqlite3.Error as e:
        print(f"SQLite error in get_popular_units: {e}")
    finally:
        conn.close()
    return popular_units

def get_difficulty_units(time_filter="all_time", limit=5, easiest=False):
    """Identifies the most difficult or easiest units based on average correct answer rate."""
    conn = get_db_connection()
    cursor = conn.cursor()
    difficulty_units = []
    try:
        time_condition_str = ""
        if time_filter == "today":
            time_condition_str = " AND DATE(start_timestamp) = DATE('now') "
        elif time_filter == "last_7_days":
            time_condition_str = " AND start_timestamp >= date('now', '-7 days') "
        elif time_filter == "last_30_days":
            time_condition_str = " AND start_timestamp >= date('now', '-30 days') "
        
        order_direction = "ASC" if not easiest else "DESC"

        query = f"""
            SELECT 
                unit_id, 
                CASE 
                    WHEN SUM(total_questions_in_quiz) > 0 
                    THEN CAST(SUM(score) AS REAL) * 100.0 / SUM(total_questions_in_quiz)
                    ELSE NULL 
                END as avg_score_percent
            FROM quiz_sessions
            WHERE status = 'completed' AND total_questions_in_quiz > 0 {time_condition_str}
            GROUP BY unit_id
            HAVING avg_score_percent IS NOT NULL
            ORDER BY avg_score_percent {order_direction}
            LIMIT ?
        """
        cursor.execute(query, (limit,))
        results = cursor.fetchall()
        for row in results:
            difficulty_units.append({"unit_id": row["unit_id"], "average_score_percent": round(row["avg_score_percent"],2)})
    except sqlite3.Error as e:
        print(f"SQLite error in get_difficulty_units: {e}")
    finally:
        conn.close()
    return difficulty_units

# --- 3. User Interaction Statistics ---

def get_average_quiz_completion_time(time_filter="all_time", unit_id=None):
    """Calculates the average time taken to complete quizzes in seconds."""
    conn = get_db_connection()
    cursor = conn.cursor()
    avg_time_seconds = 0
    try:
        time_condition_str = ""
        # For time difference, ensure timestamps are correctly formatted for julianday or strftime
        # SQLite's julianday difference is in days. Multiply by 24*60*60 for seconds.
        if time_filter == "today":
            time_condition_str = " AND DATE(start_timestamp) = DATE('now') "
        elif time_filter == "last_7_days":
            time_condition_str = " AND start_timestamp >= date('now', '-7 days') "
        elif time_filter == "last_30_days":
            time_condition_str = " AND start_timestamp >= date('now', '-30 days') "

        unit_condition_str = ""
        if unit_id:
            unit_condition_str = f" AND unit_id = '{unit_id}' "

        query = f"""
            SELECT AVG((julianday(end_timestamp) - julianday(start_timestamp)) * 86400.0) as avg_duration_seconds
            FROM quiz_sessions
            WHERE status = 'completed' AND end_timestamp IS NOT NULL {time_condition_str} {unit_condition_str}
        """
        cursor.execute(query)
        result = cursor.fetchone()
        if result and result["avg_duration_seconds"] is not None:
            avg_time_seconds = round(result["avg_duration_seconds"])
    except sqlite3.Error as e:
        print(f"SQLite error in get_average_quiz_completion_time: {e}")
    finally:
        conn.close()
    return avg_time_seconds

def get_quiz_completion_rate(time_filter="all_time", unit_id=None):
    """Calculates the percentage of quizzes that were completed versus started."""
    conn = get_db_connection()
    cursor = conn.cursor()
    completion_rate = 0.0
    try:
        time_condition_str = ""
        if time_filter == "today":
            time_condition_str = " AND DATE(start_timestamp) = DATE('now') "
        elif time_filter == "last_7_days":
            time_condition_str = " AND start_timestamp >= date('now', '-7 days') "
        elif time_filter == "last_30_days":
            time_condition_str = " AND start_timestamp >= date('now', '-30 days') "

        unit_condition_str = ""
        if unit_id:
            unit_condition_str = f" AND unit_id = '{unit_id}' "

        query = f"""
            SELECT 
                CAST(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS REAL) * 100.0 / COUNT(quiz_session_id) as rate
            FROM quiz_sessions
            WHERE 1=1 {time_condition_str} {unit_condition_str}
        """
        cursor.execute(query)
        result = cursor.fetchone()
        if result and result["rate"] is not None:
            completion_rate = round(result["rate"], 2)
    except sqlite3.Error as e:
        print(f"SQLite error in get_quiz_completion_rate: {e}")
    finally:
        conn.close()
    return completion_rate

# --- 4. Question Statistics ---

def get_question_difficulty(time_filter="all_time", limit=5, easiest=False):
    """Identifies the most difficult or easiest questions based on correct answer percentage."""
    conn = get_db_connection()
    cursor = conn.cursor()
    questions_difficulty = []
    try:
        time_condition_str = ""
        if time_filter == "today":
            time_condition_str = " AND DATE(qi.answer_timestamp) = DATE('now') " # Assuming qi for question_interactions
        elif time_filter == "last_7_days":
            time_condition_str = " AND qi.answer_timestamp >= date('now', '-7 days') "
        elif time_filter == "last_30_days":
            time_condition_str = " AND qi.answer_timestamp >= date('now', '-30 days') "

        order_direction = "ASC" if not easiest else "DESC"

        query = f"""
            SELECT 
                qi.question_id, 
                CAST(SUM(CASE WHEN qi.is_correct THEN 1 ELSE 0 END) AS REAL) * 100.0 / COUNT(qi.question_id) as correct_percentage
            FROM question_interactions qi
            WHERE 1=1 {time_condition_str}
            GROUP BY qi.question_id
            HAVING COUNT(qi.question_id) > 0 -- Ensure we only consider questions with interactions
            ORDER BY correct_percentage {order_direction}
            LIMIT ?
        """
        cursor.execute(query, (limit,))
        results = cursor.fetchall()
        for row in results:
            questions_difficulty.append({"question_id": row["question_id"], "correct_percentage": round(row["correct_percentage"], 2)})
    except sqlite3.Error as e:
        print(f"SQLite error in get_question_difficulty: {e}")
    finally:
        conn.close()
    return questions_difficulty

