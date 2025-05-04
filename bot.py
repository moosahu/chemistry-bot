#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Main script for the Chemistry Quiz Telegram Bot (Modular Version)."""

import logging

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters, # Import filters (lowercase) instead of Filters
    PicklePersistence # For storing conversation state across restarts
)

# --- Import Configuration and Core Components --- 
try:
    from config import (
        TELEGRAM_BOT_TOKEN, API_BASE_URL, DATABASE_URL, # Core config
        logger, # Logger instance
        MAIN_MENU, QUIZ_MENU, SELECT_QUIZ_TYPE, SELECT_QUIZ_SCOPE, 
        ENTER_QUESTION_COUNT, TAKING_QUIZ, SHOWING_RESULTS, 
        INFO_MENU, STATS_MENU, SHOW_INFO_DETAIL, END # Conversation states
    )
    # Import database setup function
    from database.schema import setup_database_schema, apply_schema_updates
    # Import handlers
    from handlers.common import start_handler, main_menu_handler, main_menu_callback
    from handlers.quiz import quiz_conv_handler
    from handlers.info import info_conv_handler
    from handlers.stats import stats_conv_handler
except ImportError as e:
    # Basic logging if config fails
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
def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    # Optionally, notify the user or admin about the error
    # Example: if update and hasattr(update, "effective_chat") and update.effective_chat:
    #     context.bot.send_message(chat_id=update.effective_chat.id, text="حدث خطأ ما. يرجى المحاولة مرة أخرى لاحقاً.")

# --- Main Function --- 
def main() -> None:
    """Start the bot."""
    logger.info("Starting bot...")

    # --- Database Setup --- 
    logger.info("Setting up database schema...")
    if not setup_database_schema():
        logger.error("Database initial schema setup failed. Check connection and schema script.")
        # Decide if bot should continue without DB or exit
        # exit(1) # Uncomment to exit if DB setup is critical
    else:
        logger.info("Initial schema setup/check successful.")
        # Apply any pending updates
        if not apply_schema_updates():
            logger.warning("Applying schema updates failed. Bot will continue, but some features might be affected.")
        else:
            logger.info("Schema updates applied successfully.")

    # --- Persistence --- 
    # Use PicklePersistence to save conversation states across restarts
    # Note: For production, consider using a database-backed persistence layer
    persistence = PicklePersistence(filepath="bot_conversation_persistence.pkl")

    # --- Application Setup --- 
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .persistence(persistence)
        .build()
    )

    # --- Main Conversation Handler --- 
    # This handler manages the top-level states (MAIN_MENU, QUIZ_MENU, INFO_MENU, STATS_MENU)
    # It delegates to specific conversation handlers (quiz_conv_handler, etc.) for sub-flows
    main_conv_handler = ConversationHandler(
        entry_points=[start_handler], # Start with /start
        states={
            MAIN_MENU: [
                # Entry point for sub-conversations
                quiz_conv_handler, 
                info_conv_handler,
                stats_conv_handler,
                # Handle direct return to main menu (e.g., from sub-menus)
                main_menu_handler, 
                # Fallback within MAIN_MENU if no other handler matches
                CallbackQueryHandler(main_menu_callback) 
            ],
            # Other top-level states could be added here if needed
        },
        fallbacks=[
            start_handler, # Allow restarting with /start
            # Add a generic fallback message for the main conversation?
            MessageHandler(filters.ALL, lambda u, c: main_fallback(u, c))
        ],
        # Use persistence for conversation state
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

def main_fallback(update: Update, context: CallbackContext):
    """Generic fallback handler for the main conversation (if not in a sub-conversation)."""
    logger.warning(f"Main fallback triggered for update: {update}")
    # Simply send the user back to the main menu via the start_handler logic
    # Need to ensure start_handler sends a new message or edits if possible
    # Re-using main_menu_callback might be better if it handles sending/editing
    if update.effective_chat:
        context.bot.send_message(update.effective_chat.id, "أمر غير معروف. العودة إلى القائمة الرئيسية.")
    return main_menu_callback(update, context)

if __name__ == "__main__":
    main()

