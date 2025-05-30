# db_setup.py (SQLAlchemy version, adapted from user's psycopg2 version with original tables)
import os
import logging
from sqlalchemy import create_engine, Column, BigInteger, Integer, String, Text, TIMESTAMP, Boolean, ForeignKey, MetaData, Table, Index, func, text as sql_text
from sqlalchemy.dialects.postgresql import BIGINT as PG_BIGINT, TEXT as PG_TEXT, TIMESTAMP as PG_TIMESTAMP # For specific PG types if needed

# Configure logging
logger = logging.getLogger(__name__)

# --- Database Connection Parameters (DATABASE_URL takes precedence) ---
def get_database_url():
    """Gets the database URL, preferring DATABASE_URL env var, then constructing from parts."""
    database_url_env = os.environ.get("DATABASE_URL")
    if database_url_env:
        if database_url_env.startswith("postgres://"):
            database_url_env = database_url_env.replace("postgres://", "postgresql://", 1)
        _url_prefix_for_log = database_url_env.split("@")[0]
        logger.info(f"Using DATABASE_URL from environment: {_url_prefix_for_log}@...")
        return database_url_env

    # Fallback to individual components if DATABASE_URL is not set (as in user's original file)
    db_host = os.environ.get("DB_HOST", "dpg-d09mk5p5pdvs73dv4qeg-a.oregon-postgres.render.com")
    db_name = os.environ.get("DB_NAME", "chemistry_db")
    db_user = os.environ.get("DB_USER", "chemistry_db_user")
    db_password = os.environ.get("DB_PASSWORD", "2ewIvDpOHiKe8pFVVz15pba6FVDTKaB1")
    
    if not all([db_host, db_name, db_user, db_password]):
        logger.warning("One or more PostgreSQL connection environment variables (DB_HOST, DB_NAME, DB_USER, DB_PASSWORD) are not set, and DATABASE_URL is also missing.")
        default_sqlite_path = "./default_bot_database_sqlalchemy_v2.db"
        logger.warning(f"Falling back to local SQLite database: {default_sqlite_path}")
        return f"sqlite:///{default_sqlite_path}"
        
    constructed_url = f"postgresql://{db_user}:{db_password}@{db_host}/{db_name}"
    _constructed_url_prefix_for_log = constructed_url.split("@")[0]
    logger.info(f"Constructed PostgreSQL URL from individual env vars: {_constructed_url_prefix_for_log}@...")
    return constructed_url

# --- SQLAlchemy Setup ---
# Use a consistent metadata object name, e.g., 'metadata_obj' as used in the manager
metadata_obj = MetaData()

# User Data Table - MODIFIED to match DBeaver screenshot (added is_admin and last_active_timestamp)
users_table = Table(
    "users", metadata_obj,
    Column("user_id", BigInteger, primary_key=True, autoincrement=False),
    Column("username", Text, nullable=True),
    Column("first_name", Text, nullable=True),
    Column("last_name", Text, nullable=True),
    Column("language_code", Text, nullable=True),
    Column("first_seen_timestamp", TIMESTAMP(timezone=True), server_default=func.now()),
    Column("last_active_timestamp", TIMESTAMP(timezone=True), nullable=True), # Added based on DBeaver screenshot
    Column("last_interaction_date", TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()),
    Column("is_admin", Boolean, default=False, nullable=False), # Added based on DBeaver screenshot
    Column("email", Text, nullable=True), # Added for registration
    Column("phone", Text, nullable=True), # Added for registration
    Column("grade", Text, nullable=True), # Added for registration
    Column("full_name", Text, nullable=True), # Added for registration
    Column("is_registered", Boolean, default=False, nullable=True) # Added for registration
)

# Quiz Session Data Table (as per user's original psycopg2 version)
quiz_sessions_table = Table(
    "quiz_sessions", metadata_obj,
    Column("quiz_session_id", Integer, primary_key=True, autoincrement=True), # SERIAL equivalent
    Column("user_id", BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
    Column("unit_id", Text, nullable=False),
    Column("start_timestamp", TIMESTAMP(timezone=True), server_default=func.now()),
    Column("end_timestamp", TIMESTAMP(timezone=True), nullable=True),
    Column("score", Integer, nullable=True),
    Column("total_questions_in_quiz", Integer, nullable=True),
    Column("status", Text, default="started")
)

# Question Interaction Data Table (as per user's original psycopg2 version)
question_interactions_table = Table(
    "question_interactions", metadata_obj,
    Column("interaction_id", Integer, primary_key=True, autoincrement=True), # SERIAL equivalent
    Column("quiz_session_id", Integer, ForeignKey("quiz_sessions.quiz_session_id", ondelete="CASCADE"), nullable=False),
    Column("question_id", Text, nullable=False),
    Column("user_id", BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
    Column("is_correct", Boolean, nullable=True),
    Column("answer_timestamp", TIMESTAMP(timezone=True), server_default=func.now()),
    Column("attempts_count", Integer, default=1)
)

# System Messages Table (Required for new admin tools, adapted from my SQLAlchemy version)
system_messages_table = Table(
    "system_messages", metadata_obj,
    Column("message_key", String(255), primary_key=True), # String with length for compatibility
    Column("message_text", Text, nullable=False),
    Column("last_modified", TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
)

# Define Indexes (SQLAlchemy way, adapted from user's psycopg2 version)
Index("idx_users_last_interaction", users_table.c.last_interaction_date.desc().nullslast())
Index("idx_users_username", users_table.c.username) # Example from user's file
Index("idx_quiz_sessions_user_id", quiz_sessions_table.c.user_id)
Index("idx_quiz_sessions_unit_id", quiz_sessions_table.c.unit_id)
Index("idx_quiz_sessions_start_timestamp", quiz_sessions_table.c.start_timestamp.desc().nullslast())
Index("idx_question_interactions_quiz_session_id", question_interactions_table.c.quiz_session_id)
Index("idx_question_interactions_question_id", question_interactions_table.c.question_id)
Index("idx_question_interactions_answer_timestamp", question_interactions_table.c.answer_timestamp.desc().nullslast())

# --- Core Functions (SQLAlchemy based) ---
def get_engine(db_url_override=None):
    """Creates an SQLAlchemy engine based on the provided or discovered URL."""
    db_url_to_use = db_url_override if db_url_override else get_database_url()
    
    try:
        engine = create_engine(db_url_to_use)
        with engine.connect() as connection:
            connection.execute(sql_text("SELECT 1")) 
        logger.info(f"SQLAlchemy engine created and connected successfully to: {engine.url.drivername}")
        return engine
    except Exception as e:
        # Mask password in log if present in URL
        safe_url = str(db_url_to_use)
        if "@" in safe_url and ":" in safe_url.split("@")[0]:
            parts = safe_url.split("://")
            if len(parts) > 1:
                auth_part = parts[1].split("@")[0]
                safe_url = safe_url.replace(auth_part, f"{auth_part.split(':')[0]}:********")

        logger.error(f"Error creating SQLAlchemy engine for URL \'{safe_url}\': {e}", exc_info=False) # Set exc_info=False to avoid full trace for connection errors if too verbose
        logger.debug(f"Full trace for engine creation error for URL \'{safe_url}\':", exc_info=True) # Provide full trace at DEBUG level
        return None

def create_tables(engine_to_use, drop_first=False):
    """Create tables in the database using SQLAlchemy. Optionally drop them first."""
    if not engine_to_use:
        logger.error("Database engine is not valid, cannot create tables.")
        return

    try:
        if drop_first:
            logger.warning("Attempting to drop existing tables before creation (SQLAlchemy metadata_obj.drop_all)...")
            metadata_obj.drop_all(engine_to_use)
            logger.info("Finished dropping tables.")

        logger.info("Creating tables if they do not exist (SQLAlchemy metadata_obj.create_all)...")
        metadata_obj.create_all(engine_to_use)
        logger.info("Tables (users, quiz_sessions, question_interactions, system_messages) checked/created successfully using SQLAlchemy.")
    except Exception as e:
        logger.error(f"SQLAlchemy error creating tables: {e}", exc_info=True)

# --- Main execution block for testing (similar to user's original) ---
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    db_url_for_test = get_database_url() # This will use env var or fallbacks
    _db_url_for_test_prefix = db_url_for_test.split("@")[0]
    logger.info(f"Attempting to set up database using SQLAlchemy with URL: {_db_url_for_test_prefix}@...")
    current_engine_for_test = get_engine(db_url_for_test)
    
    if current_engine_for_test is not None:
        logger.info(f"Successfully obtained engine for: {current_engine_for_test.url}")
        # IMPORTANT: For schema changes on an existing database,
        # running with drop_first=True ONCE might be needed to delete and recreate tables.
        # BE VERY CAREFUL: THIS WILL DELETE ALL EXISTING DATA IN THESE TABLES.
        # After the first successful run with drop_first=True, change it back to False.
        # Alternatively, use migration tools like Alembic for production databases.
        create_tables(current_engine_for_test, drop_first=False) # Set to True with caution for schema changes
        logger.info(f"Database setup process finished for {current_engine_for_test.url.database}.")
    else:
        _db_url_for_test_prefix_error = db_url_for_test.split("@")[0]
        logger.error(f"Error! Cannot create the database engine. Setup aborted for URL: {_db_url_for_test_prefix_error}@...")

logger.info("db_setup.py (SQLAlchemy version, adapted from user's structure) loaded.")

