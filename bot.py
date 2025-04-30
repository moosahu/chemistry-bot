print("!!! BOT SCRIPT STARTED (DEBUG PRINT 1) !!!")
import sys
print(f"!!! PYTHON VERSION: {sys.version} (DEBUG PRINT 2) !!!")

# -*- coding: utf-8 -*-
"""
Chemistry Quiz and Info Telegram Bot

This bot provides chemistry quizzes and information.
"""

print("!!! STARTING IMPORTS (DEBUG PRINT 3) !!!")
import logging
import os
# import sys # Already imported above
import random
import math
import time # Added from original
import re # Added from original
from io import BytesIO # Added from original
from datetime import datetime, timedelta

# Third-party libraries
# Keep current working imports for telegram library (seems newer than v12.8)
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
    InputMediaPhoto # Added from original, might be needed for image handling
)
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    CallbackQueryHandler,
    ConversationHandler,
    JobQueue # Added from original for timers
)
from telegram.error import BadRequest, TelegramError, NetworkError, Unauthorized, TimedOut, ChatMigrated # Added error types from original

print("!!! CORE IMPORTS DONE (DEBUG PRINT 4) !!!")

# --- Configuration & Constants ---

print("!!! CONFIGURING LOGGING (DEBUG PRINT 5) !!!")
# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout) # Use stdout handler like original for Heroku
    ]
)
logger = logging.getLogger(__name__)

print("!!! GETTING ENV VARS (DEBUG PRINT 6) !!!")
# Get sensitive info from environment variables
# Use BOT_TOKEN as confirmed working, not TOKEN from original
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
# Use single hardcoded ADMIN_USER_ID as requested and present in original
ADMIN_USER_ID = 6448526509
PORT = int(os.environ.get("PORT", 8443))
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME")

print(f"!!! BOT_TOKEN IS SET: {bool(BOT_TOKEN)} (DEBUG PRINT 7) !!!")
if not BOT_TOKEN:
    logger.critical("BOT_TOKEN environment variable not set!")
    sys.exit("Bot token not found.")

# Quiz settings from original
DEFAULT_QUIZ_QUESTIONS = 10
DEFAULT_QUIZ_DURATION_MINUTES = 10 # Default duration in minutes
QUESTION_TIMER_SECONDS = 240  # 4 minutes per question (from original)
FEEDBACK_DELAY = 2 # seconds before showing correct answer (keep from current)

print("!!! IMPORTING DB UTILS (DEBUG PRINT 8) !!!")
# --- Database Setup ---
try:
    from db_utils import connect_db, setup_database
    from quiz_db import QuizDatabase
    # استيراد الدالة المساعدة لمعالجة الأخطاء بأمان
    from helper_function import safe_edit_message_text
except ImportError as e:
    logger.error(f"Failed to import database modules: {e}. Make sure db_utils.py, quiz_db.py, helper_function.py are present.")
    sys.exit("Critical import error, stopping bot.")

print("!!! IMPORTING CHEMISTRY DATA (DEBUG PRINT 9) !!!")
# استيراد البيانات الثابتة ووظائف المعادلات (Merge imports from original and current)
try:
    # From original
    from chemistry_data import ELEMENTS, COMPOUNDS, CONCEPTS, PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO
    from chemical_equations import process_text_with_chemical_notation, format_chemical_equation
    # From current (if different/needed)
    # from chemistry_equations import get_equation_details, ALL_EQUATIONS # This seems different, stick to original for now
except ImportError as e:
    logger.warning(f"Could not import chemistry_data.py or chemical_equations.py: {e}. Some features might be limited.")
    # Define fallbacks if imports fail
    ELEMENTS, COMPOUNDS, CONCEPTS, PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO = {}, {}, {}, {}, {}, {}
    def process_text_with_chemical_notation(text): return text # Dummy function
    def format_chemical_equation(text): return text # Dummy function

print("!!! INITIALIZING DB CONNECTION (DEBUG PRINT 10) !!!")
# Initialize database connection and QuizDatabase instance
# Keep current working method
if not DATABASE_URL:
    logger.error("DATABASE_URL environment variable not set or empty. Bot cannot connect to DB.")
    sys.exit("Database configuration error.")

DB_CONN = connect_db(DATABASE_URL)
if DB_CONN:
    setup_database(DB_CONN)
    # Use the class initialization from the original file if it worked there
    # QUIZ_DB = QuizDatabase() # Original way
    # Stick to current working way which uses the connection
    QUIZ_DB = QuizDatabase(DB_CONN)
    logger.info("QuizDatabase initialized successfully.")
else:
    logger.error("Failed to establish database connection. Bot cannot function properly.")
    sys.exit("Database connection failed.")

print("!!! DEFINING STATES (DEBUG PRINT 11) !!!")
# --- States for Conversation Handler ---
# Use states from original file, add INFO_MENU if needed
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
    INFO_MENU # Add INFO_MENU state from current version
) = range(32) # Adjusted range to 32 states

print("!!! IMPORTING INFO MENU (DEBUG PRINT 12) !!!")
# Import info menu functions AFTER defining states
from info_menu_function import show_info_menu, INFO_MENU as INFO_MENU_STATE_CONST # Import constant if needed
from info_handlers import info_menu_conv_handler # Import the handler

print("!!! DEFINING HELPER FUNCTIONS (DEBUG PRINT 13) !!!")
# --- Helper Functions ---

def is_admin(user_id):
    """Check if a user is an admin (using single ADMIN_USER_ID)."""
    return str(user_id) == str(ADMIN_USER_ID)

def get_user_name(user):
    """Get user's full name or username."""
    if user.first_name and user.last_name:
        return f"{user.first_name} {user.last_name}"
    elif user.first_name:
        return user.first_name
    elif user.username:
        return user.username
    else:
        return str(user.id)

print("!!! DEFINING KEYBOARD FUNCTIONS (DEBUG PRINT 14) !!!")
# --- Keyboard Creation Functions (Merge original and current, use original callback data format) ---

def create_main_menu_keyboard(user_id):
    """Creates the main menu inline keyboard (original structure)."""
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
    """Creates the quiz type selection inline keyboard (original structure)."""
    keyboard = [
        [InlineKeyboardButton("🎯 اختبار عشوائي", callback_data=\'quiz_random_prompt\')],
        [InlineKeyboardButton("📄 اختبار حسب الفصل", callback_data=\'quiz_by_chapter_prompt\')],
        [InlineKeyboardButton("📝 اختبار حسب الدرس", callback_data=\'quiz_by_lesson_prompt\')],
        [InlineKeyboardButton("🎓 اختبار حسب المرحلة الدراسية", callback_data=\'quiz_by_grade_prompt\')],
        # [InlineKeyboardButton("🔄 مراجعة الأخطاء", callback_data=\'quiz_review_prompt\')], # Keep commented out
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=\'main_menu\')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_admin_menu_keyboard():
    """Creates the admin menu inline keyboard (original structure)."""
    keyboard = [
        [InlineKeyboardButton("➕ إضافة سؤال", callback_data=\'admin_add_question\')],
        [InlineKeyboardButton("🗑️ حذف سؤال", callback_data=\'admin_delete_question\')],
        [InlineKeyboardButton("🔍 عرض سؤال", callback_data=\'admin_show_question\')],
        [InlineKeyboardButton("🏫 إدارة المراحل/الفصول/الدروس", callback_data=\'admin_manage_structure\')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=\'main_menu\')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_structure_admin_menu_keyboard():
    """Creates the structure management admin menu (original structure)."""
    keyboard = [
        [InlineKeyboardButton("🏫 إدارة المراحل الدراسية", callback_data=\'admin_manage_grades\')],
        [InlineKeyboardButton("📚 إدارة الفصول", callback_data=\'admin_manage_chapters\')],
        [InlineKeyboardButton("📝 إدارة الدروس", callback_data=\'admin_manage_lessons\')],
        [InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data=\'menu_admin\')] # Corrected callback for back button
    ]
    return InlineKeyboardMarkup(keyboard)

def create_quiz_duration_keyboard():
    """Creates the quiz duration selection inline keyboard (original options)."""
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

# --- Keep other keyboard functions from current version if they are more complete ---
# Review create_grade_levels_keyboard, create_chapters_keyboard, create_lessons_keyboard
# create_quiz_question_keyboard, create_results_menu_keyboard from current version
# and adapt their callback data format if needed.

def create_grade_levels_keyboard(for_quiz=False, context=None):
    """Creates keyboard for selecting grade levels (adapted from current)."""
    grades = QUIZ_DB.get_all_grade_levels()
    keyboard = []
    if grades:
        for grade_id, grade_name in grades:
            # Use original callback format style
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
    """Creates keyboard for selecting chapters (adapted from current)."""
    chapters = QUIZ_DB.get_chapters_by_grade(grade_level_id)
    keyboard = []
    if chapters:
        for chapter_id, chapter_name in chapters:
            if for_quiz:
                callback_data = f\'chapter_quiz_{chapter_id}\'
            elif for_lesson:
                 callback_data = f\'lesson_chapter_{chapter_id}\'
            else: # Admin context
                callback_data = f\'admin_chapter_{chapter_id}\'
            keyboard.append([InlineKeyboardButton(chapter_name, callback_data=callback_data)])
    else:
        logger.info(f"No chapters found for grade level {grade_level_id}.")
        return None

    if for_quiz or for_lesson:
        # Original logic seemed complex, stick to current simpler logic for back button
        back_callback = \'quiz_by_grade_prompt\'
    else: # Admin context
        back_callback = \'admin_manage_structure\'
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_lessons_keyboard(chapter_id, for_quiz=False, context=None):
    """Creates keyboard for selecting lessons (adapted from current)."""
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
        # Stick to current simpler back logic
        back_callback = \'quiz_by_lesson_prompt\'
    else: # Admin context
        back_callback = \'admin_manage_structure\'
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_quiz_question_keyboard(options, question_id):
    """Creates the keyboard for a multiple-choice quiz question (adapted from current)."""
    keyboard = []
    shuffled_options = list(enumerate(options))
    random.shuffle(shuffled_options)

    for original_index, option_text in shuffled_options:
        callback_data = f\'answer_{question_id}_{original_index}\' # Use original format
        keyboard.append([InlineKeyboardButton(option_text, callback_data=callback_data)])

    keyboard.append([InlineKeyboardButton("⏭️ تخطي السؤال", callback_data=f\'skip_{question_id}\')])
    return InlineKeyboardMarkup(keyboard)

def create_results_menu_keyboard(quiz_id):
    """Creates keyboard for quiz results view (adapted from current)."""
    keyboard = [
        # [InlineKeyboardButton("🧐 مراجعة الأخطاء", callback_data=f\'review_{quiz_id}\')],
        [InlineKeyboardButton("🔄 إعادة الاختبار", callback_data=\'menu_quiz\')],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data=\'main_menu\')]
    ]
    return InlineKeyboardMarkup(keyboard)

print("!!! DEFINING TIMER FUNCTIONS (DEBUG PRINT 15) !!!")
# --- Timer Functions (from original) ---

def set_quiz_timer(context: CallbackContext, chat_id, user_id, quiz_id, duration_minutes):
    """Sets a timer to end the quiz after the specified duration."""
    if duration_minutes <= 0:
        return None

    job_context = {
        \'chat_id\': chat_id,
        \'user_id\': user_id,
        \'quiz_id\': quiz_id
    }
    try:
        # Ensure end_quiz_timeout function exists or is defined
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
    """Sets a timer to automatically move to the next question."""
    job_context = {
        \'chat_id\': chat_id,
        \'user_id\': user_id,
        \'quiz_id\': quiz_id,
        \'type\': \'question_timer\'
    }
    try:
        # Ensure question_timer_callback function exists or is defined
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
    """Callback function for the question timer."""
    job_context = context.job.context
    chat_id = job_context[\'chat_id\']
    user_id = job_context[\'user_id\']
    quiz_id = job_context[\'quiz_id\']

    # Use context.dispatcher.user_data as in original
    user_data = context.dispatcher.user_data.get(user_id, {})
    # Check if quiz is still active and matches the timer
    if user_data.get(\'current_quiz_id\') == quiz_id and user_data.get(\'quiz_active\'):
        logger.info(f"Question timer expired for quiz {quiz_id}, user {user_id}. Moving to next question.")
        # Need to call the function that handles moving to the next question
        # Assuming send_next_question is the correct function name
        # Ensure send_next_question exists or is defined
        if \'send_next_question\' not in globals():
            logger.error("send_next_question function is not defined for question timer callback!")
            return
        send_next_question(context, chat_id, user_id, quiz_id, user_data)
    else:
        logger.info(f"Question timer expired for quiz {quiz_id}, user {user_id}, but quiz is no longer active or mismatch.")

def end_quiz_timeout(context: CallbackContext):
    """Callback function when the overall quiz timer expires."""
    job_context = context.job.context
    chat_id = job_context[\'chat_id\']
    user_id = job_context[\'user_id\']
    quiz_id = job_context[\'quiz_id\']

    user_data = context.dispatcher.user_data.get(user_id, {})
    if user_data.get(\'current_quiz_id\') == quiz_id and user_data.get(\'quiz_active\'):
        logger.info(f"Quiz timeout for quiz {quiz_id}, user {user_id}.")
        context.bot.send_message(chat_id, "⏰ انتهى وقت الاختبار!")
        # Need to call the function that ends the quiz and shows results
        # Assuming end_quiz is the correct function name
        # Ensure end_quiz exists or is defined
        if \'end_quiz\' not in globals():
            logger.error("end_quiz function is not defined for quiz timeout callback!")
            return
        end_quiz(context, chat_id, user_id, quiz_id, user_data)
    else:
        logger.info(f"Quiz timeout expired for quiz {quiz_id}, user {user_id}, but quiz is no longer active or mismatch.")

print("!!! DEFINING CORE HANDLERS (DEBUG PRINT 16) !!!")
# --- Core Handlers ---

def start(update: Update, context: CallbackContext):
    """Sends the main menu when the /start command is issued."""
    print("!!! START HANDLER TRIGGERED (DEBUG PRINT 17) !!!")
    user = update.effective_user
    user_id = user.id
    user_name = get_user_name(user)
    logger.info(f"User {user_name} (ID: {user_id}) started the bot.")

    # Store user info if not already present (from original)
    QUIZ_DB.add_user_if_not_exists(user_id, user_name, user.username)

    # Reset any previous state (important for clean start)
    context.user_data.clear()

    keyboard = create_main_menu_keyboard(user_id)
    update.message.reply_text(
        f"أهلاً بك يا {user_name} في بوت الكيمياء التعليمي! 👋\n\n" # Use original welcome message
        "اختر أحد الخيارات من القائمة أدناه:",
        reply_markup=keyboard
    )
    return MAIN_MENU

def main_menu_callback(update: Update, context: CallbackContext):
    """Handles returning to the main menu via callback."""
    print("!!! MAIN MENU CALLBACK TRIGGERED (DEBUG PRINT 18) !!!")
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    keyboard = create_main_menu_keyboard(user_id)
    safe_edit_message_text(
        context=context,
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        text="🏠 القائمة الرئيسية:\nاختر أحد الخيارات:",
        reply_markup=keyboard
    )
    return MAIN_MENU

def about_bot(update: Update, context: CallbackContext):
    """Handles the 'About Bot' callback."""
    print("!!! ABOUT BOT CALLBACK TRIGGERED (DEBUG PRINT 19) !!!")
    query = update.callback_query
    query.answer()
    about_text = (
        "🤖 **بوت الكيمياء التعليمي** 🧪\n\n"
        "تم تصميم هذا البوت لمساعدتك في تعلم الكيمياء من خلال:
"
        "- اختبارات متنوعة (عشوائية، حسب الفصل، الدرس، أو المرحلة).
"
        "- معلومات كيميائية مفيدة (قيد التطوير).
"
        "- تتبع أدائك في الاختبارات (قيد التطوير).
\n"
        "تم تطويره بواسطة [اسم المطور أو الجهة]. نتمنى لك رحلة تعليمية ممتعة!"
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=\'main_menu\')]])
    safe_edit_message_text(
        context=context,
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        text=about_text,
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN
    )
    return MAIN_MENU

def reports_menu(update: Update, context: CallbackContext):
    """Handles the 'Performance Reports' callback (Placeholder)."""
    print("!!! REPORTS MENU CALLBACK TRIGGERED (DEBUG PRINT 20) !!!")
    query = update.callback_query
    query.answer()
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=\'main_menu\')]])
    safe_edit_message_text(
        context=context,
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        text="📊 تقارير الأداء (قيد التطوير).",
        reply_markup=keyboard
    )
    return MAIN_MENU

# --- Include Quiz Handlers (Adapted from both versions) ---
# Need functions like: quiz_menu, select_quiz_type, select_chapter, select_lesson, select_grade,
# select_duration, start_quiz, handle_answer, skip_question, end_quiz, show_results etc.
# Make sure they use the correct states and callback data format.

# Placeholder for quiz_menu function
def quiz_menu(update: Update, context: CallbackContext):
    print("!!! QUIZ MENU CALLBACK TRIGGERED (DEBUG PRINT 21) !!!")
    query = update.callback_query
    query.answer()
    keyboard = create_quiz_menu_keyboard()
    safe_edit_message_text(
        context=context,
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        text="📝 قائمة الاختبارات:\nاختر نوع الاختبار الذي تريده:",
        reply_markup=keyboard
    )
    return QUIZ_MENU

# Placeholder for quiz type selection prompts
def quiz_random_prompt(update: Update, context: CallbackContext):
    print("!!! QUIZ RANDOM PROMPT (DEBUG PRINT 22) !!!")
    query = update.callback_query
    query.answer()
    context.user_data[\'quiz_type\'] = \'random\'
    keyboard = create_quiz_duration_keyboard()
    safe_edit_message_text(
        context=context,
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        text="⏱️ اختر مدة الاختبار العشوائي:",
        reply_markup=keyboard
    )
    return SELECTING_QUIZ_DURATION

def quiz_by_chapter_prompt(update: Update, context: CallbackContext):
    print("!!! QUIZ BY CHAPTER PROMPT (DEBUG PRINT 23) !!!")
    query = update.callback_query
    query.answer()
    context.user_data[\'quiz_type\'] = \'chapter\'
    # First, ask for grade level
    keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
    if keyboard:
        safe_edit_message_text(
            context=context,
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            text="🎓 يرجى اختيار المرحلة الدراسية أولاً:",
            reply_markup=keyboard
        )
        return SELECT_GRADE_LEVEL_FOR_QUIZ
    else:
        safe_edit_message_text(context=context, chat_id=query.message.chat_id, message_id=query.message.message_id, text="لم يتم العثور على مراحل دراسية. يرجى إضافتها أولاً.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

def quiz_by_lesson_prompt(update: Update, context: CallbackContext):
    print("!!! QUIZ BY LESSON PROMPT (DEBUG PRINT 24) !!!")
    query = update.callback_query
    query.answer()
    context.user_data[\'quiz_type\'] = \'lesson\'
    # First, ask for grade level
    keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
    if keyboard:
        safe_edit_message_text(
            context=context,
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            text="🎓 يرجى اختيار المرحلة الدراسية أولاً:",
            reply_markup=keyboard
        )
        return SELECT_GRADE_LEVEL_FOR_QUIZ # Reuse state for grade selection
    else:
        safe_edit_message_text(context=context, chat_id=query.message.chat_id, message_id=query.message.message_id, text="لم يتم العثور على مراحل دراسية. يرجى إضافتها أولاً.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

def quiz_by_grade_prompt(update: Update, context: CallbackContext):
    print("!!! QUIZ BY GRADE PROMPT (DEBUG PRINT 25) !!!")
    query = update.callback_query
    query.answer()
    context.user_data[\'quiz_type\'] = \'grade\'
    keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
    if keyboard:
        safe_edit_message_text(
            context=context,
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            text="🎓 يرجى اختيار المرحلة الدراسية للاختبار:",
            reply_markup=keyboard
        )
        return SELECT_GRADE_LEVEL_FOR_QUIZ
    else:
        safe_edit_message_text(context=context, chat_id=query.message.chat_id, message_id=query.message.message_id, text="لم يتم العثور على مراحل دراسية. يرجى إضافتها أولاً.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

# Handler for selecting grade level for quiz
def select_grade_for_quiz(update: Update, context: CallbackContext):
    print("!!! SELECT GRADE FOR QUIZ (DEBUG PRINT 26) !!!")
    query = update.callback_query
    query.answer()
    callback_data = query.data

    if callback_data == \'grade_quiz_all\':
        grade_level_id = \'all\'
        context.user_data[\'grade_level_id\'] = grade_level_id
        context.user_data[\'grade_level_name\'] = "اختبار تحصيلي عام"
        logger.info(f"User {query.from_user.id} selected general assessment quiz.")
        # Proceed directly to duration selection for general assessment
        keyboard = create_quiz_duration_keyboard()
        safe_edit_message_text(
            context=context,
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            text=f"⏱️ اختر مدة الاختبار التحصيلي العام:",
            reply_markup=keyboard
        )
        return SELECTING_QUIZ_DURATION

    try:
        grade_level_id = int(callback_data.split(\'_\')[-1])
        context.user_data[\'grade_level_id\'] = grade_level_id
        # Fetch grade name for context
        grade_info = QUIZ_DB.get_grade_level_by_id(grade_level_id)
        grade_name = grade_info[1] if grade_info else f"المرحلة {grade_level_id}"
        context.user_data[\'grade_level_name\'] = grade_name
        logger.info(f"User {query.from_user.id} selected grade level {grade_level_id} ({grade_name}) for quiz type {context.user_data.get(\'quiz_type\')}.")

        quiz_type = context.user_data.get(\'quiz_type\')
        if quiz_type == \'chapter\':
            keyboard = create_chapters_keyboard(grade_level_id, for_quiz=True, context=context)
            if keyboard:
                safe_edit_message_text(
                    context=context,
                    chat_id=query.message.chat_id,
                    message_id=query.message.message_id,
                    text=f"📚 اختر الفصل للمرحلة \'{grade_name}\':",
                    reply_markup=keyboard
                )
                return SELECT_CHAPTER_FOR_QUIZ
            else:
                safe_edit_message_text(context=context, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"لم يتم العثور على فصول للمرحلة \'{grade_name}\'.", reply_markup=create_quiz_menu_keyboard())
                return QUIZ_MENU
        elif quiz_type == \'lesson\':
            # Need to select chapter first for lesson quiz
            keyboard = create_chapters_keyboard(grade_level_id, for_lesson=True, context=context)
            if keyboard:
                safe_edit_message_text(
                    context=context,
                    chat_id=query.message.chat_id,
                    message_id=query.message.message_id,
                    text=f"📚 اختر الفصل أولاً للمرحلة \'{grade_name}\':",
                    reply_markup=keyboard
                )
                return SELECT_CHAPTER_FOR_LESSON # State to select chapter before lesson
            else:
                safe_edit_message_text(context=context, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"لم يتم العثور على فصول للمرحلة \'{grade_name}\'.", reply_markup=create_quiz_menu_keyboard())
                return QUIZ_MENU
        elif quiz_type == \'grade\':
            # Grade level selected, proceed to duration
            keyboard = create_quiz_duration_keyboard()
            safe_edit_message_text(
                context=context,
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text=f"⏱️ اختر مدة الاختبار للمرحلة \'{grade_name}\':",
                reply_markup=keyboard
            )
            return SELECTING_QUIZ_DURATION
        else:
            logger.warning(f"Unexpected quiz type \'{quiz_type}\' after selecting grade.")
            safe_edit_message_text(context=context, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ غير متوقع.", reply_markup=create_main_menu_keyboard(query.from_user.id))
            return MAIN_MENU

    except (IndexError, ValueError):
        logger.error(f"Invalid callback data received for grade selection: {callback_data}")
        safe_edit_message_text(context=context, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

# Handler for selecting chapter (either for chapter quiz or before lesson quiz)
def select_chapter_for_quiz_or_lesson(update: Update, context: CallbackContext):
    print("!!! SELECT CHAPTER FOR QUIZ/LESSON (DEBUG PRINT 27) !!!")
    query = update.callback_query
    query.answer()
    callback_data = query.data
    quiz_type = context.user_data.get(\'quiz_type\')

    try:
        # Determine if it's for lesson selection or chapter quiz
        if callback_data.startswith(\'lesson_chapter_\'):
            chapter_id = int(callback_data.split(\'_\')[-1])
            context.user_data[\'chapter_id\'] = chapter_id
            chapter_info = QUIZ_DB.get_chapter_by_id(chapter_id)
            chapter_name = chapter_info[1] if chapter_info else f"الفصل {chapter_id}"
            context.user_data[\'chapter_name\'] = chapter_name
            logger.info(f"User {query.from_user.id} selected chapter {chapter_id} ({chapter_name}) to select lesson.")

            keyboard = create_lessons_keyboard(chapter_id, for_quiz=True, context=context)
            if keyboard:
                safe_edit_message_text(
                    context=context,
                    chat_id=query.message.chat_id,
                    message_id=query.message.message_id,
                    text=f"📝 اختر الدرس من فصل \'{chapter_name}\':",
                    reply_markup=keyboard
                )
                return SELECT_LESSON_FOR_QUIZ
            else:
                safe_edit_message_text(context=context, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"لم يتم العثور على دروس للفصل \'{chapter_name}\'.", reply_markup=create_quiz_menu_keyboard())
                return QUIZ_MENU

        elif callback_data.startswith(\'chapter_quiz_\'):
            chapter_id = int(callback_data.split(\'_\')[-1])
            context.user_data[\'chapter_id\'] = chapter_id
            chapter_info = QUIZ_DB.get_chapter_by_id(chapter_id)
            chapter_name = chapter_info[1] if chapter_info else f"الفصل {chapter_id}"
            context.user_data[\'chapter_name\'] = chapter_name
            logger.info(f"User {query.from_user.id} selected chapter {chapter_id} ({chapter_name}) for quiz.")

            # Proceed to duration selection
            keyboard = create_quiz_duration_keyboard()
            safe_edit_message_text(
                context=context,
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text=f"⏱️ اختر مدة الاختبار لفصل \'{chapter_name}\':",
                reply_markup=keyboard
            )
            return SELECTING_QUIZ_DURATION
        else:
            raise ValueError("Invalid callback prefix")

    except (IndexError, ValueError):
        logger.error(f"Invalid callback data received for chapter selection: {callback_data}")
        safe_edit_message_text(context=context, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

# Handler for selecting lesson for quiz
def select_lesson_for_quiz(update: Update, context: CallbackContext):
    print("!!! SELECT LESSON FOR QUIZ (DEBUG PRINT 28) !!!")
    query = update.callback_query
    query.answer()
    callback_data = query.data

    try:
        lesson_id = int(callback_data.split(\'_\')[-1])
        context.user_data[\'lesson_id\'] = lesson_id
        lesson_info = QUIZ_DB.get_lesson_by_id(lesson_id)
        lesson_name = lesson_info[1] if lesson_info else f"الدرس {lesson_id}"
        context.user_data[\'lesson_name\'] = lesson_name
        logger.info(f"User {query.from_user.id} selected lesson {lesson_id} ({lesson_name}) for quiz.")

        # Proceed to duration selection
        keyboard = create_quiz_duration_keyboard()
        safe_edit_message_text(
            context=context,
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            text=f"⏱️ اختر مدة الاختبار لدرس \'{lesson_name}\':",
            reply_markup=keyboard
        )
        return SELECTING_QUIZ_DURATION

    except (IndexError, ValueError):
        logger.error(f"Invalid callback data received for lesson selection: {callback_data}")
        safe_edit_message_text(context=context, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

# Handler for selecting quiz duration
def select_quiz_duration(update: Update, context: CallbackContext):
    print("!!! SELECT QUIZ DURATION (DEBUG PRINT 29) !!!")
    query = update.callback_query
    query.answer()
    callback_data = query.data

    try:
        duration_minutes = int(callback_data.split(\'_\')[-1])
        context.user_data[\'quiz_duration_minutes\'] = duration_minutes
        logger.info(f"User {query.from_user.id} selected duration: {duration_minutes} minutes.")

        # Now start the quiz
        # Ensure start_quiz function exists
        if \'start_quiz\' not in globals():
            logger.error("start_quiz function is not defined!")
            safe_edit_message_text(context=context, chat_id=query.message.chat_id, message_id=query.message.message_id, text="خطأ: لا يمكن بدء الاختبار.", reply_markup=create_main_menu_keyboard(query.from_user.id))
            return MAIN_MENU

        return start_quiz(update, context)

    except (IndexError, ValueError):
        logger.error(f"Invalid callback data received for duration selection: {callback_data}")
        safe_edit_message_text(context=context, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

# --- Quiz Taking Logic (Adapted from both versions) ---

def start_quiz(update: Update, context: CallbackContext):
    """Starts the selected quiz type."""
    print("!!! START QUIZ FUNCTION (DEBUG PRINT 30) !!!")
    query = update.callback_query # Might be None if called directly after duration
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    user_data = context.user_data

    quiz_type = user_data.get(\'quiz_type\')
    duration_minutes = user_data.get(\'quiz_duration_minutes\', DEFAULT_QUIZ_DURATION_MINUTES)
    num_questions = DEFAULT_QUIZ_QUESTIONS # Use default for now

    questions = []
    quiz_title = "اختبار"

    try:
        if quiz_type == \'random\':
            questions = QUIZ_DB.get_random_questions(num_questions)
            quiz_title = "اختبار عشوائي"
        elif quiz_type == \'chapter\':
            chapter_id = user_data.get(\'chapter_id\')
            chapter_name = user_data.get(\'chapter_name\', f"الفصل {chapter_id}")
            if chapter_id:
                questions = QUIZ_DB.get_questions_by_chapter(chapter_id, num_questions)
                quiz_title = f"اختبار فصل \'{chapter_name}\'"
            else:
                raise ValueError("Chapter ID not found for chapter quiz.")
        elif quiz_type == \'lesson\':
            lesson_id = user_data.get(\'lesson_id\')
            lesson_name = user_data.get(\'lesson_name\', f"الدرس {lesson_id}")
            if lesson_id:
                questions = QUIZ_DB.get_questions_by_lesson(lesson_id, num_questions)
                quiz_title = f"اختبار درس \'{lesson_name}\'"
            else:
                raise ValueError("Lesson ID not found for lesson quiz.")
        elif quiz_type == \'grade\':
            grade_level_id = user_data.get(\'grade_level_id\')
            grade_name = user_data.get(\'grade_level_name\', f"المرحلة {grade_level_id}")
            if grade_level_id == \'all\':
                 questions = QUIZ_DB.get_random_questions(num_questions) # Use random for general assessment
                 quiz_title = "اختبار تحصيلي عام"
            elif grade_level_id:
                questions = QUIZ_DB.get_questions_by_grade(grade_level_id, num_questions)
                quiz_title = f"اختبار مرحلة \'{grade_name}\'"
            else:
                raise ValueError("Grade Level ID not found for grade quiz.")
        else:
            raise ValueError(f"Unknown quiz type: {quiz_type}")

        if not questions:
            logger.warning(f"No questions found for the selected criteria: {user_data}")
            message_text = "عذراً، لم يتم العثور على أسئلة تطابق اختيارك. يرجى المحاولة مرة أخرى أو إضافة المزيد من الأسئلة."
            reply_markup = create_quiz_menu_keyboard()
            if query:
                safe_edit_message_text(context, chat_id, query.message.message_id, message_text, reply_markup)
            else:
                context.bot.send_message(chat_id, message_text, reply_markup=reply_markup)
            return QUIZ_MENU

        # Create a new quiz session
        quiz_id = QUIZ_DB.create_quiz_session(user_id, quiz_title, duration_minutes)
        if not quiz_id:
            raise RuntimeError("Failed to create quiz session in database.")

        user_data[\'current_quiz_id\'] = quiz_id
        user_data[\'questions\'] = questions
        user_data[\'current_question_index\'] = 0
        user_data[\'score\'] = 0
        user_data[\'quiz_active\'] = True
        user_data[\'quiz_start_time\'] = time.time()
        user_data[\'answered_questions\'] = [] # To store {q_id: correct/incorrect/skipped}

        logger.info(f"Starting {quiz_title} (ID: {quiz_id}) for user {user_id} with {len(questions)} questions and duration {duration_minutes} mins.")

        # Set the overall quiz timer if duration is specified
        set_quiz_timer(context, chat_id, user_id, quiz_id, duration_minutes)

        # Send the first question
        # Ensure send_next_question exists
        if \'send_next_question\' not in globals():
             logger.error("send_next_question function is not defined!")
             safe_edit_message_text(context, chat_id, query.message.message_id, "خطأ: لا يمكن بدء الاختبار.", reply_markup=create_main_menu_keyboard(user_id))
             return MAIN_MENU

        send_next_question(context, chat_id, user_id, quiz_id, user_data, message_id=query.message.message_id if query else None)
        return TAKING_QUIZ

    except Exception as e:
        logger.error(f"Error starting quiz for user {user_id}: {e}", exc_info=True)
        message_text = f"حدث خطأ أثناء بدء الاختبار: {e}. يرجى المحاولة مرة أخرى."
        reply_markup = create_quiz_menu_keyboard()
        if query:
            safe_edit_message_text(context, chat_id, query.message.message_id, message_text, reply_markup)
        else:
            context.bot.send_message(chat_id, message_text, reply_markup=reply_markup)
        return QUIZ_MENU

def send_next_question(context: CallbackContext, chat_id, user_id, quiz_id, user_data, message_id=None):
    """Sends the next question in the quiz."""
    print("!!! SEND NEXT QUESTION (DEBUG PRINT 31) !!!")
    current_index = user_data.get(\'current_question_index\', 0)
    questions = user_data.get(\'questions\', [])

    if current_index >= len(questions):
        # Quiz finished
        # Ensure end_quiz exists
        if \'end_quiz\' not in globals():
             logger.error("end_quiz function is not defined!")
             return TAKING_QUIZ # Stay in state, maybe show error?
        return end_quiz(context, chat_id, user_id, quiz_id, user_data, message_id)

    question_data = questions[current_index]
    question_id = question_data[0]
    question_text = question_data[1]
    options = question_data[2:6] # Assuming options are in columns 3-6
    # image_url = question_data[8] # Assuming image URL is column 9 (index 8)

    # Remove None options and shuffle
    valid_options = [opt for opt in options if opt is not None]
    if not valid_options:
        logger.error(f"Question ID {question_id} has no valid options!")
        # Skip this question automatically
        user_data[\'current_question_index\'] = current_index + 1
        user_data[\'answered_questions\'].append({\'question_id\': question_id, \'status\': \'error_skipped\', \'selected\': None, \'correct\': None})
        return send_next_question(context, chat_id, user_id, quiz_id, user_data, message_id)

    keyboard = create_quiz_question_keyboard(valid_options, question_id)

    # Format question text
    formatted_question = process_text_with_chemical_notation(question_text)
    question_number = current_index + 1
    total_questions = len(questions)
    message_text = f"**السؤال {question_number}/{total_questions}:**\n\n{formatted_question}"

    # Set question timer
    set_question_timer(context, chat_id, user_id, quiz_id)

    # Send or edit message
    try:
        # TODO: Add image handling if image_url exists
        if message_id:
            safe_edit_message_text(context, chat_id, message_id, message_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        else:
            context.bot.send_message(chat_id, message_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    except BadRequest as e:
        logger.error(f"BadRequest sending question {question_id}: {e}")
        # Try sending without Markdown if it fails
        try:
            if message_id:
                safe_edit_message_text(context, chat_id, message_id, f"السؤال {question_number}/{total_questions}:\n\n{question_text}", reply_markup=keyboard)
            else:
                context.bot.send_message(chat_id, f"السؤال {question_number}/{total_questions}:\n\n{question_text}", reply_markup=keyboard)
        except Exception as inner_e:
            logger.error(f"Failed to send question {question_id} even without Markdown: {inner_e}")
            # Skip question if sending fails completely
            user_data[\'current_question_index\'] = current_index + 1
            user_data[\'answered_questions\'].append({\'question_id\': question_id, \'status\': \'error_skipped\', \'selected\': None, \'correct\': None})
            context.bot.send_message(chat_id, "حدث خطأ في عرض هذا السؤال، سيتم تخطيه.")
            return send_next_question(context, chat_id, user_id, quiz_id, user_data)
    except Exception as e:
        logger.error(f"Error sending question {question_id}: {e}", exc_info=True)
        # Skip question on other errors too
        user_data[\'current_question_index\'] = current_index + 1
        user_data[\'answered_questions\'].append({\'question_id\': question_id, \'status\': \'error_skipped\', \'selected\': None, \'correct\': None})
        context.bot.send_message(chat_id, "حدث خطأ في عرض هذا السؤال، سيتم تخطيه.")
        return send_next_question(context, chat_id, user_id, quiz_id, user_data)

    return TAKING_QUIZ

def handle_answer(update: Update, context: CallbackContext):
    """Handles user's answer to a quiz question."""
    print("!!! HANDLE ANSWER (DEBUG PRINT 32) !!!")
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    user_data = context.user_data

    if not user_data.get(\'quiz_active\'):
        logger.warning(f"User {user_id} answered but no active quiz found.")
        safe_edit_message_text(context, chat_id, query.message.message_id, "لم يتم العثور على اختبار نشط.")
        return TAKING_QUIZ

    quiz_id = user_data.get(\'current_quiz_id\')
    current_index = user_data.get(\'current_question_index\', 0)
    questions = user_data.get(\'questions\', [])

    if current_index >= len(questions):
        logger.warning(f"User {user_id} answered but quiz {quiz_id} already finished.")
        return TAKING_QUIZ # Quiz already ended

    try:
        callback_data = query.data
        parts = callback_data.split(\'_\')
        question_id = int(parts[1])
        selected_option_index = int(parts[2]) # 0-based index of the *original* options

        # Verify this answer corresponds to the current question
        current_question_data = questions[current_index]
        current_question_id = current_question_data[0]
        if question_id != current_question_id:
            logger.warning(f"User {user_id} answered question {question_id} but current is {current_question_id}. Ignoring.")
            return TAKING_QUIZ

        # Remove existing question timer
        jobs = context.job_queue.get_jobs_by_name(f"question_timer_{user_id}_{quiz_id}")
        for job in jobs:
            job.schedule_removal()
            logger.info(f"Removed question timer for user {user_id}, quiz {quiz_id}.")

        # Get correct answer index (assuming it's column 6, index 5)
        correct_option_index = current_question_data[6] # 1-based index from DB
        if correct_option_index is None:
             logger.error(f"Question ID {question_id} has no correct answer set in DB!")
             correct_option_index = -1 # Indicate error
        else:
             correct_option_index -= 1 # Convert to 0-based index

        # Get option texts
        options = current_question_data[2:6]
        selected_option_text = options[selected_option_index] if 0 <= selected_option_index < len(options) else "[خطأ]"
        correct_option_text = options[correct_option_index] if 0 <= correct_option_index < len(options) else "[غير محدد]"

        is_correct = (selected_option_index == correct_option_index)

        # Update score and record answer
        status = \'correct\' if is_correct else \'incorrect\'
        if is_correct:
            user_data[\'score\'] = user_data.get(\'score\', 0) + 1

        user_data[\'answered_questions\'].append({
            \'question_id\': question_id,
            \'status\': status,
            \'selected\': selected_option_text,
            \'correct\': correct_option_text
        })
        QUIZ_DB.record_user_answer(user_id, quiz_id, question_id, selected_option_text, is_correct)

        # Provide feedback
        feedback_text = f"✅ إجابة صحيحة!" if is_correct else f"❌ إجابة خاطئة.\nالإجابة الصحيحة: {correct_option_text}"

        # Edit the message to show feedback
        # Get original question text again
        question_text = current_question_data[1]
        formatted_question = process_text_with_chemical_notation(question_text)
        question_number = current_index + 1
        total_questions = len(questions)
        original_message_text = f"**السؤال {question_number}/{total_questions}:**\n\n{formatted_question}"

        # Display selected answer and feedback
        # Highlight selected option (maybe bold or add indicator?)
        # For now, just add feedback below
        updated_message_text = f"{original_message_text}\n\n**إجابتك:** {selected_option_text}\n{feedback_text}"

        try:
            safe_edit_message_text(context, chat_id, query.message.message_id, updated_message_text, reply_markup=None, parse_mode=ParseMode.MARKDOWN)
        except BadRequest:
             # Try without markdown
             updated_message_text_plain = f"السؤال {question_number}/{total_questions}:\n\n{question_text}\n\nإجابتك: {selected_option_text}\n{feedback_text}"
             safe_edit_message_text(context, chat_id, query.message.message_id, updated_message_text_plain, reply_markup=None)

        # Move to the next question after a delay
        user_data[\'current_question_index\'] = current_index + 1
        context.job_queue.run_once(
            lambda ctx: send_next_question(ctx, chat_id, user_id, quiz_id, user_data),
            FEEDBACK_DELAY,
            context={\'chat_id\': chat_id, \'user_id\': user_id, \'quiz_id\': quiz_id} # Pass necessary context
        )

        return TAKING_QUIZ

    except (IndexError, ValueError, KeyError) as e:
        logger.error(f"Error handling answer for user {user_id}, quiz {quiz_id}: {e}", exc_info=True)
        safe_edit_message_text(context, chat_id, query.message.message_id, "حدث خطأ أثناء معالجة إجابتك. سيتم تخطي السؤال.")
        # Skip to next question on error
        user_data[\'current_question_index\'] = current_index + 1
        user_data[\'answered_questions\'].append({\'question_id\': current_question_id, \'status\': \'error_skipped\', \'selected\': None, \'correct\': None})
        return send_next_question(context, chat_id, user_id, quiz_id, user_data)

def skip_question(update: Update, context: CallbackContext):
    """Handles skipping a quiz question."""
    print("!!! SKIP QUESTION (DEBUG PRINT 33) !!!")
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    user_data = context.user_data

    if not user_data.get(\'quiz_active\'):
        logger.warning(f"User {user_id} tried to skip but no active quiz found.")
        safe_edit_message_text(context, chat_id, query.message.message_id, "لم يتم العثور على اختبار نشط.")
        return TAKING_QUIZ

    quiz_id = user_data.get(\'current_quiz_id\')
    current_index = user_data.get(\'current_question_index\', 0)
    questions = user_data.get(\'questions\', [])

    if current_index >= len(questions):
        logger.warning(f"User {user_id} tried to skip but quiz {quiz_id} already finished.")
        return TAKING_QUIZ

    try:
        callback_data = query.data
        question_id = int(callback_data.split(\'_\')[-1])

        # Verify this corresponds to the current question
        current_question_data = questions[current_index]
        current_question_id = current_question_data[0]
        if question_id != current_question_id:
            logger.warning(f"User {user_id} skipped question {question_id} but current is {current_question_id}. Ignoring.")
            return TAKING_QUIZ

        # Remove existing question timer
        jobs = context.job_queue.get_jobs_by_name(f"question_timer_{user_id}_{quiz_id}")
        for job in jobs:
            job.schedule_removal()
            logger.info(f"Removed question timer for user {user_id}, quiz {quiz_id} due to skip.")

        logger.info(f"User {user_id} skipped question {question_id} in quiz {quiz_id}.")

        # Record skip
        user_data[\'answered_questions\'].append({
            \'question_id\': question_id,
            \'status\': \'skipped\',
            \'selected\': None,
            \'correct\': None # Or fetch correct answer if needed for review
        })
        QUIZ_DB.record_user_answer(user_id, quiz_id, question_id, None, False, skipped=True)

        # Move to the next question immediately
        user_data[\'current_question_index\'] = current_index + 1
        return send_next_question(context, chat_id, user_id, quiz_id, user_data, message_id=query.message.message_id)

    except (IndexError, ValueError, KeyError) as e:
        logger.error(f"Error handling skip for user {user_id}, quiz {quiz_id}: {e}", exc_info=True)
        safe_edit_message_text(context, chat_id, query.message.message_id, "حدث خطأ أثناء تخطي السؤال.")
        # Attempt to move to next question anyway
        user_data[\'current_question_index\'] = current_index + 1
        return send_next_question(context, chat_id, user_id, quiz_id, user_data)

def end_quiz(context: CallbackContext, chat_id, user_id, quiz_id, user_data, message_id=None):
    """Ends the quiz and displays the results."""
    print("!!! END QUIZ FUNCTION (DEBUG PRINT 34) !!!")
    if not user_data.get(\'quiz_active\') or user_data.get(\'current_quiz_id\') != quiz_id:
        logger.info(f"Attempted to end quiz {quiz_id} for user {user_id}, but it was not active or mismatched.")
        return ConversationHandler.END # Or appropriate state

    user_data[\'quiz_active\'] = False
    score = user_data.get(\'score\', 0)
    total_questions = len(user_data.get(\'questions\', []))
    quiz_end_time = time.time()
    quiz_start_time = user_data.get(\'quiz_start_time\', quiz_end_time)
    time_taken_seconds = quiz_end_time - quiz_start_time
    time_taken_str = str(timedelta(seconds=int(time_taken_seconds)))

    # Remove timers
    quiz_timer_jobs = context.job_queue.get_jobs_by_name(f"quiz_timeout_{user_id}_{quiz_id}")
    for job in quiz_timer_jobs:
        job.schedule_removal()
    question_timer_jobs = context.job_queue.get_jobs_by_name(f"question_timer_{user_id}_{quiz_id}")
    for job in question_timer_jobs:
        job.schedule_removal()

    # Update quiz session in DB
    QUIZ_DB.end_quiz_session(quiz_id, score, total_questions)

    logger.info(f"Quiz {quiz_id} ended for user {user_id}. Score: {score}/{total_questions}. Time: {time_taken_str}")

    # Prepare results message
    percentage = (score / total_questions * 100) if total_questions > 0 else 0
    result_message = (
        f"🏁 **نتائج الاختبار** 🏁\n\n"
        f"📝 عدد الأسئلة: {total_questions}\n"
        f"✅ الإجابات الصحيحة: {score}\n"
        f"📊 النسبة المئوية: {percentage:.1f}%\n"
        f"⏱️ الوقت المستغرق: {time_taken_str}\n\n"
    )

    # Add performance feedback (simple version)
    if percentage >= 90:
        result_message += "🎉 أداء ممتاز! استمر في التألق!"
    elif percentage >= 75:
        result_message += "👍 جيد جداً! لديك أساس قوي."
    elif percentage >= 50:
        result_message += "💪 لا بأس! تحتاج إلى بعض المراجعة."
    else:
        result_message += "📖 تحتاج إلى المزيد من المذاكرة والمراجعة. لا تيأس!"

    keyboard = create_results_menu_keyboard(quiz_id)

    # Send results
    try:
        if message_id:
            safe_edit_message_text(context, chat_id, message_id, result_message, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        else:
            context.bot.send_message(chat_id, result_message, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    except BadRequest:
        # Try without markdown
        result_message_plain = (
            f"نتائج الاختبار

"
            f"عدد الأسئلة: {total_questions}
"
            f"الإجابات الصحيحة: {score}
"
            f"النسبة المئوية: {percentage:.1f}%
"
            f"الوقت المستغرق: {time_taken_str}

"
        )
        if percentage >= 90:
            result_message_plain += "أداء ممتاز! استمر في التألق!"
        elif percentage >= 75:
            result_message_plain += "جيد جداً! لديك أساس قوي."
        elif percentage >= 50:
            result_message_plain += "لا بأس! تحتاج إلى بعض المراجعة."
        else:
            result_message_plain += "تحتاج إلى المزيد من المذاكرة والمراجعة. لا تيأس!"
        if message_id:
            safe_edit_message_text(context, chat_id, message_id, result_message_plain, reply_markup=keyboard)
        else:
            context.bot.send_message(chat_id, result_message_plain, reply_markup=keyboard)

    # Clean up user_data related to the finished quiz
    keys_to_remove = [\'current_quiz_id\', \'questions\', \'current_question_index\', \'score\', \'quiz_active\', \'quiz_start_time\', \'answered_questions\', \'quiz_type\', \'quiz_duration_minutes\', \'grade_level_id\', \'chapter_id\', \'lesson_id\', \'grade_level_name\', \'chapter_name\', \'lesson_name\']
    for key in keys_to_remove:
        user_data.pop(key, None)

    return MAIN_MENU # Return to main menu after showing results

# --- Admin Handlers (Placeholders or adapt from original/current) ---
# Need functions like: admin_menu, admin_add_question_start, admin_get_question_text, ...
# admin_manage_structure, admin_manage_grades, admin_add_grade, ... etc.

def admin_menu(update: Update, context: CallbackContext):
    print("!!! ADMIN MENU CALLBACK (DEBUG PRINT 35) !!!")
    query = update.callback_query
    user_id = query.from_user.id
    if not is_admin(user_id):
        query.answer("عذراً، هذه المنطقة مخصصة للمشرفين فقط.")
        return MAIN_MENU

    query.answer()
    keyboard = create_admin_menu_keyboard()
    safe_edit_message_text(
        context=context,
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        text="⚙️ قائمة إدارة البوت:",
        reply_markup=keyboard
    )
    return ADMIN_MENU

def admin_manage_structure(update: Update, context: CallbackContext):
    print("!!! ADMIN MANAGE STRUCTURE (DEBUG PRINT 36) !!!")
    query = update.callback_query
    user_id = query.from_user.id
    if not is_admin(user_id):
        query.answer("عذراً، هذه المنطقة مخصصة للمشرفين فقط.")
        return MAIN_MENU

    query.answer()
    keyboard = create_structure_admin_menu_keyboard()
    safe_edit_message_text(
        context=context,
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        text="🏫 إدارة المراحل والفصول والدروس:",
        reply_markup=keyboard
    )
    return ADMIN_MANAGE_STRUCTURE

# --- Generic Update Handler (for debugging webhook) ---
def generic_update_handler(update: Update, context: CallbackContext):
    """Logs any update received when webhook is active."""
    print("!!! GENERIC UPDATE HANDLER (DEBUG PRINT 37) !!!")
    logger.info(f"Received update (Webhook Debug - Final): {update.to_dict()}")
    # Important: Do not return any state here, let other handlers process it.
    # This handler is just for logging.

# --- Error Handler ---
def error_handler(update: Update, context: CallbackContext):
    """Log Errors caused by Updates."""
    print("!!! ERROR HANDLER TRIGGERED (DEBUG PRINT 38) !!!")
    logger.error(f"Update \"{update}\" caused error \"{context.error}\"", exc_info=context.error)

# --- Main Function --- (Webhook setup)
def main():
    """Start the bot."""
    print("!!! MAIN FUNCTION STARTED (DEBUG PRINT 39) !!!")
    # Create the Updater and pass it your bot\'s token.
    # Use the older Updater API style if that\'s what worked before
    updater = Updater(BOT_TOKEN)
    print("!!! UPDATER CREATED (DEBUG PRINT 40) !!!")

    # Get the dispatcher to register handlers
    dp = updater.dispatcher
    print("!!! DISPATCHER OBTAINED (DEBUG PRINT 41) !!!")

    # --- Register Handlers ---
    print("!!! REGISTERING HANDLERS (DEBUG PRINT 42) !!!")
    # Add generic update handler with high priority (-1) to log all updates first
    dp.add_handler(MessageHandler(Filters.all, generic_update_handler), group=-1)
    logger.info("Generic update handler added with high priority (group -1).")

    # Conversation handler for main flow
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler(\'start\', start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(quiz_menu, pattern=\'^menu_quiz$\'),
                CallbackQueryHandler(admin_menu, pattern=\'^menu_admin$\'),
                CallbackQueryHandler(reports_menu, pattern=\'^menu_reports$\'),
                CallbackQueryHandler(about_bot, pattern=\'^menu_about$\'),
                CallbackQueryHandler(show_info_menu, pattern=\'^menu_info$\'), # Add info menu entry
            ],
            QUIZ_MENU: [
                CallbackQueryHandler(quiz_random_prompt, pattern=\'^quiz_random_prompt$\'),
                CallbackQueryHandler(quiz_by_chapter_prompt, pattern=\'^quiz_by_chapter_prompt$\'),
                CallbackQueryHandler(quiz_by_lesson_prompt, pattern=\'^quiz_by_lesson_prompt$\'),
                CallbackQueryHandler(quiz_by_grade_prompt, pattern=\'^quiz_by_grade_prompt$\'),
                # CallbackQueryHandler(quiz_review_prompt, pattern=\'^quiz_review_prompt$\'),
                CallbackQueryHandler(main_menu_callback, pattern=\'^main_menu$\'),
            ],
            ADMIN_MENU: [
                # Add handlers for admin actions like add/delete/show question
                # CallbackQueryHandler(admin_add_question_start, pattern=\'^admin_add_question$\'),
                # CallbackQueryHandler(admin_delete_question_start, pattern=\'^admin_delete_question$\'),
                # CallbackQueryHandler(admin_show_question_start, pattern=\'^admin_show_question$\'),
                CallbackQueryHandler(admin_manage_structure, pattern=\'^admin_manage_structure$\'),
                CallbackQueryHandler(main_menu_callback, pattern=\'^main_menu$\'),
            ],
            ADMIN_MANAGE_STRUCTURE: [
                 # Add handlers for managing grades/chapters/lessons
                 # CallbackQueryHandler(admin_manage_grades_menu, pattern=\'^admin_manage_grades$\'),
                 # CallbackQueryHandler(admin_manage_chapters_menu, pattern=\'^admin_manage_chapters$\'),
                 # CallbackQueryHandler(admin_manage_lessons_menu, pattern=\'^admin_manage_lessons$\'),
                 CallbackQueryHandler(admin_menu, pattern=\'^menu_admin$\'), # Back to admin menu
            ],
            SELECT_GRADE_LEVEL_FOR_QUIZ: [
                CallbackQueryHandler(select_grade_for_quiz, pattern=\'^grade_quiz_\\d+$\' ),
                CallbackQueryHandler(select_grade_for_quiz, pattern=\'^grade_quiz_all$\'), # Handle general assessment
                CallbackQueryHandler(quiz_menu, pattern=\'^menu_quiz$\'), # Back button
            ],
            SELECT_CHAPTER_FOR_QUIZ: [
                CallbackQueryHandler(select_chapter_for_quiz_or_lesson, pattern=\'^chapter_quiz_\\d+$\'),
                CallbackQueryHandler(quiz_by_grade_prompt, pattern=\'^quiz_by_grade_prompt$\'), # Back button
            ],
             SELECT_CHAPTER_FOR_LESSON: [
                CallbackQueryHandler(select_chapter_for_quiz_or_lesson, pattern=\'^lesson_chapter_\\d+$\'),
                CallbackQueryHandler(quiz_by_grade_prompt, pattern=\'^quiz_by_grade_prompt$\'), # Back button
            ],
            SELECT_LESSON_FOR_QUIZ: [
                CallbackQueryHandler(select_lesson_for_quiz, pattern=\'^lesson_quiz_\\d+$\'),
                CallbackQueryHandler(quiz_by_lesson_prompt, pattern=\'^quiz_by_lesson_prompt$\'), # Back button
            ],
            SELECTING_QUIZ_DURATION: [
                CallbackQueryHandler(select_quiz_duration, pattern=\'^quiz_duration_\\d+$\'),
                CallbackQueryHandler(quiz_menu, pattern=\'^menu_quiz$\'), # Back button
            ],
            TAKING_QUIZ: [
                CallbackQueryHandler(handle_answer, pattern=\'^answer_\\d+_\\d+$\'),
                CallbackQueryHandler(skip_question, pattern=\'^skip_\\d+$\'),
                # Add handler to end quiz prematurely? Maybe via command?
            ],
            # Add other states for adding/deleting questions, managing structure etc.
            # ... (Placeholder for other states)
        },
        fallbacks=[
            CommandHandler(\'start\', start), # Allow restarting
            CallbackQueryHandler(main_menu_callback, pattern=\'^main_menu$\') # Allow returning to main menu from anywhere
            # Add a generic message handler? Or rely on ConversationHandler timeouts?
        ],
        # Use defaults from original if needed
        # per_user=True, per_chat=True, per_message=False,
        # allow_reentry=True
    )

    dp.add_handler(conv_handler)
    print("!!! MAIN CONV HANDLER ADDED (DEBUG PRINT 43) !!!")

    # Add the info menu conversation handler separately
    # Ensure it doesn't clash with the main conversation handler states
    # Check if info_menu_conv_handler is correctly defined and imported
    if \'info_menu_conv_handler\' in globals():
        dp.add_handler(info_menu_conv_handler)
        print("!!! INFO MENU HANDLER ADDED (DEBUG PRINT 44) !!!")
    else:
        print("!!! INFO MENU HANDLER NOT FOUND (DEBUG PRINT 44) !!!")

    # Log all errors
    dp.add_error_handler(error_handler)
    print("!!! ERROR HANDLER ADDED (DEBUG PRINT 45) !!!")

    # Start the Bot using Webhook for Heroku
    print("!!! STARTING WEBHOOK (DEBUG PRINT 46) !!!")
    logger.info(f"Starting webhook for Heroku app {HEROKU_APP_NAME}")
    updater.start_webhook(listen="0.0.0.0",
                          port=PORT,
                          url_path=BOT_TOKEN,
                          webhook_url=f"https://{HEROKU_APP_NAME}.herokuapp.com/{BOT_TOKEN}")
    logger.info(f"Webhook set attempt to https://{HEROKU_APP_NAME}.herokuapp.com/{BOT_TOKEN}")

    # Verify webhook info after setting
    try:
        webhook_info = updater.bot.get_webhook_info()
        logger.info(f"Actual webhook info from Telegram: {webhook_info}")
        if not webhook_info.url:
             logger.error("Webhook URL is EMPTY after setting! Telegram might not send updates.")
        elif webhook_info.url != f"https://{HEROKU_APP_NAME}.herokuapp.com/{BOT_TOKEN}":
             logger.warning(f"Webhook URL mismatch! Expected https://{HEROKU_APP_NAME}.herokuapp.com/{BOT_TOKEN} but got {webhook_info.url}")
    except Exception as e:
        logger.error(f"Could not verify webhook info: {e}")

    logger.info("Bot started and running...")
    print("!!! BOT STARTED AND RUNNING (DEBUG PRINT 47) !!!")
    updater.idle()
    print("!!! BOT STOPPED (DEBUG PRINT 48) !!!")

if __name__ == \'__main__\':
    print("!!! SCRIPT ENTRY POINT (DEBUG PRINT 49) !!!")
    main()

