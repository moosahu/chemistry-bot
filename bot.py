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
import requests # Added for API calls
from io import BytesIO
from datetime import datetime, timedelta

# Third-party libraries
import pandas as pd
import psycopg2
import psycopg2.extras # Import extras for DictCursor
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
    CallbackContext,
    CallbackQueryHandler,
    ConversationHandler,
    JobQueue,
    Dispatcher # Import Dispatcher
)
from telegram.ext import Filters
from telegram.error import BadRequest, TelegramError, NetworkError, Unauthorized, TimedOut, ChatMigrated

# --- Configuration & Constants ---

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO, # Keep INFO for Render
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG) # Temporarily set to DEBUG for detailed diagnosis

logger.debug("[DIAG] Logger initialized with DEBUG level.")

# Get sensitive info from environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_USER_ID = os.environ.get("ADMIN_USER_ID", "6448526509")
PORT = int(os.environ.get("PORT", 8443))
APP_NAME = os.environ.get("APP_NAME")
# Corrected API Base URL - Ensure it points to the root of the API service
API_BASE_URL = "https://question-manager-web.onrender.com" # Base URL for the backend API

logger.debug(f"[DIAG] BOT_TOKEN found: {'Yes' if BOT_TOKEN else 'No'}")
logger.debug(f"[DIAG] DATABASE_URL found: {'Yes' if DATABASE_URL else 'No'}")
logger.debug(f"[DIAG] ADMIN_USER_ID: {ADMIN_USER_ID}")
logger.debug(f"[DIAG] API_BASE_URL: {API_BASE_URL}")

if not BOT_TOKEN:
    logger.critical("BOT_TOKEN environment variable not set!")
    sys.exit("Bot token not found.")

# Quiz settings
# DEFAULT_QUIZ_QUESTIONS = 10 # No longer default, user selects
DEFAULT_QUIZ_DURATION_MINUTES = 0 # No overall quiz timer unless needed
QUESTION_TIMER_SECONDS = 180 # 3 minutes per question
FEEDBACK_DELAY = 1.5
ENABLE_QUESTION_TIMER = True # Enable the per-question timer

# --- Database Setup (Only for Users and Results now) ---
try:
    logger.debug("[DIAG] Attempting to import db_utils, quiz_db, helper_function...")
    from db_utils import connect_db, setup_database
    # quiz_db is no longer needed for fetching questions
    from quiz_db import QuizDatabase # Keep for user/result management
    # Remove import of safe_edit_message_text, keep safe_send_message
    from helper_function import safe_send_message
    logger.debug("[DIAG] Imports successful.")
except ImportError as e:
    logger.error(f"Failed to import database/helper modules: {e}. Ensure db_utils.py, quiz_db.py, helper_function.py are present.")
    sys.exit("Critical import error, stopping bot.")

# Initialize database connection and QuizDatabase instance (for users/results)
if not DATABASE_URL:
    logger.error("DATABASE_URL environment variable not set or empty. Bot cannot connect to DB for user/result data.")
    DB_CONN = None
    QUIZ_DB = None
else:
    logger.debug("[DIAG] Attempting to connect to database...")
    DB_CONN = connect_db(DATABASE_URL)
    if DB_CONN:
        logger.debug("[DIAG] Database connection successful. Setting up database...")
        setup_database() # Ensure tables exist (users, quiz_results)
        logger.debug("[DIAG] Database setup complete. Initializing QuizDatabase...")
        QUIZ_DB = QuizDatabase(DB_CONN) # Keep instance for user/result methods
        logger.info("QuizDatabase initialized successfully (for users/results).")
    else:
        logger.error("Failed to establish database connection. Bot cannot save user/result data.")
        QUIZ_DB = None # Set to None if connection fails

# --- Chemistry Data (Placeholders - Likely replaced by API calls) ---
try:
    logger.debug("[DIAG] Loading chemistry data placeholders...")
    # These might not be needed if info comes from API
    ELEMENTS, COMPOUNDS, CONCEPTS, PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO = {}, {}, {}, {}, {}, {}
    def process_text_with_chemical_notation(text): return text
    def format_chemical_equation(text): return text
    logger.info("Chemistry data and equation functions loaded (placeholders used).")
except ImportError as e:
    logger.warning(f"Could not import chemistry_data.py or chemical_equations.py: {e}. Some features might be limited.")
    ELEMENTS, COMPOUNDS, CONCEPTS, PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO = {}, {}, {}, {}, {}, {}
    def process_text_with_chemical_notation(text): return text
    def format_chemical_equation(text): return text

# --- States for Conversation Handler (Expanded) ---
logger.debug("[DIAG] Defining conversation states...")
(
    MAIN_MENU, QUIZ_MENU, ADMIN_MENU, ADDING_QUESTION, ADDING_OPTIONS,
    ADDING_CORRECT_ANSWER, ADDING_EXPLANATION, DELETING_QUESTION,
    SHOWING_QUESTION, SELECTING_QUIZ_TYPE, SELECTING_CHAPTER, # Obsolete
    SELECTING_LESSON, SELECTING_QUIZ_DURATION, TAKING_QUIZ,
    SELECT_CHAPTER_FOR_LESSON, # Obsolete
    SELECT_LESSON_FOR_QUIZ, # Obsolete
    SELECT_CHAPTER_FOR_QUIZ, # Obsolete
    SELECT_GRADE_LEVEL, SELECT_GRADE_LEVEL_FOR_QUIZ, ADMIN_GRADE_MENU,
    ADMIN_CHAPTER_MENU, ADMIN_LESSON_MENU, ADDING_GRADE_LEVEL,
    ADDING_CHAPTER, ADDING_LESSON, SELECTING_GRADE_FOR_CHAPTER,
    SELECTING_CHAPTER_FOR_LESSON_ADMIN, ADMIN_MANAGE_STRUCTURE,
    ADMIN_MANAGE_GRADES, ADMIN_MANAGE_CHAPTERS, ADMIN_MANAGE_LESSONS,
    INFO_MENU, # State for showing info menu (e.g., list of courses)
    SHOWING_INFO_CONTENT, # State for showing specific info (not used yet)
    SHOWING_REPORTS, # State after clicking reports button
    SELECT_CHAPTER_FOR_LESSON_QUIZ, # Obsolete
    SHOWING_RESULTS, # State after quiz ends
    # New states for hierarchical quiz selection
    SELECT_COURSE_FOR_QUIZ, # User is selecting a course
    SELECT_UNIT_FOR_QUIZ,   # User is selecting a unit within a course
    SELECT_LESSON_FOR_QUIZ_HIERARCHY, # User is selecting a lesson within a unit (renamed)
    SELECT_QUESTION_COUNT, # NEW: User is selecting number of questions
    CONFIRM_QUIZ_START      # Optional: Confirm before starting quiz by C/U/L
) = range(41) # Corrected range
logger.debug("[DIAG] Conversation states defined.")

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

# --- API Interaction Functions (Corrected and Expanded) ---

def fetch_from_api(endpoint: str, params: dict = None) -> dict | list | None:
    """Fetches data (dict or list) from the specified API endpoint."""
    url = f"{API_BASE_URL}{endpoint}"
    logger.info(f"[API] Fetching from: {url} with params: {params}")
    try:
        response = requests.get(url, params=params, timeout=20)
        logger.info(f"[API] Response status: {response.status_code} for {url}")
        response.raise_for_status()
        data = response.json()
        return data
    except requests.exceptions.Timeout:
        logger.error(f"[API] Request timed out for {url}")
        return "TIMEOUT"
    except requests.exceptions.RequestException as e:
        logger.error(f"[API] Request failed for {url}: {e}")
        return None
    except ValueError as e:
        logger.error(f"[API] Failed to decode JSON response from {url}: {e}")
        return None

def transform_api_question(api_question: dict) -> dict | None:
    """Transforms a single question object from API format to bot format."""
    if not isinstance(api_question, dict):
        logger.error(f"[DIAG] Invalid API question format: Expected dict, got {type(api_question)}")
        return None

    question_id = api_question.get("id")
    question_text = api_question.get("text")
    question_image_url = api_question.get("image_url")
    api_options = api_question.get("options")

    if question_id is None or not isinstance(api_options, list):
        logger.error(f"[DIAG] Skipping question due to missing ID or invalid options: {api_question}")
        return None

    bot_options_text = [None] * 4
    bot_options_image = [None] * 4
    correct_answer_index = None

    for i, opt in enumerate(api_options):
        if i >= 4:
            logger.warning(f"[DIAG] Question {question_id} has more than 4 options, ignoring extras.")
            break
        if isinstance(opt, dict):
            bot_options_text[i] = opt.get("text")
            bot_options_image[i] = opt.get("image_url")
            if opt.get("is_correct") is True:
                if correct_answer_index is not None:
                    logger.warning(f"[DIAG] Multiple correct options found for question {question_id}. Using the first one.")
                else:
                    correct_answer_index = i
        else:
            logger.warning(f"[DIAG] Invalid option format in question {question_id}: {opt}")

    if not question_text and not question_image_url:
        logger.error(f"[DIAG] Skipping question {question_id}: No text or image provided.")
        return None
    if correct_answer_index is None:
        logger.error(f"[DIAG] Skipping question {question_id}: No correct answer found.")
        return None
    if bot_options_text[correct_answer_index] is None and bot_options_image[correct_answer_index] is None:
        logger.error(f"[DIAG] Skipping question {question_id}: Correct answer option ({correct_answer_index}) has no text or image.")
        return None

    bot_question = {
        "question_id": question_id,
        "question_text": question_text,
        "image_url": question_image_url,
        "option1": bot_options_text[0],
        "option2": bot_options_text[1],
        "option3": bot_options_text[2],
        "option4": bot_options_text[3],
        "option1_image": bot_options_image[0],
        "option2_image": bot_options_image[1],
        "option3_image": bot_options_image[2],
        "option4_image": bot_options_image[3],
        "correct_answer": correct_answer_index,
        "explanation": api_question.get("explanation")
    }
    return bot_question

# --- Timer Functions ---

def remove_job_if_exists(name: str, context: CallbackContext) -> bool:
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
        logger.info(f"Removed timer job: {name}")
    return True

def set_quiz_timer(context: CallbackContext, chat_id: int, user_id: int, quiz_id: int, duration_minutes: int):
    # Overall quiz timer - currently disabled (duration_minutes=0)
    if duration_minutes > 0:
        job_name = f"quiz_timer_{chat_id}_{user_id}_{quiz_id}"
        remove_job_if_exists(job_name, context)
        context.job_queue.run_once(
            end_quiz_timeout,
            duration_minutes * 60,
            context={"chat_id": chat_id, "user_id": user_id, "quiz_id": quiz_id},
            name=job_name
        )
        logger.info(f"Set quiz timer for {duration_minutes} minutes. Job: {job_name}")
        return job_name
    return None

def set_question_timer(context: CallbackContext, chat_id: int, user_id: int, quiz_id: int, question_index: int):
    # Per-question timer - now enabled
    if ENABLE_QUESTION_TIMER and QUESTION_TIMER_SECONDS > 0:
        job_name = f"question_timer_{chat_id}_{user_id}_{quiz_id}"
        remove_job_if_exists(job_name, context)
        context.job_queue.run_once(
            question_timer_callback,
            QUESTION_TIMER_SECONDS,
            context={"chat_id": chat_id, "user_id": user_id, "quiz_id": quiz_id, "question_index": question_index},
            name=job_name
        )
        logger.info(f"Set question timer for {QUESTION_TIMER_SECONDS} seconds. Job: {job_name}")
        return job_name
    return None

def end_quiz_timeout(context: CallbackContext):
    # Handles overall quiz timeout (currently unused)
    job_context = context.job.context
    chat_id = job_context["chat_id"]
    user_id = job_context["user_id"]
    quiz_id = job_context["quiz_id"]
    logger.info(f"Quiz timer expired for quiz {quiz_id} for user {user_id} in chat {chat_id}.")

    if not hasattr(context, 'dispatcher'):
         logger.error("Dispatcher not found in context for end_quiz_timeout. Cannot access user_data.")
         return

    user_data = context.dispatcher.user_data.get(user_id, {})
    quiz_data = user_data.get("current_quiz")

    if quiz_data and quiz_data["quiz_id"] == quiz_id and not quiz_data.get("timed_out"):
        quiz_data["timed_out"] = True
        if quiz_data.get("question_timer_job_name"):
            remove_job_if_exists(quiz_data["question_timer_job_name"], context)
            quiz_data["question_timer_job_name"] = None

        safe_send_message(context.bot, chat_id, text="⏰ انتهى وقت الاختبار!")
        show_results(chat_id, user_id, quiz_id, context, timed_out=True)
    else:
        logger.info(f"Quiz {quiz_id} already finished or cancelled, ignoring timeout.")

def question_timer_callback(context: CallbackContext):
    # Handles per-question timeout
    job_context = context.job.context
    chat_id = job_context["chat_id"]
    user_id = job_context["user_id"]
    quiz_id = job_context["quiz_id"]
    question_index = job_context["question_index"]
    logger.info(f"Question timer expired for question {question_index} in quiz {quiz_id} for user {user_id}.")

    if not hasattr(context, 'dispatcher'):
         logger.error("Dispatcher not found in context for question_timer_callback. Cannot access user_data.")
         return

    user_data = context.dispatcher.user_data.get(user_id, {})
    quiz_data = user_data.get("current_quiz")

    # Check if the quiz is still active and the timed-out question is the current one
    if quiz_data and quiz_data["quiz_id"] == quiz_id and quiz_data["current_question_index"] == question_index and not quiz_data.get("timed_out"):
        safe_send_message(context.bot, chat_id, text=f"⏰ انتهى وقت السؤال {question_index + 1}! سيتم اعتباره متخطى.")
        # Call the skip handler, marking it as timed out
        handle_quiz_skip(chat_id, user_id, quiz_id, question_index, context, timed_out=True)
    else:
        logger.info(f"Question {question_index} already answered/skipped or quiz ended, ignoring timer.")

# --- Keyboard Creation Functions ---

def create_main_menu_keyboard(user_id):
    keyboard = [
        [InlineKeyboardButton("📚 المعلومات الكيميائية", callback_data="menu_info")],
        [InlineKeyboardButton("📝 الاختبارات", callback_data="menu_quiz")],
        [InlineKeyboardButton("📊 تقارير الأداء", callback_data="menu_reports")],
        [InlineKeyboardButton("ℹ️ حول البوت", callback_data="menu_about")]
    ]
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ إدارة البوت", callback_data="menu_admin")])
    return InlineKeyboardMarkup(keyboard)

def create_quiz_menu_keyboard():
    """Creates the main keyboard for the Quiz section."""
    keyboard = [
        [InlineKeyboardButton("📚 اختبار تحصيلي عام", callback_data="quiz_type_random")], # Changed callback
        [InlineKeyboardButton("📄 اختبار حسب المقرر", callback_data="quiz_select_course")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_dynamic_keyboard(items: list, callback_prefix: str, back_callback: str, items_per_row: int = 2):
    """Creates a dynamic keyboard from a list of items (dicts with id and name)."""
    keyboard = []
    row = []
    for item in items:
        button = InlineKeyboardButton(item["name"], callback_data=f"{callback_prefix}_{item['id']}")
        row.append(button)
        if len(row) == items_per_row:
            keyboard.append(row)
            row = []
    if row: # Add any remaining buttons
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 عودة", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_question_count_keyboard(max_questions: int):
    """Creates keyboard to select number of questions."""
    keyboard = []
    options = [10, 20, 30]
    row = []
    for count in options:
        if count <= max_questions:
            row.append(InlineKeyboardButton(str(count), callback_data=f"quiz_count_{count}"))
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 عودة", callback_data="quiz_cancel_count")]) # Generic cancel
    return InlineKeyboardMarkup(keyboard)

def create_quiz_keyboard(question_data):
    """Creates the keyboard for a quiz question, handling text and image options."""
    options = [
        question_data.get("option1"), question_data.get("option2"),
        question_data.get("option3"), question_data.get("option4")
    ]
    images = [
        question_data.get("option1_image"), question_data.get("option2_image"),
        question_data.get("option3_image"), question_data.get("option4_image")
    ]

    keyboard_buttons = []
    for i, (text, img_url) in enumerate(zip(options, images)):
        button_text = f"{i+1}. "
        if text:
            button_text += text
        elif img_url:
            button_text += "(صورة)"
        else:
            # Skip option if both text and image are missing
            logger.warning(f"[DIAG] Option {i+1} for question {question_data.get('question_id')} has no text or image. Skipping button.")
            continue
        keyboard_buttons.append(InlineKeyboardButton(button_text, callback_data=f"quiz_answer_{i}"))

    # Arrange buttons, 2 per row
    keyboard = []
    for i in range(0, len(keyboard_buttons), 2):
        keyboard.append(keyboard_buttons[i:i+2])

    # Add Skip and End buttons
    keyboard.append([
        InlineKeyboardButton("⏭️ تخطي السؤال", callback_data="quiz_skip"),
        InlineKeyboardButton("🛑 إنهاء الاختبار", callback_data="quiz_end")
    ])
    return InlineKeyboardMarkup(keyboard)

# --- Command Handlers ---

def start(update: Update, context: CallbackContext) -> int:
    """Sends a welcome message and the main menu."""
    user = update.effective_user
    user_id = user.id
    user_name = get_user_name(user)
    logger.info(f"[DIAG] Received /start command from user {user_id} ({user_name}).")

    # Register or update user in DB
    if QUIZ_DB:
        logger.debug(f"[DIAG] Attempting to register/update user {user_id} in DB.")
        try:
            QUIZ_DB.register_user(user_id, user.first_name, user.username)
            logger.info(f"[DIAG] User {user_id} registered/updated successfully.")
        except Exception as db_error:
            logger.error(f"[DIAG] Database error during user registration for {user_id}: {db_error}")
            # Continue without blocking, but log the error
    else:
        logger.warning(f"[DIAG] QUIZ_DB not initialized. Cannot register user {user_id}.")

    welcome_message = f"👋 أهلاً بك يا {user_name} في بوت الكيمياء التعليمي!\n\n"
    welcome_message += "استخدم الأزرار أدناه للتنقل بين الأقسام المختلفة."

    keyboard = create_main_menu_keyboard(user_id)
    logger.debug(f"[DIAG] Sending welcome message and main menu to user {user_id}.")
    if update.message:
        update.message.reply_text(welcome_message, reply_markup=keyboard)
    elif update.callback_query: # Handle if /start is called from a callback (e.g., after ending quiz)
        update.callback_query.edit_message_text(welcome_message, reply_markup=keyboard)
    return MAIN_MENU

def about_callback(update: Update, context: CallbackContext) -> int:
    """Displays information about the bot."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requested 'About'.")
    about_text = (
        "🤖 **بوت الكيمياء التعليمي** 🧪\n\n"
        "هذا البوت مصمم لمساعدتك في تعلم الكيمياء من خلال:
"
        "*   📚 **المعلومات الكيميائية:** استعراض المقررات والمفاهيم.
"
        "*   📝 **الاختبارات:** اختبار معلوماتك في مواضيع مختلفة.
"
        "*   📊 **تقارير الأداء:** متابعة نتائج اختباراتك.
\n"
        "تم تطوير هذا البوت بواسطة [اذكر اسم المطور أو الجهة هنا].
"
        "نتمنى لك رحلة تعليمية ممتعة ومفيدة!"
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]])
    query.edit_message_text(text=about_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    return MAIN_MENU

def main_menu_callback(update: Update, context: CallbackContext) -> int:
    """Returns user to the main menu."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id} returned to main menu.")
    keyboard = create_main_menu_keyboard(user_id)
    query.edit_message_text(text="🏠 القائمة الرئيسية: اختر أحد الخيارات.", reply_markup=keyboard)
    return MAIN_MENU

# --- Info Menu Handlers ---

def menu_info_callback(update: Update, context: CallbackContext) -> int:
    """Handles 'Chemical Information' button press. Fetches and displays courses."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id} selected Chemical Information menu.")

    # Fetch courses from API
    courses_data = fetch_from_api("/api/v1/courses")

    if courses_data == "TIMEOUT":
        query.edit_message_text(text="⏳ حدث خطأ أثناء جلب قائمة المقررات (مهلة زمنية). الرجاء المحاولة مرة أخرى لاحقاً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]]))
        return MAIN_MENU
    elif courses_data and isinstance(courses_data, list):
        if not courses_data:
             query.edit_message_text(text="لا توجد مقررات متاحة حالياً لعرض المعلومات.",
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]]))
             return MAIN_MENU

        info_text = "📚 **المعلومات الكيميائية**\n\nاختر المقرر لعرض محتوياته (الوحدات والدروس):\n\n"
        for course in courses_data:
            info_text += f"📄 {course.get('name', 'مقرر غير مسمى')}\n" # Simple list for now

        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]])
        query.edit_message_text(text=info_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        return INFO_MENU # Stay in INFO_MENU or return MAIN_MENU if no further action
    else:
        query.edit_message_text(text="⚠️ حدث خطأ أثناء جلب قائمة المقررات. الرجاء المحاولة مرة أخرى لاحقاً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]]))
        return MAIN_MENU

# --- Reports Menu Handlers ---

def menu_reports_callback(update: Update, context: CallbackContext) -> int:
    """Handles 'Performance Reports' button press. Fetches and displays user stats."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requested Performance Reports.")

    if not QUIZ_DB:
        query.edit_message_text(text="⚠️ عذراً، لا يمكن الوصول إلى قاعدة البيانات حالياً لعرض التقارير.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]]))
        return MAIN_MENU

    try:
        stats = QUIZ_DB.get_user_stats(user_id)
        if stats:
            report_text = "📊 **تقرير الأداء الخاص بك**\n\n"
            report_text += f"*   عدد الاختبارات المكتملة: {stats.get('total_quizzes', 0)}\n"
            report_text += f"*   متوسط النتيجة: {stats.get('average_score', 0):.1f}%\n"
            report_text += f"*   إجمالي الأسئلة المجابة: {stats.get('total_answered', 0)}\n"
            report_text += f"*   الإجابات الصحيحة: {stats.get('total_correct', 0)}\n"
            report_text += f"*   الإجابات الخاطئة: {stats.get('total_incorrect', 0)}\n"
            report_text += f"*   الأسئلة المتخطاة: {stats.get('total_skipped', 0)}\n"
            # Consider adding stats per course/unit/lesson if available
        else:
            report_text = "📊 لا توجد لديك نتائج اختبارات سابقة لعرضها."

        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]])
        query.edit_message_text(text=report_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        return SHOWING_REPORTS # Or return MAIN_MENU

    except Exception as e:
        logger.error(f"Error fetching/displaying reports for user {user_id}: {e}")
        query.edit_message_text(text="⚠️ حدث خطأ أثناء جلب تقارير الأداء. الرجاء المحاولة مرة أخرى لاحقاً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]]))
        return MAIN_MENU

# --- Quiz Menu Navigation and Setup ---

def menu_quiz_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    keyboard = create_quiz_menu_keyboard()
    query.edit_message_text(text="📝 قائمة الاختبارات: اختر نوع الاختبار.", reply_markup=keyboard)
    return QUIZ_MENU

def quiz_select_course_callback(update: Update, context: CallbackContext) -> int:
    """Handles 'Test by Course' button press. Fetches and displays courses."""
    query = update.callback_query
    query.answer()
    logger.info(f"User {update.effective_user.id} selected Quiz by Course.")

    courses_data = fetch_from_api("/api/v1/courses")

    if courses_data == "TIMEOUT":
        query.edit_message_text(text="⏳ حدث خطأ أثناء جلب قائمة المقررات (مهلة زمنية). الرجاء المحاولة مرة أخرى لاحقاً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data="menu_quiz")]]))
        return QUIZ_MENU
    elif courses_data and isinstance(courses_data, list):
        if not courses_data:
             query.edit_message_text(text="لا توجد مقررات متاحة حالياً للاختبار.",
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data="menu_quiz")]]))
             return QUIZ_MENU
        keyboard = create_dynamic_keyboard(courses_data, "quiz_course", "menu_quiz") # prefix 'quiz_course_'
        query.edit_message_text(text="📄 اختر المقرر لبدء الاختبار:", reply_markup=keyboard)
        return SELECT_COURSE_FOR_QUIZ
    else:
        query.edit_message_text(text="⚠️ حدث خطأ أثناء جلب قائمة المقررات. الرجاء المحاولة مرة أخرى لاحقاً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data="menu_quiz")]]))
        return QUIZ_MENU

def quiz_select_unit_callback(update: Update, context: CallbackContext) -> int:
    """Handles course selection. Fetches and displays units for the selected course."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    course_id = query.data.split("_")[-1]
    logger.info(f"User {user_id} selected course {course_id} for quiz.")

    # Store selected course ID temporarily
    context.user_data["quiz_selection"] = {"type": "unit", "course_id": course_id}

    # Fetch units for the course - **ASSUMED ENDPOINT**
    units_data = fetch_from_api(f"/api/v1/courses/{course_id}/units")

    if units_data == "TIMEOUT":
        query.edit_message_text(text="⏳ حدث خطأ أثناء جلب قائمة الوحدات (مهلة زمنية). الرجاء المحاولة مرة أخرى لاحقاً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لاختيار المقرر", callback_data="quiz_select_course")]]))
        return SELECT_COURSE_FOR_QUIZ
    elif units_data and isinstance(units_data, list):
        if not units_data:
             query.edit_message_text(text=f"لا توجد وحدات متاحة حالياً لهذا المقرر.",
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لاختيار المقرر", callback_data="quiz_select_course")]]))
             return SELECT_COURSE_FOR_QUIZ
        keyboard = create_dynamic_keyboard(units_data, "quiz_unit", "quiz_select_course") # prefix 'quiz_unit_'
        query.edit_message_text(text="📁 اختر الوحدة لبدء الاختبار:", reply_markup=keyboard)
        return SELECT_UNIT_FOR_QUIZ
    else:
        query.edit_message_text(text="⚠️ حدث خطأ أثناء جلب قائمة الوحدات. الرجاء المحاولة مرة أخرى لاحقاً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لاختيار المقرر", callback_data="quiz_select_course")]]))
        return SELECT_COURSE_FOR_QUIZ

def quiz_select_lesson_callback(update: Update, context: CallbackContext) -> int:
    """Handles unit selection. Fetches and displays lessons for the selected unit."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    unit_id = query.data.split("_")[-1]
    logger.info(f"User {user_id} selected unit {unit_id} for quiz.")

    # Retrieve course_id stored earlier
    quiz_selection = context.user_data.get("quiz_selection", {})
    course_id = quiz_selection.get("course_id")
    if not course_id:
        logger.error(f"User {user_id} reached lesson selection without course_id in user_data.")
        query.edit_message_text(text="⚠️ حدث خطأ داخلي. الرجاء البدء من قائمة الاختبارات مرة أخرى.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data="menu_quiz")]]))
        return QUIZ_MENU

    # Store selected unit ID
    quiz_selection["type"] = "lesson"
    quiz_selection["unit_id"] = unit_id

    # Fetch lessons for the unit - **ASSUMED ENDPOINT**
    lessons_data = fetch_from_api(f"/api/v1/units/{unit_id}/lessons")

    # Back button should go back to unit selection for the *same course*
    back_to_units_cb = f"quiz_course_{course_id}" # Simulate clicking the course again

    if lessons_data == "TIMEOUT":
        query.edit_message_text(text="⏳ حدث خطأ أثناء جلب قائمة الدروس (مهلة زمنية). الرجاء المحاولة مرة أخرى لاحقاً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لاختيار الوحدة", callback_data=back_to_units_cb)]]))
        return SELECT_UNIT_FOR_QUIZ
    elif lessons_data and isinstance(lessons_data, list):
        if not lessons_data:
             query.edit_message_text(text=f"لا توجد دروس متاحة حالياً لهذه الوحدة.",
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لاختيار الوحدة", callback_data=back_to_units_cb)]]))
             return SELECT_UNIT_FOR_QUIZ
        keyboard = create_dynamic_keyboard(lessons_data, "quiz_lesson", back_to_units_cb) # prefix 'quiz_lesson_'
        query.edit_message_text(text="📖 اختر الدرس لبدء الاختبار:", reply_markup=keyboard)
        return SELECT_LESSON_FOR_QUIZ_HIERARCHY
    else:
        query.edit_message_text(text="⚠️ حدث خطأ أثناء جلب قائمة الدروس. الرجاء المحاولة مرة أخرى لاحقاً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لاختيار الوحدة", callback_data=back_to_units_cb)]]))
        return SELECT_UNIT_FOR_QUIZ

# --- Select Question Count --- NEW STEP ---

def select_question_count_entry(update: Update, context: CallbackContext, quiz_type: str, item_id: int | None = None) -> int:
    """Generic function to enter the question count selection state."""
    query = update.callback_query
    user_id = update.effective_user.id
    logger.info(f"User {user_id} entered question count selection. Type: {quiz_type}, ID: {item_id}")

    # Determine API endpoint and parameters based on quiz type
    endpoint = None
    params = {"count_only": "true"} # Ask API just for the count
    back_cb = "menu_quiz" # Default back button

    if quiz_type == "random":
        endpoint = "/api/v1/questions/all_count" # Hypothetical endpoint for total count
        # If no dedicated count endpoint, we'd have to fetch all courses, then counts per course
    elif quiz_type == "course" and item_id is not None:
        endpoint = f"/api/v1/courses/{item_id}/questions"
        back_cb = "quiz_select_course"
    elif quiz_type == "unit" and item_id is not None:
        endpoint = f"/api/v1/units/{item_id}/questions"
        quiz_selection = context.user_data.get("quiz_selection", {})
        course_id = quiz_selection.get("course_id")
        if course_id: back_cb = f"quiz_course_{course_id}"
    elif quiz_type == "lesson" and item_id is not None:
        endpoint = f"/api/v1/lessons/{item_id}/questions"
        quiz_selection = context.user_data.get("quiz_selection", {})
        unit_id = quiz_selection.get("unit_id")
        if unit_id: back_cb = f"quiz_unit_{unit_id}"

    if not endpoint:
        logger.error(f"Could not determine endpoint for question count. Type: {quiz_type}, ID: {item_id}")
        text = "⚠️ حدث خطأ داخلي. لا يمكن تحديد عدد الأسئلة المتاحة."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data="menu_quiz")]])
        if query: query.edit_message_text(text=text, reply_markup=kb)
        return QUIZ_MENU

    # Fetch total available questions count
    count_data = fetch_from_api(endpoint, params=params)
    max_questions = 0
    if isinstance(count_data, dict) and isinstance(count_data.get("count"), int):
        max_questions = count_data["count"]
    elif count_data == "TIMEOUT":
        text = "⏳ حدث خطأ أثناء جلب عدد الأسئلة المتاحة (مهلة زمنية)."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data=back_cb)]])
        if query: query.edit_message_text(text=text, reply_markup=kb)
        return ConversationHandler.END # Or back to previous menu
    else:
        # Fallback: If count endpoint fails or doesn't exist, fetch a limited number and use that count
        logger.warning(f"Failed to get count from {endpoint}. Fetching limited questions to estimate max.")
        fallback_params = {"limit": 50} # Fetch up to 50 to estimate
        questions_data = fetch_from_api(endpoint.replace("/all_count", ""), params=fallback_params)
        if isinstance(questions_data, list):
            max_questions = len(questions_data)
        else:
            max_questions = 0 # Cannot determine max
            logger.error(f"Failed to fetch count or estimate max questions from {endpoint}.")
            text = "⚠️ حدث خطأ أثناء جلب عدد الأسئلة المتاحة."
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data=back_cb)]])
            if query: query.edit_message_text(text=text, reply_markup=kb)
            return ConversationHandler.END # Or back to previous menu

    if max_questions == 0:
        text = "⚠️ لا توجد أسئلة متاحة لهذا الاختيار حالياً."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data=back_cb)]])
        if query: query.edit_message_text(text=text, reply_markup=kb)
        return ConversationHandler.END # Or back to previous menu

    # Store context for starting the quiz later
    context.user_data["quiz_start_context"] = {
        "type": quiz_type,
        "id": item_id,
        "max_questions": max_questions,
        "back_callback": back_cb
    }

    text = f"🔢 كم عدد الأسئلة التي ترغب في اختبارها؟ (الحد الأقصى المتاح: {max_questions})\n\n"
    text += "اختر من الأزرار أدناه أو اكتب العدد المطلوب:"
    keyboard = create_question_count_keyboard(max_questions)

    if query:
        query.answer()
        query.edit_message_text(text=text, reply_markup=keyboard)
    else: # Should not happen if entry is via callback
        update.message.reply_text(text=text, reply_markup=keyboard)

    return SELECT_QUESTION_COUNT

def handle_question_count_callback(update: Update, context: CallbackContext) -> int:
    """Handles button press for selecting question count."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id} selected question count via button: {query.data}")

    if query.data == "quiz_cancel_count":
        # Generic cancel, use back_callback stored in context
        quiz_start_context = context.user_data.get("quiz_start_context", {})
        back_cb = quiz_start_context.get("back_callback", "menu_quiz")
        logger.info(f"User {user_id} cancelled question count selection. Returning to {back_cb}")
        # Need to manually call the handler for the back_cb state
        if back_cb == "menu_quiz": return menu_quiz_callback(update, context)
        if back_cb == "quiz_select_course": return quiz_select_course_callback(update, context)
        # Add similar calls for unit/lesson selection if needed
        # For now, fallback to main menu if specific back handler isn't simple
        logger.warning(f"Unhandled back_callback '{back_cb}' in handle_question_count_callback. Returning to main menu.")
        return main_menu_callback(update, context)

    try:
        count = int(query.data.split("_")[-1])
        quiz_start_context = context.user_data.get("quiz_start_context")
        if not quiz_start_context:
            raise ValueError("Missing quiz start context")
        max_q = quiz_start_context.get("max_questions", 0)

        if 1 <= count <= max_q:
            logger.info(f"User {user_id} selected {count} questions.")
            quiz_start_context["count"] = count
            # Proceed to start quiz
            return start_quiz(update, context)
        else:
            logger.warning(f"User {user_id} selected invalid count {count} via button (max: {max_q}).")
            query.edit_message_text(
                text=f"❌ العدد غير صالح. الحد الأقصى هو {max_q}.\n\nاختر من الأزرار أو اكتب العدد:",
                reply_markup=create_question_count_keyboard(max_q)
            )
            return SELECT_QUESTION_COUNT

    except (ValueError, IndexError, TypeError) as e:
        logger.error(f"Error parsing question count callback data '{query.data}': {e}")
        quiz_start_context = context.user_data.get("quiz_start_context", {})
        back_cb = quiz_start_context.get("back_callback", "menu_quiz")
        query.edit_message_text(
            text="⚠️ حدث خطأ أثناء معالجة اختيارك. الرجاء المحاولة مرة أخرى.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data=back_cb)]])
        )
        # Determine correct return state based on back_cb
        if back_cb == "menu_quiz": return QUIZ_MENU
        if back_cb == "quiz_select_course": return SELECT_COURSE_FOR_QUIZ
        # Add others if needed
        return QUIZ_MENU # Fallback

def handle_question_count_message(update: Update, context: CallbackContext) -> int:
    """Handles user typing the question count."""
    user_id = update.effective_user.id
    text = update.message.text
    logger.info(f"User {user_id} typed question count: {text}")

    quiz_start_context = context.user_data.get("quiz_start_context")
    if not quiz_start_context:
        logger.warning(f"User {user_id} sent message '{text}' in SELECT_QUESTION_COUNT state but context is missing.")
        update.message.reply_text("⚠️ حدث خطأ. الرجاء البدء من قائمة الاختبارات مرة أخرى.")
        return main_menu_callback(update, context)

    max_q = quiz_start_context.get("max_questions", 0)
    back_cb = quiz_start_context.get("back_callback", "menu_quiz")

    try:
        count = int(text)
        if 1 <= count <= max_q:
            logger.info(f"User {user_id} selected {count} questions by typing.")
            quiz_start_context["count"] = count
            # Proceed to start quiz
            return start_quiz(update, context)
        else:
            logger.warning(f"User {user_id} typed invalid count {count} (max: {max_q}).")
            update.message.reply_text(
                text=f"❌ العدد غير صالح. الحد الأقصى هو {max_q}.\n\nاختر من الأزرار أو اكتب العدد الصحيح:",
                reply_markup=create_question_count_keyboard(max_q)
            )
            return SELECT_QUESTION_COUNT
    except ValueError:
        logger.warning(f"User {user_id} typed non-integer '{text}' for question count.")
        update.message.reply_text(
            text=f"❌ الرجاء إدخال رقم صحيح بين 1 و {max_q}.\n\nاختر من الأزرار أو اكتب العدد الصحيح:",
            reply_markup=create_question_count_keyboard(max_q)
        )
        return SELECT_QUESTION_COUNT

# --- Quiz Start Logic ---

def quiz_type_random_callback(update: Update, context: CallbackContext) -> int:
    """Handles 'Random Quiz' button press. Enters question count selection."""
    return select_question_count_entry(update, context, quiz_type="random")

def quiz_course_selected_callback(update: Update, context: CallbackContext) -> int:
    """Handles course selection for quiz. Enters question count selection."""
    course_id = int(update.callback_query.data.split("_")[-1])
    return select_question_count_entry(update, context, quiz_type="course", item_id=course_id)

def quiz_unit_selected_callback(update: Update, context: CallbackContext) -> int:
    """Handles unit selection for quiz. Enters question count selection."""
    unit_id = int(update.callback_query.data.split("_")[-1])
    return select_question_count_entry(update, context, quiz_type="unit", item_id=unit_id)

def quiz_lesson_selected_callback(update: Update, context: CallbackContext) -> int:
    """Handles lesson selection for quiz. Enters question count selection."""
    lesson_id = int(update.callback_query.data.split("_")[-1])
    return select_question_count_entry(update, context, quiz_type="lesson", item_id=lesson_id)

def start_quiz(update: Update, context: CallbackContext) -> int:
    """Fetches questions based on context and starts the quiz."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    quiz_start_context = context.user_data.get("quiz_start_context")

    if not quiz_start_context or "count" not in quiz_start_context:
        logger.error(f"User {user_id} reached start_quiz without complete context.")
        text = "⚠️ حدث خطأ داخلي أثناء بدء الاختبار. الرجاء المحاولة مرة أخرى."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data="menu_quiz")]])
        if update.callback_query: update.callback_query.edit_message_text(text=text, reply_markup=kb)
        elif update.message: update.message.reply_text(text=text, reply_markup=kb)
        return QUIZ_MENU

    quiz_type = quiz_start_context["type"]
    item_id = quiz_start_context.get("id")
    num_questions = quiz_start_context["count"]
    back_cb = quiz_start_context.get("back_callback", "menu_quiz")

    logger.info(f"Starting quiz for user {user_id}. Type: {quiz_type}, ID: {item_id}, Count: {num_questions}")

    # --- Fetch Questions from API --- 
    questions = []
    endpoint = None
    params = {"limit": num_questions} # API should handle random selection if needed

    if quiz_type == "random":
        # Fetch questions from all courses
        logger.info("[DIAG] Fetching all courses to get questions for random quiz...")
        all_courses_data = fetch_from_api("/api/v1/courses")
        all_questions_raw = []
        if isinstance(all_courses_data, list):
            for course in all_courses_data:
                course_id = course.get('id')
                if course_id:
                    logger.info(f"[DIAG] Fetching questions for course {course_id}...")
                    # Fetch more than needed per course initially to ensure variety
                    course_q_data = fetch_from_api(f"/api/v1/courses/{course_id}/questions", params={"limit": num_questions * 2})
                    if isinstance(course_q_data, list):
                        all_questions_raw.extend(course_q_data)
                    elif course_q_data == "TIMEOUT":
                         logger.warning(f"[DIAG] Timeout fetching questions for course {course_id}.")
                    else:
                         logger.warning(f"[DIAG] Failed to fetch questions for course {course_id}.")
            logger.info(f"[DIAG] Fetched {len(all_questions_raw)} raw questions total for random quiz.")
            if len(all_questions_raw) >= num_questions:
                # Select the required number randomly from the combined list
                selected_raw_questions = random.sample(all_questions_raw, num_questions)
                logger.info(f"[DIAG] Randomly selected {num_questions} questions.")
                # Transform selected questions
                for q_data in selected_raw_questions:
                    transformed_q = transform_api_question(q_data)
                    if transformed_q:
                        questions.append(transformed_q)
                logger.info(f"[DIAG] Transformed {len(questions)} questions successfully.")
            else:
                 logger.warning(f"[DIAG] Not enough total questions ({len(all_questions_raw)}) found across all courses for requested count {num_questions}. Using all available.")
                 # Use all available questions if less than requested
                 num_questions = len(all_questions_raw)
                 for q_data in all_questions_raw:
                    transformed_q = transform_api_question(q_data)
                    if transformed_q:
                        questions.append(transformed_q)

        elif all_courses_data == "TIMEOUT":
             logger.error("[DIAG] Timeout fetching course list for random quiz.")
             questions = "TIMEOUT"
        else:
             logger.error("[DIAG] Failed to fetch course list for random quiz.")
             questions = None # Indicate error

    elif quiz_type == "course" and item_id is not None:
        endpoint = f"/api/v1/courses/{item_id}/questions"
    elif quiz_type == "unit" and item_id is not None:
        endpoint = f"/api/v1/units/{item_id}/questions"
    elif quiz_type == "lesson" and item_id is not None:
        endpoint = f"/api/v1/lessons/{item_id}/questions"

    # Fetch for specific course/unit/lesson if not random
    if endpoint:
        logger.info(f"[DIAG] Fetching {num_questions} questions from endpoint: {endpoint}")
        questions_data = fetch_from_api(endpoint, params=params)
        if questions_data == "TIMEOUT":
            questions = "TIMEOUT"
        elif isinstance(questions_data, list):
            for q_data in questions_data:
                transformed_q = transform_api_question(q_data)
                if transformed_q:
                    questions.append(transformed_q)
            # Adjust num_questions if API returned fewer than requested
            if len(questions) < num_questions:
                logger.warning(f"API returned {len(questions)} questions, less than requested {num_questions}. Adjusting count.")
                num_questions = len(questions)
        else:
            questions = None # Indicate error

    # --- Handle API Fetch Results --- 
    if questions == "TIMEOUT":
        text = "⏳ حدث خطأ أثناء جلب أسئلة الاختبار (مهلة زمنية). الرجاء المحاولة مرة أخرى لاحقاً."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data=back_cb)]])
        if update.callback_query: update.callback_query.edit_message_text(text=text, reply_markup=kb)
        elif update.message: update.message.reply_text(text=text, reply_markup=kb)
        # Determine correct return state based on back_cb
        if back_cb == "menu_quiz": return QUIZ_MENU
        if back_cb == "quiz_select_course": return SELECT_COURSE_FOR_QUIZ
        # Add others if needed
        return QUIZ_MENU # Fallback

    if not questions: # Covers None or empty list
        logger.error(f"Failed to fetch or transform questions for quiz. Type: {quiz_type}, ID: {item_id}")
        text = "⚠️ حدث خطأ أثناء جلب أسئلة الاختبار أو لا توجد أسئلة متاحة لهذا الاختيار. الرجاء المحاولة مرة أخرى لاحقاً."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data=back_cb)]])
        if update.callback_query: update.callback_query.edit_message_text(text=text, reply_markup=kb)
        elif update.message: update.message.reply_text(text=text, reply_markup=kb)
        # Determine correct return state based on back_cb
        if back_cb == "menu_quiz": return QUIZ_MENU
        if back_cb == "quiz_select_course": return SELECT_COURSE_FOR_QUIZ
        # Add others if needed
        return QUIZ_MENU # Fallback

    # --- Initialize Quiz State --- 
    quiz_id = int(time.time() * 1000) # Unique enough ID
    quiz_data = {
        "quiz_id": quiz_id,
        "questions": questions,
        "current_question_index": 0,
        "answers": {},
        "score": 0,
        "start_time": time.time(),
        "num_questions": num_questions, # Use potentially adjusted number
        "quiz_type": quiz_type,
        "item_id": item_id,
        "timed_out": False,
        "quiz_timer_job_name": None, # For overall timer (unused)
        "question_timer_job_name": None # For per-question timer
    }
    context.user_data["current_quiz"] = quiz_data
    logger.info(f"Quiz {quiz_id} initialized for user {user_id} with {num_questions} questions.")

    # Set overall quiz timer (currently disabled)
    # quiz_data["quiz_timer_job_name"] = set_quiz_timer(context, chat_id, user_id, quiz_id, DEFAULT_QUIZ_DURATION_MINUTES)

    # Send the first question
    return send_question(update, context)

# --- Quiz Taking Handlers ---

def send_question(update: Update, context: CallbackContext) -> int:
    """Sends the current question to the user."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    quiz_data = context.user_data.get("current_quiz")

    if not quiz_data or quiz_data.get("timed_out"):
        logger.warning(f"send_question called for user {user_id} but no active quiz found or quiz timed out.")
        # Clean up just in case
        if "current_quiz" in context.user_data: del context.user_data["current_quiz"]
        safe_send_message(context.bot, chat_id, "⚠️ لا يوجد اختبار نشط حالياً.")
        return main_menu_callback(update, context) # Go to main menu

    q_index = quiz_data["current_question_index"]
    total_q = quiz_data["num_questions"]

    if q_index >= total_q:
        logger.info(f"Quiz {quiz_data['quiz_id']} finished for user {user_id}. Showing results.")
        return show_results(chat_id, user_id, quiz_data["quiz_id"], context)

    question = quiz_data["questions"][q_index]
    question_text = question.get("question_text", "")
    image_url = question.get("image_url")

    # Add question number
    display_text = f"**السؤال {q_index + 1} من {total_q}:**\n\n{question_text}"

    keyboard = create_quiz_keyboard(question)

    message_id_to_edit = None
    if update.callback_query:
        message_id_to_edit = update.callback_query.message.message_id

    sent_message = None
    try:
        if image_url:
            logger.debug(f"[DIAG] Sending question {q_index+1} with image: {image_url}")
            # If editing, delete old message first if it didn't have an image
            if message_id_to_edit and not update.callback_query.message.photo:
                try: context.bot.delete_message(chat_id, message_id_to_edit)
                except Exception: pass # Ignore if deletion fails
                message_id_to_edit = None # Send as new message

            if message_id_to_edit:
                 # Try editing media - might fail if content type changes drastically
                 try:
                     sent_message = context.bot.edit_message_media(
                         chat_id=chat_id,
                         message_id=message_id_to_edit,
                         media=InputMediaPhoto(media=image_url, caption=display_text, parse_mode=ParseMode.MARKDOWN),
                         reply_markup=keyboard
                     )
                     logger.debug("[DIAG] Edited message with new image.")
                 except BadRequest as e:
                     logger.warning(f"[DIAG] Failed to edit media (likely content type change): {e}. Sending as new message.")
                     try: context.bot.delete_message(chat_id, message_id_to_edit)
                     except Exception: pass
                     sent_message = context.bot.send_photo(chat_id, photo=image_url, caption=display_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
            else:
                sent_message = context.bot.send_photo(chat_id, photo=image_url, caption=display_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
                logger.debug("[DIAG] Sent new message with image.")
        else:
            logger.debug(f"[DIAG] Sending question {q_index+1} without image.")
            # If editing, delete old message first if it had an image
            if message_id_to_edit and update.callback_query.message.photo:
                try: context.bot.delete_message(chat_id, message_id_to_edit)
                except Exception: pass
                message_id_to_edit = None # Send as new message

            if message_id_to_edit:
                sent_message = context.bot.edit_message_text(text=display_text, chat_id=chat_id, message_id=message_id_to_edit, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
                logger.debug("[DIAG] Edited message text.")
            else:
                sent_message = context.bot.send_message(chat_id, text=display_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
                logger.debug("[DIAG] Sent new message text.")

        # Store the ID of the message displaying the question
        if sent_message:
            quiz_data["last_question_message_id"] = sent_message.message_id

        # Set the timer for this question
        quiz_data["question_timer_job_name"] = set_question_timer(context, chat_id, user_id, quiz_data["quiz_id"], q_index)

    except BadRequest as e:
        logger.error(f"Telegram BadRequest sending question {q_index + 1} for user {user_id}: {e}")
        # Attempt to send a simpler error message
        safe_send_message(context.bot, chat_id, "⚠️ حدث خطأ أثناء عرض السؤال. قد يكون السبب تنسيق النص أو الصورة. سيتم تخطي هذا السؤال.")
        # Skip the problematic question
        quiz_data["answers"][q_index] = {"selected": -1, "correct": -2, "time": 0} # Mark as error
        quiz_data["current_question_index"] += 1
        # Use job_queue to send next question slightly later to avoid race conditions
        context.job_queue.run_once(lambda ctx: send_question(update, ctx), 0.5, context=context)
    except TimedOut:
        logger.error(f"Telegram TimedOut sending question {q_index + 1} for user {user_id}.")
        safe_send_message(context.bot, chat_id, "⏳ حدث خطأ في الاتصال مع تليجرام أثناء إرسال السؤال. يرجى المحاولة مرة أخرى لاحقاً.")
        # End the quiz prematurely on timeout
        return show_results(chat_id, user_id, quiz_data["quiz_id"], context, error_occurred=True)
    except Exception as e:
        logger.exception(f"Unexpected error sending question {q_index + 1} for user {user_id}: {e}")
        safe_send_message(context.bot, chat_id, "⚠️ حدث خطأ غير متوقع أثناء عرض السؤال. سيتم إنهاء الاختبار.")
        return show_results(chat_id, user_id, quiz_data["quiz_id"], context, error_occurred=True)

    return TAKING_QUIZ

def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    """Handles user's answer selection during a quiz."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    quiz_data = context.user_data.get("current_quiz")

    if not quiz_data or quiz_data.get("timed_out"):
        logger.warning(f"handle_quiz_answer called for user {user_id} but no active quiz found or quiz timed out.")
        query.edit_message_text("⚠️ لا يوجد اختبار نشط حالياً أو انتهى وقته.")
        if "current_quiz" in context.user_data: del context.user_data["current_quiz"]
        return MAIN_MENU

    # Stop the question timer
    if quiz_data.get("question_timer_job_name"):
        remove_job_if_exists(quiz_data["question_timer_job_name"], context)
        quiz_data["question_timer_job_name"] = None

    try:
        selected_option_index = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data received for quiz answer: {query.data}")
        query.edit_message_text("⚠️ حدث خطأ في قراءة إجابتك. الرجاء المحاولة مرة أخرى.")
        # Resend the same question without penalty? Or skip?
        # For now, just stay in the quiz state
        return TAKING_QUIZ

    q_index = quiz_data["current_question_index"]
    question = quiz_data["questions"][q_index]
    correct_option_index = question["correct_answer"]

    is_correct = (selected_option_index == correct_option_index)
    if is_correct:
        quiz_data["score"] += 1
        feedback_text = "✅ إجابة صحيحة!"
    else:
        feedback_text = f"❌ إجابة خاطئة. الإجابة الصحيحة هي الخيار رقم {correct_option_index + 1}."

    # Store answer details
    quiz_data["answers"][q_index] = {
        "selected": selected_option_index,
        "correct": correct_option_index,
        "time": time.time() # Or calculate time taken if needed
    }

    # Show explanation if available
    explanation = question.get("explanation")
    if explanation:
        feedback_text += f"\n\n**💡 التفسير:**\n{explanation}"

    # Edit the question message to show feedback
    try:
        context.bot.edit_message_caption(
            chat_id=chat_id,
            message_id=quiz_data["last_question_message_id"],
            caption=query.message.caption + f"\n\n---\n*{feedback_text}*", # Append feedback
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=None # Remove keyboard
        ) if query.message.photo else context.bot.edit_message_text(
            text=query.message.text + f"\n\n---\n*{feedback_text}*", # Append feedback
            chat_id=chat_id,
            message_id=quiz_data["last_question_message_id"],
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=None # Remove keyboard
        )
    except BadRequest as e:
         logger.warning(f"Failed to edit message with feedback (likely no change or other issue): {e}")
         # Send feedback as a new message if editing fails
         safe_send_message(context.bot, chat_id, feedback_text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
         logger.error(f"Unexpected error editing message with feedback: {e}")
         safe_send_message(context.bot, chat_id, feedback_text, parse_mode=ParseMode.MARKDOWN)

    # Move to the next question
    quiz_data["current_question_index"] += 1

    # Use job_queue to send next question slightly later
    context.job_queue.run_once(lambda ctx: send_question(update, ctx), FEEDBACK_DELAY, context=context)

    return TAKING_QUIZ

def handle_quiz_skip(update_or_chat_id, context_or_user_id, quiz_id_if_timer=None, q_index_if_timer=None, context_if_timer=None, timed_out=False):
    """Handles skipping a question, either by user or timer."""
    is_timer_call = timed_out

    if is_timer_call:
        chat_id = update_or_chat_id
        user_id = context_or_user_id
        quiz_id = quiz_id_if_timer
        q_index = q_index_if_timer
        context = context_if_timer
        logger.info(f"Skipping question {q_index + 1} for user {user_id} due to timer.")
        # Need to get quiz_data from dispatcher
        if not hasattr(context, 'dispatcher'):
             logger.error("Dispatcher not found in context for handle_quiz_skip (timer). Cannot access user_data.")
             return TAKING_QUIZ # Or some error state
        user_data = context.dispatcher.user_data.get(user_id, {})
        quiz_data = user_data.get("current_quiz")
        # Ensure it's the correct quiz and question index
        if not quiz_data or quiz_data["quiz_id"] != quiz_id or quiz_data["current_question_index"] != q_index:
            logger.warning(f"handle_quiz_skip (timer) called for inactive/wrong quiz/question. Ignoring.")
            return TAKING_QUIZ
    else:
        # User initiated skip
        update = update_or_chat_id
        context = context_or_user_id
        query = update.callback_query
        query.answer("تم تخطي السؤال")
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        quiz_data = context.user_data.get("current_quiz")
        logger.info(f"User {user_id} skipped question {quiz_data['current_question_index'] + 1}.")

        if not quiz_data or quiz_data.get("timed_out"):
            logger.warning(f"handle_quiz_skip called by user {user_id} but no active quiz found or quiz timed out.")
            query.edit_message_text("⚠️ لا يوجد اختبار نشط حالياً أو انتهى وقته.")
            if "current_quiz" in context.user_data: del context.user_data["current_quiz"]
            return MAIN_MENU

        # Stop the question timer if user skipped
        if quiz_data.get("question_timer_job_name"):
            remove_job_if_exists(quiz_data["question_timer_job_name"], context)
            quiz_data["question_timer_job_name"] = None

    q_index = quiz_data["current_question_index"]
    question = quiz_data["questions"][q_index]
    correct_option_index = question["correct_answer"]

    # Store answer as skipped
    quiz_data["answers"][q_index] = {
        "selected": -1, # Indicate skipped
        "correct": correct_option_index,
        "time": time.time()
    }

    # Show correct answer and explanation if available
    feedback_text = f"⏭️ تم تخطي السؤال. الإجابة الصحيحة كانت الخيار رقم {correct_option_index + 1}."
    explanation = question.get("explanation")
    if explanation:
        feedback_text += f"\n\n**💡 التفسير:**\n{explanation}"

    # Edit the message or send new one with feedback
    try:
        if is_timer_call:
            # Timer call doesn't have query, send new message
            safe_send_message(context.bot, chat_id, feedback_text, parse_mode=ParseMode.MARKDOWN)
        else:
            # User call, edit existing message
            context.bot.edit_message_caption(
                chat_id=chat_id,
                message_id=quiz_data["last_question_message_id"],
                caption=query.message.caption + f"\n\n---\n*{feedback_text}*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=None
            ) if query.message.photo else context.bot.edit_message_text(
                text=query.message.text + f"\n\n---\n*{feedback_text}*",
                chat_id=chat_id,
                message_id=quiz_data["last_question_message_id"],
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=None
            )
    except BadRequest as e:
         logger.warning(f"Failed to edit message with skip feedback: {e}")
         safe_send_message(context.bot, chat_id, feedback_text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
         logger.error(f"Unexpected error editing/sending skip feedback: {e}")
         safe_send_message(context.bot, chat_id, feedback_text, parse_mode=ParseMode.MARKDOWN)

    # Move to the next question
    quiz_data["current_question_index"] += 1

    # Use job_queue to send next question slightly later
    delay = 0.1 if is_timer_call else FEEDBACK_DELAY # Shorter delay if timer expired
    context.job_queue.run_once(lambda ctx: send_question(update if not is_timer_call else None, ctx), delay, context=context)

    return TAKING_QUIZ

def handle_quiz_end(update: Update, context: CallbackContext) -> int:
    """Handles user pressing the 'End Quiz' button."""
    query = update.callback_query
    query.answer("إنهاء الاختبار...")
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    quiz_data = context.user_data.get("current_quiz")

    logger.info(f"User {user_id} requested to end quiz {quiz_data.get('quiz_id') if quiz_data else 'N/A'}.")

    if not quiz_data or quiz_data.get("timed_out"):
        logger.warning(f"handle_quiz_end called by user {user_id} but no active quiz found or quiz timed out.")
        query.edit_message_text("⚠️ لا يوجد اختبار نشط حالياً أو انتهى وقته.")
        if "current_quiz" in context.user_data: del context.user_data["current_quiz"]
        return MAIN_MENU

    # Stop timers
    if quiz_data.get("quiz_timer_job_name"):
        remove_job_if_exists(quiz_data["quiz_timer_job_name"], context)
    if quiz_data.get("question_timer_job_name"):
        remove_job_if_exists(quiz_data["question_timer_job_name"], context)

    # Mark remaining questions as skipped (optional, but good for stats)
    q_index = quiz_data["current_question_index"]
    total_q = quiz_data["num_questions"]
    while q_index < total_q:
        if q_index not in quiz_data["answers"]:
             correct_option_index = quiz_data["questions"][q_index]["correct_answer"]
             quiz_data["answers"][q_index] = {"selected": -1, "correct": correct_option_index, "time": 0}
        q_index += 1

    # Show results
    return show_results(chat_id, user_id, quiz_data["quiz_id"], context, ended_manually=True)

# --- Show Results --- 

def show_results(chat_id, user_id, quiz_id, context, timed_out=False, ended_manually=False, error_occurred=False) -> int:
    """Calculates and displays quiz results, saves them, and cleans up."""
    logger.info(f"Showing results for quiz {quiz_id} for user {user_id}.")

    # Need user_data, get from dispatcher if called by timer
    if isinstance(context, CallbackContext) and hasattr(context, 'dispatcher'):
         user_data = context.dispatcher.user_data.get(user_id, {})
    elif isinstance(context, CallbackContext):
         user_data = context.user_data # Assume called directly by handler
    else:
         logger.error("Invalid context type in show_results. Cannot access user_data.")
         safe_send_message(context.bot, chat_id, "⚠️ حدث خطأ داخلي أثناء عرض النتائج.")
         return ConversationHandler.END # Fallback state

    quiz_data = user_data.get("current_quiz")

    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.warning(f"show_results called for quiz {quiz_id} but data not found or mismatched for user {user_id}.")
        # Avoid sending error if called after normal cleanup
        # safe_send_message(context.bot, chat_id, "⚠️ لم يتم العثور على بيانات الاختبار لعرض النتائج.")
        return MAIN_MENU # Or ConversationHandler.END

    # Stop timers just in case
    if quiz_data.get("quiz_timer_job_name"):
        remove_job_if_exists(quiz_data["quiz_timer_job_name"], context)
    if quiz_data.get("question_timer_job_name"):
        remove_job_if_exists(quiz_data["question_timer_job_name"], context)

    # Calculate results
    score = quiz_data.get("score", 0)
    answers = quiz_data.get("answers", {})
    total_questions = quiz_data.get("num_questions", 0)
    correct_answers = score
    incorrect_answers = 0
    skipped_answers = 0

    for i in range(total_questions):
        answer_info = answers.get(i)
        if answer_info:
            if answer_info["selected"] == -1: # Skipped
                skipped_answers += 1
            elif answer_info["selected"] != answer_info["correct"]:
                incorrect_answers += 1
        else:
            # Question was never reached (e.g., ended manually)
            skipped_answers += 1

    # Ensure counts add up
    # This check might be slightly off if score calculation differs
    # assert correct_answers + incorrect_answers + skipped_answers == total_questions, "Result counts don't match total questions!"

    percentage = (correct_answers / total_questions * 100) if total_questions > 0 else 0

    # Build result message
    result_message = "🏁 **نتائج الاختبار** 🏁\n\n"
    if timed_out:
        result_message += "⏰ انتهى وقت الاختبار المحدد!\n"
    elif ended_manually:
        result_message += "🛑 تم إنهاء الاختبار يدوياً.\n"
    elif error_occurred:
         result_message += "⚠️ حدث خطأ أدى إلى إنهاء الاختبار.\n"

    result_message += f"*   النتيجة: {correct_answers} من {total_questions} ({percentage:.1f}%)\n"
    result_message += f"*   الإجابات الصحيحة: {correct_answers}\n"
    result_message += f"*   الإجابات الخاطئة: {incorrect_answers}\n"
    result_message += f"*   الأسئلة المتخطاة: {skipped_answers}\n"

    # Save results to DB
    if QUIZ_DB and not error_occurred:
        logger.debug(f"Attempting to save results for quiz {quiz_id}, user {user_id}.")
        try:
            QUIZ_DB.save_quiz_result(
                user_id=user_id,
                quiz_type=quiz_data.get("quiz_type", "unknown"),
                item_id=quiz_data.get("item_id"), # Course/Unit/Lesson ID
                score=percentage,
                total_questions=total_questions,
                correct_answers=correct_answers,
                incorrect_answers=incorrect_answers,
                skipped_answers=skipped_answers,
                start_time=datetime.fromtimestamp(quiz_data.get("start_time", time.time())) # Convert to datetime
            )
            logger.info(f"Results saved successfully for quiz {quiz_id}, user {user_id}.")
        except Exception as db_error:
            logger.error(f"Database error saving results for quiz {quiz_id}, user {user_id}: {db_error}")
            result_message += "\n⚠️ *حدث خطأ أثناء حفظ نتيجتك.*"
    elif error_occurred:
         logger.warning(f"Not saving results for quiz {quiz_id} due to error_occurred flag.")
    else:
        logger.warning(f"QUIZ_DB not available. Cannot save results for quiz {quiz_id}, user {user_id}.")
        result_message += "\n⚠️ *لا يمكن حفظ نتيجتك حالياً (مشكلة في قاعدة البيانات)."*

    # Clean up quiz data from user_data
    if "current_quiz" in user_data:
        del user_data["current_quiz"]
    if "quiz_start_context" in user_data:
        del user_data["quiz_start_context"]
    if "quiz_selection" in user_data:
         del user_data["quiz_selection"]
    logger.debug(f"Cleaned up quiz data for user {user_id}.")

    # Send results and main menu keyboard
    keyboard = create_main_menu_keyboard(user_id)
    safe_send_message(context.bot, chat_id, result_message, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

    return MAIN_MENU # Return to main menu state

# --- Admin Handlers (Placeholders - Not fully implemented) ---

def admin_menu_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        query.edit_message_text("🚫 ليس لديك صلاحية الوصول لهذه القائمة.",
                                reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU

    logger.info(f"Admin {user_id} accessed admin menu.")
    keyboard = InlineKeyboardMarkup([
        # Add admin options here (e.g., manage questions, users, structure)
        [InlineKeyboardButton("📊 عرض إحصائيات عامة", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
    ])
    query.edit_message_text("⚙️ قائمة الإدارة: اختر أحد الخيارات.", reply_markup=keyboard)
    return ADMIN_MENU

def admin_stats_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        # Redundant check, but good practice
        return MAIN_MENU

    logger.info(f"Admin {user_id} requested general stats.")
    stats_text = "📊 **إحصائيات عامة (مثال):**\n\n"
    # Fetch actual stats from DB or API if implemented
    stats_text += "*   إجمالي المستخدمين: [عدد]\n"
    stats_text += "*   إجمالي الاختبارات المجراة: [عدد]\n"
    stats_text += "*   متوسط النتيجة العام: [نسبة]%\n"
    stats_text += "*   إجمالي الأسئلة في النظام: [عدد]"

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data="menu_admin")]])
    query.edit_message_text(text=stats_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    return ADMIN_MENU

# --- Error Handler ---

def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    # Optionally, inform the user about the error
    if isinstance(update, Update) and update.effective_chat:
        try:
            # Avoid sending error message for common issues like BadRequest from editing unchanged message
            if not isinstance(context.error, BadRequest) or "Message is not modified" not in str(context.error):
                 safe_send_message(context.bot, update.effective_chat.id, "⚠️ حدث خطأ ما أثناء معالجة طلبك. نعتذر عن الإزعاج.")
        except Exception as send_error:
            logger.error(f"Exception while sending error message to user: {send_error}")

# --- NEW: Catch-all handler for diagnosis ---
def handle_all_updates(update: Update, context: CallbackContext):
    """Logs any update received by the bot for diagnostic purposes."""
    update_type = "Unknown"
    user_id = "N/A"
    chat_id = "N/A"
    text = "N/A"
    callback_data = "N/A"

    if update.message:
        update_type = "Message"
        user_id = update.message.from_user.id
        chat_id = update.message.chat.id
        text = update.message.text
    elif update.callback_query:
        update_type = "CallbackQuery"
        user_id = update.callback_query.from_user.id
        chat_id = update.callback_query.message.chat.id
        callback_data = update.callback_query.data
    elif update.edited_message:
        update_type = "EditedMessage"
        user_id = update.edited_message.from_user.id
        chat_id = update.edited_message.chat.id
        text = update.edited_message.text
    # Add other update types if needed (inline query, etc.)

    logger.debug(f"[DIAG] Received Update - Type: {update_type}, User: {user_id}, Chat: {chat_id}, Text: '{text}', Callback: '{callback_data}', Full Update: {update.to_dict()}")
    # IMPORTANT: This handler should NOT return any state, otherwise it might interfere
    # with the ConversationHandler. It's purely for logging.

# --- Main Function ---

def main() -> None:
    """Start the bot."""
    logger.info("Starting bot...")

    # Create the Updater and pass it your bot's token.
    updater = Updater(BOT_TOKEN)
    logger.debug("[DIAG] Updater created.")

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher
    logger.debug("[DIAG] Dispatcher obtained.")

    # --- Add the catch-all handler FIRST (with low group number) ---
    # This ensures it logs the update before other handlers process it.
    dispatcher.add_handler(MessageHandler(Filters.all & ~Filters.command, handle_all_updates), group=-1)
    dispatcher.add_handler(CallbackQueryHandler(handle_all_updates), group=-1)
    logger.debug("[DIAG] Catch-all update logger handler added.")

    # --- Conversation Handler Setup ---
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(menu_info_callback, pattern='^menu_info$'),
                CallbackQueryHandler(menu_quiz_callback, pattern='^menu_quiz$'),
                CallbackQueryHandler(menu_reports_callback, pattern='^menu_reports$'),
                CallbackQueryHandler(about_callback, pattern='^menu_about$'),
                CallbackQueryHandler(admin_menu_callback, pattern='^menu_admin$'),
                # Allow returning to main menu from other top-level menus
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'),
            ],
            INFO_MENU: [
                # Add handlers for specific info items if needed
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'),
            ],
            SHOWING_REPORTS: [
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'),
            ],
            QUIZ_MENU: [
                CallbackQueryHandler(quiz_type_random_callback, pattern='^quiz_type_random$'),
                CallbackQueryHandler(quiz_select_course_callback, pattern='^quiz_select_course$'),
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'),
            ],
            SELECT_COURSE_FOR_QUIZ: [
                CallbackQueryHandler(quiz_course_selected_callback, pattern='^quiz_course_\d+$'),
                CallbackQueryHandler(menu_quiz_callback, pattern='^menu_quiz$'), # Back to quiz menu
            ],
            SELECT_UNIT_FOR_QUIZ: [
                CallbackQueryHandler(quiz_unit_selected_callback, pattern='^quiz_unit_\d+$'),
                CallbackQueryHandler(quiz_select_course_callback, pattern='^quiz_select_course$'), # Back to course selection
                # Allow going back further if needed
                CallbackQueryHandler(menu_quiz_callback, pattern='^menu_quiz$'),
            ],
            SELECT_LESSON_FOR_QUIZ_HIERARCHY: [
                CallbackQueryHandler(quiz_lesson_selected_callback, pattern='^quiz_lesson_\d+$'),
                # Back button logic in create_dynamic_keyboard handles going back to unit selection
                # Need handler for the callback generated by that back button ('quiz_course_<id>')
                CallbackQueryHandler(quiz_select_unit_callback, pattern='^quiz_course_\d+$'), # Goes back to units of that course
                CallbackQueryHandler(menu_quiz_callback, pattern='^menu_quiz$'), # Further back
            ],
            SELECT_QUESTION_COUNT: [
                CallbackQueryHandler(handle_question_count_callback, pattern='^quiz_count_\d+$'),
                CallbackQueryHandler(handle_question_count_callback, pattern='^quiz_cancel_count$'), # Generic cancel
                MessageHandler(Filters.regex('^\d+$'), handle_question_count_message),
                # Add handlers for the back buttons from specific levels if needed
                CallbackQueryHandler(menu_quiz_callback, pattern='^menu_quiz$'),
                CallbackQueryHandler(quiz_select_course_callback, pattern='^quiz_select_course$'),
                CallbackQueryHandler(quiz_select_unit_callback, pattern='^quiz_course_\d+$'), # Back from lesson count select
                CallbackQueryHandler(quiz_select_lesson_callback, pattern='^quiz_unit_\d+$'), # Back from lesson count select
            ],
            TAKING_QUIZ: [
                CallbackQueryHandler(handle_quiz_answer, pattern='^quiz_answer_\d$'),
                CallbackQueryHandler(handle_quiz_skip, pattern='^quiz_skip$'),
                CallbackQueryHandler(handle_quiz_end, pattern='^quiz_end$'),
            ],
            ADMIN_MENU: [
                CallbackQueryHandler(admin_stats_callback, pattern='^admin_stats$'),
                # Add other admin handlers
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'),
            ],
            # Add other states and handlers as needed (e.g., for admin functions)
        },
        fallbacks=[CommandHandler('start', start), CallbackQueryHandler(main_menu_callback, pattern='^main_menu$')],
        # Allow re-entry into the conversation with /start
        allow_reentry=True
    )
    logger.debug("[DIAG] ConversationHandler created.")

    dispatcher.add_handler(conv_handler)
    logger.debug("[DIAG] ConversationHandler added to dispatcher.")

    # Log all errors
    dispatcher.add_error_handler(error_handler)
    logger.debug("[DIAG] Error handler added.")

    # Start the Bot using webhook on Render
    logger.info(f"Starting webhook on port {PORT}...")
    updater.start_webhook(listen="0.0.0.0",
                          port=PORT,
                          url_path=BOT_TOKEN,
                          webhook_url=f"https://{APP_NAME}.onrender.com/{BOT_TOKEN}")
    logger.info(f"Webhook started. Bot should be accessible at https://{APP_NAME}.onrender.com/{BOT_TOKEN}")

    # Run the bot until you press Ctrl-C
    updater.idle()
    logger.info("Bot stopped.")

if __name__ == '__main__':
    logger.debug("[DIAG] Script execution started.")
    main()

