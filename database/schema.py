# -*- coding: utf-8 -*-
"""Handles database schema setup and updates."""

import logging
import psycopg2

# Import config variables and connection function
try:
    from config import logger
    from .connection import connect_db # Relative import within the same package
except ImportError:
    # Fallback if run standalone or config/connection missing
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error("Failed to import config or connection. Schema setup might fail or use dummy connection.")
    # Define a dummy connect_db if needed for standalone testing
    def connect_db():
        logger.error("Dummy connect_db called!")
        return None

def setup_database_schema():
    """Sets up the initial database schema if tables don't exist.
       Combines setup logic from db_utils.py and initial table creation.
    """
    conn = connect_db()
    if conn is None:
        logger.error("[Schema Setup] Failed to connect to database. Aborting setup.")
        return False

    try:
        with conn.cursor() as cur:
            logger.info("[Schema Setup] Creating tables if they do not exist...")

            # --- Core Tables (from db_utils.py) --- 

            # users table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    first_name VARCHAR(255),
                    last_name VARCHAR(255),
                    username VARCHAR(255),
                    language_code VARCHAR(10),
                    registration_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    last_interaction_date TIMESTAMP WITH TIME ZONE,
                    is_admin BOOLEAN DEFAULT FALSE -- Added is_admin flag
                );
            """)
            logger.debug("[Schema Setup] Checked/Created users table.")

            # --- Content Structure Tables (from update_db_schema.py, adapted) --- 
            # courses (renamed from grade_levels)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS courses (
                    course_id SERIAL PRIMARY KEY,
                    name VARCHAR(100) NOT NULL UNIQUE, -- Added UNIQUE constraint
                    description TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """)
            logger.debug("[Schema Setup] Checked/Created courses table.")

            # units (renamed from chapters)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS units (
                    unit_id SERIAL PRIMARY KEY,
                    course_id INTEGER REFERENCES courses(course_id) ON DELETE CASCADE,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (course_id, name) -- Ensure unit names are unique within a course
                );
            """)
            logger.debug("[Schema Setup] Checked/Created units table.")

            # lessons
            cur.execute("""
                CREATE TABLE IF NOT EXISTS lessons (
                    lesson_id SERIAL PRIMARY KEY,
                    unit_id INTEGER REFERENCES units(unit_id) ON DELETE CASCADE,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (unit_id, name) -- Ensure lesson names are unique within a unit
                );
            """)
            logger.debug("[Schema Setup] Checked/Created lessons table.")

            # --- Quiz Related Tables (from db_utils.py, refined) --- 

            # questions table (linking to lessons)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS questions (
                    question_id SERIAL PRIMARY KEY,
                    lesson_id INTEGER REFERENCES lessons(lesson_id) ON DELETE SET NULL, -- Keep question if lesson deleted?
                    question_text TEXT NOT NULL,
                    image_url VARCHAR(512), -- Optional image URL for the question
                    -- Correct answer info is expected from API, not stored directly here?
                    -- If storing, add correct_option_index INTEGER NOT NULL CHECK (...)
                    explanation TEXT, -- Optional explanation
                    difficulty INTEGER, -- Optional difficulty level
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    -- Removed quiz_id, chapter_id, grade_level_id - link via lesson_id
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_questions_lesson_id ON questions(lesson_id);")
            logger.debug("[Schema Setup] Checked/Created questions table and index.")

            # options table (linked to questions)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS options (
                    option_id SERIAL PRIMARY KEY,
                    question_id INTEGER REFERENCES questions(question_id) ON DELETE CASCADE,
                    option_index INTEGER NOT NULL, -- 0, 1, 2, 3
                    option_text TEXT, -- Allow text to be NULL if image is used
                    option_image_url VARCHAR(512), -- Optional image URL for the option
                    is_correct BOOLEAN NOT NULL, -- Explicitly store if this option is correct
                    UNIQUE (question_id, option_index) -- Ensure option index is unique per question
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_options_question_id ON options(question_id);")
            logger.debug("[Schema Setup] Checked/Created options table and index.")

            # quiz_results table (simplified and focused)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS quiz_results (
                    result_id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    quiz_type VARCHAR(50) NOT NULL, -- e.g., 'random', 'lesson', 'unit', 'course'
                    quiz_scope_id INTEGER, -- ID of the lesson, unit, or course if applicable
                    total_questions INTEGER NOT NULL,
                    correct_count INTEGER NOT NULL,
                    wrong_count INTEGER NOT NULL,
                    skipped_count INTEGER NOT NULL,
                    score_percentage NUMERIC(5, 2) NOT NULL,
                    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
                    end_time TIMESTAMP WITH TIME ZONE NOT NULL,
                    details JSONB, -- Store question IDs, answers, etc. as JSON
                    completed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_quiz_results_user_id ON quiz_results(user_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_quiz_results_quiz_type ON quiz_results(quiz_type);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_quiz_results_completed_at ON quiz_results(completed_at);")
            logger.debug("[Schema Setup] Checked/Created quiz_results table and indexes.")

            # Removed user_quiz_attempts and user_answers as details are now in quiz_results JSONB
            # Removed quizzes table as quizzes are defined by type/scope, not separate entities

            conn.commit()
            logger.info("[Schema Setup] Initial schema setup/check completed successfully.")
            return True
    except psycopg2.Error as e:
        logger.error(f"[Schema Setup] Database error during initial setup: {e}")
        if conn:
            conn.rollback()
        return False
    except Exception as e:
        logger.exception(f"[Schema Setup] Unexpected error during initial setup: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()
            logger.debug("[Schema Setup] Database connection closed after setup.")

def apply_schema_updates():
    """Applies specific ALTER TABLE or other updates needed after initial setup.
       Based on update_db_schema.py logic, adapted for the new schema.
    """
    conn = connect_db()
    if conn is None:
        logger.error("[Schema Update] Failed to connect to database. Aborting updates.")
        return False

    try:
        with conn.cursor() as cur:
            logger.info("[Schema Update] Applying necessary schema updates...")

            # Example Update: Add 'is_admin' column to users if it doesn't exist
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'users' AND column_name = 'is_admin'
            """)
            if not cur.fetchone():
                cur.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE;")
                conn.commit()
                logger.info("[Schema Update] Added 'is_admin' column to 'users' table.")
            else:
                logger.debug("[Schema Update] 'is_admin' column already exists in 'users'.")

            # Add other ALTER statements or data migrations here as needed
            # Example: Ensure default courses exist
            cur.execute("INSERT INTO courses (name) VALUES ('الكيمياء العامة') ON CONFLICT (name) DO NOTHING;")
            # Add more default courses, units, lessons if required for initial setup

            conn.commit()
            logger.info("[Schema Update] Schema updates applied successfully.")
            return True
    except psycopg2.Error as e:
        logger.error(f"[Schema Update] Database error during updates: {e}")
        if conn:
            conn.rollback()
        return False
    except Exception as e:
        logger.exception(f"[Schema Update] Unexpected error during updates: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()
            logger.debug("[Schema Update] Database connection closed after updates.")

# Run setup and updates when the module is executed directly
if __name__ == "__main__":
    logger.info("Running database schema setup and updates directly...")
    if setup_database_schema():
        logger.info("Initial schema setup/check successful.")
        if apply_schema_updates():
            logger.info("Schema updates applied successfully.")
            exit(0)
        else:
            logger.error("Schema updates failed.")
            exit(1)
    else:
        logger.error("Initial schema setup/check failed.")
        exit(1)

