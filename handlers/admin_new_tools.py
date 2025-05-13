"""Manages all database interactions for the Chemistry Telegram Bot.

Version 5 (Merged with V16 logic + fixes): 
- Incorporates fixes and additional statistics functions.
- Includes get_detailed_question_stats (assumes 'user_answers' table with 'quiz_id_uuid', 'question_id', 'is_correct', 'time_taken').
- Includes get_average_quiz_duration.
- Includes get_average_quizzes_per_active_user.
- Includes get_quiz_completion_rate_stats (returns dict).
"""

import psycopg2
import psycopg2.extras # For DictCursor
import logging
import random
import json # For storing details in JSONB
from datetime import datetime, timedelta # Added timedelta
import uuid # Added for generating UUIDs

# Import config, connection, and schema setup
try:
    from config import logger
    from .connection import connect_db # Assuming connection.py is in the same directory (database/)
except ImportError:
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error("Failed to import config or connection. DB Manager might not function correctly.")
    def connect_db(): # Dummy for fallback
        logger.error("Dummy connect_db called!")
        return None

class DatabaseManager:
    """Handles all database operations, including user data, quiz structure, and results."""

    def __init__(self):
        """Initializes the DatabaseManager."""
        logger.info("[DB Manager V5 Merged] Initialized.")

    def _execute_query(self, query, params=None, fetch_one=False, fetch_all=False, commit=False):
        """Helper function to execute database queries with connection handling."""
        conn = connect_db()
        if not conn:
            logger.error("[DB Manager V5 Merged] Failed to get database connection for query.")
            return None
        
        cur = None
        result = None
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute(query, params)

            if commit:
                conn.commit()
                logger.debug("[DB Manager V5 Merged] Query committed successfully.")
                result = True
            elif fetch_one:
                result = cur.fetchone()
                if result: result = dict(result) # Ensure it's a dict
            elif fetch_all:
                result_list = cur.fetchall()
                result = [dict(row) for row in result_list] if result_list else []
            
            return result
        except (Exception, psycopg2.DatabaseError) as error:
            try:
                failed_query = cur.mogrify(query, params) if cur else query
            except Exception as mogrify_error:
                logger.error(f"[DB Manager V5 Merged] Error formatting query for logging: {mogrify_error}")
                failed_query = query
            logger.error(f"[DB Manager V5 Merged] Database query error: {error}\nFailed Query (params might not be expanded): {failed_query}", exc_info=True)
            if conn:
                conn.rollback()
            return None
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    def register_or_update_user(self, user_id: int, first_name: str, last_name: str | None, username: str | None, language_code: str | None):
        logger.info(f"[DB User V5 Merged] Registering/updating user: id={user_id}, name={first_name}, username={username}")
        query = """
        INSERT INTO users (user_id, first_name, last_name, username, language_code, last_interaction_date)
        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (user_id)
        DO UPDATE SET
            first_name = EXCLUDED.first_name,
            last_name = EXCLUDED.last_name,
            username = EXCLUDED.username,
            language_code = EXCLUDED.language_code,
            last_interaction_date = CURRENT_TIMESTAMP;
        """
        params = (user_id, first_name, last_name, username, language_code)
        success = self._execute_query(query, params, commit=True)
        if success:
            logger.info(f"[DB User V5 Merged] Successfully registered/updated user {user_id}.")
        else:
            logger.error(f"[DB User V5 Merged] Failed to register/update user {user_id}.")
        return success

    def is_user_admin(self, user_id: int) -> bool:
        logger.debug(f"[DB User V5 Merged] Checking admin status for user {user_id}.")
        query = "SELECT is_admin FROM users WHERE user_id = %s;"
        result = self._execute_query(query, (user_id,), fetch_one=True)
        is_admin = result["is_admin"] if result and result.get("is_admin") is True else False
        logger.debug(f"[DB User V5 Merged] Admin status for user {user_id}: {is_admin}")
        return is_admin

    def get_all_courses(self):
        logger.info("[DB Content V5 Merged] Fetching all courses.")
        query = "SELECT course_id, name, description FROM courses ORDER BY course_id;"
        return self._execute_query(query, fetch_all=True)

    def get_units_by_course(self, course_id: int):
        logger.info(f"[DB Content V5 Merged] Fetching units for course_id: {course_id}")
        query = "SELECT unit_id, name, description FROM units WHERE course_id = %s ORDER BY unit_id;"
        return self._execute_query(query, (course_id,), fetch_all=True)

    def get_lessons_by_unit(self, unit_id: int):
        logger.info(f"[DB Content V5 Merged] Fetching lessons for unit_id: {unit_id}")
        query = "SELECT lesson_id, name, description FROM lessons WHERE unit_id = %s ORDER BY lesson_id;"
        return self._execute_query(query, (unit_id,), fetch_all=True)

    def get_question_count(self, scope_type: str, scope_id: int | None = None) -> int:
        logger.info(f"[DB Questions V5 Merged] Getting question count for type=\"{scope_type}\" id={scope_id}")
        base_query = "SELECT COUNT(*) as count FROM questions q "
        params = []
        
        if scope_type == "lesson" and scope_id is not None:
            where_clause = "WHERE q.lesson_id = %s"
            params.append(scope_id)
        elif scope_type == "unit" and scope_id is not None:
            base_query += "JOIN lessons l ON q.lesson_id = l.lesson_id "
            where_clause = "WHERE l.unit_id = %s"
            params.append(scope_id)
        elif scope_type == "course" and scope_id is not None:
            base_query += "JOIN lessons l ON q.lesson_id = l.lesson_id JOIN units u ON l.unit_id = u.unit_id "
            where_clause = "WHERE u.course_id = %s"
            params.append(scope_id)
        elif scope_type == "random" or scope_type == "all":
            where_clause = ""
        else:
            logger.warning(f"[DB Questions V5 Merged] Unknown scope_type for get_question_count: {scope_type}")
            return 0
            
        query = base_query + where_clause + ";"
        result = self._execute_query(query, tuple(params), fetch_one=True)
        count = result["count"] if result and "count" in result else 0
        logger.info(f"[DB Questions V5 Merged] Found {count} questions in DB for type=\"{scope_type}\" id={scope_id}")
        return count

    def start_quiz_session_and_get_id(self, user_id: int, quiz_type: str, quiz_scope_id: int | None, 
                                      quiz_name: str, total_questions: int, start_time: datetime, score: int, initial_percentage: float, initial_time_taken_seconds: int) -> str | None:
        logger.info(f"[DB Session V5 Merged] Starting new quiz session for user {user_id}, type: {quiz_type}, name: {quiz_name}, questions: {total_questions}")
        session_uuid = str(uuid.uuid4())
        query_insert_start = """
        INSERT INTO quiz_results (
            user_id, quiz_type, filter_id, quiz_name, total_questions, start_time, quiz_id_uuid, score, percentage, time_taken_seconds
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
        """
        params = (user_id, quiz_type, quiz_scope_id, quiz_name, total_questions, start_time, session_uuid, score, initial_percentage, initial_time_taken_seconds)
        success = self._execute_query(query_insert_start, params, commit=True)        
        if success:
            logger.info(f"[DB Session V5 Merged] Successfully started and logged quiz session {session_uuid} for user {user_id}.")
            return session_uuid
        else:
            logger.error(f"[DB Session V5 Merged] Failed to start and log quiz session for user {user_id}.")
            return None

    def end_quiz_session(self, 
                           quiz_session_uuid: str, 
                           score: int, 
                           wrong_answers: int, 
                           skipped_answers: int, 
                           score_percentage: float, 
                           completed_at: datetime, 
                           time_taken_seconds: int | None, 
                           answers_details_json: str,
                           ):
        logger.info(f"[DB Results V5 Merged] Ending quiz session {quiz_session_uuid}: Score={score}, Wrong={wrong_answers}, Skipped={skipped_answers}, Percentage={score_percentage:.2f}%")
        
        query_update_end = """
        UPDATE quiz_results 
        SET 
            score = %s, 
            wrong_answers = %s, 
            skipped_answers = %s,
            score_percentage = %s, 
            completed_at = %s, 
            time_taken_seconds = %s, 
            answers_details = %s::jsonb
        WHERE quiz_id_uuid = %s;
        """
        params = (score, wrong_answers, skipped_answers, score_percentage,
                  completed_at, time_taken_seconds, answers_details_json,
                  quiz_session_uuid)
        success = self._execute_query(query_update_end, params, commit=True)
        if success:
            logger.info(f"[DB Results V5 Merged] Successfully updated (ended) quiz session {quiz_session_uuid} in DB.")
        else:
            logger.error(f"[DB Results V5 Merged] Failed to update (end) quiz session {quiz_session_uuid} in DB.")
        return success

    def get_user_overall_stats(self, user_id: int):
        logger.info(f"[DB Stats V5 Merged] Fetching overall stats for user_id: {user_id}")
        query = """
        SELECT 
            COUNT(result_id) as total_quizzes_taken,
            COALESCE(SUM(score), 0) as total_correct_answers, 
            COALESCE(SUM(total_questions), 0) as total_questions_attempted,
            COALESCE(AVG(score_percentage), 0.0) as average_score_percentage,
            COALESCE(MAX(score_percentage), 0.0) as highest_score_percentage,
            COALESCE(SUM(time_taken_seconds), 0) as total_time_seconds
        FROM quiz_results
        WHERE user_id = %s AND completed_at IS NOT NULL;
        """
        stats = self._execute_query(query, (user_id,), fetch_one=True)
        logger.info(f"[DB Stats V5 Merged] Raw overall stats for user {user_id}: {stats}")
        if stats and stats.get("total_quizzes_taken", 0) > 0:
            logger.info(f"[DB Stats V5 Merged] Overall stats found for user {user_id}: {stats}")
            return stats 
        else:
            logger.warning(f"[DB Stats V5 Merged] No overall stats found for user {user_id} or query failed. Returning defaults.")
            return {
                "total_quizzes_taken": 0,
                "total_correct_answers": 0,
                "total_questions_attempted": 0,
                "average_score_percentage": 0.0,
                "highest_score_percentage": 0.0,
                "total_time_seconds": 0
            }

    def get_user_recent_quiz_history(self, user_id: int, limit: int = 5):
        logger.info(f"[DB Stats V5 Merged] Fetching recent quiz history for user_id: {user_id}, limit: {limit}")
        query = """
        SELECT 
            result_id,
            quiz_type,
            quiz_name, 
            total_questions,
            score, 
            score_percentage as percentage, 
            completed_at as completion_timestamp,
            answers_details,
            quiz_id_uuid
        FROM quiz_results
        WHERE user_id = %s AND completed_at IS NOT NULL
        ORDER BY completed_at DESC
        LIMIT %s;
        """ 
        history = self._execute_query(query, (user_id, limit), fetch_all=True)
        logger.info(f"[DB Stats V5 Merged] Raw recent quiz history for user {user_id} (limit {limit}): {history}")
        if history:
            logger.info(f"[DB Stats V5 Merged] Found {len(history)} recent quizzes for user {user_id}.")
        else:
            logger.warning(f"[DB Stats V5 Merged] No recent quiz history found for user {user_id} or query failed.")
            history = [] 
        return history

    def get_leaderboard(self, limit: int = 10):
        logger.info(f"[DB Stats V5 Merged] Fetching top {limit} users for leaderboard.")
        query = """
        SELECT 
            r.user_id,
            COALESCE(u.username, u.first_name, CAST(r.user_id AS VARCHAR)) as user_display_name,
            AVG(r.score_percentage) as average_score_percentage,
            COUNT(r.result_id) as total_quizzes_taken
        FROM quiz_results r
        LEFT JOIN users u ON r.user_id = u.user_id
        WHERE r.completed_at IS NOT NULL AND r.score_percentage IS NOT NULL
        GROUP BY r.user_id, u.username, u.first_name
        HAVING COUNT(r.result_id) > 0 
        ORDER BY average_score_percentage DESC, total_quizzes_taken DESC
        LIMIT %s;
        """
        leaderboard = self._execute_query(query, (limit,), fetch_all=True)
        logger.info(f"[DB Stats V5 Merged] Raw leaderboard data (limit {limit}): {leaderboard}")
        if leaderboard:
            logger.info(f"[DB Stats V5 Merged] Fetched {len(leaderboard)} users for leaderboard.")
        else:
            logger.warning("[DB Stats V5 Merged] No leaderboard data found or query failed.")
            leaderboard = []
        return leaderboard

    # --- Admin Statistics Functions ---
    def _get_time_filter_condition(self, time_filter="all", date_column="created_at"):
        """Helper to create WHERE clause for time filtering."""
        if time_filter == "today":
            return f" AND DATE({date_column}) = CURRENT_DATE "
        elif time_filter == "last_7_days":
            return f" AND {date_column} >= (CURRENT_DATE - INTERVAL '6 days') AND {date_column} < (CURRENT_DATE + INTERVAL '1 day') "
        elif time_filter == "last_30_days":
            return f" AND {date_column} >= (CURRENT_DATE - INTERVAL '29 days') AND {date_column} < (CURRENT_DATE + INTERVAL '1 day') "
        elif time_filter == "all_time" or time_filter == "all":
            return " " 
        else:
            logger.warning(f"[DB Admin Stats V5 Merged] Unknown time_filter: {time_filter}. Defaulting to 'all'.")
            return " "

    def get_total_users_count(self):
        logger.info("[DB Admin Stats V5 Merged] Fetching total users count.")
        query = "SELECT COUNT(user_id) as total_users FROM users;"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V5 Merged] Raw result for total_users_count: {raw_result}")
        return raw_result["total_users"] if raw_result and "total_users" in raw_result else 0

    def get_active_users_count(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V5 Merged] Fetching active users count for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "last_interaction_date")
        query = f"SELECT COUNT(DISTINCT user_id) as active_users FROM users WHERE 1=1 {time_condition};"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V5 Merged] Raw result for active_users_count ({time_filter}): {raw_result}")
        return raw_result["active_users"] if raw_result and "active_users" in raw_result else 0
        
    def get_total_quizzes_count(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V5 Merged] Fetching total quizzes taken for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"SELECT COUNT(result_id) as total_quizzes FROM quiz_results WHERE completed_at IS NOT NULL {time_condition};"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V5 Merged] Raw result for total_quizzes_count ({time_filter}): {raw_result}")
        return raw_result["total_quizzes"] if raw_result and "total_quizzes" in raw_result else 0

    def get_average_score_percentage(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V5 Merged] Fetching average score percentage for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"SELECT COALESCE(AVG(score_percentage), 0.0) as avg_score FROM quiz_results WHERE completed_at IS NOT NULL {time_condition};"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V5 Merged] Raw result for avg_score_percentage ({time_filter}): {raw_result}")
        avg_score = raw_result["avg_score"] if raw_result and "avg_score" in raw_result else 0.0
        return round(float(avg_score), 2) # Ensure float and round

    # Alias for dashboard compatibility if needed
    def get_overall_average_score(self, time_filter="all"):
        return self.get_average_score_percentage(time_filter)

    def get_score_distribution(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V5 Merged] Fetching score distribution for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        
        # Using CTE for robust grouping and ordering as in V23 logic
        query = f"""
        WITH ScoreRanges AS (
            SELECT 
                result_id,
                CASE 
                    WHEN score_percentage >= 90 THEN '90-100%'
                    WHEN score_percentage >= 80 THEN '80-89%'
                    WHEN score_percentage >= 70 THEN '70-79%'
                    WHEN score_percentage >= 60 THEN '60-69%'
                    WHEN score_percentage >= 50 THEN '50-59%'
                    ELSE '0-49%'
                END as score_range_category,
                CASE 
                    WHEN score_percentage >= 90 THEN 1
                    WHEN score_percentage >= 80 THEN 2
                    WHEN score_percentage >= 70 THEN 3
                    WHEN score_percentage >= 60 THEN 4
                    WHEN score_percentage >= 50 THEN 5
                    ELSE 6
                END as sort_order
            FROM quiz_results
            WHERE completed_at IS NOT NULL {time_condition}
        )
        SELECT 
            score_range_category as score_range,
            COUNT(result_id) as count
        FROM ScoreRanges
        GROUP BY score_range_category, sort_order
        ORDER BY sort_order ASC;
        """
        raw_result = self._execute_query(query, fetch_all=True)
        logger.info(f"[DB Admin Stats V5 Merged] Raw result for score_distribution ({time_filter}): {raw_result}")
        
        if raw_result is None: # Query failed
            return []
        if not raw_result: # No data
            # Return all ranges with 0 count if no data, for consistent display
            return [
                {"score_range": "90-100%", "count": 0},
                {"score_range": "80-89%", "count": 0},
                {"score_range": "70-79%", "count": 0},
                {"score_range": "60-69%", "count": 0},
                {"score_range": "50-59%", "count": 0},
                {"score_range": "0-49%", "count": 0}
            ]
        return raw_result # Already a list of dicts

    def get_average_quizzes_per_active_user(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V5 Merged] Fetching average quizzes per active user for filter: {time_filter}")
        total_quizzes = self.get_total_quizzes_count(time_filter)
        active_users = self.get_active_users_count(time_filter)
        
        if active_users > 0:
            avg_quizzes = total_quizzes / active_users
        else:
            avg_quizzes = 0.0
        logger.info(f"[DB Admin Stats V5 Merged] Avg quizzes per active user ({time_filter}): {avg_quizzes} (Total Quizzes: {total_quizzes}, Active Users: {active_users})")
        return round(avg_quizzes, 2)

    def get_quiz_completion_rate_stats(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V5 Merged] Fetching quiz completion rate stats for filter: {time_filter}")
        time_condition_completed = self._get_time_filter_condition(time_filter, "completed_at")
        time_condition_started = self._get_time_filter_condition(time_filter, "start_time") # Uses start_time from quiz_results

        query_completed = f"SELECT COUNT(result_id) as count FROM quiz_results WHERE completed_at IS NOT NULL {time_condition_completed};"
        # Assumes all entries in quiz_results are 'started'. If a quiz can be 'started' but not in quiz_results until later, this logic needs adjustment.
        query_started = f"SELECT COUNT(result_id) as count FROM quiz_results WHERE 1=1 {time_condition_started};"

        completed_result = self._execute_query(query_completed, fetch_one=True)
        started_result = self._execute_query(query_started, fetch_one=True)

        completed_quizzes = completed_result["count"] if completed_result and "count" in completed_result else 0
        started_quizzes = started_result["count"] if started_result and "count" in started_result else 0
        
        rate = 0.0
        if started_quizzes > 0:
            rate = (completed_quizzes / started_quizzes) * 100
        
        stats = {
            "completed_quizzes": completed_quizzes,
            "started_quizzes": started_quizzes,
            "completion_rate": round(rate, 2)
        }
        logger.info(f"[DB Admin Stats V5 Merged] Quiz completion stats ({time_filter}): {stats}")
        return stats

    def get_average_quiz_duration(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V5 Merged] Fetching average quiz duration for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"""
        SELECT COALESCE(AVG(time_taken_seconds), 0.0) as avg_duration
        FROM quiz_results 
        WHERE completed_at IS NOT NULL AND time_taken_seconds IS NOT NULL {time_condition};
        """
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V5 Merged] Raw result for avg_quiz_duration ({time_filter}): {raw_result}")
        avg_duration = raw_result["avg_duration"] if raw_result and "avg_duration" in raw_result else 0.0
        return round(float(avg_duration), 2) # Ensure float and round

    def get_detailed_question_stats(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V5 Merged] Fetching detailed question stats with time filter: {time_filter}")
        # Time condition applies to qr.completed_at for quizzes included in stats
        time_condition_sql = self._get_time_filter_condition(time_filter, date_column="qr.completed_at")

        # ASSUMPTIONS FOR THIS QUERY:
        # 1. A table 'user_answers' exists.
        # 2. 'user_answers' has columns: 'quiz_id_uuid' (FK to quiz_results.quiz_id_uuid),
        #    'question_id' (FK to questions.question_id), 'is_correct' (boolean), 'time_taken' (numeric/float, in seconds).
        # 3. A table 'questions' exists with 'question_id' (PK) and 'text' (for question_text).
        # If these assumptions are incorrect, this query will fail or return incorrect data.
        query = f"""
        SELECT
            qa.question_id,
            q.text AS question_text,
            COUNT(qa.question_id) AS times_answered,
            SUM(CASE WHEN qa.is_correct THEN 1 ELSE 0 END) AS times_correct,
            SUM(CASE WHEN NOT qa.is_correct THEN 1 ELSE 0 END) AS times_incorrect,
            ROUND(COALESCE(AVG(qa.time_taken), 0)::numeric, 2) AS avg_time_taken_seconds,
            CASE 
                WHEN COUNT(qa.question_id) > 0 THEN ROUND((SUM(CASE WHEN qa.is_correct THEN 1 ELSE 0 END) * 100.0 / COUNT(qa.question_id))::numeric, 2)
                ELSE 0.0 
            END AS correct_percentage
        FROM
            user_answers qa
        JOIN
            quiz_results qr ON qa.quiz_id_uuid = qr.quiz_id_uuid
        JOIN
            questions q ON qa.question_id = q.question_id
        WHERE
            qa.question_id IS NOT NULL AND qr.completed_at IS NOT NULL {time_condition_sql}
        GROUP BY
            qa.question_id, q.text
        ORDER BY
            correct_percentage ASC, times_answered DESC, qa.question_id ASC;
        """
        # Added qa.question_id to ORDER BY for deterministic sort on ties.
        
        logger.debug(f"[DB Admin Stats V5 Merged] Executing SQL query for detailed question stats: {{query}}") # Log actual query
        raw_result = self._execute_query(query, fetch_all=True)
        
        if raw_result is None: # _execute_query returns None on error
            logger.error(f"[DB Admin Stats V5 Merged] Error fetching detailed question stats for filter: {time_filter}. Query failed.")
            return []
        
        if not raw_result:
             logger.info(f"[DB Admin Stats V5 Merged] No detailed question stats found for filter: {time_filter}.")

        return raw_result # Already a list of dicts

    def get_all_user_ids_for_broadcast(self):
        logger.info(f"[DB Admin Stats V5 Merged] Fetching all user IDs for broadcast.")
        query = "SELECT user_id FROM users;" # Fetches all users
        raw_result = self._execute_query(query, fetch_all=True)
        if raw_result:
            user_ids = [row['user_id'] for row in raw_result]
            logger.info(f"[DB Admin Stats V5 Merged] Found {len(user_ids)} user IDs for broadcast: {user_ids}")
            return user_ids
        else:
            logger.warning("[DB Admin Stats V5 Merged] No user IDs found for broadcast or query failed.")
            return []

# Ensure DB_MANAGER instance is created for export, if this was the main manager file.
# This might be done in __init__.py of the database package usually.
DB_MANAGER = DatabaseManager()

