# -*- coding: utf-8 -*-
"""Common handlers like /start and main menu navigation."""

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
        [InlineKeyboardButton("🧠 بدء اختبار جديد", callback_data="quiz_start")], # MODIFIED: Was quiz_menu, now matches quiz.py pattern="^quiz_start$"
        [InlineKeyboardButton("📚 معلومات كيميائية", callback_data="menu_info")], 
        [InlineKeyboardButton("📊 إحصائياتي ولوحة الصدارة", callback_data="menu_stats")], 
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
        if data == "quiz_start": # MODIFIED: Changed from quiz_menu to quiz_start
            # This will now be caught by the quiz_conv_handler entry point
            # The ConversationHandler in bot.py should have quiz_conv_handler as a top-level handler
            # or this callback needs to be explicitly routed to QUIZ_MENU state if main_menu_callback is part of a larger ConversationHandler
            # For simplicity, assuming quiz_conv_handler is directly registered with Application
            # and its entry point pattern="^quiz_start$" will pick this up.
            # If main_menu_callback is part of a MAIN ConversationHandler, then this should return QUIZ_MENU
            # and the main ConversationHandler should have an entry point for quiz_start that leads to the quiz conversation.
            # Given the current structure, this callback might not even be strictly necessary if quiz_start directly triggers quiz_conv_handler.
            # However, if it IS part of a larger conversation handler, it should return the state that triggers the quiz.
            # For now, let's assume it's meant to transition to a state handled by quiz.py
            logger.debug(f"Callback 'quiz_start' received. This should be handled by quiz_conv_handler directly.")
            # If this main_menu_callback is part of a larger ConversationHandler that has QUIZ_MENU as a state
            # and quiz_conv_handler is nested, then this should return QUIZ_MENU.
            # If quiz_conv_handler is a top-level handler, this specific 'if' branch might not be hit if the pattern is caught by quiz_conv_handler first.
            # Let's assume for now that the main dispatcher will route 'quiz_start' to quiz_conv_handler.
            # No explicit state return needed here if quiz_conv_handler handles it.
            # However, to be safe and align with how other buttons might work if they were states:
            return QUIZ_MENU # This signals to a potential parent ConversationHandler to transition.

        elif data == "menu_info": 
            state_to_return = INFO_MENU
        elif data == "menu_stats": 
            state_to_return = STATS_MENU
        elif data == "main_menu": 
            state_to_return = MAIN_MENU
        else:
            logger.warning(f"Unknown main menu callback data: '{data}'")
            state_to_return = MAIN_MENU 

    if state_to_return == MAIN_MENU:
        menu_text = "القائمة الرئيسية:"
        keyboard = create_main_menu_keyboard(user.id)
        if query:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=menu_text, reply_markup=keyboard)
        else: 
            await safe_send_message(context.bot, update.effective_chat.id, text=menu_text, reply_markup=keyboard)

    logger.debug(f"[DEBUG] main_menu_callback attempting to return state: {state_to_return}")
    return state_to_return

# --- Handler Definitions --- 

start_handler = CommandHandler('start', start_command)

# This handler is for the 
