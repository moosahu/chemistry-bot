# -*- coding: utf-8 -*-
import psycopg2
import logging
import time

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 5 # seconds

def connect_db(database_url):
    """Establishes a connection to the PostgreSQL database with retries."""
    conn = None
    retries = 0
    while retries < MAX_RETRIES:
        try:
            # Correctly call connect with sslmode=\'require\'
            conn = psycopg2.connect(database_url, sslmode=\'require\')
            logger.info("Database connection established successfully.")
            return conn
        except psycopg2.OperationalError as e:
            retries += 1
            logger.error(f"Database connection failed (Attempt {retries}/{MAX_RETRIES}): {e}")
            if retries < MAX_RETRIES:
                logger.info(f"Retrying connection in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
            else:
                logger.critical("Max retries reached. Could not connect to the database.")
                return None
        except Exception as e:
            # Catch any other unexpected errors during connection
            logger.critical(f"An unexpected error occurred during database connection: {e}")
            return None
    return None # Should not be reached if MAX_RETRIES > 0, but good practice

def setup_database(conn):
    """Creates necessary tables if they don\t exist."""
    if not conn:
        logger.error("Cannot setup database: No connection.")
        return

    # Use triple quotes for multi-line SQL commands for clarity and safety
    commands = (
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username VARCHAR(255),
            first_name VARCHAR(255),
            last_name VARCHAR(255),
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS grade_levels (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) UNIQUE NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS chapters (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            grade_level_id INTEGER REFERENCES grade_levels(id) ON DELETE CASCADE,
            UNIQUE (name, grade_level_id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS lessons (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            chapter_id INTEGER REFERENCES chapters(id) ON DELETE CASCADE,
            UNIQUE (name, chapter_id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS questions (
            id SERIAL PRIMARY KEY,
            question_text TEXT NOT NULL,
            option1 TEXT NOT NULL,
            option2 TEXT NOT NULL,
            option3 TEXT NOT NULL,
            option4 TEXT NOT NULL,
            correct_answer INTEGER NOT NULL CHECK (correct_answer BETWEEN 1 AND 4),
            explanation TEXT,
            image_data BYTEA, -- Store image as binary data
            grade_level_id INTEGER REFERENCES grade_levels(id) ON DELETE SET NULL,
            chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
            lesson_id INTEGER REFERENCES lessons(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS quiz_results (
            result_id SERIAL PRIMARY KEY,
            quiz_id BIGINT NOT NULL, -- Identifier for a specific quiz instance
            user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            score INTEGER NOT NULL,
            total_questions INTEGER NOT NULL,
            percentage REAL, -- Calculated percentage
            time_taken_seconds INTEGER,
            quiz_type VARCHAR(50), -- e.g., \'random\', \'grade\', \'chapter\', \'lesson\'
            filter_id INTEGER, -- ID of the grade/chapter/lesson if applicable
            completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        # Add indexes for faster lookups
        """CREATE INDEX IF NOT EXISTS idx_questions_grade ON questions (grade_level_id);""",
        """CREATE INDEX IF NOT EXISTS idx_questions_chapter ON questions (chapter_id);""",
        """CREATE INDEX IF NOT EXISTS idx_questions_lesson ON questions (lesson_id);""",
        """CREATE INDEX IF NOT EXISTS idx_quiz_results_user ON quiz_results (user_id);"""
    )
    cur = None
    try:
        cur = conn.cursor()
        for command in commands:
            # Ensure command is not empty before executing
            if command and command.strip():
                cur.execute(command)
        conn.commit()
        logger.info("Database setup/check completed successfully.")
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"Error during database setup: {error}")
        if conn:
            conn.rollback() # Rollback changes on error
    finally:
        if cur:
            cur.close()

# Note: Removed the example usage block for clarity in production code

