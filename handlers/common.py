# -*- coding: utf-8 -*-
"""Common handlers like /start and main menu navigation (Corrected v3 - Fixed info/stats button callbacks)."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler

# Import necessary components from other modules
try:
    from config import logger, MAIN_MENU, QUIZ_MENU, INFO_MENU, STATS_MENU
    from utils.helpers import safe_send_message, safe_edit_message_text # Ensure these are async
    from database.manager import DB_MANAGER # Import the initialized DB_MANAGER instance
except ImportError as e:
    # Fallback for potential import issues during development/restructuring
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error(f"Error importing modules in handlers.common: {e}. Using placeholders.")
    # Define placeholders for constants and functions
    MAIN_MENU, QUIZ_MENU, INFO_MENU, STATS_MENU = 0, 1, 7, 8 # Match config.py
    async def safe_send_message(bot, chat_id, text, reply_markup=None, parse_mode=None):
        logger.error("Placeholder safe_send_message called!")
        try: await bot.send_message(chat_id=chat_id, text="Error: Bot function unavailable.")
        except: pass
    async def safe_edit_message_text(query, text, reply_markup=None, parse_mode=None):
        logger.error("Placeholder safe_edit_message_text called!")
        try: await query.edit_message_text(text="Error: Bot function unavailable.")
        except: pass
    # Dummy DB_MANAGER
    class DummyDBManager:
        def register_or_update_user(*args, **kwargs): logger.warning("Dummy DB_MANAGER.register_or_update_user called"); return True
        def is_user_admin(*args, **kwargs): logger.warning("Dummy DB_MANAGER.is_user_admin called"); return False
    DB_MANAGER = DummyDBManager()

def create_main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Creates the main menu keyboard, potentially showing admin options."""
    keyboard = [
        # Use callback_data that matches the entry point patterns of the handlers
        [InlineKeyboardButton("🧠 بدء اختبار جديد", callback_data="quiz_menu")], # Matches quiz.py pattern="^quiz_menu$"
        [InlineKeyboardButton("📚 معلومات كيميائية", callback_data="menu_info")], # **FIXED**: Matches info.py pattern="^menu_info$"
        [InlineKeyboardButton("📊 إحصائياتي ولوحة الصدارة", callback_data="menu_stats")], # **FIXED**: Matches stats.py pattern="^menu_stats$"
        # Add other main menu items here
    ]
    # Example: Add an admin button if the user is an admin
    # if DB_MANAGER and DB_MANAGER.is_user_admin(user_id):
    #     keyboard.append([InlineKeyboardButton("⚙️ لوحة الإدارة", callback_data="admin_menu")]) # Use admin_menu if needed
    
    return InlineKeyboardMarkup(keyboard)

async def start_command(update: Update, context: CallbackContext) -> int:
    """Handles the /start command. Registers user and shows the main menu."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    logger.info(f"User {user.id} ({user.username or user.first_name}) started the bot in chat {chat_id}.")

    # Register or update user in the database
    if DB_MANAGER:
        # Assuming DB call is synchronous for now
        DB_MANAGER.register_or_update_user(
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            language_code=user.language_code
        )
    else:
        logger.warning("DB_MANAGER not available, skipping user registration.")

    # Send welcome message and main menu
    welcome_text = f"أهلاً بك يا {user.first_name} في بوت كيمياء تحصيلي! 👋\n\n" \
                   "استخدم الأزرار أدناه لبدء اختبار أو استعراض المعلومات."
    keyboard = create_main_menu_keyboard(user.id)
    await safe_send_message(context.bot, chat_id, text=welcome_text, reply_markup=keyboard)

    return MAIN_MENU # Set the initial state

async def main_menu_callback(update: Update, context: CallbackContext) -> int:
    """Handles callbacks from the main menu keyboard or returns to the main menu."""
    query = update.callback_query
    user = update.effective_user
    state_to_return = MAIN_MENU # Default state

    if query:
        await query.answer() # Answer callback query
        data = query.data
        logger.info(f"Main menu callback: User {user.id} chose 	'{data}'.") 

        # Determine next state based on callback data
        # **FIXED**: Compare with corrected callback_data values matching handler patterns
        if data == "quiz_menu":
            state_to_return = QUIZ_MENU
        elif data == "menu_info": # **FIXED**
            state_to_return = INFO_MENU
        elif data == "menu_stats": # **FIXED**
            state_to_return = STATS_MENU
        # Add other menu options here
        # elif data == "admin_menu":
        #     state_to_return = ADMIN_MENU
        elif data == "main_menu": # Explicitly handle returning to main menu
            state_to_return = MAIN_MENU
        else:
            logger.warning(f"Unknown main menu callback data: '{data}'")
            state_to_return = MAIN_MENU # Stay in main menu on unknown data

    # If returning to the main menu (or staying), edit the message
    if state_to_return == MAIN_MENU:
        menu_text = "القائمة الرئيسية:"
        keyboard = create_main_menu_keyboard(user.id)
        if query:
            await safe_edit_message_text(query, text=menu_text, reply_markup=keyboard)
        else: # Should not happen if called via callback, but handle direct call case
            await safe_send_message(context.bot, update.effective_chat.id, text=menu_text, reply_markup=keyboard)

    # The actual state transition is handled by the ConversationHandler return value
    # The specific handlers for QUIZ_MENU, INFO_MENU, etc., will be called next
    # and are responsible for editing the message or sending a new one.
    logger.debug(f"[DEBUG] main_menu_callback attempting to return state: {state_to_return}")
    return state_to_return

# --- Handler Definitions --- 

# Command handler for /start
start_handler = CommandHandler('start', start_command)

# Callback query handler for navigating back to the main menu
# This specifically handles the 'main_menu' callback data
# Other main menu buttons ('quiz_menu', 'menu_info', etc.) act as entry points
# to other ConversationHandlers or trigger state changes handled by the main dispatcher.
main_menu_handler = CallbackQueryHandler(main_menu_callback, pattern='^main_menu$')

# Note: The main ConversationHandler in bot.py will use main_menu_callback
# for the MAIN_MENU state to handle the initial button presses ('quiz_menu', etc.)

