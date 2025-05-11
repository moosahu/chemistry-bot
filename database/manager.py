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
            # logger.debug(f"[DB Manager] Executing query: {cur.mogrify(query, params)}") # Mogrify can be verbose
            cur.execute(query, params)

            if commit:
                conn.commit()
                logger.debug("[DB Manager] Query committed successfully.")
                result = True
            elif fetch_one:
                result = cur.fetchone()
                if result: result = dict(result) # Ensure it's a dict
                # logger.debug(f"[DB Manager] Fetched one row: {result}")
            elif fetch_all:
                result_list = cur.fetchall()
                # logger.debug(f"[DB Manager] Fetched {len(result_list)} rows.")
                result = [dict(row) for row in result_list] if result_list else []
            
            return result
        except (Exception, psycopg2.DatabaseError) as error:
            try:
                failed_query = cur.mogrify(query, params) if cur else query
            except Exception as mogrify_error:
                logger.error(f"[DB Manager] Error formatting query for logging: {mogrify_error}")
                failed_query = query # Fallback to unformatted query
            logger.error(f"[DB Manager] Database query error: {error}\nFailed Query (params might not be expanded): {failed_query}")
            if conn:
                conn.rollback()
            return None
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
                # logger.debug("[DB Manager] Database connection closed after query execution.")

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

    def get_overall_average_score(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching overall average score for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"SELECT COALESCE(AVG(score_percentage), 0.0) as average_score FROM quiz_results WHERE completed_at IS NOT NULL AND score_percentage IS NOT NULL {time_condition};"
        result = self._execute_query(query, fetch_one=True)
        return result["average_score"] if result and "average_score" in result else 0.0

    def get_average_quiz_duration(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching average quiz duration for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"SELECT COALESCE(AVG(time_taken_seconds), 0) as average_duration FROM quiz_results WHERE completed_at IS NOT NULL AND time_taken_seconds IS NOT NULL {time_condition};"
        result = self._execute_query(query, fetch_one=True)
        avg_duration = result["average_duration"] if result and "average_duration" in result else 0
        return int(avg_duration) if avg_duration is not None else 0

    def get_average_quizzes_per_active_user(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching average quizzes per active user for filter: {time_filter}")
        total_quizzes_completed = self.get_total_quizzes_count(time_filter)
        active_users = self.get_active_users_count(time_filter)
        if active_users == 0:
            return 0.0
        return round(total_quizzes_completed / active_users, 2)

    def get_quiz_completion_rate_stats(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching quiz completion rate stats for filter: {time_filter}")
        time_condition_started = self._get_time_filter_condition(time_filter, "start_time")
        time_condition_completed = self._get_time_filter_condition(time_filter, "completed_at")
        
        query_started = f"SELECT COUNT(result_id) as started_quizzes FROM quiz_results WHERE 1=1 {time_condition_started};"
        query_completed = f"SELECT COUNT(result_id) as completed_quizzes FROM quiz_results WHERE completed_at IS NOT NULL {time_condition_completed};"
        
        started_result = self._execute_query(query_started, fetch_one=True)
        completed_result = self._execute_query(query_completed, fetch_one=True)
        
        started_count = started_result["started_quizzes"] if started_result and "started_quizzes" in started_result else 0
        completed_count = completed_result["completed_quizzes"] if completed_result and "completed_quizzes" in completed_result else 0
        
        completion_rate = 0.0
        if started_count > 0:
            completion_rate = round((completed_count / started_count) * 100, 2)
        elif completed_count > 0 and started_count == 0: 
             logger.warning(f"[DB Admin Stats] Completion rate: {completed_count} quizzes completed but 0 started within filter '{time_filter}'. Rate will be 0%.")

        return {
            "started_quizzes": started_count,
            "completed_quizzes": completed_count,
            "completion_rate": completion_rate
        }

    def get_question_difficulty_stats(self, time_filter="all", limit=3):
        logger.info(f"[DB Admin Stats] Fetching question difficulty stats for filter: {time_filter}, limit: {limit}")
        time_condition = self._get_time_filter_condition(time_filter, "qr.completed_at")
        
        base_query = f"""
        SELECT 
            ad.question_id,
            q.question_text,
            COUNT(ad.question_id) as times_answered,
            SUM(CASE WHEN ad.is_correct THEN 1 ELSE 0 END) as correct_answers,
            SUM(CASE WHEN NOT ad.is_correct THEN 1 ELSE 0 END) as incorrect_answers,
            (SUM(CASE WHEN NOT ad.is_correct THEN 1 ELSE 0 END) * 100.0 / COUNT(ad.question_id)) as error_percentage,
            (SUM(CASE WHEN ad.is_correct THEN 1 ELSE 0 END) * 100.0 / COUNT(ad.question_id)) as correct_percentage
        FROM quiz_results qr
        CROSS JOIN LATERAL jsonb_to_recordset(qr.answers_details) AS ad(question_id TEXT, is_correct BOOLEAN, answer TEXT, correct_answer TEXT, explanation TEXT, image TEXT)
        LEFT JOIN questions q ON q.question_id::TEXT = ad.question_id
        WHERE qr.completed_at IS NOT NULL AND qr.answers_details IS NOT NULL
        {time_condition}
        GROUP BY ad.question_id, q.question_text
        HAVING COUNT(ad.question_id) > 0
        """
        
        query_difficult = base_query + " ORDER BY error_percentage DESC, times_answered DESC LIMIT %s;"
        most_difficult = self._execute_query(query_difficult, (limit,), fetch_all=True)
        
        query_easiest = base_query + " ORDER BY correct_percentage DESC, times_answered DESC LIMIT %s;"
        easiest = self._execute_query(query_easiest, (limit,), fetch_all=True)
        
        return {
            "most_difficult": most_difficult if most_difficult else [],
            "easiest": easiest if easiest else []
        }

    def get_unit_engagement_stats(self, time_filter="all", limit=5):
        logger.info(f"[DB Admin Stats] Fetching unit engagement (popularity) stats for filter: {time_filter}, limit: {limit}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        
        query_popular_quizzes = f"""
        SELECT 
            quiz_name, 
            COUNT(result_id) as times_taken,
            COALESCE(AVG(score_percentage), 0.0) as average_score 
        FROM quiz_results
        WHERE completed_at IS NOT NULL AND score_percentage IS NOT NULL {time_condition} 
        GROUP BY quiz_name
        HAVING COUNT(result_id) > 0
        ORDER BY times_taken DESC, average_score DESC
        LIMIT %s;
        """
        popular_quizzes = self._execute_query(query_popular_quizzes, (limit,), fetch_all=True)

        return {
            "popular_units": popular_quizzes if popular_quizzes else [] 
        }

    def get_most_difficult_units(self, time_filter="all", limit=3):
        logger.info(f"[DB Admin Stats] Fetching most difficult units for filter: {time_filter}, limit: {limit}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        
        query_difficult_units = f"""
        SELECT 
            quiz_name, 
            COUNT(result_id) as times_taken,
            COALESCE(AVG(score_percentage), 0.0) as average_score 
        FROM quiz_results
        WHERE completed_at IS NOT NULL AND score_percentage IS NOT NULL {time_condition}
        GROUP BY quiz_name
        HAVING COUNT(result_id) > 0 
        ORDER BY average_score ASC, times_taken DESC 
        LIMIT %s;
        """
        difficult_units = self._execute_query(query_difficult_units, (limit,), fetch_all=True)
        return difficult_units if difficult_units else []

    def get_easiest_units(self, time_filter="all", limit=3):
        logger.info(f"[DB Admin Stats] Fetching easiest units for filter: {time_filter}, limit: {limit}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        
        query_easiest_units = f"""
        SELECT 
            quiz_name, 
            COUNT(result_id) as times_taken,
            COALESCE(AVG(score_percentage), 0.0) as average_score
        FROM quiz_results
        WHERE completed_at IS NOT NULL AND score_percentage IS NOT NULL {time_condition}
        GROUP BY quiz_name
        HAVING COUNT(result_id) > 0
        ORDER BY average_score DESC, times_taken DESC
        LIMIT %s;
        """
        easiest_units = self._execute_query(query_easiest_units, (limit,), fetch_all=True)
        return easiest_units if easiest_units else []

    def get_user_activity_summary(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching user activity summary for filter: {time_filter}")
        time_condition_quiz = self._get_time_filter_condition(time_filter, "completed_at")
        
        query_active_quiz_takers = f"""
            SELECT COUNT(DISTINCT user_id) as active_quiz_takers
            FROM quiz_results
            WHERE completed_at IS NOT NULL {time_condition_quiz};
        """
        active_takers_result = self._execute_query(query_active_quiz_takers, fetch_one=True)
        active_quiz_takers = active_takers_result['active_quiz_takers'] if active_takers_result and 'active_quiz_takers' in active_takers_result else 0

        total_users = self.get_total_users_count()
        general_active_users = self.get_active_users_count(time_filter)

        return {
            "total_users": total_users,
            "active_users_general": general_active_users, 
            "active_users_took_quiz": active_quiz_takers 
        }

# Create an instance of the DatabaseManager for other modules to import
DB_MANAGER = DatabaseManager()

