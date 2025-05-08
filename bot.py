#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Main script for the Chemistry Quiz Telegram Bot (Modular Version - v11 with JobQueue enabled)."""

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
    from database.schema import setup_database_schema, apply_schema_updates
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
    from handlers.info import info_conv_handler
    from handlers.stats import stats_conv_handler
    # -----------------------------------------------------------

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

    # --- Database Setup ---
    logger.info("Setting up database schema...")
    try:
        if not setup_database_schema():
            logger.error("Database initial schema setup failed.")
        else:
            logger.info("Initial schema setup/check successful.")
            if not apply_schema_updates():
                logger.warning("Applying schema updates failed.")
            else:
                logger.info("Schema updates applied successfully.")
    except Exception as db_exc:
        logger.error(f"Error during database setup: {db_exc}")

    # --- Persistence ---
    try:
        persistence_dir = os.path.join(project_root, 'persistence')
        os.makedirs(persistence_dir, exist_ok=True)
        persistence_file = os.path.join(persistence_dir, 'bot_conversation_persistence.pkl')
        persistence = PicklePersistence(filepath=persistence_file)
        logger.info(f"PicklePersistence configured at {persistence_file}.")
    except Exception as pers_exc:
        logger.error(f"Error configuring persistence: {pers_exc}")
        persistence = None

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
        if job_queue: 
            app_builder = app_builder.job_queue(job_queue) 

        application = app_builder.build()
        logger.info("Telegram Application built.")

        if job_queue: 
            job_queue.set_application(application) 
            logger.info("JobQueue attached to the application.")
        else:
            logger.warning("JobQueue was not created or attached. Timed features will not work.")

    except Exception as app_exc:
        logger.critical(f"Error building Telegram Application: {app_exc}. Bot cannot start.")
        exit(1)

    # --- Register Handlers Directly ---
    # 1. Start command handler
    print("DEBUG: Adding start_handler...")
    application.add_handler(start_handler)
    print("DEBUG: start_handler added.")

    # 2. Quiz conversation handler (only if imported successfully)
    if quiz_conv_handler:
        print("DEBUG: Adding quiz_conv_handler...")
        application.add_handler(quiz_conv_handler)
        print("DEBUG: quiz_conv_handler added.")
    else:
        print("WARNING: quiz_conv_handler was not imported successfully or failed during import, skipping addition.")

    # --- MODIFIED: Uncommented info and stats handlers registration ---
    application.add_handler(info_conv_handler)
    logger.debug(f"[DEBUG] info_conv_handler added to application: {info_conv_handler}")

    application.add_handler(stats_conv_handler)
    logger.debug(f"[DEBUG] stats_conv_handler added to application: {stats_conv_handler}")
    # ---------------------------------------------------------------

    # --- ADDED GLOBAL HANDLER FOR MAIN MENU ---
    logger.info("Adding global main_menu_callback handler...")
    application.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    logger.info("Global main_menu_callback handler added.")
    # ------------------------------------------

    # 5. Error handler (add last)
    print("DEBUG: Adding error_handler...")
    application.add_error_handler(error_handler)
    print("DEBUG: error_handler added.")

    logger.info("Bot application configured with direct handlers. Starting polling...")
    application.run_polling()
    logger.info("Bot polling stopped.")


if __name__ == "__main__":
    main()

