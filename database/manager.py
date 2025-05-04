# -*- coding: utf-8 -*-
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
    # Schema setup might be called externally, but manager needs to know tables exist
except ImportError:
    # Fallback for standalone testing or import issues
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error("Failed to import config or connection. DB Manager might not function correctly.")
    # Define dummy connect_db
    def connect_db():
        logger.error("Dummy connect_db called!")
        return None

class DatabaseManager:
    """Handles all database operations, including user data, quiz structure, and results."""

    def __init__(self):
        """Initializes the DatabaseManager."""
        # Connection is acquired per operation to handle potential disconnections
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
            # Use DictCursor to get results as dictionaries
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            logger.debug(f"[DB Manager] Executing query: {cur.mogrify(query, params)}")
            cur.execute(query, params)

            if commit:
                conn.commit()
                logger.debug("[DB Manager] Query committed successfully.")
                result = True # Indicate success for commit operations
            elif fetch_one:
                result = cur.fetchone()
                logger.debug(f"[DB Manager] Fetched one row: {dict(result) if result else None}")
            elif fetch_all:
                result = cur.fetchall()
                logger.debug(f"[DB Manager] Fetched {len(result)} rows.")
                # Convert list of DictRow to list of dict for easier use outside
                result = [dict(row) for row in result] if result else []
            
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
            return None # Indicate failure
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
                logger.debug("[DB Manager] Database connection closed after query execution.")

    # --- User Management --- 

    def register_or_update_user(self, user_id: int, first_name: str, last_name: str | None, username: str | None, language_code: str | None):
        """Registers a new user or updates their info and last interaction time."""
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
        """Checks if a user has the admin flag set."""
        logger.debug(f"[DB User] Checking admin status for user {user_id}.")
        query = "SELECT is_admin FROM users WHERE user_id = %s;"
        result = self._execute_query(query, (user_id,), fetch_one=True)
        is_admin = result["is_admin"] if result and result["is_admin"] else False
        logger.debug(f"[DB User] Admin status for user {user_id}: {is_admin}")
        return is_admin

    # --- Content Structure Retrieval --- 

    def get_all_courses(self):
        """Retrieves all available courses."""
        logger.info("[DB Content] Fetching all courses.")
        query = "SELECT course_id, name, description FROM courses ORDER BY course_id;"
        return self._execute_query(query, fetch_all=True)

    def get_units_by_course(self, course_id: int):
        """Retrieves units for a specific course."""
        logger.info(f"[DB Content] Fetching units for course_id: {course_id}")
        query = "SELECT unit_id, name, description FROM units WHERE course_id = %s ORDER BY unit_id;"
        return self._execute_query(query, (course_id,), fetch_all=True)

    def get_lessons_by_unit(self, unit_id: int):
        """Retrieves lessons for a specific unit."""
        logger.info(f"[DB Content] Fetching lessons for unit_id: {unit_id}")
        query = "SELECT lesson_id, name, description FROM lessons WHERE unit_id = %s ORDER BY lesson_id;"
        return self._execute_query(query, (unit_id,), fetch_all=True)

    # --- Question/Option Management (Potentially for admin interface or local fallback) --- 
    # Note: Primary question source is likely the API based on previous logic.
    # These functions might be less used or adapted for fallback/admin.

    def get_question_count(self, scope_type: str, scope_id: int | None = None) -> int:
        """Gets the count of questions based on scope (course, unit, lesson, or all).
           Note: This queries the local DB, might differ from API count.
        """
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

    # --- Quiz Results --- 

    def save_quiz_result(self, user_id: int, quiz_type: str, quiz_scope_id: int | None, 
                           total_questions: int, correct_count: int, wrong_count: int, skipped_count: int, 
                           score_percentage: float, start_time: datetime, end_time: datetime, details: dict):
        """Saves the results of a completed quiz."""
        logger.info(f"[DB Results] Saving result for user {user_id}: Type={quiz_type}, Scope={quiz_scope_id}, Score={correct_count}/{total_questions} ({score_percentage:.2f}%)")
        query = """
        INSERT INTO quiz_results 
            (user_id, quiz_type, quiz_scope_id, total_questions, correct_count, wrong_count, skipped_count, 
             score_percentage, start_time, end_time, details, completed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP);
        """
        # Convert details dict to JSON string for storing in JSONB
        details_json = json.dumps(details)
        params = (user_id, quiz_type, quiz_scope_id, total_questions, correct_count, wrong_count, skipped_count,
                  score_percentage, start_time, end_time, details_json)
        
        success = self._execute_query(query, params, commit=True)
        if success:
            logger.info(f"[DB Results] Successfully saved result for user {user_id}, type {quiz_type}.")
        else:
            logger.error(f"[DB Results] Failed to save result for user {user_id}, type {quiz_type}.")
        return success

    def get_user_stats(self, user_id: int):
        """Retrieves aggregated statistics for a specific user."""
        logger.info(f"[DB Stats] Fetching stats for user_id: {user_id}")
        query = """
        SELECT 
            COUNT(*) as total_quizzes_taken,
            COALESCE(SUM(correct_count), 0) as total_correct,
            COALESCE(SUM(wrong_count), 0) as total_wrong,
            COALESCE(SUM(skipped_count), 0) as total_skipped,
            COALESCE(AVG(score_percentage), 0.0) as average_score,
            COALESCE(SUM(EXTRACT(EPOCH FROM (end_time - start_time))), 0) as total_time_seconds
        FROM quiz_results
        WHERE user_id = %s;
        """
        stats = self._execute_query(query, (user_id,), fetch_one=True)
        if stats:
            logger.info(f"[DB Stats] Stats found for user {user_id}: {dict(stats)}")
            return dict(stats) # Convert DictRow to dict
        else:
            logger.warning(f"[DB Stats] No stats found for user {user_id} or query failed.")
            # Return default stats if none found
            return {
                "total_quizzes_taken": 0,
                "total_correct": 0,
                "total_wrong": 0,
                "total_skipped": 0,
                "average_score": 0.0,
                "total_time_seconds": 0
            }

    def get_leaderboard(self, limit: int = 10):
        """Retrieves the leaderboard based on average score and number of quizzes taken."""
        logger.info(f"[DB Stats] Fetching top {limit} users for leaderboard.")
        query = """
        SELECT 
            r.user_id,
            COALESCE(u.username, u.first_name, CAST(r.user_id AS VARCHAR)) as user_display_name,
            AVG(r.score_percentage) as average_score,
            COUNT(r.result_id) as quizzes_taken
        FROM quiz_results r
        LEFT JOIN users u ON r.user_id = u.user_id
        GROUP BY r.user_id, user_display_name
        HAVING COUNT(r.result_id) > 0 -- Ensure user has taken at least one quiz
        ORDER BY average_score DESC, quizzes_taken DESC
        LIMIT %s;
        """
        leaderboard = self._execute_query(query, (limit,), fetch_all=True)
        if leaderboard:
            logger.info(f"[DB Stats] Fetched {len(leaderboard)} users for leaderboard.")
        else:
            logger.warning("[DB Stats] No leaderboard data found or query failed.")
            leaderboard = [] # Ensure it returns a list
        return leaderboard

# --- Content Management (Example - if needed for admin) --- 

# Add functions here to add/update/delete courses, units, lessons, questions, options
# if the bot needs to manage content directly via the database.
# Example:
# def add_course(self, name: str, description: str | None = None):
#     query = "INSERT INTO courses (name, description) VALUES (%s, %s) RETURNING course_id;"
#     result = self._execute_query(query, (name, description), fetch_one=True, commit=True)
#     return result["course_id"] if result else None

# --- Initialization --- 

# Create a single instance of the manager to be imported by other modules
DB_MANAGER = DatabaseManager()
logger.info("[DB Manager] Global instance created.")

