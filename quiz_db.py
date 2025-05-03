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

    # --- Structure Retrieval (Updated based on confirmed structure) --- 
    # Assuming these tables and columns exist as confirmed
    def get_all_courses(self):
        query = "SELECT course_id, name FROM courses ORDER BY course_id;" # Assuming PK is course_id
        return self._execute_query(query, fetch_all=True)

    def get_units_by_course(self, course_id):
        query = "SELECT unit_id, name FROM units WHERE course_id = %s ORDER BY unit_id;" # Assuming PK is unit_id
        return self._execute_query(query, (course_id,), fetch_all=True)

    def get_lessons_by_unit(self, unit_id):
        query = "SELECT lesson_id, name FROM lessons WHERE unit_id = %s ORDER BY lesson_id;" # Assuming PK is lesson_id
        return self._execute_query(query, (unit_id,), fetch_all=True)

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
                if 1 <= opt['option_index'] <= 4:
                    options_list[opt['option_index'] - 1] = opt['option_text']
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
            if not hasattr(q_row, '__getitem__') or not hasattr(q_row, 'keys'):
                logger.error(f"[_format_questions_with_options] Skipping row {i} because it's not a dictionary-like object: {q_row}")
                continue
                
            logger.debug(f"[_format_questions_with_options] Processing raw question row {i}: {dict(q_row)}")
            question_id = q_row.get('question_id') # Use .get for safety
            if question_id is None:
                logger.error(f"[_format_questions_with_options] Skipping row {i} due to missing question_id.")
                continue
                
            options = self._get_options_for_question(question_id)
            
            if len(options) != 4:
                logger.error(f"[_format_questions_with_options] Expected 4 options for question_id {question_id}, but got {len(options)}. Skipping question.")
                continue
                
            if all(opt is None for opt in options):
                 logger.warning(f"[_format_questions_with_options] All options are None for question_id {question_id}. Proceeding, but this might indicate an issue.")

            correct_db_index = q_row.get('correct_option') # 1-based index from DB
            correct_answer_index = None
            if correct_db_index is not None:
                if 1 <= correct_db_index <= 4:
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
                'question_text': q_row.get('question_text'),
                'option1': options[0],
                'option2': options[1],
                'option3': options[2],
                'option4': options[3],
                'correct_answer': correct_answer_index, # 0-based index or None
                'explanation': q_row.get('explanation'),
                'image_url': q_row.get('image_url') 
            }
            logger.debug(f"[_format_questions_with_options] Formatted question dict {i}: {question_dict}")
            
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

    # --- Filtered Question Retrieval (NEW IMPLEMENTATION) --- 

    def get_questions_by_lesson(self, lesson_id, limit=10):
        """Retrieves random questions for a specific lesson_id."""
        logger.info(f"[get_questions_by_lesson] Attempting to fetch {limit} questions for lesson_id: {lesson_id}")
        query = """
        SELECT q.question_id, q.question_text, q.image_url, q.correct_option, q.explanation 
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
        """Retrieves random questions for a specific unit_id."""
        logger.info(f"[get_questions_by_unit] Attempting to fetch {limit} questions for unit_id: {unit_id}")
        # Assuming lessons table has 'lesson_id' (PK) and 'unit_id' (FK)
        # Assuming questions table has 'lesson_id' (FK)
        query = """
        SELECT q.question_id, q.question_text, q.image_url, q.correct_option, q.explanation 
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
        """Retrieves random questions for a specific course_id."""
        logger.info(f"[get_questions_by_course] Attempting to fetch {limit} questions for course_id: {course_id}")
        # Assuming units table has 'unit_id' (PK) and 'course_id' (FK)
        # Assuming lessons table has 'lesson_id' (PK) and 'unit_id' (FK)
        # Assuming questions table has 'lesson_id' (FK)
        query = """
        SELECT q.question_id, q.question_text, q.image_url, q.correct_option, q.explanation 
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
        logger.info(f"Saving quiz result for quiz_id {quiz_id}, user_id {user_id}. Score: {score}/{total_questions} ({percentage:.2f}%), Time: {time_taken_seconds}s")
        query = """
        INSERT INTO quiz_results 
            (quiz_id, user_id, score, total_questions, percentage, time_taken_seconds, quiz_type, filter_id, completed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP);
        """
        params = (quiz_id, user_id, score, total_questions, percentage, time_taken_seconds, quiz_type, filter_id)
        return self._execute_query(query, params, commit=True)

    # --- Admin Functions (Partially Updated - Add needs more work) --- 
    # Assuming add functions for course, unit, lesson are needed
    def add_course(self, name):
        query = "INSERT INTO courses (name) VALUES (%s) RETURNING course_id;" # Assuming PK is course_id
        result = self._execute_query(query, (name,), fetch_one=True, commit=True)
        return result["course_id"] if result else None

    def add_unit(self, name, course_id):
        query = "INSERT INTO units (name, course_id) VALUES (%s, %s) RETURNING unit_id;" # Assuming PK is unit_id
        result = self._execute_query(query, (name, course_id), fetch_one=True, commit=True)
        return result["unit_id"] if result else None

    def add_lesson(self, name, unit_id):
        # Updated to take unit_id based on confirmed structure
        query = "INSERT INTO lessons (name, unit_id) VALUES (%s, %s) RETURNING lesson_id;" # Assuming PK is lesson_id
        result = self._execute_query(query, (name, unit_id), fetch_one=True, commit=True)
        return result["lesson_id"] if result else None

    def add_question(self, text, opt1, opt2, opt3, opt4, correct_option_index, lesson_id, explanation=None, image_url=None):
        """Adds a question and its options to the correct lesson."""
        logger.info(f"Attempting to add question to lesson_id: {lesson_id}")
        # Ensure correct_option_index is valid (0-3) before converting to 1-based
        correct_db_index = None
        if correct_option_index is not None and 0 <= correct_option_index <= 3:
             correct_db_index = correct_option_index + 1
        else:
             logger.error(f"Invalid correct_option_index ({correct_option_index}) provided. Must be 0-3.")
             return None # Or handle error appropriately
             
        question_query = """
        INSERT INTO questions (question_text, image_url, correct_option, explanation, lesson_id) 
        VALUES (%s, %s, %s, %s, %s) RETURNING question_id;
        """
        q_params = (text, image_url, correct_db_index, explanation, lesson_id)
        q_result = self._execute_query(question_query, q_params, fetch_one=True, commit=False) # Commit after options
        
        if not q_result or 'question_id' not in q_result:
            logger.error("Failed to insert question or retrieve question_id.")
            if self.conn: self.conn.rollback()
            return None
            
        new_question_id = q_result['question_id']
        options_list = [opt1, opt2, opt3, opt4]
        option_query = "INSERT INTO options (question_id, option_index, option_text) VALUES (%s, %s, %s);"
        
        try:
            cur = self.conn.cursor()
            for index, option_text in enumerate(options_list):
                if option_text is not None: # Only insert non-null options
                    cur.execute(option_query, (new_question_id, index + 1, option_text))
                else:
                    # Decide if you want to insert NULL or skip. Skipping seems safer.
                    logger.debug(f"Skipping insertion for option index {index+1} as it is None.")
            self.conn.commit()
            cur.close()
            logger.info(f"Successfully added question {new_question_id} to lesson {lesson_id} and its options.")
            return new_question_id
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f"Failed to insert options for question_id {new_question_id}: {error}")
            if self.conn: self.conn.rollback()
            return None

    def delete_question(self, question_id_to_delete):
        """Deletes a question and its associated options."""
        logger.info(f"Attempting to delete question {question_id_to_delete} and its options.")
        # Also delete any quiz results associated with this specific question if needed?
        # result_query = "DELETE FROM quiz_results WHERE ??? = %s;" # How are results linked?
        option_query = "DELETE FROM options WHERE question_id = %s;"
        question_query = "DELETE FROM questions WHERE question_id = %s;"
        
        # Use a transaction
        cur = None
        try:
            cur = self.conn.cursor()
            # Delete options first (foreign key constraint)
            cur.execute(option_query, (question_id_to_delete,))
            options_deleted_count = cur.rowcount
            logger.debug(f"Deleted {options_deleted_count} options for question_id {question_id_to_delete}.")
            
            # Then delete the question
            cur.execute(question_query, (question_id_to_delete,))
            question_deleted_count = cur.rowcount
            logger.debug(f"Deleted {question_deleted_count} question(s) for question_id {question_id_to_delete}.")
            
            if question_deleted_count > 0:
                self.conn.commit()
                logger.info(f"Successfully deleted question {question_id_to_delete} and its options.")
                return True
            else:
                # Question might not have existed
                logger.warning(f"Question {question_id_to_delete} not found for deletion.")
                self.conn.rollback() # Rollback if question wasn't found (though options might be deleted)
                return False
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f"Error deleting question {question_id_to_delete}: {error}")
            if self.conn: self.conn.rollback()
            return False
        finally:
            if cur:
                cur.close()

    def get_question_by_id(self, question_id_to_get):
        """Retrieves a single question by its ID, including its options."""
        logger.debug(f"[get_question_by_id] Attempting to fetch question_id: {question_id_to_get}")
        query = """
        SELECT question_id, question_text, image_url, correct_option, explanation, lesson_id
        FROM questions
        WHERE question_id = %s;
        """
        question_row = self._execute_query(query, (question_id_to_get,), fetch_one=True)
        if not question_row:
            logger.warning(f"[get_question_by_id] Question with ID {question_id_to_get} not found.")
            return None
            
        # Use list wrapper for compatibility with _format_questions_with_options
        formatted_questions = self._format_questions_with_options([question_row]) 
        
        if formatted_questions:
            logger.info(f"[get_question_by_id] Successfully retrieved and formatted question {question_id_to_get}.")
            return formatted_questions[0] # Return the single dictionary
        else:
            logger.error(f"[get_question_by_id] Failed to format question {question_id_to_get} after retrieval.")
            return None

    # --- Utility/Stats Functions (Example) ---
    def get_user_stats(self, user_id):
        """Retrieves quiz statistics for a specific user."""
        query = """
        SELECT 
            COUNT(*) as total_quizzes,
            AVG(percentage) as average_score,
            SUM(time_taken_seconds) as total_time
        FROM quiz_results
        WHERE user_id = %s;
        """
        return self._execute_query(query, (user_id,), fetch_one=True)


