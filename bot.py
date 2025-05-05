#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Main script for the Chemistry Quiz Telegram Bot (Modular Version - v6 with explicit patterns in Main ConversationHandler)."""

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
    CallbackContext
)
from telegram import Update

# --- Import Configuration and Core Components --- 
try:
    from config import (
        TELEGRAM_BOT_TOKEN, API_BASE_URL, DATABASE_URL, # Core config
        logger, # Logger instance
        MAIN_MENU, QUIZ_MENU, INFO_MENU, STATS_MENU, END # Conversation states
        # Ensure all states used in sub-handlers are imported if needed here, though primarily needed within sub-handlers
    )
    from database.schema import setup_database_schema, apply_schema_updates
    # Import handlers
    from handlers.common import start_handler, main_menu_callback # Handles /start and main menu button logic
    from handlers.quiz import quiz_conv_handler # Quiz sub-conversation
    from handlers.info import info_conv_handler # Info sub-conversation
    from handlers.stats import stats_conv_handler # Stats sub-conversation

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

    # --- Main Conversation Handler --- 
    # This handler manages the top-level flow: starting, showing the main menu,
    # and delegating to sub-conversations (quiz, info, stats).
    main_conv_handler = ConversationHandler(
        entry_points=[start_handler], # Start with /start
        states={
            MAIN_MENU: [
                # Use explicit patterns for each main menu button
                CallbackQueryHandler(main_menu_callback, pattern="^menu_quiz$"),
                CallbackQueryHandler(main_menu_callback, pattern="^menu_info$"),
                CallbackQueryHandler(main_menu_callback, pattern="^menu_stats$"),
                # Handle explicit return to main menu via button with 'main_menu' data
                CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")
            ],
            # Map the states returned by main_menu_callback to the sub-handlers
            QUIZ_MENU: [quiz_conv_handler],
            INFO_MENU: [info_conv_handler],
            STATS_MENU: [stats_conv_handler],
            # Add other top-level states if needed (e.g., ADMIN_MENU)
        },
        fallbacks=[
            # Fallback to /start if something goes wrong or user sends /start again
            start_handler,
        ],
        persistent=True,
        name="main_conversation", # Name for persistence
        map_to_parent={
            MAIN_MENU: MAIN_MENU, # If a sub-handler returns MAIN_MENU, go back to the main menu state here
            END: END # Allow sub-handlers to end the entire conversation
        }
    )

    # --- Register Handlers --- 
    application.add_handler(main_conv_handler)
    application.add_error_handler(error_handler)

    # --- Start Bot --- 
    logger.info("Bot application configured. Starting polling...")
    application.run_polling()
    logger.info("Bot polling stopped.")


if __name__ == "__main__":
    main()

