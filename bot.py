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
    # Remove import of safe_edit_message_text, keep safe_send_message
    from helper_function import safe_send_message
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
# NOTE: Keyboards related to Grade/Chapter/Lesson selection might need # if the IDs/names are now fetched differently (e.g., via API or if QUIZ_DB structure changed)

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
    return InlineKeyboardMarkup(keyboard)ef create_admin_menu_keyboard():
    # Admin functions might need significant rework if questions are managed via web app/API
    keyboard = [
        # [InlineKeyboardButton("➕ إضافة سؤال", callback_data=\'admin_add_question\')], # Likely removed/changed
        # [InlineKeyboardButton("🗑️ حذف سؤال", callback_data=\'admin_delete_question\')], # Likely removed/changed
        # [InlineKeyboardButton("🔍 عرض سؤال", callback_data=\'admin_show_question\')], # Likely removed/changed
        # [InlineKeyboardButton("🏫 إدارة المراحل/الفصول/الدروس", callback_data=\'admin_manage_structure\')], # Likely removed/changed
        [InlineKeyboardButton("📊 عرض إحصائيات المستخدمين", callback_data=\'admin_stats\')],
        [InlineKeyboardButton("📢 إرسال رسالة للجميع", callback_data=\'admin_broadcast\')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=\'main_menu\')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_quiz_options_keyboard(question, quiz_id, question_index):
    """Creates the keyboard with answer options for a given question."""
    options = [
        question["option1"],
        question["option2"],
        question["option3"],
        question["option4"]
    ]
    keyboard = []
    for i, option_text in enumerate(options):
        if option_text: # Only add button if option text exists
            callback_data = f"quiz_{quiz_id}_{question_index}_{i}"
            keyboard.append([InlineKeyboardButton(option_text, callback_data=callback_data)])

    # Add skip button
    skip_callback = f"skip_{quiz_id}_{question_index}"
    keyboard.append([InlineKeyboardButton("⏭️ تخطي السؤال", callback_data=skip_callback)])

    # Add end quiz button
    end_callback = f"end_{quiz_id}"
    keyboard.append([InlineKeyboardButton("⏹️ إنهاء الاختبار", callback_data=end_callback)])

    return InlineKeyboardMarkup(keyboard)

def create_back_button(callback_data=\'main_menu\'):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=callback_data)]])

# --- Command Handlers ---

def start(update: Update, context: CallbackContext):
    """Handles the /start command."""
    user = update.effective_user
    user_id = user.id
    chat_id = update.effective_chat.id
    user_name = get_user_name(user)
    logger.info(f"[DIAG] Received /start command from user {user_id} ({user_name}).")

    # Register or update user in DB (if DB is available)
    if QUIZ_DB:
        QUIZ_DB.register_user(user_id, user_name, user.username)
        logger.info(f"[DIAG] User {user_id} registered/updated in DB.")
    else:
        logger.warning("[DIAG] Database not available, skipping user registration.")

    text = f"👋 أهلاً بك يا {user_name} في بوت الكيمياء التعليمي!\n\nماذا تريد أن تفعل اليوم؟"
    reply_markup = create_main_menu_keyboard(user_id)

    logger.info("[DIAG] Sending welcome message and main menu keyboard.")
    safe_send_message(context.bot, chat_id, text=text, reply_markup=reply_markup)
    logger.info("[DIAG] Finished processing /start command.")
    return MAIN_MENU # Return state for conversation handler

def about(update: Update, context: CallbackContext):
    """Handles the /about command."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    logger.info(f"[DIAG] Received /about command from user {user.id}.")

    text = ("🤖 **بوت الكيمياء التعليمي**\n\n" + # Bold title
            "يهدف هذا البوت إلى مساعدتك في تعلم الكيمياء من خلال الاختبارات والمعلومات المفيدة.\n\n" +
            "**الميزات الحالية:**\n" +
            "- اختبارات عامة ومتخصصة (قيد التطوير).\n" +
            "- معلومات كيميائية (قيد التطوير).\n" +
            "- تقارير الأداء (قيد التطوير).\n\n" +
            "**تواصل مع المطور:**\n" +
            "إذا واجهت أي مشاكل أو لديك اقتراحات، يمكنك التواصل مع المطور [اسم المطور أو جهة الاتصال].\n\n" + # Placeholder
            "نتمنى لك تجربة تعليمية ممتعة! ✨")

    # Send the message without trying to edit, using safe_send_message
    safe_send_message(context.bot, chat_id, text=text, parse_mode=ParseMode.MARKDOWN)
    logger.info("[DIAG] Sent /about information.")

    # Since this is a direct command, we might not be in a conversation state,
    # or we might want to return to the main menu if we were.
    # If using ConversationHandler, decide the appropriate return state.
    # For simplicity, let's assume it doesn't change the state or returns to MAIN_MENU if needed.
    # If not using ConversationHandler for /about, no return state is needed.
    # return MAIN_MENU # Or return the current state if applicable

def unknown_command(update: Update, context: CallbackContext):
    """Handles unknown commands."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    logger.warning(f"[DIAG] Received unknown command 	{update.message.text}	 from user {user.id}.")
    safe_send_message(context.bot, chat_id, text="عذراً، لم أفهم هذا الأمر. الرجاء استخدام القائمة أو الأوامر المعروفة.")
    # Decide state: return current state or MAIN_MENU?
    # return MAIN_MENU

def unknown_message(update: Update, context: CallbackContext):
    """Handles messages that are not commands when expecting commands/buttons."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    logger.warning(f"[DIAG] Received unexpected text message from user {user.id}: 	{update.message.text}	")
    safe_send_message(context.bot, chat_id, text="عذراً، لم أفهم ما أرسلته. الرجاء استخدام الأزرار أو الأوامر.")
    # Decide state: return current state or MAIN_MENU?
    # return MAIN_MENU

# --- Callback Query Handler (Button Presses) ---

def button_handler(update: Update, context: CallbackContext):
    """Handles button presses from inline keyboards."""
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    message_id = query.message.message_id # Store message ID for potential editing
    data = query.data

    logger.info(f"[DIAG] Button pressed by user {user_id}. Callback data: 	{data}	")

    # --- Always answer the callback query first --- #
    try:
        query.answer()
        logger.info("[DIAG] Callback query answered.")
    except BadRequest as e:
        # This can happen if the query is too old, log and ignore
        logger.warning(f"[DIAG] Could not answer callback query (maybe too old?): {e}")
    except Exception as e:
        logger.error(f"[DIAG] Unexpected error answering callback query: {e}")

    # --- Handle different button actions --- #
    next_state = ConversationHandler.END # Default to ending conversation if state not handled

    # --- Menu Navigation --- #
    if data == \'main_menu\':
        logger.info("[DIAG] Handling \'main_menu\' callback.")
        text = "القائمة الرئيسية. ماذا تريد أن تفعل؟"
        reply_markup = create_main_menu_keyboard(user_id)
        try:
            query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            logger.info("[DIAG] Edited message to show main menu.")
        except BadRequest as e:
            if "Message is not modified" in str(e) or "message to edit not found" in str(e).lower():
                logger.info(f"[DIAG] Message not edited (main_menu - likely unchanged or not found): {e}")
            else: logger.error(f"[DIAG] Error editing message (main_menu): {e}")
        except Exception as e: logger.error(f"[DIAG] Unexpected error editing message (main_menu): {e}")
        next_state = MAIN_MENU

    elif data == \'menu_quiz\':
        logger.info("[DIAG] Handling \'menu_quiz\' callback.")
        text = "اختر نوع الاختبار الذي تريده:"
        reply_markup = create_quiz_menu_keyboard()
        try:
            query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            logger.info("[DIAG] Edited message to show quiz menu.")
        except BadRequest as e:
            if "Message is not modified" in str(e) or "message to edit not found" in str(e).lower():
                logger.info(f"[DIAG] Message not edited (menu_quiz - likely unchanged or not found): {e}")
            else: logger.error(f"[DIAG] Error editing message (menu_quiz): {e}")
        except Exception as e: logger.error(f"[DIAG] Unexpected error editing message (menu_quiz): {e}")
        next_state = QUIZ_MENU

    elif data == \'menu_admin\':
        logger.info("[DIAG] Handling \'menu_admin\' callback.")
        if is_admin(user_id):
            text = "⚙️ قائمة الإدارة:"
            reply_markup = create_admin_menu_keyboard()
            try:
                query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
                logger.info("[DIAG] Edited message to show admin menu.")
            except BadRequest as e:
                if "Message is not modified" in str(e) or "message to edit not found" in str(e).lower():
                    logger.info(f"[DIAG] Message not edited (menu_admin - likely unchanged or not found): {e}")
                else: logger.error(f"[DIAG] Error editing message (menu_admin): {e}")
            except Exception as e: logger.error(f"[DIAG] Unexpected error editing message (menu_admin): {e}")
            next_state = ADMIN_MENU
        else:
            logger.warning(f"[DIAG] Non-admin user {user_id} tried to access admin menu.")
            # Optionally send a message back
            # safe_send_message(context.bot, chat_id, text="ليس لديك صلاحية الوصول لهذه القائمة.")
            next_state = MAIN_MENU # Or keep current state?

    elif data == \'menu_info\':
        logger.info("[DIAG] Handling \'menu_info\' callback. (Not Implemented Yet)")
        text = "📚 المعلومات الكيميائية (قيد الإنشاء). الرجاء العودة لاحقاً."
        reply_markup = create_back_button(\'main_menu\')
        try:
            query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            logger.info("[DIAG] Edited message to show info placeholder.")
        except BadRequest as e:
            if "Message is not modified" in str(e) or "message to edit not found" in str(e).lower():
                logger.info(f"[DIAG] Message not edited (menu_info - likely unchanged or not found): {e}")
            else: logger.error(f"[DIAG] Error editing message (menu_info): {e}")
        except Exception as e: logger.error(f"[DIAG] Unexpected error editing message (menu_info): {e}")
        next_state = INFO_MENU # Or maybe back to MAIN_MENU?

    elif data == \'menu_reports\':
        logger.info("[DIAG] Handling \'menu_reports\' callback. (Not Implemented Yet)")
        text = "📊 تقارير الأداء (قيد الإنشاء). الرجاء العودة لاحقاً."
        reply_markup = create_back_button(\'main_menu\')
        try:
            query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            logger.info("[DIAG] Edited message to show reports placeholder.")
        except BadRequest as e:
            if "Message is not modified" in str(e) or "message to edit not found" in str(e).lower():
                logger.info(f"[DIAG] Message not edited (menu_reports - likely unchanged or not found): {e}")
            else: logger.error(f"[DIAG] Error editing message (menu_reports): {e}")
        except Exception as e: logger.error(f"[DIAG] Unexpected error editing message (menu_reports): {e}")
        next_state = SHOWING_REPORTS # Or maybe back to MAIN_MENU?

    elif data == \'menu_about\':
        logger.info("[DIAG] Handling \'menu_about\' callback.")
        text = ("🤖 **بوت الكيمياء التعليمي**\n\n" +
                "يهدف هذا البوت إلى مساعدتك في تعلم الكيمياء من خلال الاختبارات والمعلومات المفيدة.\n\n" +
                "**الميزات الحالية:**\n" +
                "- اختبارات عامة ومتخصصة (قيد التطوير).\n" +
                "- معلومات كيميائية (قيد التطوير).\n" +
                "- تقارير الأداء (قيد التطوير).\n\n" +
                "**تواصل مع المطور:**\n" +
                "إذا واجهت أي مشاكل أو لديك اقتراحات، يمكنك التواصل مع المطور [اسم المطور أو جهة الاتصال].\n\n" +
                "نتمنى لك تجربة تعليمية ممتعة! ✨")
        reply_markup = create_back_button(\'main_menu\')
        try:
            # Use Markdown for about text
            query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            logger.info("[DIAG] Edited message to show about info.")
        except BadRequest as e:
            if "Message is not modified" in str(e) or "message to edit not found" in str(e).lower():
                logger.info(f"[DIAG] Message not edited (menu_about - likely unchanged or not found): {e}")
            else: logger.error(f"[DIAG] Error editing message (menu_about): {e}")
        except Exception as e: logger.error(f"[DIAG] Unexpected error editing message (menu_about): {e}")
        next_state = MAIN_MENU # Go back to main menu state after showing about

    # --- Quiz Selection --- #
    elif data == \'quiz_random_prompt\':
        logger.info("[DIAG] Handling \'quiz_random_prompt\' callback.")
        # Ask for number of questions or duration?
        # For now, just start a default random quiz
        # TODO: Add steps to ask for number/duration if needed
        num_questions = DEFAULT_QUIZ_QUESTIONS
        duration = DEFAULT_QUIZ_DURATION_MINUTES
        logger.info(f"[DIAG] Starting default random quiz: {num_questions} questions, {duration} minutes.")
        start_quiz(update, context, quiz_type=\'random\', num_questions=num_questions, duration=duration)
        # start_quiz should handle state transition or message sending
        next_state = TAKING_QUIZ # Assuming start_quiz leads to this state

    # --- Quiz Actions (Answer/Skip/End) --- #
    elif data.startswith(\'quiz_\'):
        # Format: quiz_{quiz_id}_{question_index}_{selected_option_index}
        logger.info(f"[DIAG] Handling quiz answer callback: {data}")
        try:
            _, quiz_id_str, q_index_str, selected_option_str = data.split(\'_\')
            quiz_id = int(quiz_id_str)
            question_index = int(q_index_str)
            selected_option_index = int(selected_option_str)
            handle_quiz_answer(chat_id, user_id, quiz_id, question_index, selected_option_index, context)
            next_state = TAKING_QUIZ
        except ValueError as e:
            logger.error(f"[DIAG] Invalid quiz answer callback format: {data}. Error: {e}")
            next_state = MAIN_MENU # Go back to main menu on error
        except Exception as e:
            logger.error(f"[DIAG] Unexpected error handling quiz answer: {e}")
            next_state = MAIN_MENU

    elif data.startswith(\'skip_\'):
        # Format: skip_{quiz_id}_{question_index}
        logger.info(f"[DIAG] Handling quiz skip callback: {data}")
        try:
            _, quiz_id_str, q_index_str = data.split(\'_\')
            quiz_id = int(quiz_id_str)
            question_index = int(q_index_str)
            handle_quiz_skip(chat_id, user_id, quiz_id, question_index, context)
            next_state = TAKING_QUIZ
        except ValueError as e:
            logger.error(f"[DIAG] Invalid quiz skip callback format: {data}. Error: {e}")
            next_state = MAIN_MENU
        except Exception as e:
            logger.error(f"[DIAG] Unexpected error handling quiz skip: {e}")
            next_state = MAIN_MENU

    elif data.startswith(\'end_\'):
        # Format: end_{quiz_id}
        logger.info(f"[DIAG] Handling quiz end callback: {data}")
        try:
            _, quiz_id_str = data.split(\'_\')
            quiz_id = int(quiz_id_str)
            handle_quiz_end(chat_id, user_id, quiz_id, context)
            # show_results is called within handle_quiz_end
            next_state = SHOWING_RESULTS # Or MAIN_MENU after results?
        except ValueError as e:
            logger.error(f"[DIAG] Invalid quiz end callback format: {data}. Error: {e}")
            next_state = MAIN_MENU
        except Exception as e:
            logger.error(f"[DIAG] Unexpected error handling quiz end: {e}")
            next_state = MAIN_MENU

    # --- Placeholder for other actions --- #
    else:
        logger.warning(f"[DIAG] Unhandled callback data: {data}")
        try:
            # Try to inform the user, but don't edit if it fails
            query.edit_message_text(text="عذراً، هذا الزر غير مفعّل حالياً.", reply_markup=create_back_button(\'main_menu\'))
        except BadRequest as e:
             if "Message is not modified" in str(e) or "message to edit not found" in str(e).lower():
                 logger.info(f"[DIAG] Message not edited (unhandled callback - likely unchanged or not found): {e}")
             else: logger.error(f"[DIAG] Error editing message (unhandled callback): {e}")
        except Exception as e: logger.error(f"[DIAG] Unexpected error editing message (unhandled callback): {e}")
        next_state = MAIN_MENU

    logger.info(f"[DIAG] Returning state: {next_state}")
    return next_state

# --- Quiz Logic Functions ---

def start_quiz(update: Update, context: CallbackContext, quiz_type: str, num_questions: int = DEFAULT_QUIZ_QUESTIONS, duration: int = DEFAULT_QUIZ_DURATION_MINUTES, **filters):
    """Starts a new quiz based on type and filters."""
    query = update.callback_query # Assuming start_quiz is called from button_handler
    user = query.from_user if query else update.effective_user
    chat_id = query.message.chat_id if query else update.effective_chat.id
    user_id = user.id

    logger.info(f"[DIAG] Attempting to start quiz for user {user_id}. Type: {quiz_type}, Num: {num_questions}, Duration: {duration}, Filters: {filters}")

    # --- Fetch questions from API based on quiz_type --- #
    endpoint = "/questions/random/"
    params = {"count": num_questions}

    if quiz_type == \'random\':
        endpoint = "/questions/random/"
        params = {"count": num_questions}
    elif quiz_type == \'lesson\':
        lesson_id = filters.get(\'lesson_id\')
        if not lesson_id:
            logger.error("[DIAG] Lesson ID missing for lesson quiz.")
            safe_send_message(context.bot, chat_id, text="خطأ: لم يتم تحديد الدرس لبدء الاختبار.")
            return MAIN_MENU
        endpoint = f"/questions/lesson/{lesson_id}/"
        params = {"count": num_questions} # API might ignore count for specific filters
    # Add more elif blocks for unit, course etc. if API supports them
    # elif quiz_type == \'unit\': endpoint = f"/questions/unit/{filters.get(\'unit_id\')}/" ...
    else:
        logger.error(f"[DIAG] Unsupported quiz type: {quiz_type}")
        safe_send_message(context.bot, chat_id, text=f"عذراً، نوع الاختبار 	{quiz_type}	 غير مدعوم حالياً.")
        return MAIN_MENU

    api_questions = fetch_questions_from_api(endpoint, params)

    if api_questions is None:
        logger.error("[DIAG] Failed to fetch questions from API.")
        safe_send_message(context.bot, chat_id, text="عذراً، حدث خطأ أثناء جلب الأسئلة. يرجى المحاولة مرة أخرى لاحقاً.")
        return MAIN_MENU
    if not api_questions: # Empty list returned
        logger.warning("[DIAG] API returned no questions for the specified criteria.")
        safe_send_message(context.bot, chat_id, text="عذراً، لا توجد أسئلة متاحة لهذا الاختبار حالياً.")
        return MAIN_MENU

    # --- Transform API questions to bot format --- #
    questions = []
    for q in api_questions:
        transformed = transform_api_question(q)
        if transformed:
            questions.append(transformed)

    if not questions:
        logger.error("[DIAG] No valid questions found after transformation.")
        safe_send_message(context.bot, chat_id, text="عذراً، حدث خطأ في معالجة الأسئلة. يرجى المحاولة مرة أخرى لاحقاً.")
        return MAIN_MENU

    # Limit number of questions if API returned more than requested (shouldn't happen with count param?)
    questions = questions[:num_questions]
    actual_num_questions = len(questions)
    logger.info(f"[DIAG] Successfully fetched and transformed {actual_num_questions} questions.")

    # --- Initialize quiz state in user_data --- #
    quiz_id = int(time.time() * 1000) # Simple unique ID based on timestamp
    user_data = context.user_data
    user_data["current_quiz"] = {
        "quiz_id": quiz_id,
        "questions": questions,
        "answers": [None] * actual_num_questions, # Store user's selected option index (0-3) or -1 for skipped
        "score": 0,
        "current_question_index": 0,
        "start_time": datetime.now(),
        "duration_minutes": duration,
        "timed_out": False,
        "quiz_timer_job_name": None,
        "question_timer_job_name": None,
        "last_question_message_id": None
    }
    logger.info(f"[DIAG] Initialized quiz {quiz_id} state for user {user_id}.")

    # --- Set quiz timer --- #
    quiz_timer_job = set_quiz_timer(context, chat_id, user_id, quiz_id, duration)
    if quiz_timer_job:
        user_data["current_quiz"]["quiz_timer_job_name"] = quiz_timer_job

    # --- Send the first question --- #
    logger.info(f"[DIAG] Sending first question (index 0) for quiz {quiz_id}.")
    send_question(context, chat_id, user_id, quiz_id, 0)

    return TAKING_QUIZ

def send_question(context: CallbackContext, chat_id: int, user_id: int, quiz_id: int, question_index: int):
    """Sends the specified question to the user."""
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.error(f"[DIAG] Quiz data mismatch or missing for quiz {quiz_id}, user {user_id}.")
        safe_send_message(context.bot, chat_id, text="حدث خطأ في متابعة الاختبار. يرجى البدء من جديد.")
        return MAIN_MENU

    questions = quiz_data["questions"]
    if question_index < 0 or question_index >= len(questions):
        logger.error(f"[DIAG] Invalid question index {question_index} for quiz {quiz_id}.")
        safe_send_message(context.bot, chat_id, text="حدث خطأ في الانتقال للسؤال التالي.")
        # End quiz if index is out of bounds?
        handle_quiz_end(chat_id, user_id, quiz_id, context)
        return SHOWING_RESULTS

    question = questions[question_index]
    quiz_data["current_question_index"] = question_index

    # --- Prepare question text and media --- #
    question_text = question.get("question_text", "")
    image_url = question.get("image_url")
    num_questions = len(questions)

    header = f"❓ **السؤال {question_index + 1} من {num_questions}**\n\n"
    full_text = header + process_text_with_chemical_notation(question_text)

    # --- Prepare options and keyboard --- #
    reply_markup = create_quiz_options_keyboard(question, quiz_id, question_index)

    # --- Send message (with or without image) --- #
    sent_message = None
    logger.info(f"[DIAG] Preparing to send question {question_index} (ID: {question.get(\'question_id\')}) for quiz {quiz_id}.")
    try:
        if image_url:
            logger.info(f"[DIAG] Sending question {question_index} with image: {image_url}")
            # Check if any options also have images
            option_images = [
                question.get("option1_image"),
                question.get("option2_image"),
                question.get("option3_image"),
                question.get("option4_image")
            ]
            if any(option_images):
                 logger.warning("[DIAG] Question has image AND options have images. Telegram doesn't support this well in one message. Sending question image only.")
                 # Prioritize question image if both exist

            # Send photo with caption and keyboard
            sent_message = context.bot.send_photo(
                chat_id=chat_id,
                photo=image_url,
                caption=full_text,
                parse_mode=ParseMode.MARKDOWN, # Caption uses Markdown
                reply_markup=reply_markup
            )
        else:
            # Check if options have images when question doesn't
            option_images = [
                question.get("option1_image"),
                question.get("option2_image"),
                question.get("option3_image"),
                question.get("option4_image")
            ]
            if any(option_images):
                logger.info(f"[DIAG] Sending question {question_index} text with option images.")
                # Send text message first
                sent_text_message = safe_send_message(context.bot, chat_id, text=full_text, parse_mode=ParseMode.MARKDOWN)
                # Then send media group for option images (if multiple)
                media_group = []
                valid_option_images = [img for img in option_images if img]
                if len(valid_option_images) > 1:
                    for i, img_url in enumerate(option_images):
                        if img_url:
                            # Try to add option letter (A, B, C, D) to caption
                            option_letter = chr(ord(\'A\') + i)
                            media_group.append(InputMediaPhoto(media=img_url, caption=f"الخيار {option_letter}"))
                    if media_group:
                        context.bot.send_media_group(chat_id=chat_id, media=media_group)
                        # Send the keyboard separately after the media group
                        safe_send_message(context.bot, chat_id, text="اختر الإجابة الصحيحة:", reply_markup=reply_markup)
                        sent_message = sent_text_message # Track the text message for potential future edits?
                elif len(valid_option_images) == 1:
                    # Send single photo with keyboard
                    img_url = valid_option_images[0]
                    img_index = option_images.index(img_url)
                    option_letter = chr(ord(\'A\') + img_index)
                    # Send the text first, then the single image with keyboard
                    safe_send_message(context.bot, chat_id, text=full_text, parse_mode=ParseMode.MARKDOWN)
                    sent_message = context.bot.send_photo(chat_id=chat_id, photo=img_url, caption=f"صورة الخيار {option_letter}", reply_markup=reply_markup)
                else: # Should not happen if any(option_images) is true
                     sent_message = safe_send_message(context.bot, chat_id, text=full_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            else:
                # Send simple text message with keyboard
                logger.info(f"[DIAG] Sending question {question_index} as text only.")
                sent_message = safe_send_message(context.bot, chat_id, text=full_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

        if sent_message:
            quiz_data["last_question_message_id"] = sent_message.message_id
            logger.info(f"[DIAG] Sent question {question_index}. Message ID: {sent_message.message_id}")
        else:
             logger.error(f"[DIAG] Failed to send question {question_index}.")
             # How to handle failure? Maybe try ending quiz?
             handle_quiz_end(chat_id, user_id, quiz_id, context)
             return SHOWING_RESULTS

    except BadRequest as e:
        logger.error(f"[DIAG] Telegram BadRequest sending question {question_index}: {e}")
        safe_send_message(context.bot, chat_id, text="حدث خطأ أثناء إرسال السؤال. قد يكون تنسيق السؤال غير صحيح.")
        # Attempt to skip to next question or end quiz?
        handle_quiz_skip(chat_id, user_id, quiz_id, question_index, context, error_skip=True)
        return TAKING_QUIZ
    except Exception as e:
        logger.error(f"[DIAG] Unexpected error sending question {question_index}: {e}")
        safe_send_message(context.bot, chat_id, text="حدث خطأ غير متوقع أثناء عرض السؤال.")
        handle_quiz_end(chat_id, user_id, quiz_id, context)
        return SHOWING_RESULTS

    # --- Set question timer --- #
    q_timer_job = set_question_timer(context, chat_id, user_id, quiz_id, question_index)
    if q_timer_job:
        quiz_data["question_timer_job_name"] = q_timer_job

    return TAKING_QUIZ

def handle_quiz_answer(chat_id: int, user_id: int, quiz_id: int, question_index: int, selected_option_index: int, context: CallbackContext):
    """Handles user's answer to a quiz question."""
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    logger.info(f"[DIAG] Handling answer for quiz {quiz_id}, q_index {question_index}, selected {selected_option_index} by user {user_id}.")

    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.warning(f"[DIAG] Received answer for inactive/mismatched quiz {quiz_id}.")
        # Maybe the quiz ended? Inform the user.
        safe_send_message(context.bot, chat_id, text="لقد انتهى هذا الاختبار بالفعل أو تم إلغاؤه.")
        return MAIN_MENU

    if question_index != quiz_data["current_question_index"]:
        logger.warning(f"[DIAG] Received answer for wrong question index (expected {quiz_data['current_question_index']}, got {question_index}). Ignoring.")
        # Inform user they might be answering an old question?
        safe_send_message(context.bot, chat_id, text="لقد تم الانتقال للسؤال التالي بالفعل.")
        return TAKING_QUIZ

    # --- Stop question timer --- #
    if quiz_data.get("question_timer_job_name"):
        remove_job_if_exists(quiz_data["question_timer_job_name"], context)
        quiz_data["question_timer_job_name"] = None

    # --- Record answer and check correctness --- #
    questions = quiz_data["questions"]
    question = questions[question_index]
    correct_answer_index = question["correct_answer"]
    is_correct = (selected_option_index == correct_answer_index)

    quiz_data["answers"][question_index] = selected_option_index # Record the choice
    if is_correct:
        quiz_data["score"] += 1
        feedback_text = "✅ إجابة صحيحة!"
        logger.info(f"[DIAG] User {user_id} answered question {question_index} correctly.")
    else:
        feedback_text = "❌ إجابة خاطئة."
        logger.info(f"[DIAG] User {user_id} answered question {question_index} incorrectly.")

    # --- Provide feedback (optional explanation) --- #
    explanation = question.get("explanation")
    if explanation:
        feedback_text += f"\n\n**التفسير:**\n{explanation}"
    elif not is_correct:
        # Show correct answer if explanation is missing and answer was wrong
        correct_option_text = question.get(f"option{correct_answer_index+1}") # option1, option2 etc.
        if correct_option_text:
             feedback_text += f"\nالإجابة الصحيحة كانت: {correct_option_text}"

    # --- Edit the question message to show feedback (remove keyboard) --- #
    last_msg_id = quiz_data.get("last_question_message_id")
    if last_msg_id:
        try:
            # Prepare original question text again
            question_text_orig = question.get("question_text", "")
            header_orig = f"❓ **السؤال {question_index + 1} من {len(questions)}**\n\n"
            full_text_orig = header_orig + process_text_with_chemical_notation(question_text_orig)

            # Append feedback to the original question text
            text_with_feedback = f"{full_text_orig}\n\n---\n{feedback_text}"

            # Try editing the message
            context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=last_msg_id,
                text=text_with_feedback,
                reply_markup=None, # Remove keyboard
                parse_mode=ParseMode.MARKDOWN # Assuming feedback might use Markdown
            )
            logger.info(f"[DIAG] Edited question message {last_msg_id} with feedback.")
        except BadRequest as e:
            if "Message is not modified" in str(e) or "message to edit not found" in str(e).lower():
                logger.info(f"[DIAG] Message {last_msg_id} not edited for feedback (unchanged/not found): {e}")
                # Send feedback as a new message if editing fails
                safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)
            else:
                logger.error(f"[DIAG] Error editing message {last_msg_id} for feedback: {e}")
                safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"[DIAG] Unexpected error editing message {last_msg_id} for feedback: {e}")
            safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)
    else:
        # If we couldn't track the last message ID, just send feedback as new message
        logger.warning("[DIAG] Could not find last question message ID to edit for feedback.")
        safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)

    # --- Move to next question or end quiz --- #
    next_question_index = question_index + 1
    if next_question_index < len(questions):
        # Schedule sending the next question after a delay
        context.job_queue.run_once(
            lambda ctx: send_question(ctx, chat_id, user_id, quiz_id, next_question_index),
            FEEDBACK_DELAY,
            context=context # Pass the main context
        )
        logger.info(f"[DIAG] Scheduled next question ({next_question_index}) after {FEEDBACK_DELAY}s delay.")
    else:
        # End of quiz
        logger.info(f"[DIAG] Reached end of quiz {quiz_id} after question {question_index}.")
        # Schedule showing results after a delay
        context.job_queue.run_once(
            lambda ctx: show_results(chat_id, user_id, quiz_id, ctx),
            FEEDBACK_DELAY,
            context=context
        )
        logger.info(f"[DIAG] Scheduled showing results after {FEEDBACK_DELAY}s delay.")
        return SHOWING_RESULTS # Transition state

    return TAKING_QUIZ

def handle_quiz_skip(chat_id: int, user_id: int, quiz_id: int, question_index: int, context: CallbackContext, timed_out: bool = False, error_skip: bool = False):
    """Handles skipping a quiz question."""
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    logger.info(f"[DIAG] Handling skip for quiz {quiz_id}, q_index {question_index} by user {user_id}. Timed out: {timed_out}, Error skip: {error_skip}")

    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.warning(f"[DIAG] Received skip for inactive/mismatched quiz {quiz_id}.")
        if not timed_out and not error_skip: # Avoid sending message if it was a timer/error callback
            safe_send_message(context.bot, chat_id, text="لقد انتهى هذا الاختبار بالفعل أو تم إلغاؤه.")
        return MAIN_MENU

    if question_index != quiz_data["current_question_index"]:
        logger.warning(f"[DIAG] Received skip for wrong question index (expected {quiz_data['current_question_index']}, got {question_index}). Ignoring.")
        if not timed_out and not error_skip:
            safe_send_message(context.bot, chat_id, text="لقد تم الانتقال للسؤال التالي بالفعل.")
        return TAKING_QUIZ

    # --- Stop question timer if manually skipped --- #
    if not timed_out and quiz_data.get("question_timer_job_name"):
        remove_job_if_exists(quiz_data["question_timer_job_name"], context)
        quiz_data["question_timer_job_name"] = None

    # --- Record skip --- #
    quiz_data["answers"][question_index] = -1 # Use -1 to indicate skipped

    # --- Provide feedback (remove keyboard) --- #
    feedback_text = "⏭️ تم تخطي السؤال."
    last_msg_id = quiz_data.get("last_question_message_id")

    if not timed_out and not error_skip and last_msg_id:
        try:
            # Prepare original question text again
            questions = quiz_data["questions"]
            question = questions[question_index]
            question_text_orig = question.get("question_text", "")
            header_orig = f"❓ **السؤال {question_index + 1} من {len(questions)}**\n\n"
            full_text_orig = header_orig + process_text_with_chemical_notation(question_text_orig)
            text_with_feedback = f"{full_text_orig}\n\n---\n{feedback_text}"

            context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=last_msg_id,
                text=text_with_feedback,
                reply_markup=None, # Remove keyboard
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"[DIAG] Edited question message {last_msg_id} with skip feedback.")
        except BadRequest as e:
            if "Message is not modified" in str(e) or "message to edit not found" in str(e).lower():
                logger.info(f"[DIAG] Message {last_msg_id} not edited for skip (unchanged/not found): {e}")
                if not timed_out and not error_skip: # Avoid sending if timer/error related
                     safe_send_message(context.bot, chat_id, text=feedback_text)
            else:
                logger.error(f"[DIAG] Error editing message {last_msg_id} for skip: {e}")
                if not timed_out and not error_skip:
                     safe_send_message(context.bot, chat_id, text=feedback_text)
        except Exception as e:
            logger.error(f"[DIAG] Unexpected error editing message {last_msg_id} for skip: {e}")
            if not timed_out and not error_skip:
                 safe_send_message(context.bot, chat_id, text=feedback_text)
    elif not timed_out and not error_skip:
        logger.warning("[DIAG] Could not find last question message ID to edit for skip feedback.")
        safe_send_message(context.bot, chat_id, text=feedback_text)
    # If timed_out or error_skip, feedback was likely sent by the timer/error handler already

    # --- Move to next question or end quiz --- #
    next_question_index = question_index + 1
    questions = quiz_data["questions"]
    if next_question_index < len(questions):
        # Send next question immediately (or with minimal delay?)
        delay = 0.1 if (timed_out or error_skip) else FEEDBACK_DELAY
        context.job_queue.run_once(
            lambda ctx: send_question(ctx, chat_id, user_id, quiz_id, next_question_index),
            delay,
            context=context
        )
        logger.info(f"[DIAG] Scheduled next question ({next_question_index}) after skip/timeout/error with {delay}s delay.")
    else:
        # End of quiz
        logger.info(f"[DIAG] Reached end of quiz {quiz_id} after skipping question {question_index}.")
        delay = 0.1 if (timed_out or error_skip) else FEEDBACK_DELAY
        context.job_queue.run_once(
            lambda ctx: show_results(chat_id, user_id, quiz_id, ctx),
            delay,
            context=context
        )
        logger.info(f"[DIAG] Scheduled showing results after skip/timeout/error with {delay}s delay.")
        return SHOWING_RESULTS

    return TAKING_QUIZ

def handle_quiz_end(chat_id: int, user_id: int, quiz_id: int, context: CallbackContext):
    """Handles user explicitly ending the quiz."""
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    logger.info(f"[DIAG] Handling explicit end for quiz {quiz_id} by user {user_id}.")

    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.warning(f"[DIAG] Received end for inactive/mismatched quiz {quiz_id}.")
        safe_send_message(context.bot, chat_id, text="لقد انتهى هذا الاختبار بالفعل أو تم إلغاؤه.")
        return MAIN_MENU

    # --- Stop timers --- #
    if quiz_data.get("quiz_timer_job_name"):
        remove_job_if_exists(quiz_data["quiz_timer_job_name"], context)
        quiz_data["quiz_timer_job_name"] = None
    if quiz_data.get("question_timer_job_name"):
        remove_job_if_exists(quiz_data["question_timer_job_name"], context)
        quiz_data["question_timer_job_name"] = None

    # --- Mark as ended (optional) and show results --- #
    quiz_data["ended_manually"] = True # Add a flag if needed
    safe_send_message(context.bot, chat_id, text="تم إنهاء الاختبار بناءً على طلبك.")
    show_results(chat_id, user_id, quiz_id, context)

    return SHOWING_RESULTS

def show_results(chat_id: int, user_id: int, quiz_id: int, context: CallbackContext, timed_out: bool = False):
    """Calculates and displays the quiz results."""
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    logger.info(f"[DIAG] Showing results for quiz {quiz_id}, user {user_id}. Timed out: {timed_out}")

    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.error(f"[DIAG] Cannot show results, quiz data mismatch or missing for quiz {quiz_id}.")
        safe_send_message(context.bot, chat_id, text="حدث خطأ أثناء عرض النتائج.")
        # Clean up potentially stale quiz data?
        if "current_quiz" in user_data: del user_data["current_quiz"]
        return MAIN_MENU

    score = quiz_data["score"]
    answers = quiz_data["answers"]
    num_questions = len(quiz_data["questions"])
    answered_count = sum(1 for ans in answers if ans is not None)
    skipped_count = sum(1 for ans in answers if ans == -1)
    correct_count = score
    incorrect_count = answered_count - correct_count - skipped_count
    unanswered_count = num_questions - answered_count

    # Calculate percentage
    percentage = (correct_count / num_questions * 100) if num_questions > 0 else 0

    # --- Format results message --- #
    results_text = f"📊 **نتائج الاختبار (Quiz ID: {quiz_id})**\n\n"
    results_text += f"- إجمالي الأسئلة: {num_questions}\n"
    results_text += f"- الإجابات الصحيحة: {correct_count} ✅\n"
    results_text += f"- الإجابات الخاطئة: {incorrect_count} ❌\n"
    results_text += f"- الأسئلة المتخطاة: {skipped_count} ⏭️\n"
    if timed_out:
        results_text += f"- الأسئلة غير المجابة (بسبب الوقت): {unanswered_count} ⏳\n"
    elif unanswered_count > 0:
         results_text += f"- الأسئلة غير المجابة: {unanswered_count} ❔\n"

    results_text += f"\n**النتيجة النهائية: {percentage:.1f}%**\n\n"

    # Add performance message
    if percentage >= 85:
        results_text += "🎉 أداء ممتاز! استمر في العمل الرائع!"
    elif percentage >= 70:
        results_text += "👍 جيد جداً! يمكنك تحقيق الأفضل."
    elif percentage >= 50:
        results_text += "🙂 لا بأس، تحتاج إلى مراجعة بعض المفاهيم."
    else:
        results_text += "😔 تحتاج إلى المزيد من المذاكرة والممارسة. لا تيأس!"

    # --- Save results to DB (if available) --- #
    if QUIZ_DB:
        try:
            QUIZ_DB.save_quiz_result(
                user_id=user_id,
                quiz_id=quiz_id,
                score=correct_count,
                total_questions=num_questions,
                percentage=percentage,
                start_time=quiz_data["start_time"],
                end_time=datetime.now(),
                duration_minutes=quiz_data["duration_minutes"],
                timed_out=timed_out or quiz_data.get("timed_out", False)
            )
            logger.info(f"[DIAG] Saved quiz {quiz_id} results for user {user_id} to DB.")
        except Exception as e:
            logger.error(f"[DIAG] Failed to save quiz {quiz_id} results for user {user_id} to DB: {e}")
            results_text += "\n\n⚠️ تعذر حفظ نتيجتك في قاعدة البيانات."
    else:
        logger.warning("[DIAG] Database not available, skipping saving quiz results.")
        results_text += "\n\n⚠️ لم يتم حفظ النتيجة (قاعدة البيانات غير متاحة)."

    # --- Send results and clean up --- #
    safe_send_message(context.bot, chat_id, text=results_text, reply_markup=create_back_button(\'main_menu\'), parse_mode=ParseMode.MARKDOWN)
    logger.info(f"[DIAG] Sent results for quiz {quiz_id} to user {user_id}.")

    # Clean up quiz data from user_data
    if "current_quiz" in user_data:
        del user_data["current_quiz"]
        logger.info(f"[DIAG] Cleaned up quiz data for user {user_id}.")

    return MAIN_MENU # Return to main menu after showing results

# --- Admin Functions (Placeholders/Needs Rework) ---
# These functions likely need complete rework if question management is external

def admin_stats(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    if not is_admin(user_id):
        logger.warning(f"Non-admin {user_id} tried admin_stats.")
        query.answer("غير مصرح لك.")
        return ADMIN_MENU

    logger.info(f"[DIAG] Admin {user_id} requested stats.")
    text = "📊 إحصائيات البوت (قيد الإنشاء)..."
    # Fetch stats from DB if QUIZ_DB exists
    if QUIZ_DB:
        try:
            total_users = QUIZ_DB.get_total_users()
            total_quizzes = QUIZ_DB.get_total_quizzes_taken()
            avg_score = QUIZ_DB.get_average_score()
            text = f"📊 **إحصائيات البوت:**\n\n"
            text += f"- إجمالي المستخدمين المسجلين: {total_users}\n"
            text += f"- إجمالي الاختبارات التي تم إجراؤها: {total_quizzes}\n"
            text += f"- متوسط ​​النتيجة: {avg_score:.1f}%" if avg_score is not None else "- متوسط ​​النتيجة: لا توجد بيانات"
        except Exception as e:
            logger.error(f"[DIAG] Error fetching stats from DB: {e}")
            text = "حدث خطأ أثناء جلب الإحصائيات من قاعدة البيانات."
    else:
        text = "قاعدة البيانات غير متاحة لعرض الإحصائيات."

    reply_markup = create_back_button(\'menu_admin\')
    try:
        query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    except BadRequest as e:
        if "Message is not modified" in str(e) or "message to edit not found" in str(e).lower(): logger.info(f"[DIAG] Stats message not edited: {e}")
        else: logger.error(f"[DIAG] Error editing stats message: {e}")
    except Exception as e: logger.error(f"[DIAG] Unexpected error editing stats message: {e}")

    return ADMIN_MENU

def admin_broadcast(update: Update, context: CallbackContext):
    # Implementation needed: Ask admin for message, then iterate through users in DB and send
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    if not is_admin(user_id):
        logger.warning(f"Non-admin {user_id} tried admin_broadcast.")
        query.answer("غير مصرح لك.")
        return ADMIN_MENU

    logger.info(f"[DIAG] Admin {user_id} initiated broadcast.")
    text = "📢 ميزة إرسال رسالة للجميع (قيد الإنشاء)."
    reply_markup = create_back_button(\'menu_admin\')
    try:
        query.edit_message_text(text=text, reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" in str(e) or "message to edit not found" in str(e).lower(): logger.info(f"[DIAG] Broadcast message not edited: {e}")
        else: logger.error(f"[DIAG] Error editing broadcast message: {e}")
    except Exception as e: logger.error(f"[DIAG] Unexpected error editing broadcast message: {e}")

    # Need to add states to handle getting the message from admin
    return ADMIN_MENU

# --- Error Handler ---

def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # Attempt to notify the user about the error, if possible
    if isinstance(update, Update) and update.effective_chat:
        try:
            safe_send_message(context.bot, update.effective_chat.id, text="حدث خطأ ما أثناء معالجة طلبك. يرجى المحاولة مرة أخرى أو التواصل مع الدعم.")
        except Exception as e:
            logger.error(f"Failed to send error notification to user: {e}")

# --- Main Function --- #

def main() -> None:
    """Start the bot."""
    logger.info("Starting bot...")

    # Create the Updater and pass it your bot's token.
    updater = Updater(BOT_TOKEN)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # --- Conversation Handler Setup --- #
    # Define states and entry points
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler(\'start\', start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(button_handler, pattern=\'^(main_menu|menu_quiz|menu_admin|menu_info|menu_reports|menu_about)$\')
            ],
            QUIZ_MENU: [
                CallbackQueryHandler(button_handler, pattern=\'^(quiz_random_prompt|quiz_by_course_prompt|quiz_by_unit_prompt|quiz_by_lesson_prompt|main_menu)$\')
                # Add handlers for selecting course/unit/lesson if needed
            ],
            ADMIN_MENU: [
                CallbackQueryHandler(button_handler, pattern=\'^(admin_stats|admin_broadcast|main_menu)$\')
                # Add handlers for other admin actions
            ],
            TAKING_QUIZ: [
                CallbackQueryHandler(button_handler, pattern=\'^(quiz_|skip_|end_)\') # Handles answers, skips, ends
            ],
            SHOWING_RESULTS: [
                CallbackQueryHandler(button_handler, pattern=\'^main_menu$\') # Back to main menu from results
            ],
            INFO_MENU: [ # Placeholder state
                CallbackQueryHandler(button_handler, pattern=\'^main_menu$\')
            ],
             SHOWING_REPORTS: [ # Placeholder state
                CallbackQueryHandler(button_handler, pattern=\'^main_menu$\')
            ],
            # Add other states (SELECTING_CHAPTER, SELECTING_LESSON, etc.) if/when implemented
        },
        fallbacks=[
            CommandHandler(\'start\', start), # Allow restarting
            CommandHandler(\'about\', about),
            CallbackQueryHandler(button_handler), # Catch stray button presses?
            MessageHandler(Filters.command, unknown_command),
            MessageHandler(Filters.text & ~Filters.command, unknown_message)
        ],
        # per_user=True, per_chat=False # Default
    )

    dp.add_handler(conv_handler)

    # Add a generic error handler
    dp.add_error_handler(error_handler)

    # --- Start the Bot --- #
    # Use webhook for Render deployment
    # updater.start_webhook(listen="0.0.0.0",
    #                       port=PORT,
    #                       url_path=BOT_TOKEN,
    #                       webhook_url=f"https://{APP_NAME}.onrender.com/{BOT_TOKEN}")
    # logger.info(f"Bot started with webhook on port {PORT} for app {APP_NAME}")

    # OR use polling (simpler for Background Worker, but less efficient)
    logger.info("Starting bot with polling...")
    updater.start_polling()
    logger.info("Bot started successfully with polling.")

    # Run the bot until you press Ctrl-C
    updater.idle()

if __name__ == \'__main__\':
    main()

