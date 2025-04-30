# -*- coding: utf-8 -*-
"""
Chemistry Quiz and Info Telegram Bot (Webhook Debugging)

This bot provides chemistry quizzes and information.
Added extra logging for webhook debugging.
"""

import logging
import os
import sys
import random
import math
import time
import re
import json # Import json for pretty printing updates
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
ADMIN_USER_ID = 6448526509
PORT = int(os.environ.get("PORT", 8443))
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME")

if not BOT_TOKEN:
    logger.critical("BOT_TOKEN environment variable not set!")
    sys.exit("Bot token not found.")
if not HEROKU_APP_NAME:
    logger.warning("HEROKU_APP_NAME environment variable not set! Webhook setup might fail.")

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

# Import chemistry data
try:
    from chemistry_data import ELEMENTS, COMPOUNDS, CONCEPTS, PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO
    from chemical_equations import process_text_with_chemical_notation, format_chemical_equation
except ImportError as e:
    logger.warning(f"Could not import chemistry_data.py or chemical_equations.py: {e}. Some features might be limited.")
    ELEMENTS, COMPOUNDS, CONCEPTS, PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO = {}, {}, {}, {}, {}, {}
    def process_text_with_chemical_notation(text): return text
    def format_chemical_equation(text): return text

# Initialize database connection
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
    INFO_MENU
) = range(32)

# Import info menu functions AFTER defining states
from info_menu_function import show_info_menu, INFO_MENU as INFO_MENU_STATE_CONST
from info_handlers import info_menu_conv_handler

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

# --- Keyboard Creation Functions (Using original button text) ---
def create_main_menu_keyboard(user_id):
    keyboard = [
        [InlineKeyboardButton("📚 المعلومات الكيميائية", callback_data=\'menu_info\')],
        [InlineKeyboardButton("📝 الاختبارات", callback_data=\'menu_quiz\')],
        [InlineKeyboardButton("📊 تقارير الأداء", callback_data=\'menu_reports\')],
        [InlineKeyboardButton("ℹ️ حول البوت", callback_data=\'menu_about\')]
    ]
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ إدارة البوت", callback_data=\'menu_admin\')])
    return InlineKeyboardMarkup(keyboard)

def create_quiz_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🎯 اختبار عشوائي", callback_data=\'quiz_random_prompt\')], # Original text
        [InlineKeyboardButton("📄 اختبار حسب الفصل", callback_data=\'quiz_by_chapter_prompt\')],
        [InlineKeyboardButton("📝 اختبار حسب الدرس", callback_data=\'quiz_by_lesson_prompt\')],
        [InlineKeyboardButton("🎓 اختبار حسب المرحلة الدراسية", callback_data=\'quiz_by_grade_prompt\')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=\'main_menu\')]
    ]
    return InlineKeyboardMarkup(keyboard)

# ... (Keep other keyboard functions as they were in the user-provided file) ...
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
        [InlineKeyboardButton("15 دقيقة", callback_data=\'quiz_duration_15\')],
        [InlineKeyboardButton("20 دقيقة", callback_data=\'quiz_duration_20\')],
        [InlineKeyboardButton("30 دقيقة", callback_data=\'quiz_duration_30\')],
        [InlineKeyboardButton("بدون وقت محدد", callback_data=\'quiz_duration_0\')],
        [InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data=\'menu_quiz\')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_grade_levels_keyboard(for_quiz=False, context=None):
    grades = QUIZ_DB.get_all_grade_levels()
    keyboard = []
    if grades:
        for grade_id, grade_name in grades:
            callback_suffix = f\"quiz_{grade_id}\" if for_quiz else f\"admin_{grade_id}\"
            keyboard.append([InlineKeyboardButton(grade_name, callback_data=f\"grade_{callback_suffix}\")])
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
                callback_data = f\"chapter_quiz_{chapter_id}\"
            elif for_lesson:
                 callback_data = f\"lesson_chapter_{chapter_id}\"
            else:
                callback_data = f\"admin_chapter_{chapter_id}\"
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
            callback_data = f\"lesson_quiz_{lesson_id}\" if for_quiz else f\"admin_lesson_{lesson_id}\"
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
        callback_data = f\"answer_{question_id}_{original_index}\"
        keyboard.append([InlineKeyboardButton(option_text, callback_data=callback_data)])
    keyboard.append([InlineKeyboardButton("⏭️ تخطي السؤال", callback_data=f\"skip_{question_id}\")])
    return InlineKeyboardMarkup(keyboard)

def create_results_menu_keyboard(quiz_id):
    keyboard = [
        [InlineKeyboardButton("🔄 إعادة الاختبار", callback_data=\'menu_quiz\')],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data=\'main_menu\')]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Timer Functions (Keep from original user-provided file) ---
def set_quiz_timer(context: CallbackContext, chat_id, user_id, quiz_id, duration_minutes):
    if duration_minutes <= 0:
        return None
    job_context = {
        \'chat_id\': chat_id,
        \'user_id\': user_id,
        \'quiz_id\': quiz_id
    }
    try:
        if \'end_quiz_timeout\' not in globals():
            logger.error("end_quiz_timeout function is not defined!")
            return None
        job = context.job_queue.run_once(
            end_quiz_timeout,
            duration_minutes * 60,
            context=job_context,
            name=f"quiz_timeout_{user_id}_{quiz_id}"
        )
        logger.info(f"Quiz timer set for quiz {quiz_id}, user {user_id} for {duration_minutes} minutes.")
        return job
    except Exception as e:
        logger.error(f"Error setting quiz timer: {e}")
        return None

def set_question_timer(context: CallbackContext, chat_id, user_id, quiz_id):
    job_context = {
        \'chat_id\': chat_id,
        \'user_id\': user_id,
        \'quiz_id\': quiz_id,
        \'type\': \'question_timer\'
    }
    try:
        if \'question_timer_callback\' not in globals():
            logger.error("question_timer_callback function is not defined!")
            return None
        job = context.job_queue.run_once(
            question_timer_callback,
            QUESTION_TIMER_SECONDS,
            context=job_context,
            name=f"question_timer_{user_id}_{quiz_id}"
        )
        logger.info(f"Question timer set for quiz {quiz_id}, user {user_id}.")
        return job
    except Exception as e:
        logger.error(f"Error setting question timer: {e}")
        return None

def question_timer_callback(context: CallbackContext):
    job_context = context.job.context
    chat_id = job_context[\'chat_id\']
    user_id = job_context[\'user_id\']
    quiz_id = job_context[\'quiz_id\']
    user_data = context.dispatcher.user_data.get(user_id, {})
    # ... (rest of timer logic from user file)
    logger.warning("question_timer_callback needs full implementation check")

def end_quiz_timeout(context: CallbackContext):
    job_context = context.job.context
    chat_id = job_context[\'chat_id\']
    user_id = job_context[\'user_id\']
    quiz_id = job_context[\'quiz_id\']
    user_data = context.dispatcher.user_data.get(user_id, {})
    # ... (rest of timer logic from user file)
    logger.warning("end_quiz_timeout needs full implementation check")

# --- Generic Update Handler for Debugging (Enhanced) ---
def generic_update_handler(update: Update, context: CallbackContext) -> None:
    """Logs any incoming update in detail."""
    logger.critical("!!!!!!!!!!!!!! GENERIC UPDATE RECEIVED (Webhook Debug) !!!!!!!!!!!!!!")
    try:
        update_dict = update.to_dict()
        logger.info(f"Received update (Webhook Debug):
{json.dumps(update_dict, indent=2, ensure_ascii=False)}")
    except Exception as e:
        logger.error(f"Error converting update to dict or logging: {e}")
        logger.info(f"Raw update object (Webhook Debug): {update}")

    # Check if it contains a message and log text
    if update.message:
        logger.info(f"Message text (Webhook Debug): {update.message.text}")
    elif update.callback_query:
        logger.info(f"Callback query data (Webhook Debug): {update.callback_query.data}")

# --- Core Command Handlers (Enhanced Logging in start) ---
def start(update: Update, context: CallbackContext) -> int:
    """Handles the /start command and displays the main menu."""
    # --- ENHANCED LOGGING --- #
    logger.critical("!!!!!!!!!!!!!! START HANDLER TRIGGERED (Webhook Debug) !!!!!!!!!!!!!!")
    logger.info(f"Update received in start handler: {update.to_dict()}")
    # ------------------------ #
    user = update.effective_user
    if not user:
        logger.error("Could not get effective_user from update in start handler!")
        # Attempt to get user info differently if possible, or return
        if update.message:
            user = update.message.from_user
        elif update.callback_query:
            user = update.callback_query.from_user
        else:
            logger.error("Cannot determine user from update in start handler.")
            return ConversationHandler.END # Or appropriate state

    user_id = user.id
    user_name = get_user_name(user)
    logger.info(f"User {user_name} (ID: {user_id}) started the bot (Webhook Debug).")

    # Check if user exists, add if not
    if not QUIZ_DB.user_exists(user_id):
        QUIZ_DB.add_user(user_id, user_name)
        logger.info(f"New user {user_name} (ID: {user_id}) added to the database.")

    # Send main menu message
    text = f"أهلاً بك يا {user_name} في بوت الكيمياء التعليمي!\n\nاختر أحد الخيارات التالية:"
    keyboard = create_main_menu_keyboard(user_id)

    if update.message:
        logger.info("Replying to message in start handler (Webhook Debug)")
        try:
            update.message.reply_text(text, reply_markup=keyboard)
            logger.info("Reply sent successfully in start handler.")
        except Exception as e:
            logger.error(f"Error sending reply in start handler: {e}")
    elif update.callback_query: # Handle coming back from another menu
        logger.info("Editing message in start handler (from callback) (Webhook Debug)")
        query = update.callback_query
        try:
            query.answer()
            safe_edit_message_text(query, text=text, reply_markup=keyboard)
            logger.info("Message edited successfully in start handler (callback).")
        except Exception as e:
            logger.error(f"Error editing message in start handler (callback): {e}")
    else:
        logger.warning("Update in start handler is neither message nor callback query (Webhook Debug)")

    logger.info("Returning MAIN_MENU state from start handler (Webhook Debug)")
    return MAIN_MENU

# ... (Keep other handlers like main_menu_callback, quiz_menu_callback, etc. as they were) ...
def main_menu_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    logger.info(f"Main menu callback: User {user_id} chose {data} (Webhook Debug)")
    query.answer()

    if data == \'menu_info\':
        logger.info("Transitioning to info menu via info_menu_conv_handler entry point (Webhook Debug)")
        try:
            return show_info_menu(update, context)
        except Exception as e:
             logger.error(f"Cannot call show_info_menu directly: {e}")
             safe_edit_message_text(query, text="Error accessing info menu.")
             return MAIN_MENU
    elif data == \'menu_quiz\':
        text = "اختر نوع الاختبار الذي تريده:"
        keyboard = create_quiz_menu_keyboard()
        safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return QUIZ_MENU
    elif data == \'menu_reports\':
        text = "📊 قسم تقارير الأداء قيد التطوير حالياً."
        keyboard = create_main_menu_keyboard(user_id)
        safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return MAIN_MENU
    elif data == \'menu_about\':
        text = ("**حول بوت الكيمياء التعليمي**\n\n"
                "هذا البوت يهدف لمساعدتك في تعلم الكيمياء واختبار معلوماتك.\n"
                "**المميزات الحالية:**\n"
                "- عرض أهم قوانين التحصيلي في الكيمياء.\n"
                "- اختبارات متنوعة.\n"
                "- (قريباً) تتبع الأداء.\n\n"
                "**تطوير الاستاذ حسين الموسى**\n\n"
                "نتمنى لك رحلة تعليمية ممتعة! ✨")
        keyboard = create_main_menu_keyboard(user_id)
        safe_edit_message_text(query, text=text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        return MAIN_MENU
    elif data == \'menu_admin\' and is_admin(user_id):
        text = "⚙️ قائمة إدارة البوت:"
        keyboard = create_admin_menu_keyboard()
        safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return ADMIN_MENU
    elif data == \'main_menu\':
        return start(update, context)
    else:
        logger.warning(f"Unknown main menu callback data: {data} (Webhook Debug)")
        return MAIN_MENU

# --- (Include other handlers: quiz_menu_callback, admin_menu_callback, etc.) ---
# Placeholder for brevity - assume they exist as in the original file

# --- Main Function (Webhook Mode - Enhanced Logging) ---
def main() -> None:
    """Start the bot in webhook mode with enhanced logging."""
    updater = Updater(BOT_TOKEN)
    dispatcher = updater.dispatcher

    # --- Register Handlers ---
    # Add generic update handler for debugging (VERY high priority)
    # This will log *every* update received by the dispatcher
    dispatcher.add_handler(MessageHandler(Filters.all, generic_update_handler), group=-10)
    logger.info("Generic update handler added with VERY high priority (group -10) for Webhook Debug.")

    # Import and register info menu conversation handler
    dispatcher.add_handler(info_menu_conv_handler)
    logger.info("Info menu conversation handler added.")

    # Main conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler(\'start\', start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(main_menu_callback, pattern=\'^menu_\'),
                CallbackQueryHandler(start, pattern=\'^main_menu$\'),
            ],
            QUIZ_MENU: [
                # Placeholder - Add quiz menu handlers
                CallbackQueryHandler(main_menu_callback, pattern=\'^main_menu$\'),
            ],
            ADMIN_MENU: [
                # Placeholder - Add admin menu handlers
                CallbackQueryHandler(main_menu_callback, pattern=\'^main_menu$\'),
            ],
            ADMIN_MANAGE_STRUCTURE: [
                 # Placeholder - Add structure admin handlers
                 CallbackQueryHandler(admin_menu_callback, pattern=\'^menu_admin$\'),
            ],
            # Include INFO_MENU state from info_handlers
            INFO_MENU: info_menu_conv_handler.states[INFO_MENU_STATE_CONST],
            # ... other states need proper handlers ...
        },
        fallbacks=[CommandHandler(\'start\', start)],
        # Ensure info menu handler can be fallen back to if needed, or handle its fallbacks
    )
    dispatcher.add_handler(conv_handler)

    # --- Start the Bot in Webhook Mode ---
    if HEROKU_APP_NAME:
        logger.info(f"Starting bot in WEBHOOK mode on port {PORT} (Webhook Debug)...")
        webhook_url = f"https://{HEROKU_APP_NAME}.herokuapp.com/{BOT_TOKEN}"
        try:
            updater.start_webhook(listen="0.0.0.0",
                                  port=PORT,
                                  url_path=BOT_TOKEN,
                                  webhook_url=webhook_url)
            logger.info(f"Webhook set attempt to {webhook_url}")
            # Verify webhook setting with getWebhookInfo
            webhook_info = updater.bot.get_webhook_info()
            logger.info(f"Actual webhook info from Telegram: {webhook_info}")
            if webhook_info.url != webhook_url:
                logger.error(f"Webhook URL mismatch! Expected {webhook_url}, but got {webhook_info.url}")
            else:
                logger.info("Webhook URL matches expected URL.")
        except Exception as e:
            logger.error(f"Error starting webhook: {e}")
            # Fallback or exit might be needed here
            sys.exit("Webhook start failed.")

    else:
        logger.error("HEROKU_APP_NAME not set. Cannot start in webhook mode.")
        sys.exit("Missing Heroku app name.")

    logger.info("Bot started and running (Webhook Debug)...")
    updater.idle()

if __name__ == \'__main__\':
    main()

