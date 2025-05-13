"""Manages all database interactions for the Chemistry Telegram Bot.

Version 5_Plus_QuestionStatsV16_v12_CastLogFix: Adds detailed logging and get_detailed_question_stats from V16 logic for raw results from admin statistics queries
to help debug why data might appear as zero or empty.
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
        logger.info("[DB Manager Version 5_Plus_QuestionStatsV16_v12_CastLogFix] Initialized.")

    def _execute_query(self, query, params=None, fetch_one=False, fetch_all=False, commit=False):
        """Helper function to execute database queries with connection handling."""
        conn = connect_db()
        if not conn:
            logger.error("[DB Manager V5] Failed to get database connection for query.")
            return None
        
        cur = None
        result = None
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute(query, params)

            if commit:
                conn.commit()
                logger.debug("[DB Manager V5] Query committed successfully.")
                result = True
            elif fetch_one:
                result = cur.fetchone()
                # logger.debug(f"[DB Manager V5] fetch_one raw result: {result}") # Potentially too verbose
                if result: result = dict(result) # Ensure it's a dict
            elif fetch_all:
                result_list = cur.fetchall()
                # logger.debug(f"[DB Manager V5] fetch_all raw result list: {result_list}") # Potentially too verbose
                result = [dict(row) for row in result_list] if result_list else []
            
            return result
        except (Exception, psycopg2.DatabaseError) as error:
            try:
                failed_query = cur.mogrify(query, params) if cur else query
            except Exception as mogrify_error:
                logger.error(f"[DB Manager V5] Error formatting query for logging: {mogrify_error}")
                failed_query = query
            logger.error(f"[DB Manager V5] Database query error: {error}\nFailed Query (params might not be expanded): {failed_query}", exc_info=True)
            if conn:
                conn.rollback()
            return None
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    def register_or_update_user(self, user_id: int, first_name: str, last_name: str | None, username: str | None, language_code: str | None):
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
        logger.debug(f"[DB User V5] Checking admin status for user {user_id}.")
        query = "SELECT is_admin FROM users WHERE user_id = %s;"
        result = self._execute_query(query, (user_id,), fetch_one=True)
        is_admin = result["is_admin"] if result and result.get("is_admin") is True else False
        logger.debug(f"[DB User V5] Admin status for user {user_id}: {is_admin}")
        return is_admin

    def get_all_courses(self):
        logger.info("[DB Content V5] Fetching all courses.")
        query = "SELECT course_id, name, description FROM courses ORDER BY course_id;"
        return self._execute_query(query, fetch_all=True)

    def get_units_by_course(self, course_id: int):
        logger.info(f"[DB Content V5] Fetching units for course_id: {course_id}")
        query = "SELECT unit_id, name, description FROM units WHERE course_id = %s ORDER BY unit_id;"
        return self._execute_query(query, (course_id,), fetch_all=True)

    def get_lessons_by_unit(self, unit_id: int):
        logger.info(f"[DB Content V5] Fetching lessons for unit_id: {unit_id}")
        query = "SELECT lesson_id, name, description FROM lessons WHERE unit_id = %s ORDER BY lesson_id;"
        return self._execute_query(query, (unit_id,), fetch_all=True)

    def get_question_count(self, scope_type: str, scope_id: int | None = None) -> int:
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

    def start_quiz_session_and_get_id(self, user_id: int, quiz_type: str, quiz_scope_id: int | None, 
                                      quiz_name: str, total_questions: int, start_time: datetime, score: int, initial_percentage: float, initial_time_taken_seconds: int) -> str | None:
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
                           answers_details_json: str,
                           ):
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

    def get_user_overall_stats(self, user_id: int):
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
        logger.info(f"[DB Stats V5] Raw overall stats for user {user_id}: {stats}")
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
        logger.info(f"[DB Stats V5] Raw recent quiz history for user {user_id} (limit {limit}): {history}")
        if history:
            logger.info(f"[DB Stats V5] Found {len(history)} recent quizzes for user {user_id}.")
        else:
            logger.warning(f"[DB Stats V5] No recent quiz history found for user {user_id} or query failed.")
            history = [] 
        return history

    def get_leaderboard(self, limit: int = 10):
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
        logger.info(f"[DB Stats V5] Raw leaderboard data (limit {limit}): {leaderboard}")
        if leaderboard:
            logger.info(f"[DB Stats V5] Fetched {len(leaderboard)} users for leaderboard.")
        else:
            logger.warning("[DB Stats V5] No leaderboard data found or query failed.")
            leaderboard = []
        return leaderboard

    # --- Admin Statistics Functions ---
    def _get_time_filter_condition(self, time_filter="all", date_column="created_at"):
        """Helper to create WHERE clause for time filtering."""
        # Ensure date_column is not something that can cause SQL injection if it were user-provided.
        # Here it's internally controlled, so it should be safe.
        if time_filter == "today":
            return f" AND DATE({date_column}) = CURRENT_DATE "
        elif time_filter == "last_7_days":
            # Correctly includes today and the 6 previous days.
            return f" AND {date_column} >= (CURRENT_DATE - INTERVAL '6 days') AND {date_column} < (CURRENT_DATE + INTERVAL '1 day') "
        elif time_filter == "last_30_days":
            # Correctly includes today and the 29 previous days.
            return f" AND {date_column} >= (CURRENT_DATE - INTERVAL '29 days') AND {date_column} < (CURRENT_DATE + INTERVAL '1 day') "
        elif time_filter == "all_time" or time_filter == "all":
            return " " 
        else:
            logger.warning(f"[DB Admin Stats V5] Unknown time_filter: {time_filter}. Defaulting to 'all'.")
            return " "

    def get_total_users_count(self):
        logger.info("[DB Admin Stats V5] Fetching total users count.")
        query = "SELECT COUNT(user_id) as total_users FROM users;"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V5] Raw result for total_users_count: {raw_result}")
        return raw_result["total_users"] if raw_result and "total_users" in raw_result else 0

    def get_active_users_count(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V5] Fetching active users count for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "last_interaction_date")
        query = f"SELECT COUNT(DISTINCT user_id) as active_users FROM users WHERE 1=1 {time_condition};"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V5] Raw result for active_users_count ({time_filter}): {raw_result}")
        return raw_result["active_users"] if raw_result and "active_users" in raw_result else 0
        
    def get_total_quizzes_count(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V5] Fetching total quizzes completed count for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"SELECT COUNT(result_id) as total_quizzes FROM quiz_results WHERE completed_at IS NOT NULL {time_condition};"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V5] Raw result for total_quizzes_count ({time_filter}): {raw_result}")
        return raw_result["total_quizzes"] if raw_result and "total_quizzes" in raw_result else 0

    def get_average_quizzes_per_active_user(self, time_filter="all"):
        # This function relies on the two above, which now have logging.
        logger.info(f"[DB Admin Stats V5] Calculating average quizzes per active user for filter: {time_filter}")
        total_quizzes = self.get_total_quizzes_count(time_filter)
        active_users = self.get_active_users_count(time_filter)
        if active_users > 0:
            avg = round(total_quizzes / active_users, 2)
            logger.info(f"[DB Admin Stats V5] Avg quizzes per active user ({time_filter}): {avg} (Total Quizzes: {total_quizzes}, Active Users: {active_users})")
            return avg
        logger.info(f"[DB Admin Stats V5] Avg quizzes per active user ({time_filter}): 0.0 (Active Users: {active_users})")
        return 0.0

    def get_overall_average_score(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V5] Fetching overall average score for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"SELECT COALESCE(AVG(score_percentage), 0.0) as average_score FROM quiz_results WHERE completed_at IS NOT NULL AND score_percentage IS NOT NULL {time_condition};"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V5] Raw result for overall_average_score ({time_filter}): {raw_result}")
        average_score = raw_result["average_score"] if raw_result and "average_score" in raw_result else 0.0
        if average_score is not None:
            return float(average_score)
        return 0.0

    def get_score_distribution(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V5] Fetching score distribution for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"""
        SELECT 
            CASE 
                WHEN score_percentage >= 90 THEN '90-100%' 
                WHEN score_percentage >= 80 THEN '80-89%' 
                WHEN score_percentage >= 70 THEN '70-79%' 
                WHEN score_percentage >= 60 THEN '60-69%' 
                WHEN score_percentage >= 50 THEN '50-59%' 
                ELSE '0-49%' 
            END as score_range, 
            COUNT(result_id) as user_count 
        FROM quiz_results 
        WHERE completed_at IS NOT NULL AND score_percentage IS NOT NULL {time_condition}
        GROUP BY score_range 
        ORDER BY score_range DESC;
        """
        raw_results = self._execute_query(query, fetch_all=True)
        logger.info(f"[DB Admin Stats V5] Raw results for score_distribution ({time_filter}): {raw_results}")
        score_ranges = {
            '90-100%': 0, '80-89%': 0, '70-79%': 0,
            '60-69%': 0, '50-59%': 0, '0-49%': 0
        }
        if raw_results:
            for row in raw_results:
                if row["score_range"] in score_ranges: # Ensure key exists
                    score_ranges[row["score_range"]] = row["user_count"]
            logger.info(f"[DB Admin Stats V5] Processed score distribution ({time_filter}): {score_ranges}")
            return score_ranges
        else:
            logger.warning(f"[DB Admin Stats V5] No score distribution data from DB for filter: {time_filter}. Returning initialized ranges.")
            return score_ranges

    def get_quiz_completion_rate_stats(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V5] Fetching quiz completion rate stats for filter: {time_filter}")
        time_condition_started = self._get_time_filter_condition(time_filter, "start_time")
        time_condition_completed = self._get_time_filter_condition(time_filter, "completed_at")

        query_started = f"SELECT COUNT(result_id) as started_quizzes FROM quiz_results WHERE 1=1 {time_condition_started};"
        query_completed = f"SELECT COUNT(result_id) as completed_quizzes FROM quiz_results WHERE completed_at IS NOT NULL {time_condition_completed};"

        started_result_raw = self._execute_query(query_started, fetch_one=True)
        completed_result_raw = self._execute_query(query_completed, fetch_one=True)
        logger.info(f"[DB Admin Stats V5] Raw started_quizzes ({time_filter}): {started_result_raw}")
        logger.info(f"[DB Admin Stats V5] Raw completed_quizzes ({time_filter}): {completed_result_raw}")

        started_quizzes = started_result_raw["started_quizzes"] if started_result_raw and "started_quizzes" in started_result_raw else 0
        completed_quizzes = completed_result_raw["completed_quizzes"] if completed_result_raw and "completed_quizzes" in completed_result_raw else 0

        completion_rate = 0.0
        if started_quizzes > 0:
            completion_rate = (completed_quizzes / started_quizzes) * 100
        
        stats = {
            "started_quizzes": started_quizzes,
            "completed_quizzes": completed_quizzes,
            "completion_rate": round(completion_rate, 2)
        }
        logger.info(f"[DB Admin Stats V5] Processed quiz completion stats ({time_filter}): {stats}")
        return stats

    def get_question_difficulty_stats(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V5] Fetching question difficulty stats for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "qr.completed_at")
        query = f"""
        WITH question_attempts AS (
            SELECT 
                (ans_detail ->> 'question_id')::int as question_id,
                (ans_detail ->> 'question_text') as question_text,
                (ans_detail ->> 'is_correct')::boolean as is_correct
            FROM quiz_results qr, jsonb_array_elements(qr.answers_details) as ans_detail
            WHERE qr.completed_at IS NOT NULL {time_condition} AND qr.answers_details IS NOT NULL
        )
        SELECT 
            qa.question_id,
            COALESCE(MAX(qa.question_text), 'Question text not available') as question_text,
            COUNT(qa.question_id) as total_attempts,
            SUM(CASE WHEN qa.is_correct THEN 1 ELSE 0 END) as correct_answers,
            COALESCE(AVG(CASE WHEN qa.is_correct THEN 100.0 ELSE 0.0 END), 0.0) as correct_percentage
        FROM question_attempts qa
        WHERE qa.question_id IS NOT NULL
        GROUP BY qa.question_id
        ORDER BY correct_percentage ASC, total_attempts DESC; -- Added secondary sort for stability
        """
        raw_results = self._execute_query(query, fetch_all=True)
        logger.info(f"[DB Admin Stats V5] Raw results for question_difficulty_stats ({time_filter}): {raw_results}")
        if raw_results:
            # Ensure correct_percentage is float and other numbers are appropriate types
            processed_results = []
            for row in raw_results:
                row['correct_percentage'] = float(row['correct_percentage'])
                row['total_attempts'] = int(row['total_attempts'])
                row['correct_answers'] = int(row['correct_answers'])
                processed_results.append(row)
            logger.info(f"[DB Admin Stats V5] Fetched and processed {len(processed_results)} question difficulty stats for {time_filter}.")
            return processed_results
        else:
            logger.warning(f"[DB Admin Stats V5] No question difficulty data from DB for filter: {time_filter}. Returning empty list.")
            return []

    def get_average_quiz_duration(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V5] Fetching average quiz duration for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"SELECT COALESCE(AVG(time_taken_seconds), 0.0) as average_duration FROM quiz_results WHERE completed_at IS NOT NULL AND time_taken_seconds IS NOT NULL {time_condition};"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V5] Raw result for average_quiz_duration ({time_filter}): {raw_result}")
        average_duration = raw_result["average_duration"] if raw_result and "average_duration" in raw_result else 0.0
        if average_duration is not None:
            return float(average_duration)
        return 0.0

    def get_detailed_question_stats(self, time_filter="all"):
        # Version: 5_Plus_QuestionStatsAPI_v30_diag_full_hardcode_quote_fix
        logger.info(f"STAT_DEBUG: get_detailed_question_stats called with time_filter: {time_filter}")
        
        try:
            from upload.api_client import fetch_from_api, transform_api_question
            logger.info("STAT_DEBUG: Successfully imported fetch_from_api and transform_api_question from upload.api_client")
        except ImportError as e_import:
            logger.error(f"STAT_DEBUG: Failed to import from upload.api_client. Error: {e_import}. Make sure 'upload' package is in PYTHONPATH and contains api_client.py.
    ")
            return []
    
        time_filter_sql_fragment = self._get_time_filter_condition(time_filter, 'qr.completed_at')
    
        # DIAGNOSTIC: Both sql_part1 and sql_part2 are HARDCODED simple placeholder string literals
        sql_part1 = 'SELECT 0; /* SQL1_HARDCODED_DIAG */'
        sql_part2 = 'SELECT 1; /* SQL2_HARDCODED_DIAG */'
        
        if time_filter_sql_fragment and time_filter_sql_fragment.strip():
            # This logic might not make sense with placeholders but kept for structural integrity
            query_stats = sql_part1 + time_filter_sql_fragment + sql_part2 
        else:
            query_stats = sql_part1 + sql_part2
    
        log_query_snippet = query_stats[:250].replace('
    ', ' ').replace('
    ', ' ')
        logger.info(f"STAT_DEBUG: Executing SQL query for question stats (snippet): {repr(log_query_snippet)}")
        logger.info(f"STAT_DEBUG: Parameters for query: None")
        
        db_stats_results = self._execute_query(query_stats, None, fetch_all=True)
        
        if db_stats_results is None:
            logger.error("STAT_DEBUG: Failed to fetch aggregated stats from DB or no stats found (with diagnostic SQL).")
            return []
    
        detailed_stats = []
        logger.warning("STAT_DEBUG: Running with fully hardcoded diagnostic sql_part1 and sql_part2. Full processing skipped.")
        for row_idx, row in enumerate(db_stats_results):
            logger.info(f"STAT_DEBUG: Diagnostic row {row_idx}: {row}")
        return [{"diagnostic_full_hardcode_active": True, "results_count": len(db_stats_results)}]
    
        # Original processing logic is effectively bypassed by the return above
        # but kept here commented out for structural reference if needed later.
        # for row in db_stats_results:
        #     question_id = row.get('question_id')
        #     # ... (rest of the original processing logic)
        #     detailed_stats.append(stat_entry)
    
        # logger.info(f"STAT_DEBUG: Finished processing get_detailed_question_stats. Found {len(detailed_stats)} questions.")
        # return detailed_stats
