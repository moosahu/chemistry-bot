# -*- coding: utf-8 -*-
"""
Chemistry Quiz and Info Telegram Bot

This bot provides chemistry quizzes and information.
"""

import logging
import os
import sys
import random
import math
import time
import re
from io import BytesIO
from datetime import datetime, timedelta

# Third-party libraries
import pandas as pd
import psycopg2
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ParseMode,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InputMediaPhoto
)
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    CallbackQueryHandler,
    ConversationHandler,
    JobQueue
)
from telegram.error import BadRequest, TelegramError, NetworkError, Unauthorized, TimedOut, ChatMigrated

# --- Configuration & Constants ---

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Get sensitive info from environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_USER_ID = 6448526509 # Hardcoded as requested
PORT = int(os.environ.get("PORT", 8443))
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME")

if not BOT_TOKEN:
    logger.critical("BOT_TOKEN environment variable not set!")
    sys.exit("Bot token not found.")

# Quiz settings
DEFAULT_QUIZ_QUESTIONS = 10
DEFAULT_QUIZ_DURATION_MINUTES = 10
QUESTION_TIMER_SECONDS = 240
FEEDBACK_DELAY = 2

# --- Database Setup ---
try:
    from db_utils import connect_db, setup_database
    from quiz_db import QuizDatabase
    from helper_function import safe_edit_message_text
except ImportError as e:
    logger.error(f"Failed to import database modules: {e}. Make sure db_utils.py, quiz_db.py, helper_function.py are present.")
    sys.exit("Critical import error, stopping bot.")

# Import chemistry data (optional)
try:
    from chemistry_data import ELEMENTS, COMPOUNDS, CONCEPTS, PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO
    from chemical_equations import process_text_with_chemical_notation, format_chemical_equation
except ImportError as e:
    logger.warning(f"Could not import chemistry_data.py or chemical_equations.py: {e}. Some features might be limited.")
    ELEMENTS, COMPOUNDS, CONCEPTS, PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO = {}, {}, {}, {}, {}, {}
    def process_text_with_chemical_notation(text): return text
    def format_chemical_equation(text): return text

# Initialize database connection and QuizDatabase instance
if not DATABASE_URL:
    logger.error("DATABASE_URL environment variable not set or empty. Bot cannot connect to DB.")
    sys.exit("Database configuration error.")

DB_CONN = connect_db(DATABASE_URL)
if DB_CONN:
    setup_database(DB_CONN)
    QUIZ_DB = QuizDatabase(DB_CONN)
    logger.info("QuizDatabase initialized successfully.")
else:
    logger.error("Failed to establish database connection. Bot cannot function properly.")
    sys.exit("Database connection failed.")

# --- States for Conversation Handler ---
# Define states globally
(
    MAIN_MENU, QUIZ_MENU, ADMIN_MENU, ADDING_QUESTION, ADDING_OPTIONS,
    ADDING_CORRECT_ANSWER, ADDING_EXPLANATION, DELETING_QUESTION,
    SHOWING_QUESTION, SELECTING_QUIZ_TYPE, SELECTING_CHAPTER,
    SELECTING_LESSON, SELECTING_QUIZ_DURATION, TAKING_QUIZ,
    SELECT_CHAPTER_FOR_LESSON, SELECT_LESSON_FOR_QUIZ, SELECT_CHAPTER_FOR_QUIZ,
    SELECT_GRADE_LEVEL, SELECT_GRADE_LEVEL_FOR_QUIZ, ADMIN_GRADE_MENU,
    ADMIN_CHAPTER_MENU, ADMIN_LESSON_MENU, ADDING_GRADE_LEVEL,
    ADDING_CHAPTER, ADDING_LESSON, SELECTING_GRADE_FOR_CHAPTER,
    SELECTING_CHAPTER_FOR_LESSON_ADMIN, ADMIN_MANAGE_STRUCTURE,
    ADMIN_MANAGE_GRADES, ADMIN_MANAGE_CHAPTERS, ADMIN_MANAGE_LESSONS,
    # INFO_MENU state is defined in info_handlers/info_menu_function, we don't need it here
    # unless it's used directly in THIS file's handlers.
) = range(31) # Adjusted range to 31 states, INFO_MENU handled separately

# --- Helper Functions ---

def is_admin(user_id):
    return str(user_id) == str(ADMIN_USER_ID)

def get_user_name(user):
    if user.first_name and user.last_name:
        return f"{user.first_name} {user.last_name}"
    elif user.first_name:
        return user.first_name
    elif user.username:
        return user.username
    else:
        return str(user.id)

# --- Keyboard Creation Functions (Corrected callback_data) ---

def create_main_menu_keyboard(user_id):
    keyboard = [
        [InlineKeyboardButton("📚 المعلومات الكيميائية", callback_data=\'menu_info\')], # Matches info_handlers entry point
        [InlineKeyboardButton("📝 الاختبارات", callback_data=\'menu_quiz\')],
        [InlineKeyboardButton("📊 تقارير الأداء", callback_data=\'menu_reports\')],
        [InlineKeyboardButton("ℹ️ حول البوت", callback_data=\'menu_about\')]
    ]
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ إدارة البوت", callback_data=\'menu_admin\')])
    return InlineKeyboardMarkup(keyboard)

def create_quiz_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🎯 اختبار تحصيلي عام", callback_data=\'quiz_random_prompt\')],
        [InlineKeyboardButton("📄 اختبار حسب الفصل", callback_data=\'quiz_by_chapter_prompt\')],
        [InlineKeyboardButton("📝 اختبار حسب الدرس", callback_data=\'quiz_by_lesson_prompt\')],
        [InlineKeyboardButton("🎓 اختبار حسب المرحلة الدراسية", callback_data=\'quiz_by_grade_prompt\')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=\'main_menu\')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_admin_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ إضافة سؤال", callback_data=\'admin_add_question\')],
        [InlineKeyboardButton("🗑️ حذف سؤال", callback_data=\'admin_delete_question\')],
        [InlineKeyboardButton("🔍 عرض سؤال", callback_data=\'admin_show_question\')],
        [InlineKeyboardButton("🏫 إدارة المراحل/الفصول/الدروس", callback_data=\'admin_manage_structure\')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=\'main_menu\')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_structure_admin_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🏫 إدارة المراحل الدراسية", callback_data=\'admin_manage_grades\')],
        [InlineKeyboardButton("📚 إدارة الفصول", callback_data=\'admin_manage_chapters\')],
        [InlineKeyboardButton("📝 إدارة الدروس", callback_data=\'admin_manage_lessons\')],
        [InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data=\'menu_admin\')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_quiz_duration_keyboard():
    keyboard = [
        [InlineKeyboardButton("5 دقائق", callback_data=\'quiz_duration_5\')],
        [InlineKeyboardButton("10 دقائق", callback_data=\'quiz_duration_10\')],
        [InlineKeyboardButton("15 دقائق", callback_data=\'quiz_duration_15\')],
        [InlineKeyboardButton("20 دقائق", callback_data=\'quiz_duration_20\')],
        [InlineKeyboardButton("30 دقائق", callback_data=\'quiz_duration_30\')],
        [InlineKeyboardButton("بدون وقت محدد", callback_data=\'quiz_duration_0\')],
        [InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data=\'menu_quiz\')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_grade_levels_keyboard(for_quiz=False, context=None):
    grades = QUIZ_DB.get_all_grade_levels()
    keyboard = []
    if grades:
        for grade_id, grade_name in grades:
            callback_suffix = f\'quiz_{grade_id}\' if for_quiz else f\'admin_{grade_id}\'
            keyboard.append([InlineKeyboardButton(grade_name, callback_data=f\'grade_{callback_suffix}\')])
        if for_quiz:
             keyboard.append([InlineKeyboardButton("📚 اختبار تحصيلي عام", callback_data=\'grade_quiz_all\')])
    else:
        logger.info("No grade levels found in the database.")
        return None
    back_callback = \'menu_quiz\' if for_quiz else \'admin_manage_structure\'
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_chapters_keyboard(grade_level_id, for_quiz=False, for_lesson=False, context=None):
    chapters = QUIZ_DB.get_chapters_by_grade(grade_level_id)
    keyboard = []
    if chapters:
        for chapter_id, chapter_name in chapters:
            if for_quiz:
                callback_data = f\'chapter_quiz_{chapter_id}\'
            elif for_lesson:
                 callback_data = f\'lesson_chapter_{chapter_id}\'
            else:
                callback_data = f\'admin_chapter_{chapter_id}\'
            keyboard.append([InlineKeyboardButton(chapter_name, callback_data=callback_data)])
    else:
        logger.info(f"No chapters found for grade level {grade_level_id}.")
        return None
    if for_quiz or for_lesson:
        back_callback = \'quiz_by_grade_prompt\'
    else:
        back_callback = \'admin_manage_structure\'
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_lessons_keyboard(chapter_id, for_quiz=False, context=None):
    lessons = QUIZ_DB.get_lessons_by_chapter(chapter_id)
    keyboard = []
    if lessons:
        for lesson_id, lesson_name in lessons:
            callback_data = f\'lesson_quiz_{lesson_id}\' if for_quiz else f\'admin_lesson_{lesson_id}\'
            keyboard.append([InlineKeyboardButton(lesson_name, callback_data=callback_data)])
    else:
        logger.info(f"No lessons found for chapter {chapter_id}.")
        return None
    if for_quiz:
        back_callback = \'quiz_by_lesson_prompt\'
    else:
        back_callback = \'admin_manage_structure\'
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_quiz_question_keyboard(options, question_id):
    keyboard = []
    shuffled_options = list(enumerate(options))
    random.shuffle(shuffled_options)
    for original_index, option_text in shuffled_options:
        callback_data = f\'answer_{question_id}_{original_index}\'
        keyboard.append([InlineKeyboardButton(option_text, callback_data=callback_data)])
    keyboard.append([InlineKeyboardButton("⏭️ تخطي السؤال", callback_data=f\'skip_{question_id}\')])
    return InlineKeyboardMarkup(keyboard)

def create_results_menu_keyboard(quiz_id):
    keyboard = [
        [InlineKeyboardButton("🔄 إعادة الاختبار", callback_data=\'menu_quiz\')],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data=\'main_menu\')]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Timer Functions (Placeholders - require full implementation) ---
def set_quiz_timer(context: CallbackContext, chat_id, user_id, quiz_id, duration_minutes):
    logger.warning("set_quiz_timer is a placeholder.")
    return None

def set_question_timer(context: CallbackContext, chat_id, user_id, quiz_id):
    logger.warning("set_question_timer is a placeholder.")
    return None

def end_quiz_timeout(context: CallbackContext):
    logger.warning("end_quiz_timeout is a placeholder.")
    # Needs implementation to properly end the quiz

def question_timer_callback(context: CallbackContext):
    logger.warning("question_timer_callback is a placeholder.")
    # Needs implementation to handle question timeout

# --- Core Command Handlers ---

def start(update: Update, context: CallbackContext) -> int:
    """Handles the /start command and displays the main menu."""
    # --- ADDED LOGGING --- #
    logger.critical("!!!!!!!!!!!!!! START HANDLER TRIGGERED !!!!!!!!!!!!!!")
    # --------------------- #
    user = update.effective_user
    user_id = user.id
    user_name = get_user_name(user)
    logger.info(f"User {user_name} (ID: {user_id}) started the bot.")

    # Check if user exists, add if not (using placeholder function)
    if not QUIZ_DB.user_exists(user_id):
        QUIZ_DB.add_user(user_id, user_name)
        logger.info(f"New user {user_name} (ID: {user_id}) added to the database.")

    # Send main menu message
    text = f"أهلاً بك يا {user_name} في بوت الكيمياء التعليمي!\n\nاختر أحد الخيارات التالية:"
    keyboard = create_main_menu_keyboard(user_id)

    if update.message:
        logger.info("Replying to message in start handler")
        update.message.reply_text(text, reply_markup=keyboard)
    elif update.callback_query: # Handle coming back from another menu
        logger.info("Editing message in start handler (from callback)")
        query = update.callback_query
        query.answer()
        safe_edit_message_text(query, text=text, reply_markup=keyboard)
    else:
        logger.warning("Update in start handler is neither message nor callback query")

    logger.info("Returning MAIN_MENU state from start handler")
    return MAIN_MENU # Return the main menu state

def main_menu_callback(update: Update, context: CallbackContext) -> int:
    """Handles callbacks from main menu buttons or returns to main menu."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    logger.info(f"Main menu callback: User {user_id} chose {data}")

    # Always answer the callback query
    query.answer()

    # Determine next action based on callback data
    if data == \'menu_info\':
        # This should now be handled by info_menu_conv_handler entry point
        logger.info("Transitioning to info menu via info_menu_conv_handler entry point")
        # We need to call the entry point function of the other handler
        try:
            from info_menu_function import show_info_menu
            return show_info_menu(update, context)
        except ImportError as e:
             logger.error(f"Cannot call show_info_menu directly: {e}")
             safe_edit_message_text(query, text="Error accessing info menu.")
             return MAIN_MENU # Stay in main menu

    elif data == \'menu_quiz\':
        text = "اختر نوع الاختبار الذي تريده:"
        keyboard = create_quiz_menu_keyboard()
        safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return QUIZ_MENU # Transition to quiz menu state

    elif data == \'menu_reports\':
        text = "📊 قسم تقارير الأداء قيد التطوير حالياً."
        keyboard = create_main_menu_keyboard(user_id)
        safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return MAIN_MENU # Stay in main menu

    elif data == \'menu_about\':
        text = ("**حول بوت الكيمياء التعليمي**\n\n"
                "هذا البوت يهدف لمساعدتك في تعلم الكيمياء واختبار معلوماتك.\n"
                "**المميزات الحالية:**\n"
                "- عرض أهم قوانين التحصيلي في الكيمياء.\n"
                "- (قريباً) اختبارات متنوعة.\n"
                "- (قريباً) تتبع الأداء.\n\n"
                "**تطوير الاستاذ حسين الموسى**\n\n"
                "نتمنى لك رحلة تعليمية ممتعة! ✨")
        keyboard = create_main_menu_keyboard(user_id)
        safe_edit_message_text(query, text=text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        return MAIN_MENU # Stay in main menu

    elif data == \'menu_admin\' and is_admin(user_id):
        text = "⚙️ قائمة إدارة البوت:"
        keyboard = create_admin_menu_keyboard()
        safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return ADMIN_MENU # Transition to admin menu state

    elif data == \'main_menu\': # Handle explicit return to main menu
        return start(update, context) # Reuse start handler logic

    else:
        # Unknown callback data in main menu context
        query.answer("خيار غير معروف")
        return MAIN_MENU # Stay in main menu

# --- Placeholder Handlers for Other Menus/Features ---

def quiz_menu_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.from_user.id
    logger.info(f"Quiz menu callback: User {user_id} chose {data}")

    if data == \'quiz_random_prompt\':
        text = "قسم الاختبار التحصيلي العام قيد التطوير."
        safe_edit_message_text(query, text=text, reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU
    elif data == \'quiz_by_chapter_prompt\':
        text = "قسم الاختبار حسب الفصل قيد التطوير."
        safe_edit_message_text(query, text=text, reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU
    elif data == \'quiz_by_lesson_prompt\':
        text = "قسم الاختبار حسب الدرس قيد التطوير."
        safe_edit_message_text(query, text=text, reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU
    elif data == \'quiz_by_grade_prompt\':
        text = "قسم الاختبار حسب المرحلة الدراسية قيد التطوير."
        safe_edit_message_text(query, text=text, reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU
    elif data == \'main_menu\':
        return start(update, context)
    else:
        return QUIZ_MENU # Stay in quiz menu for unknown options

def admin_menu_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.from_user.id
    logger.info(f"Admin menu callback: User {user_id} chose {data}")

    if not is_admin(user_id):
        query.answer("عذراً، هذه المنطقة مخصصة للمشرفين فقط.")
        return ConversationHandler.END # Or return to MAIN_MENU

    if data == \'admin_add_question\':
        text = "قسم إضافة الأسئلة قيد التطوير."
        safe_edit_message_text(query, text=text, reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU
    elif data == \'admin_delete_question\':
        text = "قسم حذف الأسئلة قيد التطوير."
        safe_edit_message_text(query, text=text, reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU
    elif data == \'admin_show_question\':
        text = "قسم عرض الأسئلة قيد التطوير."
        safe_edit_message_text(query, text=text, reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU
    elif data == \'admin_manage_structure\':
        text = "إدارة المراحل/الفصول/الدروس قيد التطوير."
        # Example: Show structure admin menu if implemented
        # keyboard = create_structure_admin_menu_keyboard()
        # safe_edit_message_text(query, text=text, reply_markup=keyboard)
        # return ADMIN_MANAGE_STRUCTURE # Need this state defined
        safe_edit_message_text(query, text=text, reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU # Stay in admin menu for now
    elif data == \'main_menu\':
        return start(update, context)
    else:
        return ADMIN_MENU # Stay in admin menu

def error_handler(update: Update, context: CallbackContext):
    """Log Errors caused by Updates."""
    logger.warning(f"Update \"{update}\" caused error \"{context.error}\"")
    # Add more specific error handling if needed
    if isinstance(context.error, BadRequest):
        logger.error(f"BadRequest Error: {context.error.message}")
        # Handle specific BadRequest errors, e.g., message not modified
        if "Message is not modified" in context.error.message:
            logger.info("Ignoring BadRequest: Message is not modified")
            if update and update.callback_query:
                update.callback_query.answer() # Answer query even if message not modified
        else:
            # Try to inform the user about other bad requests if possible
            if update and update.effective_chat:
                try:
                    context.bot.send_message(chat_id=update.effective_chat.id, text="حدث خطأ ما أثناء معالجة طلبك.")
                except Exception as e:
                    logger.error(f"Failed to send error message to user: {e}")
    elif isinstance(context.error, TimedOut):
        logger.error("Network Timeout Error")
    elif isinstance(context.error, NetworkError):
        logger.error(f"Network Error: {context.error}")
    elif isinstance(context.error, ChatMigrated):
        logger.warning(f"Chat migrated to {context.error.new_chat_id}")
    elif isinstance(context.error, Unauthorized):
        logger.error("Unauthorized Error - Bot might be blocked by the user")
    else:
        logger.error(f"Unhandled error: {context.error}")

# --- Main Function --- #
def main():
    """Start the bot."""
    # Create the Updater and pass it your bot's token.
    updater = Updater(BOT_TOKEN, use_context=True)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # --- Import Handlers Here to Avoid Circular Import --- #
    try:
        # Import the handler itself, not just the function
        from info_handlers import info_menu_conv_handler
    except ImportError as e:
        logger.error(f"Failed to import info_menu_conv_handler: {e}")
        info_menu_conv_handler = None # Set to None if import fails

    # --- Setup Main Conversation Handler --- #
    # This handler manages the main states: MAIN_MENU, QUIZ_MENU, ADMIN_MENU
    main_conv_handler = ConversationHandler(
        entry_points=[CommandHandler(\'start\', start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(main_menu_callback, pattern=\'^menu_\'), # Handles main menu buttons
                CallbackQueryHandler(main_menu_callback, pattern=\'^main_menu$\') # Handles explicit return button
            ],
            QUIZ_MENU: [
                CallbackQueryHandler(quiz_menu_callback, pattern=\'^quiz_\'), # Handles quiz menu buttons
                CallbackQueryHandler(main_menu_callback, pattern=\'^main_menu$\') # Handles return button
            ],
            ADMIN_MENU: [
                CallbackQueryHandler(admin_menu_callback, pattern=\'^admin_\'), # Handles admin menu buttons
                CallbackQueryHandler(main_menu_callback, pattern=\'^main_menu$\') # Handles return button
            ],
            # Add other top-level states here if needed (e.g., TAKING_QUIZ)
        },
        fallbacks=[
            CommandHandler(\'start\', start) # Allow restarting with /start
            # Add other fallbacks like /cancel if needed
        ],
        # If conversations time out, return to start
        conversation_timeout=timedelta(hours=1).total_seconds(),
        # Allow reentry for flexibility
        allow_reentry=True
    )

    # Add the main conversation handler
    dp.add_handler(main_conv_handler)

    # Add the info menu conversation handler IF it was imported successfully
    if info_menu_conv_handler:
        dp.add_handler(info_menu_conv_handler)
        logger.info("Info menu conversation handler added.")
    else:
        logger.warning("Info menu conversation handler could not be added.")

    # Add the error handler
    dp.add_error_handler(error_handler)

    # Start the Bot (Webhook or Polling)
    if HEROKU_APP_NAME:
        # Run on Heroku using Webhook
        logger.info(f"Starting webhook for Heroku app {HEROKU_APP_NAME}")
        # --- MODIFIED WEBHOOK PATH --- #
        WEBHOOK_PATH = "/webhook" # Use a simple, static path
        updater.start_webhook(listen="0.0.0.0",
                              port=PORT,
                              url_path=WEBHOOK_PATH,
                              webhook_url=f"https://{HEROKU_APP_NAME}.herokuapp.com{WEBHOOK_PATH}")
        logger.info(f"Webhook set to https://{HEROKU_APP_NAME}.herokuapp.com{WEBHOOK_PATH}")
        # ----------------------------- #
    else:
        # Run locally using Polling
        logger.info("Starting bot in polling mode (not on Heroku)")
        updater.start_polling()

    logger.info("Bot started and running...")
    updater.idle()

if __name__ == \'__main__\':
    main()

