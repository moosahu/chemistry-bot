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
DEFAULT_QUIZ_QUESTIONS = 10
DEFAULT_QUIZ_DURATION_MINUTES = 10
QUESTION_TIMER_SECONDS = 240
FEEDBACK_DELAY = 2

# --- Database Setup ---
try:
    from db_utils import connect_db, setup_database
    from quiz_db import QuizDatabase
    from helper_function import safe_edit_message_text
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
    setup_database(DB_CONN)
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
    INFO_MENU # State for the integrated info menu
) = range(32)

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

# --- Keyboard Creation Functions (Corrected callback_data quotes) ---

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
    keyboard = [
        [InlineKeyboardButton("📚 اختبار تحصيلي عام", callback_data='quiz_random_prompt')],
        [InlineKeyboardButton("📄 اختبار حسب الفصل", callback_data='quiz_by_chapter_prompt')],
        [InlineKeyboardButton("📝 اختبار حسب الدرس", callback_data='quiz_by_lesson_prompt')],
        [InlineKeyboardButton("🎓 اختبار حسب المرحلة الدراسية", callback_data='quiz_by_grade_prompt')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_admin_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ إضافة سؤال", callback_data='admin_add_question')],
        [InlineKeyboardButton("🗑️ حذف سؤال", callback_data='admin_delete_question')],
        [InlineKeyboardButton("🔍 عرض سؤال", callback_data='admin_show_question')],
        [InlineKeyboardButton("🏫 إدارة المراحل/الفصول/الدروس", callback_data='admin_manage_structure')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_structure_admin_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🏫 إدارة المراحل الدراسية", callback_data='admin_manage_grades')],
        [InlineKeyboardButton("📚 إدارة الفصول", callback_data='admin_manage_chapters')],
        [InlineKeyboardButton("📝 إدارة الدروس", callback_data='admin_manage_lessons')],
        [InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data='menu_admin')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_quiz_duration_keyboard():
    keyboard = [
        [InlineKeyboardButton("5 دقائق", callback_data='quiz_duration_5')],
        [InlineKeyboardButton("10 دقائق", callback_data='quiz_duration_10')],
        [InlineKeyboardButton("15 دقائق", callback_data='quiz_duration_15')],
        [InlineKeyboardButton("20 دقائق", callback_data='quiz_duration_20')],
        [InlineKeyboardButton("30 دقائق", callback_data='quiz_duration_30')],
        [InlineKeyboardButton("بدون وقت محدد", callback_data='quiz_duration_0')],
        [InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data='menu_quiz')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_grade_levels_keyboard(for_quiz=False, context=None):
    grades = QUIZ_DB.get_all_grade_levels()
    keyboard = []
    if grades:
        for grade_id, grade_name in grades:
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
    chapters = QUIZ_DB.get_chapters_by_grade(grade_level_id)
    keyboard = []
    if chapters:
        for chapter_id, chapter_name in chapters:
            if for_quiz:
                callback_data = f'chapter_quiz_{chapter_id}'
            elif for_lesson:
                 callback_data = f'lesson_chapter_{chapter_id}'
            else:
                callback_data = f'admin_chapter_{chapter_id}'
            keyboard.append([InlineKeyboardButton(chapter_name, callback_data=callback_data)])
    else:
        logger.info(f"No chapters found for grade level {grade_level_id}.")
        return None
    if for_quiz or for_lesson:
        back_callback = 'quiz_by_grade_prompt'
    else:
        back_callback = 'admin_manage_structure'
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_lessons_keyboard(chapter_id, for_quiz=False, context=None):
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
        back_callback = 'quiz_by_lesson_prompt'
    else:
        back_callback = 'admin_manage_structure'
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_quiz_question_keyboard(options, question_id):
    keyboard = []
    shuffled_options = list(enumerate(options))
    random.shuffle(shuffled_options)
    for original_index, option_text in shuffled_options:
        callback_data = f'answer_{question_id}_{original_index}'
        keyboard.append([InlineKeyboardButton(option_text, callback_data=callback_data)])
    keyboard.append([InlineKeyboardButton("⏭️ تخطي السؤال", callback_data=f'skip_{question_id}')])
    return InlineKeyboardMarkup(keyboard)

def create_results_menu_keyboard(quiz_id):
    keyboard = [
        [InlineKeyboardButton("🔄 إعادة الاختبار", callback_data='menu_quiz')],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Integrated Info Menu Functions ---

def create_info_menu_keyboard():
    """Creates the info menu keyboard (moved from info_handlers.py)."""
    keyboard = [
        [InlineKeyboardButton("🧪 العناصر الكيميائية", callback_data='info_elements')],
        [InlineKeyboardButton("🔬 المركبات الكيميائية", callback_data='info_compounds')],
        [InlineKeyboardButton("📘 المفاهيم الكيميائية", callback_data='info_concepts')],
        [InlineKeyboardButton("📊 الجدول الدوري", callback_data='info_periodic_table')],
        [InlineKeyboardButton("🔢 الحسابات الكيميائية", callback_data='info_calculations')],
        [InlineKeyboardButton("🔗 الروابط الكيميائية", callback_data='info_bonds')],
        [InlineKeyboardButton("📜 أهم قوانين التحصيلي", callback_data='info_laws')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')],
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
        # Handle cases where this might be called unexpectedly (e.g., direct command)
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
        # Ensure the file exists in the root directory where bot.py runs
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

    if data == 'info_elements':
        return handle_info_elements(update, context)
    elif data == 'info_compounds':
        return handle_info_compounds(update, context)
    elif data == 'info_concepts':
        return handle_info_concepts(update, context)
    elif data == 'info_periodic_table':
        return handle_info_periodic_table(update, context)
    elif data == 'info_calculations':
        return handle_info_calculations(update, context)
    elif data == 'info_bonds':
        return handle_info_bonds(update, context)
    elif data == 'info_laws':
        return handle_info_laws(update, context)
    elif data == 'main_menu':
        # Go back to main menu - This will be handled by the main_menu_callback
        # We just need to return the MAIN_MENU state
        logger.info("Returning to MAIN_MENU from info menu.")
        # Edit the message to show the main menu *before* returning the state
        safe_edit_message_text(query, text="القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU
    else:
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_info_menu_keyboard())
        return INFO_MENU # Stay in info menu

# --- Timer Functions (Placeholder - Need implementation from original/previous versions) ---
def set_quiz_timer(context: CallbackContext, chat_id, user_id, quiz_id, duration_minutes):
    logger.warning("set_quiz_timer is a placeholder.")
    return None

def set_question_timer(context: CallbackContext, chat_id, user_id, quiz_id):
    logger.warning("set_question_timer is a placeholder.")
    return None

def end_quiz_timeout(context: CallbackContext):
    logger.warning("end_quiz_timeout is a placeholder.")

def question_timer_callback(context: CallbackContext):
    logger.warning("question_timer_callback is a placeholder.")

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
    logger.info(f"User {user_id} canceled operation.")

    # Remove timers (Placeholder logic, needs correct job names)
    # ... (timer removal logic) ...

    text = "تم إلغاء العملية الحالية. العودة إلى القائمة الرئيسية."
    keyboard = create_main_menu_keyboard(user_id)
    if update.message:
        update.message.reply_text(text, reply_markup=keyboard)
    elif update.callback_query:
        safe_edit_message_text(update.callback_query, text=text, reply_markup=keyboard)

    keys_to_clear = [k for k in context.user_data if k not in ["user_id"]]
    for key in keys_to_clear:
        del context.user_data[key]
    context.user_data['conversation_state'] = MAIN_MENU

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

    # Handle direct return to main_menu first
    if data == 'main_menu':
        safe_edit_message_text(query, text="القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU

    # Handle other main menu options
    if data == 'menu_info':
        # Call the integrated show_info_menu function
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
        about_text += "الإصدار: 1.2 (هيكل مدمج ومصحح)\n\n"
        about_text += "يهدف هذا البوت لمساعدتك في دراسة الكيمياء من خلال الاختبارات والمعلومات."
        safe_edit_message_text(query, text=about_text, reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU
    elif data == 'menu_admin':
        if is_admin(user_id):
            safe_edit_message_text(query, text="قائمة إدارة البوت:", reply_markup=create_admin_menu_keyboard())
            return ADMIN_MENU
        else:
            query.answer("ليس لديك صلاحيات الوصول لهذه القائمة.", show_alert=True)
            return MAIN_MENU
    else:
        logger.warning(f"Unexpected callback data '{data}' received in MAIN_MENU state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU

# Placeholder for quiz menu callback
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
        context.user_data['quiz_filter_id'] = None
        safe_edit_message_text(query, text="اختر مدة الاختبار العشوائي:", reply_markup=create_quiz_duration_keyboard())
        return SELECTING_QUIZ_DURATION
    # ... (other quiz types need implementation) ...
    else:
        logger.warning(f"Unexpected callback data '{data}' in QUIZ_MENU state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

# Placeholder for selecting quiz duration
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
            # ... (Start quiz logic needed here) ...
            logger.info("Placeholder: Need to implement start_quiz function call here.")
            safe_edit_message_text(query, text=f"تم اختيار مدة الاختبار: {duration_minutes} دقيقة. (بدء الاختبار - قيد التطوير)")
            # return TAKING_QUIZ # Should return this after starting
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
    elif data == 'admin_manage_structure':
        safe_edit_message_text(query, text="إدارة الهيكل الدراسي:", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE
    # ... (other admin options need implementation) ...
    else:
        logger.warning(f"Unexpected callback data '{data}' in ADMIN_MENU state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU

# Placeholder for admin structure menu callback
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

    if data == 'menu_admin':
        safe_edit_message_text(query, text="قائمة إدارة البوت:", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU
    # ... (other structure options need implementation) ...
    else:
        logger.warning(f"Unexpected callback data '{data}' in ADMIN_MANAGE_STRUCTURE state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE

# --- Error Handler ---
def error_handler(update: Update, context: CallbackContext):
    logger.error(f"Update \"{update}\" caused error \"{context.error}\"", exc_info=context.error)

# --- Main Function ---
def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # --- Conversation Handler Setup (Integrated Structure) ---
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MAIN_MENU: [
                # Use a more specific pattern for main menu options
                CallbackQueryHandler(main_menu_callback, pattern='^menu_')
            ],
            QUIZ_MENU: [
                CallbackQueryHandler(quiz_menu_callback, pattern='^quiz_'),
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$') # Back button
            ],
            ADMIN_MENU: [
                CallbackQueryHandler(admin_menu_callback, pattern='^admin_'),
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$') # Back button
            ],
            SELECTING_QUIZ_DURATION: [
                CallbackQueryHandler(select_quiz_duration_callback, pattern='^quiz_duration_'),
                CallbackQueryHandler(quiz_menu_callback, pattern='^menu_quiz$') # Back button
            ],
            ADMIN_MANAGE_STRUCTURE: [
                CallbackQueryHandler(admin_structure_menu_callback, pattern='^admin_manage_'),
                CallbackQueryHandler(admin_menu_callback, pattern='^menu_admin$') # Back button
            ],
            # --- Integrated INFO_MENU State ---
            INFO_MENU: [
                # Handles buttons within the info menu (e.g., info_elements, info_laws)
                CallbackQueryHandler(info_menu_callback, pattern='^info_'),
                # Handles the back button within the info menu
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$')
            ],
            # --- Add other states and their handlers here ---
            # e.g., TAKING_QUIZ, ADDING_QUESTION, etc.
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CommandHandler('start', start) # Allow restarting
        ],
        allow_reentry=True
    )

    dp.add_handler(conv_handler)
    dp.add_handler(CommandHandler('help', help_command))
    dp.add_error_handler(error_handler)

    # Start the Bot using Webhook for Render deployment
    if APP_NAME:
        logger.info(f"Starting webhook for Render app {APP_NAME}")
        webhook_path = "webhook" # Simple path
        webhook_url = f"https://{APP_NAME}.onrender.com/{webhook_path}"
        updater.start_webhook(listen="0.0.0.0",
                              port=PORT,
                              url_path=webhook_path,
                              webhook_url=webhook_url)
        logger.info(f"Webhook set to {webhook_url}")
    else:
        logger.info("Starting bot in polling mode (APP_NAME not set)")
        updater.start_polling()

    logger.info("Bot started and running...")
    updater.idle()

if __name__ == '__main__':
    main()

