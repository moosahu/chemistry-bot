"""Manages all database interactions for the Chemistry Telegram Bot.

Version 5: Adds detailed logging for raw results from admin statistics queries
to help debug why data might appear as zero or empty.
Version 17: Adds missing admin statistics functions: get_average_quizzes_per_active_user, 
get_overall_average_score, and get_quiz_completion_rate_stats.
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
        logger.info("[DB Manager V17] Initialized.")

    def _execute_query(self, query, params=None, fetch_one=False, fetch_all=False, commit=False):
        """Helper function to execute database queries with connection handling."""
        conn = connect_db()
        if not conn:
            logger.error("[DB Manager V17] Failed to get database connection for query.")
            return None
        
        cur = None
        result = None
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute(query, params)

            if commit:
                conn.commit()
                logger.debug("[DB Manager V17] Query committed successfully.")
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
                logger.error(f"[DB Manager V17] Error formatting query for logging: {mogrify_error}")
                failed_query = query
            logger.error(f"[DB Manager V17] Database query error: {error}\nFailed Query (params might not be expanded): {failed_query}", exc_info=True)
            if conn:
                conn.rollback()
            return None
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    def register_or_update_user(self, user_id: int, first_name: str, last_name: str | None, username: str | None, language_code: str | None):
        logger.info(f"[DB User V17] Registering/updating user: id={user_id}, name={first_name}, username={username}")
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
            logger.info(f"[DB User V17] Successfully registered/updated user {user_id}.")
        else:
            logger.error(f"[DB User V17] Failed to register/update user {user_id}.")
        return success

    def is_user_admin(self, user_id: int) -> bool:
        logger.debug(f"[DB User V17] Checking admin status for user {user_id}.")
        query = "SELECT is_admin FROM users WHERE user_id = %s;"
        result = self._execute_query(query, (user_id,), fetch_one=True)
        is_admin = result["is_admin"] if result and result.get("is_admin") is True else False
        logger.debug(f"[DB User V17] Admin status for user {user_id}: {is_admin}")
        return is_admin

    def get_all_courses(self):
        logger.info("[DB Content V17] Fetching all courses.")
        query = "SELECT course_id, name, description FROM courses ORDER BY course_id;"
        return self._execute_query(query, fetch_all=True)

    def get_units_by_course(self, course_id: int):
        logger.info(f"[DB Content V17] Fetching units for course_id: {course_id}")
        query = "SELECT unit_id, name, description FROM units WHERE course_id = %s ORDER BY unit_id;"
        return self._execute_query(query, (course_id,), fetch_all=True)

    def get_lessons_by_unit(self, unit_id: int):
        logger.info(f"[DB Content V17] Fetching lessons for unit_id: {unit_id}")
        query = "SELECT lesson_id, name, description FROM lessons WHERE unit_id = %s ORDER BY lesson_id;"
        return self._execute_query(query, (unit_id,), fetch_all=True)

    def get_question_count(self, scope_type: str, scope_id: int | None = None) -> int:
        logger.info(f"[DB Questions V17] Getting question count for type=\"{scope_type}\" id={scope_id}")
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
            logger.warning(f"[DB Questions V17] Unknown scope_type for get_question_count: {scope_type}")
            return 0
            
        query = base_query + where_clause + ";"
        result = self._execute_query(query, tuple(params), fetch_one=True)
        count = result["count"] if result and "count" in result else 0
        logger.info(f"[DB Questions V17] Found {count} questions in DB for type=\"{scope_type}\" id={scope_id}")
        return count

    def start_quiz_session_and_get_id(self, user_id: int, quiz_type: str, quiz_scope_id: int | None, 
                                      quiz_name: str, total_questions: int, start_time: datetime, score: int, initial_percentage: float, initial_time_taken_seconds: int) -> str | None:
        logger.info(f"[DB Session V17] Starting new quiz session for user {user_id}, type: {quiz_type}, name: {quiz_name}, questions: {total_questions}")
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
            logger.info(f"[DB Session V17] Successfully started and logged quiz session {session_uuid} for user {user_id}.")
            return session_uuid
        else:
            logger.error(f"[DB Session V17] Failed to start and log quiz session for user {user_id}.")
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
        logger.info(f"[DB Results V17] Ending quiz session {quiz_session_uuid}: Score={score}, Wrong={wrong_answers}, Skipped={skipped_answers}, Percentage={score_percentage:.2f}%")
        
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
            logger.info(f"[DB Results V17] Successfully updated (ended) quiz session {quiz_session_uuid} in DB.")
        else:
            logger.error(f"[DB Results V17] Failed to update (end) quiz session {quiz_session_uuid} in DB.")
        return success

    def get_user_overall_stats(self, user_id: int):
        logger.info(f"[DB Stats V17] Fetching overall stats for user_id: {user_id}")
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
        logger.info(f"[DB Stats V17] Raw overall stats for user {user_id}: {stats}")
        if stats and stats.get("total_quizzes_taken", 0) > 0:
            logger.info(f"[DB Stats V17] Overall stats found for user {user_id}: {stats}")
            return stats 
        else:
            logger.warning(f"[DB Stats V17] No overall stats found for user {user_id} or query failed. Returning defaults.")
            return {
                "total_quizzes_taken": 0,
                "total_correct_answers": 0,
                "total_questions_attempted": 0,
                "average_score_percentage": 0.0,
                "highest_score_percentage": 0.0,
                "total_time_seconds": 0
            }

    def get_user_recent_quiz_history(self, user_id: int, limit: int = 5):
        logger.info(f"[DB Stats V17] Fetching recent quiz history for user_id: {user_id}, limit: {limit}")
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
        logger.info(f"[DB Stats V17] Raw recent quiz history for user {user_id} (limit {limit}): {history}")
        if history:
            logger.info(f"[DB Stats V17] Found {len(history)} recent quizzes for user {user_id}.")
        else:
            logger.warning(f"[DB Stats V17] No recent quiz history found for user {user_id} or query failed.")
            history = [] 
        return history

    def get_leaderboard(self, limit: int = 10):
        logger.info(f"[DB Stats V17] Fetching top {limit} users for leaderboard.")
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
        logger.info(f"[DB Stats V17] Raw leaderboard data (limit {limit}): {leaderboard}")
        if leaderboard:
            logger.info(f"[DB Stats V17] Fetched {len(leaderboard)} users for leaderboard.")
        else:
            logger.warning("[DB Stats V17] No leaderboard data found or query failed.")
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
            logger.warning(f"[DB Admin Stats V17] Unknown time_filter: {time_filter}. Defaulting to 'all'.")
            return " "

    def get_total_users_count(self):
        logger.info("[DB Admin Stats V17] Fetching total users count.")
        query = "SELECT COUNT(user_id) as total_users FROM users;"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V17] Raw result for total_users_count: {raw_result}")
        return raw_result["total_users"] if raw_result and "total_users" in raw_result else 0

    def get_active_users_count(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V17] Fetching active users count for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "last_interaction_date")
        query = f"SELECT COUNT(DISTINCT user_id) as active_users FROM users WHERE 1=1 {time_condition};"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V17] Raw result for active_users_count ({time_filter}): {raw_result}")
        return raw_result["active_users"] if raw_result and "active_users" in raw_result else 0
        
    def get_total_quizzes_count(self, time_filter="all"):
        # This counts COMPLETED quizzes
        logger.info(f"[DB Admin Stats V17] Fetching total COMPLETED quizzes for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"SELECT COUNT(result_id) as total_quizzes FROM quiz_results WHERE completed_at IS NOT NULL {time_condition};"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V17] Raw result for total_quizzes_count ({time_filter}): {raw_result}")
        return raw_result["total_quizzes"] if raw_result and "total_quizzes" in raw_result else 0

    def get_average_score_percentage(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V17] Fetching average score percentage for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"SELECT COALESCE(AVG(score_percentage), 0.0) as average_score FROM quiz_results WHERE completed_at IS NOT NULL {time_condition};"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V17] Raw result for average_score_percentage ({time_filter}): {raw_result}")
        return raw_result["average_score"] if raw_result and "average_score" in raw_result else 0.0

    def get_overall_average_score(self, time_filter="all") -> float:
        logger.info(f"[DB Admin Stats V17] Fetching overall average score (alias for get_average_score_percentage) for filter: {time_filter}")
        return self.get_average_score_percentage(time_filter)

    def get_average_quizzes_per_active_user(self, time_filter="all") -> float:
        logger.info(f"[DB Admin Stats V17] Fetching average quizzes per active user for filter: {time_filter}")
        time_condition_quiz = self._get_time_filter_condition(time_filter, "completed_at")
        time_condition_user = self._get_time_filter_condition(time_filter, "last_interaction_date")

        query = f"""
        WITH active_users_count AS (
            SELECT COUNT(DISTINCT user_id) as count FROM users WHERE 1=1 {time_condition_user}
        ),
        completed_quizzes_count AS (
            SELECT COUNT(result_id) as count FROM quiz_results WHERE completed_at IS NOT NULL {time_condition_quiz}
        )
        SELECT 
            CASE 
                WHEN (SELECT count FROM active_users_count) > 0 THEN 
                    CAST((SELECT count FROM completed_quizzes_count) AS FLOAT) / (SELECT count FROM active_users_count)
                ELSE 0.0 
            END as average_quizzes_per_active_user;
        """
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V17] Raw result for average_quizzes_per_active_user ({time_filter}): {raw_result}")
        return raw_result["average_quizzes_per_active_user"] if raw_result and "average_quizzes_per_active_user" in raw_result else 0.0

    def get_quiz_completion_rate_stats(self, time_filter="all") -> dict:
        logger.info(f"[DB Admin Stats V17] Fetching quiz completion rate stats for filter: {time_filter}")
        time_condition_completed = self._get_time_filter_condition(time_filter, "completed_at")
        time_condition_started = self._get_time_filter_condition(time_filter, "start_time")

        query = f"""
        SELECT 
            (SELECT COUNT(result_id) FROM quiz_results WHERE completed_at IS NOT NULL {time_condition_completed}) as completed_count,
            (SELECT COUNT(result_id) FROM quiz_results WHERE start_time IS NOT NULL {time_condition_started}) as attempted_count;
        """
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V17] Raw result for quiz_completion_rate_stats ({time_filter}): {raw_result}")

        completed_count = 0
        attempted_count = 0
        completion_rate_percentage = 0.0

        if raw_result:
            completed_count = raw_result.get("completed_count", 0)
            attempted_count = raw_result.get("attempted_count", 0)
            if attempted_count > 0:
                completion_rate_percentage = (completed_count / attempted_count) * 100
            else:
                completion_rate_percentage = 0.0 
                if completed_count == 0 and attempted_count == 0:
                     completion_rate_percentage = 0.0
        
        return {
            "completed_count": completed_count,
            "attempted_count": attempted_count,
            "completion_rate_percentage": round(completion_rate_percentage, 2)
        }

    def get_score_distribution(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V17] Fetching score distribution for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        
        query = f"""
        SELECT 
            CASE 
                WHEN score_percentage >= 0 AND score_percentage <= 10 THEN '0-10%'
                WHEN score_percentage > 10 AND score_percentage <= 20 THEN '11-20%'
                WHEN score_percentage > 20 AND score_percentage <= 30 THEN '21-30%'
                WHEN score_percentage > 30 AND score_percentage <= 40 THEN '31-40%'
                WHEN score_percentage > 40 AND score_percentage <= 50 THEN '41-50%'
                WHEN score_percentage > 50 AND score_percentage <= 60 THEN '51-60%'
                WHEN score_percentage > 60 AND score_percentage <= 70 THEN '61-70%'
                WHEN score_percentage > 70 AND score_percentage <= 80 THEN '71-80%'
                WHEN score_percentage > 80 AND score_percentage <= 90 THEN '81-90%'
                WHEN score_percentage > 90 AND score_percentage <= 100 THEN '91-100%'
                ELSE 'N/A'
            END as score_range,
            COUNT(result_id) as count
        FROM quiz_results
        WHERE completed_at IS NOT NULL {time_condition}
        GROUP BY score_range
        ORDER BY 
            CASE score_range
                WHEN '0-10%' THEN 1
                WHEN '11-20%' THEN 2
                WHEN '21-30%' THEN 3
                WHEN '31-40%' THEN 4
                WHEN '41-50%' THEN 5
                WHEN '51-60%' THEN 6
                WHEN '61-70%' THEN 7
                WHEN '71-80%' THEN 8
                WHEN '81-90%' THEN 9
                WHEN '91-100%' THEN 10
                ELSE 11
            END;
        """
        raw_result = self._execute_query(query, fetch_all=True)
        logger.info(f"[DB Admin Stats V17] Raw result for score_distribution ({time_filter}): {raw_result}")
        
        expected_ranges = ['0-10%', '11-20%', '21-30%', '31-40%', '41-50%', '51-60%', '61-70%', '71-80%', '81-90%', '91-100%']
        result_map = {item['score_range']: item['count'] for item in raw_result if item and 'score_range' in item}
        
        distribution = []
        for r in expected_ranges:
            distribution.append({'score_range': r, 'count': result_map.get(r, 0)})
            
        if not raw_result:
            logger.warning(f"[DB Admin Stats V17] No score distribution data found for filter: {time_filter}. Returning empty distribution for all ranges.")

        return distribution

    def get_questions_difficulty_distribution(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V17] Fetching questions difficulty distribution for filter: {time_filter}")
        logger.warning("[DB Admin Stats V17] get_questions_difficulty_distribution is a placeholder and not fully implemented.")
        time_condition = self._get_time_filter_condition(time_filter, "qr.completed_at")

        query = f"""
        SELECT 
            q.question_id,
            q.text as question_text,
            COUNT(DISTINCT qr.result_id) as quizzes_included_in, 
            SUM(CASE WHEN ad.value->>'is_correct' = 'true' THEN 1 ELSE 0 END) as total_correct,
            SUM(CASE WHEN ad.value->>'is_correct' = 'false' THEN 1 ELSE 0 END) as total_incorrect
        FROM questions q
        LEFT JOIN quiz_results qr ON qr.completed_at IS NOT NULL {time_condition}
        CROSS JOIN LATERAL jsonb_array_elements(qr.answers_details) ad
        WHERE (ad.value->>'question_id')::int = q.question_id 
        GROUP BY q.question_id, q.text
        ORDER BY q.question_id
        LIMIT 20; 
        """
        raw_result = self._execute_query(query, fetch_all=True) 
        logger.info(f"[DB Admin Stats V17] Raw result for question_difficulty ({time_filter}): {raw_result}")
        
        if not raw_result:
            logger.warning(f"[DB Admin Stats V17] No question difficulty data found for filter: {time_filter}. Returning empty list.")
            return []
        return raw_result

    def get_user_engagement_metrics(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V17] Fetching user engagement metrics for filter: {time_filter}")
        time_condition_interaction = self._get_time_filter_condition(time_filter, "last_interaction_date")
        time_condition_quiz = self._get_time_filter_condition(time_filter, "completed_at")

        query = f"""
        SELECT 
            (SELECT COUNT(DISTINCT user_id) FROM users WHERE 1=1 {time_condition_interaction}) as active_users,
            (SELECT COUNT(result_id) FROM quiz_results WHERE completed_at IS NOT NULL {time_condition_quiz}) as total_completed_quizzes,
            (SELECT COALESCE(AVG(time_taken_seconds), 0.0) FROM quiz_results WHERE completed_at IS NOT NULL AND time_taken_seconds IS NOT NULL {time_condition_quiz}) as average_quiz_duration_seconds;
        """
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V17] Raw result for user_engagement_metrics ({time_filter}): {raw_result}")
        
        if not raw_result:
            logger.warning(f"[DB Admin Stats V17] No user engagement data found for filter: {time_filter}. Returning defaults.")
            return {"active_users": 0, "total_completed_quizzes": 0, "average_quiz_duration_seconds": 0.0}
        return raw_result

# Example usage (for testing, not part of the class normally)
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger.info("Testing DatabaseManager standalone...")
    db_manager = DatabaseManager()

    logger.info(f"Total users: {db_manager.get_total_users_count()}")
    logger.info(f"Active users (today): {db_manager.get_active_users_count('today')}")
    logger.info(f"Total quizzes (all time): {db_manager.get_total_quizzes_count('all')}")
    logger.info(f"Average score (last 7 days): {db_manager.get_average_score_percentage('last_7_days')}")
    logger.info(f"Score Distribution (all time): {db_manager.get_score_distribution('all')}")
    logger.info(f"Quiz Completion Rate (all time): {db_manager.get_quiz_completion_rate_stats('all')}")
    logger.info(f"Average Quizzes per Active User (all time): {db_manager.get_average_quizzes_per_active_user('all')}")
    logger.info(f"Question Difficulty (all time): {db_manager.get_questions_difficulty_distribution('all')}") 
    logger.info(f"User Engagement (all time): {db_manager.get_user_engagement_metrics('all')}")

    logger.info("Standalone test finished.")




DB_MANAGER = DatabaseManager()
