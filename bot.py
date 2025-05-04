#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Main script for the Chemistry Quiz Telegram Bot (Modular Version)."""

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
    filters, # Import filters (lowercase) instead of Filters
    PicklePersistence, # For storing conversation state across restarts
    CallbackContext # <-- Added missing import
)
from telegram import Update # <-- Added missing import for type hinting

# --- Import Configuration and Core Components --- 
try:
    from config import (
        TELEGRAM_BOT_TOKEN, API_BASE_URL, DATABASE_URL, # Core config
        logger, # Logger instance
        MAIN_MENU, QUIZ_MENU, SELECT_QUIZ_TYPE, SELECT_QUIZ_SCOPE, 
        ENTER_QUESTION_COUNT, TAKING_QUIZ, SHOWING_RESULTS, 
        INFO_MENU, STATS_MENU, SHOW_INFO_DETAIL, END # Conversation states
    )
    from database.schema import setup_database_schema, apply_schema_updates
    from handlers.common import start_handler, main_menu_handler, main_menu_callback
    from handlers.quiz import quiz_conv_handler
    from handlers.info import info_conv_handler
    from handlers.stats import stats_conv_handler

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
# Corrected: Defined as async def
async def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    # Optionally, notify the user or admin about the error
    # Example: 
    # if isinstance(update, Update) and update.effective_chat:
    #     try:
    #         await context.bot.send_message(chat_id=update.effective_chat.id, text="حدث خطأ ما. يرجى المحاولة مرة أخرى لاحقاً.")
    #     except Exception as send_error:
    #         logger.error(f"Failed to send error message to user: {send_error}")

# --- Main Function --- 
def main() -> None:
    """Start the bot."""
    logger.info("Starting bot...")

    # --- Database Setup --- 
    logger.info("Setting up database schema...")
    try:
        if not setup_database_schema():
            logger.error("Database initial schema setup failed. Check connection and schema script.")
        else:
            logger.info("Initial schema setup/check successful.")
            if not apply_schema_updates():
                logger.warning("Applying schema updates failed. Bot will continue, but some features might be affected.")
            else:
                logger.info("Schema updates applied successfully.")
    except Exception as db_exc:
        logger.error(f"Error during database setup: {db_exc}")

    # --- Persistence --- 
    try:
        persistence = PicklePersistence(filepath="bot_conversation_persistence.pkl")
        logger.info("PicklePersistence configured.")
    except Exception as pers_exc:
        logger.error(f"Error configuring persistence: {pers_exc}")
        persistence = None # Continue without persistence

    # --- Application Setup --- 
    try:
        application = (
            Application.builder()
            .token(TELEGRAM_BOT_TOKEN)
            .persistence(persistence)
            .build()
        )
        logger.info("Telegram Application built.")
    except Exception as app_exc:
        logger.critical(f"Error building Telegram Application: {app_exc}. Bot cannot start.")
        exit(1)

    # --- Main Conversation Handler --- 
    main_conv_handler = ConversationHandler(
        entry_points=[start_handler], # Start with /start
        states={
            MAIN_MENU: [
                quiz_conv_handler, 
                info_conv_handler,
                stats_conv_handler,
                main_menu_handler, 
                CallbackQueryHandler(main_menu_callback) 
            ],
        },
        fallbacks=[
            start_handler, 
        ],
        persistent=True,
        name="main_conversation" # Name for persistence
    )

    # --- Register Handlers --- 
    application.add_handler(main_conv_handler)
    
    # Add error handler
    application.add_error_handler(error_handler)

    # --- Start Bot --- 
    logger.info("Bot application configured. Starting polling...")
    application.run_polling()
    logger.info("Bot polling stopped.")


if __name__ == "__main__":
    main()

