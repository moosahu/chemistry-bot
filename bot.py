#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Main script for the Chemistry Quiz Telegram Bot (Modular Version - v11 with JobQueue enabled)."""

import logging
import sys
import os

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
try:
    from config import (
        TELEGRAM_BOT_TOKEN, API_BASE_URL, DATABASE_URL, # Core config
        logger, # Logger instance
        MAIN_MENU, QUIZ_MENU, INFO_MENU, STATS_MENU, END # Conversation states
    )
    from database.schema import setup_database_schema, apply_schema_updates
    # Import handlers
    from handlers.common import start_handler, main_menu_callback # Keep main_menu_callback for fallbacks
    # from handlers.quiz import quiz_conv_handler
    # from handlers.info import info_conv_handler
    # from handlers.stats import stats_conv_handler

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
        job_queue = None # Continue without JobQueue if creation fails

    # --- Application Setup --- 
    try:
        app_builder = Application.builder().token(TELEGRAM_BOT_TOKEN)
        if persistence:
            app_builder = app_builder.persistence(persistence)
        if job_queue: # <-- Check if job_queue was created successfully
            app_builder = app_builder.job_queue(job_queue) # <-- Pass JobQueue to builder
        
        application = app_builder.build()
        logger.info("Telegram Application built.")
        
        # --- Attach JobQueue to Application --- 
        if job_queue: # <-- Check again before setting application
            job_queue.set_application(application) # <-- Link JobQueue to the application
            logger.info("JobQueue attached to the application.")
        else:
            logger.warning("JobQueue was not created or attached. Timed features will not work.")
            
    except Exception as app_exc:
        logger.critical(f"Error building Telegram Application: {app_exc}. Bot cannot start.")
        exit(1)

    # --- Register Handlers Directly --- 
    # 1. Start command handler
        application.add_handler(start_handler)
    # logger.debug("[DEBUG] start_handler added to application.")

    # 2. Quiz conversation handler
    # application.add_handler(quiz_conv_handler)
    # logger.debug(f"[DEBUG] quiz_conv_handler added to application: {quiz_conv_handler}")

    # 3. Info conversation handler
    # application.add_handler(info_conv_handler)
    # logger.debug(f"[DEBUG] info_conv_handler added to application: {info_conv_handler}")

    # 4. Stats conversation handler
    # application.add_handler(stats_conv_handler)
    # logger.debug(f"[DEBUG] stats_conv_handler added to application: {stats_conv_handler}")

    # 5. Error handler (add last)
    application.add_error_handler(error_handler)
    logger.debug("[DEBUG] error_handler added to application.")

    # --- Start Bot --- 
    logger.info("Bot application configured with direct handlers. Starting polling...")
    application.run_polling()
    logger.info("Bot polling stopped.")


if __name__ == "__main__":
    main()

