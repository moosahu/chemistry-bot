#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Main script for the Chemistry Quiz Telegram Bot (Modular Version - v14 with simplified PicklePersistence)."""

import logging
import sys
import os
import traceback # Import traceback for detailed error logging

# --- Add project root to sys.path ---
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# +++ REQUIRED: Import DB_MANAGER +++
from database.manager import DB_MANAGER
# +++++++++++++++++++++++++++++++++++

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
    # MODIFIED IMPORT FOR DB SETUP
    from database.db_setup import create_connection, create_tables # WAS: from database.schema import setup_database_schema, apply_schema_updates
    # Import handlers
    print("DEBUG: Importing handlers.common...")
    from handlers.common import start_handler, main_menu_callback # Keep main_menu_callback for fallbacks
    print("DEBUG: handlers.common imported.")

    # --- Wrap quiz handler import ---
    try:
        print("DEBUG: Attempting to import quiz_conv_handler...")
        from handlers.quiz import quiz_conv_handler
        print("DEBUG: Successfully imported quiz_conv_handler.")
    except Exception as import_exc:
        print(f"CRITICAL: Failed to import quiz_conv_handler: {import_exc}")
        # Log the full traceback for detailed debugging
        traceback_str = traceback.format_exc()
        print(f"CRITICAL: Traceback:\n{traceback_str}") 
        # Also log to the configured logger if available
        if 'logger' in locals():
             logger.critical(f"CRITICAL: Failed to import quiz_conv_handler: {import_exc}", exc_info=True)
        quiz_conv_handler = None # Keep as None

    # --- MODIFIED: Uncommented info and stats handlers imports ---
    # Attempt to import info_conv_handler, handle if not found
    try:
        from handlers.info import info_conv_handler
        logger.info("Successfully imported info_conv_handler from handlers.info")
    except ImportError:
        logger.warning("Could not import info_conv_handler from handlers.info. Please ensure the file exists and is correct.")
        info_conv_handler = None # Ensure it's None if import fails
        
    from handlers.stats import stats_conv_handler
    # -----------------------------------------------------------

    # +++ ADDED: Import for Admin Statistics Handlers +++
    from handlers.admin_interface import (
        stats_admin_panel_command_handler, 
        stats_menu_callback_handler, 
        stats_fetch_stats_callback_handler, 
        STATS_PREFIX_MAIN_MENU, 
        STATS_PREFIX_FETCH
    )
    # +++++++++++++++++++++++++++++++++++++++++++++++++++

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

# --- Error Handler ---
async def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="حدث خطأ ما. يرجى المحاولة مرة أخرى لاحقاً.")
        except Exception as send_error:
            logger.error(f"Failed to send error message to user: {send_error}")

# --- Main Function ---
def main() -> None:
    """Start the bot."""
    logger.info("Starting bot...")

    # --- Database Setup --- MODIFIED BLOCK
    logger.info("Setting up database connection and tables...")
    conn = None 
    try:
        conn = create_connection()
        if conn:
            logger.info("Database connected successfully.")
            create_tables(conn, drop_first=False) 
            logger.info("Database tables checked/created successfully.")
        else:
            logger.error("Failed to create database connection. Bot may not function correctly with database features.")
    except Exception as db_exc:
        logger.error(f"Error during database setup: {db_exc}", exc_info=True)
    finally:
        if conn:
            conn.close()
            logger.info("Database connection closed after setup.")
    # --- END OF MODIFIED DB SETUP BLOCK ---

    # --- Persistence (Simplified) ---
    persistence = None # Initialize to None
    try:
        persistence_dir = os.path.join(project_root, 'persistence')
        os.makedirs(persistence_dir, exist_ok=True)
        persistence_file = os.path.join(persistence_dir, 'bot_conversation_persistence.pkl')
        
        # *** MODIFICATION: Simplified PicklePersistence initialization ***
        # We are making all ConversationHandlers persistent=False, so the exact
        # configuration of PicklePersistence regarding store_bot_data is less critical.
        # The main goal is to have a valid persistence object if possible, or None if not.
        persistence = PicklePersistence(filepath=persistence_file)
        logger.info(f"PicklePersistence configured at {persistence_file}. All ConversationHandlers should be set to persistent=False.")

    except Exception as pers_exc:
        logger.error(f"Error configuring persistence: {pers_exc}. Proceeding without persistence.", exc_info=True)
        persistence = None # Ensure persistence is None if any error occurs

    # --- Job Queue Setup ---
    try:
        job_queue = JobQueue()
        logger.info("JobQueue created.")
    except Exception as jq_exc:
        logger.error(f"Error creating JobQueue: {jq_exc}")
        job_queue = None 

    # --- Application Setup ---
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

        # +++ REQUIRED: Add DB_MANAGER to bot_data +++
        application.bot_data["db_manager"] = DB_MANAGER
        logger.info(f"DB_MANAGER added to application.bot_data. ID of application.bot_data: {id(application.bot_data)}")
        logger.info(f"DB_MANAGER instance ID: {id(DB_MANAGER)}")
        # +++++++++++++++++++++++++++++++++++++++++++++

        if job_queue: 
            job_queue.set_application(application) 
            logger.info("JobQueue attached to the application.")
        else:
            logger.warning("JobQueue was not created or attached. Timed features will not work.")

    except Exception as app_exc:
        logger.critical(f"Error building Telegram Application: {app_exc}. Bot cannot start.", exc_info=True)
        exit(1)

    # --- Register Handlers Directly ---
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

