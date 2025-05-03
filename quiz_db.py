# -*- coding: utf-8 -*-
import psycopg2
import psycopg2.extras # Moved import to top
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
            # Use DictCursor for dictionary-like row access
            cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute(query, params)
            if commit:
                self.conn.commit()
                return True # Indicate success for commit operations
            if fetch_one:
                return cur.fetchone()
            if fetch_all:
                return cur.fetchall()
            return None # Default if no fetch/commit specified
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f"Database query error: {error}\nQuery: {query}\nParams: {params}")
            if self.conn:
                self.conn.rollback() # Rollback on error
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

    # --- Structure Retrieval --- 

    def get_all_grade_levels(self):
        """Retrieves all grade levels."""
        query = "SELECT id, name FROM grade_levels ORDER BY id;"
        return self._execute_query(query, fetch_all=True)

    def get_chapters_by_grade(self, grade_level_id):
        """Retrieves chapters for a specific grade level."""
        query = "SELECT id, name FROM chapters WHERE grade_level_id = %s ORDER BY id;"
        return self._execute_query(query, (grade_level_id,), fetch_all=True)

    def get_lessons_by_chapter(self, chapter_id):
        """Retrieves lessons for a specific chapter."""
        query = "SELECT id, name FROM lessons WHERE chapter_id = %s ORDER BY id;"
        return self._execute_query(query, (chapter_id,), fetch_all=True)

    # --- Question Retrieval --- 

    def _format_questions(self, results):
        """Helper to format question results from DictCursor."""
        if not results:
            return []
        # Convert DictRow objects to simple dictionaries
        return [dict(row) for row in results]

    def get_random_questions(self, limit=10):
        """Retrieves a specified number of random questions."""
        query = """
        SELECT id, question_text, option1, option2, option3, option4, correct_answer, explanation, image_data
        FROM questions
        ORDER BY RANDOM()
        LIMIT %s;
        """
        results = self._execute_query(query, (limit,), fetch_all=True)
        return self._format_questions(results)

    def get_questions_by_grade(self, grade_level_id, limit=10):
        """Retrieves questions for a specific grade level, limited."""
        query = """
        SELECT id, question_text, option1, option2, option3, option4, correct_answer, explanation, image_data
        FROM questions
        WHERE grade_level_id = %s
        ORDER BY RANDOM() -- Still randomize within the grade
        LIMIT %s;
        """
        results = self._execute_query(query, (grade_level_id, limit), fetch_all=True)
        return self._format_questions(results)

    def get_questions_by_chapter(self, chapter_id, limit=10):
        """Retrieves questions for a specific chapter, limited."""
        query = """
        SELECT id, question_text, option1, option2, option3, option4, correct_answer, explanation, image_data
        FROM questions
        WHERE chapter_id = %s
        ORDER BY RANDOM()
        LIMIT %s;
        """
        results = self._execute_query(query, (chapter_id, limit), fetch_all=True)
        return self._format_questions(results)

    def get_questions_by_lesson(self, lesson_id, limit=10):
        """Retrieves questions for a specific lesson, limited."""
        query = """
        SELECT id, question_text, option1, option2, option3, option4, correct_answer, explanation, image_data
        FROM questions
        WHERE lesson_id = %s
        ORDER BY RANDOM()
        LIMIT %s;
        """
        results = self._execute_query(query, (lesson_id, limit), fetch_all=True)
        return self._format_questions(results)

    # --- Quiz Results --- 

    def save_quiz_result(self, quiz_id, user_id, score, total_questions, time_taken_seconds, quiz_type, filter_id):
        """Saves the results of a completed quiz."""
        if total_questions == 0:
            percentage = 0.0
        else:
            percentage = (score / total_questions) * 100.0
        
        query = """
        INSERT INTO quiz_results 
            (quiz_id, user_id, score, total_questions, percentage, time_taken_seconds, quiz_type, filter_id, completed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP);
        """
        params = (quiz_id, user_id, score, total_questions, percentage, time_taken_seconds, quiz_type, filter_id)
        return self._execute_query(query, params, commit=True)

    # --- Admin Functions (Corrected dictionary access) --- 

    def add_grade_level(self, name):
        query = "INSERT INTO grade_levels (name) VALUES (%s) RETURNING id;"
        result = self._execute_query(query, (name,), fetch_one=True, commit=True)
        return result["id"] if result else None # Corrected

    def add_chapter(self, name, grade_level_id):
        query = "INSERT INTO chapters (name, grade_level_id) VALUES (%s, %s) RETURNING id;"
        result = self._execute_query(query, (name, grade_level_id), fetch_one=True, commit=True)
        return result["id"] if result else None # Corrected

    def add_lesson(self, name, chapter_id):
        query = "INSERT INTO lessons (name, chapter_id) VALUES (%s, %s) RETURNING id;"
        result = self._execute_query(query, (name, chapter_id), fetch_one=True, commit=True)
        return result["id"] if result else None # Corrected

    def add_question(self, text, opt1, opt2, opt3, opt4, correct, explanation=None, image_data=None, grade_id=None, chapter_id=None, lesson_id=None):
        query = """
        INSERT INTO questions (question_text, option1, option2, option3, option4, correct_answer, explanation, image_data, grade_level_id, chapter_id, lesson_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id;
        """
        params = (text, opt1, opt2, opt3, opt4, correct, explanation, image_data, grade_id, chapter_id, lesson_id)
        result = self._execute_query(query, params, fetch_one=True, commit=True)
        return result["id"] if result else None # Corrected

    def delete_question(self, question_id):
        query = "DELETE FROM questions WHERE id = %s;"
        return self._execute_query(query, (question_id,), commit=True)

    def get_question_by_id(self, question_id):
        query = "SELECT * FROM questions WHERE id = %s;"
        result = self._execute_query(query, (question_id,), fetch_one=True)
        return dict(result) if result else None




    # --- Performance Reports Functions ---

    def get_user_overall_stats(self, user_id):
        """Calculates overall quiz statistics for a user."""
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
            # Convert avg_time from Decimal/float to integer seconds
            avg_time_int = int(result['avg_time']) if result['avg_time'] is not None else 0
            return {
                'total_quizzes': result['total_quizzes'],
                'avg_percentage': round(result['avg_percentage'], 2) if result['avg_percentage'] is not None else 0.0,
                'avg_time': avg_time_int
            }
        else:
            return {'total_quizzes': 0, 'avg_percentage': 0.0, 'avg_time': 0}

    def get_user_stats_by_type(self, user_id):
        """Calculates average percentage score for each quiz type for a user."""
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
        """Retrieves the details of the last few quizzes taken by a user."""
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
        # Format results directly using list comprehension with dict conversion
        return [dict(row) for row in results] if results else []

