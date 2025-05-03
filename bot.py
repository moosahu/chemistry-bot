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
from telegram.ext import filters
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
API_BASE_URL = "https://question-manager-web.onrender.com" # Added API Base URL

if not BOT_TOKEN:
    logger.critical("BOT_TOKEN environment variable not set!")
    sys.exit("Bot token not found.")

# Quiz settings
DEFAULT_QUIZ_QUESTIONS = 10
DEFAULT_QUIZ_DURATION_MINUTES = 10
QUESTION_TIMER_SECONDS = 240
FEEDBACK_DELAY = 1.5
ENABLE_QUESTION_TIMER = False

# --- Database Setup (Only for Users and Results now) ---
try:
    from db_utils import connect_db, setup_database
    # quiz_db is no longer needed for fetching questions
    from quiz_db import QuizDatabase # Keep for user/result management
    from helper_function import safe_edit_message_text, safe_send_message
except ImportError as e:
    logger.error(f"Failed to import database/helper modules: {e}. Ensure db_utils.py, quiz_db.py, helper_function.py are present.")
    sys.exit("Critical import error, stopping bot.")

# Initialize database connection and QuizDatabase instance (for users/results)
if not DATABASE_URL:
    logger.error("DATABASE_URL environment variable not set or empty. Bot cannot connect to DB for user/result data.")
    # sys.exit("Database configuration error.") # Allow bot to run without DB for testing?
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

# --- Chemistry Data (Placeholders) ---
try:
    ELEMENTS, COMPOUNDS, CONCEPTS, PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO = {}, {}, {}, {}, {}, {}
    def process_text_with_chemical_notation(text): return text
    def format_chemical_equation(text): return text
    logger.info("Chemistry data and equation functions loaded (placeholders used).")
except ImportError as e:
    logger.warning(f"Could not import chemistry_data.py or chemical_equations.py: {e}. Some features might be limited.")
    ELEMENTS, COMPOUNDS, CONCEPTS, PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO = {}, {}, {}, {}, {}, {}
    def process_text_with_chemical_notation(text): return text
    def format_chemical_equation(text): return text

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
    INFO_MENU,
    SHOWING_INFO_CONTENT,
    SHOWING_REPORTS,
    SELECT_CHAPTER_FOR_LESSON_QUIZ,
    SHOWING_RESULTS
) = range(36)

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

# --- API Interaction Functions (NEW) ---

def fetch_questions_from_api(endpoint: str, params: dict = None) -> list | None:
    """Fetches questions from the specified API endpoint."""
    url = f"{API_BASE_URL}{endpoint}"
    logger.info(f"[DIAG] Attempting to fetch questions from API: {url} with params: {params}")
    try:
        response = requests.get(url, params=params, timeout=20) # Added timeout
        logger.info(f"[DIAG] API response status code: {response.status_code} for {url}")
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        data = response.json()
        logger.info(f"[DIAG] Successfully fetched and decoded JSON from {url}. Type: {type(data)}")
        # Basic validation: Check if it's a list
        if isinstance(data, list):
            logger.info(f"[DIAG] API returned a list with {len(data)} items.")
            return data
        else:
            logger.error(f"[DIAG] API response from {url} is not a list: {type(data)}")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"[DIAG] API request failed for {url}: {e}")
        return None
    except ValueError as e: # Includes JSONDecodeError
        logger.error(f"[DIAG] Failed to decode JSON response from {url}: {e}")
        return None

def transform_api_question(api_question: dict) -> dict | None:
    """Transforms a single question object from API format to bot format."""
    # logger.debug(f"[DIAG] Transforming API question: {api_question}") # Can be very verbose
    if not isinstance(api_question, dict):
        logger.error(f"[DIAG] Invalid API question format: Expected dict, got {type(api_question)}")
        return None

    question_id = api_question.get("question_id")
    question_text = api_question.get("question_text")
    question_image_url = api_question.get("image_url")
    api_options = api_question.get("options")

    if question_id is None or not isinstance(api_options, list):
        logger.error(f"[DIAG] Skipping question due to missing ID or invalid options: {api_question}")
        return None

    # Bot expects exactly 4 options, API might return more or less?
    # Let's take the first 4, or pad with None if fewer.
    bot_options_text = [None] * 4
    bot_options_image = [None] * 4
    correct_answer_index = None

    for i, opt in enumerate(api_options):
        if i >= 4: # Limit to 4 options for the bot
            logger.warning(f"[DIAG] Question {question_id} has more than 4 options, ignoring extras.")
            break
        if isinstance(opt, dict):
            bot_options_text[i] = opt.get("option_text")
            bot_options_image[i] = opt.get("image_url") # Store option image URL
            if opt.get("is_correct") is True:
                if correct_answer_index is not None:
                    logger.warning(f"[DIAG] Multiple correct options found for question {question_id}. Using the first one.")
                else:
                    correct_answer_index = i # 0-based index
        else:
            logger.warning(f"[DIAG] Invalid option format in question {question_id}: {opt}")

    # Basic validation: Ensure question has text or image, and a correct answer
    if not question_text and not question_image_url:
        logger.error(f"[DIAG] Skipping question {question_id}: No text or image provided.")
        return None
    if correct_answer_index is None:
        logger.error(f"[DIAG] Skipping question {question_id}: No correct answer found.")
        return None
    # Ensure the correct option actually exists
    if bot_options_text[correct_answer_index] is None and bot_options_image[correct_answer_index] is None:
        logger.error(f"[DIAG] Skipping question {question_id}: Correct answer option ({correct_answer_index}) has no text or image.")
        return None

    # Note: API has no 'explanation'. Bot needs to handle this.
    bot_question = {
        "question_id": question_id, # Keep original ID if needed
        "question_text": question_text,
        "image_url": question_image_url,
        "option1": bot_options_text[0],
        "option2": bot_options_text[1],
        "option3": bot_options_text[2],
        "option4": bot_options_text[3],
        "option1_image": bot_options_image[0], # Add option images
        "option2_image": bot_options_image[1],
        "option3_image": bot_options_image[2],
        "option4_image": bot_options_image[3],
        "correct_answer": correct_answer_index, # 0-based index
        "explanation": None # Explicitly set to None as API doesn't provide it
    }
    # logger.debug(f"[DIAG] Transformed question {question_id}: {bot_question}")
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

    if quiz_data and quiz_data["quiz_id"] == quiz_id and quiz_data["current_question_index"] == question_index and not quiz_data.get("timed_out"):
        safe_send_message(context.bot, chat_id, text=f"⏰ انتهى وقت السؤال {question_index + 1}! سيتم اعتباره متخطى.")
        handle_quiz_skip(chat_id, user_id, quiz_id, question_index, context, timed_out=True)
    else:
        logger.info(f"Question {question_index} already answered/skipped or quiz ended, ignoring timer.")

# --- Keyboard Creation Functions ---
# NOTE: Keyboards related to Grade/Chapter/Lesson selection might need updates
# if the IDs/names are now fetched differently (e.g., via API or if QUIZ_DB structure changed)

def create_main_menu_keyboard(user_id):
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
    # TODO: Update callbacks if quiz types/filters change based on API structure
    # Assuming 'lesson', 'unit', 'course' IDs will be used as filters
    keyboard = [
        [InlineKeyboardButton("📚 اختبار تحصيلي عام", callback_data='quiz_random_prompt')],
        # Maybe fetch available courses/units/lessons from API to build dynamic menus?
        [InlineKeyboardButton("📄 اختبار حسب المقرر", callback_data='quiz_by_course_prompt')],
        [InlineKeyboardButton("📝 اختبار حسب الوحدة", callback_data='quiz_by_unit_prompt')],
        [InlineKeyboardButton("🎓 اختبار حسب الدرس", callback_data='quiz_by_lesson_prompt')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_admin_menu_keyboard():
    # Admin functions might need significant rework if questions are managed via web app/API
    keyboard = [
        # [InlineKeyboardButton("➕ إضافة سؤال", callback_data='admin_add_question')], # Likely removed/changed
        # [InlineKeyboardButton("🗑️ حذف سؤال", callback_data='admin_delete_question')], # Likely removed/changed
        # [InlineKeyboardButton("🔍 عرض سؤال", callback_data='admin_show_question')], # Likely removed/changed
        # [InlineKeyboardButton("🏫 إدارة المراحل/الفصول/الدروس", callback_data='admin_manage_structure')], # Likely removed/changed
        [InlineKeyboardButton("📊 عرض إحصائيات المستخدمين (مثال)", callback_data='admin_show_stats')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Command Handlers ---

def start(update: Update, context: CallbackContext) -> int:
    """Handles the /start command."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    logger.info(f"[DIAG] /start command received from user {user.id} ({get_user_name(user)}) in chat {chat_id}")

    # Register or update user in DB
    if QUIZ_DB:
        try:
            QUIZ_DB.register_user(user.id, user.username, user.first_name, user.last_name)
            logger.info(f"[DIAG] User {user.id} registered/updated in DB.")
        except Exception as e:
            logger.error(f"[DIAG] Failed to register/update user {user.id} in DB: {e}")
            # Decide if we should notify the user or just log

    welcome_message = f"أهلاً بك يا {user.first_name or user.username} في بوت الكيمياء التعليمي!\n\n"
    welcome_message += "اختر أحد الخيارات أدناه للبدء:"

    keyboard = create_main_menu_keyboard(user.id)
    logger.info("[DIAG] Sending welcome message and main menu keyboard.")
    safe_send_message(context.bot, chat_id, text=welcome_message, reply_markup=keyboard)
    logger.info("[DIAG] Finished processing /start command.")
    return MAIN_MENU

def about(update: Update, context: CallbackContext):
    """Handles the /about command."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    logger.info(f"[DIAG] /about command received from user {user.id}")
    about_text = ("هذا البوت مصمم لمساعدتك في دراسة الكيمياء من خلال الاختبارات والمعلومات المفيدة.\n"
                  "تم تطويره بواسطة [اسم المطور أو الفريق].\n"
                  "للبدء، استخدم القائمة الرئيسية.")
    safe_send_message(context.bot, chat_id, text=about_text)
    logger.info("[DIAG] Sent about message.")

def unknown_command(update: Update, context: CallbackContext):
    """Handles unknown commands."""
    logger.warning(f"[DIAG] Received unknown command: {update.message.text}")
    safe_send_message(context.bot, update.effective_chat.id, text="عذراً، لم أفهم هذا الأمر. الرجاء استخدام القائمة أو الأوامر المعروفة.")

def unknown_message(update: Update, context: CallbackContext):
    """Handles unknown messages (non-commands)."""
    logger.warning(f"[DIAG] Received unknown message: {update.message.text}")
    safe_send_message(context.bot, update.effective_chat.id, text="عذراً، لا أستطيع معالجة الرسائل النصية العادية في الوقت الحالي. الرجاء استخدام القائمة.")

# --- Button Callback Handler ---

def button_handler(update: Update, context: CallbackContext) -> int:
    """Handles all inline button presses."""
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    callback_data = query.data
    logger.info(f"[DIAG] Button pressed by user {user_id}. Callback data: '{callback_data}'")

    try:
        query.answer() # Answer the callback query immediately
        logger.info("[DIAG] Callback query answered.")
    except BadRequest as e:
        # This can happen if the button message is too old
        logger.warning(f"[DIAG] Failed to answer callback query (maybe too old?): {e}")

    # --- Main Menu Navigation ---
    if callback_data == 'main_menu':
        logger.info("[DIAG] Handling 'main_menu' callback.")
        keyboard = create_main_menu_keyboard(user_id)
        safe_edit_message_text(query.message, text="القائمة الرئيسية: اختر أحد الخيارات.", reply_markup=keyboard)
        logger.info("[DIAG] Displayed main menu.")
        return MAIN_MENU

    elif callback_data == 'menu_quiz':
        logger.info("[DIAG] Handling 'menu_quiz' callback.")
        keyboard = create_quiz_menu_keyboard()
        safe_edit_message_text(query.message, text="اختر نوع الاختبار الذي تريده:", reply_markup=keyboard)
        logger.info("[DIAG] Displayed quiz menu.")
        return QUIZ_MENU

    elif callback_data == 'menu_info':
        logger.info("[DIAG] Handling 'menu_info' callback. (Not Implemented Yet)")
        safe_edit_message_text(query.message, text="قسم المعلومات الكيميائية (قيد الإنشاء).", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU # Go back to main menu for now

    elif callback_data == 'menu_reports':
        logger.info("[DIAG] Handling 'menu_reports' callback. (Not Implemented Yet)")
        safe_edit_message_text(query.message, text="قسم تقارير الأداء (قيد الإنشاء).", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU # Go back to main menu for now

    elif callback_data == 'menu_about':
        logger.info("[DIAG] Handling 'menu_about' callback.")
        about_text = ("هذا البوت مصمم لمساعدتك في دراسة الكيمياء من خلال الاختبارات والمعلومات المفيدة.\n"
                      "تم تطويره بواسطة [اسم المطور أو الفريق].\n"
                      "للبدء، استخدم القائمة الرئيسية.")
        safe_edit_message_text(query.message, text=about_text, reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU

    elif callback_data == 'menu_admin' and is_admin(user_id):
        logger.info("[DIAG] Handling 'menu_admin' callback.")
        keyboard = create_admin_menu_keyboard()
        safe_edit_message_text(query.message, text="قائمة إدارة البوت:", reply_markup=keyboard)
        logger.info("[DIAG] Displayed admin menu.")
        return ADMIN_MENU

    # --- Quiz Selection --- (Using API now)
    elif callback_data == 'quiz_random_prompt':
        logger.info("[DIAG] Handling 'quiz_random_prompt' callback.")
        # Ask for duration or use default
        # For simplicity, let's start immediately with default settings
        logger.info("[DIAG] Starting random quiz immediately with default settings.")
        return start_quiz(update, context, quiz_type='random')

    elif callback_data == 'quiz_by_course_prompt':
        logger.info("[DIAG] Handling 'quiz_by_course_prompt' callback.")
        # Fetch courses from API
        courses = fetch_questions_from_api("/api/v1/courses")
        if courses:
            keyboard = []
            for course in courses:
                if isinstance(course, dict) and 'course_id' in course and 'name' in course:
                    keyboard.append([InlineKeyboardButton(course['name'], callback_data=f'select_course_{course["course_id"]}')])
            keyboard.append([InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data='menu_quiz')])
            safe_edit_message_text(query.message, text="اختر المقرر:", reply_markup=InlineKeyboardMarkup(keyboard))
            logger.info("[DIAG] Displayed course selection keyboard.")
            return SELECTING_QUIZ_TYPE # State for selecting course/unit/lesson
        else:
            logger.error("[DIAG] Failed to fetch courses from API.")
            safe_edit_message_text(query.message, text="عذراً، لم أتمكن من جلب قائمة المقررات. حاول مرة أخرى لاحقاً.", reply_markup=create_quiz_menu_keyboard())
            return QUIZ_MENU

    elif callback_data.startswith('select_course_'):
        course_id = callback_data.split('_')[-1]
        logger.info(f"[DIAG] Handling 'select_course_{course_id}' callback.")
        # Start quiz filtered by course_id
        return start_quiz(update, context, quiz_type='course', filter_id=course_id)

    # TODO: Implement similar logic for 'quiz_by_unit_prompt' and 'quiz_by_lesson_prompt'
    # Fetch units for a course: /api/v1/courses/<course_id>/units
    # Fetch lessons for a unit: /api/v1/units/<unit_id>/lessons
    # Then use callback_data like 'select_unit_<unit_id>' or 'select_lesson_<lesson_id>'
    # And call start_quiz with quiz_type='unit' or quiz_type='lesson'

    elif callback_data == 'quiz_by_unit_prompt':
        logger.warning("[DIAG] 'quiz_by_unit_prompt' not fully implemented yet.")
        safe_edit_message_text(query.message, text="اختيار الوحدة قيد الإنشاء.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

    elif callback_data == 'quiz_by_lesson_prompt':
        logger.warning("[DIAG] 'quiz_by_lesson_prompt' not fully implemented yet.")
        safe_edit_message_text(query.message, text="اختيار الدرس قيد الإنشاء.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

    # --- Quiz Answering ---
    elif callback_data.startswith('quiz_answer_'):
        logger.info(f"[DIAG] Handling quiz answer callback: {callback_data}")
        parts = callback_data.split('_')
        if len(parts) == 4:
            _, quiz_id_str, question_index_str, selected_option_str = parts
            try:
                quiz_id = int(quiz_id_str)
                question_index = int(question_index_str)
                selected_option = int(selected_option_str)
                logger.info(f"[DIAG] Parsed answer: quiz_id={quiz_id}, question_index={question_index}, selected_option={selected_option}")
                return handle_quiz_answer(update, context, quiz_id, question_index, selected_option)
            except ValueError:
                logger.error(f"[DIAG] Invalid format in quiz answer callback: {callback_data}")
        else:
            logger.error(f"[DIAG] Unexpected format in quiz answer callback: {callback_data}")

    elif callback_data.startswith('quiz_skip_'):
        logger.info(f"[DIAG] Handling quiz skip callback: {callback_data}")
        parts = callback_data.split('_')
        if len(parts) == 3:
            _, quiz_id_str, question_index_str = parts
            try:
                quiz_id = int(quiz_id_str)
                question_index = int(question_index_str)
                logger.info(f"[DIAG] Parsed skip: quiz_id={quiz_id}, question_index={question_index}")
                return handle_quiz_skip(chat_id, user_id, quiz_id, question_index, context)
            except ValueError:
                logger.error(f"[DIAG] Invalid format in quiz skip callback: {callback_data}")
        else:
            logger.error(f"[DIAG] Unexpected format in quiz skip callback: {callback_data}")

    # --- Admin Functions (Example) ---
    elif callback_data == 'admin_show_stats' and is_admin(user_id):
        logger.info("[DIAG] Handling 'admin_show_stats' callback. (Not Implemented Yet)")
        safe_edit_message_text(query.message, text="عرض الإحصائيات (قيد الإنشاء).", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU

    # --- Fallback for unknown callbacks ---
    else:
        logger.warning(f"[DIAG] Received unknown callback data: '{callback_data}' from user {user_id}")
        # Optionally send a message back or just ignore
        # safe_edit_message_text(query.message, text="عذراً، هذا الخيار غير معروف أو غير متاح حالياً.")
        return ConversationHandler.END # Or return current state if appropriate

    # Default return if no state change occurred in the specific handlers above
    # This might need adjustment based on conversation flow
    # return MAIN_MENU # Or the relevant menu state

# --- Quiz Logic ---

def start_quiz(update: Update, context: CallbackContext, quiz_type: str, filter_id: str | int = None, num_questions: int = DEFAULT_QUIZ_QUESTIONS, duration_minutes: int = DEFAULT_QUIZ_DURATION_MINUTES) -> int:
    """Starts a quiz based on the selected type and filter."""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    logger.info(f"[DIAG] Attempting to start quiz: type='{quiz_type}', filter='{filter_id}', user={user.id}")

    # Determine API endpoint based on quiz_type
    endpoint = None
    params = {'limit': num_questions}
    if quiz_type == 'random':
        endpoint = "/api/v1/questions/random"
    elif quiz_type == 'lesson' and filter_id:
        endpoint = f"/api/v1/lessons/{filter_id}/questions"
    elif quiz_type == 'unit' and filter_id:
        endpoint = f"/api/v1/units/{filter_id}/questions"
    elif quiz_type == 'course' and filter_id:
        endpoint = f"/api/v1/courses/{filter_id}/questions"
    else:
        logger.error(f"[DIAG] Invalid quiz type or missing filter_id for quiz start: type='{quiz_type}', filter='{filter_id}'")
        safe_edit_message_text(query.message, text="حدث خطأ عند بدء الاختبار. نوع الاختبار غير صالح.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

    # Fetch questions from API
    logger.info(f"[DIAG] Fetching questions for quiz from endpoint: {endpoint}")
    api_questions = fetch_questions_from_api(endpoint, params=params)

    if not api_questions:
        logger.error(f"[DIAG] No questions received from API for endpoint {endpoint}. Cannot start quiz.")
        safe_edit_message_text(query.message, text="عذراً، لم يتم العثور على أسئلة لهذا الاختبار. قد يكون المحتوى غير متوفر بعد.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

    # Transform questions to bot format
    logger.info("[DIAG] Transforming API questions to bot format.")
    questions = []
    for q in api_questions:
        transformed = transform_api_question(q)
        if transformed:
            questions.append(transformed)

    if not questions:
        logger.error("[DIAG] All questions from API failed transformation. Cannot start quiz.")
        safe_edit_message_text(query.message, text="عذراً، حدث خطأ أثناء تجهيز الأسئلة. حاول مرة أخرى لاحقاً.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

    # Shuffle questions (optional, API might already randomize for 'random')
    # random.shuffle(questions)
    logger.info(f"[DIAG] Successfully prepared {len(questions)} questions for the quiz.")

    # Initialize quiz data in user_data
    quiz_id = int(time.time() * 1000) # Simple unique ID
    quiz_data = {
        "quiz_id": quiz_id,
        "questions": questions,
        "current_question_index": 0,
        "answers": {},
        "score": 0,
        "start_time": datetime.now(),
        "duration_minutes": duration_minutes,
        "quiz_type": quiz_type,
        "filter_id": filter_id,
        "timed_out": False,
        "quiz_timer_job_name": None,
        "question_timer_job_name": None,
        "last_message_id": None
    }
    context.user_data["current_quiz"] = quiz_data
    logger.info(f"[DIAG] Initialized quiz data for quiz_id {quiz_id}, user {user.id}")

    # Set quiz timer
    quiz_data["quiz_timer_job_name"] = set_quiz_timer(context, chat_id, user.id, quiz_id, duration_minutes)

    # Send the first question
    logger.info("[DIAG] Sending first question of the quiz.")
    send_question(update, context, chat_id, user.id, quiz_id, 0)

    return TAKING_QUIZ

def send_question(update: Update, context: CallbackContext, chat_id: int, user_id: int, quiz_id: int, question_index: int):
    """Sends a specific question to the user."""
    logger.info(f"[DIAG] Preparing to send question {question_index} for quiz {quiz_id}, user {user_id}")
    quiz_data = context.user_data.get("current_quiz")

    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.error(f"[DIAG] Quiz data mismatch or not found when trying to send question {question_index}. Quiz ID: {quiz_id}")
        # Maybe send an error message?
        return

    if question_index >= len(quiz_data["questions"]):
        logger.error(f"[DIAG] Invalid question index {question_index} requested for quiz {quiz_id}. Max index: {len(quiz_data['questions']) - 1}")
        return

    question = quiz_data["questions"][question_index]
    quiz_data["current_question_index"] = question_index # Update current index

    # Build keyboard with options
    keyboard_buttons = []
    options_text = [question["option1"], question["option2"], question["option3"], question["option4"]]
    options_images = [question["option1_image"], question["option2_image"], question["option3_image"], question["option4_image"]]

    has_image_options = any(img for img in options_images)

    for i, opt_text in enumerate(options_text):
        if opt_text:
            callback = f'quiz_answer_{quiz_id}_{question_index}_{i}'
            keyboard_buttons.append([InlineKeyboardButton(opt_text, callback_data=callback)])
        elif options_images[i]: # If text is None but image exists
             # Need a way to represent image-only options, maybe placeholder text?
             callback = f'quiz_answer_{quiz_id}_{question_index}_{i}'
             keyboard_buttons.append([InlineKeyboardButton(f"[صورة الخيار {i+1}]", callback_data=callback)])

    # Add skip button
    keyboard_buttons.append([InlineKeyboardButton("⏭️ تخطي السؤال", callback_data=f'quiz_skip_{quiz_id}_{question_index}')])
    reply_markup = InlineKeyboardMarkup(keyboard_buttons)

    # Prepare message content
    question_number = question_index + 1
    total_questions = len(quiz_data["questions"])
    message_text = f"*السؤال {question_number} من {total_questions}:*\n\n"
    if question["question_text"]:
        message_text += process_text_with_chemical_notation(question["question_text"])

    # --- Sending Logic (Handle Text, Question Image, Option Images) ---
    media = []
    caption = message_text
    main_image_url = question.get("image_url")

    # Add main question image first if it exists
    if main_image_url:
        try:
            # Fetch image content
            response = requests.get(main_image_url, timeout=15)
            response.raise_for_status()
            image_content = BytesIO(response.content)
            image_content.seek(0) # Reset stream position
            media.append(InputMediaPhoto(media=image_content, caption=caption if not media else '', parse_mode=ParseMode.MARKDOWN))
            caption = '' # Caption only on the first image
            logger.info(f"[DIAG] Added main question image {main_image_url} to media group.")
        except Exception as e:
            logger.error(f"[DIAG] Failed to fetch or add main question image {main_image_url}: {e}")
            # Fallback to sending text only if image fails
            main_image_url = None # Ensure we don't try to send it again

    # Add option images if they exist
    if has_image_options:
        for i, img_url in enumerate(options_images):
            if img_url:
                try:
                    response = requests.get(img_url, timeout=15)
                    response.raise_for_status()
                    image_content = BytesIO(response.content)
                    image_content.seek(0)
                    # Add option label to caption if no main image or this is not the first image
                    option_caption = f"صورة الخيار {i+1}" if (not main_image_url and not media) or media else ''
                    media.append(InputMediaPhoto(media=image_content, caption=option_caption, parse_mode=ParseMode.MARKDOWN))
                    logger.info(f"[DIAG] Added option image {i+1} ({img_url}) to media group.")
                except Exception as e:
                    logger.error(f"[DIAG] Failed to fetch or add option image {i+1} ({img_url}): {e}")
                    # Maybe add placeholder text to caption if image fails?
                    if not media: # If this was supposed to be the first image
                         caption += f"\n(فشل تحميل صورة الخيار {i+1})"
                    # else: # Image group already started, can't add text easily

    # --- Send Message --- #
    sent_message = None
    try:
        # Delete previous question message if possible
        if quiz_data.get("last_message_id"):
            try:
                context.bot.delete_message(chat_id=chat_id, message_id=quiz_data["last_message_id"])
                logger.info(f"[DIAG] Deleted previous message {quiz_data['last_message_id']}")
            except TelegramError as e:
                logger.warning(f"[DIAG] Failed to delete previous message {quiz_data['last_message_id']}: {e}")
            quiz_data["last_message_id"] = None

        if media:
            logger.info(f"[DIAG] Sending question {question_index} as media group (count: {len(media)}). Caption set: {bool(caption)}")
            # Send media group
            sent_messages = context.bot.send_media_group(chat_id=chat_id, media=media, timeout=30)
            sent_message = sent_messages[0] # Use the first message for context
            # Send the keyboard separately as media groups don't support them directly
            keyboard_message_text = "اختر الإجابة الصحيحة:" if not has_image_options else "اختر الإجابة الصحيحة (راجع الصور أعلاه):"
            keyboard_message = safe_send_message(context.bot, chat_id, text=keyboard_message_text, reply_markup=reply_markup)
            quiz_data["last_message_id"] = keyboard_message.message_id if keyboard_message else None # Store ID of keyboard message
            logger.info(f"[DIAG] Sent media group and separate keyboard message {quiz_data.get('last_message_id')}.")
        elif main_image_url: # Should not happen if media list was populated, but as fallback
            logger.info(f"[DIAG] Sending question {question_index} as single photo: {main_image_url}")
            sent_message = context.bot.send_photo(chat_id=chat_id, photo=main_image_url, caption=caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN, timeout=30)
            quiz_data["last_message_id"] = sent_message.message_id
            logger.info(f"[DIAG] Sent single photo message {sent_message.message_id}.")
        else:
            logger.info(f"[DIAG] Sending question {question_index} as text message.")
            sent_message = safe_send_message(context.bot, chat_id, text=caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            quiz_data["last_message_id"] = sent_message.message_id if sent_message else None
            logger.info(f"[DIAG] Sent text message {quiz_data.get('last_message_id')}.")

    except BadRequest as e:
        logger.error(f"[DIAG] Telegram BadRequest sending question {question_index}: {e}. Text length: {len(caption)}")
        safe_send_message(context.bot, chat_id, text="حدث خطأ أثناء إرسال السؤال. قد يكون السؤال طويلاً جداً أو غير صالح.")
        # Consider ending the quiz or skipping the question
    except TimedOut:
         logger.error(f"[DIAG] Telegram TimedOut sending question {question_index}.")
         safe_send_message(context.bot, chat_id, text="حدث خطأ في الشبكة أثناء إرسال السؤال. حاول مرة أخرى.")
    except Exception as e:
        logger.exception(f"[DIAG] Unexpected error sending question {question_index}: {e}")
        safe_send_message(context.bot, chat_id, text="حدث خطأ غير متوقع أثناء إرسال السؤال.")

    # Set question timer if enabled
    if sent_message: # Only set timer if question was sent successfully
        quiz_data["question_timer_job_name"] = set_question_timer(context, chat_id, user_id, quiz_id, question_index)
    else:
        logger.error(f"[DIAG] Question {question_index} was not sent successfully. Not setting question timer.")

def handle_quiz_answer(update: Update, context: CallbackContext, quiz_id: int, question_index: int, selected_option: int) -> int:
    """Handles the user's answer to a quiz question."""
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    logger.info(f"[DIAG] Processing answer for question {question_index}, quiz {quiz_id}, user {user_id}. Selected: {selected_option}")

    quiz_data = context.user_data.get("current_quiz")

    # --- Validations ---
    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.warning(f"[DIAG] Received answer for inactive/mismatched quiz {quiz_id}. Ignoring.")
        safe_edit_message_text(query.message, text="هذا الاختبار لم يعد نشطاً.")
        return TAKING_QUIZ # Or MAIN_MENU?

    if question_index != quiz_data["current_question_index"]:
        logger.warning(f"[DIAG] Received answer for wrong question index {question_index} (expected {quiz_data['current_question_index']}). Ignoring.")
        # Don't edit message, user might have clicked an old button
        return TAKING_QUIZ

    if question_index in quiz_data["answers"]:
        logger.warning(f"[DIAG] Question {question_index} already answered. Ignoring duplicate answer.")
        # Don't edit message
        return TAKING_QUIZ

    # --- Process Answer ---
    question = quiz_data["questions"][question_index]
    correct_answer_index = question["correct_answer"]
    is_correct = (selected_option == correct_answer_index)

    quiz_data["answers"][question_index] = {
        "selected": selected_option,
        "correct": correct_answer_index,
        "is_correct": is_correct,
        "time": datetime.now()
    }

    if is_correct:
        quiz_data["score"] += 1
        feedback_text = "✅ إجابة صحيحة!"
    else:
        feedback_text = f"❌ إجابة خاطئة. الإجابة الصحيحة هي الخيار رقم {correct_answer_index + 1}."

    # Add explanation if available (currently always None from API)
    # if question.get("explanation"):
    #     feedback_text += f"\n\n*الشرح:* {question['explanation']}"

    logger.info(f"[DIAG] Answer processed. Correct: {is_correct}. Score: {quiz_data['score']}")

    # Remove question timer
    if quiz_data.get("question_timer_job_name"):
        remove_job_if_exists(quiz_data["question_timer_job_name"], context)
        quiz_data["question_timer_job_name"] = None

    # Edit the message to show feedback (remove keyboard)
    # If message was media group, we edit the keyboard message
    message_to_edit = query.message
    if quiz_data.get("last_message_id") and quiz_data["last_message_id"] != query.message.message_id:
        # This implies the keyboard was sent separately after a media group
        # We should ideally edit THAT message, but need its chat_id too.
        # For now, let's just edit the button message itself.
        logger.warning("[DIAG] Editing button message, not the separate keyboard message after media group.")

    safe_edit_message_text(message_to_edit, text=message_to_edit.text + f"\n\n{feedback_text}", reply_markup=None)
    logger.info("[DIAG] Edited message to show feedback.")

    # --- Move to Next Question or End Quiz ---
    next_question_index = question_index + 1
    if next_question_index < len(quiz_data["questions"]):
        logger.info(f"[DIAG] Scheduling next question ({next_question_index}) after delay.")
        # Schedule sending the next question after a short delay
        context.job_queue.run_once(
            lambda ctx: send_question(update, ctx, chat_id, user_id, quiz_id, next_question_index),
            FEEDBACK_DELAY,
            name=f"next_q_{chat_id}_{user_id}_{quiz_id}"
        )
        return TAKING_QUIZ
    else:
        logger.info("[DIAG] Quiz finished. Scheduling results display.")
        # End of quiz
        context.job_queue.run_once(
            lambda ctx: show_results(chat_id, user_id, quiz_id, ctx),
            FEEDBACK_DELAY,
            name=f"show_res_{chat_id}_{user_id}_{quiz_id}"
        )
        return SHOWING_RESULTS # Transition to a state indicating results are shown

def handle_quiz_skip(chat_id: int, user_id: int, quiz_id: int, question_index: int, context: CallbackContext, timed_out: bool = False) -> int:
    """Handles skipping a question."""
    logger.info(f"[DIAG] Skipping question {question_index} for quiz {quiz_id}, user {user_id}. Timed out: {timed_out}")
    quiz_data = context.user_data.get("current_quiz")

    if not quiz_data or quiz_data["quiz_id"] != quiz_id or question_index != quiz_data["current_question_index"]:
        logger.warning("[DIAG] Skip request for inactive/mismatched quiz or wrong question index. Ignoring.")
        return TAKING_QUIZ

    if question_index in quiz_data["answers"]:
        logger.warning(f"[DIAG] Question {question_index} already answered. Ignoring skip request.")
        return TAKING_QUIZ

    # Mark as skipped (incorrect)
    question = quiz_data["questions"][question_index]
    correct_answer_index = question["correct_answer"]
    quiz_data["answers"][question_index] = {
        "selected": None, # Mark as skipped
        "correct": correct_answer_index,
        "is_correct": False,
        "time": datetime.now(),
        "skipped": True
    }

    # Remove question timer
    if quiz_data.get("question_timer_job_name"):
        remove_job_if_exists(quiz_data["question_timer_job_name"], context)
        quiz_data["question_timer_job_name"] = None

    # Provide feedback if not timed out
    if not timed_out:
        feedback_text = f"تم تخطي السؤال {question_index + 1}. الإجابة الصحيحة كانت الخيار رقم {correct_answer_index + 1}."
        # Edit the message
        message_id_to_edit = quiz_data.get("last_message_id")
        if message_id_to_edit:
            try:
                # Fetch the message text first if possible to append feedback
                # This might be complex if it was a media group
                # For simplicity, just replace the keyboard message text
                context.bot.edit_message_text(chat_id=chat_id, message_id=message_id_to_edit, text=feedback_text, reply_markup=None)
                logger.info("[DIAG] Edited message to show skip feedback.")
            except TelegramError as e:
                logger.warning(f"[DIAG] Failed to edit message {message_id_to_edit} for skip feedback: {e}")
        else:
             safe_send_message(context.bot, chat_id, text=feedback_text)

    # --- Move to Next Question or End Quiz ---
    next_question_index = question_index + 1
    if next_question_index < len(quiz_data["questions"]):
        logger.info(f"[DIAG] Scheduling next question ({next_question_index}) after skip/timeout.")
        delay = 0 if timed_out else FEEDBACK_DELAY
        context.job_queue.run_once(
            lambda ctx: send_question(None, ctx, chat_id, user_id, quiz_id, next_question_index), # Pass None for update if called from timer/skip
            delay,
            name=f"next_q_{chat_id}_{user_id}_{quiz_id}"
        )
        return TAKING_QUIZ
    else:
        logger.info("[DIAG] Quiz finished after skip/timeout. Scheduling results display.")
        delay = 0 if timed_out else FEEDBACK_DELAY
        context.job_queue.run_once(
            lambda ctx: show_results(chat_id, user_id, quiz_id, ctx),
            delay,
            name=f"show_res_{chat_id}_{user_id}_{quiz_id}"
        )
        return SHOWING_RESULTS

def show_results(chat_id: int, user_id: int, quiz_id: int, context: CallbackContext, timed_out: bool = False):
    """Calculates and displays the quiz results."""
    logger.info(f"[DIAG] Displaying results for quiz {quiz_id}, user {user_id}. Timed out: {timed_out}")
    quiz_data = context.user_data.get("current_quiz")

    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.warning(f"[DIAG] Results requested for inactive/mismatched quiz {quiz_id}. Ignoring.")
        return

    # Ensure timers are cleaned up
    if quiz_data.get("quiz_timer_job_name"):
        remove_job_if_exists(quiz_data["quiz_timer_job_name"], context)
    if quiz_data.get("question_timer_job_name"):
        remove_job_if_exists(quiz_data["question_timer_job_name"], context)

    score = quiz_data["score"]
    total_questions = len(quiz_data["questions"])
    answered_count = len(quiz_data["answers"])
    skipped_count = sum(1 for ans in quiz_data["answers"].values() if ans.get("skipped"))
    correct_count = score
    incorrect_count = answered_count - correct_count - skipped_count
    unanswered_count = total_questions - answered_count

    percentage = (score / total_questions * 100) if total_questions > 0 else 0

    results_text = f"🏁 *نتائج الاختبار* 🏁\n\n"
    if timed_out:
        results_text += "⏰ انتهى وقت الاختبار المحدد!\n"
    results_text += f"▫️ عدد الأسئلة الكلي: {total_questions}\n"
    results_text += f"✅ الإجابات الصحيحة: {correct_count}\n"
    results_text += f"❌ الإجابات الخاطئة: {incorrect_count}\n"
    results_text += f"⏭️ الأسئلة المتخطاة: {skipped_count}\n"
    if unanswered_count > 0:
         results_text += f"❓ الأسئلة غير المجابة: {unanswered_count}\n"
    results_text += f"\n🎯 *النتيجة النهائية: {score} من {total_questions} ({percentage:.1f}%)*\n\n"

    # Add performance message
    if percentage >= 90:
        results_text += "🎉 أداء ممتاز! أنت تتقن هذه المادة!"
    elif percentage >= 75:
        results_text += "👍 جيد جداً! استمر في المذاكرة."
    elif percentage >= 50:
        results_text += "🙂 لا بأس، تحتاج إلى مراجعة بعض النقاط."
    else:
        results_text += "🤔 تحتاج إلى المزيد من المذاكرة والتركيز."

    # Save results to database
    if QUIZ_DB:
        try:
            QUIZ_DB.save_quiz_result(
                user_id=user_id,
                quiz_type=quiz_data["quiz_type"],
                filter_id=quiz_data.get("filter_id"), # May be None
                score=score,
                total_questions=total_questions,
                percentage=percentage,
                duration_seconds=int((datetime.now() - quiz_data["start_time"]).total_seconds()),
                details=quiz_data["answers"] # Save detailed answers
            )
            logger.info(f"[DIAG] Saved quiz results for user {user_id}, quiz {quiz_id} to DB.")
        except Exception as e:
            logger.error(f"[DIAG] Failed to save quiz results for user {user_id}, quiz {quiz_id} to DB: {e}")
            results_text += "\n\n*(تحذير: لم يتم حفظ نتيجتك بسبب خطأ في قاعدة البيانات.)*"

    # Clean up quiz data from user_data
    context.user_data.pop("current_quiz", None)
    logger.info(f"[DIAG] Cleared quiz data for user {user_id}.")

    # Send results message with main menu keyboard
    keyboard = create_main_menu_keyboard(user_id)
    safe_send_message(context.bot, chat_id, text=results_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    logger.info(f"[DIAG] Sent quiz results to user {user_id}.")

# --- Error Handler ---

def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # Optionally, notify the user or admin about the error
    # if isinstance(update, Update) and update.effective_chat:
    #     safe_send_message(context.bot, update.effective_chat.id, text="عذراً، حدث خطأ ما أثناء معالجة طلبك.")

# --- Main Function ---

def main() -> None:
    """Start the bot."""
    logger.info("Starting bot...")

    # Create the Updater and pass it your bot's token.
    updater = Updater(BOT_TOKEN)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # --- Conversation Handler Setup ---
    # We might simplify this if admin functions are removed
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MAIN_MENU: [CallbackQueryHandler(button_handler)],
            QUIZ_MENU: [CallbackQueryHandler(button_handler)],
            ADMIN_MENU: [CallbackQueryHandler(button_handler)],
            SELECTING_QUIZ_TYPE: [CallbackQueryHandler(button_handler)], # For course/unit/lesson selection
            TAKING_QUIZ: [CallbackQueryHandler(button_handler)], # Handles answers/skips
            SHOWING_RESULTS: [CallbackQueryHandler(button_handler)], # Handles button presses on results screen (if any)
            # Add other states if needed (e.g., INFO_MENU)
        },
        fallbacks=[
            CommandHandler('start', start), # Allow restarting
            CommandHandler('about', about),
            CallbackQueryHandler(button_handler), # Catch stray button presses?
            MessageHandler(filters.COMMAND, unknown_command),
            MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message)
        ],
        # per_user=True, per_chat=False # Default
    )

    dp.add_handler(conv_handler)

    # Add a generic error handler
    dp.add_error_handler(error_handler)

    # Start the Bot using polling
    logger.info("Starting polling...")
    updater.start_polling()
    logger.info("Bot started and running...")

    # Run the bot until you press Ctrl-C
    updater.idle()
    logger.info("Bot stopped.")

if __name__ == '__main__':
    main()

