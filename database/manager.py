"""Manages all database interactions for the Chemistry Telegram Bot."""

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
            cur.execute(query, params)

            if commit:
                conn.commit()
                logger.debug("[DB Manager] Query committed successfully.")
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
                logger.error(f"[DB Manager] Error formatting query for logging: {mogrify_error}")
                failed_query = query
            logger.error(f"[DB Manager] Database query error: {error}\nFailed Query (params might not be expanded): {failed_query}", exc_info=True)
            if conn:
                conn.rollback()
            return None
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

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
        is_admin = result["is_admin"] if result and result.get("is_admin") is True else False
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
        count = result["count"] if result and "count" in result else 0
        logger.info(f"[DB Questions] Found {count} questions in DB for type=\"{scope_type}\" id={scope_id}")
        return count

    def start_quiz_session_and_get_id(self, user_id: int, quiz_type: str, quiz_scope_id: int | None, 
                                      quiz_name: str, total_questions: int, start_time: datetime, score: int, initial_percentage: float, initial_time_taken_seconds: int) -> str | None:
        logger.info(f"[DB Session] Starting new quiz session for user {user_id}, type: {quiz_type}, name: {quiz_name}, questions: {total_questions}")
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
            logger.info(f"[DB Session] Successfully started and logged quiz session {session_uuid} for user {user_id}.")
            return session_uuid
        else:
            logger.error(f"[DB Session] Failed to start and log quiz session for user {user_id}.")
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
        logger.info(f"[DB Results] Ending quiz session {quiz_session_uuid}: Score={score}, Wrong={wrong_answers}, Skipped={skipped_answers}, Percentage={score_percentage:.2f}%")
        
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
            logger.info(f"[DB Results] Successfully updated (ended) quiz session {quiz_session_uuid} in DB.")
        else:
            logger.error(f"[DB Results] Failed to update (end) quiz session {quiz_session_uuid} in DB.")
        return success

    def get_user_overall_stats(self, user_id: int):
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
        WHERE user_id = %s AND completed_at IS NOT NULL;
        """
        stats = self._execute_query(query, (user_id,), fetch_one=True)
        if stats and stats.get("total_quizzes_taken", 0) > 0:
            logger.info(f"[DB Stats] Overall stats found for user {user_id}: {stats}")
            return stats 
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
            answers_details,
            quiz_id_uuid
        FROM quiz_results
        WHERE user_id = %s AND completed_at IS NOT NULL
        ORDER BY completed_at DESC
        LIMIT %s;
        """ 
        history = self._execute_query(query, (user_id, limit), fetch_all=True)
        if history:
            logger.info(f"[DB Stats] Found {len(history)} recent quizzes for user {user_id}.")
        else:
            logger.warning(f"[DB Stats] No recent quiz history found for user {user_id} or query failed.")
            history = [] 
        return history

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
        WHERE r.completed_at IS NOT NULL AND r.score_percentage IS NOT NULL
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
    def _get_time_filter_condition(self, time_filter="all", date_column="created_at"):
        """Helper to create WHERE clause for time filtering."""
        if time_filter == "today":
            return f" AND DATE({date_column}) = CURRENT_DATE "
        elif time_filter == "last_7_days":
            return f" AND {date_column} >= CURRENT_DATE - INTERVAL '6 days' AND {date_column} < CURRENT_DATE + INTERVAL '1 day' "
        elif time_filter == "last_30_days":
            return f" AND {date_column} >= CURRENT_DATE - INTERVAL '29 days' AND {date_column} < CURRENT_DATE + INTERVAL '1 day' "
        elif time_filter == "all":
            return " " 
        else:
            logger.warning(f"[DB Admin Stats] Unknown time_filter: {time_filter}. Defaulting to 'all'.")
            return " "

    def get_total_users_count(self):
        logger.info("[DB Admin Stats] Fetching total users count.")
        query = "SELECT COUNT(user_id) as total_users FROM users;"
        result = self._execute_query(query, fetch_one=True)
        return result["total_users"] if result and "total_users" in result else 0

    def get_active_users_count(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching active users count for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "last_interaction_date")
        query = f"SELECT COUNT(DISTINCT user_id) as active_users FROM users WHERE 1=1 {time_condition};"
        result = self._execute_query(query, fetch_one=True)
        return result["active_users"] if result and "active_users" in result else 0
        
    def get_total_quizzes_count(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching total quizzes completed count for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"SELECT COUNT(result_id) as total_quizzes FROM quiz_results WHERE completed_at IS NOT NULL {time_condition};"
        result = self._execute_query(query, fetch_one=True)
        return result["total_quizzes"] if result and "total_quizzes" in result else 0

    def get_average_quizzes_per_active_user(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching average quizzes per active user for filter: {time_filter}")
        total_quizzes = self.get_total_quizzes_count(time_filter)
        active_users = self.get_active_users_count(time_filter)
        if active_users > 0:
            return round(total_quizzes / active_users, 2)
        return 0.0

    def get_overall_average_score(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching overall average score for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"SELECT COALESCE(AVG(score_percentage), 0.0) as average_score FROM quiz_results WHERE completed_at IS NOT NULL AND score_percentage IS NOT NULL {time_condition};"
        result = self._execute_query(query, fetch_one=True)
        return result["average_score"] if result and "average_score" in result else 0.0

    def get_score_distribution(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching score distribution for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"""
        SELECT
            CASE
                WHEN score_percentage >= 0 AND score_percentage < 10 THEN '0-9%'
                WHEN score_percentage >= 10 AND score_percentage < 20 THEN '10-19%'
                WHEN score_percentage >= 20 AND score_percentage < 30 THEN '20-29%'
                WHEN score_percentage >= 30 AND score_percentage < 40 THEN '30-39%'
                WHEN score_percentage >= 40 AND score_percentage < 50 THEN '40-49%'
                WHEN score_percentage >= 50 AND score_percentage < 60 THEN '50-59%'
                WHEN score_percentage >= 60 AND score_percentage < 70 THEN '60-69%'
                WHEN score_percentage >= 70 AND score_percentage < 80 THEN '70-79%'
                WHEN score_percentage >= 80 AND score_percentage < 90 THEN '80-89%'
                WHEN score_percentage >= 90 AND score_percentage <= 100 THEN '90-100%'
                ELSE 'N/A'
            END as score_range,
            COUNT(*) as count
        FROM quiz_results
        WHERE completed_at IS NOT NULL AND score_percentage IS NOT NULL {time_condition}
        GROUP BY score_range
        ORDER BY score_range;
        """
        rows = self._execute_query(query, fetch_all=True)
        distribution_dict = {}
        if rows:
            for row in rows:
                distribution_dict[row["score_range"]] = row["count"]
        logger.debug(f"[DB Admin Stats] Score distribution for {time_filter}: {distribution_dict}")
        return distribution_dict # Returns a dictionary as expected

    def get_quiz_completion_rate_stats(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching quiz completion rate stats for filter: {time_filter}")
        time_condition_started = self._get_time_filter_condition(time_filter, "start_time")
        time_condition_completed = self._get_time_filter_condition(time_filter, "completed_at")

        query_started = f"SELECT COUNT(DISTINCT quiz_id_uuid) as started_quizzes FROM quiz_results WHERE 1=1 {time_condition_started};"
        query_completed = f"SELECT COUNT(DISTINCT quiz_id_uuid) as completed_quizzes FROM quiz_results WHERE completed_at IS NOT NULL {time_condition_completed};"
        
        started_result = self._execute_query(query_started, fetch_one=True)
        completed_result = self._execute_query(query_completed, fetch_one=True)
        
        started_count = started_result["started_quizzes"] if started_result else 0
        completed_count = completed_result["completed_quizzes"] if completed_result else 0
        
        completion_rate = (completed_count / started_count * 100) if started_count > 0 else 0.0
        
        logger.debug(f"[DB Admin Stats] Completion rate for {time_filter}: Started={started_count}, Completed={completed_count}, Rate={completion_rate:.2f}%")
        return {
            "started_quizzes": started_count,
            "completed_quizzes": completed_count,
            "completion_rate": round(completion_rate, 2)
        }

    def get_question_difficulty_stats(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching question difficulty stats for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "qr.completed_at")
        
        # This query is complex and assumes answers_details is a JSONB array of objects like:
        # [{"question_id": X, "is_correct": true/false, ...}, ...]
        # It unnests the array, then groups by question_id to calculate correctness.
        # This might be slow on very large datasets without proper indexing on JSONB content.
        query = f"""
        WITH question_attempts AS (
            SELECT 
                (answer_detail ->> 'question_id')::INT as question_id,
                (answer_detail ->> 'is_correct')::BOOLEAN as is_correct
            FROM quiz_results qr,
            LATERAL jsonb_array_elements(qr.answers_details) as answer_detail
            WHERE qr.completed_at IS NOT NULL {time_condition}
        )
        SELECT 
            qa.question_id,
            q.question_text, -- Assuming you have a 'question_text' in 'questions' table
            SUM(CASE WHEN qa.is_correct THEN 1 ELSE 0 END) as correct_answers,
            COUNT(qa.question_id) as total_attempts,
            ROUND((SUM(CASE WHEN qa.is_correct THEN 1 ELSE 0 END) * 100.0 / COUNT(qa.question_id)), 2) as correct_percentage
        FROM question_attempts qa
        JOIN questions q ON qa.question_id = q.question_id -- Join to get question_text
        GROUP BY qa.question_id, q.question_text
        ORDER BY correct_percentage ASC, total_attempts DESC
        LIMIT 20; -- Limit to top/bottom N for display purposes
        """
        # Note: The LIMIT 20 is arbitrary. You might want to fetch all and paginate or filter in Python.
        # Also, if 'question_text' is not in 'questions' table or named differently, adjust the JOIN and SELECT.
        
        difficulty_stats = self._execute_query(query, fetch_all=True)
        if not difficulty_stats:
            logger.warning(f"[DB Admin Stats] No question difficulty stats found for {time_filter}.")
            return []
        
        logger.debug(f"[DB Admin Stats] Fetched {len(difficulty_stats)} question difficulty stats for {time_filter}.")
        return difficulty_stats

# Instantiate the manager for other modules to import
DB_MANAGER = DatabaseManager()
logger.info("[DB Manager] Instance created and ready for import.")

