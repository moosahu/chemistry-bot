"""Manages all database interactions for the Chemistry Telegram Bot.

Version 5: Adds detailed logging for raw results from admin statistics queries
to help debug why data might appear as zero or empty.

Version 17: Adds missing methods for admin statistics: 
get_average_quizzes_per_active_user, get_overall_average_score, 
get_score_distribution, get_average_quiz_duration, get_quiz_completion_rate_stats

Version 18: Modifies get_active_users_count to count users based on actual quiz completions
within the time_filter, rather than last_interaction_date from the users table.
This makes the 'active users' stat in 'Usage Overview' more relevant to quiz activity.
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
        logger.info("[DB Manager V18] Initialized.")

    def _execute_query(self, query, params=None, fetch_one=False, fetch_all=False, commit=False):
        """Helper function to execute database queries with connection handling."""
        conn = connect_db()
        if not conn:
            logger.error("[DB Manager V18] Failed to get database connection for query.")
            return None
        
        cur = None
        result = None
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute(query, params)

            if commit:
                conn.commit()
                logger.debug("[DB Manager V18] Query committed successfully.")
                result = True
            elif fetch_one:
                result = cur.fetchone()
                if result: result = dict(result) 
            elif fetch_all:
                result_list = cur.fetchall()
                result = [dict(row) for row in result_list] if result_list else []
            
            return result
        except (Exception, psycopg2.DatabaseError) as error:
            try:
                failed_query = cur.mogrify(query, params) if cur else query
            except Exception as mogrify_error:
                logger.error(f"[DB Manager V18] Error formatting query for logging: {mogrify_error}")
                failed_query = query
            logger.error(f"[DB Manager V18] Database query error: {error}\nFailed Query (params might not be expanded): {failed_query}", exc_info=True)
            if conn:
                conn.rollback()
            return None
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    def register_or_update_user(self, user_id: int, first_name: str, last_name: str | None, username: str | None, language_code: str | None):
        logger.info(f"[DB User V18] Registering/updating user: id={user_id}, name={first_name}, username={username}")
        # It's crucial to update last_interaction_date on every significant interaction, including starting/ending a quiz.
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
            logger.info(f"[DB User V18] Successfully registered/updated user {user_id}.")
        else:
            logger.error(f"[DB User V18] Failed to register/update user {user_id}.")
        return success

    def is_user_admin(self, user_id: int) -> bool:
        logger.debug(f"[DB User V18] Checking admin status for user {user_id}.")
        query = "SELECT is_admin FROM users WHERE user_id = %s;"
        result = self._execute_query(query, (user_id,), fetch_one=True)
        is_admin = result["is_admin"] if result and result.get("is_admin") is True else False
        logger.debug(f"[DB User V18] Admin status for user {user_id}: {is_admin}")
        return is_admin

    def get_all_courses(self):
        logger.info("[DB Content V18] Fetching all courses.")
        query = "SELECT course_id, name, description FROM courses ORDER BY course_id;"
        return self._execute_query(query, fetch_all=True)

    def get_units_by_course(self, course_id: int):
        logger.info(f"[DB Content V18] Fetching units for course_id: {course_id}")
        query = "SELECT unit_id, name, description FROM units WHERE course_id = %s ORDER BY unit_id;"
        return self._execute_query(query, (course_id,), fetch_all=True)

    def get_lessons_by_unit(self, unit_id: int):
        logger.info(f"[DB Content V18] Fetching lessons for unit_id: {unit_id}")
        query = "SELECT lesson_id, name, description FROM lessons WHERE unit_id = %s ORDER BY lesson_id;"
        return self._execute_query(query, (unit_id,), fetch_all=True)

    def get_question_count(self, scope_type: str, scope_id: int | None = None) -> int:
        logger.info(f"[DB Questions V18] Getting question count for type=\"{scope_type}\" id={scope_id}")
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
            logger.warning(f"[DB Questions V18] Unknown scope_type for get_question_count: {scope_type}")
            return 0
            
        query = base_query + where_clause + ";"
        result = self._execute_query(query, tuple(params), fetch_one=True)
        count = result["count"] if result and "count" in result else 0
        logger.info(f"[DB Questions V18] Found {count} questions in DB for type=\"{scope_type}\" id={scope_id}")
        return count

    def start_quiz_session_and_get_id(self, user_id: int, quiz_type: str, quiz_scope_id: int | None, 
                                      quiz_name: str, total_questions: int, start_time: datetime, score: int, initial_percentage: float, initial_time_taken_seconds: int) -> str | None:
        logger.info(f"[DB Session V18] Starting new quiz session for user {user_id}, type: {quiz_type}, name: {quiz_name}, questions: {total_questions}")
        # Ensure last_interaction_date is updated when a quiz starts
        self.register_or_update_user(user_id, "", None, None, None) # Minimal update to touch last_interaction_date

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
            logger.info(f"[DB Session V18] Successfully started and logged quiz session {session_uuid} for user {user_id}.")
            return session_uuid
        else:
            logger.error(f"[DB Session V18] Failed to start and log quiz session for user {user_id}.")
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
                           user_id: int # Added user_id to update last_interaction_date
                           ):
        logger.info(f"[DB Results V18] Ending quiz session {quiz_session_uuid}: Score={score}, Wrong={wrong_answers}, Skipped={skipped_answers}, Percentage={score_percentage:.2f}%")
        # Ensure last_interaction_date is updated when a quiz ends
        self.register_or_update_user(user_id, "", None, None, None) # Minimal update to touch last_interaction_date

        query_update_end = """
        UPDATE quiz_results 
        SET 
            score = %s, 
            wrong_answers = %s, 
            skipped_answers = %s,
            percentage = %s, 
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
            logger.info(f"[DB Results V18] Successfully updated (ended) quiz session {quiz_session_uuid} in DB.")
        else:
            logger.error(f"[DB Results V18] Failed to update (end) quiz session {quiz_session_uuid} in DB.")
        return success

    def get_user_overall_stats(self, user_id: int):
        logger.info(f"[DB Stats V18] Fetching overall stats for user_id: {user_id}")
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
        logger.info(f"[DB Stats V18] Raw overall stats for user {user_id}: {stats}")
        if stats and stats.get("total_quizzes_taken", 0) > 0:
            logger.info(f"[DB Stats V18] Overall stats found for user {user_id}: {stats}")
            return stats 
        else:
            logger.warning(f"[DB Stats V18] No overall stats found for user {user_id} or query failed. Returning defaults.")
            return {
                "total_quizzes_taken": 0,
                "total_correct_answers": 0,
                "total_questions_attempted": 0,
                "average_score_percentage": 0.0,
                "highest_score_percentage": 0.0,
                "total_time_seconds": 0
            }

    def get_user_recent_quiz_history(self, user_id: int, limit: int = 5):
        logger.info(f"[DB Stats V18] Fetching recent quiz history for user_id: {user_id}, limit: {limit}")
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
        logger.info(f"[DB Stats V18] Raw recent quiz history for user {user_id} (limit {limit}): {history}")
        if history:
            logger.info(f"[DB Stats V18] Found {len(history)} recent quizzes for user {user_id}.")
        else:
            logger.warning(f"[DB Stats V18] No recent quiz history found for user {user_id} or query failed.")
            history = [] 
        return history

    def get_leaderboard(self, limit: int = 10):
        logger.info(f"[DB Stats V18] Fetching top {limit} users for leaderboard.")
        query = """
        SELECT 
            r.user_id,
            COALESCE(u.full_name, u.username, u.first_name, CAST(r.user_id AS VARCHAR)) as user_display_name,
            AVG(r.score_percentage) as average_score_percentage,
            COUNT(r.result_id) as total_quizzes_taken,
            SUM(r.score) as total_correct
        FROM quiz_results r
        LEFT JOIN users u ON r.user_id = u.user_id
        WHERE r.completed_at IS NOT NULL AND r.score_percentage IS NOT NULL
        GROUP BY r.user_id, u.full_name, u.username, u.first_name
        HAVING COUNT(r.result_id) > 0 
        ORDER BY average_score_percentage DESC, total_quizzes_taken DESC
        LIMIT %s;
        """
        leaderboard = self._execute_query(query, (limit,), fetch_all=True)
        logger.info(f"[DB Stats V18] Raw leaderboard data (limit {limit}): {leaderboard}")
        if leaderboard:
            logger.info(f"[DB Stats V18] Fetched {len(leaderboard)} users for leaderboard.")
        else:
            logger.warning("[DB Stats V18] No leaderboard data found or query failed.")
            leaderboard = []
        return leaderboard

    def get_user_rank(self, user_id: int, weekly: bool = False) -> dict:
        """Get user's rank in the leaderboard.
        
        Args:
            user_id: Telegram user ID
            weekly: If True, get rank for this week only
            
        Returns:
            Dict with rank, total_users, avg_score, total_quizzes
        """
        logger.info(f"[DB Rank] Fetching rank for user {user_id}, weekly={weekly}")
        date_filter = "AND r.completed_at >= (CURRENT_DATE - INTERVAL '6 days')" if weekly else ""
        query = f"""
        WITH user_scores AS (
            SELECT 
                r.user_id,
                AVG(r.score_percentage) as avg_score,
                COUNT(r.result_id) as total_quizzes,
                SUM(r.score) as total_correct
            FROM quiz_results r
            WHERE r.completed_at IS NOT NULL 
              AND r.score_percentage IS NOT NULL
              {date_filter}
            GROUP BY r.user_id
            HAVING COUNT(r.result_id) > 0
        ),
        ranked AS (
            SELECT 
                user_id,
                avg_score,
                total_quizzes,
                total_correct,
                RANK() OVER (ORDER BY avg_score DESC, total_quizzes DESC) as rank,
                COUNT(*) OVER () as total_users
            FROM user_scores
        )
        SELECT rank, total_users, avg_score, total_quizzes, total_correct
        FROM ranked
        WHERE user_id = %s;
        """
        result = self._execute_query(query, (user_id,), fetch_one=True)
        if result:
            return result
        return {"rank": 0, "total_users": 0, "avg_score": 0, "total_quizzes": 0, "total_correct": 0}

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
            logger.warning(f"[DB Admin Stats V18] Unknown time_filter: {time_filter}. Defaulting to 'all'.")
            return " "

    def get_total_users_count(self):
        logger.info("[DB Admin Stats V18] Fetching total users count.")
        query = "SELECT COUNT(user_id) as total_users FROM users;"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V18] Raw result for total_users_count: {raw_result}")
        return raw_result["total_users"] if raw_result and "total_users" in raw_result else 0

    def get_active_users_count(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V18] Fetching active users count for filter: {time_filter} (based on quiz_results.completed_at)")
        # MODIFIED: Count distinct users who COMPLETED a quiz in the given time_filter
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"SELECT COUNT(DISTINCT user_id) as active_users FROM quiz_results WHERE completed_at IS NOT NULL {time_condition};"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V18] Raw result for active_users_count ({time_filter}): {raw_result}")
        return raw_result["active_users"] if raw_result and "active_users" in raw_result else 0
        
    def get_total_quizzes_count(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V18] Fetching total quizzes taken for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"SELECT COUNT(result_id) as total_quizzes FROM quiz_results WHERE completed_at IS NOT NULL {time_condition};"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V18] Raw result for total_quizzes_count ({time_filter}): {raw_result}")
        return raw_result["total_quizzes"] if raw_result and "total_quizzes" in raw_result else 0

    def get_average_quizzes_per_active_user(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V18] Fetching average quizzes per active user for filter: {time_filter}")
        active_users = self.get_active_users_count(time_filter) # Now uses the modified active user count
        if active_users == 0:
            logger.info(f"[DB Admin Stats V18] No active users for filter {time_filter}, returning 0 for average quizzes.")
            return 0.0
        total_quizzes = self.get_total_quizzes_count(time_filter)
        average = total_quizzes / active_users if active_users > 0 else 0.0
        logger.info(f"[DB Admin Stats V18] Average quizzes per active user ({time_filter}): {average:.2f}") # Added formatting
        return average

    def get_overall_average_score(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V18] Fetching overall average score for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"SELECT AVG(score_percentage) as avg_score FROM quiz_results WHERE completed_at IS NOT NULL {time_condition};"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V18] Raw result for overall_average_score ({time_filter}): {raw_result}")
        return float(raw_result["avg_score"]) if raw_result and raw_result["avg_score"] is not None else 0.0

    def get_score_distribution(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V18] Fetching score distribution for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"""
        SELECT 
            CASE 
                WHEN score_percentage BETWEEN 0 AND 20 THEN '0-20%' 
                WHEN score_percentage BETWEEN 21 AND 40 THEN '21-40%' 
                WHEN score_percentage BETWEEN 41 AND 60 THEN '41-60%' 
                WHEN score_percentage BETWEEN 61 AND 80 THEN '61-80%' 
                WHEN score_percentage BETWEEN 81 AND 100 THEN '81-100%' 
            END as score_range,
            COUNT(*) as count
        FROM quiz_results 
        WHERE completed_at IS NOT NULL {time_condition}
        GROUP BY score_range
        ORDER BY score_range;
        """
        raw_results = self._execute_query(query, fetch_all=True)
        logger.info(f"[DB Admin Stats V18] Raw result for score_distribution ({time_filter}): {raw_results}")
        distribution = {item["score_range"]: item["count"] for item in raw_results} if raw_results else {}
        # Ensure all ranges are present, even if count is 0
        all_ranges = ['0-20%', '21-40%', '41-60%', '61-80%', '81-100%']
        for r in all_ranges:
            if r not in distribution:
                distribution[r] = 0
        logger.info(f"[DB Admin Stats V18] Processed score_distribution ({time_filter}): {distribution}")
        return distribution

    def get_average_quiz_duration(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V18] Fetching average quiz duration for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"SELECT AVG(time_taken_seconds) as avg_duration FROM quiz_results WHERE completed_at IS NOT NULL AND time_taken_seconds IS NOT NULL {time_condition};"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V18] Raw result for average_quiz_duration ({time_filter}): {raw_result}")
        return float(raw_result["avg_duration"]) if raw_result and raw_result["avg_duration"] is not None else 0.0

    def get_quiz_completion_rate_stats(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V18] Fetching quiz completion rate stats for filter: {time_filter}")
        time_condition_started = self._get_time_filter_condition(time_filter, "start_time") # Use start_time for started quizzes
        time_condition_completed = self._get_time_filter_condition(time_filter, "completed_at")
        
        query_started = f"SELECT COUNT(result_id) as started_quizzes FROM quiz_results WHERE 1=1 {time_condition_started};"
        started_result = self._execute_query(query_started, fetch_one=True)
        started_quizzes = started_result["started_quizzes"] if started_result and "started_quizzes" in started_result else 0
        logger.info(f"[DB Admin Stats V18] Raw result for started_quizzes ({time_filter}): {started_result}")

        query_completed = f"SELECT COUNT(result_id) as completed_quizzes FROM quiz_results WHERE completed_at IS NOT NULL {time_condition_completed};"
        completed_result = self._execute_query(query_completed, fetch_one=True)
        completed_quizzes = completed_result["completed_quizzes"] if completed_result and "completed_quizzes" in completed_result else 0
        logger.info(f"[DB Admin Stats V18] Raw result for completed_quizzes ({time_filter}): {completed_result}")

        completion_rate = (completed_quizzes / started_quizzes * 100) if started_quizzes > 0 else 0.0
        stats = {
            "started_quizzes": started_quizzes,
            "completed_quizzes": completed_quizzes,
            "completion_rate": completion_rate
        }
        logger.info(f"[DB Admin Stats V18] Processed quiz_completion_rate_stats ({time_filter}): {stats}")
        return stats

    def get_detailed_question_stats(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V18] Fetching detailed question stats for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "qr.completed_at")

        query = f"""
        WITH question_performance AS (
            SELECT 
                (answer_detail ->> 'question_id') as question_id_text, 
                (answer_detail ->> 'question_text') as question_text, 
                (answer_detail ->> 'is_correct')::boolean as is_correct,
                (answer_detail ->> 'time_taken')::float as time_taken_seconds
            FROM quiz_results qr, jsonb_array_elements(qr.answers_details) as answer_detail
            WHERE qr.completed_at IS NOT NULL {time_condition} AND qr.answers_details IS NOT NULL AND jsonb_typeof(qr.answers_details) = 'array'
        )
        SELECT 
            qp.question_id_text, 
            qp.question_text, 
            COUNT(*) as times_answered, 
            SUM(CASE WHEN qp.is_correct THEN 1 ELSE 0 END) as times_correct, 
            SUM(CASE WHEN NOT qp.is_correct THEN 1 ELSE 0 END) as times_incorrect, 
            AVG(qp.time_taken_seconds) as avg_time_seconds
        FROM question_performance qp
        WHERE qp.question_text IS NOT NULL AND qp.question_text <> '' -- Ensure question_text is present
        GROUP BY qp.question_id_text, qp.question_text
        ORDER BY times_incorrect DESC, times_answered DESC;
        """
        raw_results = self._execute_query(query, fetch_all=True)
        logger.info(f"[DB Admin Stats V18] Raw result for detailed_question_stats ({time_filter}): {raw_results}")
        
        detailed_stats = []
        if raw_results:
            for row in raw_results:
                times_answered = int(row.get("times_answered", 0))
                times_correct = int(row.get("times_correct", 0))
                correct_percentage = (times_correct / times_answered * 100) if times_answered > 0 else 0.0
                detailed_stats.append({
                    "question_id": str(row.get("question_id_text", "N/A")),
                    "question_text": str(row.get("question_text", "N/A")),
                    "times_answered": times_answered,
                    "times_correct": times_correct,
                    "times_incorrect": int(row.get("times_incorrect", 0)),
                    "correct_percentage": correct_percentage,
                    "avg_time_seconds": float(row.get("avg_time_seconds", 0.0) or 0.0) # Handle None from AVG
                })
        logger.info(f"[DB Admin Stats V18] Processed detailed_question_stats ({time_filter}): {len(detailed_stats)} questions.")
        return detailed_stats

    # --- Weakness Quiz: Get questions user got wrong ---
    def get_user_weak_questions(self, user_id: int, limit: int = 50) -> list:
        """Get question IDs that the user answered incorrectly most often.
        
        Args:
            user_id: Telegram user ID
            limit: Maximum number of weak questions to return
            
        Returns:
            List of dicts with question_id, question_text, times_wrong, times_answered
        """
        logger.info(f"[DB Weakness] Fetching weak questions for user {user_id}, limit {limit}")
        query = """
        WITH user_answers AS (
            SELECT 
                (answer_detail ->> 'question_id') as question_id,
                (answer_detail ->> 'question_text') as question_text,
                (answer_detail ->> 'is_correct')::boolean as is_correct,
                (answer_detail ->> 'status') as status
            FROM quiz_results qr, jsonb_array_elements(qr.answers_details) as answer_detail
            WHERE qr.user_id = %s 
              AND qr.completed_at IS NOT NULL 
              AND qr.answers_details IS NOT NULL 
              AND jsonb_typeof(qr.answers_details) = 'array'
              AND (answer_detail ->> 'status') = 'answered'
        )
        SELECT 
            question_id,
            question_text,
            COUNT(*) as times_answered,
            SUM(CASE WHEN NOT is_correct THEN 1 ELSE 0 END) as times_wrong,
            ROUND(SUM(CASE WHEN NOT is_correct THEN 1 ELSE 0 END)::numeric / COUNT(*)::numeric * 100, 1) as error_rate
        FROM user_answers
        WHERE question_id IS NOT NULL
        GROUP BY question_id, question_text
        HAVING SUM(CASE WHEN NOT is_correct THEN 1 ELSE 0 END) > 0
        ORDER BY error_rate DESC, times_wrong DESC
        LIMIT %s;
        """
        results = self._execute_query(query, (user_id, limit), fetch_all=True)
        logger.info(f"[DB Weakness] Found {len(results) if results else 0} weak questions for user {user_id}")
        return results if results else []

    def get_user_weakness_by_unit(self, user_id: int) -> list:
        """Get weakness analysis grouped by quiz scope (unit/course).
        
        Analyzes all wrong answers and groups them by the quiz_scope_id 
        to identify which units the user struggles with most.
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            List of dicts with quiz_scope_id, quiz_type, total_wrong, total_answered, error_rate
        """
        logger.info(f"[DB Weakness] Fetching weakness by unit for user {user_id}")
        query = """
        WITH user_answers AS (
            SELECT 
                qr.quiz_scope_id,
                qr.quiz_type,
                (answer_detail ->> 'question_id') as question_id,
                (answer_detail ->> 'is_correct')::boolean as is_correct,
                (answer_detail ->> 'status') as status
            FROM quiz_results qr, jsonb_array_elements(qr.answers_details) as answer_detail
            WHERE qr.user_id = %s 
              AND qr.completed_at IS NOT NULL 
              AND qr.answers_details IS NOT NULL 
              AND jsonb_typeof(qr.answers_details) = 'array'
              AND (answer_detail ->> 'status') = 'answered'
        )
        SELECT 
            quiz_scope_id,
            quiz_type,
            COUNT(*) as total_answered,
            SUM(CASE WHEN NOT is_correct THEN 1 ELSE 0 END) as total_wrong,
            ROUND(SUM(CASE WHEN NOT is_correct THEN 1 ELSE 0 END)::numeric / NULLIF(COUNT(*), 0)::numeric * 100, 1) as error_rate
        FROM user_answers
        WHERE quiz_scope_id IS NOT NULL
        GROUP BY quiz_scope_id, quiz_type
        HAVING SUM(CASE WHEN NOT is_correct THEN 1 ELSE 0 END) > 0
        ORDER BY error_rate DESC, total_wrong DESC;
        """
        results = self._execute_query(query, (user_id,), fetch_all=True)
        logger.info(f"[DB Weakness] Found {len(results) if results else 0} weak scopes for user {user_id}")
        return results if results else []

    def get_user_weak_questions_by_scope(self, user_id: int, quiz_scope_id: str, limit: int = 30) -> list:
        """Get wrong question IDs for a specific quiz scope (unit/course).
        
        Args:
            user_id: Telegram user ID
            quiz_scope_id: The unit or course ID to filter by
            limit: Maximum questions to return
            
        Returns:
            List of dicts with question_id, times_wrong
        """
        logger.info(f"[DB Weakness] Fetching weak questions for user {user_id}, scope {quiz_scope_id}")
        query = """
        WITH user_answers AS (
            SELECT 
                (answer_detail ->> 'question_id') as question_id,
                (answer_detail ->> 'is_correct')::boolean as is_correct,
                (answer_detail ->> 'status') as status
            FROM quiz_results qr, jsonb_array_elements(qr.answers_details) as answer_detail
            WHERE qr.user_id = %s 
              AND qr.quiz_scope_id = %s
              AND qr.completed_at IS NOT NULL 
              AND qr.answers_details IS NOT NULL 
              AND jsonb_typeof(qr.answers_details) = 'array'
              AND (answer_detail ->> 'status') = 'answered'
        )
        SELECT 
            question_id,
            SUM(CASE WHEN NOT is_correct THEN 1 ELSE 0 END) as times_wrong
        FROM user_answers
        WHERE question_id IS NOT NULL
        GROUP BY question_id
        HAVING SUM(CASE WHEN NOT is_correct THEN 1 ELSE 0 END) > 0
        ORDER BY times_wrong DESC
        LIMIT %s;
        """
        results = self._execute_query(query, (user_id, quiz_scope_id, limit), fetch_all=True)
        return results if results else []

    # --- User Streak: Get consecutive days of quiz activity ---
    def get_user_streak(self, user_id: int) -> dict:
        """Get the user's current and longest quiz streak (consecutive days).
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            Dict with current_streak, longest_streak, last_quiz_date
        """
        logger.info(f"[DB Streak] Calculating streak for user {user_id}")
        query = """
        WITH quiz_dates AS (
            SELECT DISTINCT DATE(completed_at) as quiz_date
            FROM quiz_results
            WHERE user_id = %s AND completed_at IS NOT NULL
            ORDER BY quiz_date DESC
        ),
        streaks AS (
            SELECT 
                quiz_date,
                quiz_date - (ROW_NUMBER() OVER (ORDER BY quiz_date DESC))::int AS streak_group
            FROM quiz_dates
        )
        SELECT 
            streak_group,
            COUNT(*) as streak_length,
            MAX(quiz_date) as latest_date,
            MIN(quiz_date) as earliest_date
        FROM streaks
        GROUP BY streak_group
        ORDER BY latest_date DESC;
        """
        results = self._execute_query(query, (user_id,), fetch_all=True)
        
        if not results:
            return {"current_streak": 0, "longest_streak": 0, "last_quiz_date": None}
        
        # الـ streak الحالي هو أول مجموعة إذا كانت تشمل اليوم أو أمس
        from datetime import date
        today = date.today()
        
        current_streak = 0
        longest_streak = 0
        last_quiz_date = None
        
        for row in results:
            streak_len = int(row.get("streak_length", 0))
            latest = row.get("latest_date")
            
            if longest_streak < streak_len:
                longest_streak = streak_len
            
            if last_quiz_date is None and latest:
                last_quiz_date = latest
            
            # الـ streak الحالي: آخر تاريخ يكون اليوم أو أمس
            if latest and current_streak == 0:
                if isinstance(latest, datetime):
                    latest = latest.date()
                days_diff = (today - latest).days
                if days_diff <= 1:  # اليوم أو أمس
                    current_streak = streak_len
        
        result = {
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "last_quiz_date": str(last_quiz_date) if last_quiz_date else None
        }
        logger.info(f"[DB Streak] User {user_id} streak: {result}")
        return result

    # --- Weekly Leaderboard ---
    def get_weekly_leaderboard(self, limit: int = 10) -> list:
        """Get leaderboard filtered to last 7 days only.
        
        Args:
            limit: Maximum number of users to return
            
        Returns:
            List of dicts with user info and scores
        """
        logger.info(f"[DB Leaderboard] Fetching weekly leaderboard, limit {limit}")
        query = """
        SELECT 
            r.user_id,
            COALESCE(u.full_name, u.username, u.first_name, CAST(r.user_id AS VARCHAR)) as user_display_name,
            AVG(r.score_percentage) as average_score_percentage,
            COUNT(r.result_id) as total_quizzes_taken,
            SUM(r.score) as total_correct
        FROM quiz_results r
        LEFT JOIN users u ON r.user_id = u.user_id
        WHERE r.completed_at IS NOT NULL 
          AND r.score_percentage IS NOT NULL
          AND r.completed_at >= (CURRENT_DATE - INTERVAL '6 days')
        GROUP BY r.user_id, u.full_name, u.username, u.first_name
        HAVING COUNT(r.result_id) > 0 
        ORDER BY average_score_percentage DESC, total_quizzes_taken DESC
        LIMIT %s;
        """
        leaderboard = self._execute_query(query, (limit,), fetch_all=True)
        logger.info(f"[DB Leaderboard] Weekly leaderboard: {len(leaderboard) if leaderboard else 0} users")
        return leaderboard if leaderboard else []

    def get_user_info(self, user_id: int) -> dict | None:
        """Get user information from database."""
        logger.debug(f"[DB User] Fetching info for user {user_id}")
        query = "SELECT * FROM users WHERE user_id = %s;"
        return self._execute_query(query, (user_id,), fetch_one=True)

    def get_system_message(self, message_key: str) -> str | None:
        """Get a system message by key."""
        logger.debug(f"[DB System] Fetching system message: {message_key}")
        query = "SELECT message_text FROM system_messages WHERE message_key = %s;"
        result = self._execute_query(query, (message_key,), fetch_one=True)
        return result.get("message_text") if result else None

    def delete_user_account(self, user_id: int) -> dict:
        """حذف حساب المستخدم وجميع بياناته بالكامل"""
        logger.info(f"[DB Delete] Starting account deletion for user {user_id}")
        conn = connect_db()
        if not conn:
            return {'success': False, 'error': 'لا يوجد اتصال بقاعدة البيانات'}
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM quiz_results WHERE user_id = %s", (user_id,))
            quiz_count = cur.fetchone()[0]
            cur.execute("DELETE FROM quiz_results WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
            conn.commit()
            logger.info(f"[DB Delete] User {user_id} deleted: {quiz_count} quizzes removed")
            return {'success': True, 'quizzes_deleted': quiz_count}
        except Exception as e:
            logger.error(f"[DB Delete] Error deleting user {user_id}: {e}")
            conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if cur: cur.close()
            if conn: conn.close()

DB_MANAGER = DatabaseManager()
logger.info("[DB Manager V18] Global DB_MANAGER instance created.")


def delete_user_account(user_id):
    """حذف حساب المستخدم وجميع بياناته — دالة مستقلة"""
    logger.info(f"[DB Delete] Starting account deletion for user {user_id}")
    conn = connect_db()
    if not conn:
        return {'success': False, 'error': 'لا يوجد اتصال بقاعدة البيانات'}
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM quiz_results WHERE user_id = %s", (user_id,))
        quiz_count = cur.fetchone()[0]
        cur.execute("DELETE FROM quiz_results WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        conn.commit()
        logger.info(f"[DB Delete] User {user_id} deleted: {quiz_count} quizzes removed")
        return {'success': True, 'quizzes_deleted': quiz_count}
    except Exception as e:
        logger.error(f"[DB Delete] Error deleting user {user_id}: {e}")
        conn.rollback()
        return {'success': False, 'error': str(e)}
    finally:
        if cur: cur.close()
        if conn: conn.close()


# ============================================================
#  جدول مواعيد التحصيلي
# ============================================================

def ensure_exam_schedule_table():
    """إنشاء جدول مواعيد التحصيلي إذا ما كان موجود"""
    conn = connect_db()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS exam_schedule (
                id SERIAL PRIMARY KEY,
                period_name VARCHAR(100) NOT NULL,
                exam_start_date DATE,
                exam_end_date DATE,
                reg_boys_date DATE,
                reg_girls_date DATE,
                late_reg_date DATE,
                last_reg_date DATE,
                status VARCHAR(20) DEFAULT 'active',
                notes TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)
        conn.commit()
        logger.info("[DB] exam_schedule table ensured")
    except Exception as e:
        logger.error(f"[DB] Error creating exam_schedule table: {e}")
        conn.rollback()
    finally:
        if cur: cur.close()
        if conn: conn.close()

ensure_exam_schedule_table()


def get_exam_periods(status_filter=None):
    """جلب فترات الاختبار"""
    conn = connect_db()
    if not conn: return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        if status_filter:
            cur.execute("SELECT * FROM exam_schedule WHERE status = %s ORDER BY exam_start_date", (status_filter,))
        else:
            cur.execute("SELECT * FROM exam_schedule ORDER BY exam_start_date")
        rows = cur.fetchall()
        return [dict(r) for r in rows] if rows else []
    except Exception as e:
        logger.error(f"[DB] Error getting exam periods: {e}")
        return []
    finally:
        if cur: cur.close()
        if conn: conn.close()


def add_exam_period(period_name, exam_start, exam_end, reg_boys=None, reg_girls=None,
                    late_reg=None, last_reg=None, status='active', notes=None):
    """إضافة فترة اختبار جديدة"""
    conn = connect_db()
    if not conn: return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO exam_schedule
            (period_name, exam_start_date, exam_end_date, reg_boys_date, reg_girls_date,
             late_reg_date, last_reg_date, status, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (period_name, exam_start, exam_end, reg_boys, reg_girls, late_reg, last_reg, status, notes))
        conn.commit()
        logger.info(f"[DB] Added exam period: {period_name}")
        return True
    except Exception as e:
        logger.error(f"[DB] Error adding exam period: {e}")
        conn.rollback()
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()


def update_exam_period_status(period_id, new_status):
    """تغيير حالة فترة الاختبار"""
    conn = connect_db()
    if not conn: return False
    try:
        cur = conn.cursor()
        cur.execute("UPDATE exam_schedule SET status = %s, updated_at = NOW() WHERE id = %s",
                    (new_status, period_id))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"[DB] Error updating period status: {e}")
        conn.rollback()
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()


def delete_exam_period(period_id):
    """حذف فترة اختبار"""
    conn = connect_db()
    if not conn: return False
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM exam_schedule WHERE id = %s", (period_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"[DB] Error deleting period: {e}")
        conn.rollback()
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()


# ============================================================
#  جدول الحسابات المحذوفة (فترة الانتظار)
# ============================================================

def ensure_deleted_accounts_table():
    """إنشاء جدول الحسابات المحذوفة"""
    conn = connect_db()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS deleted_accounts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                deleted_at TIMESTAMP DEFAULT NOW(),
                full_name VARCHAR(200)
            );
        """)
        conn.commit()
        logger.info("[DB] deleted_accounts table ensured")
    except Exception as e:
        logger.error(f"[DB] Error creating deleted_accounts table: {e}")
        conn.rollback()
    finally:
        if cur: cur.close()
        if conn: conn.close()

ensure_deleted_accounts_table()


def record_account_deletion(user_id, full_name=None):
    """تسجيل حذف الحساب"""
    conn = connect_db()
    if not conn: return False
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO deleted_accounts (user_id, full_name) VALUES (%s, %s)", (user_id, full_name))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"[DB] Error recording deletion: {e}")
        conn.rollback()
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()


def check_deletion_cooldown(user_id, cooldown_days=7):
    """التحقق هل المستخدم حذف حسابه مؤخراً — يرجع None إذا مافي حظر"""
    conn = connect_db()
    if not conn: return None
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT deleted_at FROM deleted_accounts 
            WHERE user_id = %s ORDER BY deleted_at DESC LIMIT 1
        """, (user_id,))
        row = cur.fetchone()
        if not row:
            return None
        from datetime import datetime, timedelta
        deleted_at = row['deleted_at']
        cooldown_end = deleted_at + timedelta(days=cooldown_days)
        now = datetime.now()
        if now < cooldown_end:
            remaining = cooldown_end - now
            return {
                'in_cooldown': True,
                'deleted_at': deleted_at,
                'cooldown_end': cooldown_end,
                'remaining_days': remaining.days,
                'remaining_hours': remaining.seconds // 3600
            }
        return None
    except Exception as e:
        logger.error(f"[DB] Error checking cooldown: {e}")
        return None
    finally:
        if cur: cur.close()
        if conn: conn.close()


# ============================================================
#  جدول إعدادات البوت (تفعيل/تعطيل الميزات)
# ============================================================

def ensure_bot_settings_table():
    """إنشاء جدول إعدادات البوت"""
    conn = connect_db()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                setting_key VARCHAR(50) PRIMARY KEY,
                setting_value VARCHAR(200) NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)
        cur.execute("""
            INSERT INTO bot_settings (setting_key, setting_value)
            VALUES ('allow_account_deletion', 'off')
            ON CONFLICT (setting_key) DO NOTHING;
        """)
        conn.commit()
        logger.info("[DB] bot_settings table ensured")
    except Exception as e:
        logger.error(f"[DB] Error creating bot_settings table: {e}")
        conn.rollback()
    finally:
        if cur: cur.close()
        if conn: conn.close()

ensure_bot_settings_table()


def get_bot_setting(key, default='off'):
    """جلب إعداد من جدول الإعدادات"""
    conn = connect_db()
    if not conn: return default
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT setting_value FROM bot_settings WHERE setting_key = %s", (key,))
        row = cur.fetchone()
        return row['setting_value'] if row else default
    except Exception as e:
        logger.error(f"[DB] Error getting setting {key}: {e}")
        return default
    finally:
        if cur: cur.close()
        if conn: conn.close()


def set_bot_setting(key, value):
    """تعديل إعداد في جدول الإعدادات"""
    conn = connect_db()
    if not conn: return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO bot_settings (setting_key, setting_value, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (setting_key) DO UPDATE SET setting_value = %s, updated_at = NOW()
        """, (key, value, value))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"[DB] Error setting {key}: {e}")
        conn.rollback()
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()


# ============================================================
#  جدول خطط المذاكرة
# ============================================================

def ensure_study_tables():
    """إنشاء جداول خطط المذاكرة + جداول تتبع الإشعارات"""
    conn = connect_db()
    if not conn:
        return
    try:
        cur = conn.cursor()
        # جدول الإشعارات
        cur.execute("""
            CREATE TABLE IF NOT EXISTS broadcasts (
                id SERIAL PRIMARY KEY,
                message_text TEXT,
                target_type VARCHAR(50) DEFAULT 'all',
                target_filter VARCHAR(100),
                sent_count INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        # جدول قراءة الإشعارات
        cur.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_reads (
                id SERIAL PRIMARY KEY,
                broadcast_id INT REFERENCES broadcasts(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL,
                read_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(broadcast_id, user_id)
            );
        """)
        conn.commit()
        logger.info("[DB] broadcasts & broadcast_reads tables ensured")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS study_plans (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                subject VARCHAR(100) DEFAULT 'كيمياء',
                num_weeks INT DEFAULT 4,
                rest_days VARCHAR(50) DEFAULT '',
                start_date DATE,
                created_at TIMESTAMP DEFAULT NOW(),
                is_active BOOLEAN DEFAULT TRUE
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS study_plan_days (
                id SERIAL PRIMARY KEY,
                plan_id INT REFERENCES study_plans(id) ON DELETE CASCADE,
                day_date DATE NOT NULL,
                week_number INT NOT NULL,
                day_name VARCHAR(20),
                is_rest_day BOOLEAN DEFAULT FALSE,
                is_completed BOOLEAN DEFAULT FALSE,
                pages VARCHAR(100),
                notes TEXT,
                completed_at TIMESTAMP
            );
        """)
        # إضافة عمود is_rest_day لو الجدول موجود بدونه
        cur.execute("""
            ALTER TABLE study_plan_days ADD COLUMN IF NOT EXISTS is_rest_day BOOLEAN DEFAULT FALSE;
        """)
        cur.execute("""
            ALTER TABLE study_plans ADD COLUMN IF NOT EXISTS rest_days VARCHAR(50) DEFAULT '';
        """)
        conn.commit()
        logger.info("[DB] study_plans & study_plan_days tables ensured")
    except Exception as e:
        logger.error(f"[DB] Error creating study tables: {e}")
        conn.rollback()
    finally:
        if cur: cur.close()
        if conn: conn.close()

ensure_study_tables()


def create_study_plan(user_id, subject, num_weeks, start_date, rest_days_list=None):
    """إنشاء خطة مذاكرة جديدة مع أيام الراحة"""
    conn = connect_db()
    if not conn: return None
    if rest_days_list is None:
        rest_days_list = []
    rest_days_str = ','.join(str(d) for d in rest_days_list)
    try:
        cur = conn.cursor()
        # تعطيل أي خطة سابقة
        cur.execute("UPDATE study_plans SET is_active = FALSE WHERE user_id = %s AND is_active = TRUE", (user_id,))
        # إنشاء الخطة الجديدة
        cur.execute("""
            INSERT INTO study_plans (user_id, subject, num_weeks, rest_days, start_date)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        """, (user_id, subject, num_weeks, rest_days_str, start_date))
        plan_id = cur.fetchone()[0]
        
        # إنشاء أيام الخطة
        from datetime import timedelta
        day_names_ar = ['الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد']
        current_date = start_date
        for week in range(1, num_weeks + 1):
            for day_idx in range(7):
                day_name = day_names_ar[current_date.weekday()]
                # weekday(): 0=Mon,1=Tue,2=Wed,3=Thu,4=Fri,5=Sat,6=Sun
                is_rest = current_date.weekday() in rest_days_list
                cur.execute("""
                    INSERT INTO study_plan_days (plan_id, day_date, week_number, day_name, is_rest_day)
                    VALUES (%s, %s, %s, %s, %s)
                """, (plan_id, current_date, week, day_name, is_rest))
                current_date += timedelta(days=1)
        
        conn.commit()
        study_days = num_weeks * 7 - num_weeks * len(rest_days_list)
        logger.info(f"[DB] Study plan {plan_id} created: {subject}, {num_weeks}w, {study_days} study days, rest={rest_days_list}")
        return plan_id
    except Exception as e:
        logger.error(f"[DB] Error creating study plan: {e}")
        conn.rollback()
        return None
    finally:
        if cur: cur.close()
        if conn: conn.close()


def get_active_study_plan(user_id):
    """جلب الخطة النشطة للمستخدم"""
    conn = connect_db()
    if not conn: return None
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT * FROM study_plans 
            WHERE user_id = %s AND is_active = TRUE 
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"[DB] Error getting study plan: {e}")
        return None
    finally:
        if cur: cur.close()
        if conn: conn.close()


def get_study_plan_days(plan_id, week_number=None):
    """جلب أيام خطة المذاكرة"""
    conn = connect_db()
    if not conn: return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        if week_number:
            cur.execute("""
                SELECT * FROM study_plan_days 
                WHERE plan_id = %s AND week_number = %s 
                ORDER BY day_date
            """, (plan_id, week_number))
        else:
            cur.execute("""
                SELECT * FROM study_plan_days 
                WHERE plan_id = %s ORDER BY day_date
            """, (plan_id,))
        return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"[DB] Error getting plan days: {e}")
        return []
    finally:
        if cur: cur.close()
        if conn: conn.close()


def update_study_day(day_id, is_completed=True, pages=None, notes=None):
    """تحديث يوم في خطة المذاكرة"""
    conn = connect_db()
    if not conn: return False
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE study_plan_days 
            SET is_completed = %s, pages = %s, notes = %s, completed_at = NOW()
            WHERE id = %s
        """, (is_completed, pages, notes, day_id))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"[DB] Error updating study day: {e}")
        conn.rollback()
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()


def toggle_study_day(day_id):
    """تبديل حالة يوم (تم/لم يتم)"""
    conn = connect_db()
    if not conn: return False
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE study_plan_days 
            SET is_completed = NOT is_completed,
                completed_at = CASE WHEN is_completed THEN NULL ELSE NOW() END
            WHERE id = %s
        """, (day_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"[DB] Error toggling study day: {e}")
        conn.rollback()
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()


def get_study_plan_stats(plan_id):
    """إحصائيات خطة المذاكرة — تستثني أيام الراحة"""
    conn = connect_db()
    if not conn: return {}
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT 
                COUNT(*) as total_days,
                COUNT(*) FILTER (WHERE NOT is_rest_day) as study_days,
                COUNT(*) FILTER (WHERE is_completed AND NOT is_rest_day) as completed_days,
                COUNT(*) FILTER (WHERE is_rest_day) as rest_days_count,
                COUNT(DISTINCT week_number) as total_weeks
            FROM study_plan_days WHERE plan_id = %s
        """, (plan_id,))
        row = cur.fetchone()
        if row:
            study = row['study_days']
            completed = row['completed_days']
            return {
                'total_days': row['total_days'],
                'study_days': study,
                'completed_days': completed,
                'rest_days_count': row['rest_days_count'],
                'total_weeks': row['total_weeks'],
                'progress_pct': round((completed / study * 100) if study > 0 else 0, 1)
            }
        return {}
    except Exception as e:
        logger.error(f"[DB] Error getting plan stats: {e}")
        return {}
    finally:
        if cur: cur.close()
        if conn: conn.close()


def delete_study_plan(plan_id):
    """حذف خطة مذاكرة"""
    conn = connect_db()
    if not conn: return False
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM study_plans WHERE id = %s", (plan_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"[DB] Error deleting plan: {e}")
        conn.rollback()
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()


def get_study_schedule_report(only_my_students=False):
    """تقرير شامل عن استخدام جداول المذاكرة"""
    conn = connect_db()
    if not conn: return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        my_filter = "AND COALESCE(u.is_my_student, FALSE) = TRUE" if only_my_students else ""
        cur.execute(f"""
            SELECT 
                sp.id as plan_id,
                sp.user_id,
                u.full_name,
                u.grade,
                COALESCE(u.is_my_student, FALSE) as is_my_student,
                sp.subject,
                sp.num_weeks,
                sp.rest_days,
                sp.start_date,
                sp.created_at,
                sp.is_active,
                COUNT(d.id) as total_days,
                COUNT(d.id) FILTER (WHERE NOT d.is_rest_day) as study_days,
                COUNT(d.id) FILTER (WHERE d.is_completed AND NOT d.is_rest_day) as completed_days,
                COUNT(d.id) FILTER (WHERE d.is_rest_day) as rest_count,
                MAX(d.completed_at) as last_activity,
                CASE 
                    WHEN COUNT(d.id) FILTER (WHERE d.is_completed) > 0 THEN TRUE 
                    ELSE FALSE 
                END as has_progress,
                EXTRACT(DAY FROM NOW() - MAX(d.completed_at))::INT as days_since_activity
            FROM study_plans sp
            JOIN users u ON sp.user_id = u.user_id
            LEFT JOIN study_plan_days d ON sp.id = d.plan_id
            WHERE u.is_registered = TRUE {my_filter}
            GROUP BY sp.id, sp.user_id, u.full_name, u.grade, u.is_my_student,
                     sp.subject, sp.num_weeks, sp.rest_days, sp.start_date, sp.created_at, sp.is_active
            ORDER BY sp.is_active DESC, sp.created_at DESC
        """)
        return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"[DB] Error getting study schedule report: {e}")
        return []
    finally:
        if cur: cur.close()
        if conn: conn.close()


# ============================================================
#  تتبع قراءة الإشعارات
# ============================================================

def create_broadcast_record(message_text, target_type='all', target_filter=None, sent_count=0):
    """تسجيل إشعار جديد"""
    conn = connect_db()
    if not conn: return None
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO broadcasts (message_text, target_type, target_filter, sent_count)
            VALUES (%s, %s, %s, %s) RETURNING id
        """, (message_text[:500], target_type, target_filter, sent_count))
        broadcast_id = cur.fetchone()[0]
        conn.commit()
        logger.info(f"[DB] Broadcast {broadcast_id} created: {target_type}, sent={sent_count}")
        return broadcast_id
    except Exception as e:
        logger.error(f"[DB] Error creating broadcast: {e}")
        conn.rollback()
        return None
    finally:
        if cur: cur.close()
        if conn: conn.close()


def record_broadcast_read(broadcast_id, user_id):
    """تسجيل قراءة إشعار"""
    conn = connect_db()
    if not conn: return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO broadcast_reads (broadcast_id, user_id)
            VALUES (%s, %s) ON CONFLICT (broadcast_id, user_id) DO NOTHING
        """, (broadcast_id, user_id))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"[DB] Error recording broadcast read: {e}")
        conn.rollback()
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()


def get_broadcast_read_stats(broadcast_id):
    """إحصائيات قراءة إشعار معين"""
    conn = connect_db()
    if not conn: return {}
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        # بيانات الإشعار
        cur.execute("SELECT * FROM broadcasts WHERE id = %s", (broadcast_id,))
        bc = cur.fetchone()
        if not bc:
            return {}
        # عدد القراء
        cur.execute("SELECT COUNT(*) FROM broadcast_reads WHERE broadcast_id = %s", (broadcast_id,))
        read_count = cur.fetchone()[0]
        # أسماء القراء
        cur.execute("""
            SELECT u.full_name, u.grade, COALESCE(u.is_my_student, FALSE) as is_my_student, br.read_at
            FROM broadcast_reads br
            JOIN users u ON br.user_id = u.user_id
            WHERE br.broadcast_id = %s
            ORDER BY br.read_at
        """, (broadcast_id,))
        readers = [dict(r) for r in cur.fetchall()]

        return {
            'broadcast_id': broadcast_id,
            'message_text': bc['message_text'],
            'target_type': bc['target_type'],
            'sent_count': bc['sent_count'],
            'read_count': read_count,
            'read_pct': round(read_count / bc['sent_count'] * 100, 1) if bc['sent_count'] > 0 else 0,
            'created_at': bc['created_at'],
            'readers': readers
        }
    except Exception as e:
        logger.error(f"[DB] Error getting broadcast stats: {e}")
        return {}
    finally:
        if cur: cur.close()
        if conn: conn.close()


def get_recent_broadcasts(limit=10):
    """قائمة آخر الإشعارات مع إحصائيات القراءة"""
    conn = connect_db()
    if not conn: return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT b.id, b.message_text, b.target_type, b.target_filter, b.sent_count, b.created_at,
                   COUNT(br.id) as read_count
            FROM broadcasts b
            LEFT JOIN broadcast_reads br ON b.id = br.broadcast_id
            GROUP BY b.id
            ORDER BY b.created_at DESC
            LIMIT %s
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"[DB] Error getting recent broadcasts: {e}")
        return []
    finally:
        if cur: cur.close()
        if conn: conn.close()


def auto_track_broadcast_read(user_id):
    """تسجيل قراءة تلقائية — يتحقق من إشعارات آخر 48 ساعة اللي ما قرأها المستخدم"""
    conn = connect_db()
    if not conn: return
    try:
        cur = conn.cursor()
        # إشعارات آخر 48 ساعة اللي ما قرأها هذا المستخدم
        cur.execute("""
            INSERT INTO broadcast_reads (broadcast_id, user_id)
            SELECT b.id, %s
            FROM broadcasts b
            WHERE b.created_at > NOW() - INTERVAL '48 hours'
            AND NOT EXISTS (
                SELECT 1 FROM broadcast_reads br 
                WHERE br.broadcast_id = b.id AND br.user_id = %s
            )
        """, (user_id, user_id))
        if cur.rowcount > 0:
            logger.info(f"[AutoTrack] User {user_id} auto-marked {cur.rowcount} broadcasts as read")
        conn.commit()
    except Exception as e:
        logger.error(f"[DB] Error auto-tracking broadcast read: {e}")
        conn.rollback()
    finally:
        if cur: cur.close()
        if conn: conn.close()
