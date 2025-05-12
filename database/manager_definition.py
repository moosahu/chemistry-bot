# manager_v17_admin_tools.py
# Assuming DatabaseManager class and DB_MANAGER instance exist as in previous versions.

import sqlite3
import logging
import json
from datetime import datetime, timedelta

# Configure logging (as in previous manager versions)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class DatabaseManager:
    def __init__(self, db_path='user_data/bot_database.db'):
        self.db_path = db_path
        self._create_tables_if_not_exists()
        self._create_system_messages_table_if_not_exists() # New table
        self._add_default_system_messages() # Add default messages if not present

    def _execute_query(self, query, params=(), commit=False, fetchone=False, fetchall=False):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                if commit:
                    conn.commit()
                if fetchone:
                    return cursor.fetchone()
                if fetchall:
                    return cursor.fetchall()
                return cursor.lastrowid # For INSERT, UPDATE, DELETE if needed
        except sqlite3.Error as e:
            logging.error(f"Database error: {e} for query: {query} with params: {params}")
            return None

    def _create_tables_if_not_exists(self):
        # Assuming existing tables like users, quiz_results, etc.
        # For brevity, not re-listing all previous table creations here.
        # Example from previous versions:
        self._execute_query("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            is_admin BOOLEAN DEFAULT FALSE,
            registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_interaction_date TIMESTAMP
        )
        """, commit=True)
        self._execute_query("""
        CREATE TABLE IF NOT EXISTS quiz_results (
            result_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            quiz_type TEXT, -- e.g., 'general', 'custom_topic', 'unit_X'
            score INTEGER,
            total_questions INTEGER,
            percentage REAL,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            time_taken_seconds INTEGER,
            answers_details TEXT, -- JSON string of detailed answers
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
        """, commit=True)
        # ... other tables ...
        logging.info("Core database tables checked/created.")

    def _create_system_messages_table_if_not_exists(self):
        query = """
        CREATE TABLE IF NOT EXISTS system_messages (
            message_key TEXT PRIMARY KEY,
            message_text TEXT NOT NULL,
            last_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
        self._execute_query(query, commit=True)
        logging.info("System messages table checked/created.")

    def _add_default_system_messages(self):
        default_messages = {
            'welcome_new_user': "مرحباً بك في بوت الكيمياء التحصيلي! أنا هنا لمساعدتك في الاستعداد لاختباراتك. يمكنك البدء باختبار تجريبي أو اختيار وحدة معينة.",
            'about_bot_message': "بوت الكيمياء التحصيلي هو مبادرة لمساعدة الطلاب على مراجعة مادة الكيمياء بطريقة تفاعلية. تم تطويره بواسطة فريق Manus.",
            'help_command_message': "يمكنك استخدام الأوامر التالية:\n/start - لبدء استخدام البوت أو العودة للقائمة الرئيسية.\n/quiz - لبدء اختبار جديد.\n/stats - لعرض إحصائياتك.\n/about - لمعرفة المزيد عن البوت."
        }
        for key, text in default_messages.items():
            # Check if message already exists
            if not self.get_system_message(key):
                self.update_system_message(key, text, is_initial_setup=True)
                logging.info(f"Added default system message for key: {key}")

    def get_system_message(self, message_key):
        query = "SELECT message_text FROM system_messages WHERE message_key = ?"
        result = self._execute_query(query, (message_key,), fetchone=True)
        return result[0] if result else None

    def update_system_message(self, message_key, new_text, is_initial_setup=False):
        # For initial setup, we don't update last_modified to current time if it's just an insert
        # For actual updates by admin, last_modified should be updated.
        if is_initial_setup:
            query_insert = "INSERT OR IGNORE INTO system_messages (message_key, message_text) VALUES (?, ?)"
            self._execute_query(query_insert, (message_key, new_text), commit=True)
        else:
            query_update = """
            INSERT INTO system_messages (message_key, message_text, last_modified)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(message_key) DO UPDATE SET
            message_text = excluded.message_text,
            last_modified = CURRENT_TIMESTAMP;
            """
            self._execute_query(query_update, (message_key, new_text), commit=True)
        logging.info(f"System message for key '{message_key}' updated.")

    def get_all_editable_message_keys(self):
        # This could return a predefined list or query the DB for all keys
        # For now, let's return a predefined list as per the plan
        return [
            {'key': 'welcome_new_user', 'description': 'رسالة الترحيب بالجدد'},
            {'key': 'help_command_message', 'description': 'رسالة المساعدة (/help)'}
            # 'about_bot_message' will be handled by a direct button
        ]

    def get_all_active_user_ids(self):
        # For now, returns all user_ids. Can be refined later for 'active' users.
        query = "SELECT user_id FROM users"
        results = self._execute_query(query, fetchall=True)
        return [row[0] for row in results] if results else []

    def is_user_admin(self, user_id):
        query = "SELECT is_admin FROM users WHERE user_id = ?"
        result = self._execute_query(query, (user_id,), fetchone=True)
        return result[0] == 1 if result else False

    # ... (other existing methods from manager_v16_final_fix_clean.py would be here) ...
    # For example: add_user_if_not_exists, get_total_users_count, get_active_users_count, etc.
    # Make sure to integrate these new methods with the existing class structure.

# Instantiate the manager (as it would be in the main bot file)
# DB_MANAGER = DatabaseManager()

# Example usage (for testing purposes, normally not in this file):
# if __name__ == '__main__':
#     DB_MANAGER = DatabaseManager(db_path='test_bot_database.db') # Use a test DB
#     DB_MANAGER._execute_query("DELETE FROM system_messages") # Clear for testing
#     DB_MANAGER._add_default_system_messages()

#     print("Initial messages:")
#     print(f"Welcome: {DB_MANAGER.get_system_message('welcome_new_user')}")
#     print(f"About: {DB_MANAGER.get_system_message('about_bot_message')}")
#     print(f"Help: {DB_MANAGER.get_system_message('help_command_message')}")

#     DB_MANAGER.update_system_message('about_bot_message', 'تم تحديث رسالة حول البوت بواسطة الأدمن.')
#     print(f"Updated About: {DB_MANAGER.get_system_message('about_bot_message')}")

#     print("Editable keys:", DB_MANAGER.get_all_editable_message_keys())
#     print("All user IDs:", DB_MANAGER.get_all_active_user_ids()) # Assuming some users exist

logging.info("manager_v17_admin_tools.py loaded with admin tool functionalities.")


