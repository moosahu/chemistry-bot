#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Main script for the Chemistry Quiz Telegram Bot (Modular Version - v15 - db_manager independent)."""

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
    JobQueue # <-- Import JobQueue
)
from telegram import Update

# --- Import Configuration and Core Components ---
quiz_conv_handler = None # Define as None initially
try:
    from config import (
        TELEGRAM_BOT_TOKEN, API_BASE_URL, DATABASE_URL, # Core config
        logger, # Logger instance
        MAIN_MENU, QUIZ_MENU, INFO_MENU, STATS_MENU, END # Conversation states
    )
    from database.db_setup import create_connection, create_tables
    print("DEBUG: Importing handlers.common...")
    from handlers.common import start_handler, main_menu_callback
    print("DEBUG: handlers.common imported.")

    try:
        print("DEBUG: Attempting to import quiz_conv_handler...")
        from handlers.quiz import quiz_conv_handler
        print("DEBUG: Successfully imported quiz_conv_handler.")
    except Exception as import_exc:
        print(f"CRITICAL: Failed to import quiz_conv_handler: {import_exc}")
        traceback_str = traceback.format_exc()
        print(f"CRITICAL: Traceback:\n{traceback_str}")
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

    from handlers.admin_interface import (
        stats_admin_panel_command_handler, 
        stats_menu_callback_handler, 
        stats_fetch_stats_callback_handler, 
        STATS_PREFIX_MAIN_MENU, 
        STATS_PREFIX_FETCH
    )

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

async def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="حدث خطأ ما. يرجى المحاولة مرة أخرى لاحقاً.")
        except Exception as send_error:
            logger.error(f"Failed to send error message to user: {send_error}")

def main() -> None:
    """Start the bot."""
    logger.info("Starting bot...")

    logger.info("Setting up database connection and tables...")
    conn_check = None
    try:
        # This block is for initial table creation using db_setup.
        # DB_MANAGER (imported from database.manager) is assumed to manage its own connections for operations.
        conn_check = create_connection() # from database.db_setup
        if conn_check:
            logger.info("Database connection for setup check successful.")
            create_tables(conn_check, drop_first=False) # from database.db_setup
            logger.info("Database tables checked/created successfully via db_setup.")
        else:
            logger.error("Failed to create database connection for setup. Bot may not function correctly with database features.")
    except Exception as db_exc:
        logger.error(f"Error during initial database table setup: {db_exc}", exc_info=True)
    finally:
        if conn_check:
            conn_check.close()
            logger.info("Database connection for setup check closed.")
    
    logger.info("DB_MANAGER is expected to be initialized and ready from its module (database.manager). Explicit initialization if needed should be handled there.")

    persistence = None
    try:
        persistence_dir = os.path.join(project_root, 'persistence')
        os.makedirs(persistence_dir, exist_ok=True)
        persistence_file = os.path.join(persistence_dir, 'bot_conversation_persistence.pkl')
        persistence = PicklePersistence(filepath=persistence_file)
        logger.info(f"PicklePersistence configured at {persistence_file}. All ConversationHandlers should be set to persistent=False.")
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
            
        if job_queue:
            app_builder = app_builder.job_queue(job_queue)

        application = app_builder.build()
        logger.info("Telegram Application built.")

        # --- DB_MANAGER is NO LONGER added to application.bot_data ---
        # Handlers will import and use DB_MANAGER directly from database.manager
        logger.info("DB_MANAGER will be imported and used directly by handlers, not stored in bot_data.")
        # ---

        if job_queue:
            job_queue.set_application(application)
            logger.info("JobQueue attached to the application.")
        else:
            logger.warning("JobQueue was not created or attached. Timed features will not work.")

    except Exception as app_exc:
        logger.critical(f"Error building Telegram Application: {app_exc}. Bot cannot start.", exc_info=True)
        exit(1)

    print("DEBUG: Adding start_handler...")
    application.add_handler(start_handler)
    print("DEBUG: start_handler added.")

    if quiz_conv_handler:
        print("DEBUG: Adding quiz_conv_handler...")
        application.add_handler(quiz_conv_handler)
        print("DEBUG: quiz_conv_handler added.")
    else:
        print("WARNING: quiz_conv_handler was not imported successfully or failed during import, skipping addition.")

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

    logger.info("Adding Admin Statistics handlers...")
    application.add_handler(CommandHandler("adminstats", stats_admin_panel_command_handler))
    application.add_handler(CallbackQueryHandler(stats_menu_callback_handler, pattern=f"^{STATS_PREFIX_MAIN_MENU}"))
    application.add_handler(CallbackQueryHandler(stats_fetch_stats_callback_handler, pattern=f"^{STATS_PREFIX_FETCH}"))
    logger.info("Admin Statistics handlers added.")

    logger.info("Adding global main_menu_callback handler...")
    application.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^(main_menu|about_bot)$"))
    logger.info("Global main_menu_callback handler added.")

    print("DEBUG: Adding error_handler...")
    application.add_error_handler(error_handler)
    print("DEBUG: error_handler added.")

    logger.info("Bot application configured with direct handlers. Starting polling...")
    application.run_polling()
    logger.info("Bot polling stopped.")

if __name__ == "__main__":
    main()

