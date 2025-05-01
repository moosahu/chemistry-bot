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
    ParseMode, # Re-add for PTB v13.15
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InputMediaPhoto # Added from original, might be needed for image handling
)
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    # Filters, # Removed in PTB v20+
    CallbackContext,
    CallbackQueryHandler,
    ConversationHandler,
    JobQueue # Added from original for timers
)
from telegram.ext import filters # Import new filters module for PTB v20+from telegram.error import BadRequest, TelegramError, NetworkError, Unauthorized, TimedOut, ChatMigrated # Added error types from original

# --- Configuration & Constants ---

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout) # Use stdout handler like original for Heroku
    ]
)
logger = logging.getLogger(__name__)

# Get sensitive info from environment variables
# Use BOT_TOKEN as confirmed working, not TOKEN from original
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
# Use single hardcoded ADMIN_USER_ID as requested and present in original
ADMIN_USER_ID = 6448526509
PORT = int(os.environ.get("PORT", 8443))
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME")

if not BOT_TOKEN:
    logger.critical("BOT_TOKEN environment variable not set!")
    sys.exit("Bot token not found.")

# Quiz settings from original
DEFAULT_QUIZ_QUESTIONS = 10
DEFAULT_QUIZ_DURATION_MINUTES = 10 # Default duration in minutes
QUESTION_TIMER_SECONDS = 240  # 4 minutes per question (from original)
FEEDBACK_DELAY = 2 # seconds before showing correct answer (keep from current)

# --- Database Setup ---
try:
    from db_utils import connect_db, setup_database
    from quiz_db import QuizDatabase
    # استيراد الدالة المساعدة لمعالجة الأخطاء بأمان
    from helper_function import safe_edit_message_text
except ImportError as e:
    logger.error(f"Failed to import database modules: {e}. Make sure db_utils.py, quiz_db.py, helper_function.py are present.")
    sys.exit("Critical import error, stopping bot.")

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

# Import info menu functions AFTER defining states
from info_menu_function import show_info_menu, INFO_MENU as INFO_MENU_STATE_CONST # Import constant if needed
from info_handlers import info_menu_conv_handler, info_menu_callback # Import the callback too

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

# --- Keyboard Creation Functions (Merge original and current, use original callback data format) ---

def create_main_menu_keyboard(user_id):
    """Creates the main menu inline keyboard (original structure)."""
    keyboard = [
        [InlineKeyboardButton("📚 المعلومات الكيميائية", callback_data='menu_info')],
        [InlineKeyboardButton("📝 الاختبارات", callback_data='menu_quiz')],
        [InlineKeyboardButton("📊 تقارير الأداء", callback_data='menu_reports')],
        [InlineKeyboardButton("ℹ️ حول البوت", callback_data='menu_about')]
    ]
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ إدارة البوت", callback_data='menu_admin')])
    return InlineKeyboardMarkup(keyboard)

def create_quiz_menu_keyboard():
    """Creates the quiz type selection inline keyboard (original structure)."""
    keyboard = [        [InlineKeyboardButton("📚 اختبار تحصيلي عام", callback_data='quiz_random_prompt')],        [InlineKeyboardButton("📄 اختبار حسب الفصل", callback_data='quiz_by_chapter_prompt')],
        [InlineKeyboardButton("📝 اختبار حسب الدرس", callback_data='quiz_by_lesson_prompt')],
        [InlineKeyboardButton("🎓 اختبار حسب المرحلة الدراسية", callback_data='quiz_by_grade_prompt')],
        # [InlineKeyboardButton("🔄 مراجعة الأخطاء", callback_data='quiz_review_prompt')], # Keep commented out
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_admin_menu_keyboard():
    """Creates the admin menu inline keyboard (original structure)."""
    keyboard = [
        [InlineKeyboardButton("➕ إضافة سؤال", callback_data='admin_add_question')],
        [InlineKeyboardButton("🗑️ حذف سؤال", callback_data='admin_delete_question')],
        [InlineKeyboardButton("🔍 عرض سؤال", callback_data='admin_show_question')],
        [InlineKeyboardButton("🏫 إدارة المراحل/الفصول/الدروس", callback_data='admin_manage_structure')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_structure_admin_menu_keyboard():
    """Creates the structure management admin menu (original structure)."""
    keyboard = [
        [InlineKeyboardButton("🏫 إدارة المراحل الدراسية", callback_data='admin_manage_grades')],
        [InlineKeyboardButton("📚 إدارة الفصول", callback_data='admin_manage_chapters')],
        [InlineKeyboardButton("📝 إدارة الدروس", callback_data='admin_manage_lessons')],
        [InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data='menu_admin')] # Corrected callback for back button
    ]
    return InlineKeyboardMarkup(keyboard)

def create_quiz_duration_keyboard():
    """Creates the quiz duration selection inline keyboard (original options)."""
    keyboard = [
        [InlineKeyboardButton("5 دقائق", callback_data='quiz_duration_5')],
        [InlineKeyboardButton("10 دقائق", callback_data='quiz_duration_10')],
        [InlineKeyboardButton("15 دقيقة", callback_data='quiz_duration_15')],
        [InlineKeyboardButton("20 دقيقة", callback_data='quiz_duration_20')],
        [InlineKeyboardButton("30 دقيقة", callback_data='quiz_duration_30')],
        [InlineKeyboardButton("بدون وقت محدد", callback_data='quiz_duration_0')],
        [InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data='menu_quiz')]
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
            callback_suffix = f'quiz_{grade_id}' if for_quiz else f'admin_{grade_id}'
            keyboard.append([InlineKeyboardButton(grade_name, callback_data=f'grade_{callback_suffix}')])
        if for_quiz:
             keyboard.append([InlineKeyboardButton("📚 اختبار تحصيلي عام", callback_data='grade_quiz_all')])
    else:
        logger.info("No grade levels found in the database.")
        return None

    back_callback = 'menu_quiz' if for_quiz else 'admin_manage_structure'
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_chapters_keyboard(grade_level_id, for_quiz=False, for_lesson=False, context=None):
    """Creates keyboard for selecting chapters (adapted from current)."""
    chapters = QUIZ_DB.get_chapters_by_grade(grade_level_id)
    keyboard = []
    if chapters:
        for chapter_id, chapter_name in chapters:
            if for_quiz:
                callback_data = f'chapter_quiz_{chapter_id}'
            elif for_lesson:
                 callback_data = f'lesson_chapter_{chapter_id}'
            else: # Admin context
                callback_data = f'admin_chapter_{chapter_id}'
            keyboard.append([InlineKeyboardButton(chapter_name, callback_data=callback_data)])
    else:
        logger.info(f"No chapters found for grade level {grade_level_id}.")
        return None

    if for_quiz or for_lesson:
        # Original logic seemed complex, stick to current simpler logic for back button
        back_callback = 'quiz_by_grade_prompt'
    else: # Admin context
        back_callback = 'admin_manage_structure'
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_lessons_keyboard(chapter_id, for_quiz=False, context=None):
    """Creates keyboard for selecting lessons (adapted from current)."""
    lessons = QUIZ_DB.get_lessons_by_chapter(chapter_id)
    keyboard = []
    if lessons:
        for lesson_id, lesson_name in lessons:
            callback_data = f'lesson_quiz_{lesson_id}' if for_quiz else f'admin_lesson_{lesson_id}'
            keyboard.append([InlineKeyboardButton(lesson_name, callback_data=callback_data)])
    else:
        logger.info(f"No lessons found for chapter {chapter_id}.")
        return None

    if for_quiz:
        # Stick to current simpler back logic
        back_callback = 'quiz_by_lesson_prompt'
    else: # Admin context
        back_callback = 'admin_manage_structure'
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_quiz_question_keyboard(options, question_id):
    """Creates the keyboard for a multiple-choice quiz question (adapted from current)."""
    keyboard = []
    shuffled_options = list(enumerate(options))
    random.shuffle(shuffled_options)

    for original_index, option_text in shuffled_options:
        callback_data = f'answer_{question_id}_{original_index}' # Use original format
        keyboard.append([InlineKeyboardButton(option_text, callback_data=callback_data)])

    keyboard.append([InlineKeyboardButton("⏭️ تخطي السؤال", callback_data=f'skip_{question_id}')])
    return InlineKeyboardMarkup(keyboard)

def create_results_menu_keyboard(quiz_id):
    """Creates keyboard for quiz results view (adapted from current)."""
    keyboard = [
        # [InlineKeyboardButton("🧐 مراجعة الأخطاء", callback_data=f'review_{quiz_id}')],
        [InlineKeyboardButton("🔄 إعادة الاختبار", callback_data='menu_quiz')],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Timer Functions (from original) ---

def set_quiz_timer(context: CallbackContext, chat_id, user_id, quiz_id, duration_minutes):
    """Sets a timer to end the quiz after the specified duration."""
    if duration_minutes <= 0:
        return None

    job_context = {
        'chat_id': chat_id,
        'user_id': user_id,
        'quiz_id': quiz_id
    }
    try:
        # Ensure end_quiz_timeout function exists or is defined
        if 'end_quiz_timeout' not in globals():
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
        'chat_id': chat_id,
        'user_id': user_id,
        'quiz_id': quiz_id,
        'type': 'question_timer'
    }
    try:
        # Ensure question_timer_callback function exists or is defined
        if 'question_timer_callback' not in globals():
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
    chat_id = job_context['chat_id']
    user_id = job_context['user_id']
    quiz_id = job_context['quiz_id']

    # Use context.dispatcher.user_data as in original
    user_data = context.dispatcher.user_data.get(user_id, {})
    # Check if quiz is still active (adjust state name if needed)
    if user_data.get('conversation_state') == TAKING_QUIZ and user_data.get('quiz', {}).get('id') == quiz_id:
        logger.info(f"Question timer expired for quiz {quiz_id}, user {user_id}. Moving to next question.")

        quiz_data = user_data['quiz']
        current_index = quiz_data['current_question_index']
        questions = quiz_data['questions']

        # Placeholder: Need logic to handle skipping/moving to next question
        logger.warning("Question timer callback: Skipping/next question logic not implemented.")
        # Example: send_next_question(context, chat_id, user_id, quiz_id)

# Placeholder for end_quiz_timeout (needed by set_quiz_timer)
def end_quiz_timeout(context: CallbackContext):
    """Callback function when the overall quiz timer expires."""
    job_context = context.job.context
    chat_id = job_context['chat_id']
    user_id = job_context['user_id']
    quiz_id = job_context['quiz_id']

    user_data = context.dispatcher.user_data.get(user_id, {})
    if user_data.get('conversation_state') == TAKING_QUIZ and user_data.get('quiz', {}).get('id') == quiz_id:
        logger.info(f"Quiz timer expired for quiz {quiz_id}, user {user_id}. Ending quiz.")
        # Placeholder: Need logic to end the quiz and show results
        logger.warning("Quiz timeout callback: End quiz logic not implemented.")
        # Example: show_quiz_results(context, chat_id, user_id, quiz_id)
        context.bot.send_message(chat_id, "انتهى وقت الاختبار!")
        # Clean up user data and return to main menu (example)
        keys_to_clear = [k for k in user_data if k not in ["user_id"]]
        for key in keys_to_clear:
            del user_data[key]
        user_data['conversation_state'] = MAIN_MENU
        context.bot.send_message(chat_id, "القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))


# --- Command Handlers (Merge/Adapt) ---

def start(update: Update, context: CallbackContext) -> int:
    """Sends a welcome message and the main menu (adapted)."""
    user = update.effective_user
    user_id = user.id
    name = get_user_name(user)
    logger.info(f"User {name} (ID: {user_id}) started the bot.")

    if QUIZ_DB:
        QUIZ_DB.add_or_update_user(user_id, user.username, user.first_name, user.last_name)
    else:
        logger.error("Cannot add/update user: QuizDatabase not initialized.")

    context.user_data["user_id"] = user_id

    welcome_text = f"أهلاً بك يا {name} في بوت الكيمياء التعليمي! 👋\n\n"
    welcome_text += "استخدم الأزرار أدناه للتنقل بين الأقسام المختلفة."

    keyboard = create_main_menu_keyboard(user_id)
    update.message.reply_text(welcome_text, reply_markup=keyboard)

    return MAIN_MENU

def cancel(update: Update, context: CallbackContext) -> int:
    """Cancels the current operation and returns to the main menu (adapted)."""
    user = update.effective_user
    user_id = user.id
    logger.info(f"User {user_id} canceled operation.")

    # Remove quiz timer (use original job name format)
    quiz_id = context.user_data.get('quiz', {}).get('id')
    if quiz_id:
        quiz_job_name = f"quiz_timeout_{user_id}_{quiz_id}"
        current_quiz_jobs = context.job_queue.get_jobs_by_name(quiz_job_name)
        if current_quiz_jobs:
            for job in current_quiz_jobs:
                job.schedule_removal()
            logger.info(f"Removed active quiz timer job {quiz_job_name}.")

        # Remove question timer (use original job name format)
        question_job_name = f"question_timer_{user_id}_{quiz_id}"
        current_question_jobs = context.job_queue.get_jobs_by_name(question_job_name)
        if current_question_jobs:
            for job in current_question_jobs:
                job.schedule_removal()
            logger.info(f"Removed active question timer job {question_job_name}.")

    # Remove feedback timer (from current version)
    feedback_job_name = f"feedback_timer_{user_id}"
    feedback_jobs = context.job_queue.get_jobs_by_name(feedback_job_name)
    if feedback_jobs:
        for job in feedback_jobs:
            job.schedule_removal()
        logger.info(f"Removed active feedback timer job {feedback_job_name}.")

    update.message.reply_text(
        "تم إلغاء العملية الحالية. العودة إلى القائمة الرئيسية.",
        reply_markup=create_main_menu_keyboard(user_id)
    )

    keys_to_clear = [k for k in context.user_data if k not in ["user_id"]]
    for key in keys_to_clear:
        del context.user_data[key]
    # Set conversation state explicitly
    context.user_data['conversation_state'] = MAIN_MENU

    return MAIN_MENU

def help_command(update: Update, context: CallbackContext):
    """Displays help information (adapted)."""
    user = update.effective_user
    help_text = "مرحباً! أنا بوت الكيمياء التعليمي. يمكنك استخدامي لـ:\n"
    help_text += "- 📚 تصفح المعلومات الكيميائية.\n"
    help_text += "- 📝 إجراء اختبارات في مواضيع مختلفة.\n"
    help_text += "- 📊 مراجعة أدائك في الاختبارات (قيد التطوير).\n\n"
    help_text += "استخدم الأوامر التالية:\n"
    help_text += "/start - لبدء البوت أو العودة للقائمة الرئيسية.\n"
    help_text += "/help - لعرض هذه الرسالة.\n"
    help_text += "/cancel - لإلغاء أي عملية جارية والعودة للقائمة الرئيسية.\n\n"
    help_text += "استخدم الأزرار التي تظهر لك للتنقل بين الأقسام."

    update.message.reply_text(help_text, reply_markup=create_main_menu_keyboard(user.id))
    # Don't return state from command handler unless it's the entry point
    # return MAIN_MENU

# --- Callback Query Handlers (Merge/Adapt) ---

def main_menu_callback(update: Update, context: CallbackContext) -> int:
    """Handles main menu button presses (adapted)."""
    query = update.callback_query
    query.answer()
    user = query.from_user
    user_id = user.id
    data = query.data

    logger.info(f"User {user_id} chose {data} from main menu.")

    if "user_id" not in context.user_data:
        context.user_data["user_id"] = user_id

    if data == 'menu_info':
        # Use the function imported from info_menu_function
        # This should return the initial state for the info menu conversation
        return show_info_menu(update, context)
    elif data == 'menu_quiz':
        safe_edit_message_text(query, text="اختر نوع الاختبار:", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU
    elif data == 'menu_reports':
        safe_edit_message_text(query, text="ميزة التقارير قيد التطوير. 🚧", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU
    elif data == 'menu_about':
        about_text = "بوت الكيمياء التعليمي\n"
        about_text += "تم التطوير بواسطة الاستاذ حسين الموسى\n"
        about_text += "الإصدار: 1.0 (تجريبي)\n\n"
        about_text += "يهدف هذا البوت لمساعدتك في دراسة الكيمياء من خلال الاختبارات والمعلومات."
        safe_edit_message_text(query, text=about_text, reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU
    elif data == 'menu_admin':
        if is_admin(user_id):
            safe_edit_message_text(query, text="قائمة إدارة البوت:", reply_markup=create_admin_menu_keyboard())
            return ADMIN_MENU
        else:
            query.answer("ليس لديك صلاحيات الوصول لهذه القائمة.", show_alert=True)
            return MAIN_MENU # Stay in main menu
    else:
        logger.warning(f"Unexpected callback data '{data}' received in MAIN_MENU state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU

# Placeholder for quiz menu callback (needs merging)
def quiz_menu_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data
    logger.info(f"User {user_id} chose {data} from quiz menu.")

    if data == 'main_menu':
        safe_edit_message_text(query, text="القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU
    elif data == 'quiz_random_prompt':
        context.user_data['quiz_type'] = 'random'
        context.user_data['quiz_filter_id'] = None # No filter for random
        safe_edit_message_text(query, text="اختر مدة الاختبار العشوائي:", reply_markup=create_quiz_duration_keyboard())
        return SELECTING_QUIZ_DURATION
    elif data == 'quiz_by_grade_prompt':
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
        if keyboard:
            safe_edit_message_text(query, text="اختر المرحلة الدراسية للاختبار:", reply_markup=keyboard)
            context.user_data['quiz_selection_mode'] = 'grade' # Mode is grade quiz
            return SELECT_GRADE_LEVEL_FOR_QUIZ
        else:
            safe_edit_message_text(query, text="لم يتم إضافة مراحل دراسية بعد.", reply_markup=create_quiz_menu_keyboard())
            return QUIZ_MENU
    elif data == 'quiz_by_chapter_prompt':
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
        if keyboard:
            safe_edit_message_text(query, text="أولاً، اختر المرحلة الدراسية التي ينتمي إليها الفصل:", reply_markup=keyboard)
            context.user_data['quiz_selection_mode'] = 'chapter'
            return SELECT_GRADE_LEVEL_FOR_QUIZ
        else:
            safe_edit_message_text(query, text="لم يتم إضافة مراحل دراسية بعد.", reply_markup=create_quiz_menu_keyboard())
            return QUIZ_MENU
    elif data == 'quiz_by_lesson_prompt':
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
        if keyboard:
            safe_edit_message_text(query, text="أولاً، اختر المرحلة الدراسية التي ينتمي إليها الدرس:", reply_markup=keyboard)
            context.user_data['quiz_selection_mode'] = 'lesson'
            return SELECT_GRADE_LEVEL_FOR_QUIZ
        else:
            safe_edit_message_text(query, text="لم يتم إضافة مراحل دراسية بعد.", reply_markup=create_quiz_menu_keyboard())
            return QUIZ_MENU
    # Add other quiz menu options if needed
    else:
        logger.warning(f"Unexpected callback data '{data}' in QUIZ_MENU state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

# Placeholder for selecting quiz duration (needs merging, use original duration format)
def select_quiz_duration_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data
    logger.info(f"User {user_id} chose duration {data}.")

    if data.startswith('quiz_duration_'):
        try:
            duration_minutes = int(data.split('_')[-1])
            context.user_data['quiz_duration_minutes'] = duration_minutes
            quiz_type = context.user_data.get('quiz_type')
            quiz_filter_id = context.user_data.get('quiz_filter_id')
            # Need the function to start the quiz
            # return start_quiz(update, context, quiz_type, quiz_filter_id)
            logger.info("Placeholder: Need to implement start_quiz function call here.")
            safe_edit_message_text(query, text=f"تم اختيار مدة الاختبار: {duration_minutes} دقيقة. (بدء الاختبار - قيد التطوير)")
            # For now, return to main menu after selection
            # In reality, should return TAKING_QUIZ after starting
            # return TAKING_QUIZ
            return MAIN_MENU # Placeholder return
        except ValueError:
            logger.error(f"Invalid duration value in callback data: {data}")
            safe_edit_message_text(query, text="مدة غير صالحة.", reply_markup=create_quiz_duration_keyboard())
            return SELECTING_QUIZ_DURATION
    elif data == 'menu_quiz':
        safe_edit_message_text(query, text="اختر نوع الاختبار:", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU
    else:
        logger.warning(f"Unexpected callback data '{data}' in SELECTING_QUIZ_DURATION state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_quiz_duration_keyboard())
        return SELECTING_QUIZ_DURATION

# --- Admin Handlers (Need careful merging) ---
# Placeholder for admin menu callback
def admin_menu_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    if not is_admin(user_id):
        query.answer("ليس لديك صلاحيات.", show_alert=True)
        return MAIN_MENU

    logger.info(f"Admin {user_id} chose {data} from admin menu.")

    if data == 'main_menu':
        safe_edit_message_text(query, text="القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU
    elif data == 'admin_add_question':
        # Start add question flow (placeholder)
        safe_edit_message_text(query, text="بدء عملية إضافة سؤال (قيد التطوير).", reply_markup=create_admin_menu_keyboard())
        # return ADDING_QUESTION # Should go to the first step of adding
        return ADMIN_MENU # Placeholder return
    elif data == 'admin_delete_question':
        safe_edit_message_text(query, text="ميزة حذف الأسئلة قيد التطوير. 🚧", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU
    elif data == 'admin_show_question':
        safe_edit_message_text(query, text="ميزة عرض الأسئلة قيد التطوير. 🚧", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU
    elif data == 'admin_manage_structure':
        safe_edit_message_text(query, text="إدارة الهيكل الدراسي:", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE
    else:
        logger.warning(f"Unexpected callback data '{data}' in ADMIN_MENU state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU

# Callback handler for the admin structure management menu
def admin_structure_menu_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    if not is_admin(user_id):
        query.answer("ليس لديك صلاحيات.", show_alert=True)
        # Go back to main menu if not admin somehow reached here
        safe_edit_message_text(query, text="القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU

    logger.info(f"Admin {user_id} chose {data} from admin structure menu.")

    if data == 'menu_admin': # Handle the back button
        safe_edit_message_text(query, text="قائمة إدارة البوت:", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU
    elif data == 'admin_manage_grades':
        # Placeholder for managing grades
        safe_edit_message_text(query, text="إدارة المراحل الدراسية (قيد التطوير).", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE # Stay in the same menu for now
    elif data == 'admin_manage_chapters':
        # Placeholder for managing chapters
        safe_edit_message_text(query, text="إدارة الفصول (قيد التطوير).", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE # Stay in the same menu for now
    elif data == 'admin_manage_lessons':
        # Placeholder for managing lessons
        safe_edit_message_text(query, text="إدارة الدروس (قيد التطوير).", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE # Stay in the same menu for now
    else:
        logger.warning(f"Unexpected callback data '{data}' in ADMIN_MANAGE_STRUCTURE state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE

# --- Other handlers (Need merging: quiz taking, admin structure management, etc.) ---
# --- This requires significant effort to merge correctly --- 

# --- Error Handler ---
def error_handler(update: Update, context: CallbackContext):
    """Log Errors caused by Updates."""
    logger.error(f"Update \"{update}\" caused error \"{context.error}\"", exc_info=context.error)
    # Optionally send a message to the user or admin
    # if isinstance(context.error, (TimedOut, NetworkError)):
    #     # Handle temporary network issues
    #     pass
    # elif isinstance(context.error, Unauthorized):
    #     # Handle bot being blocked or kicked
    #     pass
    # else:
    #     # Handle other errors
    #     if update and update.effective_chat:
    #         update.effective_chat.send_message("حدث خطأ ما. يرجى المحاولة مرة أخرى لاحقاً.")
    #     pass

# --- Main Function --- 
def main():
    """Start the bot."""
    # Create the Updater and pass it your bot's token.
    updater = Updater(BOT_TOKEN, use_context=True)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # --- Conversation Handler Setup (Merge handlers carefully) ---
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(main_menu_callback, pattern='^menu_.*$'),
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$') # Handle direct return
            ],
            QUIZ_MENU: [
                CallbackQueryHandler(quiz_menu_callback, pattern='^quiz_.*$'),
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$')
            ],
            ADMIN_MENU: [
                CallbackQueryHandler(admin_menu_callback, pattern='^admin_.*$'),
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$')
            ],
            SELECTING_QUIZ_DURATION: [
                CallbackQueryHandler(select_quiz_duration_callback, pattern='^quiz_duration_.*$'),
                CallbackQueryHandler(quiz_menu_callback, pattern='^menu_quiz$') # Back button
            ],
            ADMIN_MANAGE_STRUCTURE: [ # Added state handler
                CallbackQueryHandler(admin_structure_menu_callback, pattern='^admin_manage_.*$'), # Handle structure options
                CallbackQueryHandler(admin_structure_menu_callback, pattern='^menu_admin$') # Handle back button
            ],
            # --- Add other states and their handlers here --- 
            # SELECT_GRADE_LEVEL_FOR_QUIZ: [...],
            # SELECT_CHAPTER_FOR_QUIZ: [...],
            # SELECT_LESSON_FOR_QUIZ: [...],
            # TAKING_QUIZ: [...],
            # ADMIN_MANAGE_GRADES: [...],
            # ADMIN_MANAGE_CHAPTERS: [...],
            # ADMIN_MANAGE_LESSONS: [...],
            # ADDING_QUESTION: [...],
            # ... etc ...

            # Integrate the INFO_MENU handler
            INFO_MENU: [CallbackQueryHandler(info_menu_callback)], # Use the imported callback directly
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CommandHandler('start', start) # Allow restarting with /start
        ],
        # Allow re-entry into the conversation
        allow_reentry=True
    )

    # Add ConversationHandler to dispatcher
    dp.add_handler(conv_handler)

    # Add other handlers (like /help) outside the conversation if needed
    dp.add_handler(CommandHandler('help', help_command))

    # Log all errors
    dp.add_error_handler(error_handler)

    # Start the Bot using Webhook for Heroku
    if HEROKU_APP_NAME:
        logger.info(f"Starting webhook for Heroku app {HEROKU_APP_NAME}")
        updater.start_webhook(listen="0.0.0.0",
                              port=PORT,
                              url_path="webhook", # Use a simple, static path
                              webhook_url=f"https://{HEROKU_APP_NAME}.herokuapp.com/webhook") # Update URL accordingly
        logger.info(f"Webhook set to https://{HEROKU_APP_NAME}.herokuapp.com/webhook")
    else:
        # Start polling if not on Heroku (for local testing)
        logger.info("Starting bot in polling mode (not on Heroku)")
        updater.start_polling()

    # Run the bot until you press Ctrl-C
    logger.info("Bot started and running...")
    updater.idle()

if __name__ == '__main__':
    main()

