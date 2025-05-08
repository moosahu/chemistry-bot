# db_setup.py
import psycopg2
import os

# PostgreSQL connection parameters (get from environment variables or config file in production)
DB_HOST = os.environ.get("DB_HOST", "dpg-d09mk5p5pdvs73dv4qeg-a.oregon-postgres.render.com")
DB_NAME = os.environ.get("DB_NAME", "chemistry_db")
DB_USER = os.environ.get("DB_USER", "chemistry_db_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "2ewIvDpOHiKe8pFVVz15pba6FVDTKaB1")

def get_db_connection_string():
    return f"dbname=\'{DB_NAME}\' user=\'{DB_USER}\' host=\'{DB_HOST}\' password=\'{DB_PASSWORD}\'"

def create_connection():
    """Create a database connection to the PostgreSQL database."""
    conn = None
    try:
        conn = psycopg2.connect(get_db_connection_string())
        print(f"PostgreSQL DB {DB_NAME} connected successfully.")
    except psycopg2.Error as e:
        print(f"PostgreSQL error connecting to {DB_NAME}: {e}")
    return conn

def drop_existing_tables(cursor):
    """Drops existing tables to avoid conflicts. Use with caution."""
    tables_to_drop = ["question_interactions", "quiz_sessions", "users"]
    for table in tables_to_drop:
        try:
            cursor.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
            print(f"Table {table} dropped successfully (if it existed).")
        except psycopg2.Error as e:
            print(f"Error dropping table {table}: {e}")

def create_tables(conn, drop_first=False):
    """Create tables in the PostgreSQL database. Optionally drop them first."""
    if not conn:
        print("Database connection is not valid, cannot create tables.")
        return

    cursor = conn.cursor()
    try:
        if drop_first:
            print("Attempting to drop existing tables before creation...")
            drop_existing_tables(cursor)
            conn.commit() # Commit the drop operations
            print("Finished attempting to drop tables.")

        # User Data Table - MODIFIED TO INCLUDE first_name, last_name, language_code, and last_interaction_date
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            language_code TEXT,
            first_seen_timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            last_interaction_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP -- Changed from last_active_timestamp and ensured it's present
        );
        """)

        # Quiz Session Data Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS quiz_sessions (
            quiz_session_id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            unit_id TEXT NOT NULL,
            start_timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            end_timestamp TIMESTAMP WITH TIME ZONE,
            score INTEGER,
            total_questions_in_quiz INTEGER,
            status TEXT DEFAULT 'started', -- e.g., 'started', 'completed', 'abandoned'
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
        );
        """)

        # Question Interaction Data Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS question_interactions (
            interaction_id SERIAL PRIMARY KEY,
            quiz_session_id INTEGER NOT NULL,
            question_id TEXT NOT NULL,
            user_id BIGINT NOT NULL,
            is_correct BOOLEAN,
            answer_timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            attempts_count INTEGER DEFAULT 1,
            FOREIGN KEY (quiz_session_id) REFERENCES quiz_sessions (quiz_session_id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
        );
        """)

        # Create indexes for faster queries on frequently used columns
        # Changed from idx_users_last_active
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_last_interaction ON users (last_interaction_date DESC NULLS LAST);")
        # Add indexes for new columns if they will be frequently queried/filtered on
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users (username);") # Example for username

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_quiz_sessions_user_id ON quiz_sessions (user_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_quiz_sessions_unit_id ON quiz_sessions (unit_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_quiz_sessions_start_timestamp ON quiz_sessions (start_timestamp DESC NULLS LAST);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_question_interactions_quiz_session_id ON question_interactions (quiz_session_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_question_interactions_question_id ON question_interactions (question_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_question_interactions_answer_timestamp ON question_interactions (answer_timestamp DESC NULLS LAST);")

        conn.commit()
        print("Tables checked/created successfully in PostgreSQL.")
    except psycopg2.Error as e:
        print(f"PostgreSQL error creating tables: {e}")
        if conn:
            conn.rollback() # Rollback changes if an error occurs
    finally:
        if cursor:
            cursor.close()

if __name__ == '__main__':
    print(f"Attempting to set up PostgreSQL database '{DB_NAME}' on host '{DB_HOST}'")
    conn = create_connection()
    if conn is not None:
        # IMPORTANT: For the schema change to take effect on an existing database,
        # you MUST run this with drop_first=True ONCE to delete and recreate tables.
        # BE VERY CAREFUL: THIS WILL DELETE ALL EXISTING DATA IN THESE TABLES.
        # After the first successful run with drop_first=True, change it back to False.
        # Alternatively, manually apply ALTER TABLE commands to your production DB if you cannot lose data.
        create_tables(conn, drop_first=True) # Set to True for the first run to apply schema changes
        conn.close()
        print(f"Database setup process finished for {DB_NAME}.")
    else:
        print(f"Error! Cannot create the database connection for {DB_NAME}.")

