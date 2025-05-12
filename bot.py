#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Main script for the Chemistry Quiz Telegram Bot (Modular Version - v16 - db_manager independent, admin handler debug).

Changes in this version:
- Added detailed logging for admin interface handler types and callability before adding them.
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
try:
    from config import (
        TELEGRAM_BOT_TOKEN, API_BASE_URL, DATABASE_URL, # Core config
        logger, # Logger instance
        MAIN_MENU, QUIZ_MENU, INFO_MENU, STATS_MENU, END # Conversation states
    )
    from database.db_setup import get_engine, create_tables # MODIFIED: create_connection to get_engine
    # print("DEBUG: Importing handlers.common...")
    from handlers.common import start_handler, main_menu_callback
    # print("DEBUG: handlers.common imported.")

    try:
        # print("DEBUG: Attempting to import quiz_conv_handler...")
        from handlers.quiz import quiz_conv_handler
        # print("DEBUG: Successfully imported quiz_conv_handler.")
    except Exception as import_exc:
        # print(f"CRITICAL: Failed to import quiz_conv_handler: {import_exc}")
        # traceback_str = traceback.format_exc()
        # print(f"CRITICAL: Traceback:\n{traceback_str}")
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
        from database.manager_definition import DatabaseManager 
        logger.info("Successfully imported new admin tools (edit/broadcast) and DatabaseManager.")
        new_admin_tools_loaded = True
    except ImportError as ie_new_admin:
        logger.warning(f"Could not import new admin tools (edit/broadcast) or DatabaseManager: {{ie_new_admin}}. New admin functionalities will be unavailable.")
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
        admin_interface_v4_loaded = False # Set flag if import fails

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
            # Assuming process_arabic_text is available if admin_interface was loaded, otherwise plain text
            error_message = "حدث خطأ ما. يرجى المحاولة مرة أخرى لاحقاً."
            try:
                from handlers.admin_interface import process_arabic_text
                error_message = process_arabic_text(error_message)
            except ImportError:
                pass # Use plain error message
            await context.bot.send_message(chat_id=update.effective_chat.id, text=error_message)
        except Exception as send_error:
            logger.error(f"Failed to send error message to user: {send_error}")

def main() -> None:
    """Start the bot."""
    global new_admin_tools_loaded, admin_interface_v4_loaded # Declare as global
    # Flags new_admin_tools_loaded and admin_interface_v4_loaded are set globally during imports.
    # Do not re-initialize them locally here.

    logger.info("Starting bot...")

    logger.info("Setting up database engine and tables using SQLAlchemy...")
    engine = None # Initialize engine to None
    try:
        # DATABASE_URL should be available from config.py, db_setup.py will use it
        engine = get_engine() # Call get_engine() from db_setup
        if engine:
            logger.info(f"SQLAlchemy engine created successfully for: {engine.url}")
            # create_tables now takes the engine directly
            create_tables(engine, drop_first=False)
            logger.info("Database tables checked/created successfully via db_setup using SQLAlchemy.")
        else:
            logger.error("Failed to create SQLAlchemy engine. Bot may not function correctly with database features.")
    except Exception as db_exc:
        logger.error(f"Error during initial SQLAlchemy database setup (get_engine or create_tables): {db_exc}", exc_info=True)
    # No explicit engine.close() here, SQLAlchemy manages connections.
    # The engine object itself is not a single connection to be closed in this manner.
    
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

        # --- Initialize and store DatabaseManager for new admin tools ---
        if new_admin_tools_loaded:
            try:
                db_manager_instance = DatabaseManager(database_url=DATABASE_URL) # MODIFIED: db_path to database_url
                if db_manager_instance and getattr(db_manager_instance, 'engine', None) is not None: # MODIFIED: Check for 'engine' instead of 'conn'
                    application.bot_data["DB_MANAGER"] = db_manager_instance
                    logger.info("DB_MANAGER for new admin tools initialized and stored in bot_data.")
                else:
                    logger.error("Failed to initialize DatabaseManager or its connection for new admin tools. Ensure DATABASE_URL is correct, path is writable, and database is accessible.")
                    new_admin_tools_loaded = False # Crucial: disable tools if DB manager is not usable
            except Exception as db_init_exc:
                logger.error(f"Exception during DatabaseManager initialization for new admin tools: {db_init_exc}", exc_info=True)
                new_admin_tools_loaded = False # Disable tools if DB manager fails
        # --- End DatabaseManager Initialization ---

        logger.info("DB_MANAGER will be imported and used directly by handlers, not stored in bot_data.")

        if job_queue:
            job_queue.set_application(application)
            logger.info("JobQueue attached to the application.")
        else:
            logger.warning("JobQueue was not created or attached. Timed features will not work.")

    except Exception as app_exc:
        logger.critical(f"Error building Telegram Application: {app_exc}. Bot cannot start.", exc_info=True)
        exit(1)

    if new_admin_tools_loaded:
        application.add_handler(CommandHandler("start", admin_start_command))
        application.add_handler(CommandHandler("about", admin_about_command))
        application.add_handler(CommandHandler("help", admin_help_command))
        logger.info("New admin tools command handlers (start, about, help) added.")
    else:
        # print("DEBUG: Adding common start_handler...")
        application.add_handler(CommandHandler("start", start_handler)) # start_handler is from handlers.common
        # Note: /about and /help commands might be missing if new_admin_tools_loaded is False
        # and they are not handled by other common handlers (e.g. if original bot.py had them).
        # The current dummy common.py handles 'about_bot' via a callback button, not a direct /about command.
        logger.info("Common start_handler (from handlers.common) added as CommandHandler.")

    if quiz_conv_handler:
        # print("DEBUG: Adding quiz_conv_handler...")
        application.add_handler(quiz_conv_handler)
        # print("DEBUG: quiz_conv_handler added.")
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

    # Add New Admin Statistics (V4/V7/V8) Handlers if imported successfully
    if admin_interface_v4_loaded:
        logger.info("Adding New Admin Statistics (V4/V7/V8) handlers (e.g., /adminstats_v4)...")
        
        # Log types and callability for debugging the TypeError
        logger.info(f"[HANDLER_DEBUG] stats_admin_panel_command_handler_v4: type={type(stats_admin_panel_command_handler_v4)}, callable={callable(stats_admin_panel_command_handler_v4)}")
        logger.info(f"[HANDLER_DEBUG] stats_menu_callback_handler_v4: type={type(stats_menu_callback_handler_v4)}, callable={callable(stats_menu_callback_handler_v4)}")
        logger.info(f"[HANDLER_DEBUG] stats_fetch_callback_handler_v4: type={type(stats_fetch_callback_handler_v4)}, callable={callable(stats_fetch_callback_handler_v4)}")

        application.add_handler(CommandHandler("adminstats_v4", stats_admin_panel_command_handler_v4))
        
        # Using the functions directly as they are confirmed to be functions by imports
        application.add_handler(CallbackQueryHandler(stats_menu_callback_handler_v4, pattern=f"^{STATS_PREFIX_MAIN_MENU_V4}"))
        application.add_handler(CallbackQueryHandler(stats_fetch_callback_handler_v4, pattern=f"^{STATS_PREFIX_FETCH_V4}"))
        
        logger.info("New Admin Statistics (V4/V7/V8) handlers added for /adminstats_v4.")
    else:
        logger.warning("New Admin Statistics (V4/V7/V8) handlers were not imported, skipping their addition.")

    logger.info("Adding global main_menu_callback handler...")
    application.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^(main_menu|about_bot)$"))
    logger.info("Global main_menu_callback handler added.")

    # --- Add New Admin Tools Handlers (Edit Messages, Broadcast) ---
    if new_admin_tools_loaded:
        logger.info("Adding new admin tools (edit/broadcast) handlers...")

        # Conversation handler for editing messages
        edit_message_conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(admin_edit_specific_message_callback, pattern=r"^admin_edit_specific_msg_")
            ],
            states={
                EDIT_MESSAGE_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_new_message_text)],
            },
            fallbacks=[
                CommandHandler("cancel_edit", cancel_edit_command),
                CallbackQueryHandler(admin_show_tools_menu_callback, pattern=r"^admin_show_tools_menu$"),
                CallbackQueryHandler(admin_edit_other_messages_menu_callback, pattern=r"^admin_edit_other_messages_menu$")
            ],
            persistent=False, # As per PicklePersistence setup
            map_to_parent={
                ConversationHandler.END: ConversationHandler.END
            }
        )

        # Conversation handler for broadcasting messages
        broadcast_conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_broadcast_start_callback, pattern=r"^admin_broadcast_start$")],
            states={
                BROADCAST_MESSAGE_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_broadcast_text)],
                BROADCAST_CONFIRM: [
                    CallbackQueryHandler(admin_broadcast_confirm_callback, pattern=r"^admin_broadcast_confirm$"),
                    CallbackQueryHandler(admin_broadcast_cancel_callback, pattern=r"^admin_broadcast_cancel$")
                ]
            },
            fallbacks=[
                CommandHandler("cancel_broadcast", cancel_broadcast_command),
                CallbackQueryHandler(admin_show_tools_menu_callback, pattern=r"^admin_show_tools_menu$"),
            ],
            persistent=False, # As per PicklePersistence setup
            map_to_parent={
                ConversationHandler.END: ConversationHandler.END
            }
        )

        application.add_handler(edit_message_conv_handler)
        application.add_handler(broadcast_conv_handler)

        # Add callback query handlers for new admin tools navigation
        application.add_handler(CallbackQueryHandler(admin_show_tools_menu_callback, pattern=r"^admin_show_tools_menu$"))
        application.add_handler(CallbackQueryHandler(admin_edit_other_messages_menu_callback, pattern=r"^admin_edit_other_messages_menu$"))
        application.add_handler(CallbackQueryHandler(admin_back_to_start_callback, pattern=r"^admin_back_to_start$"))
        
        logger.info("New admin tools (edit/broadcast) ConversationHandlers and CallbackQueryHandlers added.")
    else:
        logger.warning("New admin tools (edit/broadcast) were not loaded, skipping their handlers.")
    # --- End Add New Admin Tools Handlers ---

    # print("DEBUG: Adding error_handler...")
    application.add_error_handler(error_handler)
    # print("DEBUG: error_handler added.")

    logger.info("Bot application configured with direct handlers. Starting polling...")
    application.run_polling()
    logger.info("Bot polling stopped.")

if __name__ == "__main__":
    main()

