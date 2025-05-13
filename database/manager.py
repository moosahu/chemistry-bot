"""Manages all database interactions for the Chemistry Telegram Bot.

Version 16 (Merged): This version combines the functionalities of v5 and v16,
retaining the fixes, cleanups, and new features introduced in v16.
It includes detailed logging for admin statistics (from v5's intent, refined in v16)
and new admin statistics functions.
"""

import psycopg2
import psycopg2.extras # For DictCursor
import logging
import random # Still present, though not actively used in the provided snippets
import json # For storing details in JSONB
from datetime import datetime, timedelta
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
        # Retained V5 initialization message as it's consistent in both versions
        logger.info("[DB Manager V5] Initialized.")

    def _execute_query(self, query, params=None, fetch_one=False, fetch_all=False, commit=False):
        """Helper function to execute database queries with connection handling.
        This version reflects the cleaned-up logging from v16.
        """
        conn = connect_db()
        if not conn:
            # Retained V5 error message as it's consistent
            logger.error("[DB Manager V5] Failed to get database connection for query.")
            return None
        
        cur = None
        result = None
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute(query, params)

            if commit:
                conn.commit()
                # Retained V5 debug message
                logger.debug("[DB Manager V5] Query committed successfully.")
                result = True
            elif fetch_one:
                result = cur.fetchone()
                # Cleaned: No verbose raw result logging by default (as in v16)
                if result: result = dict(result) 
            elif fetch_all:
                result_list = cur.fetchall()
                # Cleaned: No verbose raw result logging by default (as in v16)
                result = [dict(row) for row in result_list] if result_list else []
            
            return result
        except (Exception, psycopg2.DatabaseError) as error:
            try:
                failed_query = cur.mogrify(query, params) if cur else query
            except Exception as mogrify_error:
                # Retained V5 error message
                logger.error(f"[DB Manager V5] Error formatting query for logging: {mogrify_error}")
                failed_query = query
            # Retained V5 error message format
            logger.error(f"[DB Manager V5] Database query error: {error}\nFailed Query (params might not be expanded): {failed_query}", exc_info=True)
            if conn:
                conn.rollback()
            return None
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    # --- User Management --- 
    def register_or_update_user(self, user_id: int, first_name: str, last_name: str | None, username: str | None, language_code: str | None):
        # Logic identical in v5 and v16. Using v16's (which is same as v5).
        logger.info(f"[DB User V5] Registering/updating user: id={user_id}, name={first_name}, username={username}")
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
            logger.info(f"[DB User V5] Successfully registered/updated user {user_id}.")
        else:
            logger.error(f"[DB User V5] Failed to register/update user {user_id}.")
        return success

    def is_user_admin(self, user_id: int) -> bool:
        # Logic identical in v5 and v16.
        logger.debug(f"[DB User V5] Checking admin status for user {user_id}.")
        query = "SELECT is_admin FROM users WHERE user_id = %s;"
        result = self._execute_query(query, (user_id,), fetch_one=True)
        is_admin = result["is_admin"] if result and result.get("is_admin") is True else False
        logger.debug(f"[DB User V5] Admin status for user {user_id}: {is_admin}")
        return is_admin

    # --- Content Retrieval --- 
    def get_all_courses(self):
        # Logic identical in v5 and v16.
        logger.info("[DB Content V5] Fetching all courses.")
        query = "SELECT course_id, name, description FROM courses ORDER BY course_id;"
        return self._execute_query(query, fetch_all=True)

    def get_units_by_course(self, course_id: int):
        # Logic identical in v5 and v16.
        logger.info(f"[DB Content V5] Fetching units for course_id: {course_id}")
        query = "SELECT unit_id, name, description FROM units WHERE course_id = %s ORDER BY unit_id;"
        return self._execute_query(query, (course_id,), fetch_all=True)

    def get_lessons_by_unit(self, unit_id: int):
        # Logic identical in v5 and v16.
        logger.info(f"[DB Content V5] Fetching lessons for unit_id: {unit_id}")
        query = "SELECT lesson_id, name, description FROM lessons WHERE unit_id = %s ORDER BY lesson_id;"
        return self._execute_query(query, (unit_id,), fetch_all=True)

    def get_question_count(self, scope_type: str, scope_id: int | None = None) -> int:
        # Logic identical in v5 and v16.
        logger.info(f"[DB Questions V5] Getting question count for type=\"{scope_type}\" id={scope_id}")
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
            logger.warning(f"[DB Questions V5] Unknown scope_type for get_question_count: {scope_type}")
            return 0
            
        query = base_query + where_clause + ";"
        result = self._execute_query(query, tuple(params), fetch_one=True)
        count = result["count"] if result and "count" in result else 0
        logger.info(f"[DB Questions V5] Found {count} questions in DB for type=\"{scope_type}\" id={scope_id}")
        return count

    # --- Quiz Session Management --- 
    def start_quiz_session_and_get_id(self, user_id: int, quiz_type: str, quiz_scope_id: int | None, 
                                      quiz_name: str, total_questions: int, start_time: datetime, 
                                      score: int, initial_percentage: float, initial_time_taken_seconds: int) -> str | None:
        # Logic identical in v5 and v16.
        logger.info(f"[DB Session V5] Starting new quiz session for user {user_id}, type: {quiz_type}, name: {quiz_name}, questions: {total_questions}")
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
            logger.info(f"[DB Session V5] Successfully started and logged quiz session {session_uuid} for user {user_id}.")
            return session_uuid
        else:
            logger.error(f"[DB Session V5] Failed to start and log quiz session for user {user_id}.")
            return None

    def end_quiz_session(self, 
                           quiz_session_uuid: str, 
                           score: int, 
                           wrong_answers: int, 
                           skipped_answers: int, 
                           score_percentage: float, 
                           completed_at: datetime, 
                           time_taken_seconds: int | None, 
                           answers_details_json: str):
        # Logic identical in v5 and v16.
        logger.info(f"[DB Results V5] Ending quiz session {quiz_session_uuid}: Score={score}, Wrong={wrong_answers}, Skipped={skipped_answers}, Percentage={score_percentage:.2f}%")
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
            logger.info(f"[DB Results V5] Successfully updated (ended) quiz session {quiz_session_uuid} in DB.")
        else:
            logger.error(f"[DB Results V5] Failed to update (end) quiz session {quiz_session_uuid} in DB.")
        return success

    # --- User Statistics --- 
    def get_user_overall_stats(self, user_id: int):
        # Logic identical in v5 and v16. v5 included more detailed logging of raw stats.
        # Retaining the v5 logging for this specific function as it was part of its debug purpose.
        logger.info(f"[DB Stats V5] Fetching overall stats for user_id: {user_id}")
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
        logger.info(f"[DB Stats V5] Raw overall stats for user {user_id}: {stats}") # Retained from v5 for debug insight
        if stats and stats.get("total_quizzes_taken", 0) > 0:
            logger.info(f"[DB Stats V5] Overall stats found for user {user_id}: {stats}")
            return stats 
        else:
            logger.warning(f"[DB Stats V5] No overall stats found for user {user_id} or query failed. Returning defaults.")
            return {
                "total_quizzes_taken": 0,
                "total_correct_answers": 0,
                "total_questions_attempted": 0,
                "average_score_percentage": 0.0,
                "highest_score_percentage": 0.0,
                "total_time_seconds": 0
            }

    def get_user_recent_quiz_history(self, user_id: int, limit: int = 5):
        # Logic identical in v5 and v16. v5 included more detailed logging of raw history.
        # Retaining the v5 logging for this specific function.
        logger.info(f"[DB Stats V5] Fetching recent quiz history for user_id: {user_id}, limit: {limit}")
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
        logger.info(f"[DB Stats V5] Raw recent quiz history for user {user_id} (limit {limit}): {history}") # Retained from v5
        if history:
            logger.info(f"[DB Stats V5] Found {len(history)} recent quizzes for user {user_id}.")
        else:
            logger.warning(f"[DB Stats V5] No recent quiz history found for user {user_id} or query failed.")
            history = [] 
        return history

    def get_leaderboard(self, limit: int = 10):
        # Logic identical in v5 and v16. v5 included more detailed logging of raw data.
        # Retaining the v5 logging for this specific function.
        logger.info(f"[DB Stats V5] Fetching top {limit} users for leaderboard.")
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
        logger.info(f"[DB Stats V5] Raw leaderboard data (limit {limit}): {leaderboard}") # Retained from v5
        if leaderboard:
            logger.info(f"[DB Stats V5] Fetched {len(leaderboard)} users for leaderboard.")
        else:
            logger.warning("[DB Stats V5] No leaderboard data found or query failed.")
            leaderboard = []
        return leaderboard

    # --- Admin Statistics Functions (Incorporating v16 enhancements and completions) ---
    def _get_time_filter_condition(self, time_filter="all", date_column="created_at"):
        """Helper to create WHERE clause for time filtering. Consistent in both versions."""
        if time_filter == "today":
            return f" AND DATE({date_column}) = CURRENT_DATE "
        elif time_filter == "last_7_days":
            return f" AND {date_column} >= (CURRENT_DATE - INTERVAL '6 days') AND {date_column} < (CURRENT_DATE + INTERVAL '1 day') "
        elif time_filter == "last_30_days":
            return f" AND {date_column} >= (CURRENT_DATE - INTERVAL '29 days') AND {date_column} < (CURRENT_DATE + INTERVAL '1 day') "
        elif time_filter == "all_time" or time_filter == "all":
            return " " 
        else:
            logger.warning(f"[DB Admin Stats V5] Unknown time_filter: {time_filter}. Defaulting to 'all'.")
            return " "

    def get_total_users_count(self):
        # Logic identical, v5 had specific raw result logging.
        logger.info("[DB Admin Stats V5] Fetching total users count.")
        query = "SELECT COUNT(user_id) as total_users FROM users;"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V5] Raw result for total_users_count: {raw_result}") # Retained from v5
        return raw_result["total_users"] if raw_result and "total_users" in raw_result else 0

    def get_active_users_count(self, time_filter="all"):
        # Logic identical, v5 had specific raw result logging.
        logger.info(f"[DB Admin Stats V5] Fetching active users count for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "last_interaction_date")
        query = f"SELECT COUNT(DISTINCT user_id) as active_users FROM users WHERE 1=1 {time_condition};"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V5] Raw result for active_users_count ({time_filter}): {raw_result}") # Retained from v5
        return raw_result["active_users"] if raw_result and "active_users" in raw_result else 0
        
    def get_total_quizzes_count(self, time_filter="all"):
        # Logic identical, v5 had specific raw result logging. v16 had slightly different log message text.
        # Using v16's log text for clarity, but retaining v5's raw result logging.
        logger.info(f"[DB Admin Stats V5] Fetching total quizzes taken for filter: {time_filter}") # Log text from v16
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"SELECT COUNT(result_id) as total_quizzes FROM quiz_results WHERE completed_at IS NOT NULL {time_condition};"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V5] Raw result for total_quizzes_count ({time_filter}): {raw_result}") # Retained from v5
        return raw_result["total_quizzes"] if raw_result and "total_quizzes" in raw_result else 0

    def get_average_score_percentage(self, time_filter="all"):
        # This function was completed in v16. v5 was incomplete.
        # Adopting the complete v16 implementation.
        logger.info(f"[DB Admin Stats V5] Fetching average score percentage for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"""
        SELECT COALESCE(AVG(score_percentage), 0.0) as average_score
        FROM quiz_results 
        WHERE completed_at IS NOT NULL {time_condition};
        """
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V5] Raw result for average_score_percentage ({time_filter}): {raw_result}") # Retained from v5 for consistency
        return raw_result["average_score"] if raw_result and "average_score" in raw_result else 0.0

    def get_quiz_completion_rate(self, time_filter="all"):
        # This function was completed in v16. v5 was incomplete.
        # Adopting the complete v16 implementation.
        logger.info(f"[DB Admin Stats V5] Fetching quiz completion rate for filter: {time_filter}")
        time_condition_completed = self._get_time_filter_condition(time_filter, "completed_at")
        time_condition_started = self._get_time_filter_condition(time_filter, "start_time") # Assuming start_time for started quizzes

        query_completed = f"SELECT COUNT(result_id) as completed_count FROM quiz_results WHERE completed_at IS NOT NULL {time_condition_completed};"
        query_started = f"SELECT COUNT(result_id) as started_count FROM quiz_results WHERE 1=1 {time_condition_started};" # All quizzes started in period
        
        completed_result = self._execute_query(query_completed, fetch_one=True)
        started_result = self._execute_query(query_started, fetch_one=True)

        logger.info(f"[DB Admin Stats V5] Raw completed_count for completion_rate ({time_filter}): {completed_result}")
        logger.info(f"[DB Admin Stats V5] Raw started_count for completion_rate ({time_filter}): {started_result}")

        completed_count = completed_result["completed_count"] if completed_result and "completed_count" in completed_result else 0
        started_count = started_result["started_count"] if started_result and "started_count" in started_result else 0

        if started_count == 0:
            return 0.0 # Avoid division by zero
        
        completion_rate = (completed_count / started_count) * 100
        logger.info(f"[DB Admin Stats V5] Calculated quiz completion rate ({time_filter}): {completion_rate:.2f}%")
        return completion_rate

    # --- New Admin Statistics Functions from v16 ---
    def get_questions_added_count(self, time_filter="all"):
        """Counts how many questions were added within the specified time_filter."""
        logger.info(f"[DB Admin Stats V5] Fetching questions added count for filter: {time_filter}")
        # Assuming 'questions' table has a 'created_at' timestamp column for when it was added
        time_condition = self._get_time_filter_condition(time_filter, "created_at") 
        query = f"SELECT COUNT(question_id) as questions_added FROM questions WHERE 1=1 {time_condition};"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V5] Raw result for questions_added_count ({time_filter}): {raw_result}")
        return raw_result["questions_added"] if raw_result and "questions_added" in raw_result else 0

    def get_content_overview(self):
        """Provides an overview of the content: total courses, units, lessons, questions."""
        logger.info("[DB Admin Stats V5] Fetching content overview.")
        overview = {
            "total_courses": 0,
            "total_units": 0,
            "total_lessons": 0,
            "total_questions": 0
        }
        try:
            query_courses = "SELECT COUNT(course_id) as count FROM courses;"
            query_units = "SELECT COUNT(unit_id) as count FROM units;"
            query_lessons = "SELECT COUNT(lesson_id) as count FROM lessons;"
            query_questions = "SELECT COUNT(question_id) as count FROM questions;"

            overview["total_courses"] = (self._execute_query(query_courses, fetch_one=True) or {}).get("count", 0)
            overview["total_units"] = (self._execute_query(query_units, fetch_one=True) or {}).get("count", 0)
            overview["total_lessons"] = (self._execute_query(query_lessons, fetch_one=True) or {}).get("count", 0)
            overview["total_questions"] = (self._execute_query(query_questions, fetch_one=True) or {}).get("count", 0)
            
            logger.info(f"[DB Admin Stats V5] Content overview: {overview}")
        except Exception as e:
            logger.error(f"[DB Admin Stats V5] Error fetching content overview: {e}", exc_info=True)
        return overview

# Example usage (optional, for testing or direct script execution)
if __name__ == "__main__":
    # This part is typically not included in a library module but can be useful for direct testing.
    # For this merged file, we'll assume it's a library and omit direct execution block,
    # as neither v5 nor v16 had a significant __main__ block for general use.
    logger.info("DatabaseManager module loaded. (Merged Version)")
    # db_manager = DatabaseManager()
    # Test calls can be made here, e.g.:
    # print(db_manager.get_total_users_count())
    # print(db_manager.get_content_overview())
    pass




# Create an instance of the DatabaseManager for export
DB_MANAGER = DatabaseManager()
logger.info("[DB Manager Merged] DB_MANAGER instance created and ready for export.")

