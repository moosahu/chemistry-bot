# -*- coding: utf-8 -*-
"""Handles database schema setup and updates for the bot's own data."""

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
    """Sets up the initial database schema for bot-specific tables if they don't exist."""
    conn = connect_db()
    if conn is None:
        logger.error("[Schema Setup] Failed to connect to database. Aborting setup.")
        return False

    try:
        with conn.cursor() as cur:
            logger.info("[Schema Setup] Creating bot-specific tables if they do not exist...")

            # --- Bot Core Tables --- 

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

            # blocked_users table for admin security system
            cur.execute("""
                CREATE TABLE IF NOT EXISTS blocked_users (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL UNIQUE,
                    blocked_by BIGINT NOT NULL,
                    blocked_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    reason TEXT DEFAULT 'غير محدد',
                    is_active BOOLEAN DEFAULT TRUE NOT NULL,
                    unblocked_by BIGINT,
                    unblocked_at TIMESTAMP WITH TIME ZONE,
                    notes TEXT
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_blocked_users_user_id ON blocked_users(user_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_blocked_users_is_active ON blocked_users(is_active);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_blocked_users_blocked_at ON blocked_users(blocked_at);")
            logger.debug("[Schema Setup] Checked/Created blocked_users table and indexes.")

            # --- Content tables (courses, units, lessons, questions, options) are NOT managed by the bot --- 
            # --- They are managed by the separate API and its database --- 

            conn.commit()
            logger.info("[Schema Setup] Bot-specific initial schema setup/check completed successfully.")
            return True
    except psycopg2.Error as e:
        logger.error(f"[Schema Setup] Database error during bot-specific initial setup: {e}")
        if conn:
            conn.rollback()
        return False
    except Exception as e:
        logger.exception(f"[Schema Setup] Unexpected error during bot-specific initial setup: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()
            logger.debug("[Schema Setup] Database connection closed after setup.")

def apply_schema_updates():
    """Applies specific ALTER TABLE or other updates needed for bot tables after initial setup."""
    conn = connect_db()
    if conn is None:
        logger.error("[Schema Update] Failed to connect to database. Aborting updates.")
        return False

    try:
        with conn.cursor() as cur:
            logger.info("[Schema Update] Applying necessary schema updates for bot tables...")

            # Update 1: Add 'is_admin' column to users if it doesn't exist
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'users' AND column_name = 'is_admin'
            """)
            if not cur.fetchone():
                cur.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE;")
                # No commit here, commit at the end
                logger.info("[Schema Update] Added 'is_admin' column to 'users' table.")
            else:
                logger.debug("[Schema Update] 'is_admin' column already exists in 'users'.")

            # --- Updates for content tables (courses, units, lessons, questions, options) are NOT applied here --- 
            # --- They should be handled in the API's database migration process --- 

            conn.commit() # Commit all changes at the end
            logger.info("[Schema Update] Bot-specific schema updates applied successfully.")
            return True
    except psycopg2.Error as e:
        logger.error(f"[Schema Update] Database error during bot-specific updates: {e}")
        if conn:
            conn.rollback()
        return False
    except Exception as e:
        logger.exception(f"[Schema Update] Unexpected error during bot-specific updates: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()
            logger.debug("[Schema Update] Database connection closed after updates.")

# Run setup and updates when the module is executed directly
if __name__ == "__main__":
    logger.info("Running bot-specific database schema setup and updates directly...")
    if setup_database_schema():
        logger.info("Bot-specific initial schema setup/check successful.")
        if apply_schema_updates():
            logger.info("Bot-specific schema updates applied successfully.")
            exit(0)
        else:
            logger.error("Bot-specific schema updates failed.")
            exit(1)
    else:
        logger.error("Bot-specific initial schema setup/check failed.")
        exit(1)

