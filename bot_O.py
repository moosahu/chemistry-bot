#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Main script for the Chemistry Quiz Telegram Bot (Modular Version - v17 - post_init DB_MANAGER).

Changes in this version:
- Introduced post_initialize_db_manager to set DB_MANAGER in bot_data after persistence loads.
- Removed direct DB_MANAGER initialization in main() to avoid being overwritten by persistence.
"""

import logging
import sys
import os
import traceback # Import traceback for detailed error logging

# --- Add project root to sys.path ---
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    PicklePersistence,
    CallbackContext,
    JobQueue
)
from telegram import Update

# --- Import Configuration and Core Components ---
quiz_conv_handler = None # Define as None initially
new_admin_tools_loaded = False # Initialize default, will be set by import block
admin_interface_v4_loaded = False # Initialize default

try:
    from config import (
        TELEGRAM_BOT_TOKEN, API_BASE_URL, DATABASE_URL, # Core config
        logger, # Logger instance
        MAIN_MENU, QUIZ_MENU, INFO_MENU, STATS_MENU, END # Conversation states
    )
    from database.db_setup import get_engine, create_tables # MODIFIED: create_connection to get_engine
    from handlers.common import start_handler, main_menu_callback

    try:
        from handlers.quiz import quiz_conv_handler
    except Exception as import_exc:
        if 'logger' in locals():
             logger.critical(f"CRITICAL: Failed to import quiz_conv_handler: {import_exc}", exc_info=True)
        quiz_conv_handler = None

    try:
        from handlers.info import info_conv_handler
        logger.info("Successfully imported info_conv_handler from handlers.info")
    except ImportError:
        logger.warning("Could not import info_conv_handler from handlers.info. Please ensure the file exists and is correct.")
        info_conv_handler = None
    from handlers.stats import stats_conv_handler

    # --- Import New Admin Tools (Edit Messages, Broadcast) ---
    try:
        from handlers.admin_new_tools import (
            start_command as admin_start_command, 
            about_command as admin_about_command,
            help_command as admin_help_command,
            admin_show_tools_menu_callback,
            admin_back_to_start_callback,
            admin_edit_specific_message_callback,
            admin_edit_other_messages_menu_callback,
            received_new_message_text,
            cancel_edit_command,
            admin_broadcast_start_callback,
            received_broadcast_text,
            admin_broadcast_confirm_callback,
            admin_broadcast_cancel_callback,
            cancel_broadcast_command,
            EDIT_MESSAGE_TEXT, 
            BROADCAST_MESSAGE_TEXT, 
            BROADCAST_CONFIRM 
        )
        # إضافة استيراد أدوات تصدير بيانات المستخدمين
        from handlers.admin_tools.admin_commands import export_users_command
        from database.manager_definition import DatabaseManager 
        logger.info("Successfully imported new admin tools (edit/broadcast) and DatabaseManager class.")
        new_admin_tools_loaded = True # Set flag based on successful import
    except ImportError as ie_new_admin:
        logger.warning(f"Could not import new admin tools (edit/broadcast) or DatabaseManager class: {ie_new_admin}. New admin functionalities will be unavailable.")
        new_admin_tools_loaded = False
    # --- End Import New Admin Tools ---

    # New Admin Interface (v4) Handlers
    try:
        from handlers.admin_interface import (
            stats_admin_panel_command_handler_v4,
            stats_menu_callback_handler_v4,
            stats_fetch_callback_handler_v4,
            STATS_PREFIX_MAIN_MENU as STATS_PREFIX_MAIN_MENU_V4,
            STATS_PREFIX_FETCH as STATS_PREFIX_FETCH_V4
        )
        logger.info("Successfully imported Admin Interface V4/V7/V8 handlers from handlers.admin_interface.")
        admin_interface_v4_loaded = True
    except ImportError as ie_v4:
        logger.warning(f"Could not import Admin Interface V4/V7/V8 handlers from handlers.admin_interface: {ie_v4}. The new admin dashboard will not be available.")
        admin_interface_v4_loaded = False

except ImportError as e:
    logging.basicConfig(level=logging.ERROR)
    logger = logging.getLogger(__name__)
    logger.critical(f"Failed to import core modules: {e}. Bot cannot start.")
    exit(1)
except Exception as e:
    logging.basicConfig(level=logging.ERROR)
    logger = logging.getLogger(__name__)
    logger.critical(f"An unexpected error occurred during imports: {e}. Bot cannot start.")
    exit(1)

async def post_initialize_db_manager(application: Application) -> None:
    """
    This function is called after the Application has been initialized,
    including loading data from persistence. It ensures DB_MANAGER is
    freshly initialized in application.bot_data.
    Uses global 'new_admin_tools_loaded', 'DatabaseManager', 'DATABASE_URL', 'logger'.
    """
    logger.info("=== [DB_MANAGER] Executing post_initialize_db_manager to set DB_MANAGER in bot_data... ===")
    
    # Check if DB_MANAGER already exists in bot_data
    existing_db_manager = application.bot_data.get("DB_MANAGER")
    if existing_db_manager:
        logger.info(f"[DB_MANAGER] Found existing DB_MANAGER in bot_data of type: {type(existing_db_manager)}")
        try:
            # Test if the existing DB_MANAGER is functional
            if hasattr(existing_db_manager, 'engine') and existing_db_manager.engine:
                logger.info("[DB_MANAGER] Existing DB_MANAGER has a valid engine. Testing connection...")
                try:
                    # Try a simple connection test
                    with existing_db_manager.engine.connect() as conn:
                        logger.info("[DB_MANAGER] Connection test successful. Keeping existing DB_MANAGER.")
                        return  # Keep the existing DB_MANAGER
                except Exception as conn_err:
                    logger.warning(f"[DB_MANAGER] Connection test failed: {conn_err}. Will re-initialize DB_MANAGER.")
            else:
                logger.warning("[DB_MANAGER] Existing DB_MANAGER has no valid engine. Will re-initialize.")
        except Exception as test_err:
            logger.warning(f"[DB_MANAGER] Error testing existing DB_MANAGER: {test_err}. Will re-initialize.")
    else:
        logger.info("[DB_MANAGER] No existing DB_MANAGER found in bot_data. Will initialize new instance.")
    
    current_db_manager_in_bot_data = None # Default to None
    
    # 'new_admin_tools_loaded' is the global flag set during the initial import phase.
    if new_admin_tools_loaded: 
        logger.info("[DB_MANAGER] Imports for new admin tools were successful. Attempting to init DB_MANAGER.")
        try:
            # Create a new instance of DatabaseManager
            # DatabaseManager class and DATABASE_URL should be in global scope from imports
            logger.info(f"[DB_MANAGER] Creating new DatabaseManager with DATABASE_URL: {DATABASE_URL[:10]}...")
            db_manager_instance = DatabaseManager(database_url=DATABASE_URL)
            instance_engine = getattr(db_manager_instance, 'engine', None)

            if db_manager_instance and instance_engine is not None:
                # Test the connection to ensure it's working
                try:
                    with instance_engine.connect() as conn:
                        logger.info("[DB_MANAGER] Connection test successful for new DB_MANAGER instance.")
                    current_db_manager_in_bot_data = db_manager_instance
                    logger.info(f"[DB_MANAGER] DatabaseManager initialized successfully. Type: {type(current_db_manager_in_bot_data)}")
                except Exception as conn_err:
                    logger.error(f"[DB_MANAGER] Connection test failed for new DB_MANAGER: {conn_err}")
                    current_db_manager_in_bot_data = None
            else:
                logger.error("[DB_MANAGER] Failed to create a valid DatabaseManager instance (or its engine is None). DB_MANAGER will be None in bot_data.")
        except Exception as e:
            logger.error(f"[DB_MANAGER] Exception during DatabaseManager instantiation: {e}", exc_info=True)
    else:
        logger.warning("[DB_MANAGER] Initial imports for new admin tools or DatabaseManager class failed. DB_MANAGER will not be initialized.")

    # Set the DB_MANAGER in bot_data
    application.bot_data["DB_MANAGER"] = current_db_manager_in_bot_data
    
    # Verify the DB_MANAGER was set correctly
    if application.bot_data.get("DB_MANAGER") is not None:
        logger.info(f"[DB_MANAGER] Successfully set DB_MANAGER in application.bot_data. Type: {type(application.bot_data.get('DB_MANAGER'))}")
    else:
        logger.critical("[DB_MANAGER] CRITICAL: Failed to set DB_MANAGER in application.bot_data. Registration and database features will not work!")

async def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            error_message = "حدث خطأ ما. يرجى المحاولة مرة أخرى لاحقاً."
            # Attempt to use Arabic processing if available
            # try:
            #     from handlers.admin_interface import process_arabic_text
            #     error_message = process_arabic_text(error_message)
            # except ImportError:
            #     pass # Use plain error message
            await context.bot.send_message(chat_id=update.effective_chat.id, text=error_message)
        except Exception as send_error:
            logger.error(f"Failed to send error message to user: {send_error}")

def main() -> None:
    """Start the bot."""
    # global new_admin_tools_loaded, admin_interface_v4_loaded # These are already global

    logger.info("Starting bot...")

    logger.info("Setting up database engine and tables using SQLAlchemy...")
    engine = None
    try:
        engine = get_engine()
        if engine:
            logger.info(f"SQLAlchemy engine created successfully for: {engine.url}")
            create_tables(engine, drop_first=False)
            logger.info("Database tables checked/created successfully via db_setup using SQLAlchemy.")
        else:
            logger.error("Failed to create SQLAlchemy engine. Bot may not function correctly with database features.")
    except Exception as db_exc:
        logger.error(f"Error during initial SQLAlchemy database setup (get_engine or create_tables): {db_exc}", exc_info=True)
    
    persistence = None
    try:
        persistence_dir = os.path.join(project_root, 'persistence')
        os.makedirs(persistence_dir, exist_ok=True)
        persistence_file = os.path.join(persistence_dir, 'bot_conversation_persistence.pkl')
        persistence = PicklePersistence(filepath=persistence_file)
        logger.info(f"PicklePersistence configured at {persistence_file}. All ConversationHandlers should be persistent=False.")
    except Exception as pers_exc:
        logger.error(f"Error configuring persistence: {pers_exc}. Proceeding without persistence.", exc_info=True)
        persistence = None

    job_queue = None
    try:
        job_queue = JobQueue()
        logger.info("JobQueue created.")
    except Exception as jq_exc:
        logger.error(f"Error creating JobQueue: {jq_exc}")
        job_queue = None 

    try:
        app_builder = Application.builder().token(TELEGRAM_BOT_TOKEN)
        if persistence:
            app_builder = app_builder.persistence(persistence)
            logger.info("Persistence object successfully attached to ApplicationBuilder.")
        else:
            logger.warning("Persistence object is None. Application will be built without persistence. Ensure all ConversationHandlers are persistent=False.")
            
        # Add the post_init hook HERE
        app_builder = app_builder.post_init(post_initialize_db_manager)
        logger.info("[DB_MANAGER] post_initialize_db_manager hook added to ApplicationBuilder.")

        if job_queue:
            app_builder = app_builder.job_queue(job_queue)

        application = app_builder.build()
        logger.info("Telegram Application built.")
        
        # The DB_MANAGER initialization block that was previously here has been removed.
        # It's now handled by post_initialize_db_manager after persistence loading.

        if job_queue:
            job_queue.set_application(application)
            logger.info("JobQueue attached to the application.")
        else:
            logger.warning("JobQueue was not created or attached. Timed features will not work.")

    except Exception as app_exc:
        logger.critical(f"Error building Telegram Application: {app_exc}. Bot cannot start.", exc_info=True)
        exit(1)

    # إضافة معالجات التسجيل أولاً قبل أي معالج آخر
    try:
        # استيراد معالجات التسجيل
        from registration import registration_conv_handler, edit_info_conv_handler
        
        # إضافة معالج التسجيل أولاً
        application.add_handler(registration_conv_handler)
        logger.info("Registration conversation handler added successfully.")
        
        # إضافة معالج تعديل المعلومات
        application.add_handler(edit_info_conv_handler)
        logger.info("Edit info conversation handler added successfully.")
    except ImportError as e:
        # محاولة استيراد من المسار الكامل
        try:
            from handlers.registration import registration_conv_handler, edit_info_conv_handler
            
            # إضافة معالج التسجيل أولاً
            application.add_handler(registration_conv_handler)
            logger.info("Registration conversation handler added successfully from handlers.registration.")
            
            # إضافة معالج تعديل المعلومات
            application.add_handler(edit_info_conv_handler)
            logger.info("Edit info conversation handler added successfully from handlers.registration.")
        except ImportError as e2:
            logger.error(f"Error importing registration handlers: {e2}. Registration features will not be available.")

    # إضافة باقي المعالجات بعد معالجات التسجيل
    if new_admin_tools_loaded:
        # تجنب إضافة معالج start لتجنب التعارض مع معالج التسجيل
        application.add_handler(CommandHandler("about", admin_about_command))
        application.add_handler(CommandHandler("help", admin_help_command))
        logger.info("New admin tools command handlers (about, help) added.")
    else:
        # لا نضيف معالج start هنا لأنه تمت إضافته بالفعل في معالج التسجيل
        logger.info("Common start_handler is already handled by registration_conv_handler.")

    if quiz_conv_handler:
        application.add_handler(quiz_conv_handler)
    else:
        logger.warning("quiz_conv_handler was not imported successfully or failed during import, skipping addition.")

    if info_conv_handler:
        application.add_handler(info_conv_handler)
        logger.debug(f"[DEBUG] info_conv_handler added to application: {info_conv_handler}")
    else:
        logger.warning("info_conv_handler was not imported or is None, skipping addition.")

    if stats_conv_handler:
        application.add_handler(stats_conv_handler)
        logger.debug(f"[DEBUG] stats_conv_handler added to application: {stats_conv_handler}")
    else:
        logger.warning("stats_conv_handler is None, skipping addition.")

    if admin_interface_v4_loaded:
        logger.info("Adding New Admin Statistics (V4/V7/V8) handlers (e.g., /adminstats_v4)...")
        application.add_handler(CommandHandler("adminstats_v4", stats_admin_panel_command_handler_v4))
        application.add_handler(CallbackQueryHandler(stats_menu_callback_handler_v4, pattern=f"^{STATS_PREFIX_MAIN_MENU_V4}"))
        application.add_handler(CallbackQueryHandler(stats_fetch_callback_handler_v4, pattern=f"^{STATS_PREFIX_FETCH_V4}"))
        logger.info("New Admin Statistics (V4/V7/V8) handlers added for /adminstats_v4.")
    else:
        logger.warning("New Admin Statistics (V4/V7/V8) handlers were not imported, skipping their addition.")

    # إضافة معالج الأخطاء
    application.add_error_handler(error_handler)
    logger.info("Error handler added.")

    # إضافة معالج الأوامر غير المعروفة
    application.add_handler(MessageHandler(filters.COMMAND, lambda u, c: safe_send_message(c.bot, u.effective_chat.id, "أمر غير معروف. استخدم /start للبدء.")))
    logger.info("Unknown command handler added.")

    # إضافة معالج الرسائل غير المعروفة
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: safe_send_message(c.bot, u.effective_chat.id, "رسالة غير معروفة. استخدم /start للبدء.")))
    logger.info("Unknown message handler added.")

    # بدء البوت
    logger.info("Starting polling...")
    application.run_polling()

async def safe_send_message(bot, chat_id, text, reply_markup=None, parse_mode=None):
    """إرسال رسالة بشكل آمن مع معالجة الأخطاء"""
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except Exception as e:
        logger.error(f"خطأ في إرسال الرسالة: {e}")
        try:
            # محاولة إرسال رسالة بدون تنسيق خاص
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup
            )
        except Exception as e2:
            logger.error(f"فشل محاولة إرسال الرسالة البديلة: {e2}")
            return None

if __name__ == "__main__":
    main()
