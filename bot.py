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
    # Import handlers directly
    from handlers.common import start_handler # Handles /start command
    from handlers.quiz import quiz_conv_handler # Quiz conversation
    from handlers.info import info_conv_handler # Info conversation
    from handlers.stats import stats_conv_handler # Stats conversation
    # Import main_menu_callback separately if needed for explicit returns, but rely on sub-handler entry points first
    from handlers.common import main_menu_callback 

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
    # Optionally notify user
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
        # Ensure the directory exists for the persistence file
        persistence_dir = os.path.join(project_root, 'persistence')
        os.makedirs(persistence_dir, exist_ok=True)
        persistence_file = os.path.join(persistence_dir, 'bot_conversation_persistence.pkl')
        persistence = PicklePersistence(filepath=persistence_file)
        logger.info(f"PicklePersistence configured at {persistence_file}.")
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

    # --- Register Handlers --- 
    # Add the /start command handler
    application.add_handler(start_handler)

    # Add conversation handlers directly. Their entry points (e.g., CallbackQueryHandler pattern='^menu_quiz$')
    # will be triggered by the buttons sent by start_handler.
    application.add_handler(quiz_conv_handler)
    application.add_handler(info_conv_handler)
    application.add_handler(stats_conv_handler)

    # Add a handler for explicit 
