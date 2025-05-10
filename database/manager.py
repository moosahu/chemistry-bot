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

    def start_quiz_session_and_get_id(self, user_id: int, quiz_type: str, quiz_scope_id: int | None, 
                                      quiz_name: str, total_questions: int, start_time: datetime, score: int, initial_percentage: float, initial_time_taken_seconds: int) -> str | None:
        """
        Starts a new quiz session by logging it to the database and returns a unique session ID (UUID).
        This creates an initial record in quiz_results, which will be updated upon quiz completion.
        Assumes quiz_results table allows NULLs for score, completed_at, etc., for an in-progress quiz.
        """
        logger.info(f"[DB Session] Starting new quiz session for user {user_id}, type: {quiz_type}, name: {quiz_name}, questions: {total_questions}")
        
        session_uuid = str(uuid.uuid4())
        
        query_insert_start = """
        INSERT INTO quiz_results (
            user_id, quiz_type, filter_id, quiz_name, total_questions, start_time, quiz_id_uuid, score, percentage, time_taken_seconds
            -- wrong_answers, skipped_answers, score_percentage, completed_at, answers_details are implicitly NULL
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

    def save_quiz_result(self, 
                           quiz_id_uuid: str, 
                           user_id: int, # For logging/verification, and in case it's needed by a trigger/etc.
                           correct_count: int, 
                           wrong_count: int, 
                           skipped_count: int,
                           score_percentage_calculated: float, 
                           start_time_original: datetime | None, # The start_time logged initially, used for time_taken calculation
                           end_time: datetime, 
                           answers_details_list: list, # Formerly from details.get("answers_details", [])
                           quiz_type_for_log: str # For matching original log message
                           ):
        """Updates the results of a completed quiz session identified by quiz_id_uuid."""
        
        logger.info(f"[DB Results] Saving (updating) result for quiz_id_uuid {quiz_id_uuid} for user {user_id}: Score={correct_count}/{skipped_count+correct_count+wrong_count} ({score_percentage_calculated:.2f}%)")

        time_taken_seconds_val = None
        if start_time_original and end_time:
            time_taken_seconds_val = int((end_time - start_time_original).total_seconds())
        
        answers_details_json = json.dumps(answers_details_list)

        query_update_end = """
        UPDATE quiz_results 
        SET 
            score = %s, 
            wrong_answers = %s, 
            skipped_answers = %s,
            score_percentage = %s, 
            completed_at = %s, 
            time_taken_seconds = %s, 
            answers_details = %s
            -- user_id, quiz_type, filter_id, quiz_name, total_questions, start_time should already be set from start_quiz_session
        WHERE quiz_id_uuid = %s;
        """
        params = (correct_count, wrong_count, skipped_count, score_percentage_calculated,
                  end_time, time_taken_seconds_val, answers_details_json,
                  quiz_id_uuid)
        
        success = self._execute_query(query_update_end, params, commit=True)
        if success:
            logger.info(f"[DB Results] Successfully updated detailed result to DB for user {user_id}, type {quiz_type_for_log}, session {quiz_id_uuid}.")
        else:
            logger.error(f"[DB Results] Failed to update detailed result to DB for user {user_id}, type {quiz_type_for_log}, session {quiz_id_uuid}.")
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
        WHERE user_id = %s AND completed_at IS NOT NULL; -- Added condition for completed quizzes
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
            answers_details,
            quiz_id_uuid
        FROM quiz_results
        WHERE user_id = %s AND completed_at IS NOT NULL -- Added condition for completed quizzes
        ORDER BY completed_at DESC
        LIMIT %s;
        """ 
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
        WHERE r.completed_at IS NOT NULL -- Added condition for completed quizzes
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

    # --- Admin Statistics Functions (Existing and New) ---
    def _get_time_filter_condition(self, time_filter="all", date_column="created_at"):
        """Helper to create WHERE clause for time filtering."""
        # Ensure date_column is a valid column name to prevent SQL injection if it were user-supplied
        # For this internal use, we assume it's one of the known date columns.
        if time_filter == "today":
            return f" AND DATE({date_column}) = CURRENT_DATE "
        elif time_filter == "week":
            return f" AND {date_column} >= date_trunc(\'week\', CURRENT_TIMESTAMP) "
        elif time_filter == "month":
            return f" AND {date_column} >= date_trunc(\'month\', CURRENT_TIMESTAMP) "
        elif time_filter == "all":
            return " " # No additional time filter
        else:
            logger.warning(f"[DB Admin Stats] Unknown time_filter: {time_filter}. Defaulting to 'all'.")
            return " "

    def get_total_users_count(self):
        logger.info("[DB Admin Stats] Fetching total users count.")
        query = "SELECT COUNT(user_id) as total_users FROM users;"
        result = self._execute_query(query, fetch_one=True)
        return result["total_users"] if result and "total_users" in result else 0

    def get_active_users_count(self, time_filter="today"):
        logger.info(f"[DB Admin Stats] Fetching active users count for period: {time_filter}.")
        time_condition = self._get_time_filter_condition(time_filter, "last_interaction_date")
        # Remove leading ' AND ' if time_condition is not empty, and add WHERE if it is the first condition
        if time_condition.strip().startswith("AND"):
             time_condition = time_condition.strip()[3:] # remove 'AND'
        
        if time_condition.strip():
            query = f"SELECT COUNT(DISTINCT user_id) as active_users FROM users WHERE {time_condition.strip()};"
        else: # This case is for 'all' or invalid filter, effectively counting all users as active based on last_interaction_date
            query = f"SELECT COUNT(DISTINCT user_id) as active_users FROM users;"
            
        result = self._execute_query(query, fetch_one=True)
        return result["active_users"] if result and "active_users" in result else 0

    def get_total_quizzes_taken_count(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching total quizzes taken count for period: {time_filter}.")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"SELECT COUNT(result_id) as total_quizzes FROM quiz_results WHERE completed_at IS NOT NULL {time_condition};"
        result = self._execute_query(query, fetch_one=True)
        return result["total_quizzes"] if result and "total_quizzes" in result else 0

    def get_average_score_percentage_overall(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching average score percentage overall for period: {time_filter}.")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"SELECT COALESCE(AVG(score_percentage), 0.0) as avg_score_percentage FROM quiz_results WHERE completed_at IS NOT NULL {time_condition};"
        result = self._execute_query(query, fetch_one=True)
        return result["avg_score_percentage"] if result and "avg_score_percentage" in result else 0.0

    def get_average_quiz_completion_time(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching average quiz completion time for period: {time_filter}.")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"SELECT COALESCE(AVG(time_taken_seconds), 0.0) as avg_completion_time FROM quiz_results WHERE completed_at IS NOT NULL AND time_taken_seconds IS NOT NULL {time_condition};"
        result = self._execute_query(query, fetch_one=True)
        return result["avg_completion_time"] if result and "avg_completion_time" in result else 0.0

    def get_quiz_completion_rate(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching quiz completion rate for period: {time_filter}.")
        time_condition_started = self._get_time_filter_condition(time_filter, "start_time")
        time_condition_completed = self._get_time_filter_condition(time_filter, "completed_at")

        query_started = f"SELECT COUNT(quiz_id_uuid) as started_quizzes FROM quiz_results WHERE 1=1 {time_condition_started};"
        query_completed = f"SELECT COUNT(quiz_id_uuid) as completed_quizzes FROM quiz_results WHERE completed_at IS NOT NULL {time_condition_completed};"
        
        started_result = self._execute_query(query_started, fetch_one=True)
        completed_result = self._execute_query(query_completed, fetch_one=True)

        started_count = started_result["started_quizzes"] if started_result else 0
        completed_count = completed_result["completed_quizzes"] if completed_result else 0

        if started_count > 0:
            completion_rate = (completed_count / started_count) * 100
            return completion_rate
        return 0.0

    def get_average_quizzes_per_active_user(self, time_filter="today"):
        logger.info(f"[DB Admin Stats] Fetching average quizzes per active user for period: {time_filter}.")
        active_users = self.get_active_users_count(time_filter)
        if active_users == 0:
            return 0.0
        
        # Get total quizzes taken by users who were active in the period
        # This is a bit more complex as quiz_results.completed_at might not align with users.last_interaction_date
        # For simplicity, we'll count quizzes completed in the period by any user.
        # A more accurate (but complex) query would join users active in the period with their quizzes in that period.
        total_quizzes_in_period = self.get_total_quizzes_taken_count(time_filter)
        
        if active_users > 0:
            return total_quizzes_in_period / active_users
        return 0.0

    def get_most_popular_units(self, time_filter="all", limit=3):
        logger.info(f"[DB Admin Stats] Fetching most popular units for period: {time_filter}, limit: {limit}.")
        time_condition = self._get_time_filter_condition(time_filter, "qr.completed_at")
        # Assuming quiz_results.filter_id stores unit_id when quiz_type is 'unit'
        # And questions table has lesson_id, lessons table has unit_id
        # This query assumes 'quiz_name' might contain unit name or we join through questions to units
        # Let's assume quiz_results.filter_id is the unit_id for 'unit' type quizzes for simplicity
        # Or, if quizzes are tied to lessons, we need to join through questions -> lessons -> units
        
        # Simplified: Count quizzes by quiz_name if it represents the unit, or by filter_id if it's unit_id
        # A more robust way: if quiz_results has a direct unit_id or if we can trace questions in a quiz to a unit.
        # For now, let's assume quiz_type = 'unit' and filter_id = unit_id
        query = f"""
        SELECT u.name as unit_name, COUNT(qr.result_id) as quiz_count
        FROM quiz_results qr
        JOIN units u ON qr.filter_id = u.unit_id AND qr.quiz_type = 'unit'
        WHERE qr.completed_at IS NOT NULL {time_condition}
        GROUP BY u.name
        ORDER BY quiz_count DESC
        LIMIT %s;
        """
        # Fallback if no 'unit' type quizzes or filter_id is not unit_id
        # A more general approach might be to see which units' questions appear most in completed quizzes.
        # This requires parsing answers_details or having a question_to_quiz_result link.
        # The current schema seems to imply quiz_results.filter_id can be a unit_id for unit quizzes.

        results = self._execute_query(query, (limit,), fetch_all=True)
        return results if results else []

    def get_question_difficulty_stats(self, time_filter="all", limit=3):
        logger.info(f"[DB Admin Stats] Fetching question difficulty stats for period: {time_filter}, limit: {limit}.")
        time_condition = self._get_time_filter_condition(time_filter, "qr.completed_at")
        
        # This query requires parsing the answers_details JSONB field.
        # It assumes answers_details is an array of objects, each with 'question_id' and 'is_correct'.
        # This is a complex query and might be slow on large datasets without proper indexing on JSONB fields.
        query_difficult = f"""
        WITH question_attempts AS (
            SELECT 
                (answer_detail ->> 'question_id')::int as question_id,
                (answer_detail ->> 'is_correct')::boolean as is_correct
            FROM quiz_results qr,
                 jsonb_array_elements(qr.answers_details) as answer_detail
            WHERE qr.completed_at IS NOT NULL {time_condition} AND qr.answers_details IS NOT NULL
        )
        SELECT 
            q.question_text,
            q.question_id,
            SUM(CASE WHEN qa.is_correct = false THEN 1 ELSE 0 END) as incorrect_count,
            COUNT(qa.question_id) as total_attempts,
            (SUM(CASE WHEN qa.is_correct = false THEN 1 ELSE 0 END)::float / COUNT(qa.question_id)::float) * 100 as incorrect_percentage
        FROM question_attempts qa
        JOIN questions q ON qa.question_id = q.question_id
        GROUP BY q.question_id, q.question_text
        HAVING COUNT(qa.question_id) > 0 -- Ensure question was attempted
        ORDER BY incorrect_percentage DESC, incorrect_count DESC
        LIMIT %s;
        """
        
        query_easy = f"""
        WITH question_attempts AS (
            SELECT 
                (answer_detail ->> 'question_id')::int as question_id,
                (answer_detail ->> 'is_correct')::boolean as is_correct
            FROM quiz_results qr,
                 jsonb_array_elements(qr.answers_details) as answer_detail
            WHERE qr.completed_at IS NOT NULL {time_condition} AND qr.answers_details IS NOT NULL
        )
        SELECT 
            q.question_text,
            q.question_id,
            SUM(CASE WHEN qa.is_correct = true THEN 1 ELSE 0 END) as correct_count,
            COUNT(qa.question_id) as total_attempts,
            (SUM(CASE WHEN qa.is_correct = true THEN 1 ELSE 0 END)::float / COUNT(qa.question_id)::float) * 100 as correct_percentage
        FROM question_attempts qa
        JOIN questions q ON qa.question_id = q.question_id
        GROUP BY q.question_id, q.question_text
        HAVING COUNT(qa.question_id) > 0 -- Ensure question was attempted
        ORDER BY correct_percentage DESC, correct_count DESC
        LIMIT %s;
        """
        
        difficult_questions = self._execute_query(query_difficult, (limit,), fetch_all=True)
        easy_questions = self._execute_query(query_easy, (limit,), fetch_all=True)
        
        return {
            "most_difficult": difficult_questions if difficult_questions else [],
            "easiest": easy_questions if easy_questions else []
        }

# Singleton instance of the DatabaseManager
DB_MANAGER = DatabaseManager()

