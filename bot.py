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

    if not hasattr(context, "dispatcher"):
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

    if not hasattr(context, "dispatcher"):
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

def create_quiz_options_keyboard(options_text, options_images, question_id):
    """Creates the keyboard with quiz options (text or image)."""
    buttons = []
    option_labels = ["A", "B", "C", "D"]
    has_text_options = any(opt for opt in options_text if opt)
    has_image_options = any(opt for opt in options_images if opt)

    if has_text_options:
        for i, text in enumerate(options_text):
            if text:
                buttons.append(InlineKeyboardButton(f"{option_labels[i]}. {text}", callback_data=f"quiz_answer_{question_id}_{i}"))
    elif has_image_options:
        # If only images, use labels A, B, C, D
        for i, img in enumerate(options_images):
            if img:
                buttons.append(InlineKeyboardButton(option_labels[i], callback_data=f"quiz_answer_{question_id}_{i}"))
    else:
        # Fallback if somehow no options are valid (should not happen with validation)
        logger.error(f"Question {question_id} has no valid text or image options for keyboard.")
        return None

    # Always add skip button
    buttons.append(InlineKeyboardButton("⏭️ تخطي السؤال", callback_data=f"quiz_skip_{question_id}"))

    # Arrange buttons in rows (max 2 per row for text, 4 for image labels)
    max_cols = 2 if has_text_options else 4
    keyboard = [buttons[i:i + max_cols] for i in range(0, len(buttons) -1, max_cols)] # Group options
    keyboard.append([buttons[-1]]) # Add skip button in its own row

    return InlineKeyboardMarkup(keyboard)

def create_back_button(callback_data):
    """Creates a standard back button."""
    return InlineKeyboardButton("🔙 عودة", callback_data=callback_data)

def create_back_to_main_menu_button():
    """Creates a button to go back to the main menu."""
    return InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")

def create_pagination_keyboard(items: list, current_page: int, items_per_page: int, callback_prefix: str, back_callback: str, extra_params: str = "") -> InlineKeyboardMarkup:
    """Creates a paginated keyboard for lists (courses, units, lessons)."""
    keyboard = []
    total_items = len(items)
    total_pages = math.ceil(total_items / items_per_page)
    start_index = current_page * items_per_page
    end_index = start_index + items_per_page

    # Add item buttons for the current page
    for i in range(start_index, min(end_index, total_items)):
        item = items[i]
        # Ensure item has 'id' and 'name'
        if isinstance(item, dict) and 'id' in item and 'name' in item:
            button_callback = f"{callback_prefix}_{item['id']}{extra_params}"
            keyboard.append([InlineKeyboardButton(item['name'], callback_data=button_callback)])
        else:
            logger.warning(f"Skipping item in pagination due to missing 'id' or 'name': {item}")

    # Add navigation buttons
    nav_buttons = []
    if current_page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"page_{current_page - 1}_{callback_prefix}{extra_params}"))
    if current_page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️ التالي", callback_data=f"page_{current_page + 1}_{callback_prefix}{extra_params}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    # Add back button
    keyboard.append([create_back_button(back_callback)])

    return InlineKeyboardMarkup(keyboard)

def create_question_count_keyboard(callback_prefix: str, max_questions: int) -> InlineKeyboardMarkup:
    """Creates keyboard for selecting number of questions."""
    buttons = []
    options = [10, 20, 30]
    valid_options = [opt for opt in options if opt <= max_questions]

    row = []
    for count in valid_options:
        row.append(InlineKeyboardButton(str(count), callback_data=f"{callback_prefix}_{count}"))
    if row:
        buttons.append(row)

    # Always add 'Enter Manually' if max_questions > 0
    if max_questions > 0:
        buttons.append([InlineKeyboardButton("⌨️ إدخال يدوي", callback_data=f"{callback_prefix}_manual")])

    # Determine the correct back button based on the prefix
    if callback_prefix.startswith("q_count_random"):
        back_callback = "menu_quiz"
    elif callback_prefix.startswith("q_count_course"):
        # Extract course_id from prefix like "q_count_course_123"
        try:
            course_id = int(callback_prefix.split('_')[-1])
            back_callback = f"quiz_select_course_page_0" # Go back to course list
        except (ValueError, IndexError):
            logger.error(f"Could not parse course_id from q_count prefix: {callback_prefix}")
            back_callback = "menu_quiz" # Fallback
    elif callback_prefix.startswith("q_count_unit"):
        # Extract course_id and unit_id from prefix like "q_count_unit_123_456"
        try:
            parts = callback_prefix.split('_')
            course_id = int(parts[-2])
            unit_id = int(parts[-1])
            back_callback = f"quiz_select_unit_{course_id}_page_0" # Go back to unit list for that course
        except (ValueError, IndexError):
            logger.error(f"Could not parse course/unit_id from q_count prefix: {callback_prefix}")
            back_callback = "menu_quiz" # Fallback
    elif callback_prefix.startswith("q_count_lesson"):
        # Extract course_id, unit_id, lesson_id from prefix like "q_count_lesson_123_456_789"
        try:
            parts = callback_prefix.split('_')
            course_id = int(parts[-3])
            unit_id = int(parts[-2])
            lesson_id = int(parts[-1])
            back_callback = f"quiz_select_lesson_{course_id}_{unit_id}_page_0" # Go back to lesson list for that unit
        except (ValueError, IndexError):
            logger.error(f"Could not parse course/unit/lesson_id from q_count prefix: {callback_prefix}")
            back_callback = "menu_quiz" # Fallback
    else:
        back_callback = "menu_quiz" # Default fallback

    buttons.append([create_back_button(back_callback)])
    return InlineKeyboardMarkup(buttons)

# --- Command Handlers ---

def start(update: Update, context: CallbackContext) -> int:
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user.id
    name = get_user_name(user)
    logger.info(f"[DIAG] Received /start command from user {user_id} ({name}) in chat {chat_id}.")

    # Register user if not already registered
    if QUIZ_DB:
        try:
            logger.debug(f"[DIAG] Checking/Registering user {user_id}...")
            QUIZ_DB.register_user(user_id, name)
            logger.info(f"User {user_id} ({name}) registered or already exists.")
        except Exception as e:
            logger.error(f"Error registering user {user_id}: {e}")
            # Continue even if registration fails, but log the error
    else:
        logger.warning("QUIZ_DB not initialized. Cannot register user.")

    # Reset any ongoing quiz or conversation state
    context.user_data.pop("current_quiz", None)
    logger.debug(f"[DIAG] Cleared current_quiz for user {user_id}.")

    keyboard = create_main_menu_keyboard(user_id)
    welcome_message = f"أهلاً بك يا {name}! 👋\n\nأنا بوت الكيمياء التعليمي. ماذا تريد أن تفعل اليوم؟"
    logger.debug(f"[DIAG] Sending welcome message and main menu to user {user_id}.")
    safe_send_message(context.bot, chat_id, text=welcome_message, reply_markup=keyboard)
    return MAIN_MENU

def help_command(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id
    logger.info(f"User {user.id} requested help in chat {chat_id}.")
    help_text = (
        "🤖 **مساعدة بوت الكيمياء** 🤖\n\n"
        "استخدم الأزرار للتنقل بين الأقسام:\n"
        "- **📚 المعلومات الكيميائية:** استعرض معلومات حول العناصر والمركبات والمفاهيم (قيد التطوير).\n"
        "- **📝 الاختبارات:** اختبر معلوماتك في الكيمياء باختبارات عامة أو مخصصة.\n"
        "- **📊 تقارير الأداء:** اطلع على نتائج اختباراتك السابقة.\n"
        "- **ℹ️ حول البوت:** معلومات عن البوت وميزاته.\n\n"
        "**أوامر إضافية:**\n"
        "- `/start` - لبدء محادثة جديدة أو العودة للقائمة الرئيسية.\n"
        "- `/help` - لعرض هذه الرسالة.\n"
        "- `/cancel` - لإلغاء أي عملية جارية (مثل الاختبار أو إدخال عدد الأسئلة)."
    )
    safe_send_message(context.bot, chat_id, text=help_text, parse_mode=ParseMode.MARKDOWN)

def cancel(update: Update, context: CallbackContext) -> int:
    user = update.effective_user
    chat_id = update.effective_chat.id
    logger.info(f"User {user.id} initiated /cancel in chat {chat_id}.")

    # Check if a quiz is active and stop it
    quiz_data = context.user_data.get("current_quiz")
    if quiz_data:
        quiz_id = quiz_data.get("quiz_id")
        logger.info(f"Cancelling active quiz {quiz_id} for user {user.id}.")
        # Remove timers
        if quiz_data.get("quiz_timer_job_name"):
            remove_job_if_exists(quiz_data["quiz_timer_job_name"], context)
        if quiz_data.get("question_timer_job_name"):
            remove_job_if_exists(quiz_data["question_timer_job_name"], context)
        context.user_data.pop("current_quiz", None)
        safe_send_message(context.bot, chat_id, text="تم إلغاء الاختبار الحالي.")
    else:
        safe_send_message(context.bot, chat_id, text="تم إلغاء العملية الحالية.")

    # Send main menu again
    keyboard = create_main_menu_keyboard(user.id)
    safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=keyboard)
    return MAIN_MENU

# --- Callback Query Handlers ---

def main_menu_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    logger.info(f"User {user_id} returned to main menu via callback.")
    query.answer()
    keyboard = create_main_menu_keyboard(user_id)
    try:
        query.edit_message_text(text="القائمة الرئيسية:", reply_markup=keyboard)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info("Main menu message not modified.")
        else:
            logger.error(f"Error editing message to main menu: {e}")
            # Fallback: Send new message if editing fails
            safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Unexpected error editing message to main menu: {e}")
        safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=keyboard)
    return MAIN_MENU

def about_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    logger.info(f"User {user_id} requested 'About'.")
    query.answer()
    about_text = """🤖 **بوت الكيمياء التعليمي** 🤖

هذا البوت مصمم لمساعدتك في تعلم الكيمياء من خلال:

*   **📝 اختبارات متنوعة:**
    *   اختبارات عامة شاملة.
    *   اختبارات مخصصة حسب المقرر الدراسي، الوحدة، أو الدرس.
    *   اختيار عدد الأسئلة.
    *   مؤقت لكل سؤال لتحدي إضافي.
*   **📚 معلومات كيميائية:** (قيد التطوير) استعراض معلومات حول العناصر، المركبات، والمفاهيم.
*   **📊 تقارير الأداء:** تتبع نتائج اختباراتك السابقة.

تم تطوير هذا البوت بواسطة [اسم المطور/الفريق].
نأمل أن يكون مفيداً في رحلتك التعليمية! ✨
"""
    keyboard = InlineKeyboardMarkup([[create_back_to_main_menu_button()]])
    try:
        query.edit_message_text(text=about_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info("About message not modified.")
        else:
            logger.error(f"Error editing message to About: {e}")
            safe_send_message(context.bot, query.message.chat_id, text=about_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Unexpected error editing message to About: {e}")
        safe_send_message(context.bot, query.message.chat_id, text=about_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    return MAIN_MENU # Stay in main menu context

def info_menu_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    logger.info(f"User {user_id} requested 'Info Menu'.")
    query.answer()
    # --- Placeholder for Info Menu --- 
    # This section needs to be implemented based on how info is structured.
    # Example: Fetch list of informational topics/categories from API?
    info_text = """📚 قسم المعلومات الكيميائية (قيد التطوير).

سيتم هنا عرض معلومات حول العناصر، المركبات، والمفاهيم الكيميائية."""
    keyboard = InlineKeyboardMarkup([[create_back_to_main_menu_button()]])
    try:
        query.edit_message_text(text=info_text, reply_markup=keyboard)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info("Info menu message not modified.")
        else:
            logger.error(f"Error editing message to Info Menu: {e}")
            safe_send_message(context.bot, query.message.chat_id, text=info_text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Unexpected error editing message to Info Menu: {e}")
        safe_send_message(context.bot, query.message.chat_id, text=info_text, reply_markup=keyboard)
    # --- End Placeholder --- 
    return INFO_MENU # Or back to MAIN_MENU if no further interaction

def reports_menu_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    logger.info(f"User {user_id} requested 'Reports Menu'.")
    query.answer()

    if not QUIZ_DB:
        error_text = "عذراً، لا يمكن عرض التقارير حالياً بسبب مشكلة في الاتصال بقاعدة البيانات."
        kb = InlineKeyboardMarkup([[create_back_to_main_menu_button()]])
        try:
            query.edit_message_text(text=error_text, reply_markup=kb)
        except Exception as e:
            logger.error(f"Error editing message for DB connection error in reports: {e}")
            safe_send_message(context.bot, chat_id, text=error_text, reply_markup=kb)
        return MAIN_MENU

    try:
        logger.debug(f"Fetching reports for user {user_id}")
        results = QUIZ_DB.get_user_results(user_id, limit=10) # Get last 10 results
        logger.debug(f"Fetched {len(results)} results.")

        if not results:
            report_text = "📊 لم تقم بإجراء أي اختبارات بعد."
        else:
            report_text = "📊 **آخر نتائج اختباراتك:**\n\n"
            for i, res in enumerate(results):
                # Safely access dictionary keys
                quiz_type = res.get('quiz_type', 'غير معروف')
                score = res.get('score')
                total_questions = res.get('total_questions')
                timestamp = res.get('timestamp') # Already a datetime object

                # Format timestamp
                try:
                    # Format timestamp to a readable string (e.g., YYYY-MM-DD HH:MM)
                    timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M") if timestamp else "غير معروف"
                except AttributeError:
                    timestamp_str = str(timestamp) if timestamp else "غير معروف"
                    logger.warning(f"Timestamp for result {res.get('result_id')} is not a datetime object: {timestamp}")

                # Format score/total
                score_str = f"{score}/{total_questions}" if score is not None and total_questions is not None else "غير متوفرة"

                # Format quiz type (make it more readable)
                quiz_type_readable = quiz_type.replace('_', ' ').title()
                if 'Random' in quiz_type_readable: quiz_type_readable = "اختبار عام"
                elif 'Course' in quiz_type_readable: quiz_type_readable = f"مقرر {quiz_type.split('_')[-1]}"
                elif 'Unit' in quiz_type_readable: quiz_type_readable = f"وحدة {quiz_type.split('_')[-1]}"
                elif 'Lesson' in quiz_type_readable: quiz_type_readable = f"درس {quiz_type.split('_')[-1]}"

                report_text += f"**{i+1}.** {quiz_type_readable} ({timestamp_str}) - النتيجة: **{score_str}**\n"

        keyboard = InlineKeyboardMarkup([[create_back_to_main_menu_button()]])
        try:
            query.edit_message_text(text=report_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        except BadRequest as e:
            if "Message is not modified" in str(e):
                logger.info("Reports message not modified.")
            else:
                logger.error(f"Error editing message to Reports: {e}")
                safe_send_message(context.bot, chat_id, text=report_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Unexpected error editing message to Reports: {e}")
            safe_send_message(context.bot, chat_id, text=report_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Error fetching or formatting reports for user {user_id}: {e}")
        error_text = "حدث خطأ أثناء جلب تقاريرك. يرجى المحاولة مرة أخرى لاحقاً."
        kb = InlineKeyboardMarkup([[create_back_to_main_menu_button()]])
        try:
            query.edit_message_text(text=error_text, reply_markup=kb)
        except Exception as edit_e:
            logger.error(f"Error editing message for report fetching error: {edit_e}")
            safe_send_message(context.bot, chat_id, text=error_text, reply_markup=kb)

    return SHOWING_REPORTS # Stay in reports state (or back to MAIN_MENU)

# --- Quiz Selection Handlers (Hierarchical) ---

def quiz_menu_callback(update: Update, context: CallbackContext) -> int:
    """Handles the main quiz menu button press."""
    query = update.callback_query
    user_id = query.from_user.id
    logger.info(f"User {user_id} selected 'Quiz Menu'.")
    query.answer()
    keyboard = create_quiz_menu_keyboard()
    try:
        query.edit_message_text(text="📝 اختر نوع الاختبار:", reply_markup=keyboard)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info("Quiz menu message not modified.")
        else:
            logger.error(f"Error editing message to Quiz Menu: {e}")
            safe_send_message(context.bot, query.message.chat_id, text="📝 اختر نوع الاختبار:", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Unexpected error editing message to Quiz Menu: {e}")
        safe_send_message(context.bot, query.message.chat_id, text="📝 اختر نوع الاختبار:", reply_markup=keyboard)
    return QUIZ_MENU

def handle_pagination_callback(update: Update, context: CallbackContext) -> int:
    """Handles all pagination button clicks (Next/Previous)."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    logger.info(f"User {user_id} clicked pagination: {data}")
    query.answer()

    try:
        parts = data.split('_')
        page = int(parts[1])
        callback_type = parts[2]
        extra_params_list = parts[3:] # Can be course_id, unit_id etc.
        extra_params_str = "_" + "_".join(extra_params_list) if extra_params_list else ""
        extra_params_ids = [int(p) for p in extra_params_list if p.isdigit()] # Extract IDs

        logger.debug(f"Pagination: page={page}, type={callback_type}, params={extra_params_ids}")

        if callback_type == "course":
            return select_course_for_quiz(update, context, page=page)
        elif callback_type == "unit":
            if len(extra_params_ids) >= 1:
                course_id = extra_params_ids[0]
                return select_unit_for_quiz(update, context, course_id=course_id, page=page)
            else:
                raise ValueError("Missing course_id for unit pagination")
        elif callback_type == "lesson":
            if len(extra_params_ids) >= 2:
                course_id = extra_params_ids[0]
                unit_id = extra_params_ids[1]
                return select_lesson_for_quiz(update, context, course_id=course_id, unit_id=unit_id, page=page)
            else:
                raise ValueError("Missing course_id or unit_id for lesson pagination")
        else:
            raise ValueError(f"Unknown pagination type: {callback_type}")

    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing pagination callback data '{data}': {e}")
        safe_send_message(context.bot, query.message.chat_id, text="حدث خطأ في التنقل بين الصفحات.")
        # Go back to quiz menu as a fallback
        keyboard = create_quiz_menu_keyboard()
        try:
            query.edit_message_text(text="📝 اختر نوع الاختبار:", reply_markup=keyboard)
        except Exception as edit_e:
             logger.error(f"Error editing message on pagination error fallback: {edit_e}")
        return QUIZ_MENU

def select_course_for_quiz(update: Update, context: CallbackContext, page: int = 0) -> int:
    """Displays the list of courses for quiz selection."""
    query = update.callback_query
    user_id = query.from_user.id if query else update.effective_user.id
    chat_id = query.message.chat_id if query else update.effective_chat.id
    logger.info(f"User {user_id} is selecting a course (page {page}).")
    if query: query.answer()

    courses = fetch_from_api("/courses")

    if courses == "TIMEOUT":
        error_text = "⏳ لا يمكن جلب قائمة المقررات حالياً (انتهت مهلة الاتصال). يرجى المحاولة مرة أخرى لاحقاً."
        kb = InlineKeyboardMarkup([[create_back_button("menu_quiz")]])
    elif courses is None or not isinstance(courses, list):
        error_text = "⚠️ لا يمكن جلب قائمة المقررات حالياً. يرجى المحاولة مرة أخرى لاحقاً."
        kb = InlineKeyboardMarkup([[create_back_button("menu_quiz")]])
    elif not courses:
        error_text = "📚 لا توجد مقررات متاحة حالياً."
        kb = InlineKeyboardMarkup([[create_back_button("menu_quiz")]])
    else:
        # Success - create pagination
        keyboard = create_pagination_keyboard(
            items=courses,
            current_page=page,
            items_per_page=5,
            callback_prefix="quiz_select_unit", # Next step is selecting unit
            back_callback="menu_quiz"
        )
        message_text = "📄 اختر المقرر الدراسي:"
        try:
            if query:
                query.edit_message_text(text=message_text, reply_markup=keyboard)
            else: # Should not happen in normal flow, but handle direct call
                safe_send_message(context.bot, chat_id, text=message_text, reply_markup=keyboard)
            return SELECT_COURSE_FOR_QUIZ
        except BadRequest as e:
            if "Message is not modified" in str(e):
                logger.info("Select course message not modified.")
                return SELECT_COURSE_FOR_QUIZ
            else:
                logger.error(f"Error editing message for course selection: {e}")
                error_text = "حدث خطأ أثناء عرض المقررات."
                kb = InlineKeyboardMarkup([[create_back_button("menu_quiz")]])
        except Exception as e:
            logger.error(f"Unexpected error editing message for course selection: {e}")
            error_text = "حدث خطأ أثناء عرض المقررات."
            kb = InlineKeyboardMarkup([[create_back_button("menu_quiz")]])

    # Handle errors or empty list
    try:
        if query:
            query.edit_message_text(text=error_text, reply_markup=kb)
        else:
            safe_send_message(context.bot, chat_id, text=error_text, reply_markup=kb)
    except Exception as e:
        logger.error(f"Error editing message for course selection error/empty: {e}")
        safe_send_message(context.bot, chat_id, text=error_text, reply_markup=kb)
    return QUIZ_MENU # Go back to quiz menu on error

def select_unit_for_quiz(update: Update, context: CallbackContext, course_id: int = None, page: int = 0) -> int:
    """Displays the list of units for a selected course."""
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    data = query.data
    logger.info(f"User {user_id} selecting unit (callback: {data}, page: {page}).")
    query.answer()

    # Extract course_id if not passed directly (e.g., from button click)
    if course_id is None:
        try:
            # Format: quiz_select_unit_{course_id}
            course_id = int(data.split('_')[-1])
        except (ValueError, IndexError):
            logger.error(f"Could not parse course_id from callback: {data}")
            safe_send_message(context.bot, chat_id, text="حدث خطأ في تحديد المقرر.")
            return select_course_for_quiz(update, context) # Go back to course selection

    logger.info(f"User {user_id} selecting unit for course {course_id} (page {page}).")
    units = fetch_from_api(f"/courses/{course_id}/units")

    if units == "TIMEOUT":
        error_text = "⏳ لا يمكن جلب قائمة الوحدات حالياً (انتهت مهلة الاتصال). يرجى المحاولة مرة أخرى لاحقاً."
        kb = InlineKeyboardMarkup([[create_back_button("quiz_select_course_page_0")]]) # Back to course list
    elif units is None or not isinstance(units, list):
        error_text = "⚠️ لا يمكن جلب قائمة الوحدات حالياً. يرجى المحاولة مرة أخرى لاحقاً."
        kb = InlineKeyboardMarkup([[create_back_button("quiz_select_course_page_0")]])
    elif not units:
        error_text = "📚 لا توجد وحدات متاحة لهذا المقرر حالياً."
        kb = InlineKeyboardMarkup([[create_back_button("quiz_select_course_page_0")]])
    else:
        # Success - create pagination
        keyboard = create_pagination_keyboard(
            items=units,
            current_page=page,
            items_per_page=5,
            callback_prefix="quiz_select_lesson", # Next step is selecting lesson
            back_callback="quiz_select_course_page_0", # Back to course list
            extra_params=f"_{course_id}" # Pass course_id for next step
        )
        message_text = f"📖 اختر الوحدة الدراسية (المقرر {course_id}):"
        try:
            query.edit_message_text(text=message_text, reply_markup=keyboard)
            return SELECT_UNIT_FOR_QUIZ
        except BadRequest as e:
            if "Message is not modified" in str(e):
                logger.info("Select unit message not modified.")
                return SELECT_UNIT_FOR_QUIZ
            else:
                logger.error(f"Error editing message for unit selection: {e}")
                error_text = "حدث خطأ أثناء عرض الوحدات."
                kb = InlineKeyboardMarkup([[create_back_button("quiz_select_course_page_0")]])
        except Exception as e:
            logger.error(f"Unexpected error editing message for unit selection: {e}")
            error_text = "حدث خطأ أثناء عرض الوحدات."
            kb = InlineKeyboardMarkup([[create_back_button("quiz_select_course_page_0")]])

    # Handle errors or empty list
    try:
        query.edit_message_text(text=error_text, reply_markup=kb)
    except Exception as e:
        logger.error(f"Error editing message for unit selection error/empty: {e}")
        safe_send_message(context.bot, chat_id, text=error_text, reply_markup=kb)
    return SELECT_COURSE_FOR_QUIZ # Go back to course selection on error

def select_lesson_for_quiz(update: Update, context: CallbackContext, course_id: int = None, unit_id: int = None, page: int = 0) -> int:
    """Displays the list of lessons for a selected unit."""
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    data = query.data
    logger.info(f"User {user_id} selecting lesson (callback: {data}, page: {page}).")
    query.answer()

    # Extract course_id and unit_id if not passed directly
    if course_id is None or unit_id is None:
        try:
            # Format: quiz_select_lesson_{course_id}_{unit_id}
            parts = data.split('_')
            course_id = int(parts[-2])
            unit_id = int(parts[-1])
        except (ValueError, IndexError):
            logger.error(f"Could not parse course_id/unit_id from callback: {data}")
            safe_send_message(context.bot, chat_id, text="حدث خطأ في تحديد الوحدة.")
            # Attempt to go back to unit selection for the course if possible
            try:
                # Try to extract course_id again for fallback
                course_id_fallback = int(data.split('_')[-2])
                return select_unit_for_quiz(update, context, course_id=course_id_fallback)
            except (ValueError, IndexError):
                return select_course_for_quiz(update, context) # Fallback to course selection

    logger.info(f"User {user_id} selecting lesson for course {course_id}, unit {unit_id} (page {page}).")
    lessons = fetch_from_api(f"/units/{unit_id}/lessons")

    # Define back callback to unit list page 0 for this course
    back_callback_units = f"quiz_select_unit_{course_id}_page_0"

    if lessons == "TIMEOUT":
        error_text = "⏳ لا يمكن جلب قائمة الدروس حالياً (انتهت مهلة الاتصال). يرجى المحاولة مرة أخرى لاحقاً."
        kb = InlineKeyboardMarkup([[create_back_button(back_callback_units)]])
    elif lessons is None or not isinstance(lessons, list):
        error_text = "⚠️ لا يمكن جلب قائمة الدروس حالياً. يرجى المحاولة مرة أخرى لاحقاً."
        kb = InlineKeyboardMarkup([[create_back_button(back_callback_units)]])
    elif not lessons:
        error_text = "📚 لا توجد دروس متاحة لهذه الوحدة حالياً."
        kb = InlineKeyboardMarkup([[create_back_button(back_callback_units)]])
    else:
        # Success - create pagination
        keyboard = create_pagination_keyboard(
            items=lessons,
            current_page=page,
            items_per_page=5,
            callback_prefix="q_count_lesson", # Next step is selecting question count
            back_callback=back_callback_units, # Back to unit list
            extra_params=f"_{course_id}_{unit_id}" # Pass course_id and unit_id
        )
        message_text = f"📝 اختر الدرس (المقرر {course_id}, الوحدة {unit_id}):"
        try:
            query.edit_message_text(text=message_text, reply_markup=keyboard)
            return SELECT_LESSON_FOR_QUIZ_HIERARCHY
        except BadRequest as e:
            if "Message is not modified" in str(e):
                logger.info("Select lesson message not modified.")
                return SELECT_LESSON_FOR_QUIZ_HIERARCHY
            else:
                logger.error(f"Error editing message for lesson selection: {e}")
                error_text = "حدث خطأ أثناء عرض الدروس."
                kb = InlineKeyboardMarkup([[create_back_button(back_callback_units)]])
        except Exception as e:
            logger.error(f"Unexpected error editing message for lesson selection: {e}")
            error_text = "حدث خطأ أثناء عرض الدروس."
            kb = InlineKeyboardMarkup([[create_back_button(back_callback_units)]])

    # Handle errors or empty list
    try:
        query.edit_message_text(text=error_text, reply_markup=kb)
    except Exception as e:
        logger.error(f"Error editing message for lesson selection error/empty: {e}")
        safe_send_message(context.bot, chat_id, text=error_text, reply_markup=kb)
    return SELECT_UNIT_FOR_QUIZ # Go back to unit selection on error

# --- Question Count Selection --- #

def select_question_count(update: Update, context: CallbackContext) -> int:
    """Handles selection of quiz type or specific lesson, leading to question count selection."""
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    data = query.data
    logger.info(f"User {user_id} initiating question count selection with callback: {data}")
    query.answer()

    quiz_params = {}
    callback_prefix_for_count = ""
    max_questions = 0
    error_occurred = False
    error_message = "حدث خطأ غير متوقع."
    back_callback_on_error = "menu_quiz"

    try:
        if data == "quiz_type_random":
            quiz_params = {"type": "random"}
            callback_prefix_for_count = "q_count_random"
            back_callback_on_error = "menu_quiz"
            # Fetch total number of questions available for random quiz
            count_data = fetch_from_api("/questions/count", params={"is_active": True})

        elif data.startswith("q_count_lesson"):
            # Format: q_count_lesson_{course_id}_{unit_id}_{lesson_id}
            parts = data.split('_')
            if len(parts) == 6:
                course_id = int(parts[3])
                unit_id = int(parts[4])
                lesson_id = int(parts[5])
                quiz_params = {"lesson_id": lesson_id}
                callback_prefix_for_count = f"q_count_lesson_{course_id}_{unit_id}_{lesson_id}"
                back_callback_on_error = f"quiz_select_lesson_{course_id}_{unit_id}_page_0" # Back to lesson list
                # Fetch count for this specific lesson
                count_data = fetch_from_api("/questions/count", params={"lesson_id": lesson_id, "is_active": True})
            else:
                raise ValueError("Invalid format for lesson question count callback")

        # Add handlers for course/unit level if needed in future
        # elif data.startswith("q_count_course"): ...
        # elif data.startswith("q_count_unit"): ...

        else:
            raise ValueError(f"Unknown callback for question count: {data}")

        # Process count_data
        if count_data == "TIMEOUT":
            error_occurred = True
            error_message = "⏳ لا يمكن تحديد عدد الأسئلة المتاحة (انتهت مهلة الاتصال)."
        elif count_data is None or not isinstance(count_data, dict) or 'count' not in count_data:
            error_occurred = True
            error_message = "⚠️ لا يمكن تحديد عدد الأسئلة المتاحة حالياً."
        else:
            max_questions = count_data['count']
            if max_questions == 0:
                error_occurred = True
                error_message = "⚠️ لا توجد أسئلة متاحة لهذا الاختيار حالياً."

    except (ValueError, IndexError, TypeError) as e:
        logger.error(f"Error parsing callback or fetching count for '{data}': {e}")
        error_occurred = True
        error_message = "حدث خطأ أثناء معالجة طلبك."

    # Handle errors or show question count selection
    if error_occurred:
        kb = InlineKeyboardMarkup([[create_back_button(back_callback_on_error)]])
        try:
            query.edit_message_text(text=error_message, reply_markup=kb)
        except Exception as edit_e:
            logger.error(f"Error editing message on count selection error: {edit_e}")
            safe_send_message(context.bot, chat_id, text=error_message, reply_markup=kb)
        # Determine state to return based on error context
        if back_callback_on_error == "menu_quiz": return QUIZ_MENU
        if back_callback_on_error.startswith("quiz_select_lesson"): return SELECT_LESSON_FOR_QUIZ_HIERARCHY
        # Add other fallbacks if course/unit levels are implemented
        return QUIZ_MENU # Default fallback
    else:
        # Store quiz parameters and max questions for the next step
        context.user_data["quiz_selection_params"] = quiz_params
        context.user_data["quiz_max_questions"] = max_questions

        message_text = f"🔢 كم عدد الأسئلة التي تريدها؟ (الحد الأقصى: {max_questions})"
        keyboard = create_question_count_keyboard(callback_prefix_for_count, max_questions)
        try:
            query.edit_message_text(text=message_text, reply_markup=keyboard)
            return SELECT_QUESTION_COUNT
        except Exception as edit_e:
            logger.error(f"Error editing message for question count selection: {edit_e}")
            safe_send_message(context.bot, chat_id, text=message_text, reply_markup=keyboard)
            return SELECT_QUESTION_COUNT

def handle_question_count_selection(update: Update, context: CallbackContext) -> int:
    """Handles button press for selecting question count (10, 20, 30, manual)."""
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    data = query.data
    logger.info(f"User {user_id} selected question count option: {data}")
    query.answer()

    max_questions = context.user_data.get("quiz_max_questions", 0)

    try:
        if data.endswith("_manual"):
            # Ask user to type the number
            context.user_data["awaiting_question_count"] = True
            message_text = f"⌨️ يرجى كتابة عدد الأسئلة المطلوب (بحد أقصى {max_questions}):"
            # Remove inline keyboard
            try:
                query.edit_message_text(text=message_text, reply_markup=None)
            except Exception as e:
                 logger.error(f"Error removing keyboard for manual count input: {e}")
                 safe_send_message(context.bot, chat_id, text=message_text)
            return SELECT_QUESTION_COUNT # Stay in this state, waiting for text input
        else:
            # Format: q_count_random_10, q_count_lesson_1_2_3_20, etc.
            parts = data.split('_')
            count = int(parts[-1])

            if count <= 0:
                 raise ValueError("Question count must be positive.")
            if count > max_questions:
                # This shouldn't happen if keyboard is generated correctly, but double-check
                logger.warning(f"User {user_id} selected {count} questions, exceeding max {max_questions}. Clamping.")
                count = max_questions

            # We have the count, proceed to start the quiz
            quiz_params = context.user_data.get("quiz_selection_params", {})
            return start_quiz(update, context, quiz_params, count)

    except (ValueError, IndexError, TypeError) as e:
        logger.error(f"Error parsing question count callback data '{data}': {e}")
        safe_send_message(context.bot, chat_id, text="حدث خطأ في تحديد عدد الأسئلة. يرجى المحاولة مرة أخرى.")
        # Go back to the start of question count selection
        # Need to reconstruct the state based on quiz_selection_params
        quiz_params = context.user_data.get("quiz_selection_params", {})
        if quiz_params.get("type") == "random":
            dummy_data = "quiz_type_random"
        elif "lesson_id" in quiz_params:
            # Need course/unit id to go back correctly - this is complex
            # Simplest fallback: go back to quiz menu
            logger.warning("Cannot reliably go back to specific lesson count selection on error. Returning to quiz menu.")
            keyboard = create_quiz_menu_keyboard()
            try: query.edit_message_text(text="📝 اختر نوع الاختبار:", reply_markup=keyboard) # Try editing
            except: pass
            return QUIZ_MENU
        else:
             # Fallback if params are missing
            keyboard = create_quiz_menu_keyboard()
            try: query.edit_message_text(text="📝 اختر نوع الاختبار:", reply_markup=keyboard) # Try editing
            except: pass
            return QUIZ_MENU
        # If we had a dummy_data, recall select_question_count
        # This requires modifying select_question_count to accept dummy_data
        # For now, the fallback to quiz menu is safer.
        return QUIZ_MENU

def handle_manual_question_count_input(update: Update, context: CallbackContext) -> int:
    """Handles the text input after user selects 'manual' question count."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = update.message.text
    logger.info(f"User {user_id} entered manual question count: {text}")

    if not context.user_data.get("awaiting_question_count"):
        # Ignore if not expecting input
        logger.warning(f"Received unexpected text '{text}' from user {user_id} when not awaiting count.")
        return SELECT_QUESTION_COUNT # Stay in state, maybe send a clarification?

    max_questions = context.user_data.get("quiz_max_questions", 0)

    try:
        count = int(text.strip())
        if count <= 0:
            safe_send_message(context.bot, chat_id, text=f"⚠️ عدد الأسئلة يجب أن يكون موجباً. يرجى إدخال عدد صحيح بين 1 و {max_questions}.")
            return SELECT_QUESTION_COUNT # Ask again
        elif count > max_questions:
            safe_send_message(context.bot, chat_id, text=f"⚠️ الحد الأقصى لعدد الأسئلة هو {max_questions}. يرجى إدخال عدد أصغر أو يساوي هذا الحد.")
            return SELECT_QUESTION_COUNT # Ask again
        else:
            # Valid count entered
            context.user_data.pop("awaiting_question_count", None)
            quiz_params = context.user_data.get("quiz_selection_params", {})
            return start_quiz(update, context, quiz_params, count)

    except ValueError:
        safe_send_message(context.bot, chat_id, text=f"⚠️ الإدخال غير صالح. يرجى إدخال عدد صحيح بين 1 و {max_questions}.")
        return SELECT_QUESTION_COUNT # Ask again

# --- Quiz Taking Handlers ---

def start_quiz(update: Update, context: CallbackContext, quiz_params: dict, question_count: int) -> int:
    """Fetches questions from API and starts the quiz."""
    query = update.callback_query # Might be None if started from manual input
    user = update.effective_user
    chat_id = query.message.chat_id if query else update.effective_chat.id
    user_id = user.id
    logger.info(f"User {user_id} starting quiz with params: {quiz_params}, count: {question_count}")
    if query: query.answer()

    # Add count and is_active=True to API params
    api_params = quiz_params.copy()
    api_params['limit'] = question_count
    api_params['is_active'] = True

    loading_message = "⏳ جارٍ تحضير الاختبار..."
    sent_loading_msg = None
    try:
        if query:
            # Edit the message to show loading indicator
            sent_loading_msg = query.edit_message_text(text=loading_message, reply_markup=None)
        else:
            # Send a new loading message if started from text input
            sent_loading_msg = safe_send_message(context.bot, chat_id, text=loading_message)
    except Exception as e:
        logger.error(f"Error showing loading message: {e}")
        # Continue anyway, but log the error

    api_questions = fetch_from_api("/questions/quiz", params=api_params)

    # --- Delete loading message --- #
    if sent_loading_msg:
        try:
            context.bot.delete_message(chat_id=chat_id, message_id=sent_loading_msg.message_id)
        except Exception as e:
            logger.warning(f"Could not delete loading message: {e}")
    # --- --- --- --- --- --- --- --- #

    if api_questions == "TIMEOUT":
        error_text = "⏳ لا يمكن بدء الاختبار حالياً (انتهت مهلة جلب الأسئلة). يرجى المحاولة مرة أخرى لاحقاً."
        kb = InlineKeyboardMarkup([[create_back_button("menu_quiz")]]) # Fallback to main quiz menu
    elif api_questions is None or not isinstance(api_questions, list):
        error_text = "⚠️ لا يمكن بدء الاختبار حالياً (خطأ في جلب الأسئلة). يرجى المحاولة مرة أخرى لاحقاً."
        kb = InlineKeyboardMarkup([[create_back_button("menu_quiz")]])
    elif not api_questions:
        error_text = "⚠️ لا توجد أسئلة متاحة لهذا الاختيار لبدء الاختبار."
        kb = InlineKeyboardMarkup([[create_back_button("menu_quiz")]])
    else:
        # Transform questions
        questions = [transform_api_question(q) for q in api_questions]
        questions = [q for q in questions if q is not None] # Filter out invalid ones

        if not questions:
            error_text = "⚠️ لم يتم العثور على أسئلة صالحة لبدء الاختبار بعد المعالجة."
            kb = InlineKeyboardMarkup([[create_back_button("menu_quiz")]])
        else:
            # Successfully got questions
            quiz_id = int(time.time() * 1000) # Unique ID for this quiz instance
            quiz_data = {
                "quiz_id": quiz_id,
                "questions": questions,
                "current_question_index": 0,
                "answers": {},
                "score": 0,
                "start_time": datetime.now(),
                "quiz_timer_job_name": None, # For overall timer (unused)
                "question_timer_job_name": None, # For per-question timer
                "timed_out": False,
                "last_question_message_id": None, # To store ID of the question message
                "quiz_type": "_" .join(quiz_params.keys()) if quiz_params else "random" # Store type for reports
            }
            context.user_data["current_quiz"] = quiz_data
            logger.info(f"Quiz {quiz_id} started for user {user_id} with {len(questions)} questions.")

            # Set overall quiz timer (if enabled)
            # quiz_data["quiz_timer_job_name"] = set_quiz_timer(context, chat_id, user_id, quiz_id, DEFAULT_QUIZ_DURATION_MINUTES)

            # Send the first question
            return send_question(update, context)

    # Handle errors or empty list
    try:
        # Use the original query message if possible, otherwise send new
        if query:
            query.edit_message_text(text=error_text, reply_markup=kb)
        else:
            safe_send_message(context.bot, chat_id, text=error_text, reply_markup=kb)
    except Exception as e:
        logger.error(f"Error editing/sending message for quiz start error: {e}")
        safe_send_message(context.bot, chat_id, text=error_text, reply_markup=kb)

    # Determine state to return based on error context
    # This needs refinement based on where the error occurred (random, course, unit, lesson)
    return QUIZ_MENU # Fallback to main quiz menu

def send_question(update: Update, context: CallbackContext) -> int:
    """Sends the current question to the user."""
    query = update.callback_query # Might be None if called directly
    user = update.effective_user
    chat_id = query.message.chat_id if query else update.effective_chat.id
    user_id = user.id

    quiz_data = context.user_data.get("current_quiz")
    if not quiz_data:
        logger.warning(f"send_question called for user {user_id} but no active quiz found.")
        safe_send_message(context.bot, chat_id, text="لم يتم العثور على اختبار نشط.")
        return MAIN_MENU

    current_question_index = quiz_data["current_question_index"]
    questions = quiz_data["questions"]
    quiz_id = quiz_data["quiz_id"]

    if current_question_index >= len(questions):
        logger.info(f"Quiz {quiz_id} finished for user {user_id}. Showing results.")
        return show_results(chat_id, user_id, quiz_id, context)

    question = questions[current_question_index]
    question_id = question["question_id"]
    question_text = question["question_text"]
    question_image_url = question["image_url"]
    options_text = [question["option1"], question["option2"], question["option3"], question["option4"]]
    options_images = [question["option1_image"], question["option2_image"], question["option3_image"], question["option4_image"]]

    logger.info(f"Sending question {current_question_index + 1}/{len(questions)} (ID: {question_id}) for quiz {quiz_id} to user {user_id}.")

    # Create keyboard
    reply_markup = create_quiz_options_keyboard(options_text, options_images, question_id)
    if not reply_markup:
        logger.error(f"Failed to create keyboard for question {question_id}. Skipping question.")
        # Skip this question and move to the next
        quiz_data["answers"][current_question_index] = {"skipped": True, "timed_out": False}
        quiz_data["current_question_index"] += 1
        return send_question(update, context)

    # --- Sending Logic (Handles Text, Image, Media Group) ---
    sent_message = None
    try:
        # Case 1: Question has image, options have images (Media Group for options)
        if question_image_url and any(opt_img for opt_img in options_images):
            logger.debug("Sending question as text+image, options as media group.")
            # Send question text/image first
            if question_text:
                safe_send_message(context.bot, chat_id, text=f"**السؤال {current_question_index + 1}:**\n{question_text}", parse_mode=ParseMode.MARKDOWN)
            if question_image_url:
                try:
                    context.bot.send_photo(chat_id=chat_id, photo=question_image_url, timeout=30)
                except Exception as img_err:
                    logger.error(f"Failed to send question image {question_image_url}: {img_err}")
                    safe_send_message(context.bot, chat_id, text="⚠️ تعذر تحميل صورة السؤال.")

            # Send options as media group
            media_group = []
            option_labels = ["A", "B", "C", "D"]
            final_caption = "اختر الإجابة الصحيحة:"
            for i, img_url in enumerate(options_images):
                if img_url:
                    try:
                        # Fetch image into memory
                        response = requests.get(img_url, timeout=20)
                        response.raise_for_status()
                        image_bytes = BytesIO(response.content)
                        # Add label to caption if it's the first image
                        caption = f"{option_labels[i]}" if not media_group else option_labels[i]
                        media_group.append(InputMediaPhoto(media=image_bytes, caption=caption))
                    except Exception as mg_err:
                        logger.error(f"Failed to process option image {img_url} for media group: {mg_err}")
                        final_caption += f"\n(⚠️ تعذر تحميل الخيار {option_labels[i]})"
                elif options_text[i]: # Add text option to caption if image fails or missing
                     final_caption += f"\n{option_labels[i]}. {options_text[i]}"

            if media_group:
                 # Send the media group
                 safe_send_message(context.bot, chat_id, text=final_caption, parse_mode=ParseMode.MARKDOWN)

                 logger.debug(f"Sending media group with {len(media_group)} items.")
                 sent_messages = context.bot.send_media_group(chat_id=chat_id, media=media_group, timeout=30)
                 # Send the keyboard separately after the media group
                 if sent_messages:
                      # Send keyboard as reply to the last message of the media group if possible
                      try:
                          sent_message = safe_send_message(context.bot, chat_id, text="اختر الإجابة الصحيحة:", reply_markup=reply_markup, reply_to_message_id=sent_messages[-1].message_id)
                      except Exception as e:
                          logger.error(f'Error sending keyboard reply to media group message: {e}')
                          # Fallback: Send keyboard in a new message if reply fails
                          sent_message = safe_send_message(context.bot, chat_id, text="اختر الإجابة الصحيحة:", reply_markup=reply_markup)
                 else:
                     # Fallback if media group sending failed
                     sent_message = safe_send_message(context.bot, chat_id, text="اختر الإجابة الصحيحة:", reply_markup=reply_markup)
            else:
                 # Fallback if no images could be processed
                 sent_message = safe_send_message(context.bot, chat_id, text=final_caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

        # Case 2: Question has image, options are text-only
        elif question_image_url:
            logger.debug("Sending question as image with text options in caption/keyboard.")
            caption_text = f"**السؤال {current_question_index + 1}:**\n{question_text if question_text else ''}"
            try:
                sent_message = context.bot.send_photo(chat_id=chat_id, photo=question_image_url, caption=caption_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN, timeout=30)
            except Exception as img_err:
                 logger.error(f"Failed to send question image {question_image_url} with caption: {img_err}")
                 # Fallback: send text and keyboard separately
                 fallback_text = f"**السؤال {current_question_index + 1}:**\n{question_text if question_text else ''}\n(⚠️ تعذر تحميل صورة السؤال)"
                 sent_message = safe_send_message(context.bot, chat_id, text=fallback_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

        # Case 3: Question is text-only, options might have images (Send options as media group)
        elif any(opt_img for opt_img in options_images):
            logger.debug("Sending question as text, options as media group.")
            # Send question text first
            safe_send_message(context.bot, chat_id, text=f"**السؤال {current_question_index + 1}:**\n{question_text}", parse_mode=ParseMode.MARKDOWN)

            # Send options as media group (similar to Case 1)
            media_group = []
            option_labels = ["A", "B", "C", "D"]
            final_caption = "اختر الإجابة الصحيحة:"
            for i, img_url in enumerate(options_images):
                if img_url:
                    try:
                        response = requests.get(img_url, timeout=20)
                        response.raise_for_status()
                        image_bytes = BytesIO(response.content)
                        caption = f"{option_labels[i]}" if not media_group else option_labels[i]
                        media_group.append(InputMediaPhoto(media=image_bytes, caption=caption))
                    except Exception as mg_err:
                        logger.error(f"Failed to process option image {img_url} for media group: {mg_err}")
                        final_caption += f"\n(⚠️ تعذر تحميل الخيار {option_labels[i]})"
                elif options_text[i]:
                     final_caption += f"\n{option_labels[i]}. {options_text[i]}"

            if media_group:
                 safe_send_message(context.bot, chat_id, text=final_caption, parse_mode=ParseMode.MARKDOWN)
                 logger.debug(f"Sending media group with {len(media_group)} items.")
                 sent_messages = context.bot.send_media_group(chat_id=chat_id, media=media_group, timeout=30)
                 if sent_messages:
                      try:
                          sent_message = safe_send_message(context.bot, chat_id, text="اختر الإجابة الصحيحة:", reply_markup=reply_markup, reply_to_message_id=sent_messages[-1].message_id)
                      except Exception as e:
                          logger.error(f'Error sending keyboard reply to media group message: {e}')
                          sent_message = safe_send_message(context.bot, chat_id, text="اختر الإجابة الصحيحة:", reply_markup=reply_markup)
                 else:
                     sent_message = safe_send_message(context.bot, chat_id, text="اختر الإجابة الصحيحة:", reply_markup=reply_markup)
            else:
                 sent_message = safe_send_message(context.bot, chat_id, text=final_caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

        # Case 4: Question is text-only, options are text-only
        else:
            logger.debug("Sending question as text with text options in keyboard.")
            message_text = f"**السؤال {current_question_index + 1}:**\n{question_text}"
            sent_message = safe_send_message(context.bot, chat_id, text=message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

        # Store the message ID of the question/keyboard for potential editing later
        if sent_message:
            quiz_data["last_question_message_id"] = sent_message.message_id
        else:
            logger.warning(f"Could not get message ID for question {current_question_index} in quiz {quiz_id}")
            quiz_data["last_question_message_id"] = None # Ensure it's reset

        # Set the timer for this question
        quiz_data["question_timer_job_name"] = set_question_timer(context, chat_id, user_id, quiz_id, current_question_index)

        return TAKING_QUIZ # Stay in the quiz state

    except (BadRequest, TimedOut, NetworkError, Unauthorized, ChatMigrated) as e:
        logger.error(f"Telegram error sending question {question_id}: {e}")
        safe_send_message(context.bot, chat_id, text="حدث خطأ أثناء إرسال السؤال. سيتم تخطي هذا السؤال.")
        # Skip this question
        quiz_data["answers"][current_question_index] = {"skipped": True, "timed_out": False, "error": str(e)}
        quiz_data["current_question_index"] += 1
        # Remove timer if it was set
        if quiz_data.get("question_timer_job_name"):
            remove_job_if_exists(quiz_data["question_timer_job_name"], context)
            quiz_data["question_timer_job_name"] = None
        # Try sending the next question after a short delay
        context.job_queue.run_once(lambda ctx: send_question(update, ctx), 1, context=context)
        return TAKING_QUIZ
    except Exception as e:
        logger.exception(f"Unexpected error sending question {question_id}: {e}") # Use exception for full traceback
        safe_send_message(context.bot, chat_id, text="حدث خطأ غير متوقع أثناء إرسال السؤال. سيتم تخطي هذا السؤال.")
        # Skip this question
        quiz_data["answers"][current_question_index] = {"skipped": True, "timed_out": False, "error": str(e)}
        quiz_data["current_question_index"] += 1
        # Remove timer if it was set
        if quiz_data.get("question_timer_job_name"):
            remove_job_if_exists(quiz_data["question_timer_job_name"], context)
            quiz_data["question_timer_job_name"] = None
        # Try sending the next question after a short delay
        context.job_queue.run_once(lambda ctx: send_question(update, ctx), 1, context=context)
        return TAKING_QUIZ

def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    """Handles user's answer selection during a quiz."""
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    data = query.data
    logger.info(f"User {user_id} answered: {data}")
    query.answer()

    quiz_data = context.user_data.get("current_quiz")
    if not quiz_data:
        logger.warning(f"Received quiz answer from user {user_id} but no active quiz found.")
        try:
            query.edit_message_text(text="لم يتم العثور على اختبار نشط.")
        except Exception as e:
            logger.error(f"Error editing message for no active quiz: {e}")
        return MAIN_MENU

    try:
        parts = data.split('_')
        question_id = int(parts[2])
        selected_option_index = int(parts[3])
    except (ValueError, IndexError):
        logger.error(f"Could not parse quiz answer callback data: {data}")
        safe_send_message(context.bot, chat_id, text="حدث خطأ في معالجة إجابتك.")
        return TAKING_QUIZ # Stay in quiz state

    current_question_index = quiz_data["current_question_index"]
    questions = quiz_data["questions"]
    quiz_id = quiz_data["quiz_id"]

    if current_question_index >= len(questions):
        logger.warning(f"Received answer for quiz {quiz_id} but index {current_question_index} is out of bounds.")
        return show_results(chat_id, user_id, quiz_id, context)

    question = questions[current_question_index]

    # Check if the answer corresponds to the current question
    if question["question_id"] != question_id:
        logger.warning(f"User {user_id} answered question {question_id} but current question is {question['question_id']}. Ignoring.")
        # Maybe provide feedback? For now, just ignore.
        return TAKING_QUIZ

    # --- Process the answer --- #
    correct_option_index = question["correct_answer"]
    is_correct = (selected_option_index == correct_option_index)

    # Store the answer
    quiz_data["answers"][current_question_index] = {
        "selected": selected_option_index,
        "correct": correct_option_index,
        "is_correct": is_correct,
        "skipped": False,
        "timed_out": False
    }

    if is_correct:
        quiz_data["score"] += 1
        feedback_text = "✅ إجابة صحيحة!"
    else:
        feedback_text = f"❌ إجابة خاطئة. الإجابة الصحيحة هي الخيار {chr(ord('A') + correct_option_index)}."
        # Add explanation if available
        if question.get("explanation"):
            feedback_text += f"\n\n**التفسير:**\n{question['explanation']}"

    # Remove the question timer job
    if quiz_data.get("question_timer_job_name"):
        remove_job_if_exists(quiz_data["question_timer_job_name"], context)
        quiz_data["question_timer_job_name"] = None

    # Edit the original question message to remove keyboard and show feedback
    try:
        # Use the stored message ID
        message_id_to_edit = quiz_data.get("last_question_message_id")
        if message_id_to_edit:
            # Try editing the message that contained the keyboard
            context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id_to_edit, reply_markup=None)
            # Send feedback as a new message
            safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)
        else:
            # Fallback if message ID wasn't stored
            logger.warning("last_question_message_id not found, cannot remove keyboard. Sending feedback.")
            safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)

    except BadRequest as e:
        if "Message to edit not found" in str(e) or "message can't be edited" in str(e) or "message is not modified" in str(e):
            logger.warning(f"Could not edit previous question message {message_id_to_edit} (likely deleted or old): {e}. Sending feedback.")
            safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)
        else:
            logger.error(f"Error editing previous question message {message_id_to_edit}: {e}")
            safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN) # Send feedback anyway
    except Exception as e:
        logger.error(f"Unexpected error editing previous question message {message_id_to_edit}: {e}")
        safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN) # Send feedback anyway

    # Move to the next question after a delay
    quiz_data["current_question_index"] += 1
    context.job_queue.run_once(lambda ctx: send_question(update, ctx), FEEDBACK_DELAY, context=context)

    return TAKING_QUIZ

def handle_quiz_skip(update: Update, context: CallbackContext, timed_out: bool = False) -> int:
    """Handles user skipping a question or question timeout."""
    query = update.callback_query # Might be None if called by timer
    user_id = query.from_user.id if query else context.job.context["user_id"]
    chat_id = query.message.chat_id if query else context.job.context["chat_id"]

    quiz_data = context.user_data.get("current_quiz")
    if not quiz_data:
        logger.warning(f"handle_quiz_skip called for user {user_id} but no active quiz found.")
        if query:
            query.answer()
            try: query.edit_message_text(text="لم يتم العثور على اختبار نشط.")
            except: pass
        return MAIN_MENU

    current_question_index = quiz_data["current_question_index"]
    questions = quiz_data["questions"]
    quiz_id = quiz_data["quiz_id"]

    if current_question_index >= len(questions):
        logger.warning(f"Received skip for quiz {quiz_id} but index {current_question_index} is out of bounds.")
        if query: query.answer()
        return show_results(chat_id, user_id, quiz_id, context)

    question = questions[current_question_index]
    question_id_from_data = None

    if query:
        # If called by button press, verify question ID
        data = query.data
        logger.info(f"User {user_id} skipped question via button: {data}")
        query.answer()
        try:
            # Format: quiz_skip_{question_id}
            question_id_from_data = int(data.split('_')[-1])
        except (ValueError, IndexError):
            logger.error(f"Could not parse quiz skip callback data: {data}")
            safe_send_message(context.bot, chat_id, text="حدث خطأ في معالجة التخطي.")
            return TAKING_QUIZ

        if question["question_id"] != question_id_from_data:
            logger.warning(f"User {user_id} skipped question {question_id_from_data} but current question is {question['question_id']}. Ignoring.")
            return TAKING_QUIZ
    else:
        # If called by timer, question_id verification is implicit
        logger.info(f"Question {current_question_index} timed out for user {user_id} in quiz {quiz_id}.")

    # --- Process the skip --- #
    feedback_text = f"⏭️ تم تخطي السؤال {current_question_index + 1}."
    if timed_out:
        feedback_text = f"⏰ تم تخطي السؤال {current_question_index + 1} (انتهى الوقت)."

    correct_option_index = question["correct_answer"]
    feedback_text += f" الإجابة الصحيحة كانت الخيار {chr(ord('A') + correct_option_index)}."
    if question.get("explanation"):
        feedback_text += f"\n\n**التفسير:**\n{question['explanation']}"

    # Store the skip
    quiz_data["answers"][current_question_index] = {
        "selected": None,
        "correct": correct_option_index,
        "is_correct": False,
        "skipped": True,
        "timed_out": timed_out
    }

    # Remove the question timer job (important even if called by timer, to prevent race conditions)
    if quiz_data.get("question_timer_job_name"):
        remove_job_if_exists(quiz_data["question_timer_job_name"], context)
        quiz_data["question_timer_job_name"] = None

    # Edit the original question message to remove keyboard and show feedback
    try:
        message_id_to_edit = quiz_data.get("last_question_message_id")
        if message_id_to_edit:
            context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id_to_edit, reply_markup=None)
            safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)
        else:
            logger.warning("last_question_message_id not found, cannot remove keyboard. Sending feedback.")
            safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)
    except BadRequest as e:
        if "Message to edit not found" in str(e) or "message can't be edited" in str(e) or "message is not modified" in str(e):
            logger.warning(f"Could not edit previous question message {message_id_to_edit} (likely deleted or old): {e}. Sending feedback.")
            safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)
        else:
            logger.error(f"Error editing previous question message {message_id_to_edit}: {e}")
            safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Unexpected error editing previous question message {message_id_to_edit}: {e}")
        safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)

    # Move to the next question after a delay
    quiz_data["current_question_index"] += 1
    context.job_queue.run_once(lambda ctx: send_question(update, ctx), FEEDBACK_DELAY, context=context)

    return TAKING_QUIZ

def show_results(chat_id: int, user_id: int, quiz_id: int, context: CallbackContext, timed_out: bool = False) -> int:
    """Calculates and displays the quiz results."""
    logger.info(f"Showing results for quiz {quiz_id} for user {user_id}.")

    quiz_data = context.user_data.get("current_quiz")

    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.warning(f"show_results called for quiz {quiz_id} but data not found or mismatched.")
        safe_send_message(context.bot, chat_id, text="لم يتم العثور على بيانات هذا الاختبار.")
        return MAIN_MENU

    # Ensure timers are stopped
    if quiz_data.get("quiz_timer_job_name"):
        remove_job_if_exists(quiz_data["quiz_timer_job_name"], context)
    if quiz_data.get("question_timer_job_name"):
        remove_job_if_exists(quiz_data["question_timer_job_name"], context)

    score = quiz_data["score"]
    total_questions = len(quiz_data["questions"])
    answers = quiz_data["answers"]
    quiz_type = quiz_data.get("quiz_type", "غير محدد")
    start_time = quiz_data["start_time"]
    end_time = datetime.now()
    duration = end_time - start_time
    duration_str = str(duration).split('.')[0] # Format as H:MM:SS

    # Calculate detailed stats
    correct_count = score
    incorrect_count = 0
    skipped_count = 0
    timed_out_count = 0
    for idx, ans_data in answers.items():
        if ans_data.get("skipped"):
            if ans_data.get("timed_out"):
                timed_out_count += 1
            else:
                skipped_count += 1
        elif not ans_data.get("is_correct"):
            incorrect_count += 1

    answered_count = correct_count + incorrect_count
    attempted_count = answered_count + skipped_count + timed_out_count

    # Build result message
    result_message = f"🏁 **نتائج الاختبار (النوع: {quiz_type})** 🏁\n\n"
    result_message += f"✨ نتيجتك: **{score}** من **{total_questions}**\n"
    try:
        percentage = (score / total_questions) * 100 if total_questions > 0 else 0
        result_message += f"📊 النسبة المئوية: **{percentage:.1f}%**\n\n"
    except ZeroDivisionError:
        result_message += "📊 النسبة المئوية: غير متاحة\n\n"

    result_message += f"✅ الإجابات الصحيحة: {correct_count}\n"
    result_message += f"❌ الإجابات الخاطئة: {incorrect_count}\n"
    result_message += f"⏭️ الأسئلة المتخطاة: {skipped_count}\n"
    if timed_out_count > 0:
        result_message += f"⏱️ انتهى وقتها: {timed_out_count}\n"
    result_message += f"⏱️ الوقت المستغرق: {duration_str}\n"

    if timed_out: # Check if the whole quiz timed out
        result_message += "\n⏰ *انتهى وقت الاختبار.*\n"
    elif quiz_data.get("timed_out"): # Check if flag was set by overall timer
        result_message += "\n⏰ *انتهى وقت الاختبار.*\n"

    # Save results to database
    db_saved = False
    if QUIZ_DB:
        try:
            QUIZ_DB.save_quiz_result(
                user_id=user_id,
                quiz_type=quiz_type,
                score=score,
                total_questions=total_questions,
                answers_details=answers, # Store detailed answers if needed
                duration_seconds=int(duration.total_seconds()),
                timestamp=end_time
            )
            db_saved = True
            logger.info(f"Quiz {quiz_id} results saved for user {user_id}.")
        except Exception as e:
            logger.error(f"Failed to save quiz results for user {user_id}: {e}")
            result_message += "\n⚠️ *لا يمكن حفظ نتيجتك حالياً (مشكلة في قاعدة البيانات).*"
    else:
        logger.warning("QUIZ_DB not initialized. Cannot save quiz results.")
        result_message += "\n⚠️ *لا يمكن حفظ نتيجتك حالياً (قاعدة البيانات غير متاحة).*"

    # Clean up quiz data from user_data
    context.user_data.pop("current_quiz", None)
    context.user_data.pop("quiz_selection_params", None)
    context.user_data.pop("quiz_max_questions", None)
    context.user_data.pop("awaiting_question_count", None)

    # Send results
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 إجراء اختبار آخر", callback_data="menu_quiz")],
        [InlineKeyboardButton("📊 عرض التقارير", callback_data="menu_reports")],
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]
    ])
    safe_send_message(context.bot, chat_id, text=result_message, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

    return SHOWING_RESULTS # End state for quiz flow

# --- Admin Handlers (Placeholders) ---

def admin_menu_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    if not is_admin(user_id):
        query.answer("عذراً، هذه المنطقة مخصصة للمشرفين فقط.", show_alert=True)
        return MAIN_MENU

    logger.info(f"Admin {user_id} accessed admin menu.")
    query.answer()
    admin_text = "⚙️ قائمة إدارة البوت ⚙️"
    keyboard = InlineKeyboardMarkup([
        # Add admin options here (e.g., manage questions, manage structure, view stats)
        [InlineKeyboardButton("🏗️ إدارة الهيكل الدراسي", callback_data="admin_manage_structure")],
        [InlineKeyboardButton("❓ إدارة الأسئلة (API)", url=API_BASE_URL)], # Link to API frontend
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
    ])
    try:
        query.edit_message_text(text=admin_text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error editing message to Admin Menu: {e}")
        safe_send_message(context.bot, query.message.chat_id, text=admin_text, reply_markup=keyboard)
    return ADMIN_MENU

def admin_manage_structure_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    if not is_admin(user_id):
        query.answer("عذراً، هذه المنطقة مخصصة للمشرفين فقط.", show_alert=True)
        return MAIN_MENU

    logger.info(f"Admin {user_id} accessed structure management.")
    query.answer()
    text = "🏗️ إدارة الهيكل الدراسي 🏗️\n\nاختر ما تريد إدارته:"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 إدارة المقررات", callback_data="admin_manage_grades")], # Assuming 'grades' maps to 'courses'
        [InlineKeyboardButton("📖 إدارة الوحدات", callback_data="admin_manage_chapters")], # Assuming 'chapters' maps to 'units'
        [InlineKeyboardButton("📝 إدارة الدروس", callback_data="admin_manage_lessons")],
        [InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data="menu_admin")]
    ])
    try:
        query.edit_message_text(text=text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error editing message to Structure Management: {e}")
        safe_send_message(context.bot, query.message.chat_id, text=text, reply_markup=keyboard)
    return ADMIN_MANAGE_STRUCTURE

# --- Error Handler ---

def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # Attempt to notify the user about the error, if possible
    if isinstance(update, Update) and update.effective_chat:
        try:
            safe_send_message(context.bot, update.effective_chat.id, text="حدث خطأ غير متوقع أثناء معالجة طلبك. يرجى المحاولة مرة أخرى أو استخدام /start للبدء من جديد.")
        except Exception as e:
            logger.error(f"Failed to send error message to user: {e}")

# --- Main Function ---

def main() -> None:
    """Start the bot."""
    logger.info("Initializing bot...")

    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN not found. Exiting.")
        return

    # Create the Updater and pass it your bot's token.
    updater = Updater(BOT_TOKEN, use_context=True)
    logger.debug("[DIAG] Updater created.")

    # Get the dispatcher to register handlers
    dp = updater.dispatcher
    logger.debug("[DIAG] Dispatcher obtained.")

    # --- Conversation Handler Setup ---
    logger.debug("[DIAG] Setting up ConversationHandler...")
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CallbackQueryHandler(main_menu_callback, pattern='^main_menu$') # Allow returning via callback
            ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(info_menu_callback, pattern='^menu_info$'),
                CallbackQueryHandler(quiz_menu_callback, pattern='^menu_quiz$'),
                CallbackQueryHandler(reports_menu_callback, pattern='^menu_reports$'),
                CallbackQueryHandler(about_callback, pattern='^menu_about$'),
                CallbackQueryHandler(admin_menu_callback, pattern='^menu_admin$'),
            ],
            QUIZ_MENU: [
                CallbackQueryHandler(select_question_count, pattern='^quiz_type_random$'),
                CallbackQueryHandler(select_course_for_quiz, pattern='^quiz_select_course$'),
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'),
            ],
            SELECT_COURSE_FOR_QUIZ: [
                CallbackQueryHandler(handle_pagination_callback, pattern='^page_\d+_course'),
                CallbackQueryHandler(select_unit_for_quiz, pattern='^quiz_select_unit_\d+$'),
                CallbackQueryHandler(quiz_menu_callback, pattern='^menu_quiz$'), # Back button
            ],
            SELECT_UNIT_FOR_QUIZ: [
                CallbackQueryHandler(handle_pagination_callback, pattern='^page_\d+_unit_\d+'),
                CallbackQueryHandler(select_lesson_for_quiz, pattern='^quiz_select_lesson_\d+_\d+$'),
                CallbackQueryHandler(select_course_for_quiz, pattern='^quiz_select_course_page_0$'), # Back button
            ],
            SELECT_LESSON_FOR_QUIZ_HIERARCHY: [
                CallbackQueryHandler(handle_pagination_callback, pattern='^page_\d+_lesson_\d+_\d+'),
                CallbackQueryHandler(select_question_count, pattern='^q_count_lesson_\d+_\d+_\d+$'),
                CallbackQueryHandler(select_unit_for_quiz, pattern='^quiz_select_unit_\d+_page_0$'), # Back button
            ],
            SELECT_QUESTION_COUNT: [
                CallbackQueryHandler(handle_question_count_selection, pattern='^q_count_.*_\d+$'), # Button press (e.g., _10)
                CallbackQueryHandler(handle_question_count_selection, pattern='^q_count_.*_manual$'), # Manual button
                MessageHandler(Filters.text & ~Filters.command & Filters.chat_type.private, handle_manual_question_count_input), # Manual text input
                # Back buttons (handled within create_question_count_keyboard logic)
                CallbackQueryHandler(quiz_menu_callback, pattern='^menu_quiz$'),
                CallbackQueryHandler(select_course_for_quiz, pattern='^quiz_select_course_page_0$'),
                CallbackQueryHandler(select_unit_for_quiz, pattern='^quiz_select_unit_\d+_page_0$'),
                CallbackQueryHandler(select_lesson_for_quiz, pattern='^quiz_select_lesson_\d+_\d+_page_0$'),
            ],
            TAKING_QUIZ: [
                CallbackQueryHandler(handle_quiz_answer, pattern='^quiz_answer_\d+_\d$'),
                CallbackQueryHandler(handle_quiz_skip, pattern='^quiz_skip_\d+$'),
            ],
            SHOWING_RESULTS: [ # State after quiz ends
                CallbackQueryHandler(quiz_menu_callback, pattern='^menu_quiz$'),
                CallbackQueryHandler(reports_menu_callback, pattern='^menu_reports$'),
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'),
            ],
            INFO_MENU: [
                # Add handlers for info sub-menus if needed
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'),
            ],
            SHOWING_REPORTS: [
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'),
            ],
            ADMIN_MENU: [
                CallbackQueryHandler(admin_manage_structure_callback, pattern='^admin_manage_structure$'),
                # Add other admin handlers
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'),
            ],
            ADMIN_MANAGE_STRUCTURE: [
                # CallbackQueryHandler(admin_manage_grades_callback, pattern='^admin_manage_grades$'),
                # CallbackQueryHandler(admin_manage_chapters_callback, pattern='^admin_manage_chapters$'),
                # CallbackQueryHandler(admin_manage_lessons_callback, pattern='^admin_manage_lessons$'),
                CallbackQueryHandler(admin_menu_callback, pattern='^menu_admin$'), # Back button
            ],
            # Add states for ADMIN_MANAGE_GRADES, CHAPTERS, LESSONS etc. if implemented
        },
        fallbacks=[
            CommandHandler('start', start), # Allow restarting
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(main_menu_callback, pattern='^main_menu$') # Global fallback to main menu
            ],
        per_user=True,
        per_chat=True,
    )
    logger.debug("[DIAG] ConversationHandler created.")
    dp.add_handler(conv_handler)
    logger.debug("[DIAG] ConversationHandler added to dispatcher.")

    # Add help command handler (outside conversation)
    dp.add_handler(CommandHandler('help', help_command))

    # Log all errors
    dp.add_error_handler(error_handler)
    logger.debug("[DIAG] Error handler added.")

    # --- Start the Bot using Polling --- #
    logger.info("Starting bot using polling...")
    updater.start_polling()
    logger.info("Bot started successfully using polling.")

    # Run the bot until you press Ctrl-C
    updater.idle()
    logger.info("Bot stopped.")

if __name__ == '__main__':
    main()

