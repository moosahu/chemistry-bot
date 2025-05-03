import psycopg2
import os
from urllib.parse import urlparse

# Get database URL from environment variables
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise ValueError("No DATABASE_URL set for Connection")

# Parse the database URL
try:
    result = urlparse(DATABASE_URL)
    username = result.username
    password = result.password
    database = result.path[1:]
    hostname = result.hostname
    port = result.port
except Exception as e:
    raise ValueError(f"Error parsing DATABASE_URL: {e}")

def connect_db():
    """Connects to the PostgreSQL database."""
    try:
        # Ensure sslmode is set correctly without backslashes
        conn = psycopg2.connect(
            database=database,
            user=username,
            password=password,
            host=hostname,
            port=port,
            sslmode='require' # Correct syntax
        )
        return conn
    except psycopg2.Error as e:
        print(f"Error connecting to database: {e}")
        # Consider logging the error instead of just printing
        # Log the connection details being used (excluding password) for debugging
        print(f"Attempted connection with: user={username}, db={database}, host={hostname}, port={port}, sslmode=require")
        return None # Return None or raise an exception

def setup_database():
    """Sets up the database schema if it doesn't exist."""
    conn = connect_db()
    if conn is None:
        print("Failed to connect to database for setup.")
        return # Exit if connection failed

    try:
        with conn.cursor() as cur:
            # Create users table (if not exists) - Storing user info
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    first_name VARCHAR(255),
                    last_name VARCHAR(255),
                    username VARCHAR(255),
                    language_code VARCHAR(10),
                    registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_interaction_date TIMESTAMP
                );
            """)

            # Create quizzes table (if not exists) - Storing quiz metadata
            cur.execute("""
                CREATE TABLE IF NOT EXISTS quizzes (
                    quiz_id SERIAL PRIMARY KEY,
                    title VARCHAR(255) NOT NULL UNIQUE,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Create questions table (if not exists) - Storing quiz questions
            cur.execute("""
                CREATE TABLE IF NOT EXISTS questions (
                    question_id SERIAL PRIMARY KEY,
                    quiz_id INTEGER REFERENCES quizzes(quiz_id) ON DELETE CASCADE,
                    question_text TEXT NOT NULL,
                    image_url VARCHAR(512), -- Optional image URL for the question
                    correct_option INTEGER NOT NULL CHECK (correct_option >= 0 AND correct_option <= 3), -- Assuming 4 options (0-3)
                    explanation TEXT -- Optional explanation for the correct answer
                );
            """)
            # Add index for faster question retrieval by quiz_id
            cur.execute("CREATE INDEX IF NOT EXISTS idx_questions_quiz_id ON questions(quiz_id);")


            # Create options table (if not exists) - Storing answer options for questions
            cur.execute("""
                CREATE TABLE IF NOT EXISTS options (
                    option_id SERIAL PRIMARY KEY,
                    question_id INTEGER REFERENCES questions(question_id) ON DELETE CASCADE,
                    option_index INTEGER NOT NULL, -- 0, 1, 2, 3
                    option_text TEXT NOT NULL,
                    UNIQUE (question_id, option_index) -- Ensure option index is unique per question
                );
            """)
            # Add index for faster option retrieval by question_id
            cur.execute("CREATE INDEX IF NOT EXISTS idx_options_question_id ON options(question_id);")


            # Create user_quiz_attempts table (if not exists) - Tracking user attempts
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_quiz_attempts (
                    attempt_id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    quiz_id INTEGER REFERENCES quizzes(quiz_id) ON DELETE CASCADE,
                    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    end_time TIMESTAMP,
                    score INTEGER,
                    total_questions INTEGER,
                    completed BOOLEAN DEFAULT FALSE
                );
            """)
            # Add indexes for faster lookups
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_quiz_attempts_user_id ON user_quiz_attempts(user_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_quiz_attempts_quiz_id ON user_quiz_attempts(quiz_id);")


            # Create user_answers table (if not exists) - Storing specific answers for each attempt
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_answers (
                    answer_id SERIAL PRIMARY KEY,
                    attempt_id INTEGER REFERENCES user_quiz_attempts(attempt_id) ON DELETE CASCADE,
                    question_id INTEGER REFERENCES questions(question_id) ON DELETE SET NULL, -- Keep answer even if question deleted? Or CASCADE?
                    selected_option_index INTEGER, -- The index chosen by the user
                    is_correct BOOLEAN,
                    answer_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Add index for faster answer retrieval by attempt_id
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_answers_attempt_id ON user_answers(attempt_id);")

        conn.commit()
        print("Database setup/check completed successfully.")
    except psycopg2.Error as e:
        print(f"Error during database setup: {e}")
        if conn:
            conn.rollback() # Rollback changes on error
    finally:
        if conn:
            conn.close()

# Example usage (optional, for testing)
if __name__ == "__main__":
    print("Attempting to connect to database...")
    connection = connect_db()
    if connection:
        print("Connection successful!")
        connection.close()
        print("Connection closed.")
        print("\nRunning database setup...")
        setup_database()
    else:
        print("Connection failed.")

