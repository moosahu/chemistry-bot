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

    def save_quiz_result(self, 
                           quiz_id_uuid: str, 
                           user_id: int, 
                           correct_count: int, 
                           wrong_count: int, 
                           skipped_count: int,
                           score_percentage_calculated: float, 
                           start_time_original: datetime | None, 
                           end_time: datetime, 
                           answers_details_list: list, 
                           quiz_type_for_log: str 
                           ):
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
        WHERE r.completed_at IS NOT NULL
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
            return f" AND {date_column} >= CURRENT_DATE - INTERVAL '7 days' AND {date_column} < CURRENT_DATE + INTERVAL '1 day' "
        elif time_filter == "last_30_days":
            return f" AND {date_column} >= CURRENT_DATE - INTERVAL '30 days' AND {date_column} < CURRENT_DATE + INTERVAL '1 day' "
        elif time_filter == "all":
            return " " # Returns a space to be appended, ensuring valid SQL
        else:
            logger.warning(f"[DB Admin Stats] Unknown time_filter: {time_filter}. Defaulting to 'all'.")
            return " " # Default to all if filter is unknown

    def get_total_users_count(self):
        logger.info("[DB Admin Stats] Fetching total users count.")
        query = "SELECT COUNT(user_id) as total_users FROM users;"
        result = self._execute_query(query, fetch_one=True)
        return result["total_users"] if result and "total_users" in result else 0

    def get_active_users_count(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching active users count for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "last_interaction_date")
        where_clause = "WHERE 1=1" + time_condition 
        query = f"SELECT COUNT(DISTINCT user_id) as active_users FROM users {where_clause};"
        result = self._execute_query(query, fetch_one=True)
        return result["active_users"] if result and "active_users" in result else 0

    # Renamed from get_total_quizzes_taken_count to match expected call
    def get_total_quizzes_count(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching total quizzes taken count for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        where_clause = "WHERE completed_at IS NOT NULL" + time_condition
        query = f"SELECT COUNT(result_id) as total_quizzes FROM quiz_results {where_clause};"
        result = self._execute_query(query, fetch_one=True)
        return result["total_quizzes"] if result and "total_quizzes" in result else 0

    def get_overall_average_score(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching overall average score for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        where_clause = "WHERE completed_at IS NOT NULL" + time_condition
        query = f"SELECT COALESCE(AVG(score_percentage), 0.0) as average_score FROM quiz_results {where_clause};"
        result = self._execute_query(query, fetch_one=True)
        return result["average_score"] if result and "average_score" in result else 0.0

    def get_average_quiz_duration(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching average quiz duration for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        # Ensure time_taken_seconds is not NULL for averaging
        where_clause = "WHERE completed_at IS NOT NULL AND time_taken_seconds IS NOT NULL" + time_condition
        query = f"SELECT COALESCE(AVG(time_taken_seconds), 0) as average_duration FROM quiz_results {where_clause};"
        result = self._execute_query(query, fetch_one=True)
        # Return as integer or float, ensure it's a number
        avg_duration = result["average_duration"] if result and "average_duration" in result else 0
        return int(avg_duration) if avg_duration is not None else 0

    def get_average_quizzes_per_active_user(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching average quizzes per active user for filter: {time_filter}")
        total_quizzes = self.get_total_quizzes_count(time_filter)
        active_users = self.get_active_users_count(time_filter) # Assuming last_interaction_date for active users
        if active_users == 0:
            return 0.0
        return round(total_quizzes / active_users, 2)

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
            
        return {
            "started_quizzes": started_count,
            "completed_quizzes": completed_count,
            "completion_rate": completion_rate
        }

    def get_question_difficulty_stats(self, time_filter="all", limit=3):
        logger.info(f"[DB Admin Stats] Fetching question difficulty stats for filter: {time_filter}, limit: {limit}")
        time_condition = self._get_time_filter_condition(time_filter, "qr.completed_at")
        
        base_query = """
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
        LEFT JOIN questions q ON q.question_id::TEXT = ad.question_id -- Ensure correct join type for question_id
        WHERE qr.completed_at IS NOT NULL AND qr.answers_details IS NOT NULL
        {time_condition}
        GROUP BY ad.question_id, q.question_text
        HAVING COUNT(ad.question_id) > 0
        """
        
        # Most difficult (highest error_percentage)
        query_difficult = base_query + " ORDER BY error_percentage DESC, times_answered DESC LIMIT %s;"
        most_difficult = self._execute_query(query_difficult, (limit,), fetch_all=True)
        
        # Easiest (highest correct_percentage)
        query_easiest = base_query + " ORDER BY correct_percentage DESC, times_answered DESC LIMIT %s;"
        easiest = self._execute_query(query_easiest, (limit,), fetch_all=True)
        
        return {
            "most_difficult": most_difficult if most_difficult else [],
            "easiest": easiest if easiest else []
        }

    def get_unit_engagement_stats(self, time_filter="all", limit=5):
        logger.info(f"[DB Admin Stats] Fetching unit engagement stats for filter: {time_filter}, limit: {limit}")
        time_condition = self._get_time_filter_condition(time_filter, "qr.completed_at")
        
        # This query assumes quiz_name might contain unit information or filter_id refers to unit_id
        # Adjust based on how units are associated with quizzes (e.g., via quiz_type or filter_id)
        # For this example, let's assume filter_id is unit_id when quiz_type is 'unit_quiz'
        query = f"""
        SELECT 
            qr.filter_id as unit_id, 
            u.name as unit_name,
            COUNT(qr.result_id) as quizzes_taken,
            AVG(qr.score_percentage) as average_score
        FROM quiz_results qr
        JOIN units u ON qr.filter_id = u.unit_id AND qr.quiz_type LIKE '%%unit%%' -- Example condition
        WHERE qr.completed_at IS NOT NULL {time_condition}
        GROUP BY qr.filter_id, u.name
        ORDER BY quizzes_taken DESC, average_score DESC
        LIMIT %s;
        """
        # The above query is an example and needs to be adapted to your actual schema for unit quizzes.
        # If filter_id does not store unit_id, or quiz_type is different, this needs adjustment.
        # A more robust way might involve parsing quiz_name or having a dedicated column.
        # For now, this is a placeholder structure.
        # Example: if quiz_name is 'Unit X Quiz', you might parse 'Unit X'

        # Placeholder if the above is too complex or schema-dependent for now:
        # Fallback: Get most popular quiz_types or quiz_names if direct unit linkage is hard.
        query_popular_quizzes = f"""
        SELECT 
            quiz_name, 
            COUNT(result_id) as times_taken,
            AVG(score_percentage) as average_score
        FROM quiz_results
        WHERE completed_at IS NOT NULL {time_condition}
        GROUP BY quiz_name
        ORDER BY times_taken DESC, average_score DESC
        LIMIT %s;
        """
        popular_quizzes = self._execute_query(query_popular_quizzes, (limit,), fetch_all=True)

        # For now, returning popular quizzes as a proxy for unit engagement until schema is clarified
        return {
            "popular_units_or_quizzes": popular_quizzes if popular_quizzes else [] 
            # Ideally, this would be structured like: {"unit_id": X, "unit_name": Y, "quizzes_taken": Z, "average_score": A}
        }

    def get_user_activity_summary(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching user activity summary for filter: {time_filter}")
        time_condition_quiz = self._get_time_filter_condition(time_filter, "completed_at")
        time_condition_interaction = self._get_time_filter_condition(time_filter, "last_interaction_date")

        query = f"""
        SELECT 
            COUNT(DISTINCT CASE WHEN qr.completed_at IS NOT NULL {time_condition_quiz} THEN qr.user_id ELSE NULL END) as users_took_quiz,
            COUNT(DISTINCT CASE WHEN u.last_interaction_date IS NOT NULL {time_condition_interaction} THEN u.user_id ELSE NULL END) as users_interacted
        FROM users u
        LEFT JOIN quiz_results qr ON u.user_id = qr.user_id;
        """
        # This query is a simplified version. A more accurate one might need to consider the time filter on both tables carefully.
        # For instance, users who interacted in the period vs users who took quizzes in the period.
        # The current query counts users who took a quiz (within filter) and users who interacted (within filter) separately.
        
        # A simpler approach for active users (who took a quiz) in the period:
        query_active_quiz_takers = f"""
            SELECT COUNT(DISTINCT user_id) as active_quiz_takers
            FROM quiz_results
            WHERE completed_at IS NOT NULL {time_condition_quiz};
        """
        active_takers_result = self._execute_query(query_active_quiz_takers, fetch_one=True)
        active_quiz_takers = active_takers_result['active_quiz_takers'] if active_takers_result else 0

        total_users = self.get_total_users_count()
        # Active users based on any interaction (already have get_active_users_count)
        general_active_users = self.get_active_users_count(time_filter)

        return {
            "total_users": total_users,
            "active_users_general": general_active_users, # Based on last_interaction_date
            "active_users_took_quiz": active_quiz_takers # Based on completing a quiz in the period
        }


# Example usage (for testing purposes, typically not here)
if __name__ == '__main__':
    # This section would require a live database connection and proper config setup to run.
    # It's primarily for illustration or direct script testing if configured.
    logger.info("DatabaseManager script executed directly. (For testing/illustration)")
    
    # To test, you would need to:
    # 1. Ensure your config.py and connection.py are accessible and correct.
    # 2. Have a PostgreSQL database running with the schema applied.
    # 3. Potentially mock the connect_db or have it connect to a test DB.

    # db_manager = DatabaseManager()
    # print(f"Total users: {db_manager.get_total_users_count()}")
    # print(f"Active users (today): {db_manager.get_active_users_count('today')}")
    # print(f"Total quizzes (all time): {db_manager.get_total_quizzes_count('all')}")
    # print(f"Total quizzes (last 7 days): {db_manager.get_total_quizzes_count('last_7_days')}")
    # print(f"Overall Average Score (all time): {db_manager.get_overall_average_score('all')}")
    # print(f"Overall Average Score (today): {db_manager.get_overall_average_score('today')}")
    # print(f"Average Quiz Duration (all time): {db_manager.get_average_quiz_duration('all')} seconds")
    # print(f"Average Quiz Duration (last 30 days): {db_manager.get_average_quiz_duration('last_30_days')} seconds")
    # print(f"Avg quizzes per active user (today): {db_manager.get_average_quizzes_per_active_user('today')}")
    # print(f"Quiz completion rate (all): {db_manager.get_quiz_completion_rate_stats('all')}") 
    # question_stats = db_manager.get_question_difficulty_stats('all', limit=2)
    # print(f"Question difficulty (all): Most difficult: {question_stats['most_difficult']}, Easiest: {question_stats['easiest']}")
    # print(f"Unit engagement (all): {db_manager.get_unit_engagement_stats('all', limit=3)}")
    # print(f"User activity summary (all): {db_manager.get_user_activity_summary('all')}")




# Create an instance of the DatabaseManager for other modules to import
DB_MANAGER = DatabaseManager()

