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
    CallbackContext,
    CallbackQueryHandler,
    ConversationHandler,
    JobQueue
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

# Get sensitive info from environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_USER_ID = 6448526509
PORT = int(os.environ.get("PORT", 8443))
APP_NAME = os.environ.get("APP_NAME") # Use APP_NAME for Render

if not BOT_TOKEN:
    logger.critical("BOT_TOKEN environment variable not set!")
    sys.exit("Bot token not found.")

# Quiz settings
DEFAULT_QUIZ_QUESTIONS = 10 # Default number of questions for random quizzes
DEFAULT_QUIZ_DURATION_MINUTES = 10
QUESTION_TIMER_SECONDS = 240 # Timer per question (optional)
FEEDBACK_DELAY = 1.5 # Shorter delay
ENABLE_QUESTION_TIMER = False # Set to True to enable per-question timer

# --- Database Setup ---
try:
    from db_utils import connect_db, setup_database
    from quiz_db import QuizDatabase
    from helper_function import safe_edit_message_text, safe_send_message
except ImportError as e:
    logger.error(f"Failed to import database modules: {e}. Make sure db_utils.py, quiz_db.py, helper_function.py are present.")
    sys.exit("Critical import error, stopping bot.")

# استيراد البيانات الثابتة ووظائف المعادلات
try:
    from chemistry_data import ELEMENTS, COMPOUNDS, CONCEPTS, PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO
    from chemical_equations import process_text_with_chemical_notation, format_chemical_equation
except ImportError as e:
    logger.warning(f"Could not import chemistry_data.py or chemical_equations.py: {e}. Some features might be limited.")
    ELEMENTS, COMPOUNDS, CONCEPTS, PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO = {}, {}, {}, {}, {}, {}
    def process_text_with_chemical_notation(text): return text
    def format_chemical_equation(text): return text

# Initialize database connection and QuizDatabase instance
if not DATABASE_URL:
    logger.error("DATABASE_URL environment variable not set or empty. Bot cannot connect to DB.")
    sys.exit("Database configuration error.")

DB_CONN = connect_db(DATABASE_URL)
if DB_CONN:
    setup_database(DB_CONN) # Ensure tables exist
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
    INFO_MENU,
    SELECT_CHAPTER_FOR_LESSON_QUIZ,
    SHOWING_RESULTS # New state for showing quiz results
) = range(34) # Increased range for new states

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

# --- Timer Functions ---

def remove_job_if_exists(name: str, context: CallbackContext) -> bool:
    """Removes a job with the given name if it exists."""
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
        logger.info(f"Removed timer job: {name}")
    return True

def set_quiz_timer(context: CallbackContext, chat_id: int, user_id: int, quiz_id: int, duration_minutes: int):
    """Sets the overall timer for the quiz."""
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
    """Sets the timer for the current question if enabled."""
    if ENABLE_QUESTION_TIMER and QUESTION_TIMER_SECONDS > 0:
        job_name = f"question_timer_{chat_id}_{user_id}_{quiz_id}" # Only one question timer per quiz at a time
        remove_job_if_exists(job_name, context)
        context.job_queue.run_once(
            question_timer_callback,
            QUESTION_TIMER_SECONDS,
            context={\"chat_id\": chat_id, \"user_id\": user_id, \"quiz_id\": quiz_id, \"question_index\": question_index},
            name=job_name
        )
        logger.info(f"Set question timer for {QUESTION_TIMER_SECONDS} seconds. Job: {job_name}")
        return job_name
    return None

def end_quiz_timeout(context: CallbackContext):
    """Callback function when the overall quiz timer expires."""
    job_context = context.job.context
    chat_id = job_context[\"chat_id\"]
    user_id = job_context[\"user_id\"]
    quiz_id = job_context[\"quiz_id\"]
    logger.info(f"Quiz timer expired for quiz {quiz_id} for user {user_id} in chat {chat_id}.")

    # Access user_data via bot_data (requires passing dispatcher to main)
    user_data = context.dispatcher.user_data.get(user_id, {})
    quiz_data = user_data.get(\"current_quiz\")

    # Check if the quiz is still the active one
    if quiz_data and quiz_data[\"quiz_id\"] == quiz_id and not quiz_data.get(\"timed_out\"):
        quiz_data[\"timed_out\"] = True # Mark as timed out
        # Remove question timer if it exists
        if quiz_data.get(\"question_timer_job_name\"):
            remove_job_if_exists(quiz_data[\"question_timer_job_name\"], context)
            quiz_data[\"question_timer_job_name\"] = None

        safe_send_message(context.bot, chat_id, text="⏰ انتهى وقت الاختبار!")
        # Call show_results to finalize and display
        show_results(chat_id, user_id, quiz_id, context, timed_out=True)
    else:
        logger.info(f"Quiz {quiz_id} already finished or cancelled, ignoring timeout.")

def question_timer_callback(context: CallbackContext):
    """Callback function when the question timer expires."""
    job_context = context.job.context
    chat_id = job_context[\"chat_id\"]
    user_id = job_context[\"user_id\"]
    quiz_id = job_context[\"quiz_id\"]
    question_index = job_context[\"question_index\"]
    logger.info(f"Question timer expired for question {question_index} in quiz {quiz_id} for user {user_id}.")

    user_data = context.dispatcher.user_data.get(user_id, {})
    quiz_data = user_data.get(\"current_quiz\")

    # Check if the quiz and question index match the current state
    if quiz_data and quiz_data[\"quiz_id\"] == quiz_id and quiz_data[\"current_question_index\"] == question_index and not quiz_data.get(\"timed_out\"):
        safe_send_message(context.bot, chat_id, text=f"⏰ انتهى وقت السؤال {question_index + 1}! سيتم اعتباره متخطى.")
        # Treat as skip
        handle_quiz_skip(chat_id, user_id, quiz_id, question_index, context, timed_out=True)
    else:
        logger.info(f"Question {question_index} already answered/skipped or quiz ended, ignoring timer.")

# --- Keyboard Creation Functions ---
# (Keep existing keyboard functions, ensure callback_data uses single quotes)

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
        [InlineKeyboardButton("📚 اختبار تحصيلي عام", callback_data=\'quiz_random_prompt\')],
        [InlineKeyboardButton("📄 اختبار حسب الفصل", callback_data=\'quiz_by_chapter_prompt\')],
        [InlineKeyboardButton("📝 اختبار حسب الدرس", callback_data=\'quiz_by_lesson_prompt\')],
        [InlineKeyboardButton("🎓 اختبار حسب المرحلة الدراسية", callback_data=\'quiz_by_grade_prompt\')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=\'main_menu\')]
    ]
    return InlineKeyboardMarkup(keyboard)

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
        [InlineKeyboardButton("15 دقائق", callback_data=\'quiz_duration_15\')],
        [InlineKeyboardButton("20 دقائق", callback_data=\'quiz_duration_20\')],
        [InlineKeyboardButton("30 دقائق", callback_data=\'quiz_duration_30\')],
        [InlineKeyboardButton("بدون وقت محدد", callback_data=\'quiz_duration_0\')],
        [InlineKeyboardButton("🔙 العودة لاختيار النوع", callback_data=\'menu_quiz\')] # Simplified back
    ]
    return InlineKeyboardMarkup(keyboard)

def create_grade_levels_keyboard(for_quiz=False, context=None):
    grades = QUIZ_DB.get_all_grade_levels()
    keyboard = []
    if grades:
        for grade_id, grade_name in grades:
            callback_data = f\'select_grade_quiz_{grade_id}\' if for_quiz else f\'admin_grade_{grade_id}\'
            keyboard.append([InlineKeyboardButton(grade_name, callback_data=callback_data)])
    else:
        logger.info("No grade levels found in the database.")
        pass

    back_callback = \'menu_quiz\' if for_quiz else \'admin_manage_structure\'
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_chapters_keyboard(grade_level_id, for_quiz=False, for_lesson_selection=False, context=None):
    chapters = QUIZ_DB.get_chapters_by_grade(grade_level_id)
    keyboard = []
    if chapters:
        for chapter_id, chapter_name in chapters:
            if for_quiz:
                callback_data = f\'select_chapter_quiz_{chapter_id}\'
            elif for_lesson_selection:
                 callback_data = f\'select_lesson_chapter_{chapter_id}\'
            else: # Admin context
                callback_data = f\'admin_chapter_{chapter_id}\'
            keyboard.append([InlineKeyboardButton(chapter_name, callback_data=callback_data)])
    else:
        logger.info(f"No chapters found for grade level {grade_level_id}.")
        pass

    back_callback = \'quiz_selection_back_to_grades\' if (for_quiz or for_lesson_selection) else \'admin_manage_structure\'
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_lessons_keyboard(chapter_id, for_quiz=False, context=None):
    lessons = QUIZ_DB.get_lessons_by_chapter(chapter_id)
    keyboard = []
    if lessons:
        for lesson_id, lesson_name in lessons:
            callback_data = f\'select_lesson_quiz_{lesson_id}\' if for_quiz else f\'admin_lesson_{lesson_id}\'
            keyboard.append([InlineKeyboardButton(lesson_name, callback_data=callback_data)])
    else:
        logger.info(f"No lessons found for chapter {chapter_id}.")
        pass

    back_callback = \'quiz_selection_back_to_chapters\' if for_quiz else \'admin_manage_structure\'
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_quiz_question_keyboard(options, question_id, question_index):
    keyboard = []
    shuffled_options = list(enumerate(options))
    random.shuffle(shuffled_options)
    for original_index, option_text in shuffled_options:
        callback_data = f\'answer_{question_id}_{original_index}_{question_index}\'
        keyboard.append([InlineKeyboardButton(option_text, callback_data=callback_data)])
    keyboard.append([InlineKeyboardButton("⏭️ تخطي السؤال", callback_data=f\'skip_{question_id}_{question_index}\')])
    return InlineKeyboardMarkup(keyboard)

def create_results_menu_keyboard(quiz_id):
    keyboard = [
        [InlineKeyboardButton("🔄 اختبار جديد", callback_data=\'menu_quiz\')],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data=\'main_menu\')]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Integrated Info Menu Functions ---
# (Keep existing info menu functions)
def create_info_menu_keyboard():
    """Creates the info menu keyboard (moved from info_handlers.py)."""
    keyboard = [
        [InlineKeyboardButton("🧪 العناصر الكيميائية", callback_data=\'info_elements\')],
        [InlineKeyboardButton("🔬 المركبات الكيميائية", callback_data=\'info_compounds\')],
        [InlineKeyboardButton("📘 المفاهيم الكيميائية", callback_data=\'info_concepts\')],
        [InlineKeyboardButton("📊 الجدول الدوري", callback_data=\'info_periodic_table\')],
        [InlineKeyboardButton("🔢 الحسابات الكيميائية", callback_data=\'info_calculations\')],
        [InlineKeyboardButton("🔗 الروابط الكيميائية", callback_data=\'info_bonds\')],
        [InlineKeyboardButton("📜 أهم قوانين التحصيلي", callback_data=\'info_laws\')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=\'main_menu\')],
    ]
    return InlineKeyboardMarkup(keyboard)

def show_info_menu(update: Update, context: CallbackContext) -> int:
    """Displays the info menu (integrated)."""
    query = update.callback_query
    if query:
        query.answer()
        logger.info("Showing info menu")
        safe_edit_message_text(query, text="اختر أحد أقسام المعلومات الكيميائية:", reply_markup=create_info_menu_keyboard())
    else:
        update.message.reply_text("اختر أحد أقسام المعلومات الكيميائية:", reply_markup=create_info_menu_keyboard())
    return INFO_MENU

def handle_info_elements(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    safe_edit_message_text(query, text="قسم العناصر الكيميائية قيد التطوير.", reply_markup=create_info_menu_keyboard())
    return INFO_MENU

def handle_info_compounds(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    safe_edit_message_text(query, text="قسم المركبات الكيميائية قيد التطوير.", reply_markup=create_info_menu_keyboard())
    return INFO_MENU

def handle_info_concepts(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    safe_edit_message_text(query, text="قسم المفاهيم الكيميائية قيد التطوير.", reply_markup=create_info_menu_keyboard())
    return INFO_MENU

def handle_info_periodic_table(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    safe_edit_message_text(query, text="قسم الجدول الدوري قيد التطوير.", reply_markup=create_info_menu_keyboard())
    return INFO_MENU

def handle_info_calculations(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    safe_edit_message_text(query, text="قسم الحسابات الكيميائية قيد التطوير.", reply_markup=create_info_menu_keyboard())
    return INFO_MENU

def handle_info_bonds(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    safe_edit_message_text(query, text="قسم الروابط الكيميائية قيد التطوير.", reply_markup=create_info_menu_keyboard())
    return INFO_MENU

def handle_info_laws(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    try:
        with open("chemistry_laws_content.md", "r", encoding="utf-8") as f:
            laws_content = f.read()
        safe_edit_message_text(query, text=laws_content, reply_markup=create_info_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)
    except FileNotFoundError:
        logger.error("Chemistry laws content file (chemistry_laws_content.md) not found.")
        safe_edit_message_text(query, text="عذراً، حدث خطأ أثناء تحميل محتوى قوانين الكيمياء.", reply_markup=create_info_menu_keyboard())
    except Exception as e:
        logger.error(f"Error loading/sending chemistry laws content: {e}")
        safe_edit_message_text(query, text="عذراً، حدث خطأ غير متوقع.", reply_markup=create_info_menu_keyboard())
    return INFO_MENU

def info_menu_callback(update: Update, context: CallbackContext) -> int:
    """Handles button presses within the integrated info menu."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.from_user.id
    logger.info(f"User {user_id} chose {data} from info menu.")

    if data == \'info_elements\': return handle_info_elements(update, context)
    elif data == \'info_compounds\': return handle_info_compounds(update, context)
    elif data == \'info_concepts\': return handle_info_concepts(update, context)
    elif data == \'info_periodic_table\': return handle_info_periodic_table(update, context)
    elif data == \'info_calculations\': return handle_info_calculations(update, context)
    elif data == \'info_bonds\': return handle_info_bonds(update, context)
    elif data == \'info_laws\': return handle_info_laws(update, context)
    elif data == \'main_menu\':
        logger.info("Returning to MAIN_MENU from info menu.")
        safe_edit_message_text(query, text="القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU
    else:
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_info_menu_keyboard())
        return INFO_MENU

# --- Core Bot Handlers ---

def start(update: Update, context: CallbackContext) -> int:
    user = update.effective_user
    user_id = user.id
    name = get_user_name(user)
    logger.info(f"User {name} (ID: {user_id}) started the bot.")

    if QUIZ_DB:
        QUIZ_DB.add_or_update_user(user_id, user.username, user.first_name, user.last_name)
    else:
        logger.error("Cannot add/update user: QuizDatabase not initialized.")

    context.user_data.clear() # Clear previous state on /start
    context.user_data["user_id"] = user_id

    welcome_text = f"أهلاً بك يا {name} في بوت الكيمياء التعليمي! 👋\n\n"
    welcome_text += "استخدم الأزرار أدناه للتنقل بين الأقسام المختلفة."

    keyboard = create_main_menu_keyboard(user_id)
    if update.message:
        update.message.reply_text(welcome_text, reply_markup=keyboard)
    elif update.callback_query: # Handle restart from callback
        safe_edit_message_text(update.callback_query, text=welcome_text, reply_markup=keyboard)

    return MAIN_MENU

def cancel(update: Update, context: CallbackContext) -> int:
    user = update.effective_user
    user_id = user.id
    chat_id = update.effective_chat.id
    logger.info(f"User {user_id} canceled operation.")

    # Remove timers if a quiz was active
    quiz_data = context.user_data.get(\'current_quiz\')
    if quiz_data:
        quiz_id = quiz_data.get(\'quiz_id\')
        quiz_timer_job_name = f"quiz_timer_{chat_id}_{user_id}_{quiz_id}"
        question_timer_job_name = f"question_timer_{chat_id}_{user_id}_{quiz_id}"
        remove_job_if_exists(quiz_timer_job_name, context)
        remove_job_if_exists(question_timer_job_name, context)

    text = "تم إلغاء العملية الحالية. العودة إلى القائمة الرئيسية."
    keyboard = create_main_menu_keyboard(user_id)
    if update.callback_query:
        safe_edit_message_text(update.callback_query, text=text, reply_markup=keyboard)
    else:
        safe_send_message(context.bot, chat_id, text=text, reply_markup=keyboard)

    # Clear user data except user_id
    keys_to_clear = [k for k in context.user_data if k not in ["user_id"]]
    for key in keys_to_clear:
        del context.user_data[key]

    return MAIN_MENU

def help_command(update: Update, context: CallbackContext):
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

# --- Callback Query Handlers ---

def main_menu_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user = query.from_user
    user_id = user.id
    data = query.data

    logger.info(f"User {user_id} chose {data} from main menu or returning to main menu.")

    if "user_id" not in context.user_data:
        context.user_data["user_id"] = user_id

    if data == \'main_menu\':
        safe_edit_message_text(query, text="القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU
    if data == \'menu_info\':
        return show_info_menu(update, context)
    elif data == \'menu_quiz\':
        safe_edit_message_text(query, text="اختر نوع الاختبار:", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU
    elif data == \'menu_reports\':
        safe_edit_message_text(query, text="ميزة التقارير قيد التطوير. 🚧", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU
    elif data == \'menu_about\':
        about_text = "بوت الكيمياء التعليمي\n"
        about_text += "تم التطوير بواسطة الاستاذ حسين الموسى\n"
        about_text += "الإصدار: 1.5 (تحسين عرض الأسئلة)\n\n"
        about_text += "يهدف هذا البوت لمساعدتك في دراسة الكيمياء من خلال الاختبارات والمعلومات."
        safe_edit_message_text(query, text=about_text, reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU
    elif data == \'menu_admin\':
        if is_admin(user_id):
            safe_edit_message_text(query, text="قائمة إدارة البوت:", reply_markup=create_admin_menu_keyboard())
            return ADMIN_MENU
        else:
            query.answer("ليس لديك صلاحيات الوصول لهذه القائمة.", show_alert=True)
            return MAIN_MENU
    else:
        logger.warning(f"Unexpected callback data \'{data}\' received in MAIN_MENU state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU

# --- Quiz Selection Handlers ---

def quiz_menu_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data
    logger.info(f"User {user_id} chose {data} from quiz menu.")

    context.user_data.pop(\'quiz_selection_mode\', None)
    context.user_data.pop(\'selected_grade_id\', None)
    context.user_data.pop(\'selected_chapter_id\', None)

    if data == \'main_menu\':
        safe_edit_message_text(query, text="القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU
    elif data == \'quiz_random_prompt\':
        context.user_data["quiz_type"] = "random"
        context.user_data["quiz_filter_id"] = None
        safe_edit_message_text(query, text="اختر مدة الاختبار العشوائي:", reply_markup=create_quiz_duration_keyboard())
        return SELECTING_QUIZ_DURATION
    elif data == \'quiz_by_grade_prompt\':
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
        if keyboard.inline_keyboard and len(keyboard.inline_keyboard) > 1:
            safe_edit_message_text(query, text="اختر المرحلة الدراسية للاختبار:", reply_markup=keyboard)
            context.user_data["quiz_selection_mode"] = "grade"
            return SELECT_GRADE_LEVEL_FOR_QUIZ
        else:
            safe_edit_message_text(query, text="لم يتم إضافة مراحل دراسية بعد.", reply_markup=create_quiz_menu_keyboard())
            return QUIZ_MENU
    elif data == \'quiz_by_chapter_prompt\':
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
        if keyboard.inline_keyboard and len(keyboard.inline_keyboard) > 1:
            safe_edit_message_text(query, text="أولاً، اختر المرحلة الدراسية التي ينتمي إليها الفصل:", reply_markup=keyboard)
            context.user_data["quiz_selection_mode"] = "chapter"
            return SELECT_GRADE_LEVEL_FOR_QUIZ
        else:
            safe_edit_message_text(query, text="لم يتم إضافة مراحل دراسية بعد.", reply_markup=create_quiz_menu_keyboard())
            return QUIZ_MENU
    elif data == \'quiz_by_lesson_prompt\':
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
        if keyboard.inline_keyboard and len(keyboard.inline_keyboard) > 1:
            safe_edit_message_text(query, text="أولاً، اختر المرحلة الدراسية التي ينتمي إليها الدرس:", reply_markup=keyboard)
            context.user_data["quiz_selection_mode"] = "lesson"
            return SELECT_GRADE_LEVEL_FOR_QUIZ
        else:
            safe_edit_message_text(query, text="لم يتم إضافة مراحل دراسية بعد.", reply_markup=create_quiz_menu_keyboard())
            return QUIZ_MENU
    else:
        logger.warning(f"Unexpected callback data \'{data}\' in QUIZ_MENU state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

def select_grade_level_for_quiz_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data
    mode = context.user_data.get(\'quiz_selection_mode\')

    if data == \'menu_quiz\': # Back button
        safe_edit_message_text(query, text="اختر نوع الاختبار:", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

    if data.startswith(\'select_grade_quiz_\'):
        try:
            grade_id = int(data.split(\'_\')[-1])
            context.user_data["selected_grade_id"] = grade_id
            logger.info(f"User {user_id} selected grade {grade_id} for quiz mode \'{mode}\'.")

            if mode == \'grade\':
                context.user_data["quiz_type"] = "grade"
                context.user_data["quiz_filter_id"] = grade_id
                safe_edit_message_text(query, text="اختر مدة الاختبار:", reply_markup=create_quiz_duration_keyboard())
                return SELECTING_QUIZ_DURATION
            elif mode == \'chapter\':
                keyboard = create_chapters_keyboard(grade_id, for_quiz=True, context=context)
                if keyboard.inline_keyboard and len(keyboard.inline_keyboard) > 1:
                    safe_edit_message_text(query, text="اختر الفصل للاختبار:", reply_markup=keyboard)
                    return SELECT_CHAPTER_FOR_QUIZ
                else:
                    safe_edit_message_text(query, text="لا توجد فصول لهذه المرحلة. الرجاء اختيار مرحلة أخرى.", reply_markup=create_grade_levels_keyboard(for_quiz=True, context=context))
                    return SELECT_GRADE_LEVEL_FOR_QUIZ
            elif mode == \'lesson\':
                keyboard = create_chapters_keyboard(grade_id, for_lesson_selection=True, context=context)
                if keyboard.inline_keyboard and len(keyboard.inline_keyboard) > 1:
                    safe_edit_message_text(query, text="اختر الفصل الذي ينتمي إليه الدرس:", reply_markup=keyboard)
                    return SELECT_CHAPTER_FOR_LESSON_QUIZ
                else:
                    safe_edit_message_text(query, text="لا توجد فصول لهذه المرحلة. الرجاء اختيار مرحلة أخرى.", reply_markup=create_grade_levels_keyboard(for_quiz=True, context=context))
                    return SELECT_GRADE_LEVEL_FOR_QUIZ
            else:
                logger.error(f"Invalid quiz selection mode: {mode}")
                safe_edit_message_text(query, text="حدث خطأ في اختيار نوع الاختبار.", reply_markup=create_quiz_menu_keyboard())
                return QUIZ_MENU

        except (ValueError, IndexError):
            logger.error(f"Invalid grade callback data: {data}")
            safe_edit_message_text(query, text="اختيار مرحلة غير صالح.", reply_markup=create_grade_levels_keyboard(for_quiz=True, context=context))
            return SELECT_GRADE_LEVEL_FOR_QUIZ
    elif data == \'quiz_selection_back_to_grades\':
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
        text = "اختر المرحلة الدراسية للاختبار:"
        if mode == \'chapter\': text = "أولاً، اختر المرحلة الدراسية التي ينتمي إليها الفصل:"
        elif mode == \'lesson\': text = "أولاً، اختر المرحلة الدراسية التي ينتمي إليه الدرس:"
        safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_GRADE_LEVEL_FOR_QUIZ
    else:
        logger.warning(f"Unexpected callback data \'{data}\' in SELECT_GRADE_LEVEL_FOR_QUIZ state.")
        return SELECT_GRADE_LEVEL_FOR_QUIZ

def select_chapter_for_quiz_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data
    grade_id = context.user_data.get(\'selected_grade_id\')

    if data == \'quiz_selection_back_to_grades\': # Back button
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
        safe_edit_message_text(query, text="أولاً، اختر المرحلة الدراسية التي ينتمي إليها الفصل:", reply_markup=keyboard)
        return SELECT_GRADE_LEVEL_FOR_QUIZ

    if data.startswith(\'select_chapter_quiz_\'):
        try:
            chapter_id = int(data.split(\'_\')[-1])
            context.user_data["quiz_type"] = "chapter"
            context.user_data["quiz_filter_id"] = chapter_id
            logger.info(f"User {user_id} selected chapter {chapter_id} for quiz.")
            safe_edit_message_text(query, text="اختر مدة الاختبار:", reply_markup=create_quiz_duration_keyboard())
            return SELECTING_QUIZ_DURATION
        except (ValueError, IndexError):
            logger.error(f"Invalid chapter callback data: {data}")
            keyboard = create_chapters_keyboard(grade_id, for_quiz=True, context=context)
            safe_edit_message_text(query, text="اختيار فصل غير صالح.", reply_markup=keyboard)
            return SELECT_CHAPTER_FOR_QUIZ
    else:
        logger.warning(f"Unexpected callback data \'{data}\' in SELECT_CHAPTER_FOR_QUIZ state.")
        return SELECT_CHAPTER_FOR_QUIZ

def select_chapter_for_lesson_quiz_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data
    grade_id = context.user_data.get(\'selected_grade_id\')

    if data == \'quiz_selection_back_to_grades\': # Back button
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
        safe_edit_message_text(query, text="أولاً، اختر المرحلة الدراسية التي ينتمي إليها الدرس:", reply_markup=keyboard)
        return SELECT_GRADE_LEVEL_FOR_QUIZ

    if data.startswith(\'select_lesson_chapter_\'):
        try:
            chapter_id = int(data.split(\'_\')[-1])
            context.user_data["selected_chapter_id"] = chapter_id
            logger.info(f"User {user_id} selected chapter {chapter_id} to choose lesson for quiz.")
            keyboard = create_lessons_keyboard(chapter_id, for_quiz=True, context=context)
            if keyboard.inline_keyboard and len(keyboard.inline_keyboard) > 1:
                safe_edit_message_text(query, text="اختر الدرس للاختبار:", reply_markup=keyboard)
                return SELECT_LESSON_FOR_QUIZ
            else:
                safe_edit_message_text(query, text="لا توجد دروس لهذا الفصل. الرجاء اختيار فصل آخر.", reply_markup=create_chapters_keyboard(grade_id, for_lesson_selection=True, context=context))
                return SELECT_CHAPTER_FOR_LESSON_QUIZ
        except (ValueError, IndexError):
            logger.error(f"Invalid chapter callback data for lesson selection: {data}")
            keyboard = create_chapters_keyboard(grade_id, for_lesson_selection=True, context=context)
            safe_edit_message_text(query, text="اختيار فصل غير صالح.", reply_markup=keyboard)
            return SELECT_CHAPTER_FOR_LESSON_QUIZ
    else:
        logger.warning(f"Unexpected callback data \'{data}\' in SELECT_CHAPTER_FOR_LESSON_QUIZ state.")
        return SELECT_CHAPTER_FOR_LESSON_QUIZ

def select_lesson_for_quiz_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data
    chapter_id = context.user_data.get(\'selected_chapter_id\')
    grade_id = context.user_data.get(\'selected_grade_id\') # Needed for back button

    if data == \'quiz_selection_back_to_chapters\': # Back button
        keyboard = create_chapters_keyboard(grade_id, for_lesson_selection=True, context=context)
        safe_edit_message_text(query, text="اختر الفصل الذي ينتمي إليه الدرس:", reply_markup=keyboard)
        return SELECT_CHAPTER_FOR_LESSON_QUIZ

    if data.startswith(\'select_lesson_quiz_\'):
        try:
            lesson_id = int(data.split(\'_\')[-1])
            context.user_data["quiz_type"] = "lesson"
            context.user_data["quiz_filter_id"] = lesson_id
            logger.info(f"User {user_id} selected lesson {lesson_id} for quiz.")
            safe_edit_message_text(query, text="اختر مدة الاختبار:", reply_markup=create_quiz_duration_keyboard())
            return SELECTING_QUIZ_DURATION
        except (ValueError, IndexError):
            logger.error(f"Invalid lesson callback data: {data}")
            keyboard = create_lessons_keyboard(chapter_id, for_quiz=True, context=context)
            safe_edit_message_text(query, text="اختيار درس غير صالح.", reply_markup=keyboard)
            return SELECT_LESSON_FOR_QUIZ
    else:
        logger.warning(f"Unexpected callback data \'{data}\' in SELECT_LESSON_FOR_QUIZ state.")
        return SELECT_LESSON_FOR_QUIZ

# --- Quiz Taking Handlers ---

def start_quiz(user_id: int, quiz_type: str, filter_id: int | None, num_questions: int, context: CallbackContext) -> dict | None:
    """Fetches questions from DB and initializes quiz data."""
    questions = []
    if quiz_type == \'random\':
        questions = QUIZ_DB.get_random_questions(num_questions)
    elif quiz_type == \'grade\':
        questions = QUIZ_DB.get_questions_by_grade(filter_id, num_questions)
    elif quiz_type == \'chapter\':
        questions = QUIZ_DB.get_questions_by_chapter(filter_id, num_questions)
    elif quiz_type == \'lesson\':
        questions = QUIZ_DB.get_questions_by_lesson(filter_id, num_questions)

    if not questions:
        logger.warning(f"No questions found for quiz type 
{quiz_type}
 with filter 
{filter_id}
.")
        return None

    # Shuffle questions
    random.shuffle(questions)
    # Limit number of questions if more were fetched than requested (e.g., for grade/chapter/lesson)
    questions = questions[:num_questions]

    # Format questions into the structure needed for the quiz
    formatted_questions = []
    for q in questions:
        try:
            options = [q[\"option1\"], q[\"option2\"], q[\"option3\"], q[\"option4\"]]
            # Ensure correct_answer_index is 0-based
            correct_index = int(q[\"correct_answer\"]) - 1
            if not (0 <= correct_index < 4):
                logger.error(f"Invalid correct_answer value 
{q[\"correct_answer\"]}
 for question ID 
{q[\"id\"]}
. Skipping.")
                continue

            formatted_questions.append({
                \"id\": q[\"id\"],
                \"text\": q[\"question_text\"],
                \"options\": options,
                \"correct_answer_index\": correct_index,
                \"explanation\": q[\"explanation\"],
                \"image_data\": q[\"image_data\"] # Include image data if present
            })
        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Error processing question ID 
{q.get(\'id\', \'N/A\')}
: 
{e}
. Skipping.")
            continue

    if not formatted_questions:
        logger.error("Failed to format any questions after fetching.")
        return None

    quiz_id = random.randint(10000, 99999) # Unique quiz ID
    chat_id = context.user_data.get(\"chat_id\") # Get chat_id stored earlier
    duration_minutes = context.user_data.get(\"quiz_duration_minutes\", 0)

    quiz_data = {
        \"quiz_id\": quiz_id,
        \"user_id\": user_id,
        \"chat_id\": chat_id,
        \"questions\": formatted_questions,
        \"current_question_index\": 0,
        \"answers\": {}, # Store user answers {question_id: {selected: index, correct: index, is_correct: bool}}
        \"score\": 0,
        \"start_time\": datetime.now(),
        \"duration_minutes\": duration_minutes,
        \"quiz_timer_job_name\": None,
        \"question_timer_job_name\": None,
        \"timed_out\": False,
        \"last_message_id\": None # To store the ID of the question message for editing
    }
    context.user_data[\"current_quiz\"] = quiz_data
    logger.info(f"Quiz 
{quiz_id}
 started for user 
{user_id}
 with 
{len(formatted_questions)}
 questions.")
    return quiz_data

def send_next_question(update: Update | None, context: CallbackContext, query: Update.callback_query = None):
    """Sends the next question or ends the quiz."""
    user_id = context.user_data.get(\"user_id\")
    quiz_data = context.user_data.get(\"current_quiz\")

    if not quiz_data or quiz_data[\"user_id\"] != user_id or quiz_data.get(\"timed_out\"):
        logger.warning("send_next_question called without active quiz or after timeout.")
        # Optionally send a message or end conversation
        return ConversationHandler.END # Or MAIN_MENU

    current_index = quiz_data[\"current_question_index\"]
    questions = quiz_data[\"questions\"]

    if current_index >= len(questions):
        # Quiz finished
        logger.info(f"Quiz 
{quiz_data[\"quiz_id\"]}
 finished for user 
{user_id}
.")
        # Remove timers
        if quiz_data.get(\"quiz_timer_job_name\"):
            remove_job_if_exists(quiz_data[\"quiz_timer_job_name\"], context)
        if quiz_data.get(\"question_timer_job_name\"):
            remove_job_if_exists(quiz_data[\"question_timer_job_name\"], context)
        # Show results
        return show_results(quiz_data[\"chat_id\"], user_id, quiz_data[\"quiz_id\"], context)

    question = questions[current_index]
    question_text = f"السؤال {current_index + 1} من {len(questions)}:\n\n{question[\"text\"]}"
    keyboard = create_quiz_question_keyboard(question[\"options\"], question[\"id\"], current_index)

    chat_id = quiz_data[\"chat_id\"]
    image_data = question.get(\"image_data\")
    sent_message = None

    # Determine how to send/edit the message
    edit_target = query or update # Prefer query if available
    use_edit = edit_target and edit_target.message # Can we edit the previous message?

    try:
        if image_data:
            photo = BytesIO(image_data)
            if use_edit:
                # Editing with media requires InputMediaPhoto
                try:
                    media = InputMediaPhoto(media=photo, caption=question_text)
                    sent_message = edit_target.message.edit_media(media=media, reply_markup=keyboard)
                except BadRequest as e:
                    logger.warning(f"Failed to edit media, sending new message: {e}")
                    # Fallback to sending a new message if editing media fails
                    sent_message = context.bot.send_photo(chat_id=chat_id, photo=photo, caption=question_text, reply_markup=keyboard)
                    # Try to delete the old message if possible
                    try: edit_target.message.delete() 
                    except: pass
            else:
                sent_message = context.bot.send_photo(chat_id=chat_id, photo=photo, caption=question_text, reply_markup=keyboard)
        else:
            if use_edit:
                # Try editing text, fallback to sending new if it fails (e.g., message too old)
                try:
                    sent_message = safe_edit_message_text(edit_target, text=question_text, reply_markup=keyboard, parse_mode=ParseMode.HTML) # Use HTML or Markdown if needed
                except BadRequest:
                    logger.warning("Failed to edit text message, sending new.")
                    sent_message = safe_send_message(context.bot, chat_id, text=question_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
                    try: edit_target.message.delete() 
                    except: pass
            else:
                sent_message = safe_send_message(context.bot, chat_id, text=question_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

        # Store the message ID for potential future edits (like showing feedback)
        if sent_message:
            quiz_data[\"last_message_id\"] = sent_message.message_id

        # Set question timer
        q_timer_job = set_question_timer(context, chat_id, user_id, quiz_data[\"quiz_id\"], current_index)
        if q_timer_job:
            quiz_data[\"question_timer_job_name\"] = q_timer_job

        return TAKING_QUIZ # Stay in the quiz state

    except Exception as e:
        logger.error(f"Error sending question 
{current_index}
 for quiz 
{quiz_data[\"quiz_id\"]}
: 
{e}
")
        safe_send_message(context.bot, chat_id, text="حدث خطأ أثناء عرض السؤال. سيتم إلغاء الاختبار.")
        # Clean up quiz state and timers
        cancel(update, context) # Use cancel to clean up
        return MAIN_MENU

def select_quiz_duration_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    chat_id = update.effective_chat.id
    data = query.data
    logger.info(f"User {user_id} chose duration {data}.")

    # Store chat_id in user_data if not already present
    if \"chat_id\" not in context.user_data:
        context.user_data[\"chat_id\"] = chat_id

    if data.startswith(\'quiz_duration_\'):
        try:
            duration_minutes = int(data.split(\'_\')[-1])
            context.user_data["quiz_duration_minutes"] = duration_minutes
            quiz_type = context.user_data.get(\'quiz_type\')
            quiz_filter_id = context.user_data.get(\'quiz_filter_id\')
            logger.info(f"Attempting to start quiz for user {user_id}: type={quiz_type}, filter_id={quiz_filter_id}, duration={duration_minutes} mins")

            # Start the quiz (fetch questions, setup data)
            quiz_data = start_quiz(user_id, quiz_type, quiz_filter_id, DEFAULT_QUIZ_QUESTIONS, context)

            if quiz_data:
                # Set the overall quiz timer
                quiz_timer_job = set_quiz_timer(context, chat_id, user_id, quiz_data[\"quiz_id\"], duration_minutes)
                if quiz_timer_job:
                    quiz_data[\"quiz_timer_job_name\"] = quiz_timer_job # Store job name

                # Send the first question
                return send_next_question(update, context, query=query)
            else:
                safe_edit_message_text(query, text="عذراً، لم يتم العثور على أسئلة لهذا الاختبار أو حدث خطأ.", reply_markup=create_quiz_menu_keyboard())
                return QUIZ_MENU

        except ValueError:
            logger.error(f"Invalid duration value in callback data: {data}")
            safe_edit_message_text(query, text="مدة غير صالحة.", reply_markup=create_quiz_duration_keyboard())
            return SELECTING_QUIZ_DURATION
        except Exception as e:
            logger.error(f"Error during quiz start process: {e}", exc_info=True)
            safe_edit_message_text(query, text="حدث خطأ غير متوقع أثناء بدء الاختبار.", reply_markup=create_quiz_menu_keyboard())
            return QUIZ_MENU

    elif data == \'menu_quiz\': # Back button from duration selection
        # Go back to the main quiz type selection menu
        safe_edit_message_text(query, text="اختر نوع الاختبار:", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU
    else:
        logger.warning(f"Unexpected callback data \'{data}\' in SELECTING_QUIZ_DURATION state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_quiz_duration_keyboard())
        return SELECTING_QUIZ_DURATION

def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    chat_id = update.effective_chat.id
    data = query.data
    quiz_data = context.user_data.get(\'current_quiz\')

    if not quiz_data or quiz_data[\"user_id\"] != user_id or quiz_data.get(\"timed_out\"):
        safe_edit_message_text(query, text="لم يعد هذا الاختبار نشطاً.")
        # Attempt to clear keyboard if possible
        try: query.edit_message_reply_markup(reply_markup=None) 
        except: pass
        return MAIN_MENU

    try:
        _, question_id_str, selected_option_index_str, question_index_str = data.split(\'_\')
        question_id = int(question_id_str)
        selected_option_index = int(selected_option_index_str)
        question_index = int(question_index_str)
    except (ValueError, IndexError):
        logger.error(f"Invalid answer callback data: {data}")
        return TAKING_QUIZ # Stay in quiz state

    # Check if this answer is for the current question
    if question_index != quiz_data[\"current_question_index\"]:
        query.answer("لقد تم تجاوز هذا السؤال أو الإجابة عليه بالفعل.")
        return TAKING_QUIZ

    # Remove question timer
    if quiz_data.get(\"question_timer_job_name\"):
        remove_job_if_exists(quiz_data[\"question_timer_job_name\"], context)
        quiz_data[\"question_timer_job_name\"] = None

    logger.info(f"User {user_id} answered question index {question_index} (ID: {question_id}) with option {selected_option_index}")

    # Process the answer
    current_question = quiz_data[\"questions\"][question_index]
    is_correct = (selected_option_index == current_question[\"correct_answer_index\"])
    quiz_data[\"answers\"][question_id] = {
        \"selected\": selected_option_index,
        \"correct\": current_question[\"correct_answer_index\"],
        \"is_correct\": is_correct
    }
    if is_correct:
        quiz_data[\"score\"] += 1
        feedback_text = "✅ إجابة صحيحة!"
    else:
        correct_option_text = current_question[\"options\"][current_question[\"correct_answer_index\"]]
        feedback_text = f"❌ إجابة خاطئة. الإجابة الصحيحة: {correct_option_text}"
        if current_question.get(\"explanation\"):
            feedback_text += f"\n\n📜 الشرح: {current_question[\"explanation\"]}"

    # Edit the original question message to show feedback and remove keyboard
    try:
        original_text = query.message.caption if query.message.photo else query.message.text
        context.bot.edit_message_caption(
            chat_id=chat_id,
            message_id=query.message.message_id,
            caption=original_text + f"\n\n*{feedback_text}*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=None # Remove keyboard
        ) if query.message.photo else context.bot.edit_message_text(
            text=original_text + f"\n\n*{feedback_text}*",
            chat_id=chat_id,
            message_id=query.message.message_id,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=None # Remove keyboard
        )
    except BadRequest as e:
        logger.warning(f"Could not edit message for feedback (maybe too old?): {e}")
        # Send feedback as a new message if editing fails
        safe_send_message(context.bot, chat_id, text=f"*{feedback_text}*", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Unexpected error editing message for feedback: {e}")

    # Move to the next question after a short delay
    quiz_data[\"current_question_index\"] += 1
    context.job_queue.run_once(
        lambda ctx: send_next_question(update, ctx), # Use lambda to pass context correctly
        FEEDBACK_DELAY,
        context=context.user_data # Pass user_data if needed, or rely on dispatcher access
    )

    return TAKING_QUIZ # Stay in the quiz state

def handle_quiz_skip(update: Update | None, context: CallbackContext, chat_id: int = None, user_id: int = None, quiz_id: int = None, question_index: int = None, timed_out: bool = False):
    """Handles skipping a question, either by user action or timeout."""
    query = update.callback_query if update else None
    if query:
        query.answer()
        user_id = query.from_user.id
        chat_id = update.effective_chat.id
        data = query.data
        try:
            _, question_id_str, question_index_str = data.split(\'_\')
            question_id = int(question_id_str)
            question_index = int(question_index_str)
        except (ValueError, IndexError):
            logger.error(f"Invalid skip callback data: {data}")
            return TAKING_QUIZ
    elif not timed_out:
        # Should not happen if called directly without timeout or query
        logger.error("handle_quiz_skip called incorrectly.")
        return ConversationHandler.END

    quiz_data = context.user_data.get(\'current_quiz\')

    # Validate quiz state
    if not quiz_data or quiz_data[\"user_id\"] != user_id or quiz_data.get(\"timed_out\"):
        if query: safe_edit_message_text(query, text="لم يعد هذا الاختبار نشطاً.")
        return MAIN_MENU
    if question_index != quiz_data[\"current_question_index\"]:
        if query: query.answer("لقد تم تجاوز هذا السؤال بالفعل.")
        return TAKING_QUIZ

    # Remove question timer
    if quiz_data.get(\"question_timer_job_name\"):
        remove_job_if_exists(quiz_data[\"question_timer_job_name\"], context)
        quiz_data[\"question_timer_job_name\"] = None

    logger.info(f"User {user_id} skipped question index {question_index} (ID: {quiz_data[\"questions\"][question_index][\"id\"]}). Timed out: {timed_out}")

    # Record skip (optional, could just not add to answers)
    # quiz_data[\"answers\"][question_id] = { \"selected\": None, \"correct\": ..., \"is_correct\": False, \"skipped\": True }

    feedback_text = "⏭️ تم تخطي السؤال."

    # Edit message to show skip feedback and remove keyboard
    if query:
        try:
            original_text = query.message.caption if query.message.photo else query.message.text
            context.bot.edit_message_caption(
                chat_id=chat_id,
                message_id=query.message.message_id,
                caption=original_text + f"\n\n*{feedback_text}*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=None
            ) if query.message.photo else context.bot.edit_message_text(
                text=original_text + f"\n\n*{feedback_text}*",
                chat_id=chat_id,
                message_id=query.message.message_id,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=None
            )
        except Exception as e:
            logger.warning(f"Could not edit message for skip feedback: {e}")
            # Send feedback as a new message if editing fails
            safe_send_message(context.bot, chat_id, text=f"*{feedback_text}*", parse_mode=ParseMode.MARKDOWN)
    # If called by timer, no query to edit, feedback already sent by timer callback

    # Move to the next question
    quiz_data[\"current_question_index\"] += 1
    # Use run_once for consistency, even with zero delay if not timed_out
    delay = 0 if timed_out else FEEDBACK_DELAY # No delay if called by timer
    context.job_queue.run_once(
        lambda ctx: send_next_question(update, ctx), # Pass update if available
        delay,
        context=context.user_data
    )

    return TAKING_QUIZ

# --- Results Handling (Placeholder) ---
def show_results(chat_id: int, user_id: int, quiz_id: int, context: CallbackContext, timed_out: bool = False) -> int:
    """Calculates and displays quiz results."""
    quiz_data = context.user_data.get(\"current_quiz\")

    if not quiz_data or quiz_data[\"quiz_id\"] != quiz_id:
        logger.warning(f"show_results called for inactive or mismatched quiz 
{quiz_id}
.")
        safe_send_message(context.bot, chat_id, "لم يتم العثور على بيانات هذا الاختبار.")
        return MAIN_MENU

    logger.info(f"Showing results for quiz 
{quiz_id}
 for user 
{user_id}
.")

    # --- !!! Placeholder: Calculate results, format message, save to DB --- 
    num_questions = len(quiz_data[\"questions\"])
    score = quiz_data[\"score\"]
    answers = quiz_data[\"answers\"]
    num_answered = len(answers)
    num_correct = score
    num_incorrect = num_answered - num_correct
    num_skipped = num_questions - num_answered

    end_time = datetime.now()
    time_taken = end_time - quiz_data[\"start_time\"]
    total_seconds = time_taken.total_seconds()
    minutes, seconds = divmod(total_seconds, 60)

    result_text = f"🏁 *نتائج الاختبار* 🏁\n\n"
    if timed_out:
        result_text += "⏰ انتهى الوقت المحدد للاختبار!\n"
    result_text += f"🔢 عدد الأسئلة: {num_questions}\n"
    result_text += f"✅ الإجابات الصحيحة: {num_correct}\n"
    result_text += f"❌ الإجابات الخاطئة: {num_incorrect}\n"
    result_text += f"⏭️ الأسئلة المتخطاة: {num_skipped}\n"
    result_text += f"⏱️ الوقت المستغرق: {int(minutes)} دقيقة و {int(seconds)} ثانية\n\n"

    percentage = (num_correct / num_questions * 100) if num_questions > 0 else 0
    result_text += f"🎯 النسبة المئوية: {percentage:.1f}%\n\n"

    # Add some encouragement
    if percentage >= 80:
        result_text += "🎉 ممتاز! أداء رائع!"
    elif percentage >= 60:
        result_text += "👍 جيد جداً! استمر في التقدم!"
    elif percentage >= 40:
        result_text += "💪 لا بأس! يمكنك التحسن بالمزيد من المراجعة."
    else:
        result_text += "📖 تحتاج إلى المزيد من المذاكرة. لا تيأس!"

    # Save results to DB (using the separate table as requested)
    try:
        QUIZ_DB.save_quiz_result(
            quiz_id=quiz_id,
            user_id=user_id,
            score=num_correct,
            total_questions=num_questions,
            time_taken_seconds=int(total_seconds),
            quiz_type=context.user_data.get(\"quiz_type\"), # Store quiz type
            filter_id=context.user_data.get(\"quiz_filter_id\") # Store filter ID
        )
        logger.info(f"Saved results for quiz 
{quiz_id}
 to database.")
    except Exception as e:
        logger.error(f"Failed to save quiz results for quiz 
{quiz_id}
: 
{e}
")
    # --- End Placeholder ---

    keyboard = create_results_menu_keyboard(quiz_id)
    safe_send_message(context.bot, chat_id, text=result_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

    # Clean up quiz data from user_data
    context.user_data.pop(\"current_quiz\", None)
    # Keep other selection data? Maybe clear it too.
    context.user_data.pop(\'quiz_selection_mode\', None)
    context.user_data.pop(\'selected_grade_id\', None)
    context.user_data.pop(\'selected_chapter_id\', None)
    context.user_data.pop(\'quiz_type\', None)
    context.user_data.pop(\'quiz_filter_id\', None)
    context.user_data.pop(\'quiz_duration_minutes\', None)

    return SHOWING_RESULTS # Transition to results state

def results_menu_callback(update: Update, context: CallbackContext) -> int:
    """Handles buttons pressed on the results screen."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == \'menu_quiz\':
        safe_edit_message_text(query, text="اختر نوع الاختبار:", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU
    elif data == \'main_menu\':
        safe_edit_message_text(query, text="القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU
    else:
        logger.warning(f"Unexpected callback data \'{data}\' in SHOWING_RESULTS state.")
        return SHOWING_RESULTS

# --- Admin Handlers (Placeholders - Keep as is) ---

def admin_menu_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    if not is_admin(user_id):
        query.answer("ليس لديك صلاحيات.", show_alert=True)
        return MAIN_MENU

    logger.info(f"Admin {user_id} chose {data} from admin menu.")

    if data == \'main_menu\':
        safe_edit_message_text(query, text="القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU
    elif data == \'admin_manage_structure\':
        safe_edit_message_text(query, text="إدارة الهيكل الدراسي:", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE
    # ... (other admin options need implementation) ...
    elif data == \'admin_add_question\':
         safe_edit_message_text(query, text="ميزة إضافة الأسئلة قيد التطوير.", reply_markup=create_admin_menu_keyboard())
         return ADMIN_MENU
    elif data == \'admin_delete_question\':
         safe_edit_message_text(query, text="ميزة حذف الأسئلة قيد التطوير.", reply_markup=create_admin_menu_keyboard())
         return ADMIN_MENU
    elif data == \'admin_show_question\':
         safe_edit_message_text(query, text="ميزة عرض الأسئلة قيد التطوير.", reply_markup=create_admin_menu_keyboard())
         return ADMIN_MENU
    else:
        logger.warning(f"Unexpected callback data \'{data}\' in ADMIN_MENU state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU

def admin_structure_menu_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    if not is_admin(user_id):
        query.answer("ليس لديك صلاحيات.", show_alert=True)
        safe_edit_message_text(query, text="القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU

    logger.info(f"Admin {user_id} chose {data} from admin structure menu.")

    if data == \'menu_admin\':
        safe_edit_message_text(query, text="قائمة إدارة البوت:", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU
    # ... (other structure options need implementation) ...
    elif data == \'admin_manage_grades\':
        safe_edit_message_text(query, text="ميزة إدارة المراحل قيد التطوير.", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE
    elif data == \'admin_manage_chapters\':
        safe_edit_message_text(query, text="ميزة إدارة الفصول قيد التطوير.", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE
    elif data == \'admin_manage_lessons\':
        safe_edit_message_text(query, text="ميزة إدارة الدروس قيد التطوير.", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE
    else:
        logger.warning(f"Unexpected callback data \'{data}\' in ADMIN_MANAGE_STRUCTURE state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE

# --- Error Handler ---
def error_handler(update: Update, context: CallbackContext):
    """Log Errors caused by Updates."""
    logger.error(f"Update \"{update}\" caused error \"{context.error}\"", exc_info=context.error)
    # Add more specific error handling if needed
    # For example, handle specific Telegram errors
    # if isinstance(context.error, Unauthorized):
    #     # Handle unauthorized error (e.g., bot blocked)
    # elif isinstance(context.error, NetworkError):
    #     # Handle network errors

# --- Main Function ---
def main():
    # Pass dispatcher to job context
    dp_for_jobs = {"dispatcher"}
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Pass dispatcher to job context data
    dp.bot_data[\"dispatcher\"] = dp

    # --- Conversation Handler Setup (Integrated Structure) ---
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler(\'start\', start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(main_menu_callback, pattern=\'^menu_\')
            ],
            QUIZ_MENU: [
                CallbackQueryHandler(quiz_menu_callback, pattern=\'^quiz_.*_prompt$\'
