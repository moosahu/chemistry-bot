# -*- coding: utf-8 -*-
"""
Chemistry Quiz and Info Telegram Bot (Polling Mode)

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
# PORT = int(os.environ.get("PORT", 8443)) # Not needed for polling
# APP_NAME = os.environ.get("APP_NAME") # Not needed for polling
# Corrected API Base URL - Ensure it points to the root of the API service
API_BASE_URL = "https://question-manager-web.onrender.com" # Base URL for the backend API

logger.debug(f"[DIAG] BOT_TOKEN found: {"Yes" if BOT_TOKEN else "No"}")
logger.debug(f"[DIAG] DATABASE_URL found: {"Yes" if DATABASE_URL else "No"}")
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

def create_dynamic_keyboard(items: list, callback_prefix: str, back_callback: str, items_per_row: int = 2) -> InlineKeyboardMarkup:
    """Creates a dynamic keyboard from a list of items (dicts with 'id' and 'name')."""
    buttons = []
    row = []
    if not items:
        logger.warning(f"No items provided for dynamic keyboard with prefix {callback_prefix}")
        # Return a keyboard with only the back button if no items are available
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data=back_callback)]])

    for item in items:
        # Ensure item is a dictionary and has 'id' and 'name'
        if isinstance(item, dict) and 'id' in item and 'name' in item:
            # Use single quotes inside f-string for dictionary keys
            button = InlineKeyboardButton(item["name"], callback_data=f"{callback_prefix}_{item['id']}")
            row.append(button)
            if len(row) == items_per_row:
                buttons.append(row)
                row = []
        else:
            logger.warning(f"Skipping invalid item for dynamic keyboard: {item}")

    if row: # Add the last row if it's not empty
        buttons.append(row)

    # Add the back button as the last row
    buttons.append([InlineKeyboardButton("🔙 عودة", callback_data=back_callback)])
    return InlineKeyboardMarkup(buttons)

def create_question_count_keyboard(back_callback: str) -> InlineKeyboardMarkup:
    """Creates keyboard for selecting number of questions."""
    keyboard = [
        [InlineKeyboardButton("10", callback_data="q_count_10"),
         InlineKeyboardButton("20", callback_data="q_count_20"),
         InlineKeyboardButton("30", callback_data="q_count_30")],
        [InlineKeyboardButton("🔢 كتابة العدد يدوياً", callback_data="q_count_manual")],
        [InlineKeyboardButton("🔙 عودة", callback_data=back_callback)]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Command Handlers ---

def log_update(update: Update, context: CallbackContext):
    """Logs every update received by the bot for diagnostic purposes."""
    if update:
        user_id = update.effective_user.id if update.effective_user else "N/A"
        chat_id = update.effective_chat.id if update.effective_chat else "N/A"
        update_type = update.effective_message.text if update.effective_message and update.effective_message.text else update.callback_query.data if update.callback_query else "Other Update"
        logger.debug(f"[DIAG] Received Update: User={user_id}, Chat={chat_id}, Type/Data='{update_type}'")
    else:
        logger.debug("[DIAG] Received an empty update object.")

def start(update: Update, context: CallbackContext) -> int:
    """Sends a welcome message and the main menu."""
    user = update.effective_user
    user_id = user.id
    user_name = get_user_name(user)
    chat_id = update.effective_chat.id

    logger.info(f"User {user_id} ({user_name}) started the bot in chat {chat_id}.")
    logger.debug(f"[DIAG] Entering start handler for user {user_id}.")

    # Register user if not already registered
    if QUIZ_DB:
        try:
            logger.debug(f"[DIAG] Attempting to register user {user_id}.")
            QUIZ_DB.register_user(user_id, user_name)
            logger.info(f"User {user_id} registered or already exists.")
        except Exception as e:
            logger.error(f"Error registering user {user_id}: {e}")
    else:
        logger.warning("QUIZ_DB not available. Cannot register user.")

    welcome_text = f"أهلاً بك يا {user_name} في بوت الكيمياء التعليمي! 👋"
    keyboard = create_main_menu_keyboard(user_id)
    safe_send_message(context.bot, chat_id, text=welcome_text, reply_markup=keyboard)
    logger.debug(f"[DIAG] Sent welcome message and main menu to user {user_id}.")
    return MAIN_MENU

def cancel(update: Update, context: CallbackContext) -> int:
    """Cancels the current operation and returns to the main menu."""
    user = update.effective_user
    user_id = user.id
    chat_id = update.effective_chat.id
    logger.info(f"User {user_id} cancelled the conversation.")

    # Clean up any ongoing quiz or operation data
    if "current_quiz" in context.user_data:
        quiz_data = context.user_data["current_quiz"]
        if quiz_data.get("quiz_timer_job_name"):
            remove_job_if_exists(quiz_data["quiz_timer_job_name"], context)
        if quiz_data.get("question_timer_job_name"):
            remove_job_if_exists(quiz_data["question_timer_job_name"], context)
        del context.user_data["current_quiz"]
        logger.info(f"Cleaned up quiz data for user {user_id} due to cancel.")

    safe_send_message(context.bot, chat_id, text="تم إلغاء العملية الحالية. العودة إلى القائمة الرئيسية.", reply_markup=ReplyKeyboardRemove())
    keyboard = create_main_menu_keyboard(user_id)
    safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=keyboard)
    return MAIN_MENU

# --- Callback Query Handlers (Main Menu and Submenus) ---

def main_menu_button(update: Update, context: CallbackContext) -> int:
    """Handles button presses from the main menu."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    data = query.data

    logger.info(f"User {user_id} pressed main menu button: {data}")

    if data == "menu_info":
        return info_menu_callback(update, context)
    elif data == "menu_quiz":
        return quiz_menu_callback(update, context)
    elif data == "menu_reports":
        return reports_menu_callback(update, context)
    elif data == "menu_about":
        return about_callback(update, context)
    elif data == "menu_admin" and is_admin(user_id):
        return admin_menu_callback(update, context)
    else:
        logger.warning(f"Unhandled main menu callback: {data}")
        query.edit_message_text(text="خيار غير معروف.")
        return MAIN_MENU # Stay in main menu

def about_callback(update: Update, context: CallbackContext) -> int:
    """Displays information about the bot."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requested 'About'.")
    about_text = """🤖 **بوت الكيمياء التعليمي** 🧪\n\nهذا البوت مصمم لمساعدتك في تعلم الكيمياء من خلال:\n*   📚 **المعلومات الكيميائية:** استعراض المقررات والمفاهيم.\n*   📝 **الاختبارات:** اختبار معلوماتك في مواضيع مختلفة.\n*   📊 **تقارير الأداء:** متابعة نتائج اختباراتك.\n\nتم تطوير هذا البوت بواسطة [اذكر اسم المطور أو الجهة هنا].\nنتمنى لك رحلة تعليمية ممتعة ومفيدة!"""
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]])
    query.edit_message_text(text=about_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    return MAIN_MENU

def main_menu_callback(update: Update, context: CallbackContext) -> int:
    """Handles the 'Back to Main Menu' button press."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    logger.info(f"User {user_id} returned to main menu.")

    # Clean up potential quiz selection state
    context.user_data.pop("quiz_selection", None)

    keyboard = create_main_menu_keyboard(user_id)
    # Use edit_message_text if coming from another menu, send_message if command
    try:
        query.edit_message_text(text="القائمة الرئيسية:", reply_markup=keyboard)
    except BadRequest:
        # Message might not have changed or was deleted, send a new one
        safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=keyboard)
    return MAIN_MENU

def info_menu_callback(update: Update, context: CallbackContext) -> int:
    """Handles the 'Info Menu' button press - Fetches and displays courses."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id} entered info menu.")

    courses = fetch_from_api("/courses")

    if courses == "TIMEOUT":
        query.edit_message_text(text="⏳ المهلة انتهت أثناء محاولة جلب قائمة المقررات. يرجى المحاولة مرة أخرى.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]]))
        return MAIN_MENU
    elif courses is None or not isinstance(courses, list):
        logger.error("Failed to fetch or parse courses for info menu.")
        query.edit_message_text(text="حدث خطأ أثناء جلب قائمة المقررات. يرجى المحاولة لاحقاً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]]))
        return MAIN_MENU
    elif not courses:
        query.edit_message_text(text="لا توجد مقررات متاحة حالياً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]]))
        return MAIN_MENU

    keyboard = create_dynamic_keyboard(courses, "info_course", "main_menu")
    query.edit_message_text(text="📚 **المعلومات الكيميائية** 🧪\n\nاختر المقرر لعرض الوحدات:", reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    return INFO_MENU # Stay in INFO_MENU state to handle course selection

def info_course_callback(update: Update, context: CallbackContext) -> int:
    """Handles selection of a course in the info menu - Fetches and displays units."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    course_id = query.data.split("_")[-1]
    logger.info(f"User {user_id} selected info course ID: {course_id}")

    units = fetch_from_api(f"/courses/{course_id}/units")

    if units == "TIMEOUT":
        query.edit_message_text(text="⏳ المهلة انتهت أثناء محاولة جلب قائمة الوحدات. يرجى المحاولة مرة أخرى.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة المقررات", callback_data="menu_info")]]))
        return INFO_MENU
    elif units is None or not isinstance(units, list):
        logger.error(f"Failed to fetch or parse units for course {course_id}.")
        query.edit_message_text(text="حدث خطأ أثناء جلب قائمة الوحدات. يرجى المحاولة لاحقاً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة المقررات", callback_data="menu_info")]]))
        return INFO_MENU
    elif not units:
        query.edit_message_text(text="لا توجد وحدات متاحة لهذا المقرر حالياً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة المقررات", callback_data="menu_info")]]))
        return INFO_MENU

    keyboard = create_dynamic_keyboard(units, f"info_unit_{course_id}", "menu_info")
    query.edit_message_text(text="اختر الوحدة لعرض الدروس:", reply_markup=keyboard)
    return INFO_MENU # Stay in INFO_MENU state to handle unit selection

def info_unit_callback(update: Update, context: CallbackContext) -> int:
    """Handles selection of a unit in the info menu - Fetches and displays lessons."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    parts = query.data.split("_")
    course_id = parts[-2]
    unit_id = parts[-1]
    logger.info(f"User {user_id} selected info unit ID: {unit_id} from course {course_id}")

    lessons = fetch_from_api(f"/units/{unit_id}/lessons")

    if lessons == "TIMEOUT":
        query.edit_message_text(text="⏳ المهلة انتهت أثناء محاولة جلب قائمة الدروس. يرجى المحاولة مرة أخرى.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الوحدات", callback_data=f"info_course_{course_id}")]]))
        return INFO_MENU
    elif lessons is None or not isinstance(lessons, list):
        logger.error(f"Failed to fetch or parse lessons for unit {unit_id}.")
        query.edit_message_text(text="حدث خطأ أثناء جلب قائمة الدروس. يرجى المحاولة لاحقاً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الوحدات", callback_data=f"info_course_{course_id}")]]))
        return INFO_MENU
    elif not lessons:
        query.edit_message_text(text="لا توجد دروس متاحة لهذه الوحدة حالياً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الوحدات", callback_data=f"info_course_{course_id}")]]))
        return INFO_MENU

    # For info, just show lesson names. Clicking them won't do anything yet.
    # We create a keyboard but the callback won't be handled further for now.
    keyboard = create_dynamic_keyboard(lessons, f"info_lesson_{unit_id}", f"info_course_{course_id}")
    query.edit_message_text(text="قائمة الدروس المتاحة:", reply_markup=keyboard)
    return INFO_MENU # Stay in INFO_MENU state

def reports_menu_callback(update: Update, context: CallbackContext) -> int:
    """Handles the 'Reports Menu' button press."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    logger.info(f"User {user_id} requested reports.")

    if not QUIZ_DB:
        query.edit_message_text(text="عذراً، لا يمكن عرض التقارير حالياً بسبب مشكلة في قاعدة البيانات.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]]))
        return MAIN_MENU

    try:
        results = QUIZ_DB.get_user_results(user_id)
        if not results:
            report_text = "لم تقم بإجراء أي اختبارات بعد."
        else:
            report_text = "📊 **تقرير الأداء الخاص بك:**\n\n"
            # Group results by quiz type/details if possible (needs quiz details from API or saved)
            # For now, just list them chronologically
            for i, result in enumerate(results):
                # result format: (result_id, user_id, quiz_id, score, total_questions, timestamp, quiz_details)
                quiz_details_str = result[6] if result[6] else "اختبار عام"
                timestamp_dt = result[5]
                # Format timestamp nicely (e.g., YYYY-MM-DD HH:MM)
                formatted_time = timestamp_dt.strftime("%Y-%m-%d %H:%M") if timestamp_dt else "غير معروف"
                score = result[3]
                total = result[4]
                percentage = (score / total * 100) if total > 0 else 0
                report_text += f"*{i+1}.* {quiz_details_str} ({formatted_time}): {score}/{total} ({percentage:.1f}%)\n"

        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]])
        query.edit_message_text(text=report_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Error fetching reports for user {user_id}: {e}")
        query.edit_message_text(text="حدث خطأ أثناء جلب تقاريرك. يرجى المحاولة لاحقاً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]]))

    return SHOWING_REPORTS # Stay in reports state until back button

def quiz_menu_callback(update: Update, context: CallbackContext) -> int:
    """Handles the 'Quiz Menu' button press."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id} entered quiz menu.")

    keyboard = create_quiz_menu_keyboard()
    query.edit_message_text(text="📝 **الاختبارات** 📝\n\nاختر نوع الاختبار الذي تريده:", reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    return QUIZ_MENU # Transition to QUIZ_MENU state

# --- Quiz Selection Callbacks (Hierarchical) ---

def quiz_select_course_callback(update: Update, context: CallbackContext) -> int:
    """Handles 'Quiz by Course' button - Fetches and displays courses."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id} chose 'Quiz by Course'. Fetching courses.")

    courses = fetch_from_api("/courses")

    if courses == "TIMEOUT":
        query.edit_message_text(text="⏳ المهلة انتهت أثناء محاولة جلب قائمة المقررات. يرجى المحاولة مرة أخرى.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data="menu_quiz")]]))
        return QUIZ_MENU
    elif courses is None or not isinstance(courses, list):
        logger.error("Failed to fetch or parse courses for quiz selection.")
        query.edit_message_text(text="حدث خطأ أثناء جلب قائمة المقررات. يرجى المحاولة لاحقاً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data="menu_quiz")]]))
        return QUIZ_MENU
    elif not courses:
        query.edit_message_text(text="لا توجد مقررات متاحة للاختبار حالياً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data="menu_quiz")]]))
        return QUIZ_MENU

    # Store selection type
    context.user_data["quiz_selection"] = {"type": "course"}

    keyboard = create_dynamic_keyboard(courses, "quiz_course", "menu_quiz")
    query.edit_message_text(text="اختر المقرر الذي تريد الاختبار فيه:", reply_markup=keyboard)
    return SELECT_COURSE_FOR_QUIZ

def quiz_course_selected_callback(update: Update, context: CallbackContext) -> int:
    """Handles selection of a course for the quiz - Fetches and displays units."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    course_id = query.data.split("_")[-1]
    logger.info(f"User {user_id} selected course {course_id} for quiz. Fetching units.")

    # Store course ID in selection
    if "quiz_selection" not in context.user_data:
        context.user_data["quiz_selection"] = {}
    context.user_data["quiz_selection"]["course_id"] = course_id
    context.user_data["quiz_selection"]["type"] = "unit" # Next level is unit

    # Fetch course name for context
    course_details = fetch_from_api(f"/courses/{course_id}")
    course_name = course_details.get("name", f"المقرر {course_id}") if isinstance(course_details, dict) else f"المقرر {course_id}"
    context.user_data["quiz_selection"]["course_name"] = course_name

    units = fetch_from_api(f"/courses/{course_id}/units")

    if units == "TIMEOUT":
        query.edit_message_text(text="⏳ المهلة انتهت أثناء محاولة جلب قائمة الوحدات. يرجى المحاولة مرة أخرى.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لاختيار المقرر", callback_data="quiz_select_course")]]))
        return SELECT_COURSE_FOR_QUIZ
    elif units is None or not isinstance(units, list):
        logger.error(f"Failed to fetch or parse units for course {course_id} quiz.")
        query.edit_message_text(text="حدث خطأ أثناء جلب قائمة الوحدات. يرجى المحاولة لاحقاً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لاختيار المقرر", callback_data="quiz_select_course")]]))
        return SELECT_COURSE_FOR_QUIZ
    elif not units:
        query.edit_message_text(text="لا توجد وحدات متاحة لهذا المقرر حالياً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لاختيار المقرر", callback_data="quiz_select_course")]]))
        return SELECT_COURSE_FOR_QUIZ

    keyboard = create_dynamic_keyboard(units, f"quiz_unit_{course_id}", "quiz_select_course")
    query.edit_message_text(text=f"اختر الوحدة من مقرر '{course_name}':", reply_markup=keyboard)
    return SELECT_UNIT_FOR_QUIZ

def quiz_unit_selected_callback(update: Update, context: CallbackContext) -> int:
    """Handles selection of a unit for the quiz - Fetches and displays lessons."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    parts = query.data.split("_")
    course_id = parts[-2]
    unit_id = parts[-1]
    logger.info(f"User {user_id} selected unit {unit_id} from course {course_id} for quiz. Fetching lessons.")

    # Store unit ID in selection
    if "quiz_selection" not in context.user_data:
        context.user_data["quiz_selection"] = {}
    context.user_data["quiz_selection"]["unit_id"] = unit_id
    context.user_data["quiz_selection"]["type"] = "lesson" # Next level is lesson

    # Fetch unit name for context
    unit_details = fetch_from_api(f"/units/{unit_id}")
    unit_name = unit_details.get("name", f"الوحدة {unit_id}") if isinstance(unit_details, dict) else f"الوحدة {unit_id}"
    context.user_data["quiz_selection"]["unit_name"] = unit_name
    course_name = context.user_data.get("quiz_selection", {}).get("course_name", "المقرر")

    lessons = fetch_from_api(f"/units/{unit_id}/lessons")

    if lessons == "TIMEOUT":
        query.edit_message_text(text="⏳ المهلة انتهت أثناء محاولة جلب قائمة الدروس. يرجى المحاولة مرة أخرى.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لاختيار الوحدة", callback_data=f"quiz_course_{course_id}")]]))
        return SELECT_UNIT_FOR_QUIZ
    elif lessons is None or not isinstance(lessons, list):
        logger.error(f"Failed to fetch or parse lessons for unit {unit_id} quiz.")
        query.edit_message_text(text="حدث خطأ أثناء جلب قائمة الدروس. يرجى المحاولة لاحقاً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لاختيار الوحدة", callback_data=f"quiz_course_{course_id}")]]))
        return SELECT_UNIT_FOR_QUIZ
    elif not lessons:
        query.edit_message_text(text="لا توجد دروس متاحة لهذه الوحدة حالياً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لاختيار الوحدة", callback_data=f"quiz_course_{course_id}")]]))
        return SELECT_UNIT_FOR_QUIZ

    keyboard = create_dynamic_keyboard(lessons, f"quiz_lesson_{unit_id}", f"quiz_course_{course_id}")
    query.edit_message_text(text=f"اختر الدرس من وحدة '{unit_name}' (مقرر '{course_name}'):", reply_markup=keyboard)
    return SELECT_LESSON_FOR_QUIZ_HIERARCHY

def quiz_lesson_selected_callback(update: Update, context: CallbackContext) -> int:
    """Handles selection of a lesson for the quiz - Moves to question count selection."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    parts = query.data.split("_")
    unit_id = parts[-2]
    lesson_id = parts[-1]
    logger.info(f"User {user_id} selected lesson {lesson_id} from unit {unit_id} for quiz.")

    # Store lesson ID in selection
    if "quiz_selection" not in context.user_data:
        context.user_data["quiz_selection"] = {}
    context.user_data["quiz_selection"]["lesson_id"] = lesson_id
    context.user_data["quiz_selection"]["type"] = "lesson" # Final selection type

    # Fetch lesson name for context
    lesson_details = fetch_from_api(f"/lessons/{lesson_id}")
    lesson_name = lesson_details.get("name", f"الدرس {lesson_id}") if isinstance(lesson_details, dict) else f"الدرس {lesson_id}"
    context.user_data["quiz_selection"]["lesson_name"] = lesson_name
    unit_name = context.user_data.get("quiz_selection", {}).get("unit_name", "الوحدة")
    course_name = context.user_data.get("quiz_selection", {}).get("course_name", "المقرر")

    # Fetch max questions for this lesson
    count_data = fetch_from_api(f"/lessons/{lesson_id}/questions/count")
    max_questions = count_data.get("count", 0) if isinstance(count_data, dict) else 0
    context.user_data["quiz_selection"]["max_questions"] = max_questions

    if max_questions == 0:
        query.edit_message_text(text=f"عذراً، لا توجد أسئلة متاحة حالياً للدرس '{lesson_name}'.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لاختيار الدرس", callback_data=f"quiz_unit_{course_id}_{unit_id}")]])) # Need course_id here
        return SELECT_LESSON_FOR_QUIZ_HIERARCHY

    # Proceed to question count selection
    keyboard = create_question_count_keyboard(back_callback=f"quiz_unit_{course_id}_{unit_id}") # Back to unit selection
    query.edit_message_text(text=f"اختر عدد الأسئلة للاختبار في الدرس '{lesson_name}' (الوحدة '{unit_name}', المقرر '{course_name}').\nالحد الأقصى المتاح: {max_questions}", reply_markup=keyboard)
    return SELECT_QUESTION_COUNT

def quiz_type_random_callback(update: Update, context: CallbackContext) -> int:
    """Handles 'Random Comprehensive Quiz' button press."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id} selected random comprehensive quiz.")

    # Store selection type
    context.user_data["quiz_selection"] = {"type": "random"}

    # Fetch max questions available overall
    count_data = fetch_from_api("/questions/count")
    max_questions = count_data.get("count", 0) if isinstance(count_data, dict) else 0
    context.user_data["quiz_selection"]["max_questions"] = max_questions

    if max_questions == 0:
        query.edit_message_text(text="عذراً، لا توجد أسئلة متاحة في النظام حالياً.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data="menu_quiz")]]))
        return QUIZ_MENU

    # Proceed to question count selection
    keyboard = create_question_count_keyboard(back_callback="menu_quiz")
    query.edit_message_text(text=f"اختر عدد الأسئلة للاختبار التحصيلي العام.\nالحد الأقصى المتاح: {max_questions}", reply_markup=keyboard)
    return SELECT_QUESTION_COUNT

# --- Question Count Selection --- #

def question_count_callback(update: Update, context: CallbackContext) -> int:
    """Handles selection of question count via buttons."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    data = query.data

    if "quiz_selection" not in context.user_data:
        logger.error(f"User {user_id} reached question count selection without prior quiz type selection.")
        query.edit_message_text(text="حدث خطأ، يرجى البدء من قائمة الاختبارات مرة أخرى.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 الاختبارات", callback_data="menu_quiz")]]))
        return QUIZ_MENU

    quiz_selection = context.user_data["quiz_selection"]
    max_questions = quiz_selection.get("max_questions", 0)

    if data == "q_count_manual":
        logger.info(f"User {user_id} chose manual question count input.")
        # Determine the correct back button based on quiz type
        quiz_type = quiz_selection.get("type")
        if quiz_type == "random":
            back_callback = "menu_quiz"
        elif quiz_type == "lesson":
            unit_id = quiz_selection.get("unit_id")
            course_id = quiz_selection.get("course_id") # Should exist if lesson_id exists
            back_callback = f"quiz_unit_{course_id}_{unit_id}"
        else: # Should not happen if logic is correct, default back to quiz menu
            back_callback = "menu_quiz"

        # Send message asking for input
        query.edit_message_text(text=f"🔢 يرجى كتابة عدد الأسئلة المطلوب (الحد الأقصى: {max_questions}).")
        # No keyboard here, waiting for user text input
        return SELECT_QUESTION_COUNT # Stay in this state, waiting for message
    else:
        try:
            count_str = data.split("_")[-1]
            question_count = int(count_str)
            logger.info(f"User {user_id} selected {question_count} questions via button.")

            if question_count <= 0:
                query.edit_message_text(text=f"عدد الأسئلة يجب أن يكون أكبر من صفر. يرجى المحاولة مرة أخرى (الحد الأقصى: {max_questions}).",
                                        reply_markup=query.message.reply_markup) # Keep original keyboard
                return SELECT_QUESTION_COUNT
            elif question_count > max_questions:
                query.edit_message_text(text=f"عذراً، الحد الأقصى للأسئلة المتاحة هو {max_questions}. يرجى اختيار عدد أقل أو يساويه.",
                                        reply_markup=query.message.reply_markup) # Keep original keyboard
                return SELECT_QUESTION_COUNT
            else:
                quiz_selection["count"] = question_count
                # Start the quiz directly after button selection
                return start_quiz(update, context)

        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing question count callback data: {e}")
            query.edit_message_text(text="حدث خطأ في تحديد عدد الأسئلة. يرجى المحاولة مرة أخرى.",
                                    reply_markup=query.message.reply_markup)
            return SELECT_QUESTION_COUNT

def question_count_manual_input(update: Update, context: CallbackContext) -> int:
    """Handles manual input of question count via text message."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = update.message.text

    logger.info(f"User {user_id} entered manual question count: {text}")

    if "quiz_selection" not in context.user_data:
        logger.error(f"User {user_id} sent manual count without prior quiz type selection.")
        safe_send_message(context.bot, chat_id, text="حدث خطأ، يرجى البدء من قائمة الاختبارات مرة أخرى.",
                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 الاختبارات", callback_data="menu_quiz")]]))
        # Go back to main menu as state is lost
        keyboard = create_main_menu_keyboard(user_id)
        safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=keyboard)
        return MAIN_MENU

    quiz_selection = context.user_data["quiz_selection"]
    max_questions = quiz_selection.get("max_questions", 0)

    try:
        question_count = int(text)
        if question_count <= 0:
            safe_send_message(context.bot, chat_id, text=f"عدد الأسئلة يجب أن يكون أكبر من صفر. يرجى إدخال عدد صحيح بين 1 و {max_questions}.")
            return SELECT_QUESTION_COUNT # Stay in state, wait for new input
        elif question_count > max_questions:
            safe_send_message(context.bot, chat_id, text=f"عذراً، الحد الأقصى للأسئلة المتاحة هو {max_questions}. يرجى إدخال عدد أقل أو يساويه.")
            return SELECT_QUESTION_COUNT # Stay in state, wait for new input
        else:
            quiz_selection["count"] = question_count
            logger.info(f"User {user_id} confirmed {question_count} questions manually.")
            # Start the quiz after valid manual input
            return start_quiz(update, context)

    except ValueError:
        safe_send_message(context.bot, chat_id, text=f"إدخال غير صالح. يرجى كتابة رقم صحيح يمثل عدد الأسئلة (بين 1 و {max_questions}).")
        return SELECT_QUESTION_COUNT # Stay in state, wait for new input

# --- Quiz Logic --- #

def start_quiz(update: Update, context: CallbackContext) -> int:
    """Fetches questions based on selection and starts the quiz."""
    query = update.callback_query # If coming from button
    message = update.message     # If coming from manual input
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if "quiz_selection" not in context.user_data or "count" not in context.user_data["quiz_selection"]:
        logger.error(f"User {user_id} tried to start quiz without proper selection or count.")
        text = "حدث خطأ، لم يتم تحديد نوع الاختبار أو عدد الأسئلة. يرجى البدء من جديد."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📝 الاختبارات", callback_data="menu_quiz")]])
        if query:
            query.edit_message_text(text=text, reply_markup=kb)
        else:
            safe_send_message(context.bot, chat_id, text=text, reply_markup=kb)
        return QUIZ_MENU

    quiz_selection = context.user_data["quiz_selection"]
    quiz_type = quiz_selection["type"]
    question_count = quiz_selection["count"]
    quiz_id = f"quiz_{user_id}_{int(time.time())}" # Unique quiz ID

    logger.info(f"User {user_id} starting quiz (ID: {quiz_id}). Type: {quiz_type}, Count: {question_count}")

    # --- Fetch Questions from API based on type ---
    api_questions = None
    quiz_details_str = ""

    if quiz_type == "random":
        api_questions = fetch_from_api("/questions/random", params={"count": question_count})
        quiz_details_str = f"اختبار تحصيلي عام ({question_count} سؤال)"
    elif quiz_type == "lesson":
        lesson_id = quiz_selection.get("lesson_id")
        lesson_name = quiz_selection.get("lesson_name", f"الدرس {lesson_id}")
        unit_name = quiz_selection.get("unit_name", "الوحدة")
        course_name = quiz_selection.get("course_name", "المقرر")
        if lesson_id:
            api_questions = fetch_from_api(f"/lessons/{lesson_id}/questions/random", params={"count": question_count})
            quiz_details_str = f"{course_name} - {unit_name} - {lesson_name} ({question_count} سؤال)"
        else:
            logger.error(f"Lesson ID missing for lesson quiz start. User: {user_id}")
            # Handle error - message user and return
            text = "حدث خطأ: لم يتم تحديد الدرس بشكل صحيح. يرجى البدء من جديد."
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📝 الاختبارات", callback_data="menu_quiz")]])
            if query:
                query.edit_message_text(text=text, reply_markup=kb)
            else:
                safe_send_message(context.bot, chat_id, text=text, reply_markup=kb)
            return QUIZ_MENU
    # Add elif for course/unit quizzes if needed later
    else:
        logger.error(f"Unknown quiz type '{quiz_type}' for starting quiz. User: {user_id}")
        # Handle error - message user and return
        text = "حدث خطأ: نوع الاختبار غير معروف. يرجى البدء من جديد."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📝 الاختبارات", callback_data="menu_quiz")]])
        if query:
            query.edit_message_text(text=text, reply_markup=kb)
        else:
            safe_send_message(context.bot, chat_id, text=text, reply_markup=kb)
        return QUIZ_MENU

    # --- Handle API Fetch Results ---
    if api_questions == "TIMEOUT":
        text = "⏳ المهلة انتهت أثناء محاولة جلب أسئلة الاختبار. يرجى المحاولة مرة أخرى."
        # Determine correct back button
        if quiz_type == "random": back_cb = "menu_quiz"
        elif quiz_type == "lesson":
             unit_id = quiz_selection.get("unit_id")
             course_id = quiz_selection.get("course_id")
             back_cb = f"quiz_unit_{course_id}_{unit_id}"
        else: back_cb = "menu_quiz"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data=back_cb)]])
        if query:
            query.edit_message_text(text=text, reply_markup=kb)
        else:
            safe_send_message(context.bot, chat_id, text=text, reply_markup=kb)
        return SELECT_QUESTION_COUNT # Go back to count selection

    elif api_questions is None or not isinstance(api_questions, list):
        logger.error(f"Failed to fetch or parse questions for quiz {quiz_id}. API Response: {api_questions}")
        text = "حدث خطأ فادح أثناء جلب أسئلة الاختبار. يرجى المحاولة لاحقاً أو التواصل مع المسؤول."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]])
        if query:
            query.edit_message_text(text=text, reply_markup=kb)
        else:
            safe_send_message(context.bot, chat_id, text=text, reply_markup=kb)
        return MAIN_MENU

    elif not api_questions:
        logger.warning(f"No questions returned from API for quiz {quiz_id} (Type: {quiz_type}, Count: {question_count}).")
        text = "عذراً، لم يتم العثور على أسئلة لهذا الاختبار في الوقت الحالي."
        # Determine correct back button
        if quiz_type == "random": back_cb = "menu_quiz"
        elif quiz_type == "lesson":
             unit_id = quiz_selection.get("unit_id")
             course_id = quiz_selection.get("course_id")
             back_cb = f"quiz_unit_{course_id}_{unit_id}"
        else: back_cb = "menu_quiz"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data=back_cb)]])
        if query:
            query.edit_message_text(text=text, reply_markup=kb)
        else:
            safe_send_message(context.bot, chat_id, text=text, reply_markup=kb)
        return SELECT_QUESTION_COUNT # Go back to count selection

    # --- Transform Questions and Initialize Quiz Data ---
    questions = []
    for q in api_questions:
        transformed_q = transform_api_question(q)
        if transformed_q:
            questions.append(transformed_q)
        else:
            logger.warning(f"Skipped invalid question during quiz start: {q}")

    if not questions:
        logger.error(f"All fetched questions were invalid for quiz {quiz_id}. Cannot start quiz.")
        text = "حدث خطأ في تنسيق الأسئلة المستلمة. لا يمكن بدء الاختبار. يرجى التواصل مع المسؤول."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]])
        if query:
            query.edit_message_text(text=text, reply_markup=kb)
        else:
            safe_send_message(context.bot, chat_id, text=text, reply_markup=kb)
        return MAIN_MENU

    # Ensure we didn't get more questions than requested (API might ignore count)
    if len(questions) > question_count:
        logger.warning(f"API returned {len(questions)} questions for quiz {quiz_id}, requested {question_count}. Truncating.")
        questions = questions[:question_count]
    elif len(questions) < question_count:
        logger.warning(f"API returned only {len(questions)} valid questions for quiz {quiz_id}, requested {question_count}. Starting with available questions.")
        question_count = len(questions) # Adjust count to actual number

    quiz_data = {
        "quiz_id": quiz_id,
        "questions": questions,
        "current_question_index": 0,
        "score": 0,
        "answers": {},
        "start_time": time.time(),
        "quiz_timer_job_name": None, # For overall timer (unused)
        "question_timer_job_name": None, # For per-question timer
        "timed_out": False,
        "quiz_details_str": quiz_details_str, # Store details for results
        "error_occurred": False # Flag for errors during quiz
    }
    context.user_data["current_quiz"] = quiz_data
    context.user_data.pop("quiz_selection", None) # Clear selection state

    start_message = f"🚀 تم بدء الاختبار: {quiz_details_str}\nحظاً موفقاً!"

    # Edit the message if started via button, send new if via text
    if query:
        try:
            query.edit_message_text(text=start_message)
        except BadRequest:
             # If edit fails (e.g., message too old), send a new one
             safe_send_message(context.bot, chat_id, text=start_message)
    else:
        safe_send_message(context.bot, chat_id, text=start_message)

    # Send the first question
    send_question(chat_id, user_id, quiz_id, 0, context)
    return TAKING_QUIZ

def send_question(chat_id: int, user_id: int, quiz_id: str, question_index: int, context: CallbackContext):
    """Sends the specified question to the user."""
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.warning(f"Attempted to send question {question_index} for inactive/mismatched quiz {quiz_id}. User: {user_id}")
        safe_send_message(context.bot, chat_id, text="حدث خطأ، يبدو أن الاختبار لم يعد نشطاً.")
        # Go back to main menu as state is inconsistent
        keyboard = create_main_menu_keyboard(user_id)
        safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=keyboard)
        return MAIN_MENU # Or ConversationHandler.END ?

    questions = quiz_data["questions"]
    if question_index >= len(questions):
        logger.error(f"Invalid question index {question_index} requested for quiz {quiz_id}. Max index: {len(questions)-1}")
        safe_send_message(context.bot, chat_id, text="حدث خطأ داخلي في ترقيم الأسئلة.")
        # End the quiz prematurely
        show_results(chat_id, user_id, quiz_id, context, error_occurred=True)
        return SHOWING_RESULTS

    question = questions[question_index]
    quiz_data["current_question_index"] = question_index

    # --- Prepare Question Text and Media --- #
    question_text = f"**السؤال {question_index + 1} من {len(questions)}:**\n\n"
    if question.get("question_text"):
        question_text += process_text_with_chemical_notation(question["question_text"]) + "\n"

    options = [
        question.get("option1"), question.get("option2"),
        question.get("option3"), question.get("option4")
    ]
    option_images = [
        question.get("option1_image"), question.get("option2_image"),
        question.get("option3_image"), question.get("option4_image")
    ]

    # Check if any option has text
    has_text_options = any(opt for opt in options if opt)

    if has_text_options:
        question_text += "\n**الخيارات:**\n"
        for i, option_text in enumerate(options):
            if option_text:
                question_text += f"{chr(ord('🇦') + i)}: {process_text_with_chemical_notation(option_text)}\n"

    # --- Prepare Keyboard --- #
    keyboard_buttons = []
    row = []
    option_emojis = ["🇦", "🇧", "🇨", "🇩"]
    for i in range(4):
        # Only add button if either text or image exists for the option
        if options[i] or option_images[i]:
            button_text = option_emojis[i]
            # Add text to button only if there are no images at all in options
            # if not any(img for img in option_images if img) and options[i]:
            #     button_text += f" {options[i][:20]}{'...' if len(options[i]) > 20 else ''}" # Truncate long text

            row.append(InlineKeyboardButton(button_text, callback_data=f"quiz_answer_{quiz_id}_{question_index}_{i}"))
            if len(row) == 2:
                keyboard_buttons.append(row)
                row = []
    if row:
        keyboard_buttons.append(row)

    # Add skip button
    keyboard_buttons.append([InlineKeyboardButton("⏭️ تخطي السؤال", callback_data=f"quiz_skip_{quiz_id}_{question_index}")])
    reply_markup = InlineKeyboardMarkup(keyboard_buttons)

    # --- Send Message (Text, Photo, or Media Group) --- #
    main_image_url = question.get("image_url")
    option_image_urls = [img for img in option_images if img] # Filter out None values

    message_sent = False
    try:
        if main_image_url and not option_image_urls:
            # Case 1: Main question image only
            logger.debug(f"[DIAG] Sending question {question_index} with main image.")
            safe_send_message(context.bot, chat_id, photo=main_image_url, caption=question_text,
                              reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            message_sent = True
        elif not main_image_url and len(option_image_urls) > 1:
            # Case 2: Multiple option images only (Media Group)
            logger.debug(f"[DIAG] Sending question {question_index} with option images as media group.")
            media_group = []
            for i, img_url in enumerate(option_images):
                caption = f"{option_emojis[i]}: {options[i]}" if options[i] else option_emojis[i]
                if i == 0: # Add main text caption to the first image
                    media_group.append(InputMediaPhoto(media=img_url, caption=f"{question_text}\n{caption}", parse_mode=ParseMode.MARKDOWN))
                else:
                    media_group.append(InputMediaPhoto(media=img_url, caption=caption, parse_mode=ParseMode.MARKDOWN))
            context.bot.send_media_group(chat_id=chat_id, media=media_group)
            # Send keyboard separately for media group
            safe_send_message(context.bot, chat_id, text="اختر الإجابة الصحيحة:", reply_markup=reply_markup)
            message_sent = True
        elif not main_image_url and len(option_image_urls) == 1:
             # Case 3: Single option image only
             logger.debug(f"[DIAG] Sending question {question_index} with single option image.")
             option_idx = option_images.index(option_image_urls[0]) # Find which option it belongs to
             caption = f"{question_text}\nصورة الخيار {option_emojis[option_idx]}"
             safe_send_message(context.bot, chat_id, photo=option_image_urls[0], caption=caption,
                               reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
             message_sent = True
        # Case 4: Main image AND option images (Send main image first, then options as text/group)
        elif main_image_url and option_image_urls:
             logger.debug(f"[DIAG] Sending question {question_index} with main image first, then options.")
             # Send main image with question text part 1
             safe_send_message(context.bot, chat_id, photo=main_image_url, caption=question_text, parse_mode=ParseMode.MARKDOWN)
             # Then send options (text or media group)
             if len(option_image_urls) > 1:
                 media_group = []
                 options_caption = "**الخيارات:**\n"
                 for i, img_url in enumerate(option_images):
                     if img_url:
                         caption = f"{option_emojis[i]}: {options[i]}" if options[i] else option_emojis[i]
                         media_group.append(InputMediaPhoto(media=img_url, caption=caption, parse_mode=ParseMode.MARKDOWN))
                     elif options[i]: # Text only option
                         options_caption += f"{option_emojis[i]}: {options[i]}\n"
                 if media_group:
                     context.bot.send_media_group(chat_id=chat_id, media=media_group)
                 # Send keyboard with options caption
                 safe_send_message(context.bot, chat_id, text=options_caption + "اختر الإجابة الصحيحة:", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
             elif len(option_image_urls) == 1:
                 option_idx = option_images.index(option_image_urls[0])
                 options_text_only = "**الخيارات:**\n"
                 for i, opt_txt in enumerate(options):
                     if i != option_idx and opt_txt:
                         options_text_only += f"{option_emojis[i]}: {opt_txt}\n"
                 caption = f"{options_text_only}\nصورة الخيار {option_emojis[option_idx]}"
                 safe_send_message(context.bot, chat_id, photo=option_image_urls[0], caption=caption,
                                   reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
             else: # Should not happen if option_image_urls is not empty
                 safe_send_message(context.bot, chat_id, text="اختر الإجابة الصحيحة:", reply_markup=reply_markup)
             message_sent = True
        else:
            # Case 5: Text only
            logger.debug(f"[DIAG] Sending question {question_index} as text only.")
            safe_send_message(context.bot, chat_id, text=question_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            message_sent = True

    except BadRequest as e:
        logger.error(f"BadRequest sending question {question_index} for quiz {quiz_id}: {e}")
        safe_send_message(context.bot, chat_id, text=f"حدث خطأ في عرض السؤال {question_index + 1}. قد يكون السبب تنسيقاً غير مدعوم. سيتم تخطي السؤال.")
        quiz_data["error_occurred"] = True
        # Skip to next question or end quiz
        handle_quiz_skip(chat_id, user_id, quiz_id, question_index, context, error_skip=True)
        return # Don't set timer if sending failed
    except (NetworkError, TimedOut) as e:
        logger.error(f"NetworkError/TimedOut sending question {question_index} for quiz {quiz_id}: {e}")
        # Don't skip, user might retry later or bot might recover
        safe_send_message(context.bot, chat_id, text=f"حدث خطأ في الشبكة أثناء إرسال السؤال {question_index + 1}. يرجى الانتظار قليلاً.")
        return # Don't set timer
    except Exception as e:
        logger.exception(f"Unexpected error sending question {question_index} for quiz {quiz_id}: {e}")
        safe_send_message(context.bot, chat_id, text=f"حدث خطأ غير متوقع أثناء عرض السؤال {question_index + 1}. سيتم تخطي السؤال.")
        quiz_data["error_occurred"] = True
        handle_quiz_skip(chat_id, user_id, quiz_id, question_index, context, error_skip=True)
        return # Don't set timer

    # --- Set Timer --- #
    if message_sent:
        job_name = set_question_timer(context, chat_id, user_id, quiz_id, question_index)
        if job_name:
            quiz_data["question_timer_job_name"] = job_name

def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    """Handles user's answer selection during a quiz."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    try:
        _, quiz_id, q_index_str, answer_index_str = query.data.split("_")
        question_index = int(q_index_str)
        selected_answer_index = int(answer_index_str)
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing quiz answer callback data ", query.data, f": {e}")
        query.edit_message_text(text="حدث خطأ في معالجة إجابتك.")
        return TAKING_QUIZ # Stay in quiz state

    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    # --- Validate Quiz State --- #
    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.warning(f"Received answer for inactive/mismatched quiz {quiz_id}. User: {user_id}")
        query.edit_message_text(text="يبدو أن هذا الاختبار لم يعد نشطاً.")
        return MAIN_MENU # Go back to main menu

    if question_index != quiz_data["current_question_index"]:
        logger.warning(f"Received answer for question {question_index} but current is {quiz_data['current_question_index']}. Quiz: {quiz_id}, User: {user_id}")
        # Ignore late answers, maybe edit message to say "Question already answered/skipped"
        try:
            query.edit_message_text(text="لقد تم بالفعل الإجابة على هذا السؤال أو تخطيه.")
        except BadRequest:
            pass # Ignore if message cannot be edited
        return TAKING_QUIZ

    # --- Process Answer --- #
    logger.info(f"User {user_id} answered question {question_index} with {selected_answer_index} for quiz {quiz_id}.")

    # Cancel the question timer
    if quiz_data.get("question_timer_job_name"):
        remove_job_if_exists(quiz_data["question_timer_job_name"], context)
        quiz_data["question_timer_job_name"] = None

    question = quiz_data["questions"][question_index]
    correct_answer_index = question["correct_answer"]
    is_correct = (selected_answer_index == correct_answer_index)

    quiz_data["answers"][question_index] = {
        "selected": selected_answer_index,
        "correct": correct_answer_index,
        "is_correct": is_correct
    }
    if is_correct:
        quiz_data["score"] += 1

    # --- Provide Feedback --- #
    feedback_text = "✅ إجابة صحيحة!" if is_correct else "❌ إجابة خاطئة."
    correct_option_emoji = chr(ord('🇦') + correct_answer_index)
    feedback_text += f" الإجابة الصحيحة: {correct_option_emoji}"

    explanation = question.get("explanation")
    if explanation:
        feedback_text += f"\n\n**الشرح:**\n{process_text_with_chemical_notation(explanation)}"

    try:
        # Edit the original question message to show feedback
        # Remove the keyboard by setting reply_markup=None
        query.edit_message_text(text=query.message.text_markdown + f"\n\n---\n{feedback_text}",
                                reply_markup=None, parse_mode=ParseMode.MARKDOWN)
    except BadRequest as e:
        logger.warning(f"Could not edit message for feedback (maybe no change or deleted?): {e}")
        # Send feedback as a new message if editing fails
        safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.exception(f"Unexpected error editing message for feedback: {e}")
        # Send feedback as a new message if editing fails
        safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)

    # --- Move to Next Question or End Quiz --- #
    next_question_index = question_index + 1
    if next_question_index < len(quiz_data["questions"]):
        # Schedule sending the next question after a short delay
        context.job_queue.run_once(
            lambda ctx: send_question(chat_id, user_id, quiz_id, next_question_index, ctx),
            FEEDBACK_DELAY,
            context=context # Pass the main context
        )
        return TAKING_QUIZ
    else:
        # End of quiz
        logger.info(f"User {user_id} finished quiz {quiz_id}.")
        context.job_queue.run_once(
            lambda ctx: show_results(chat_id, user_id, quiz_id, ctx),
            FEEDBACK_DELAY,
            context=context
        )
        return SHOWING_RESULTS

def handle_quiz_skip(update_or_chat_id, context_or_user_id, quiz_id_maybe, question_index_maybe=None, context_maybe=None, timed_out=False, error_skip=False):
    """Handles skipping a question (via button, timeout, or error)."""

    # Adapt based on how it's called (callback vs timer/error)
    if isinstance(update_or_chat_id, Update):
        # Called by button press
        query = update_or_chat_id.callback_query
        query.answer()
        user_id = update_or_chat_id.effective_user.id
        chat_id = update_or_chat_id.effective_chat.id
        context = context_or_user_id # context is the second arg here
        try:
            _, quiz_id, q_index_str = query.data.split("_")
            question_index = int(q_index_str)
        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing quiz skip callback data ", query.data, f": {e}")
            query.edit_message_text(text="حدث خطأ في معالجة طلب التخطي.")
            return TAKING_QUIZ
        logger.info(f"User {user_id} skipped question {question_index} for quiz {quiz_id}.")
        skip_source = "user"
    else:
        # Called by timer or error handler
        chat_id = update_or_chat_id
        user_id = context_or_user_id
        quiz_id = quiz_id_maybe
        question_index = question_index_maybe
        context = context_maybe
        if timed_out:
            logger.info(f"Question {question_index} timed out for quiz {quiz_id}, user {user_id}.")
            skip_source = "timeout"
        elif error_skip:
            logger.info(f"Skipping question {question_index} due to error for quiz {quiz_id}, user {user_id}.")
            skip_source = "error"
        else:
             logger.warning(f"handle_quiz_skip called without valid source. Quiz: {quiz_id}, Q: {question_index}")
             return TAKING_QUIZ # Should not happen

    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    # --- Validate Quiz State --- #
    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.warning(f"Attempted skip for inactive/mismatched quiz {quiz_id}. User: {user_id}")
        if isinstance(update_or_chat_id, Update):
            query.edit_message_text(text="يبدو أن هذا الاختبار لم يعد نشطاً.")
        return MAIN_MENU

    if question_index != quiz_data["current_question_index"]:
        logger.warning(f"Attempted skip for question {question_index} but current is {quiz_data['current_question_index']}. Quiz: {quiz_id}, User: {user_id}")
        if isinstance(update_or_chat_id, Update):
            try:
                query.edit_message_text(text="لقد تم بالفعل الإجابة على هذا السؤال أو تخطيه.")
            except BadRequest:
                pass
        return TAKING_QUIZ

    # --- Process Skip --- #
    # Cancel the question timer if skipped by user or error
    if skip_source in ["user", "error"] and quiz_data.get("question_timer_job_name"):
        remove_job_if_exists(quiz_data["question_timer_job_name"], context)
        quiz_data["question_timer_job_name"] = None

    question = quiz_data["questions"][question_index]
    correct_answer_index = question["correct_answer"]

    # Mark as skipped in answers
    quiz_data["answers"][question_index] = {
        "selected": None, # Mark as skipped
        "correct": correct_answer_index,
        "is_correct": False # Skipped is considered incorrect for scoring
    }

    # --- Provide Feedback (Different for skip/timeout) --- #
    if skip_source == "user":
        feedback_text = f"⏭️ تم تخطي السؤال {question_index + 1}."
    elif skip_source == "timeout":
        feedback_text = f"⏰ انتهى وقت السؤال {question_index + 1} (تم تخطيه)."
    elif skip_source == "error":
        feedback_text = f"⚠️ تم تخطي السؤال {question_index + 1} بسبب خطأ."
    else:
        feedback_text = f"تم تخطي السؤال {question_index + 1}."

    correct_option_emoji = chr(ord('🇦') + correct_answer_index)
    feedback_text += f" الإجابة الصحيحة كانت: {correct_option_emoji}"

    explanation = question.get("explanation")
    if explanation:
        feedback_text += f"\n\n**الشرح:**\n{process_text_with_chemical_notation(explanation)}"

    # Edit message if skipped via button, send new if via timer/error
    if isinstance(update_or_chat_id, Update):
        try:
            query.edit_message_text(text=query.message.text_markdown + f"\n\n---\n{feedback_text}",
                                    reply_markup=None, parse_mode=ParseMode.MARKDOWN)
        except BadRequest as e:
            logger.warning(f"Could not edit message for skip feedback: {e}")
            safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.exception(f"Unexpected error editing message for skip feedback: {e}")
            safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)
    else:
        # Send feedback as a new message for timer/error skips
        safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)

    # --- Move to Next Question or End Quiz --- #
    next_question_index = question_index + 1
    if next_question_index < len(quiz_data["questions"]):
        # Schedule sending the next question after a short delay
        context.job_queue.run_once(
            lambda ctx: send_question(chat_id, user_id, quiz_id, next_question_index, ctx),
            FEEDBACK_DELAY,
            context=context
        )
        return TAKING_QUIZ
    else:
        # End of quiz
        logger.info(f"User {user_id} finished quiz {quiz_id} after skipping last question.")
        context.job_queue.run_once(
            lambda ctx: show_results(chat_id, user_id, quiz_id, ctx),
            FEEDBACK_DELAY,
            context=context
        )
        return SHOWING_RESULTS

def show_results(chat_id: int, user_id: int, quiz_id: str, context: CallbackContext, timed_out: bool = False, error_occurred: bool = False):
    """Calculates and displays the quiz results."""
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.warning(f"Attempted to show results for inactive/mismatched quiz {quiz_id}. User: {user_id}")
        # Don't send error message here, might be called after cleanup
        return SHOWING_RESULTS # Or MAIN_MENU?

    score = quiz_data["score"]
    total_questions = len(quiz_data["questions"])
    answers = quiz_data["answers"]
    quiz_details_str = quiz_data.get("quiz_details_str", "الاختبار الحالي")
    # Check for errors flagged during the quiz
    error_occurred = error_occurred or quiz_data.get("error_occurred", False)

    percentage = (score / total_questions * 100) if total_questions > 0 else 0

    result_message = f"🏁 **نتائج الاختبار: {quiz_details_str}** 🏁\n\n"
    result_message += f"✨ نتيجتك: {score} من {total_questions} ({percentage:.1f}%)\n"

    if timed_out:
        result_message += "\n⏰ *انتهى وقت الاختبار.*
"
    elif error_occurred:
        result_message += "\n⚠️ *حدث خطأ أثناء الاختبار، قد تكون النتيجة غير مكتملة.*
"

    # Optional: Add details about correct/incorrect answers
    # result_message += "\n**تفاصيل الإجابات:**\n"
    # for i in range(total_questions):
    #     answer_data = answers.get(i)
    #     status = "لم تتم الإجابة" # Default
    #     if answer_data:
    #         if answer_data["selected"] is None:
    #             status = "تم التخطي ⏭️"
    #         elif answer_data["is_correct"]:
    #             status = "صحيحة ✅"
    #         else:
    #             status = "خاطئة ❌"
    #     result_message += f"السؤال {i+1}: {status}\n"

    # Save results to database
    if QUIZ_DB and not error_occurred:
        try:
            QUIZ_DB.save_result(user_id, quiz_id, score, total_questions, quiz_details_str)
            logger.info(f"Saved results for quiz {quiz_id}, user {user_id}.")
        except Exception as e:
            logger.error(f"Failed to save results for quiz {quiz_id}, user {user_id}: {e}")
            result_message += "\n⚠️ *لا يمكن حفظ نتيجتك حالياً (مشكلة في قاعدة البيانات).*"
    elif error_occurred:
         logger.warning(f"Not saving results for quiz {quiz_id} due to error_occurred flag.")
    else:
        logger.warning(f"QUIZ_DB not available. Cannot save results for quiz {quiz_id}, user {user_id}.")
        result_message += "\n⚠️ *لا يمكن حفظ نتيجتك حالياً (مشكلة في قاعدة البيانات).*"

    # Clean up quiz data from user_data
    if "current_quiz" in user_data:
        del user_data["current_quiz"]
        logger.info(f"Cleaned up quiz data for user {user_id} after showing results.")

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 إجراء اختبار آخر", callback_data="menu_quiz")],
        [InlineKeyboardButton("📊 عرض التقارير", callback_data="menu_reports")],
        [InlineKeyboardButton("🏠 العودة للقائمة الرئيسية", callback_data="main_menu")]
    ])
    safe_send_message(context.bot, chat_id, text=result_message, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    return SHOWING_RESULTS # Stay in this state until user navigates away

# --- Admin Handlers (Placeholders - To be implemented if needed) ---

def admin_menu_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        query.edit_message_text(text="عذراً، هذه المنطقة مخصصة للمشرف فقط.")
        return MAIN_MENU

    logger.info(f"Admin user {user_id} accessed admin menu.")
    keyboard = InlineKeyboardMarkup([
        # Add admin options here later if needed (e.g., manage questions, users)
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
    ])
    query.edit_message_text(text="⚙️ قائمة الإدارة ⚙️\n\n(الوظائف الإدارية لم تنفذ بعد)", reply_markup=keyboard)
    return ADMIN_MENU

# --- Error Handler ---

def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # Optionally, notify the user or admin about the error
    if isinstance(update, Update):
        chat_id = update.effective_chat.id
        if chat_id:
            try:
                safe_send_message(context.bot, chat_id, text="حدث خطأ غير متوقع أثناء معالجة طلبك. يرجى المحاولة مرة أخرى لاحقاً.")
            except Exception as e:
                logger.error(f"Failed to send error message to chat {chat_id}: {e}")

    # You could also send a detailed error report to the admin
    # try:
    #     admin_chat_id = ADMIN_USER_ID
    #     tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    #     tb_string = "".join(tb_list)
    #     update_str = update.to_dict() if isinstance(update, Update) else str(update)
    #     message = (
    #         f"An exception was raised while handling an update\n"
    #         f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}</pre>\n\n"
    #         f"<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n"
    #         f"<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n"
    #         f"<pre>{html.escape(tb_string)}</pre>"
    #     )
    #     context.bot.send_message(chat_id=admin_chat_id, text=message, parse_mode=ParseMode.HTML)
    # except Exception as e:
    #     logger.error(f"Failed to send detailed error report to admin {admin_chat_id}: {e}")

# --- Main Function (Modified for Polling) ---

def main() -> None:
    """Start the bot using Polling."""
    logger.info("[DIAG] Script execution started.")

    # Create the Updater and pass it your bot's token.
    updater = Updater(BOT_TOKEN)
    logger.debug("[DIAG] Updater created.")

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher
    logger.debug("[DIAG] Dispatcher obtained.")

    # --- Register Handlers ---

    # Log all updates for debugging
    dispatcher.add_handler(MessageHandler(Filters.all, log_update), group=-1) # Add to group -1 to log first
    logger.debug("[DIAG] Catch-all update logger handler added.")

    # Conversation handler for main logic
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(main_menu_button, pattern="^menu_"),
                CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"), # Handle direct back to main menu
            ],
            INFO_MENU: [
                CallbackQueryHandler(info_course_callback, pattern="^info_course_"),
                CallbackQueryHandler(info_unit_callback, pattern="^info_unit_"),
                # CallbackQueryHandler(info_lesson_callback, pattern="^info_lesson_"), # Not implemented yet
                CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"),
                CallbackQueryHandler(info_menu_callback, pattern="^menu_info$"), # Back to course list
            ],
            QUIZ_MENU: [
                CallbackQueryHandler(quiz_type_random_callback, pattern="^quiz_type_random$"),
                CallbackQueryHandler(quiz_select_course_callback, pattern="^quiz_select_course$"),
                CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"),
            ],
            SELECT_COURSE_FOR_QUIZ: [
                CallbackQueryHandler(quiz_course_selected_callback, pattern="^quiz_course_"),
                CallbackQueryHandler(quiz_menu_callback, pattern="^menu_quiz$"), # Back to quiz type selection
                CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"), # Back to main menu
            ],
            SELECT_UNIT_FOR_QUIZ: [
                CallbackQueryHandler(quiz_unit_selected_callback, pattern="^quiz_unit_"),
                CallbackQueryHandler(quiz_select_course_callback, pattern="^quiz_select_course$"), # Back to course selection
                CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"), # Back to main menu
            ],
            SELECT_LESSON_FOR_QUIZ_HIERARCHY: [
                CallbackQueryHandler(quiz_lesson_selected_callback, pattern="^quiz_lesson_"),
                CallbackQueryHandler(quiz_course_selected_callback, pattern="^quiz_course_"), # Back to unit selection (needs course_id)
                 # Need to handle back button properly here, maybe store course_id in callback?
                 # For now, going back to course selection might be acceptable
                 CallbackQueryHandler(quiz_select_course_callback, pattern="^quiz_select_course$"),
                 CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"), # Back to main menu
            ],
            SELECT_QUESTION_COUNT: [
                CallbackQueryHandler(question_count_callback, pattern="^q_count_"),
                MessageHandler(Filters.text & ~Filters.command, question_count_manual_input),
                # Back button handlers need to be specific based on previous state
                CallbackQueryHandler(quiz_menu_callback, pattern="^menu_quiz$"), # Back from random quiz
                CallbackQueryHandler(quiz_unit_selected_callback, pattern="^quiz_unit_"), # Back from lesson quiz (needs unit/course id)
                 # Add more specific back handlers if needed
                 CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"), # General backstop
            ],
            TAKING_QUIZ: [
                CallbackQueryHandler(handle_quiz_answer, pattern="^quiz_answer_"),
                CallbackQueryHandler(handle_quiz_skip, pattern="^quiz_skip_"),
            ],
            SHOWING_RESULTS: [
                CallbackQueryHandler(quiz_menu_callback, pattern="^menu_quiz$"),
                CallbackQueryHandler(reports_menu_callback, pattern="^menu_reports$"),
                CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"),
            ],
            SHOWING_REPORTS: [
                CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"),
            ],
            ADMIN_MENU: [
                # Add admin state handlers here
                CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"),
            ],
            # Add other states (ADDING_QUESTION etc.) if admin features are implemented
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
        # Allow re-entry into the conversation with /start or /cancel
        allow_reentry=True
    )
    dispatcher.add_handler(conv_handler)
    logger.debug("[DIAG] ConversationHandler added to dispatcher.")

    # log all errors
    dispatcher.add_error_handler(error_handler)
    logger.debug("[DIAG] Error handler added.")

    # Start the Bot using Polling
    logger.info("Starting bot using Polling...")
    updater.start_polling()
    logger.info("Bot started successfully using Polling.")

    # Run the bot until you press Ctrl-C
    updater.idle()

    logger.info("Bot stopped.")

if __name__ == "__main__":
    main()

