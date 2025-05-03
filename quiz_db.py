# -*- coding: utf-8 -*-
import psycopg2
import psycopg2.extras
import logging
import random

logger = logging.getLogger(__name__)

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
            cur.execute(query, params)
            if commit:
                self.conn.commit()
                return True
            if fetch_one:
                return cur.fetchone()
            if fetch_all:
                return cur.fetchall()
            return None
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f"Database query error: {error}\nQuery: {query}\nParams: {params}")
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
    # NOTE: These might need adjustments if grade/chapter/lesson tables have different structures or PKs
    def get_all_grade_levels(self):
        query = "SELECT id, name FROM grade_levels ORDER BY id;" # Assuming 'id' PK
        return self._execute_query(query, fetch_all=True)

    def get_chapters_by_grade(self, grade_level_id):
        query = "SELECT id, name FROM chapters WHERE grade_level_id = %s ORDER BY id;" # Assuming 'id' PK
        return self._execute_query(query, (grade_level_id,), fetch_all=True)

    def get_lessons_by_chapter(self, chapter_id):
        query = "SELECT id, name FROM lessons WHERE chapter_id = %s ORDER BY id;" # Assuming 'id' PK
        return self._execute_query(query, (chapter_id,), fetch_all=True)

    # --- Question Retrieval (Updated for new DB structure) --- 

    def _get_options_for_question(self, question_id):
        """Retrieves options for a specific question_id."""
        query = """
        SELECT option_index, option_text 
        FROM options 
        WHERE question_id = %s 
        ORDER BY option_index;
        """
        options_result = self._execute_query(query, (question_id,), fetch_all=True)
        # Format options into a list like ["text1", "text2", ...]
        options_list = [None] * 4 # Assuming max 4 options
        if options_result:
            for opt in options_result:
                # Adjust index to be 0-based for list access if needed, but store based on option_index (1-4)
                if 1 <= opt['option_index'] <= 4:
                    options_list[opt['option_index'] - 1] = opt['option_text']
        # Return only the text, filtering out None if fewer than 4 options exist
        return [text for text in options_list if text is not None]

    def _format_questions_with_options(self, question_rows):
        """Formats question rows and fetches/attaches their options."""
        formatted_questions = []
        if not question_rows:
            return []
            
        for q_row in question_rows:
            question_id = q_row['question_id']
            options = self._get_options_for_question(question_id)
            
            # Ensure we have 4 options, padding with placeholders if necessary (though _get_options_for_question handles this)
            # The bot expects option1, option2 etc keys, so we reconstruct that structure
            question_dict = {
                'question_id': question_id,
                'question_text': q_row['question_text'],
                'option1': options[0] if len(options) > 0 else None,
                'option2': options[1] if len(options) > 1 else None,
                'option3': options[2] if len(options) > 2 else None,
                'option4': options[3] if len(options) > 3 else None,
                # IMPORTANT: 'correct_answer' in the DB is 'correct_option' (index 1-4)
                # The bot code expects the *index* (0-3) of the correct option in the options list.
                'correct_answer': q_row['correct_option'] - 1 if q_row['correct_option'] is not None and 1 <= q_row['correct_option'] <= len(options) else None, 
                'explanation': q_row['explanation'],
                'image_data': q_row['image_url'] # Renaming image_url to image_data for compatibility with bot code?
                                                # Or should bot code be updated to use image_url?
                                                # Let's keep image_url for now and see if bot handles it, or adjust later.
                                                # Using image_url as key for clarity.
                # 'image_url': q_row['image_url'] # Use the correct column name
            }
            # Add image_url only if it exists
            if q_row['image_url']:
                 question_dict['image_url'] = q_row['image_url']
            else:
                 question_dict['image_url'] = None # Ensure key exists even if null

            # Add explanation only if it exists
            if q_row['explanation']:
                 question_dict['explanation'] = q_row['explanation']
            else:
                 question_dict['explanation'] = None # Ensure key exists even if null

            # Validate correct_answer index
            if question_dict['correct_answer'] is None or question_dict['correct_answer'] >= len(options):
                 logger.warning(f"Invalid or missing correct_option ({q_row['correct_option']}) for question_id {question_id}. Setting correct_answer index to None.")
                 question_dict['correct_answer'] = None # Set to None if invalid

            formatted_questions.append(question_dict)
            
        return formatted_questions

    def get_random_questions(self, limit=10):
        """Retrieves random questions with their options."""
        query = """
        SELECT question_id, question_text, image_url, correct_option, explanation
        FROM questions
        ORDER BY RANDOM()
        LIMIT %s;
        """
        question_rows = self._execute_query(query, (limit,), fetch_all=True)
        return self._format_questions_with_options(question_rows)

    # --- Filtered Question Retrieval (Temporarily Disabled/Limited) --- 
    # NOTE: These functions currently cannot filter by grade/chapter/lesson 
    # because the 'questions' table lacks grade_level_id, chapter_id, lesson_id columns.
    # They will behave like get_random_questions for now, or return empty.
    # Returning empty list to avoid unexpected behavior.

    def get_questions_by_grade(self, grade_level_id, limit=10):
        """Retrieves questions for a specific grade level (Currently not supported)."""
        logger.warning("Filtering questions by grade level is not currently supported due to DB structure.")
        # Option 1: Return empty list
        return []
        # Option 2: Fallback to random questions (might be confusing for user)
        # return self.get_random_questions(limit)

    def get_questions_by_chapter(self, chapter_id, limit=10):
        """Retrieves questions for a specific chapter (Currently not supported)."""
        logger.warning("Filtering questions by chapter is not currently supported due to DB structure.")
        return []

    def get_questions_by_lesson(self, lesson_id, limit=10):
        """Retrieves questions for a specific lesson (Currently not supported)."""
        logger.warning("Filtering questions by lesson is not currently supported due to DB structure.")
        return []

    # --- Quiz Results --- 

    def save_quiz_result(self, quiz_id, user_id, score, total_questions, time_taken_seconds, quiz_type, filter_id):
        """Saves the results of a completed quiz."""
        percentage = (score / total_questions) * 100.0 if total_questions > 0 else 0.0
        query = """
        INSERT INTO quiz_results 
            (quiz_id, user_id, score, total_questions, percentage, time_taken_seconds, quiz_type, filter_id, completed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP);
        """
        params = (quiz_id, user_id, score, total_questions, percentage, time_taken_seconds, quiz_type, filter_id)
        return self._execute_query(query, params, commit=True)

    # --- Admin Functions (Partially Updated - Add/Delete need more work for options) --- 

    # Add grade/chapter/lesson assume 'id' PK - might need checking
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

    # NOTE: add_question needs significant changes to handle separate options table.
    # This version is INCOMPLETE and will NOT work correctly for adding questions.
    def add_question(self, text, opt1, opt2, opt3, opt4, correct_option_index, explanation=None, image_url=None, quiz_id=None): # Removed grade/chapter/lesson ids
        """Adds a question and its options (INCOMPLETE - Needs rework for separate options table)."""
        logger.warning("add_question function is not fully updated for the current DB structure and will likely fail.")
        # 1. Insert into questions table
        question_query = """
        INSERT INTO questions (question_text, image_url, correct_option, explanation, quiz_id) 
        VALUES (%s, %s, %s, %s, %s) RETURNING question_id;
        """
        # correct_option_index should be 1-4 as per DB
        q_params = (text, image_url, correct_option_index + 1 if correct_option_index is not None else None, explanation, quiz_id)
        q_result = self._execute_query(question_query, q_params, fetch_one=True, commit=False) # Commit after options
        
        if not q_result or 'question_id' not in q_result:
            logger.error("Failed to insert question or retrieve question_id.")
            if self.conn: self.conn.rollback()
            return None
            
        new_question_id = q_result['question_id']
        
        # 2. Insert options into options table (Needs error handling and rollback)
        options_to_insert = [opt for opt in [opt1, opt2, opt3, opt4] if opt is not None]
        option_query = "INSERT INTO options (question_id, option_index, option_text) VALUES (%s, %s, %s);"
        try:
            cur = self.conn.cursor()
            for index, option_text in enumerate(options_to_insert):
                cur.execute(option_query, (new_question_id, index + 1, option_text))
            self.conn.commit()
            cur.close()
            return new_question_id
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f"Failed to insert options for question_id {new_question_id}: {error}")
            if self.conn: self.conn.rollback()
            return None

    def delete_question(self, question_id_to_delete):
        """Deletes a question and its associated options."""
        # Need to delete from options first due to potential foreign key constraints
        option_query = "DELETE FROM options WHERE question_id = %s;"
        question_query = "DELETE FROM questions WHERE question_id = %s;"
        
        options_deleted = self._execute_query(option_query, (question_id_to_delete,), commit=False) # Commit after both deletes
        if options_deleted is None: # Check for explicit False might be better depending on _execute_query
             logger.warning(f"Failed to delete options for question_id {question_id_to_delete}. Aborting question delete.")
             if self.conn: self.conn.rollback()
             return False # Indicate failure

        question_deleted = self._execute_query(question_query, (question_id_to_delete,), commit=True) # Commit now
        
        if question_deleted:
            logger.info(f"Successfully deleted question {question_id_to_delete} and its options.")
            return True
        else:
            logger.error(f"Failed to delete question {question_id_to_delete} after deleting options (or options delete failed silently).")
            # Rollback might have happened in _execute_query already
            return False

    def get_question_by_id(self, question_id_to_get):
        """Retrieves a single question by its ID, including its options."""
        query = """
        SELECT question_id, question_text, image_url, correct_option, explanation
        FROM questions 
        WHERE question_id = %s;
        """
        question_row = self._execute_query(query, (question_id_to_get,), fetch_one=True)
        if question_row:
            # Use the formatting function which also fetches options
            formatted_list = self._format_questions_with_options([question_row])
            return formatted_list[0] if formatted_list else None
        return None

    # --- Performance Reports Functions (Unchanged, assuming quiz_results structure is correct) ---

    def get_user_overall_stats(self, user_id):
        query = """
        SELECT 
            COUNT(*) as total_quizzes,
            AVG(percentage) as avg_percentage,
            AVG(time_taken_seconds) as avg_time
        FROM quiz_results
        WHERE user_id = %s;
        """
        result = self._execute_query(query, (user_id,), fetch_one=True)
        if result and result['total_quizzes'] > 0:
            avg_time_int = int(result['avg_time']) if result['avg_time'] is not None else 0
            return {
                'total_quizzes': result['total_quizzes'],
                'avg_percentage': round(result['avg_percentage'], 2) if result['avg_percentage'] is not None else 0.0,
                'avg_time': avg_time_int
            }
        else:
            return {'total_quizzes': 0, 'avg_percentage': 0.0, 'avg_time': 0}

    def get_user_stats_by_type(self, user_id):
        query = """
        SELECT 
            quiz_type,
            AVG(percentage) as avg_percentage
        FROM quiz_results
        WHERE user_id = %s
        GROUP BY quiz_type;
        """
        results = self._execute_query(query, (user_id,), fetch_all=True)
        stats_by_type = {}
        if results:
            for row in results:
                stats_by_type[row['quiz_type']] = round(row['avg_percentage'], 2) if row['avg_percentage'] is not None else 0.0
        return stats_by_type

    def get_user_last_quizzes(self, user_id, limit=5):
        query = """
        SELECT 
            quiz_type, 
            percentage, 
            completed_at
        FROM quiz_results
        WHERE user_id = %s
        ORDER BY completed_at DESC
        LIMIT %s;
        """
        results = self._execute_query(query, (user_id, limit), fetch_all=True)
        return [dict(row) for row in results] if results else []


