# manager_definition.py (SQLAlchemy version, adapted for user's db_setup.py)
import logging
import json
import os
from datetime import datetime, timedelta # Added timedelta for get_active_users_count
from sqlalchemy import select, insert, update, delete, func, text as sql_text # Removed create_engine as it's in db_setup
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError

# Assuming db_setup.py is in a location accessible for import, e.g., same package
# The user's adapted db_setup.py is at /home/ubuntu/upload/db_setup.py
# For this to work, the bot's execution environment needs to handle this path, 
# or db_setup.py should be in the same directory as this manager or in PYTHONPATH.
# We will assume the import path will be resolved in the deployment environment.
# The key is that it now imports tables from the user's adapted db_setup.py schema.
from .db_setup import get_engine, metadata_obj, users_table, system_messages_table
# quiz_sessions_table and question_interactions_table are in user's db_setup but not directly used by these core admin tools.
# quiz_results_table (which was in my original manager) is NOT in user's db_setup.

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, database_url=None):
        """Initializes the DatabaseManager with an SQLAlchemy engine."""
        try:
            # get_engine is now imported from the user's adapted db_setup.py
            self.engine = get_engine(database_url) 
            if not self.engine:
                raise ConnectionError("Failed to get a valid database engine from db_setup.get_engine().")
            self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
            # Tables (users_table, system_messages_table) are imported from db_setup.py
            # Ensuring tables exist can be done here or in the main bot script using create_tables from db_setup.py
            # from .db_setup import create_tables
            # create_tables(self.engine) # Optional: call if manager should ensure table creation
            self._add_default_system_messages() # Add default messages if not present
            logger.info(f"DatabaseManager initialized successfully with engine: {self.engine.url.drivername}")
        except Exception as e:
            logger.error(f"Failed to initialize DatabaseManager: {e}", exc_info=True)
            self.engine = None
            self.SessionLocal = None

    def _execute_query(self, operation):
        """Helper to execute SQLAlchemy operations with session management."""
        if not self.SessionLocal:
            logger.error("SessionLocal is not initialized. Cannot execute query.")
            return None
        
        session = self.SessionLocal()
        try:
            result = operation(session)
            session.commit()
            return result
        except SQLAlchemyError as e:
            logger.error(f"SQLAlchemy database error: {e}", exc_info=True)
            session.rollback()
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred during query execution: {e}", exc_info=True)
            session.rollback()
            return None
        finally:
            session.close()

    def _add_default_system_messages(self):
        if not self.engine: 
            logger.warning("Cannot add default system messages: Database engine not initialized.")
            return

        default_messages = {
            'welcome_new_user': "مرحباً بك في بوت الكيمياء التحصيلي! أنا هنا لمساعدتك في الاستعداد لاختباراتك. يمكنك البدء باختبار تجريبي أو اختيار وحدة معينة.",
            'about_bot_message': "بوت الكيمياء التحصيلي هو مبادرة لمساعدة الطلاب على مراجعة مادة الكيمياء بطريقة تفاعلية. تم تطويره بواسطة فريق Manus.",
            'help_command_message': "يمكنك استخدام الأوامر التالية:\n/start - لبدء استخدام البوت أو العودة للقائمة الرئيسية.\n/quiz - لبدء اختبار جديد.\n/stats - لعرض إحصائياتك.\n/about - لمعرفة المزيد عن البوت."
        }
        for key, text_val in default_messages.items():
            if self.get_system_message(key) is None:
                self.update_system_message(key, text_val, is_initial_setup=True)
                logger.info(f"Added default system message for key: {key}")

    def get_system_message(self, message_key):
        if not self.engine: return None
        def operation(session):
            # system_messages_table is imported from user's adapted db_setup.py
            stmt = select(system_messages_table.c.message_text).where(system_messages_table.c.message_key == message_key)
            result = session.execute(stmt).scalar_one_or_none()
            return result
        return self._execute_query(operation)

    def update_system_message(self, message_key, new_text, is_initial_setup=False):
        if not self.engine: return None
        def operation(session):
            current_time = datetime.now()
            # Using system_messages_table from user's adapted db_setup.py
            if self.engine.url.drivername.startswith("postgres"):
                # PostgreSQL specific UPSERT for system_messages
                stmt = sql_text(f"""
                    INSERT INTO {system_messages_table.name} (message_key, message_text, last_modified)
                    VALUES (:key, :text, :now)
                    ON CONFLICT (message_key) DO UPDATE SET
                    message_text = EXCLUDED.message_text,
                    last_modified = :now;
                """)
                session.execute(stmt, {"key": message_key, "text": new_text, "now": current_time})
            else: # SQLite and other general cases for system_messages
                existing_stmt = select(system_messages_table).where(system_messages_table.c.message_key == message_key)
                existing = session.execute(existing_stmt).first()
                if existing:
                    update_stmt = update(system_messages_table).where(system_messages_table.c.message_key == message_key).values(
                        message_text=new_text,
                        last_modified=current_time
                    )
                    session.execute(update_stmt)
                else:
                    insert_stmt = insert(system_messages_table).values(
                        message_key=message_key,
                        message_text=new_text,
                        last_modified=current_time # server_default handles initial, explicit for update logic
                    )
                    session.execute(insert_stmt)
            logger.info(f"System message for key \'{message_key}\' updated/inserted.")
        return self._execute_query(operation)

    def get_all_editable_message_keys(self):
        return [
            {'key': 'welcome_new_user', 'description': 'رسالة الترحيب بالجدد'},
            {'key': 'help_command_message', 'description': 'رسالة المساعدة (/help)'}
        ]

    def get_all_active_user_ids(self):
        if not self.engine: return []
        def operation(session):
            # users_table is imported from user's adapted db_setup.py
            stmt = select(users_table.c.user_id)
            results = session.execute(stmt).fetchall()
            return [row[0] for row in results] if results else []
        return self._execute_query(operation) or [] 

    def is_user_admin(self, user_id):
        if not self.engine: return False
        # This function assumes 'is_admin' column exists in the 'users_table'.
        # The user's original users table schema in their db_setup.py did not explicitly have 'is_admin'.
        # If it's missing, this will fail. It needs to be added to users_table in db_setup.py.
        # For now, proceeding with assumption it might be added or this function might not be used by user's current bot for admin checks.
        # Let's add a check for the column's existence to be safer.
        if 'is_admin' not in users_table.c:
            logger.warning("Column 'is_admin' not found in users_table. Cannot check admin status.")
            return False # Default to not admin if column is missing
            
        def operation(session):
            stmt = select(users_table.c.is_admin).where(users_table.c.user_id == user_id)
            result = session.execute(stmt).scalar_one_or_none()
            return result is True 
        return self._execute_query(operation) or False

    # --- Methods from the original manager_definition.py that interact with users_table ---
    # These should work if users_table from user's db_setup.py has the required columns.

    def add_user_if_not_exists(self, user_id, username=None, first_name=None, last_name=None, language_code=None):
        # Modified to include language_code as in user's users_table schema
        if not self.engine: return None
        def operation(session):
            stmt_select = select(users_table).where(users_table.c.user_id == user_id)
            user = session.execute(stmt_select).first()
            if not user:
                insert_values = {
                    "user_id": user_id,
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                    "language_code": language_code,
                    # first_seen_timestamp and last_interaction_date have server_default
                }
                # Add is_admin if the column exists in the table definition from db_setup.py
                if 'is_admin' in users_table.c:
                    insert_values['is_admin'] = False # Default to not admin
                
                stmt_insert = insert(users_table).values(**insert_values)
                session.execute(stmt_insert)
                logger.info(f"User {user_id} added to the database.")
                return True 
            else:
                # Optionally update last_interaction_date here if user interacts
                # The users_table in user's db_setup has onupdate=func.now() for last_interaction_date
                # So, a separate update might not be needed if an interaction implies an update to the row.
                # For now, just log existence.
                logger.debug(f"User {user_id} already exists.")
                return False 
        return self._execute_query(operation)

    def get_total_users_count(self):
        if not self.engine: return 0
        def operation(session):
            stmt = select(func.count(users_table.c.user_id))
            count = session.execute(stmt).scalar_one()
            return count
        return self._execute_query(operation) or 0

    # --- The following methods depended on 'quiz_results_table' which is not in user's db_setup.py --- 
    # --- User's db_setup.py has 'quiz_sessions_table' and 'question_interactions_table'.            ---
    # --- These methods (get_active_users_count, record_quiz_result, get_user_stats, get_leaderboard) ---
    # --- would need to be rewritten to work with the user's specific quiz table structure.          ---
    # --- For now, they are commented out to prevent errors, as the core admin tools (message editing, broadcast) ---
    # --- primarily rely on users_table and system_messages_table.                                   ---

    # def get_active_users_count(self, days=30):
    #     if not self.engine: return 0
    #     def operation(session):
    #         time_threshold = datetime.now() - timedelta(days=days)
    #         # This should query based on users_table.c.last_interaction_date
    #         stmt = select(func.count(users_table.c.user_id)).where(users_table.c.last_interaction_date >= time_threshold)
    #         count = session.execute(stmt).scalar_one()
    #         return count
    #     return self._execute_query(operation) or 0

    # def record_quiz_result(self, user_id, quiz_type, score, total_questions, percentage, start_time, end_time, time_taken_seconds, answers_details_json):
    #     logger.warning("record_quiz_result is not compatible with current quiz table structure (quiz_sessions, question_interactions).")
    #     return None

    # def get_user_stats(self, user_id):
    #     logger.warning("get_user_stats is not compatible with current quiz table structure.")
    #     return []

    # def get_leaderboard(self, limit=10):
    #     logger.warning("get_leaderboard is not compatible with current quiz table structure.")
    #     return []

logger.info("SQLAlchemy DatabaseManager (manager_definition.py adapted for user's schema) loaded.")

# Example usage for direct testing (should be adapted if run)
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger.info("Running manager_definition.py (adapted) directly for testing...")

    # This test block needs the adapted db_setup.py to be in the python path
    # e.g., by setting PYTHONPATH=. if running from the directory containing 'database' and 'upload' folders
    # or by restructuring files into a proper package.
    try:
        from db_setup import create_tables # Assuming db_setup is in same dir for test
        test_db_url_env = os.environ.get("DATABASE_URL", "sqlite:///./test_dbs/test_manager_adapted.db")
        if "sqlite" in test_db_url_env and not os.path.exists("./test_dbs"):
            os.makedirs("./test_dbs")
        logger.info(f"Test DATABASE_URL set to: {test_db_url_env}")
        
        test_engine = get_engine(test_db_url_env)
        if test_engine:
            # create_tables from the adapted db_setup.py
            # Ensure the import path for create_tables is correct for this test context.
            # For this example, we assume db_setup.py is in the same directory for testing.
            # If it's in ../upload/db_setup.py, the import needs adjustment or PYTHONPATH.
            # For simplicity, this test might fail if paths are not set up for direct execution.
            # create_tables(test_engine, drop_first=True) 
            logger.info("Test tables would be created here if db_setup.create_tables is callable.")

            db_mngr = DatabaseManager(database_url=test_db_url_env)
            if db_mngr.engine:
                logger.info("DatabaseManager initialized for testing.")
                # Test methods that use users_table and system_messages_table
                # Ensure 'is_admin' column is added to users_table in db_setup.py for is_user_admin to work fully.
                # db_mngr.add_user_if_not_exists(12345, "testuser1", "Test", "UserOne", "en")
                # logger.info(f"Is 12345 admin? {db_mngr.is_user_admin(12345)}") 
                # logger.info(f"Welcome message: {db_mngr.get_system_message('welcome_new_user')}")
                logger.info("Basic testing stubs. Full test requires db_setup.py in path and 'is_admin' column.")
            else:
                logger.error("Failed to initialize DatabaseManager for testing.")
        else:
            logger.error("Failed to get test engine.")
            
    except ImportError as e:
        logger.error(f"ImportError during testing, ensure db_setup.py is accessible: {e}")
    except Exception as main_exc:
        logger.error(f"Error in manager_definition.py __main__ execution: {main_exc}", exc_info=True)

