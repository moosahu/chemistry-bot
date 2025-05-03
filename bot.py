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
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG) # Uncomment locally for detailed logs

# Get sensitive info from environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_USER_ID = os.environ.get("ADMIN_USER_ID", "6448526509")
PORT = int(os.environ.get("PORT", 8443))
APP_NAME = os.environ.get("APP_NAME")
# Corrected API Base URL - Ensure it points to the root of the API service
API_BASE_URL = "https://question-manager-web.onrender.com" # Base URL for the backend API

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
    from db_utils import connect_db, setup_database
    # quiz_db is no longer needed for fetching questions
    from quiz_db import QuizDatabase # Keep for user/result management
    # Remove import of safe_edit_message_text, keep safe_send_message
    from helper_function import safe_send_message
except ImportError as e:
    logger.error(f"Failed to import database/helper modules: {e}. Ensure db_utils.py, quiz_db.py, helper_function.py are present.")
    sys.exit("Critical import error, stopping bot.")

# Initialize database connection and QuizDatabase instance (for users/results)
if not DATABASE_URL:
    logger.error("DATABASE_URL environment variable not set or empty. Bot cannot connect to DB for user/result data.")
    DB_CONN = None
    QUIZ_DB = None
else:
    DB_CONN = connect_db(DATABASE_URL)
    if DB_CONN:
        setup_database() # Ensure tables exist (users, quiz_results)
        QUIZ_DB = QuizDatabase(DB_CONN) # Keep instance for user/result methods
        logger.info("QuizDatabase initialized successfully (for users/results).")
    else:
        logger.error("Failed to establish database connection. Bot cannot save user/result data.")
        QUIZ_DB = None # Set to None if connection fails

# --- Chemistry Data (Placeholders - Likely replaced by API calls) ---
try:
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
            row.append(InlineKeyboardButton(str(count), callback_data=f"q_count_{count}"))
    if row:
        keyboard.append(row)
    # Add back button based on context (e.g., back to unit selection, course selection, or quiz menu)
    # This needs context, so maybe add it in the calling function
    # keyboard.append([InlineKeyboardButton("🔙 عودة", callback_data="quiz_menu")]) # Placeholder
    return InlineKeyboardMarkup(keyboard)

def create_quiz_answer_keyboard(question_index: int, quiz_id: int, options_have_images: bool):
    """Creates the keyboard for answering a quiz question."""
    # Use A, B, C, D if options have images, otherwise use option text
    # This logic needs refinement based on how images are displayed
    labels = ["A", "B", "C", "D"] # Simple labels for now
    keyboard = [
        [InlineKeyboardButton(labels[0], callback_data=f"quiz_{quiz_id}_{question_index}_0"),
         InlineKeyboardButton(labels[1], callback_data=f"quiz_{quiz_id}_{question_index}_1")],
        [InlineKeyboardButton(labels[2], callback_data=f"quiz_{quiz_id}_{question_index}_2"),
         InlineKeyboardButton(labels[3], callback_data=f"quiz_{quiz_id}_{question_index}_3")],
        [InlineKeyboardButton("⏭️ تخطي السؤال", callback_data=f"quiz_{quiz_id}_{question_index}_skip"),
         InlineKeyboardButton("🛑 إنهاء الاختبار", callback_data=f"quiz_{quiz_id}_{question_index}_stop")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Core Command Handlers ---

def start(update: Update, context: CallbackContext) -> int:
    user = update.effective_user
    user_id = user.id
    user_name = get_user_name(user)
    logger.info(f"[DIAG] Received /start command from user {user_id} ({user_name}).")

    # Register or update user in DB if DB is available
    if QUIZ_DB:
        try:
            QUIZ_DB.register_user(user_id, user_name, user.username)
            logger.info(f"User {user_id} ({user_name}) registered or updated.")
        except Exception as e:
            logger.error(f"Database error registering user {user_id}: {e}")
            # Don't stop the bot, but log the error

    text = f"أهلاً بك يا {user_name} في بوت الكيمياء التعليمي!\n\nاختر أحد الخيارات أدناه للبدء:"
    keyboard = create_main_menu_keyboard(user_id)
    safe_send_message(context.bot, update.effective_chat.id, text=text, reply_markup=keyboard)
    return MAIN_MENU

def cancel(update: Update, context: CallbackContext) -> int:
    user = update.effective_user
    logger.info(f"User {user.id} cancelled the conversation.")
    # Clean up any ongoing quiz or operation
    user_data = context.user_data
    if "current_quiz" in user_data:
        quiz_data = user_data["current_quiz"]
        if quiz_data.get("quiz_timer_job_name"):
            remove_job_if_exists(quiz_data["quiz_timer_job_name"], context)
        if quiz_data.get("question_timer_job_name"):
            remove_job_if_exists(quiz_data["question_timer_job_name"], context)
        del user_data["current_quiz"]

    safe_send_message(context.bot, update.effective_chat.id, text="تم الإلغاء. يمكنك البدء مجدداً بإرسال /start.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- Main Menu Navigation ---

def main_menu_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    keyboard = create_main_menu_keyboard(user_id)
    query.edit_message_text(text="القائمة الرئيسية: اختر أحد الخيارات.", reply_markup=keyboard)
    return MAIN_MENU

def menu_info_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    logger.info(f"User {update.effective_user.id} selected Info Menu.")

    # Fetch courses from API
    courses_data = fetch_from_api("/api/v1/courses")

    if courses_data == "TIMEOUT":
        query.edit_message_text(text="⏳ حدث خطأ أثناء جلب قائمة المقررات (مهلة زمنية). الرجاء المحاولة مرة أخرى لاحقاً.")
        return MAIN_MENU # Stay in main menu or go back?
    elif courses_data and isinstance(courses_data, list):
        if not courses_data:
             query.edit_message_text(text="لا توجد مقررات متاحة حالياً في قسم المعلومات.")
             return MAIN_MENU
        # Assuming API returns list of dicts like [{\'id\': 1, \'name\': \'Course 1\'}, ...]
        keyboard = create_dynamic_keyboard(courses_data, "info_course", "main_menu")
        # *** CORRECTED LINE 465 ***
        query.edit_message_text(text="📚 المعلومات الكيميائية:\nاختر المقرر لعرض معلوماته (الميزة قيد الإنشاء).", reply_markup=keyboard)
        return INFO_MENU # Go to info menu state
    else:
        query.edit_message_text(text="⚠️ حدث خطأ أثناء جلب قائمة المقررات. الرجاء المحاولة مرة أخرى لاحقاً.")
        return MAIN_MENU

def menu_reports_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id} selected Reports Menu.")

    if not QUIZ_DB:
        query.edit_message_text(text="⚠️ عذراً، خدمة التقارير غير متاحة حالياً بسبب مشكلة في الاتصال بقاعدة البيانات.")
        return MAIN_MENU

    try:
        stats = QUIZ_DB.get_user_stats(user_id)
        report_lines = ["📊 تقرير أدائك:"] # Start with title

        if stats:
            total_quizzes = stats.get("total_quizzes", 0)
            avg_score = stats.get("average_score")

            report_lines.append(f"\n📝 عدد الاختبارات المكتملة: {total_quizzes}")

            if total_quizzes > 0 and avg_score is not None:
                 report_lines.append(f"🎯 متوسط الدرجات: {avg_score:.1f}%")
            else:
                 # Add empty line if no average score
                 report_lines.append("لم تكمل أي اختبارات بعد.")
            # Add more stats if available (e.g., last score, best score)
        else:
            report_lines.append("\nلم تقم بإكمال أي اختبارات بعد.")

        # Join the lines into a single string
        text = "\n".join(report_lines)

        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]])
        query.edit_message_text(text=text, reply_markup=keyboard)
        return SHOWING_REPORTS # State indicating reports are shown

    except Exception as e:
        logger.error(f"Error fetching stats for user {user_id}: {e}")
        query.edit_message_text(text="⚠️ حدث خطأ أثناء جلب تقرير أدائك. الرجاء المحاولة مرة أخرى لاحقاً.")
        return MAIN_MENU

def menu_about_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    # Using triple quotes for multi-line string
    text = """ℹ️ **حول البوت**

هذا البوت مصمم لمساعدتك في تعلم الكيمياء واختبار معلوماتك.

**الميزات:**
- اختبارات متنوعة (عامة، حسب المقرر/الوحدة/الدرس)
- معلومات كيميائية (قيد الإنشاء)
- تتبع الأداء

تم التطوير بواسطة [اسم المطور/الفريق]"""
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]])
    query.edit_message_text(text=text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    return MAIN_MENU

def menu_admin_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        query.edit_message_text(text="⚠️ ليس لديك صلاحية الوصول لهذه القائمة.")
        return MAIN_MENU

    # Placeholder for Admin Menu
    keyboard = [
        # [InlineKeyboardButton("➕ إضافة سؤال", callback_data=\"admin_add_q\")],
        # [InlineKeyboardButton("➖ حذف سؤال", callback_data=\"admin_del_q\")],
        # [InlineKeyboardButton("👁️ عرض سؤال", callback_data=\"admin_view_q\")],
        [InlineKeyboardButton("📊 عرض إحصائيات المستخدمين", callback_data="admin_view_stats")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
    ]
    query.edit_message_text(text="⚙️ قائمة الإدارة:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU

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
             query.edit_message_text(text="لا توجد وحدات متاحة حالياً لهذا المقرر.",
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لاختيار المقرر", callback_data="quiz_select_course")]]))
             return SELECT_COURSE_FOR_QUIZ
        keyboard = create_dynamic_keyboard(units_data, "quiz_unit", "quiz_select_course") # prefix 'quiz_unit_'
        query.edit_message_text(text="🗂️ اختر الوحدة لبدء الاختبار:", reply_markup=keyboard)
        return SELECT_UNIT_FOR_QUIZ
    else:
        logger.error(f"API error or invalid data fetching units for course {course_id}: {units_data}")
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

    # Retrieve course_id from user_data
    quiz_selection = context.user_data.get("quiz_selection", {})
    course_id = quiz_selection.get("course_id")
    if not course_id:
        logger.error(f"Course ID not found in user_data for unit selection callback (user {user_id}).")
        query.edit_message_text(text="⚠️ حدث خطأ داخلي. الرجاء البدء من قائمة الاختبارات مرة أخرى.",
                                reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

    # Store selected unit ID
    quiz_selection["type"] = "lesson"
    quiz_selection["unit_id"] = unit_id
    context.user_data["quiz_selection"] = quiz_selection

    # Fetch lessons for the unit - **ASSUMED ENDPOINT**
    lessons_data = fetch_from_api(f"/api/v1/units/{unit_id}/lessons")

    if lessons_data == "TIMEOUT":
        query.edit_message_text(text="⏳ حدث خطأ أثناء جلب قائمة الدروس (مهلة زمنية). الرجاء المحاولة مرة أخرى لاحقاً.",
                                reply_markup=create_dynamic_keyboard([], "", f"quiz_course_{course_id}")) # Back to unit selection
        return SELECT_UNIT_FOR_QUIZ
    elif lessons_data and isinstance(lessons_data, list):
        if not lessons_data:
             query.edit_message_text(text="لا توجد دروس متاحة حالياً لهذه الوحدة.",
                                     reply_markup=create_dynamic_keyboard([], "", f"quiz_course_{course_id}")) # Back to unit selection
             return SELECT_UNIT_FOR_QUIZ
        keyboard = create_dynamic_keyboard(lessons_data, "quiz_lesson", f"quiz_course_{course_id}") # prefix 'quiz_lesson_', back to unit sel.
        query.edit_message_text(text="🎓 اختر الدرس لبدء الاختبار:", reply_markup=keyboard)
        return SELECT_LESSON_FOR_QUIZ_HIERARCHY
    else:
        logger.error(f"API error or invalid data fetching lessons for unit {unit_id}: {lessons_data}")
        query.edit_message_text(text="⚠️ حدث خطأ أثناء جلب قائمة الدروس. الرجاء المحاولة مرة أخرى لاحقاً.",
                                reply_markup=create_dynamic_keyboard([], "", f"quiz_course_{course_id}")) # Back to unit selection
        return SELECT_UNIT_FOR_QUIZ

# --- Question Count Selection --- NEW SECTION ---

def ask_question_count(update: Update, context: CallbackContext, available_questions: list) -> int:
    """Asks the user to select the number of questions."""
    query = update.callback_query # Can be called from callback or message
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    max_questions = len(available_questions)
    if max_questions == 0:
        logger.warning(f"No questions available for the selected criteria (user {user_id}).")
        text = "⚠️ عذراً، لا توجد أسئلة متاحة لهذا الاختيار حالياً."
        # Determine the correct back button based on quiz_selection type
        quiz_selection = context.user_data.get("quiz_selection", {})
        back_cb = "menu_quiz"
        if quiz_selection.get("type") == "lesson":
            back_cb = f"quiz_unit_{quiz_selection.get('unit_id')}"
        elif quiz_selection.get("type") == "unit":
            back_cb = f"quiz_course_{quiz_selection.get('course_id')}"
        elif quiz_selection.get("type") == "course":
            back_cb = "quiz_select_course"

        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data=back_cb)]])
        if query:
            query.edit_message_text(text=text, reply_markup=keyboard)
        else:
            safe_send_message(context.bot, chat_id, text=text, reply_markup=keyboard)
        # Need to return to the previous menu state
        if quiz_selection.get("type") == "lesson": return SELECT_LESSON_FOR_QUIZ_HIERARCHY
        if quiz_selection.get("type") == "unit": return SELECT_UNIT_FOR_QUIZ
        if quiz_selection.get("type") == "course": return SELECT_COURSE_FOR_QUIZ
        return QUIZ_MENU # Default back

    # Store available questions and max count temporarily
    context.user_data["quiz_setup"] = {
        "available_questions": available_questions,
        "max_questions": max_questions
    }

    text = f"🔢 كم عدد الأسئلة التي ترغب في اختبارها؟ (الحد الأقصى المتاح: {max_questions})\n\nاختر من الأزرار أدناه أو اكتب العدد المطلوب:"
    keyboard = create_question_count_keyboard(max_questions)

    # Add the correct back button dynamically
    quiz_selection = context.user_data.get("quiz_selection", {})
    back_cb = "menu_quiz"
    if quiz_selection.get("type") == "lesson":
        back_cb = f"quiz_unit_{quiz_selection.get('unit_id')}"
    elif quiz_selection.get("type") == "unit":
        back_cb = f"quiz_course_{quiz_selection.get('course_id')}"
    elif quiz_selection.get("type") == "course":
        back_cb = "quiz_select_course"
    elif quiz_selection.get("type") == "random":
        back_cb = "menu_quiz"

    # Ensure keyboard is mutable list before appending
    if isinstance(keyboard.inline_keyboard, tuple):
        keyboard.inline_keyboard = list(keyboard.inline_keyboard)
    keyboard.inline_keyboard.append([InlineKeyboardButton("🔙 عودة", callback_data=back_cb)])

    if query:
        query.edit_message_text(text=text, reply_markup=keyboard)
    else: # If called after text input error
        safe_send_message(context.bot, chat_id, text=text, reply_markup=keyboard)

    return SELECT_QUESTION_COUNT

def handle_question_count_callback(update: Update, context: CallbackContext) -> int:
    """Handles button press for question count selection."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    try:
        selected_count = int(query.data.split("_")[-1])
        logger.info(f"User {user_id} selected question count: {selected_count} via button.")

        quiz_setup = context.user_data.get("quiz_setup")
        if not quiz_setup or "available_questions" not in quiz_setup:
            logger.error(f"Quiz setup data missing for user {user_id} in question count callback.")
            query.edit_message_text("⚠️ حدث خطأ داخلي. الرجاء البدء من قائمة الاختبارات مرة أخرى.",
                                    reply_markup=create_quiz_menu_keyboard())
            return QUIZ_MENU

        max_questions = quiz_setup["max_questions"]

        if 0 < selected_count <= max_questions:
            # Start the quiz with the selected count
            return start_quiz(update, context, selected_count)
        else:
            # This case should ideally not happen with buttons, but handle defensively
            logger.warning(f"User {user_id} selected invalid count {selected_count} via button (max: {max_questions}).")
            text = f"⚠️ العدد المحدد ({selected_count}) غير صالح. الحد الأقصى هو {max_questions}.\n\nالرجاء الاختيار مرة أخرى أو كتابة العدد الصحيح:"
            keyboard = create_question_count_keyboard(max_questions)
            # Add back button again
            quiz_selection = context.user_data.get("quiz_selection", {})
            back_cb = "menu_quiz"
            if quiz_selection.get("type") == "lesson": back_cb = f"quiz_unit_{quiz_selection.get('unit_id')}"
            elif quiz_selection.get("type") == "unit": back_cb = f"quiz_course_{quiz_selection.get('course_id')}"
            elif quiz_selection.get("type") == "course": back_cb = "quiz_select_course"
            elif quiz_selection.get("type") == "random": back_cb = "menu_quiz"
            if isinstance(keyboard.inline_keyboard, tuple): keyboard.inline_keyboard = list(keyboard.inline_keyboard)
            keyboard.inline_keyboard.append([InlineKeyboardButton("🔙 عودة", callback_data=back_cb)])
            query.edit_message_text(text=text, reply_markup=keyboard)
            return SELECT_QUESTION_COUNT

    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing question count callback data: {e}")
