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
from .db_setup import get_engine, metadata_obj, users_table, system_messages_table, quiz_sessions_table

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
            # Tables (users_table, system_messages_table, quiz_sessions_table) are imported from db_setup.py
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
            stmt = select(system_messages_table.c.message_text).where(system_messages_table.c.message_key == message_key)
            result = session.execute(stmt).scalar_one_or_none()
            return result
        return self._execute_query(operation)

    def update_system_message(self, message_key, new_text, is_initial_setup=False):
        if not self.engine: return None
        def operation(session):
            current_time = datetime.now()
            if self.engine.url.drivername.startswith("postgres"):
                stmt = sql_text(f"""
                    INSERT INTO {system_messages_table.name} (message_key, message_text, last_modified)
                    VALUES (:key, :text, :now)
                    ON CONFLICT (message_key) DO UPDATE SET
                    message_text = EXCLUDED.message_text,
                    last_modified = :now;
                """)
                session.execute(stmt, {"key": message_key, "text": new_text, "now": current_time})
            else:
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
                        last_modified=current_time
                    )
                    session.execute(insert_stmt)
            logger.info(f"System message for key \'{message_key}\' updated/inserted.")
        return self._execute_query(operation)

    def get_all_editable_message_keys(self):
        return [
            {'key': 'welcome_new_user', 'description': 'رسالة الترحيب بالجدد'},
            {'key': 'help_command_message', 'description': 'رسالة المساعدة (/help)'}
        ]

    # Modified to get_all_user_ids_for_broadcast to align with manager.py and admin_new_tools.py usage
    def get_all_user_ids_for_broadcast(self):
        """Fetches all user IDs for broadcasting messages."""
        logger.info("[DB Broadcast] Fetching all user IDs for broadcast from manager_definition.py.")
        if not self.engine: 
            logger.warning("[DB Broadcast] Database engine not initialized. Cannot fetch user IDs.")
            return []
        def operation(session):
            stmt = select(users_table.c.user_id)
            results = session.execute(stmt).fetchall()
            user_ids = [row[0] for row in results] if results else []
            logger.info(f"[DB Broadcast] Found {len(user_ids)} user IDs for broadcast.")
            return user_ids
        return self._execute_query(operation) or [] 

    # Kept original get_all_active_user_ids for other potential uses, but broadcast uses the new one.
    def get_all_active_user_ids(self):
        if not self.engine: return []
        def operation(session):
            stmt = select(users_table.c.user_id) # This was the original logic, kept for now.
                                                # If it was meant to be truly 'active', it would need a time filter.
            results = session.execute(stmt).fetchall()
            return [row[0] for row in results] if results else []
        return self._execute_query(operation) or [] 

    def is_user_admin(self, user_id):
        if not self.engine: return False
        # logger.info(f"Available columns in users_table at runtime: {list(users_table.c.keys())}") # Redundant logging, can be removed
        if 'is_admin' not in users_table.c:
            logger.warning(f"Column 'is_admin' not found in users_table (columns: {list(users_table.c.keys())}). Cannot check admin status.")
            return False
            
        def operation(session):
            stmt = select(users_table.c.is_admin).where(users_table.c.user_id == user_id)
            result = session.execute(stmt).scalar_one_or_none()
            return result is True 
        return self._execute_query(operation) or False

    def add_user_if_not_exists(self, user_id, username=None, first_name=None, last_name=None, language_code=None):
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
                }
                # Ensure all columns defined in db_setup.users_table are handled or have defaults
                if 'first_seen_timestamp' in users_table.c:
                    insert_values['first_seen_timestamp'] = datetime.now()
                if 'last_active_timestamp' in users_table.c:
                    insert_values['last_active_timestamp'] = datetime.now()
                if 'last_interaction_date' in users_table.c:
                    insert_values['last_interaction_date'] = datetime.now()
                if 'is_admin' in users_table.c:
                    insert_values['is_admin'] = False
                
                stmt_insert = insert(users_table).values(**insert_values)
                session.execute(stmt_insert)
                logger.info(f"User {user_id} added to the database.")
                return True 
            else:
                # Optionally update last_active_timestamp or last_interaction_date here if user exists
                update_values = {'last_interaction_date': datetime.now()}
                if 'last_active_timestamp' in users_table.c:
                    update_values['last_active_timestamp'] = datetime.now()
                
                stmt_update = update(users_table).where(users_table.c.user_id == user_id).values(**update_values)
                session.execute(stmt_update)
                logger.debug(f"User {user_id} already exists. Updated interaction/activity timestamps.")
                return False 
        return self._execute_query(operation)

    def get_total_users_count(self):
        if not self.engine: return 0
        def operation(session):
            stmt = select(func.count(users_table.c.user_id))
            count = session.execute(stmt).scalar_one()
            return count
        return self._execute_query(operation) or 0

    def get_active_users_count(self, days=30):
        if not self.engine: return 0
        if 'last_active_timestamp' not in users_table.c:
            logger.warning("Column 'last_active_timestamp' not found in users_table. Cannot get active users count. Returning total users instead.")
            return self.get_total_users_count()
        def operation(session):
            time_threshold = datetime.now() - timedelta(days=days)
            stmt = select(func.count(users_table.c.user_id)).where(users_table.c.last_active_timestamp >= time_threshold)
            count = session.execute(stmt).scalar_one()
            return count
        return self._execute_query(operation) or 0

    def get_total_quizzes_count(self, days=30):
        """Counts total completed quizzes within a specified number of past days."""
        if not self.engine:
            logger.error("Database engine not initialized.")
            return 0
        if quiz_sessions_table is None or 'end_timestamp' not in quiz_sessions_table.c:
            logger.error("quiz_sessions_table or end_timestamp column not available.")
            return 0
        def operation(session):
            time_threshold = datetime.now() - timedelta(days=days)
            stmt = select(func.count(quiz_sessions_table.c.quiz_session_id)).where(
                quiz_sessions_table.c.end_timestamp.isnot(None),
                quiz_sessions_table.c.end_timestamp >= time_threshold
            )
            count = session.execute(stmt).scalar_one_or_none()
            return count if count is not None else 0
        result = self._execute_query(operation)
        return result if result is not None else 0

    def get_average_quizzes_per_active_user(self, days=30):
        """Calculates the average number of completed quizzes per active user within a specified period."""
        if not self.engine:
            logger.error("Database engine not initialized for get_average_quizzes_per_active_user.")
            return 0.0
        if 'last_active_timestamp' not in users_table.c or quiz_sessions_table is None or 'end_timestamp' not in quiz_sessions_table.c:
            logger.error("Required columns/tables not available for get_average_quizzes_per_active_user.")
            return 0.0

        def operation(session):
            time_threshold = datetime.now() - timedelta(days=days)

            active_users_sq = (
                select(users_table.c.user_id.label("user_id"))
                .where(users_table.c.last_active_timestamp >= time_threshold)
                .alias("active_users_sq")
            )
            
            total_active_users_stmt = select(func.count(active_users_sq.c.user_id))
            total_active_users = session.execute(total_active_users_stmt).scalar_one_or_none()

            if not total_active_users or total_active_users == 0:
                logger.info(f"No active users found in the last {days} days for average quiz calculation.")
                return 0.0

            completed_quizzes_sq = (
                select(
                    quiz_sessions_table.c.user_id,
                    func.count(quiz_sessions_table.c.quiz_session_id).label("num_completed_quizzes"),
                )
                .where(quiz_sessions_table.c.end_timestamp.isnot(None))
                .where(quiz_sessions_table.c.end_timestamp >= time_threshold) 
                .group_by(quiz_sessions_table.c.user_id)
                .alias("completed_quizzes_sq")
            )

            stmt = (
                select(
                    func.sum(func.coalesce(completed_quizzes_sq.c.num_completed_quizzes, 0)).label("total_completed_quizzes_by_active_users")
                )
                .select_from(active_users_sq) 
                .outerjoin( 
                    completed_quizzes_sq,
                    active_users_sq.c.user_id == completed_quizzes_sq.c.user_id,
                )
            )
            
            total_completed_quizzes_for_active_users = session.execute(stmt).scalar_one_or_none()

            if total_completed_quizzes_for_active_users is None:
                 total_completed_quizzes_for_active_users = 0

            average_quizzes = (
                float(total_completed_quizzes_for_active_users) / total_active_users
            )
            
            logger.info(f"Total active users (last {days} days): {total_active_users}")
            logger.info(f"Total completed quizzes by these active users (last {days} days): {total_completed_quizzes_for_active_users}")
            logger.info(f"Calculated average quizzes per active user (last {days} days): {average_quizzes:.2f}")
            return average_quizzes

        result = self._execute_query(operation)
        return result if result is not None else 0.0

logger.info("SQLAlchemy DatabaseManager (manager_definition.py adapted for user's schema) loaded.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger.info("Running manager_definition.py (adapted) directly for testing...")
    try:
        test_db_url_env = os.environ.get("DATABASE_URL", "sqlite:///./test_dbs/test_manager_adapted.db")
        if "sqlite" in test_db_url_env and not os.path.exists("./test_dbs"):
            os.makedirs("./test_dbs")
        logger.info(f"Test DATABASE_URL set to: {test_db_url_env}")
        
        test_engine = get_engine(test_db_url_env)
        if test_engine:
            logger.info("Test tables would be created here if db_setup.create_tables is callable.")
            db_mngr = DatabaseManager(database_url=test_db_url_env)
            if db_mngr.engine:
                logger.info("DatabaseManager initialized for testing.")
                # Example: Add a few users for testing broadcast list
                # db_mngr.add_user_if_not_exists(111, "user111")
                # db_mngr.add_user_if_not_exists(222, "user222")
                # broadcast_ids = db_mngr.get_all_user_ids_for_broadcast()
                # logger.info(f"Test: User IDs for broadcast: {broadcast_ids}")
                logger.info("Basic testing stubs. Full test requires db_setup.py in path and data.")
            else:
                logger.error("Failed to initialize DatabaseManager for testing.")
        else:
            logger.error("Failed to get test engine.")
            
    except ImportError as e:
        logger.error(f"ImportError during testing, ensure db_setup.py is accessible: {e}")
    except Exception as main_exc:
        logger.error(f"Error in manager_definition.py __main__ execution: {main_exc}", exc_info=True)

