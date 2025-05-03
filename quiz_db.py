# -*- coding: utf-8 -*-
import psycopg2
import psycopg2.extras
import logging
import random

# Enhanced logging for debugging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG) # Set level to DEBUG for maximum verbosity

class QuizDatabase:
    def __init__(self, conn):
        self.conn = conn

    def _execute_query(self, query, params=None, fetch_one=False, fetch_all=False, commit=False):
        """Helper function to execute database queries."""
        if not self.conn:
            logger.error("Database connection is not available.")
            return None
        cur = None
        try:
            cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            logger.debug(f"Executing query: {cur.mogrify(query, params)}") # Log the actual query
            cur.execute(query, params)
            if commit:
                self.conn.commit()
                logger.debug("Query committed successfully.")
                return True
            result = None
            if fetch_one:
                result = cur.fetchone()
                logger.debug(f"Fetched one row: {result}")
            if fetch_all:
                result = cur.fetchall()
                logger.debug(f"Fetched {len(result) if result else 0} rows.")
            return result
        except (Exception, psycopg2.DatabaseError) as error:
            # Log the specific query and params that caused the error
            try:
                failed_query = cur.mogrify(query, params) if cur else query
            except Exception as mogrify_error:
                logger.error(f"Error formatting query for logging: {mogrify_error}")
                failed_query = query # Fallback to original query string
            logger.error(f"Database query error: {error}\nFailed Query: {failed_query}")
            if self.conn:
                self.conn.rollback()
            return None
        finally:
            if cur:
                cur.close()

    # --- User Management --- 
    def register_user(self, user_id, first_name, username):
        """Registers a new user or updates their info if they already exist."""
        # Use COALESCE for username as it might be None
        logger.info(f"[register_user] Registering/updating user_id: {user_id}, first_name: {first_name}, username: {username}")
        query = """
        INSERT INTO users (user_id, first_name, username, last_interaction_date)
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (user_id)
        DO UPDATE SET
            first_name = EXCLUDED.first_name,
            username = EXCLUDED.username,
            last_interaction_date = CURRENT_TIMESTAMP;
        """
        # Note: Assuming 'last_name' is not strictly required for registration based on bot.py call
        success = self._execute_query(query, (user_id, first_name, username), commit=True)
        if success:
            logger.info(f"[register_user] Successfully registered/updated user_id {user_id}.")
        else:
            logger.error(f"[register_user] Failed to register/update user_id {user_id}.")
        return success

    def add_or_update_user(self, user_id, username, first_name, last_name):
        """DEPRECATED? Adds a new user or updates their info and last active time. Consider using register_user."""
        logger.warning("[add_or_update_user] Called potentially deprecated function. Consider using register_user.")
        query = """
        INSERT INTO users (user_id, username, first_name, last_name, last_interaction_date)
        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (user_id)
        DO UPDATE SET
            username = EXCLUDED.username,
            first_name = EXCLUDED.first_name,
            last_name = EXCLUDED.last_name,
            last_interaction_date = CURRENT_TIMESTAMP;
        """
        return self._execute_query(query, (user_id, username, first_name, last_name), commit=True)

    # --- Structure Retrieval (NEW: Based on confirmed structure) --- 
    # Assuming these tables and columns exist as confirmed
    def get_all_courses(self):
        """Retrieves all courses for the new structure."""
        logger.info("[get_all_courses] Fetching all courses.")
        query = "SELECT course_id, name FROM courses ORDER BY course_id;" # Assuming PK is course_id
        return self._execute_query(query, fetch_all=True)

    def get_units_by_course(self, course_id):
        """Retrieves units for a specific course_id."""
        logger.info(f"[get_units_by_course] Fetching units for course_id: {course_id}")
        query = "SELECT unit_id, name FROM units WHERE course_id = %s ORDER BY unit_id;" # Assuming PK is unit_id
        return self._execute_query(query, (course_id,), fetch_all=True)

    def get_lessons_by_unit(self, unit_id):
        """Retrieves lessons for a specific unit_id."""
        logger.info(f"[get_lessons_by_unit] Fetching lessons for unit_id: {unit_id}")
        query = "SELECT lesson_id, name FROM lessons WHERE unit_id = %s ORDER BY lesson_id;" # Assuming PK is lesson_id
        return self._execute_query(query, (unit_id,), fetch_all=True)

    # --- Structure Retrieval (OLD/DEPRECATED - Added back temporarily to prevent AttributeError) --- 
    def get_all_grade_levels(self):
        """DEPRECATED: Returns empty list. Bot should use get_all_courses instead."""
        logger.warning("Called DEPRECATED function get_all_grade_levels. Bot needs update. Returning empty list.")
        return []

    def get_chapters_by_grade(self, grade_level_id):
        """DEPRECATED: Returns empty list. Bot should use get_units_by_course instead."""
        logger.warning(f"Called DEPRECATED function get_chapters_by_grade for grade_id {grade_level_id}. Bot needs update. Returning empty list.")
        return []

    def get_lessons_by_chapter(self, chapter_id):
        """DEPRECATED: Returns empty list. Bot should use get_lessons_by_unit instead."""
        logger.warning(f"Called DEPRECATED function get_lessons_by_chapter for chapter_id {chapter_id}. Bot needs update. Returning empty list.")
        return []

    # --- Question Retrieval --- 

    def _get_options_for_question(self, question_id):
        """Retrieves options for a specific question_id."""
        logger.debug(f"[_get_options_for_question] Fetching options for question_id: {question_id}")
        query = """
        SELECT option_index, option_text 
        FROM options 
        WHERE question_id = %s 
        ORDER BY option_index;
        """
        options_result = self._execute_query(query, (question_id,), fetch_all=True)
        options_list = [None] * 4 # Initialize list for 4 options
        if options_result:
            logger.debug(f"[_get_options_for_question] Raw options for question_id {question_id}: {options_result}")
            for opt in options_result:
                if 1 <= opt["option_index"] <= 4:
                    options_list[opt["option_index"] - 1] = opt["option_text"]
                else:
                    logger.warning(f"[_get_options_for_question] Invalid option_index {opt['option_index']} found for question_id {question_id}")
        else:
            logger.warning(f"[_get_options_for_question] No options found in DB for question_id: {question_id}")
            
        final_options = options_list # Keep the list of 4, including None
        logger.debug(f"[_get_options_for_question] Final options list for question_id {question_id}: {final_options}")
        return final_options

    def _format_questions_with_options(self, question_rows):
        """Formats question rows and fetches/attaches their options."""
        logger.debug(f"[_format_questions_with_options] Formatting {len(question_rows) if question_rows else 0} question rows.")
        formatted_questions = []
        if not question_rows:
            logger.debug("[_format_questions_with_options] Input question_rows is empty. Returning empty list.")
            return []
            
        for i, q_row in enumerate(question_rows):
            # Ensure q_row is a dictionary-like object
            if not hasattr(q_row, "__getitem__") or not hasattr(q_row, "keys"):
                logger.error(f"[_format_questions_with_options] Skipping row {i} because it's not a dictionary-like object: {q_row}")
                continue
                
            logger.debug(f"[_format_questions_with_options] Processing raw question row {i}: {dict(q_row)}")
            question_id = q_row.get("question_id") # Use .get for safety
            if question_id is None:
                logger.error(f"[_format_questions_with_options] Skipping row {i} due to missing question_id.")
                continue
                
            options = self._get_options_for_question(question_id)
            
            if len(options) != 4:
                logger.error(f"[_format_questions_with_options] Expected 4 options for question_id {question_id}, but got {len(options)}. Skipping question.")
                continue
                
            if all(opt is None for opt in options):
                 logger.warning(f"[_format_questions_with_options] All options are None for question_id {question_id}. Proceeding, but this might indicate an issue.")

            # Correct answer index determination logic removed as 'correct_option' column is gone.
            # The API response should ideally contain the correct answer info.
            # For now, we set it to None as quiz_db doesn't know the correct answer anymore.
            correct_answer_index = None 
            logger.warning(f"[_format_questions_with_options] Cannot determine correct answer for question_id {question_id} from DB. Relying on API response. Setting correct_answer index to None.")

            question_dict = {
                "question_id": question_id,
                "question_text": q_row.get("question_text"),
                "option1": options[0],
                "option2": options[1],
                "option3": options[2],
                "option4": options[3],
                "correct_answer": correct_answer_index, # Always None now from DB perspective
                "explanation": q_row.get("explanation"),
                "image_url": q_row.get("image_url") 
            }
            logger.debug(f"[_format_questions_with_options] Formatted question dict {i}: {question_dict}")
            
            # Removed check for correct_answer being None, as it's always None now
            if not question_dict["question_text"]:
                 logger.error(f"[_format_questions_with_options] Skipping question {question_id} due to missing text.")
                 continue
                 
            formatted_questions.append(question_dict)
            
        logger.debug(f"[_format_questions_with_options] Finished formatting. Returning {len(formatted_questions)} questions.")
        return formatted_questions

    def get_random_questions(self, limit=10):
        """Retrieves random questions (without correct answer info from DB)."""
        logger.info(f"[get_random_questions] Attempting to fetch {limit} random questions (DB query - likely unused if API works).")
        query = """
        SELECT question_id, question_text, image_url, explanation
        FROM questions
        ORDER BY RANDOM()
        LIMIT %s;
        """
        question_rows = self._execute_query(query, (limit,), fetch_all=True)
        if question_rows is None:
             logger.error("[get_random_questions] Database query failed or returned None.")
             return [] # Return empty list on DB error
        logger.info(f"[get_random_questions] Fetched {len(question_rows)} raw question rows from DB.")
        
        if not question_rows:
            logger.warning("[get_random_questions] No raw question rows found in the database for the query.")
            return []
            
        formatted_questions = self._format_questions_with_options(question_rows)
        logger.info(f"[get_random_questions] Returning {len(formatted_questions)} formatted questions after processing.")
        return formatted_questions

    # --- Filtered Question Retrieval (NEW IMPLEMENTATION - Corrected SQL) --- 

    def get_questions_by_lesson(self, lesson_id, limit=10):
        """Retrieves random questions for a specific lesson_id (without correct answer info from DB)."""
        logger.info(f"[get_questions_by_lesson] Attempting to fetch {limit} questions for lesson_id: {lesson_id} (DB query - likely unused if API works).")
        query = """
        SELECT q.question_id, q.question_text, q.image_url, q.explanation 
        FROM questions q 
        WHERE q.lesson_id = %s 
        ORDER BY RANDOM() 
        LIMIT %s;
        """
        question_rows = self._execute_query(query, (lesson_id, limit), fetch_all=True)
        if question_rows is None:
             logger.error(f"[get_questions_by_lesson] Database query failed for lesson_id {lesson_id}.")
             return []
        logger.info(f"[get_questions_by_lesson] Fetched {len(question_rows)} raw question rows for lesson_id {lesson_id}.")
        if not question_rows:
            logger.warning(f"[get_questions_by_lesson] No raw question rows found for lesson_id {lesson_id}.")
            return []
        formatted_questions = self._format_questions_with_options(question_rows)
        logger.info(f"[get_questions_by_lesson] Returning {len(formatted_questions)} formatted questions for lesson_id {lesson_id}.")
        return formatted_questions

    def get_questions_by_unit(self, unit_id, limit=10):
        """Retrieves random questions for a specific unit_id (without correct answer info from DB)."""
        logger.info(f"[get_questions_by_unit] Attempting to fetch {limit} questions for unit_id: {unit_id} (DB query - likely unused if API works).")
        query = """
        SELECT q.question_id, q.question_text, q.image_url, q.explanation 
        FROM questions q
        JOIN lessons l ON q.lesson_id = l.lesson_id
        WHERE l.unit_id = %s 
        ORDER BY RANDOM() 
        LIMIT %s;
        """
        question_rows = self._execute_query(query, (unit_id, limit), fetch_all=True)
        if question_rows is None:
             logger.error(f"[get_questions_by_unit] Database query failed for unit_id {unit_id}.")
             return []
        logger.info(f"[get_questions_by_unit] Fetched {len(question_rows)} raw question rows for unit_id {unit_id}.")
        if not question_rows:
            logger.warning(f"[get_questions_by_unit] No raw question rows found for unit_id {unit_id}.")
            return []
        formatted_questions = self._format_questions_with_options(question_rows)
        logger.info(f"[get_questions_by_unit] Returning {len(formatted_questions)} formatted questions for unit_id {unit_id}.")
        return formatted_questions

    def get_questions_by_course(self, course_id, limit=10):
        """Retrieves random questions for a specific course_id (without correct answer info from DB)."""
        logger.info(f"[get_questions_by_course] Attempting to fetch {limit} questions for course_id: {course_id} (DB query - likely unused if API works).")
        query = """
        SELECT q.question_id, q.question_text, q.image_url, q.explanation 
        FROM questions q
        JOIN lessons l ON q.lesson_id = l.lesson_id
        JOIN units u ON l.unit_id = u.unit_id
        WHERE u.course_id = %s 
        ORDER BY RANDOM() 
        LIMIT %s;
        """
        question_rows = self._execute_query(query, (course_id, limit), fetch_all=True)
        if question_rows is None:
             logger.error(f"[get_questions_by_course] Database query failed for course_id {course_id}.")
             return []
        logger.info(f"[get_questions_by_course] Fetched {len(question_rows)} raw question rows for course_id {course_id}.")
        if not question_rows:
            logger.warning(f"[get_questions_by_course] No raw question rows found for course_id {course_id}.")
            return []
        formatted_questions = self._format_questions_with_options(question_rows)
        logger.info(f"[get_questions_by_course] Returning {len(formatted_questions)} formatted questions for course_id {course_id}.")
        return formatted_questions

    # --- Quiz Results --- 
    def save_quiz_result(self, quiz_id, user_id, score, total_questions, time_taken_seconds, quiz_type, filter_id):
        """Saves the results of a completed quiz."""
        percentage = (score / total_questions) * 100.0 if total_questions > 0 else 0.0
        logger.info(f"[save_quiz_result] Saving result for quiz_id {quiz_id}, user_id {user_id}: Score={score}/{total_questions} ({percentage:.2f}%), Time={time_taken_seconds}s, Type={quiz_type}, Filter={filter_id}")
        query = """
        INSERT INTO quiz_results (quiz_id, user_id, score, total_questions, percentage, time_taken_seconds, quiz_type, filter_id, completed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP);
        """
        params = (quiz_id, user_id, score, total_questions, percentage, time_taken_seconds, quiz_type, filter_id)
        success = self._execute_query(query, params, commit=True)
        if success:
            logger.info(f"[save_quiz_result] Successfully saved result for quiz_id {quiz_id}.")
        else:
            logger.error(f"[save_quiz_result] Failed to save result for quiz_id {quiz_id}.")
        return success

    def get_user_stats(self, user_id):
        """Retrieves statistics for a specific user."""
        logger.info(f"[get_user_stats] Fetching stats for user_id: {user_id}")
        query = """
        SELECT 
            COUNT(*) as total_quizzes,
            AVG(percentage) as average_score,
            SUM(time_taken_seconds) as total_time_seconds
        FROM quiz_results
        WHERE user_id = %s;
        """
        stats = self._execute_query(query, (user_id,), fetch_one=True)
        if stats:
            logger.info(f"[get_user_stats] Stats found for user_id {user_id}: {dict(stats)}")
        else:
            logger.warning(f"[get_user_stats] No stats found for user_id {user_id} or query failed.")
        return stats

    def get_leaderboard(self, limit=10):
        """Retrieves the leaderboard based on average score."""
        logger.info(f"[get_leaderboard] Fetching top {limit} users for leaderboard.")
        query = """
        SELECT 
            r.user_id,
            COALESCE(u.username, u.first_name, CAST(r.user_id AS VARCHAR)) as user_display_name, -- Use username, then first_name, then user_id
            AVG(r.percentage) as average_score,
            COUNT(r.quiz_id) as quizzes_taken
        FROM quiz_results r
        LEFT JOIN users u ON r.user_id = u.user_id
        GROUP BY r.user_id, user_display_name
        HAVING COUNT(r.quiz_id) > 0 -- Ensure user has taken at least one quiz
        ORDER BY average_score DESC, quizzes_taken DESC
        LIMIT %s;
        """
        leaderboard = self._execute_query(query, (limit,), fetch_all=True)
        if leaderboard:
            logger.info(f"[get_leaderboard] Fetched {len(leaderboard)} users for leaderboard.")
        else:
            logger.warning("[get_leaderboard] No leaderboard data found or query failed.")
        return leaderboard

