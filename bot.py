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
    sys.exit("Database configuration error.")

DB_CONN = connect_db(DATABASE_URL)
if DB_CONN:
    setup_database() # Ensure tables exist (users, quiz_results)
    QUIZ_DB = QuizDatabase(DB_CONN) # Keep instance for user/result methods
    logger.info("QuizDatabase initialized successfully (for users/results).")
else:
    logger.error("Failed to establish database connection. Bot cannot save user/result data.")
    # Decide if this is critical - maybe allow bot to run without saving results?
    # sys.exit("Database connection failed.")
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
    logger.info(f"Fetching questions from API: {url} with params: {params}")
    try:
        response = requests.get(url, params=params, timeout=20) # Added timeout
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        data = response.json()
        logger.info(f"Successfully fetched {len(data) if isinstance(data, list) else 0} items from {url}")
        # Basic validation: Check if it's a list
        if isinstance(data, list):
            return data
        else:
            logger.error(f"API response from {url} is not a list: {type(data)}")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed for {url}: {e}")
        return None
    except ValueError as e: # Includes JSONDecodeError
        logger.error(f"Failed to decode JSON response from {url}: {e}")
        return None

def transform_api_question(api_question: dict) -> dict | None:
    """Transforms a single question object from API format to bot format."""
    if not isinstance(api_question, dict):
        logger.error(f"Invalid API question format: Expected dict, got {type(api_question)}")
        return None

    question_id = api_question.get("question_id")
    question_text = api_question.get("question_text")
    question_image_url = api_question.get("image_url")
    api_options = api_question.get("options")

    if question_id is None or not isinstance(api_options, list):
        logger.error(f"Skipping question due to missing ID or invalid options: {api_question}")
        return None

    # Bot expects exactly 4 options, API might return more or less?
    # Let's take the first 4, or pad with None if fewer.
    bot_options_text = [None] * 4
    bot_options_image = [None] * 4
    correct_answer_index = None

    for i, opt in enumerate(api_options):
        if i >= 4: # Limit to 4 options for the bot
            logger.warning(f"Question {question_id} has more than 4 options, ignoring extras.")
            break
        if isinstance(opt, dict):
            bot_options_text[i] = opt.get("option_text")
            bot_options_image[i] = opt.get("image_url") # Store option image URL
            if opt.get("is_correct") is True:
                if correct_answer_index is not None:
                    logger.warning(f"Multiple correct options found for question {question_id}. Using the first one.")
                else:
                    correct_answer_index = i # 0-based index
        else:
            logger.warning(f"Invalid option format in question {question_id}: {opt}")

    # Basic validation: Ensure question has text or image, and a correct answer
    if not question_text and not question_image_url:
        logger.error(f"Skipping question {question_id}: No text or image provided.")
        return None
    if correct_answer_index is None:
        logger.error(f"Skipping question {question_id}: No correct answer found.")
        return None
    # Ensure the correct option actually exists
    if bot_options_text[correct_answer_index] is None and bot_options_image[correct_answer_index] is None:
        logger.error(f"Skipping question {question_id}: Correct answer option ({correct_answer_index}) has no text or image.")
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
    # logger.debug(f"Transformed question {question_id}: {bot_question}")
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

# --- DEPRECATED/REMOVED KEYBOARDS (Related to old DB structure) ---
# create_structure_admin_menu_keyboard, create_grade_levels_keyboard,
# create_chapters_keyboard, create_lessons_keyboard might be removed or
# need complete rework based on API data for courses/units/lessons.
# For now, keep them but they might rely on QUIZ_DB methods that are gone.

def create_quiz_duration_keyboard():
    keyboard = [
        [InlineKeyboardButton("5 دقائق", callback_data='quiz_duration_5')],
        [InlineKeyboardButton("10 دقائق", callback_data='quiz_duration_10')],
        [InlineKeyboardButton("15 دقائق", callback_data='quiz_duration_15')],
        [InlineKeyboardButton("20 دقائق", callback_data='quiz_duration_20')],
        [InlineKeyboardButton("30 دقائق", callback_data='quiz_duration_30')],
        [InlineKeyboardButton("بدون وقت محدد", callback_data='quiz_duration_0')],
        [InlineKeyboardButton("🔙 العودة لاختيار النوع", callback_data='menu_quiz')]
    ]
    return InlineKeyboardMarkup(keyboard)

# TODO: Need functions to fetch Courses, Units, Lessons from API to build dynamic keyboards
def create_courses_keyboard(for_quiz=True, context=None):
    # Placeholder - Needs API call to fetch courses
    logger.warning("create_courses_keyboard needs implementation using API call.")
    courses = [] # Replace with API call: fetch_from_api('/api/v1/courses')? Check response format.
    keyboard = []
    if courses:
        # Assuming API returns list of {'course_id': id, 'name': name}
        for course in courses:
             callback_data = f'select_course_quiz_{course["course_id"]}' # Example callback
             keyboard.append([InlineKeyboardButton(course["name"], callback_data=callback_data)])

    back_callback = 'menu_quiz' if for_quiz else 'admin_manage_structure' # Adjust as needed
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_units_keyboard(course_id, for_quiz=True, context=None):
    # Placeholder - Needs API call to fetch units for a course
    logger.warning(f"create_units_keyboard needs implementation using API call for course {course_id}.")
    units = [] # Replace with API call: fetch_from_api(f'/api/v1/courses/{course_id}/units')? Check endpoint/format.
    keyboard = []
    if units:
         # Assuming API returns list of {'unit_id': id, 'name': name}
        for unit in units:
             callback_data = f'select_unit_quiz_{unit["unit_id"]}' # Example callback
             keyboard.append([InlineKeyboardButton(unit["name"], callback_data=callback_data)])

    back_callback = 'quiz_by_course_prompt' # Go back to course selection
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_lessons_keyboard(unit_id, for_quiz=True, context=None):
    # Placeholder - Needs API call to fetch lessons for a unit
    logger.warning(f"create_lessons_keyboard needs implementation using API call for unit {unit_id}.")
    lessons = [] # Replace with API call: fetch_from_api(f'/api/v1/units/{unit_id}/lessons')? Check endpoint/format.
    keyboard = []
    if lessons:
         # Assuming API returns list of {'lesson_id': id, 'name': name}
        for lesson in lessons:
             callback_data = f'select_lesson_quiz_{lesson["lesson_id"]}' # Example callback
             keyboard.append([InlineKeyboardButton(lesson["name"], callback_data=callback_data)])

    back_callback = 'quiz_by_unit_prompt' # Go back to unit selection
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_info_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("⚛️ الجدول الدوري", callback_data='info_periodic_table')],
        [InlineKeyboardButton("🧪 المركبات الشائعة", callback_data='info_compounds')],
        [InlineKeyboardButton("💡 المفاهيم الأساسية", callback_data='info_concepts')],
        [InlineKeyboardButton("🔢 الحسابات الكيميائية", callback_data='info_calculations')],
        [InlineKeyboardButton("🔗 الروابط الكيميائية", callback_data='info_bonds')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_back_button(target_menu='main_menu'):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=target_menu)]])

# --- Command Handlers ---

def start(update: Update, context: CallbackContext) -> int:
    logger.info("****** RECEIVED UPDATE: Processing /start command ******") # Diagnostic log added
    user = update.effective_user
    user_id = user.id
    username = user.username
    first_name = user.first_name
    last_name = user.last_name

    logger.info(f"User {user_id} ({get_user_name(user)}) started the bot.")

    # Add or update user in DB (using QUIZ_DB if available)
    if QUIZ_DB:
        QUIZ_DB.add_or_update_user(user_id, username, first_name, last_name)
    else:
        logger.warning("QUIZ_DB not available, cannot update user info.")

    welcome_message = f"أهلاً بك يا {get_user_name(user)} في بوت الكيمياء التعليمي!\n\n"
    welcome_message += "يمكنك استكشاف المعلومات الكيميائية أو بدء اختبار جديد.\n"
    welcome_message += "استخدم الأزرار أدناه للتنقل."

    reply_markup = create_main_menu_keyboard(user_id)
    if update.message:
        update.message.reply_text(welcome_message, reply_markup=reply_markup)
    elif update.callback_query:
        # If coming from a callback, edit the message
        safe_edit_message_text(context=context, chat_id=update.effective_chat.id,
                               message_id=update.callback_query.message.message_id,
                               text=welcome_message, reply_markup=reply_markup)

    return MAIN_MENU

def about(update: Update, context: CallbackContext):
    about_text = "بوت الكيمياء التعليمي\n"
    about_text += "تم تطوير هذا البوت لمساعدتك في تعلم الكيمياء واختبار معلوماتك.\n"
    about_text += "\nالميزات:\n- اختبارات متنوعة (عشوائية ومخصصة).\n- معلومات حول العناصر والمركبات والمفاهيم.\n- (المزيد قادمًا...)"
    # Add version or contact info if desired

    reply_markup = create_back_button('main_menu')
    if update.message:
        update.message.reply_text(about_text, reply_markup=reply_markup)
    elif update.callback_query:
        safe_edit_message_text(context=context, chat_id=update.effective_chat.id,
                               message_id=update.callback_query.message.message_id,
                               text=about_text, reply_markup=reply_markup)

    return MAIN_MENU # Or a dedicated ABOUT state if needed

# --- Menu Handlers ---

def handle_main_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id

    menu_text = "القائمة الرئيسية: اختر أحد الخيارات أدناه."
    reply_markup = create_main_menu_keyboard(user_id)

    safe_edit_message_text(context=context, chat_id=query.message.chat_id,
                           message_id=query.message.message_id,
                           text=menu_text, reply_markup=reply_markup)
    return MAIN_MENU

def handle_quiz_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()

    menu_text = "📝 قائمة الاختبارات: اختر نوع الاختبار الذي تريده."
    reply_markup = create_quiz_menu_keyboard()

    safe_edit_message_text(context=context, chat_id=query.message.chat_id,
                           message_id=query.message.message_id,
                           text=menu_text, reply_markup=reply_markup)
    return QUIZ_MENU

def handle_admin_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id

    if not is_admin(user_id):
        query.edit_message_text(text="عذراً، هذه القائمة مخصصة للمشرفين فقط.")
        return MAIN_MENU

    menu_text = "⚙️ قائمة الإدارة: اختر الإجراء المطلوب."
    reply_markup = create_admin_menu_keyboard()
    safe_edit_message_text(context=context, chat_id=query.message.chat_id,
                           message_id=query.message.message_id,
                           text=menu_text, reply_markup=reply_markup)
    return ADMIN_MENU

def handle_info_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()

    menu_text = "📚 قائمة المعلومات الكيميائية: اختر الموضوع الذي يهمك."
    reply_markup = create_info_menu_keyboard()

    safe_edit_message_text(context=context, chat_id=query.message.chat_id,
                           message_id=query.message.message_id,
                           text=menu_text, reply_markup=reply_markup)
    return INFO_MENU

# --- Quiz Logic --- #

def prompt_quiz_duration(update: Update, context: CallbackContext, quiz_type: str, filter_id=None) -> int:
    """Asks the user to select the quiz duration."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    context.user_data["quiz_selection"] = {"type": quiz_type, "filter": filter_id}

    duration_text = "اختر مدة الاختبار:"
    reply_markup = create_quiz_duration_keyboard()
    safe_edit_message_text(context=context, chat_id=query.message.chat_id,
                           message_id=query.message.message_id,
                           text=duration_text, reply_markup=reply_markup)
    return SELECTING_QUIZ_DURATION

def handle_quiz_random_prompt(update: Update, context: CallbackContext) -> int:
    return prompt_quiz_duration(update, context, quiz_type="random")

# --- Placeholder handlers for selecting course/unit/lesson for quiz ---
def handle_quiz_by_course_prompt(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    # TODO: Fetch courses from API and display keyboard
    reply_markup = create_courses_keyboard(for_quiz=True, context=context)
    if not reply_markup.inline_keyboard or len(reply_markup.inline_keyboard) <= 1: # Only back button
         safe_edit_message_text(context=context, chat_id=query.message.chat_id,
                               message_id=query.message.message_id,
                               text="عذراً، لا توجد مقررات متاحة حالياً. حاول مرة أخرى لاحقاً.",
                               reply_markup=create_back_button('menu_quiz'))
         return QUIZ_MENU
    else:
        safe_edit_message_text(context=context, chat_id=query.message.chat_id,
                               message_id=query.message.message_id,
                               text="اختر المقرر لبدء الاختبار:",
                               reply_markup=reply_markup)
        return SELECTING_QUIZ_TYPE # State to handle course selection

def handle_quiz_by_unit_prompt(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    # TODO: Need to ask for Course first, then Unit. Add state SELECTING_COURSE_FOR_UNIT
    # For now, just show a placeholder message
    safe_edit_message_text(context=context, chat_id=query.message.chat_id,
                           message_id=query.message.message_id,
                           text="(مؤقت) اختيار الوحدة يتطلب اختيار المقرر أولاً. سيتم تنفيذ ذلك لاحقاً.",
                           reply_markup=create_back_button('menu_quiz'))
    # return SELECTING_COURSE_FOR_UNIT # Add this state later
    return QUIZ_MENU

def handle_quiz_by_lesson_prompt(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    # TODO: Need Course -> Unit -> Lesson selection flow.
    # For now, just show a placeholder message
    safe_edit_message_text(context=context, chat_id=query.message.chat_id,
                           message_id=query.message.message_id,
                           text="(مؤقت) اختيار الدرس يتطلب اختيار المقرر ثم الوحدة أولاً. سيتم تنفيذ ذلك لاحقاً.",
                           reply_markup=create_back_button('menu_quiz'))
    # return SELECTING_COURSE_FOR_LESSON # Add states later
    return QUIZ_MENU

# --- Handler for selecting Course/Unit/Lesson ID --- #
def handle_quiz_filter_selection(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    data = query.data
    query.answer()

    quiz_type = None
    filter_id = None

    if data.startswith("select_lesson_quiz_"):
        quiz_type = "lesson"
        filter_id = int(data.split("_")[-1])
    elif data.startswith("select_unit_quiz_"):
        quiz_type = "unit"
        filter_id = int(data.split("_")[-1])
    elif data.startswith("select_course_quiz_"):
        quiz_type = "course"
        filter_id = int(data.split("_")[-1])

    if quiz_type and filter_id is not None:
        logger.info(f"User selected quiz type: {quiz_type}, filter ID: {filter_id}")
        return prompt_quiz_duration(update, context, quiz_type=quiz_type, filter_id=filter_id)
    else:
        logger.warning(f"Could not parse quiz filter selection from callback data: {data}")
        safe_edit_message_text(context=context, chat_id=query.message.chat_id,
                               message_id=query.message.message_id,
                               text="حدث خطأ أثناء اختيار نوع الاختبار. يرجى المحاولة مرة أخرى.",
                               reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

# --- Starting the Quiz --- #
def start_quiz(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    chat_id = query.message.chat_id

    # Get selected duration
    duration_minutes = int(query.data.split("_")[-1])
    quiz_selection = context.user_data.get("quiz_selection", {})
    quiz_type = quiz_selection.get("type", "random")
    filter_id = quiz_selection.get("filter")

    logger.info(f"Starting quiz for user {user_id}: type={quiz_type}, filter={filter_id}, duration={duration_minutes}")

    # --- Fetch questions using API (NEW) ---
    api_questions = None
    endpoint = None
    limit = DEFAULT_QUIZ_QUESTIONS # How many questions to fetch/select?

    if quiz_type == "random":
        # Fetch all questions from all courses, then sample
        endpoint = "/api/v1/courses" # Endpoint returns list of questions across all courses?
        all_api_questions = fetch_questions_from_api(endpoint)
        if all_api_questions:
            if len(all_api_questions) >= limit:
                api_questions = random.sample(all_api_questions, limit)
            else:
                api_questions = all_api_questions # Use all available if less than limit
                logger.warning(f"Requested {limit} random questions, but only {len(api_questions)} available in total.")
        else:
             logger.error("Failed to fetch any questions from /api/v1/courses for random quiz.")

    elif quiz_type == "lesson" and filter_id is not None:
        endpoint = f"/api/v1/lessons/{filter_id}/questions"
        # API might return more than limit? Add limit param if API supports it?
        api_questions_all = fetch_questions_from_api(endpoint)
        if api_questions_all:
             if len(api_questions_all) >= limit:
                 api_questions = random.sample(api_questions_all, limit)
             else:
                 api_questions = api_questions_all
                 logger.warning(f"Requested {limit} questions for lesson {filter_id}, but only {len(api_questions)} available.")

    elif quiz_type == "unit" and filter_id is not None:
        endpoint = f"/api/v1/units/{filter_id}/questions"
        api_questions_all = fetch_questions_from_api(endpoint)
        if api_questions_all:
             if len(api_questions_all) >= limit:
                 api_questions = random.sample(api_questions_all, limit)
             else:
                 api_questions = api_questions_all
                 logger.warning(f"Requested {limit} questions for unit {filter_id}, but only {len(api_questions)} available.")

    elif quiz_type == "course" and filter_id is not None:
        endpoint = f"/api/v1/courses/{filter_id}/questions"
        api_questions_all = fetch_questions_from_api(endpoint)
        if api_questions_all:
             if len(api_questions_all) >= limit:
                 api_questions = random.sample(api_questions_all, limit)
             else:
                 api_questions = api_questions_all
                 logger.warning(f"Requested {limit} questions for course {filter_id}, but only {len(api_questions)} available.")

    # --- Transform and Validate Fetched Questions ---
    questions = []
    if api_questions:
        for q_data in api_questions:
            transformed_q = transform_api_question(q_data)
            if transformed_q:
                questions.append(transformed_q)
        logger.info(f"Successfully transformed {len(questions)} questions for the quiz.")
    else:
        logger.warning(f"No questions fetched or transformed from API for quiz type {quiz_type}.")
