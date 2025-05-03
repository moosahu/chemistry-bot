# -*- coding: utf-8 -*-
import psycopg2
import psycopg2.extras
import logging
import random

# Enhanced logging for debugging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG) # Set level to DEBUG for maximum verbosity during this test

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

    def add_or_update_user(self, user_id, username, first_name, last_name):
        """Adds a new user or updates their info and last active time."""
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

    # --- Structure Retrieval (Assuming these tables exist and use 'id') --- 
    def get_all_grade_levels(self):
        query = "SELECT id, name FROM grade_levels ORDER BY id;"
        return self._execute_query(query, fetch_all=True)

    def get_chapters_by_grade(self, grade_level_id):
        query = "SELECT id, name FROM chapters WHERE grade_level_id = %s ORDER BY id;"
        return self._execute_query(query, (grade_level_id,), fetch_all=True)

    def get_lessons_by_chapter(self, chapter_id):
        query = "SELECT id, name FROM lessons WHERE chapter_id = %s ORDER BY id;"
        return self._execute_query(query, (chapter_id,), fetch_all=True)

    # --- Question Retrieval (Updated for new DB structure + More Debug Logging) --- 

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
                if 1 <= opt['option_index'] <= 4:
                    options_list[opt['option_index'] - 1] = opt['option_text']
                else:
                    logger.warning(f"[_get_options_for_question] Invalid option_index {opt['option_index']} found for question_id {question_id}")
        else:
            logger.warning(f"[_get_options_for_question] No options found in DB for question_id: {question_id}")
            
        # Return only the text, filtering out None if fewer than 4 options exist
        # Important: We need exactly 4 options (even if None) for the bot structure
        # final_options = [text for text in options_list if text is not None]
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
            logger.debug(f"[_format_questions_with_options] Processing raw question row {i}: {dict(q_row)}")
            question_id = q_row['question_id']
            if question_id is None:
                logger.error(f"[_format_questions_with_options] Skipping row {i} due to missing question_id.")
                continue
                
            options = self._get_options_for_question(question_id)
            
            # Check if we got exactly 4 options (even if some are None)
            if len(options) != 4:
                logger.error(f"[_format_questions_with_options] Expected 4 options for question_id {question_id}, but got {len(options)}. Skipping question.")
                continue
                
            # Check if at least one option is not None (basic sanity check)
            if all(opt is None for opt in options):
                 logger.warning(f"[_format_questions_with_options] All options are None for question_id {question_id}. Proceeding, but this might indicate an issue.")

            # Determine correct answer index (0-based)
            correct_db_index = q_row['correct_option'] # This is 1-based index from DB
            correct_answer_index = None
            if correct_db_index is not None:
                if 1 <= correct_db_index <= 4:
                    # Check if the correct option actually exists (is not None)
                    if options[correct_db_index - 1] is not None:
                        correct_answer_index = correct_db_index - 1
                        logger.debug(f"[_format_questions_with_options] Correct answer index for {question_id} set to {correct_answer_index} (DB index {correct_db_index})")
                    else:
                        logger.error(f"[_format_questions_with_options] Correct option text is None for correct_option index {correct_db_index} in question_id {question_id}. Setting correct_answer index to None.")
                else:
                    logger.error(f"[_format_questions_with_options] Invalid correct_option value ({correct_db_index}) outside range [1, 4] for question_id {question_id}. Setting correct_answer index to None.")
            else:
                 logger.warning(f"[_format_questions_with_options] Missing correct_option value for question_id {question_id}. Setting correct_answer index to None.")

            question_dict = {
                'question_id': question_id,
                'question_text': q_row['question_text'],
                'option1': options[0],
                'option2': options[1],
                'option3': options[2],
                'option4': options[3],
                'correct_answer': correct_answer_index, # 0-based index or None
                'explanation': q_row['explanation'],
                'image_url': q_row['image_url'] 
            }
            logger.debug(f"[_format_questions_with_options] Formatted question dict {i}: {question_dict}")
            
            # Final check: Ensure essential fields are present
            if not question_dict['question_text'] or question_dict['correct_answer'] is None:
                 logger.error(f"[_format_questions_with_options] Skipping question {question_id} due to missing text or invalid correct answer index.")
                 continue
                 
            formatted_questions.append(question_dict)
            
        logger.debug(f"[_format_questions_with_options] Finished formatting. Returning {len(formatted_questions)} questions.")
        return formatted_questions

    def get_random_questions(self, limit=10):
        """Retrieves random questions with their options."""
        logger.info(f"[get_random_questions] Attempting to fetch {limit} random questions.")
        query = """
        SELECT question_id, question_text, image_url, correct_option, explanation
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

    # --- Filtered Question Retrieval (Temporarily Disabled/Limited) --- 
    def get_questions_by_grade(self, grade_level_id, limit=10):
        logger.warning("Filtering questions by grade level is not currently supported due to DB structure. Returning empty list.")
        return []

    def get_questions_by_chapter(self, chapter_id, limit=10):
        logger.warning("Filtering questions by chapter is not currently supported due to DB structure. Returning empty list.")
        return []

    def get_questions_by_lesson(self, lesson_id, limit=10):
        logger.warning("Filtering questions by lesson is not currently supported due to DB structure. Returning empty list.")
        return []

    # --- Quiz Results --- 
    def save_quiz_result(self, quiz_id, user_id, score, total_questions, time_taken_seconds, quiz_type, filter_id):
        """Saves the results of a completed quiz."""
        percentage = (score / total_questions) * 100.0 if total_questions > 0 else 0.0
        logger.info(f"Saving quiz result for quiz_id {quiz_id}, user_id {user_id}. Score: {score}/{total_questions} ({percentage:.2f}%), Time: {time_taken_seconds}s")
        query = """
        INSERT INTO quiz_results 
            (quiz_id, user_id, score, total_questions, percentage, time_taken_seconds, quiz_type, filter_id, completed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP);
        """
        params = (quiz_id, user_id, score, total_questions, percentage, time_taken_seconds, quiz_type, filter_id)
        return self._execute_query(query, params, commit=True)

    # --- Admin Functions (Partially Updated - Add/Delete need more work for options) --- 
    def add_grade_level(self, name):
        query = "INSERT INTO grade_levels (name) VALUES (%s) RETURNING id;"
        result = self._execute_query(query, (name,), fetch_one=True, commit=True)
        return result["id"] if result else None

    def add_chapter(self, name, grade_level_id):
        query = "INSERT INTO chapters (name, grade_level_id) VALUES (%s, %s) RETURNING id;"
        result = self._execute_query(query, (name, grade_level_id), fetch_one=True, commit=True)
        return result["id"] if result else None

    def add_lesson(self, name, chapter_id):
        query = "INSERT INTO lessons (name, chapter_id) VALUES (%s, %s) RETURNING id;"
        result = self._execute_query(query, (name, chapter_id), fetch_one=True, commit=True)
        return result["id"] if result else None

    def add_question(self, text, opt1, opt2, opt3, opt4, correct_option_index, explanation=None, image_url=None, quiz_id=None):
        """Adds a question and its options (Needs rework for separate options table)."""
        logger.warning("add_question function is not fully updated for the current DB structure and will likely fail.")
        # ... (rest of the function remains the same, known to be incomplete)
        question_query = """
        INSERT INTO questions (question_text, image_url, correct_option, explanation, quiz_id) 
        VALUES (%s, %s, %s, %s, %s) RETURNING question_id;
        """
        q_params = (text, image_url, correct_option_index + 1 if correct_option_index is not None else None, explanation, quiz_id)
        q_result = self._execute_query(question_query, q_params, fetch_one=True, commit=False)
        if not q_result or 'question_id' not in q_result:
            logger.error("Failed to insert question or retrieve question_id.")
            if self.conn: self.conn.rollback()
            return None
        new_question_id = q_result['question_id']
        options_to_insert = [opt for opt in [opt1, opt2, opt3, opt4] if opt is not None]
        option_query = "INSERT INTO options (question_id, option_index, option_text) VALUES (%s, %s, %s);"
        try:
            cur = self.conn.cursor()
            for index, option_text in enumerate(options_to_insert):
                cur.execute(option_query, (new_question_id, index + 1, option_text))
            self.conn.commit()
            cur.close()
            logger.info(f"Successfully added question {new_question_id} and its options.")
            return new_question_id
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f"Failed to insert options for question_id {new_question_id}: {error}")
            if self.conn: self.conn.rollback()
            return None

    def delete_question(self, question_id_to_delete):
        """Deletes a question and its associated options."""
        logger.info(f"Attempting to delete question {question_id_to_delete} and its options.")
        option_query = "DELETE FROM options WHERE question_id = %s;"
        question_query = "DELETE FROM questions WHERE question_id = %s;"
        options_deleted = self._execute_query(option_query, (question_id_to_delete,), commit=False)
        # No rollback here, proceed to delete question even if options fail
        if options_deleted is None:
             logger.warning(f"Failed or no options found/deleted for question_id {question_id_to_delete}. Proceeding to delete question anyway.")

        question_deleted = self._execute_query(question_query, (question_id_to_delete,), commit=True)
        if question_deleted:
            logger.info(f"Successfully deleted question {question_id_to_delete}.")
            return True
        else:
            logger.error(f"Failed to delete question {question_id_to_delete}.")
            # Rollback might not be needed if commit=True failed, but doesn't hurt
            if self.conn: self.conn.rollback() 
            return False

    def get_question_by_id(self, question_id_to_get):
        """Retrieves a single question by its ID, including its options."""
        logger.debug(f"[get_question_by_id] Attempting to fetch question by id: {question_id_to_get}")
        query = """
        SELECT question_id, question_text, image_url, correct_option, explanation
        FROM questions 
        WHERE question_id = %s;
        """
        question_row = self._execute_query(query, (question_id_to_get,), fetch_one=True)
        if question_row:
            logger.debug(f"[get_question_by_id] Found raw question row for id {question_id_to_get}.")
            formatted_list = self._format_questions_with_options([question_row])
            if formatted_list:
                logger.debug(f"[get_question_by_id] Successfully formatted question {question_id_to_get}.")
                return formatted_list[0]
            else:
                logger.error(f"[get_question_by_id] Failed to format question {question_id_to_get} after fetching.")
                return None
        else:
            logger.warning(f"[get_question_by_id] No question found for id {question_id_to_get}.")
            return None

    # --- Performance Reports Functions --- 
    def get_user_overall_stats(self, user_id):
        query = """
        SELECT 
            COUNT(*) as total_quizzes,
            AVG(percentage) as avg_percentage,
            AVG(time_taken_seconds) as avg_time
        FROM quiz_results
        WHERE user_id = %s;
        """
        return self._execute_query(query, (user_id,), fetch_one=True)

    def get_user_stats_by_type(self, user_id):
        query = """
        SELECT 
            quiz_type,
            AVG(percentage) as avg_percentage
        FROM quiz_results
        WHERE user_id = %s
        GROUP BY quiz_type;
        """
        return self._execute_query(query, (user_id,), fetch_all=True)

    def get_user_last_quizzes(self, user_id, limit=5):
        # Updated to fetch more details for display
        query = """
        SELECT 
            quiz_type, 
            score, 
            total_questions, 
            percentage, 
            time_taken_seconds, 
            completed_at as timestamp
        FROM quiz_results
        WHERE user_id = %s
        ORDER BY completed_at DESC
        LIMIT %s;
        """
        return self._execute_query(query, (user_id, limit), fetch_all=True)


