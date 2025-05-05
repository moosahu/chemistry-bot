#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Main script for the Chemistry Quiz Telegram Bot (Modular Version - v7 with added debugging)."""

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
    MessageHandler, # Import MessageHandler
    filters, # Import filters (lowercase)
    PicklePersistence,
    CallbackContext
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
    from handlers.common import start_handler, main_menu_callback
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
async def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="حدث خطأ ما. يرجى المحاولة مرة أخرى لاحقاً.")
        except Exception as send_error:
            logger.error(f"Failed to send error message to user: {send_error}")

# --- Debug Handler for MAIN_MENU state --- 
async def debug_main_menu_message(update: Update, context: CallbackContext) -> int:
    """Logs any text message received while in the MAIN_MENU state."""
    if update.message:
        logger.debug(f"[DEBUG] Received text message in MAIN_MENU state: 	'{update.message.text}	'")
        # Optionally reply to user to indicate state
        # await update.message.reply_text("Debug: In MAIN_MENU state. Use buttons.")
    return MAIN_MENU # Stay in the same state

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

    # --- Debugging log before defining handler --- 
    logger.debug(f"[DEBUG] Registering main_menu_callback function: {main_menu_callback}")

    # --- Main Conversation Handler --- 
    main_conv_handler = ConversationHandler(
        entry_points=[start_handler],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(main_menu_callback, pattern="^menu_quiz$"),
                CallbackQueryHandler(main_menu_callback, pattern="^menu_info$"),
                CallbackQueryHandler(main_menu_callback, pattern="^menu_stats$"),
                CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"),
                # Add a message handler for debugging within MAIN_MENU state
                MessageHandler(filters.TEXT & ~filters.COMMAND, debug_main_menu_message)
            ],
            QUIZ_MENU: [quiz_conv_handler],
            INFO_MENU: [info_conv_handler],
            STATS_MENU: [stats_conv_handler],
        },
        fallbacks=[
            start_handler,
        ],
        persistent=True,
        name="main_conversation",
        map_to_parent={
            MAIN_MENU: MAIN_MENU,
            END: END
        }
    )

    # --- Debugging log after defining handler --- 
    logger.debug(f"[DEBUG] Main ConversationHandler defined: {main_conv_handler}")

    # --- Register Handlers --- 
    application.add_handler(main_conv_handler)
    logger.debug("[DEBUG] Main ConversationHandler added to application.") # Log after adding
    application.add_error_handler(error_handler)

    # --- Start Bot --- 
    logger.info("Bot application configured. Starting polling...")
    application.run_polling()
    logger.info("Bot polling stopped.")


if __name__ == "__main__":
    main()

