"""Manages all database interactions for the Chemistry Telegram Bot."""

import psycopg2
import psycopg2.extras # For DictCursor
import logging
import random
import json # For storing details in JSONB
from datetime import datetime

# Import config, connection, and schema setup
try:
    from config import logger
    from .connection import connect_db
except ImportError:
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error("Failed to import config or connection. DB Manager might not function correctly.")
    def connect_db():
        logger.error("Dummy connect_db called!")
        return None

class DatabaseManager:
    """Handles all database operations, including user data, quiz structure, and results."""

    def __init__(self):
        """Initializes the DatabaseManager."""
        logger.info("[DB Manager] Initialized.")

    def _execute_query(self, query, params=None, fetch_one=False, fetch_all=False, commit=False):
        """Helper function to execute database queries with connection handling."""
        conn = connect_db()
        if not conn:
            logger.error("[DB Manager] Failed to get database connection for query.")
            return None
        
        cur = None
        result = None
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            logger.debug(f"[DB Manager] Executing query: {cur.mogrify(query, params)}")
            cur.execute(query, params)

            if commit:
                conn.commit()
                logger.debug("[DB Manager] Query committed successfully.")
                result = True
            elif fetch_one:
                result = cur.fetchone()
                logger.debug(f"[DB Manager] Fetched one row: {dict(result) if result else None}")
            elif fetch_all:
                result_list = cur.fetchall()
                logger.debug(f"[DB Manager] Fetched {len(result_list)} rows.")
                result = [dict(row) for row in result_list] if result_list else []
            
            return result
        except (Exception, psycopg2.DatabaseError) as error:
            try:
                failed_query = cur.mogrify(query, params) if cur else query
            except Exception as mogrify_error:
                logger.error(f"[DB Manager] Error formatting query for logging: {mogrify_error}")
                failed_query = query
            logger.error(f"[DB Manager] Database query error: {error}\nFailed Query: {failed_query}")
            if conn:
                conn.rollback()
            return None
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
                logger.debug("[DB Manager] Database connection closed after query execution.")

    def register_or_update_user(self, user_id: int, first_name: str, last_name: str | None, username: str | None, language_code: str | None):
        logger.info(f"[DB User] Registering/updating user: id={user_id}, name={first_name}, username={username}")
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
            logger.info(f"[DB User] Successfully registered/updated user {user_id}.")
        else:
            logger.error(f"[DB User] Failed to register/update user {user_id}.")
        return success

    def is_user_admin(self, user_id: int) -> bool:
        logger.debug(f"[DB User] Checking admin status for user {user_id}.")
        query = "SELECT is_admin FROM users WHERE user_id = %s;"
        result = self._execute_query(query, (user_id,), fetch_one=True)
        is_admin = result["is_admin"] if result and result["is_admin"] is True else False
        logger.debug(f"[DB User] Admin status for user {user_id}: {is_admin}")
        return is_admin

    def get_all_courses(self):
        logger.info("[DB Content] Fetching all courses.")
        query = "SELECT course_id, name, description FROM courses ORDER BY course_id;"
        return self._execute_query(query, fetch_all=True)

    def get_units_by_course(self, course_id: int):
        logger.info(f"[DB Content] Fetching units for course_id: {course_id}")
        query = "SELECT unit_id, name, description FROM units WHERE course_id = %s ORDER BY unit_id;"
        return self._execute_query(query, (course_id,), fetch_all=True)

    def get_lessons_by_unit(self, unit_id: int):
        logger.info(f"[DB Content] Fetching lessons for unit_id: {unit_id}")
        query = "SELECT lesson_id, name, description FROM lessons WHERE unit_id = %s ORDER BY lesson_id;"
        return self._execute_query(query, (unit_id,), fetch_all=True)

    def get_question_count(self, scope_type: str, scope_id: int | None = None) -> int:
        logger.info(f"[DB Questions] Getting question count for type=\"{scope_type}\" id={scope_id}")
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
            logger.warning(f"[DB Questions] Unknown scope_type for get_question_count: {scope_type}")
            return 0
            
        query = base_query + where_clause + ";"
        result = self._execute_query(query, tuple(params), fetch_one=True)
        count = result["count"] if result else 0
        logger.info(f"[DB Questions] Found {count} questions in DB for type=\"{scope_type}\" id={scope_id}")
        return count

    def save_quiz_result(self, user_id: int, quiz_type: str, quiz_scope_id: int | None,
                           total_questions: int, correct_count: int, wrong_count: int, skipped_count: int,
                           score_percentage_calculated: float, start_time: datetime | None, end_time: datetime, details: dict):
        """Saves the results of a completed quiz with all detailed parameters."""
        logger.info(f"[DB Results] Saving result for user {user_id}: Type={quiz_type}, Scope={quiz_scope_id}, Score={correct_count}/{total_questions} ({score_percentage_calculated:.2f}%), Wrong={wrong_count}, Skipped={skipped_count}")

        time_taken_seconds_val = None
        if start_time and end_time:
            time_taken_seconds_val = int((end_time - start_time).total_seconds())
        
        quiz_name = details.get("quiz_name")
        quiz_id_uuid_from_details = details.get("quiz_id_uuid")
        answers_details_json = json.dumps(details.get("answers_details", []))

        query = """
        INSERT INTO quiz_results 
            (user_id, quiz_type, filter_id, quiz_name, total_questions, score, wrong_answers, skipped_answers,
             score_percentage, start_time, completed_at, time_taken_seconds, quiz_id_uuid, answers_details)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
        """
        # 'completed_at' column in DB will store the 'end_time' parameter value from quiz_logic
        params = (user_id, quiz_type, quiz_scope_id, quiz_name, total_questions, correct_count, wrong_count, skipped_count,
                  score_percentage_calculated, start_time, end_time, time_taken_seconds_val, 
                  quiz_id_uuid_from_details, answers_details_json)
        
        success = self._execute_query(query, params, commit=True)
        if success:
            logger.info(f"[DB Results] Successfully saved detailed result to DB for user {user_id}, type {quiz_type}.")
        else:
            logger.error(f"[DB Results] Failed to save detailed result to DB for user {user_id}, type {quiz_type}.")
        return success

    def get_user_overall_stats(self, user_id: int):
        """Retrieves aggregated overall statistics for a specific user."""
        logger.info(f"[DB Stats] Fetching overall stats for user_id: {user_id}")
        query = """
        SELECT 
            COUNT(result_id) as total_quizzes_taken,
            COALESCE(SUM(score), 0) as total_correct_answers, 
            COALESCE(SUM(total_questions), 0) as total_questions_attempted,
            COALESCE(AVG(score_percentage), 0.0) as average_score_percentage,
            COALESCE(MAX(score_percentage), 0.0) as highest_score_percentage,
            COALESCE(SUM(time_taken_seconds), 0) as total_time_seconds
        FROM quiz_results
        WHERE user_id = %s;
        """
        stats = self._execute_query(query, (user_id,), fetch_one=True)
        if stats and stats["total_quizzes_taken"] > 0:
            logger.info(f"[DB Stats] Overall stats found for user {user_id}: {dict(stats)}")
            return dict(stats)
        else:
            logger.warning(f"[DB Stats] No overall stats found for user {user_id} or query failed.")
            return {
                "total_quizzes_taken": 0,
                "total_correct_answers": 0,
                "total_questions_attempted": 0,
                "average_score_percentage": 0.0,
                "highest_score_percentage": 0.0,
                "total_time_seconds": 0
            }

    def get_user_recent_quiz_history(self, user_id: int, limit: int = 5):
        """Retrieves recent quiz history for a specific user."""
        logger.info(f"[DB Stats] Fetching recent quiz history for user_id: {user_id}, limit: {limit}")
        query = """
        SELECT 
            result_id,
            quiz_type,
            quiz_name, 
            total_questions,
            score, 
            score_percentage as percentage, 
            completed_at as completion_timestamp,
            answers_details
        FROM quiz_results
        WHERE user_id = %s
        ORDER BY completed_at DESC
        LIMIT %s;
        """ # Re-enabled answers_details column
        history = self._execute_query(query, (user_id, limit), fetch_all=True)
        if history:
            logger.info(f"[DB Stats] Found {len(history)} recent quizzes for user {user_id}.")
            return history
        else:
            logger.warning(f"[DB Stats] No recent quiz history found for user {user_id} or query failed.")
            return []

    def get_leaderboard(self, limit: int = 10):
        logger.info(f"[DB Stats] Fetching top {limit} users for leaderboard.")
        query = """
        SELECT 
            r.user_id,
            COALESCE(u.username, u.first_name, CAST(r.user_id AS VARCHAR)) as user_display_name,
            AVG(r.score_percentage) as average_score_percentage,
            COUNT(r.result_id) as total_quizzes_taken
        FROM quiz_results r
        LEFT JOIN users u ON r.user_id = u.user_id
        GROUP BY r.user_id, u.username, u.first_name
        HAVING COUNT(r.result_id) > 0
        ORDER BY average_score_percentage DESC, total_quizzes_taken DESC
        LIMIT %s;
        """
        leaderboard = self._execute_query(query, (limit,), fetch_all=True)
        if leaderboard:
            logger.info(f"[DB Stats] Fetched {len(leaderboard)} users for leaderboard.")
        else:
            logger.warning("[DB Stats] No leaderboard data found or query failed.")
            leaderboard = []
        return leaderboard

    # --- Admin Statistics Functions ---
    def get_total_users_count(self):
        logger.info("[DB Admin Stats] Fetching total users count.")
        query = "SELECT COUNT(user_id) as total_users FROM users;"
        result = self._execute_query(query, fetch_one=True)
        return result['total_users'] if result and 'total_users' in result else 0

    def get_active_users_count(self, time_period="today"):
        logger.info(f"[DB Admin Stats] Fetching active users count for period: {time_period}.")
        # Assumes 'last_interaction_date' is a TIMESTAMP or DATE column in users table
        if time_period == "today":
            query = "SELECT COUNT(DISTINCT user_id) as active_users FROM users WHERE DATE(last_interaction_date) = CURRENT_DATE;"
        elif time_period == "week":
            query = "SELECT COUNT(DISTINCT user_id) as active_users FROM users WHERE last_interaction_date >= date_trunc('week', CURRENT_TIMESTAMP);"
        elif time_period == "month":
            query = "SELECT COUNT(DISTINCT user_id) as active_users FROM users WHERE last_interaction_date >= date_trunc('month', CURRENT_TIMESTAMP);"
        else: # Default to all time active users
            query = "SELECT COUNT(DISTINCT user_id) as active_users FROM users;"
        result = self._execute_query(query, fetch_one=True)
        return result['active_users'] if result and 'active_users' in result else 0

    def get_total_quizzes_count(self, time_period="all"):
        logger.info(f"[DB Admin Stats] Fetching total quizzes taken count for period: {time_period}.")
        # Assumes 'completed_at' is a TIMESTAMP column in quiz_results table
        if time_period == "today":
            query = "SELECT COUNT(result_id) as total_quizzes FROM quiz_results WHERE DATE(completed_at) = CURRENT_DATE;"
        elif time_period == "week":
            query = "SELECT COUNT(result_id) as total_quizzes FROM quiz_results WHERE completed_at >= date_trunc('week', CURRENT_TIMESTAMP);"
        elif time_period == "month":
            query = "SELECT COUNT(result_id) as total_quizzes FROM quiz_results WHERE completed_at >= date_trunc('month', CURRENT_TIMESTAMP);"
        else: # Default to all time
            query = "SELECT COUNT(result_id) as total_quizzes FROM quiz_results;"
        result = self._execute_query(query, fetch_one=True)
        return result['total_quizzes'] if result and 'total_quizzes' in result else 0

    def get_overall_average_score(self, time_period="all"):
        logger.info(f"[DB Admin Stats] Fetching average score percentage for period: {time_period}.")
        # Assumes 'score_percentage' column exists and is populated in quiz_results table
        base_query = "SELECT AVG(score_percentage) as avg_score FROM quiz_results"
        where_clause = ""
        if time_period == "today":
            where_clause = " WHERE DATE(completed_at) = CURRENT_DATE"
        elif time_period == "week":
            where_clause = " WHERE completed_at >= date_trunc('week', CURRENT_TIMESTAMP)"
        elif time_period == "month":
            where_clause = " WHERE completed_at >= date_trunc('month', CURRENT_TIMESTAMP)"
        
        query = base_query + where_clause + ";"
        result = self._execute_query(query, fetch_one=True)
        return round(result['avg_score'], 2) if result and result['avg_score'] is not None else 0.0

    def get_average_quiz_duration(self, time_period="all"):
        logger.info(f"[DB Admin Stats] Fetching average quiz completion time for period: {time_period}.")
        # Assumes 'time_taken_seconds' column exists and is populated in quiz_results table
        base_query = "SELECT AVG(time_taken_seconds) as avg_time FROM quiz_results WHERE time_taken_seconds IS NOT NULL AND time_taken_seconds > 0"
        where_clause = ""
        if time_period == "today":
            where_clause += " AND DATE(completed_at) = CURRENT_DATE" # Note: changed to += and added AND
        elif time_period == "week":
            where_clause += " AND completed_at >= date_trunc('week', CURRENT_TIMESTAMP)"
        elif time_period == "month":
            where_clause += " AND completed_at >= date_trunc('month', CURRENT_TIMESTAMP)"
            
        query = base_query + where_clause + ";"
        result = self._execute_query(query, fetch_one=True)
        return round(result['avg_time'], 2) if result and result['avg_time'] is not None else 0.0

DB_MANAGER = DatabaseManager()
logger.info("[DB Manager] Global instance created.")

