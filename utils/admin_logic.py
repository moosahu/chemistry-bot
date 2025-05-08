# admin_logic.py
import psycopg2
import psycopg2.extras # For DictCursor
import datetime

# Import connection details from db_setup
from database.db_setup import get_db_connection_string

def get_db_connection():
    """Establishes a connection to the PostgreSQL database."""
    conn_string = get_db_connection_string()
    conn = psycopg2.connect(conn_string)
    return conn

# --- Helper function for time filtering (PostgreSQL specific) ---
def get_time_filter_condition_pg(time_filter_str, timestamp_column_name):
    """Returns a SQL condition string for PostgreSQL based on the time filter."""
    if time_filter_str == "today":
        return f" AND DATE({timestamp_column_name}) = CURRENT_DATE "
    elif time_filter_str == "last_7_days":
        return f" AND {timestamp_column_name} >= CURRENT_DATE - INTERVAL '7 days' "
    elif time_filter_str == "last_30_days":
        return f" AND {timestamp_column_name} >= CURRENT_DATE - INTERVAL '30 days' "
    return "" # Default to all time (no additional condition)

# --- 1. Usage Overview Statistics --- 

def get_total_users(time_filter="all_time"):
    """Calculates the total number of unique users based on registration time."""
    conn = None
    total_users = 0
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # If time_filter is not 'all_time', it filters users by their first_seen_timestamp.
        # Otherwise, it counts all users ever registered.
        time_condition_str = get_time_filter_condition_pg(time_filter, "first_seen_timestamp")
        
        query = f"SELECT COUNT(DISTINCT user_id) as total_users FROM users WHERE 1=1 {time_condition_str}"
        cursor.execute(query)
        result = cursor.fetchone()
        if result and result["total_users"] is not None:
            total_users = result["total_users"]
    except psycopg2.Error as e:
        print(f"PostgreSQL error in get_total_users: {e}")
    finally:
        if conn:
            conn.close()
    return total_users

def get_active_users(time_filter="last_7_days"):
    """Calculates the number of active users within a given time period based on last_active_timestamp."""
    conn = None
    active_users = 0
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        time_condition_str = get_time_filter_condition_pg(time_filter, "last_active_timestamp")
            
        query = f"SELECT COUNT(DISTINCT user_id) as active_users FROM users WHERE 1=1 {time_condition_str}"
        cursor.execute(query)
        result = cursor.fetchone()
        if result and result["active_users"] is not None:
            active_users = result["active_users"]
    except psycopg2.Error as e:
        print(f"PostgreSQL error in get_active_users: {e}")
    finally:
        if conn:
            conn.close()
    return active_users

def get_total_quizzes_taken(time_filter="all_time"):
    """Calculates the total number of quiz sessions initiated."""
    conn = None
    total_quizzes = 0
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        time_condition_str = get_time_filter_condition_pg(time_filter, "start_timestamp")
        
        query = f"SELECT COUNT(quiz_session_id) as total_quizzes FROM quiz_sessions WHERE 1=1 {time_condition_str}"
        cursor.execute(query)
        result = cursor.fetchone()
        if result and result["total_quizzes"] is not None:
            total_quizzes = result["total_quizzes"]
    except psycopg2.Error as e:
        print(f"PostgreSQL error in get_total_quizzes_taken: {e}")
    finally:
        if conn:
            conn.close()
    return total_quizzes

def get_average_quizzes_per_user(time_filter="all_time"):
    """Calculates the average number of quizzes taken per user who took quizzes in the period."""
    conn = None
    average_quizzes = 0.0
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        time_condition_str = get_time_filter_condition_pg(time_filter, "start_timestamp")

        query = f"""
            SELECT 
                CASE 
                    WHEN COUNT(DISTINCT user_id) > 0 THEN CAST(COUNT(quiz_session_id) AS DECIMAL) / COUNT(DISTINCT user_id)
                    ELSE 0 
                END as avg_quizzes
            FROM quiz_sessions 
            WHERE 1=1 {time_condition_str}
        """
        cursor.execute(query)
        result = cursor.fetchone()
        if result and result["avg_quizzes"] is not None:
            average_quizzes = round(float(result["avg_quizzes"]), 2)
            
    except psycopg2.Error as e:
        print(f"PostgreSQL error in get_average_quizzes_per_user: {e}")
    finally:
        if conn:
            conn.close()
    return average_quizzes

# --- 2. Quiz Performance Statistics ---

def get_average_correct_answer_rate(time_filter="all_time", unit_id=None):
    """Calculates the average correct answer rate across all completed quizzes."""
    conn = None
    avg_rate = 0.0
    params = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        time_condition_str = get_time_filter_condition_pg(time_filter, "qs.start_timestamp")
        
        unit_condition_str = ""
        if unit_id:
            unit_condition_str = " AND qs.unit_id = %s "
            params.append(unit_id)

        query = f"""
            SELECT 
                CASE 
                    WHEN SUM(qs.total_questions_in_quiz) > 0 
                    THEN CAST(SUM(qs.score) AS DECIMAL) * 100.0 / SUM(qs.total_questions_in_quiz)
                    ELSE 0 
                END as avg_correct_rate
            FROM quiz_sessions qs
            WHERE qs.status = 'completed' AND qs.total_questions_in_quiz > 0 {time_condition_str} {unit_condition_str}
        """
        cursor.execute(query, tuple(params))
        result = cursor.fetchone()
        if result and result["avg_correct_rate"] is not None:
            avg_rate = round(float(result["avg_correct_rate"]), 2)
    except psycopg2.Error as e:
        print(f"PostgreSQL error in get_average_correct_answer_rate: {e}")
    finally:
        if conn:
            conn.close()
    return avg_rate

def get_popular_units(time_filter="all_time", limit=5):
    """Identifies the most popular units based on quiz count."""
    conn = None
    popular_units = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        time_condition_str = get_time_filter_condition_pg(time_filter, "start_timestamp")

        query = f"""
            SELECT unit_id, COUNT(quiz_session_id) as quiz_count
            FROM quiz_sessions
            WHERE 1=1 {time_condition_str}
            GROUP BY unit_id
            ORDER BY quiz_count DESC
            LIMIT %s
        """
        cursor.execute(query, (limit,))
        results = cursor.fetchall()
        for row in results:
            popular_units.append({"unit_id": row["unit_id"], "quiz_count": row["quiz_count"]})
    except psycopg2.Error as e:
        print(f"PostgreSQL error in get_popular_units: {e}")
    finally:
        if conn:
            conn.close()
    return popular_units

def get_difficulty_units(time_filter="all_time", limit=5, easiest=False):
    """Identifies the most difficult or easiest units based on average score."""
    conn = None
    difficulty_units = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        time_condition_str = get_time_filter_condition_pg(time_filter, "start_timestamp")
        order_direction = "ASC" if not easiest else "DESC"

        query = f"""
            SELECT 
                unit_id, 
                CASE 
                    WHEN SUM(total_questions_in_quiz) > 0 
                    THEN CAST(SUM(score) AS DECIMAL) * 100.0 / SUM(total_questions_in_quiz)
                    ELSE NULL 
                END as avg_score_percent
            FROM quiz_sessions
            WHERE status = 'completed' AND total_questions_in_quiz > 0 {time_condition_str}
            GROUP BY unit_id
            HAVING SUM(total_questions_in_quiz) > 0 -- Ensure we don't divide by zero and only consider units with valid quiz data
            ORDER BY avg_score_percent {order_direction}
            LIMIT %s
        """
        cursor.execute(query, (limit,))
        results = cursor.fetchall()
        for row in results:
            if row["avg_score_percent"] is not None:
                 difficulty_units.append({"unit_id": row["unit_id"], "average_score_percent": round(float(row["avg_score_percent"]),2)})
    except psycopg2.Error as e:
        print(f"PostgreSQL error in get_difficulty_units: {e}")
    finally:
        if conn:
            conn.close()
    return difficulty_units

# --- 3. User Interaction Statistics ---

def get_average_quiz_completion_time(time_filter="all_time", unit_id=None):
    """Calculates the average time taken to complete quizzes in seconds."""
    conn = None
    avg_time_seconds = 0
    params = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        time_condition_str = get_time_filter_condition_pg(time_filter, "start_timestamp")

        unit_condition_str = ""
        if unit_id:
            unit_condition_str = " AND unit_id = %s "
            params.append(unit_id)

        query = f"""
            SELECT AVG(EXTRACT(EPOCH FROM (end_timestamp - start_timestamp))) as avg_duration_seconds
            FROM quiz_sessions
            WHERE status = 'completed' AND end_timestamp IS NOT NULL AND start_timestamp IS NOT NULL {time_condition_str} {unit_condition_str}
        """
        cursor.execute(query, tuple(params))
        result = cursor.fetchone()
        if result and result["avg_duration_seconds"] is not None:
            avg_time_seconds = round(float(result["avg_duration_seconds"]))
    except psycopg2.Error as e:
        print(f"PostgreSQL error in get_average_quiz_completion_time: {e}")
    finally:
        if conn:
            conn.close()
    return avg_time_seconds

def get_quiz_completion_rate(time_filter="all_time", unit_id=None):
    """Calculates the percentage of quizzes that were completed versus started."""
    conn = None
    completion_rate = 0.0
    params = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        time_condition_str = get_time_filter_condition_pg(time_filter, "start_timestamp")

        unit_condition_str = ""
        if unit_id:
            unit_condition_str = " AND unit_id = %s "
            params.append(unit_id)

        query = f"""
            SELECT 
                CASE 
                    WHEN COUNT(quiz_session_id) > 0 THEN CAST(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS DECIMAL) * 100.0 / COUNT(quiz_session_id)
                    ELSE 0
                END as rate
            FROM quiz_sessions
            WHERE 1=1 {time_condition_str} {unit_condition_str}
        """
        cursor.execute(query, tuple(params))
        result = cursor.fetchone()
        if result and result["rate"] is not None:
            completion_rate = round(float(result["rate"]), 2)
    except psycopg2.Error as e:
        print(f"PostgreSQL error in get_quiz_completion_rate: {e}")
    finally:
        if conn:
            conn.close()
    return completion_rate

# --- 4. Question Statistics ---

def get_question_difficulty(time_filter="all_time", limit=5, easiest=False):
    """Identifies the most difficult or easiest questions based on correct answer percentage."""
    conn = None
    questions_difficulty = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        time_condition_str = get_time_filter_condition_pg(time_filter, "qi.answer_timestamp")
        order_direction = "ASC" if not easiest else "DESC"

        query = f"""
            SELECT 
                qi.question_id, 
                CASE 
                    WHEN COUNT(qi.question_id) > 0 THEN CAST(SUM(CASE WHEN qi.is_correct THEN 1 ELSE 0 END) AS DECIMAL) * 100.0 / COUNT(qi.question_id)
                    ELSE 0 
                END as correct_percentage
            FROM question_interactions qi
            WHERE 1=1 {time_condition_str}
            GROUP BY qi.question_id
            HAVING COUNT(qi.question_id) > 0
            ORDER BY correct_percentage {order_direction}, COUNT(qi.question_id) DESC -- Added secondary sort by count for tie-breaking
            LIMIT %s
        """
        cursor.execute(query, (limit,))
        results = cursor.fetchall()
        for row in results:
            questions_difficulty.append({"question_id": row["question_id"], "correct_percentage": round(float(row["correct_percentage"]), 2)})
    except psycopg2.Error as e:
        print(f"PostgreSQL error in get_question_difficulty: {e}")
    finally:
        if conn:
            conn.close()
    return questions_difficulty

if __name__ == '__main__':
    # This is for direct testing of admin_logic.py with PostgreSQL
    # Ensure db_setup.py has created tables in your PostgreSQL database.
    # You might also want to run data_logger.py's __main__ section to populate some test data.

    print("--- Testing Admin Logic with PostgreSQL ---")

    print(f"Total Users (all time): {get_total_users('all_time')}")
    print(f"Total Users (today): {get_total_users('today')}")
    print(f"Active Users (last 7 days): {get_active_users('last_7_days')}")
    print(f"Active Users (today): {get_active_users('today')}")
    print(f"Total Quizzes Taken (all time): {get_total_quizzes_taken('all_time')}")
    print(f"Total Quizzes Taken (last 30 days): {get_total_quizzes_taken('last_30_days')}")
    print(f"Average Quizzes Per User (all time): {get_average_quizzes_per_user('all_time')}")
    
    print(f"\nAverage Correct Answer Rate (all time): {get_average_correct_answer_rate('all_time')}")
    print(f"Average Correct Answer Rate (Unit1_PG_Math, all time): {get_average_correct_answer_rate('all_time', 'Unit1_PG_Math')}")
    
    popular_units_all = get_popular_units('all_time', 3)
    print(f"\nMost Popular Units (all time, top 3): {popular_units_all}")
    popular_units_today = get_popular_units('today', 3)
    print(f"Most Popular Units (today, top 3): {popular_units_today}")

    hardest_units = get_difficulty_units('all_time', 3, easiest=False)
    print(f"\nMost Difficult Units (all time, top 3): {hardest_units}")
    easiest_units = get_difficulty_units('all_time', 3, easiest=True)
    print(f"Easiest Units (all time, top 3): {easiest_units}")

    print(f"\nAverage Quiz Completion Time (all time): {get_average_quiz_completion_time('all_time')} seconds")
    print(f"Average Quiz Completion Time (Unit1_PG_Math): {get_average_quiz_completion_time('all_time', 'Unit1_PG_Math')} seconds")
    
    print(f"\nQuiz Completion Rate (all time): {get_quiz_completion_rate('all_time')}%")
    print(f"Quiz Completion Rate (last 7 days): {get_quiz_completion_rate('last_7_days')}%")

    hardest_questions = get_question_difficulty('all_time', 3, easiest=False)
    print(f"\nMost Difficult Questions (all time, top 3): {hardest_questions}")
    easiest_questions = get_question_difficulty('all_time', 3, easiest=True)
    print(f"Easiest Questions (all time, top 3): {easiest_questions}")

    print("\n--- Admin Logic Test Finished ---")

