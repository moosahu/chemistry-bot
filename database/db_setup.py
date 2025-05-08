# db_setup.py
import sqlite3
import os # Added for robust path handling

DB_NAME = "database/bot_stats.db" # <-- MODIFIED HERE

def create_connection():
    """Create a database connection to the SQLite database."""
    conn = None
    try:
        # Ensure the database directory exists
        db_dir = os.path.dirname(DB_NAME)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            print(f"Directory {db_dir} created.")
            
        conn = sqlite3.connect(DB_NAME)
        print(f"SQLite DB {DB_NAME} created/connected successfully.")
    except sqlite3.Error as e:
        print(f"SQLite error creating/connecting to {DB_NAME}: {e}")
    return conn

def create_tables(conn):
    """Create tables in the SQLite database."""
    if not conn:
        print("Database connection is not valid, cannot create tables.")
        return
        
    cursor = conn.cursor()
    try:
        # User Data Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_seen_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_active_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Quiz Session Data Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS quiz_sessions (
            quiz_session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            unit_id TEXT NOT NULL, -- Assuming unit_id can be text, e.g., 'Unit1', 'ChapterA'
            start_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            end_timestamp DATETIME,
            score INTEGER,
            total_questions_in_quiz INTEGER,
            status TEXT DEFAULT 'started', -- e.g., 'started', 'completed', 'abandoned'
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        );
        """)

        # Question Interaction Data Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS question_interactions (
            interaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_session_id INTEGER NOT NULL,
            question_id TEXT NOT NULL, -- Assuming question_id can be text or a unique string
            user_id INTEGER NOT NULL,
            is_correct BOOLEAN,
            answer_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            attempts_count INTEGER DEFAULT 1,
            FOREIGN KEY (quiz_session_id) REFERENCES quiz_sessions (quiz_session_id),
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        );
        """)

        # Create indexes for faster queries on frequently used columns
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_last_active ON users (last_active_timestamp);") # Added index
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_quiz_sessions_user_id ON quiz_sessions (user_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_quiz_sessions_unit_id ON quiz_sessions (unit_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_quiz_sessions_start_timestamp ON quiz_sessions (start_timestamp);") # Added index
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_question_interactions_quiz_session_id ON question_interactions (quiz_session_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_question_interactions_question_id ON question_interactions (question_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_question_interactions_answer_timestamp ON question_interactions (answer_timestamp);") # Added index

        conn.commit()
        print("Tables created successfully.")
    except sqlite3.Error as e:
        print(f"SQLite error creating tables: {e}")

if __name__ == '__main__':
    # This part is executed when the script is run directly (e.g., python database/db_setup.py from project root)
    print(f"Attempting to set up database at: {os.path.abspath(DB_NAME)}")
    conn = create_connection()
    if conn is not None:
        create_tables(conn)
        conn.close()
        print(f"Database setup process finished for {DB_NAME}.")
    else:
        print(f"Error! Cannot create the database connection for {DB_NAME}.")

# Next steps would involve modifying the bot's code (e.g., quiz_logic.py)
# to call functions that insert/update data into these tables.
# For example:
# def log_user_activity(user_id, username=None):
#     conn = create_connection()
#     cursor = conn.cursor()
#     cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
#     cursor.execute("UPDATE users SET last_active_timestamp = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
#     conn.commit()
#     conn.close()

