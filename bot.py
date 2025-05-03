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
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO, # Keep INFO level for production
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG) # Uncomment this locally for more detailed debug logs if needed

# Get sensitive info from environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_USER_ID = os.environ.get("ADMIN_USER_ID", "6448526509") # Default if not set
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
    ELEMENTS, COMPOUNDS, CONCEPTS, PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO = {}, {}, {}, {}, {}, {}
    def process_text_with_chemical_notation(text): return text
    def format_chemical_equation(text): return text
    logger.info("Chemistry data and equation functions loaded (placeholders used).")
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
    setup_database() # Ensure tables exist
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
    SHOWING_INFO_CONTENT, # New state for showing info content
    SHOWING_REPORTS, # New state for showing reports
    SELECT_CHAPTER_FOR_LESSON_QUIZ,
    SHOWING_RESULTS # New state for showing quiz results
) = range(36) # Increased range for new states

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
        [InlineKeyboardButton("🔙 العودة لاختيار النوع", callback_data='menu_quiz')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_grade_levels_keyboard(for_quiz=False, context=None):
    grades = QUIZ_DB.get_all_grade_levels()
    keyboard = []
    if grades:
        for grade_id, grade_name in grades:
            callback_data = f'select_grade_quiz_{grade_id}' if for_quiz else f'admin_grade_{grade_id}'
            keyboard.append([InlineKeyboardButton(grade_name, callback_data=callback_data)])
    else:
        logger.info("No grade levels found in the database.")

    back_callback = 'menu_quiz' if for_quiz else 'admin_manage_structure'
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_chapters_keyboard(grade_level_id, for_quiz=False, for_lesson_selection=False, context=None):
    chapters = QUIZ_DB.get_chapters_by_grade(grade_level_id)
    keyboard = []
    if chapters:
        for chapter_id, chapter_name in chapters:
            if for_quiz:
                callback_data = f'select_chapter_quiz_{chapter_id}'
            elif for_lesson_selection:
                 callback_data = f'select_lesson_chapter_{chapter_id}'
            else: # Admin context
                callback_data = f'admin_chapter_{chapter_id}'
            keyboard.append([InlineKeyboardButton(chapter_name, callback_data=callback_data)])
    else:
        logger.info(f"No chapters found for grade level {grade_level_id}.")

    if for_quiz:
        back_callback = 'quiz_by_grade_prompt'
    elif for_lesson_selection:
        back_callback = 'quiz_by_grade_prompt'
    else: # Admin context
        back_callback = 'admin_manage_grades'

    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_lessons_keyboard(chapter_id, for_quiz=False, context=None):
    lessons = QUIZ_DB.get_lessons_by_chapter(chapter_id)
    keyboard = []
    if lessons:
        for lesson_id, lesson_name in lessons:
            callback_data = f'select_lesson_quiz_{lesson_id}' if for_quiz else f'admin_lesson_{lesson_id}'
            keyboard.append([InlineKeyboardButton(lesson_name, callback_data=callback_data)])
    else:
        logger.info(f"No lessons found for chapter {chapter_id}.")

    if for_quiz:
        # Need grade_level_id to go back correctly
        # Assuming it's stored in context.user_data['selected_grade_id']
        # If not, this back button might go to the wrong place
        back_callback = f'select_lesson_chapter_{chapter_id}' # Go back to chapter selection
    else: # Admin context
        back_callback = 'admin_manage_chapters'

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
    user = update.effective_user
    user_id = user.id
    username = user.username
    first_name = user.first_name
    last_name = user.last_name

    logger.info(f"User {user_id} ({get_user_name(user)}) started the bot.")

    # Add or update user in DB
    if QUIZ_DB:
        QUIZ_DB.add_or_update_user(user_id, username, first_name, last_name)

    welcome_message = f"أهلاً بك يا {get_user_name(user)} في بوت الكيمياء التعليمي!\n\n"
    welcome_message += "يمكنك استكشاف المعلومات الكيميائية أو بدء اختبار جديد.\n"
    welcome_message += "استخدم الأزرار أدناه للتنقل."

    reply_markup = create_main_menu_keyboard(user_id)
    safe_send_message(context.bot, chat_id=user_id, text=welcome_message, reply_markup=reply_markup)
    return MAIN_MENU

def handle_main_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    data = query.data

    logger.debug(f"handle_main_menu called with data: {data}")

    if data == 'menu_quiz':
        text = "اختر نوع الاختبار الذي تريده:"
        reply_markup = create_quiz_menu_keyboard()
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return QUIZ_MENU
    elif data == 'menu_admin':
        if is_admin(user_id):
            text = "⚙️ قائمة الإدارة:"
            reply_markup = create_admin_menu_keyboard()
            safe_edit_message_text(query, text=text, reply_markup=reply_markup)
            return ADMIN_MENU
        else:
            query.answer("عذراً، هذه القائمة متاحة للمشرف فقط.", show_alert=True)
            return MAIN_MENU
    elif data == 'menu_info':
        text = "📚 اختر الموضوع الذي تريد معرفة المزيد عنه:"
        reply_markup = create_info_menu_keyboard()
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return INFO_MENU
    elif data == 'menu_reports':
        show_user_reports(update, context)
        return SHOWING_REPORTS # Stay in a state to handle back button
    elif data == 'menu_about':
        text = ("*ℹ️ حول بوت الكيمياء التعليمي*\n\n"
                "هذا البوت مصمم لمساعدتك في تعلم الكيمياء من خلال الاختبارات والمعلومات المفيدة.\n"
                "- يمكنك اختيار اختبارات عشوائية أو حسب مستوى معين.\n"
                "- استكشف معلومات حول العناصر، المركبات، والمفاهيم الأساسية.\n"
                "- تابع تقدمك من خلال تقارير الأداء.\n\n"
                "تم تطويره بواسطة [اسم المطور/الفريق]. نتمنى لك تجربة تعليمية ممتعة!")
        reply_markup = create_back_button('main_menu')
        safe_edit_message_text(query, text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return MAIN_MENU # Or a dedicated ABOUT state if needed
    else:
        # Go back to main menu if unknown data
        text = "القائمة الرئيسية:"
        reply_markup = create_main_menu_keyboard(user_id)
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return MAIN_MENU

# --- Quiz Menu Handlers ---

def handle_quiz_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    data = query.data

    logger.debug(f"handle_quiz_menu called with data: {data}")

    if data == 'quiz_random_prompt':
        text = "اختر مدة الاختبار العشوائي:"
        reply_markup = create_quiz_duration_keyboard()
        context.user_data['quiz_type'] = 'random'
        context.user_data['quiz_filter'] = None
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return SELECTING_QUIZ_DURATION

    elif data == 'quiz_by_grade_prompt':
        text = "اختر المرحلة الدراسية:"
        reply_markup = create_grade_levels_keyboard(for_quiz=True, context=context)
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return SELECT_GRADE_LEVEL_FOR_QUIZ

    elif data == 'quiz_by_chapter_prompt':
        # First, ask for grade level
        text = "أولاً، اختر المرحلة الدراسية التي ينتمي إليها الفصل:"
        reply_markup = create_grade_levels_keyboard(for_quiz=True, context=context)
        context.user_data['quiz_selection_target'] = 'chapter'
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return SELECT_GRADE_LEVEL_FOR_QUIZ # Re-use grade selection state

    elif data == 'quiz_by_lesson_prompt':
        # First, ask for grade level
        text = "أولاً، اختر المرحلة الدراسية التي ينتمي إليها الدرس:"
        reply_markup = create_grade_levels_keyboard(for_quiz=True, context=context)
        context.user_data['quiz_selection_target'] = 'lesson'
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return SELECT_GRADE_LEVEL_FOR_QUIZ # Re-use grade selection state

    elif data == 'main_menu':
        text = "القائمة الرئيسية:"
        reply_markup = create_main_menu_keyboard(user_id)
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return MAIN_MENU
    else:
        # Unknown option, go back to quiz menu
        text = "اختر نوع الاختبار الذي تريده:"
        reply_markup = create_quiz_menu_keyboard()
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return QUIZ_MENU

# --- Quiz Selection Handlers (Grade, Chapter, Lesson) ---

def handle_select_grade_for_quiz(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    data = query.data
    logger.debug(f"handle_select_grade_for_quiz called with data: {data}")

    if data.startswith('select_grade_quiz_'):
        grade_id = int(data.split('_')[-1])
        context.user_data['selected_grade_id'] = grade_id
        selection_target = context.user_data.get('quiz_selection_target')

        if selection_target == 'chapter':
            text = "الآن، اختر الفصل:"
            reply_markup = create_chapters_keyboard(grade_id, for_quiz=True, context=context)
            safe_edit_message_text(query, text=text, reply_markup=reply_markup)
            return SELECT_CHAPTER_FOR_QUIZ
        elif selection_target == 'lesson':
            text = "الآن، اختر الفصل الذي ينتمي إليه الدرس:"
            reply_markup = create_chapters_keyboard(grade_id, for_lesson_selection=True, context=context)
            safe_edit_message_text(query, text=text, reply_markup=reply_markup)
            return SELECT_CHAPTER_FOR_LESSON_QUIZ # New state for selecting chapter before lesson
        else: # Direct quiz by grade
            context.user_data['quiz_type'] = 'grade'
            context.user_data['quiz_filter'] = grade_id
            text = "اختر مدة الاختبار لهذه المرحلة:"
            reply_markup = create_quiz_duration_keyboard()
            safe_edit_message_text(query, text=text, reply_markup=reply_markup)
            return SELECTING_QUIZ_DURATION

    elif data == 'menu_quiz': # Back button
        text = "اختر نوع الاختبار الذي تريده:"
        reply_markup = create_quiz_menu_keyboard()
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return QUIZ_MENU
    else:
        return SELECT_GRADE_LEVEL_FOR_QUIZ # Stay in state if invalid

def handle_select_chapter_for_quiz(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    data = query.data
    logger.debug(f"handle_select_chapter_for_quiz called with data: {data}")

    if data.startswith('select_chapter_quiz_'):
        chapter_id = int(data.split('_')[-1])
        context.user_data['quiz_type'] = 'chapter'
        context.user_data['quiz_filter'] = chapter_id
        text = "اختر مدة الاختبار لهذا الفصل:"
        reply_markup = create_quiz_duration_keyboard()
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return SELECTING_QUIZ_DURATION

    elif data == 'quiz_by_grade_prompt': # Back button
        text = "أولاً، اختر المرحلة الدراسية التي ينتمي إليها الفصل:"
        reply_markup = create_grade_levels_keyboard(for_quiz=True, context=context)
        context.user_data['quiz_selection_target'] = 'chapter'
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return SELECT_GRADE_LEVEL_FOR_QUIZ
    else:
        return SELECT_CHAPTER_FOR_QUIZ # Stay in state

def handle_select_chapter_for_lesson_quiz(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    data = query.data
    logger.debug(f"handle_select_chapter_for_lesson_quiz called with data: {data}")

    if data.startswith('select_lesson_chapter_'): # Changed prefix
        chapter_id = int(data.split('_')[-1])
        context.user_data['selected_chapter_id'] = chapter_id
        text = "الآن، اختر الدرس:"
        reply_markup = create_lessons_keyboard(chapter_id, for_quiz=True, context=context)
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return SELECT_LESSON_FOR_QUIZ

    elif data == 'quiz_by_grade_prompt': # Back button
        text = "أولاً، اختر المرحلة الدراسية التي ينتمي إليها الدرس:"
        reply_markup = create_grade_levels_keyboard(for_quiz=True, context=context)
        context.user_data['quiz_selection_target'] = 'lesson'
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return SELECT_GRADE_LEVEL_FOR_QUIZ
    else:
        return SELECT_CHAPTER_FOR_LESSON_QUIZ # Stay in state

def handle_select_lesson_for_quiz(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    data = query.data
    logger.debug(f"handle_select_lesson_for_quiz called with data: {data}")

    if data.startswith('select_lesson_quiz_'):
        lesson_id = int(data.split('_')[-1])
        context.user_data['quiz_type'] = 'lesson'
        context.user_data['quiz_filter'] = lesson_id
        text = "اختر مدة الاختبار لهذا الدرس:"
        reply_markup = create_quiz_duration_keyboard()
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return SELECTING_QUIZ_DURATION

    elif data.startswith('select_lesson_chapter_'): # Back button (goes back to chapter selection)
        chapter_id = int(data.split('_')[-1])
        grade_id = context.user_data.get('selected_grade_id')
        if grade_id:
            text = "الآن، اختر الفصل الذي ينتمي إليه الدرس:"
            reply_markup = create_chapters_keyboard(grade_id, for_lesson_selection=True, context=context)
            safe_edit_message_text(query, text=text, reply_markup=reply_markup)
            return SELECT_CHAPTER_FOR_LESSON_QUIZ
        else:
            # Fallback if grade_id is lost
            text = "حدث خطأ، يرجى البدء من جديد. اختر المرحلة الدراسية:"
            reply_markup = create_grade_levels_keyboard(for_quiz=True, context=context)
            context.user_data['quiz_selection_target'] = 'lesson'
            safe_edit_message_text(query, text=text, reply_markup=reply_markup)
            return SELECT_GRADE_LEVEL_FOR_QUIZ
    else:
        return SELECT_LESSON_FOR_QUIZ # Stay in state

# --- Quiz Duration and Start --- #

def handle_select_quiz_duration(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    query.answer()
    data = query.data

    logger.debug(f"handle_select_quiz_duration called with data: {data}")

    if data.startswith('quiz_duration_'):
        duration_minutes = int(data.split('_')[-1])
        quiz_type = context.user_data.get('quiz_type', 'random')
        quiz_filter = context.user_data.get('quiz_filter')

        logger.info(f"Starting quiz for user {user_id}: type={quiz_type}, filter={quiz_filter}, duration={duration_minutes}")
        safe_edit_message_text(query, text="⏳ جارٍ إعداد الاختبار...")

        # --- Start Quiz Logic ---
        logger.debug(f"Calling QUIZ_DB.get_questions with type={quiz_type}, filter={quiz_filter}, num_questions={DEFAULT_QUIZ_QUESTIONS}")
        try:
            if quiz_type == 'random':
                questions = QUIZ_DB.get_random_questions(DEFAULT_QUIZ_QUESTIONS)
            elif quiz_type == 'grade':
                questions = QUIZ_DB.get_questions_by_grade(quiz_filter, DEFAULT_QUIZ_QUESTIONS)
            elif quiz_type == 'chapter':
                questions = QUIZ_DB.get_questions_by_chapter(quiz_filter, DEFAULT_QUIZ_QUESTIONS)
            elif quiz_type == 'lesson':
                questions = QUIZ_DB.get_questions_by_lesson(quiz_filter, DEFAULT_QUIZ_QUESTIONS)
            else:
                questions = []
                logger.warning(f"Unknown quiz type: {quiz_type}")

            logger.debug(f"Retrieved {len(questions)} questions from DB.")
            if questions:
                logger.debug(f"First question data (first 50 chars): {str(questions[0])[:50]}...")
            else:
                logger.debug("No questions retrieved.")

        except Exception as e:
            logger.exception(f"Error fetching questions from DB: {e}")
            safe_send_message(context.bot, chat_id, text="حدث خطأ أثناء جلب الأسئلة من قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً.")
            # Go back to main menu on error
            text_main = "القائمة الرئيسية:"
            reply_markup_main = create_main_menu_keyboard(user_id)
            safe_send_message(context.bot, chat_id, text=text_main, reply_markup=reply_markup_main)
            return MAIN_MENU

        if not questions or len(questions) < 1: # Check if list is empty or None
            logger.warning(f"No questions found for quiz type '{quiz_type}' with filter '{quiz_filter}'.")
            safe_send_message(context.bot, chat_id, text="عذراً، لم يتم العثور على أسئلة كافية لهذا النوع من الاختبار في الوقت الحالي. يرجى المحاولة مرة أخرى لاحقاً أو اختيار نوع آخر.")
            # Go back to quiz menu
            text_quiz = "اختر نوع الاختبار الذي تريده:"
            reply_markup_quiz = create_quiz_menu_keyboard()
            safe_send_message(context.bot, chat_id, text=text_quiz, reply_markup=reply_markup_quiz)
            return QUIZ_MENU

        # Shuffle questions just in case DB didn't randomize
        random.shuffle(questions)

        # Store quiz data in user_data
        quiz_id = f"{user_id}_{int(time.time())}" # Simple unique ID
        quiz_data = {
            "quiz_id": quiz_id,
            "questions": questions,
            "answers": {},
            "current_question_index": 0,
            "start_time": time.time(),
            "duration_minutes": duration_minutes,
            "quiz_type": quiz_type,
            "quiz_filter": quiz_filter,
            "timed_out": False,
            "quiz_timer_job_name": None,
            "question_timer_job_name": None
        }
        context.user_data["current_quiz"] = quiz_data
        logger.debug(f"Quiz data stored for user {user_id}: {quiz_data}")

        # Set overall quiz timer
        quiz_timer_job = set_quiz_timer(context, chat_id, user_id, quiz_id, duration_minutes)
        if quiz_timer_job:
            quiz_data["quiz_timer_job_name"] = quiz_timer_job

        # Send the first question
        logger.debug("Calling send_question for the first question.")
        send_question(chat_id, user_id, quiz_id, 0, context)
        return TAKING_QUIZ

    elif data == 'menu_quiz': # Back button
        text = "اختر نوع الاختبار الذي تريده:"
        reply_markup = create_quiz_menu_keyboard()
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return QUIZ_MENU
    else:
        return SELECTING_QUIZ_DURATION # Stay in state

# --- Taking Quiz Handlers ---

def send_question(chat_id: int, user_id: int, quiz_id: str, question_index: int, context: CallbackContext):
    logger.debug(f"send_question called for chat={chat_id}, user={user_id}, quiz={quiz_id}, index={question_index}")
    quiz_data = context.user_data.get("current_quiz")

    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.warning(f"send_question: Quiz data mismatch or not found for quiz {quiz_id}")
        safe_send_message(context.bot, chat_id, text="حدث خطأ في بيانات الاختبار. يرجى البدء من جديد.")
        # Go back to main menu
        text_main = "القائمة الرئيسية:"
        reply_markup_main = create_main_menu_keyboard(user_id)
        safe_send_message(context.bot, chat_id, text=text_main, reply_markup=reply_markup_main)
        return MAIN_MENU # End conversation or go to main menu

    questions = quiz_data["questions"]
    total_questions = len(questions)

    if question_index >= total_questions:
        logger.info(f"Quiz {quiz_id} finished naturally after question {question_index-1}.")
        show_results(chat_id, user_id, quiz_id, context)
        return SHOWING_RESULTS # Go to results state

    question = questions[question_index]
    logger.debug(f"Preparing question {question_index}: {question}")

    # Ensure options are present and correctly formatted
    options = []
    option_keys = ['option1', 'option2', 'option3', 'option4']
    missing_options = False
    for key in option_keys:
        if key in question and question[key] is not None:
            options.append(question[key])
        else:
            logger.error(f"Missing or None value for {key} in question {question_index} (ID: {question.get('question_id')})")
            missing_options = True
            break # Stop processing if an option is missing

    if missing_options or len(options) != 4:
        logger.error(f"Incorrect number of options ({len(options)}) or missing options for question {question_index} (ID: {question.get('question_id')}). Skipping question.")
        safe_send_message(context.bot, chat_id, text=f"حدث خطأ في تنسيق السؤال {question_index + 1}. سيتم تخطيه.")
        # Record as skipped/error in answers?
        quiz_data["answers"][question_index] = {"selected": -2, "correct": question.get('correct_answer', -1), "time": time.time()} # -2 indicates format error
        quiz_data["current_question_index"] += 1
        # Send next question immediately
        send_question(chat_id, user_id, quiz_id, quiz_data["current_question_index"], context)
        return TAKING_QUIZ

    # Shuffle options and store the original correct index mapping
    original_indices = list(range(4))
    shuffled_options_with_indices = list(zip(options, original_indices))
    random.shuffle(shuffled_options_with_indices)
    shuffled_options, shuffled_original_indices = zip(*shuffled_options_with_indices)

    # Find the new index of the originally correct option
    original_correct_index = question.get('correct_answer', -1) # 0-based index from DB
    if original_correct_index == -1:
         logger.error(f"Missing correct_answer for question {question_index} (ID: {question.get('question_id')}). Skipping.")
         safe_send_message(context.bot, chat_id, text=f"حدث خطأ في تحديد الإجابة الصحيحة للسؤال {question_index + 1}. سيتم تخطيه.")
         quiz_data["answers"][question_index] = {"selected": -2, "correct": -1, "time": time.time()}
         quiz_data["current_question_index"] += 1
         send_question(chat_id, user_id, quiz_id, quiz_data["current_question_index"], context)
         return TAKING_QUIZ

    try:
        new_correct_index = shuffled_original_indices.index(original_correct_index)
    except ValueError:
        logger.error(f"Could not find original correct index {original_correct_index} in shuffled indices {shuffled_original_indices} for question {question_index}. Skipping.")
        safe_send_message(context.bot, chat_id, text=f"حدث خطأ في ترتيب خيارات السؤال {question_index + 1}. سيتم تخطيه.")
        quiz_data["answers"][question_index] = {"selected": -2, "correct": original_correct_index, "time": time.time()}
        quiz_data["current_question_index"] += 1
        send_question(chat_id, user_id, quiz_id, quiz_data["current_question_index"], context)
        return TAKING_QUIZ

    # Store the shuffled correct index for checking later
    quiz_data["current_correct_index"] = new_correct_index
    quiz_data["current_question_start_time"] = time.time()

    # Build question text and keyboard
    question_text = f"*السؤال {question_index + 1} من {total_questions}:*\n\n{process_text_with_chemical_notation(question['question_text'])}"

    keyboard = [
        [InlineKeyboardButton(f"1. {process_text_with_chemical_notation(shuffled_options[0])}", callback_data=f'quiz_answer_{quiz_id}_{question_index}_0')],
        [InlineKeyboardButton(f"2. {process_text_with_chemical_notation(shuffled_options[1])}", callback_data=f'quiz_answer_{quiz_id}_{question_index}_1')],
        [InlineKeyboardButton(f"3. {process_text_with_chemical_notation(shuffled_options[2])}", callback_data=f'quiz_answer_{quiz_id}_{question_index}_2')],
        [InlineKeyboardButton(f"4. {process_text_with_chemical_notation(shuffled_options[3])}", callback_data=f'quiz_answer_{quiz_id}_{question_index}_3')],
        [InlineKeyboardButton("⏭️ تخطي السؤال", callback_data=f'quiz_skip_{quiz_id}_{question_index}')],
        [InlineKeyboardButton("🛑 إنهاء الاختبار", callback_data=f'quiz_cancel_{quiz_id}')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send message with or without image
    image_url = question.get('image_url')
    sent_message = None
    try:
        if image_url:
            logger.debug(f"Sending question {question_index} with image: {image_url}")
            # Send photo first, then text with keyboard
            # sent_photo = context.bot.send_photo(chat_id=chat_id, photo=image_url)
            # sent_message = safe_send_message(context.bot, chat_id=chat_id, text=question_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            # Alternative: Send as media group (might not work well with long text)
            # Or send photo with caption
            sent_message = context.bot.send_photo(chat_id=chat_id, photo=image_url, caption=question_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            logger.debug(f"Sending question {question_index} without image.")
            sent_message = safe_send_message(context.bot, chat_id=chat_id, text=question_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

        if sent_message:
            quiz_data["last_question_message_id"] = sent_message.message_id
            logger.debug(f"Stored last_question_message_id: {sent_message.message_id}")
        else:
            logger.error(f"Failed to send question {question_index} message.")
            # Attempt to cancel quiz if message fails?

    except BadRequest as e:
        logger.error(f"BadRequest sending question {question_index}: {e}. Text length: {len(question_text)}")
        # Try sending without markdown if it's a formatting issue
        try:
            if image_url:
                 sent_message = context.bot.send_photo(chat_id=chat_id, photo=image_url, caption=question_text, reply_markup=reply_markup)
            else:
                 sent_message = safe_send_message(context.bot, chat_id=chat_id, text=question_text, reply_markup=reply_markup)
            if sent_message:
                quiz_data["last_question_message_id"] = sent_message.message_id
        except Exception as inner_e:
            logger.error(f"Failed to send question {question_index} even without markdown: {inner_e}")
            safe_send_message(context.bot, chat_id, text="حدث خطأ أثناء إرسال السؤال. سيتم إلغاء الاختبار.")
            handle_quiz_cancel(update, context, quiz_id_override=quiz_id)
            return ConversationHandler.END # Or back to main menu
    except Exception as e:
        logger.exception(f"Unexpected error sending question {question_index}: {e}")
        safe_send_message(context.bot, chat_id, text="حدث خطأ غير متوقع أثناء إرسال السؤال. سيتم إلغاء الاختبار.")
        handle_quiz_cancel(update, context, quiz_id_override=quiz_id)
        return ConversationHandler.END # Or back to main menu

    # Set question timer if enabled
    question_timer_job = set_question_timer(context, chat_id, user_id, quiz_id, question_index)
    if question_timer_job:
        quiz_data["question_timer_job_name"] = question_timer_job

    return TAKING_QUIZ

def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    query.answer() # Acknowledge button press
    data = query.data

    logger.debug(f"handle_quiz_answer called with data: {data}")

    try:
        _, quiz_id, question_index_str, selected_option_index_str = data.split('_')
        question_index = int(question_index_str)
        selected_option_index = int(selected_option_index_str)
    except ValueError:
        logger.error(f"Invalid callback data format in handle_quiz_answer: {data}")
        return TAKING_QUIZ # Stay in state, maybe send an error message?

    quiz_data = context.user_data.get("current_quiz")

    # --- Input Validation ---
    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.warning(f"Received answer for inactive/mismatched quiz {quiz_id}. Current quiz: {quiz_data.get('quiz_id') if quiz_data else 'None'}")
        safe_edit_message_text(query, text="هذا الاختبار لم يعد نشطاً.", reply_markup=None)
        return TAKING_QUIZ # Or end conversation?

    if question_index != quiz_data["current_question_index"]:
        logger.warning(f"Received answer for wrong question index {question_index}. Expected: {quiz_data['current_question_index']}")
        # Ignore or notify user? For now, ignore.
        return TAKING_QUIZ

    if quiz_data.get("timed_out"):
        logger.info(f"Received answer for quiz {quiz_id} after it timed out. Ignoring.")
        safe_edit_message_text(query, text="انتهى وقت هذا الاختبار.", reply_markup=None)
        return TAKING_QUIZ

    # --- Process Answer --- #
    logger.info(f"User {user_id} answered question {question_index} with option {selected_option_index} for quiz {quiz_id}.")

    # Remove question timer
    if quiz_data.get("question_timer_job_name"):
        remove_job_if_exists(quiz_data["question_timer_job_name"], context)
        quiz_data["question_timer_job_name"] = None

    correct_answer_index = quiz_data.get("current_correct_index", -1)
    is_correct = (selected_option_index == correct_answer_index)
    question = quiz_data["questions"][question_index]

    # Store answer
    quiz_data["answers"][question_index] = {"selected": selected_option_index, "correct": correct_answer_index, "time": time.time()}

    # Provide feedback
    feedback_text = "✅ إجابة صحيحة!" if is_correct else "❌ إجابة خاطئة."
    if not is_correct and question.get('explanation'):
        feedback_text += f"\n\n*الشرح:*\n{process_text_with_chemical_notation(question['explanation'])}"
    elif not is_correct:
         # Show the correct option text if no explanation
         try:
             correct_option_text = question[f'option{correct_answer_index + 1}'] # Assumes options are stored like this in the original question dict
             feedback_text += f"\n\n*الإجابة الصحيحة:* {process_text_with_chemical_notation(correct_option_text)}"
         except KeyError:
             logger.error(f"Could not find correct option text for question {question_index} when showing feedback.")

    # Edit the original question message to show feedback and remove buttons
    try:
        logger.debug(f"Editing message {quiz_data.get('last_question_message_id')} to show feedback.")
        # Rebuild the original question text to keep it
        original_question_text = f"*السؤال {question_index + 1} من {len(quiz_data['questions'])}:*\n\n{process_text_with_chemical_notation(question['question_text'])}"
        full_feedback_text = f"{original_question_text}\n\n---\n{feedback_text}"

        if query.message.photo:
            # Edit caption if it was a photo message
            context.bot.edit_message_caption(
                chat_id=chat_id,
                message_id=query.message.message_id,
                caption=full_feedback_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=None # Remove keyboard
            )
        else:
            # Edit text if it was a text message
            safe_edit_message_text(query, text=full_feedback_text, reply_markup=None, parse_mode=ParseMode.MARKDOWN)

    except BadRequest as e:
        logger.error(f"BadRequest editing message for feedback: {e}. Feedback text length: {len(full_feedback_text)}")
        # Fallback: Send feedback as a new message
        safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.exception(f"Error editing message for feedback: {e}")
        # Fallback: Send feedback as a new message
        safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)

    # Move to the next question after a delay
    quiz_data["current_question_index"] += 1
    next_question_index = quiz_data["current_question_index"]

    # Schedule sending the next question
    context.job_queue.run_once(
        send_next_question_job,
        FEEDBACK_DELAY,
        context={"chat_id": chat_id, "user_id": user_id, "quiz_id": quiz_id, "next_index": next_question_index},
        name=f"next_q_{quiz_id}_{next_question_index}"
    )

    return TAKING_QUIZ

def send_next_question_job(context: CallbackContext):
    job_context = context.job.context
    chat_id = job_context["chat_id"]
    user_id = job_context["user_id"]
    quiz_id = job_context["quiz_id"]
    next_index = job_context["next_index"]

    # Check if quiz is still active and index matches
    user_data = context.dispatcher.user_data.get(user_id, {})
    quiz_data = user_data.get("current_quiz")

    if quiz_data and quiz_data["quiz_id"] == quiz_id and quiz_data["current_question_index"] == next_index and not quiz_data.get("timed_out"):
        logger.debug(f"Job executing: Sending question {next_index} for quiz {quiz_id}")
        send_question(chat_id, user_id, quiz_id, next_index, context)
    else:
        logger.info(f"Job skipped: Quiz {quiz_id} inactive, index mismatch, or timed out before sending question {next_index}.")

def handle_quiz_skip(update: Update, context: CallbackContext, timed_out=False, quiz_id_override=None) -> int:
    query = update.callback_query if update.callback_query else None
    user_id = query.from_user.id if query else context.job.context["user_id"]
    chat_id = query.message.chat_id if query else context.job.context["chat_id"]
    if query:
        query.answer()
        data = query.data
        logger.debug(f"handle_quiz_skip called with data: {data}")
        try:
            _, quiz_id, question_index_str = data.split('_')
            question_index = int(question_index_str)
        except ValueError:
            logger.error(f"Invalid callback data format in handle_quiz_skip: {data}")
            return TAKING_QUIZ
    else: # Called from timer
        quiz_id = quiz_id_override if quiz_id_override else context.job.context["quiz_id"]
        question_index = context.job.context["question_index"]
        logger.debug(f"handle_quiz_skip called from timer for quiz {quiz_id}, question {question_index}")

    quiz_data = context.user_data.get("current_quiz")

    # --- Input Validation ---
    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.warning(f"Received skip for inactive/mismatched quiz {quiz_id}.")
        if query: safe_edit_message_text(query, text="هذا الاختبار لم يعد نشطاً.", reply_markup=None)
        return TAKING_QUIZ

    if question_index != quiz_data["current_question_index"]:
        logger.warning(f"Received skip for wrong question index {question_index}. Expected: {quiz_data['current_question_index']}")
        return TAKING_QUIZ

    if quiz_data.get("timed_out") and not timed_out: # Don't log if skip is *because* of timeout
        logger.info(f"Received skip for quiz {quiz_id} after it timed out. Ignoring.")
        if query: safe_edit_message_text(query, text="انتهى وقت هذا الاختبار.", reply_markup=None)
        return TAKING_QUIZ

    # --- Process Skip --- #
    logger.info(f"User {user_id} skipped question {question_index} for quiz {quiz_id}. Timed out: {timed_out}")

    # Remove question timer
    if quiz_data.get("question_timer_job_name"):
        remove_job_if_exists(quiz_data["question_timer_job_name"], context)
        quiz_data["question_timer_job_name"] = None

    correct_answer_index = quiz_data.get("current_correct_index", -1)
    question = quiz_data["questions"][question_index]

    # Store as skipped (-1)
    quiz_data["answers"][question_index] = {"selected": -1, "correct": correct_answer_index, "time": time.time()}

    # Provide feedback (explanation only)
    feedback_text = "⏭️ تم تخطي السؤال."
    if question.get('explanation'):
        feedback_text += f"\n\n*الشرح:*\n{process_text_with_chemical_notation(question['explanation'])}"
    else:
         # Show the correct option text if no explanation
         try:
             correct_option_text = question[f'option{correct_answer_index + 1}']
             feedback_text += f"\n\n*الإجابة الصحيحة كانت:* {process_text_with_chemical_notation(correct_option_text)}"
         except KeyError:
             logger.error(f"Could not find correct option text for question {question_index} when showing skip feedback.")

    # Edit the original question message
    if query: # Only edit if triggered by button press
        try:
            logger.debug(f"Editing message {quiz_data.get('last_question_message_id')} to show skip feedback.")
            original_question_text = f"*السؤال {question_index + 1} من {len(quiz_data['questions'])}:*\n\n{process_text_with_chemical_notation(question['question_text'])}"
            full_feedback_text = f"{original_question_text}\n\n---\n{feedback_text}"

            if query.message.photo:
                context.bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=query.message.message_id,
                    caption=full_feedback_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=None
                )
            else:
                safe_edit_message_text(query, text=full_feedback_text, reply_markup=None, parse_mode=ParseMode.MARKDOWN)
        except BadRequest as e:
            logger.error(f"BadRequest editing message for skip feedback: {e}. Feedback text length: {len(full_feedback_text)}")
            safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.exception(f"Error editing message for skip feedback: {e}")
            safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)
    else: # If timed out, just send feedback as new message
         safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)

    # Move to the next question after a delay
    quiz_data["current_question_index"] += 1
    next_question_index = quiz_data["current_question_index"]

    context.job_queue.run_once(
        send_next_question_job,
        FEEDBACK_DELAY,
        context={"chat_id": chat_id, "user_id": user_id, "quiz_id": quiz_id, "next_index": next_question_index},
        name=f"next_q_{quiz_id}_{next_question_index}"
    )

    return TAKING_QUIZ

def handle_quiz_cancel(update: Update, context: CallbackContext, quiz_id_override=None) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    query.answer()
    data = query.data

    logger.debug(f"handle_quiz_cancel called with data: {data}")

    try:
        if quiz_id_override:
            quiz_id = quiz_id_override
        else:
            _, quiz_id = data.split('_')
    except ValueError:
        logger.error(f"Invalid callback data format in handle_quiz_cancel: {data}")
        return TAKING_QUIZ

    quiz_data = context.user_data.get("current_quiz")

    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.warning(f"Received cancel for inactive/mismatched quiz {quiz_id}.")
        safe_edit_message_text(query, text="هذا الاختبار لم يعد نشطاً أو تم إلغاؤه بالفعل.", reply_markup=None)
        return TAKING_QUIZ # Or end?

    logger.info(f"User {user_id} cancelled quiz {quiz_id}.")

    # Clean up timers
    if quiz_data.get("quiz_timer_job_name"):
        remove_job_if_exists(quiz_data["quiz_timer_job_name"], context)
    if quiz_data.get("question_timer_job_name"):
        remove_job_if_exists(quiz_data["question_timer_job_name"], context)

    # Clear quiz data
    context.user_data.pop("current_quiz", None)

    safe_edit_message_text(query, text="🛑 تم إلغاء الاختبار.", reply_markup=None)

    # Send main menu again
    text_main = "القائمة الرئيسية:"
    reply_markup_main = create_main_menu_keyboard(user_id)
    safe_send_message(context.bot, chat_id, text=text_main, reply_markup=reply_markup_main)
    return MAIN_MENU

# --- Show Results --- #

def show_results(chat_id: int, user_id: int, quiz_id: str, context: CallbackContext, timed_out=False):
    logger.info(f"Showing results for quiz {quiz_id} for user {user_id}. Timed out: {timed_out}")
    quiz_data = context.user_data.get("current_quiz")

    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.warning(f"show_results: Quiz data mismatch or not found for quiz {quiz_id}")
        safe_send_message(context.bot, chat_id, text="حدث خطأ في عرض النتائج. بيانات الاختبار غير موجودة.")
        # Go back to main menu
        text_main = "القائمة الرئيسية:"
        reply_markup_main = create_main_menu_keyboard(user_id)
        safe_send_message(context.bot, chat_id, text=text_main, reply_markup=reply_markup_main)
        return MAIN_MENU

    # Clean up timers immediately
    if quiz_data.get("quiz_timer_job_name"):
        remove_job_if_exists(quiz_data["quiz_timer_job_name"], context)
    if quiz_data.get("question_timer_job_name"):
        remove_job_if_exists(quiz_data["question_timer_job_name"], context)

    questions = quiz_data["questions"]
    answers = quiz_data["answers"]
    start_time = quiz_data["start_time"]
    end_time = time.time()
    duration_seconds = int(end_time - start_time)
    minutes, seconds = divmod(duration_seconds, 60)
    duration_str = f"{minutes} د {seconds} ث"

    total_questions = len(questions)
    correct_answers = 0
    skipped_answers = 0
    incorrect_answers = 0

    for i in range(total_questions):
        answer_info = answers.get(i)
        if answer_info:
            selected = answer_info["selected"]
            correct = answer_info["correct"]
            if selected == correct:
                correct_answers += 1
            elif selected == -1: # Skipped
                skipped_answers += 1
            elif selected == -2: # Format error
                # Treat as skipped or incorrect? Let's say skipped for now.
                skipped_answers += 1
            else:
                incorrect_answers += 1
        else:
            # Question was not answered (e.g., quiz ended early)
            skipped_answers += 1

    # Ensure we account for all questions
    answered_count = correct_answers + incorrect_answers
    # skipped_answers = total_questions - answered_count # Recalculate skipped based on total

    score_percentage = (correct_answers / total_questions * 100) if total_questions > 0 else 0

    # Save results to DB
    if QUIZ_DB:
        try:
            QUIZ_DB.save_quiz_result(
                user_id=user_id,
                quiz_type=quiz_data["quiz_type"],
                quiz_filter=quiz_data.get("quiz_filter"), # Can be None
                total_questions=total_questions,
                correct_answers=correct_answers,
                duration_seconds=duration_seconds,
                score_percentage=score_percentage
            )
            logger.info(f"Saved quiz result for user {user_id}, quiz {quiz_id}")
        except Exception as e:
            logger.exception(f"Failed to save quiz result for user {user_id}: {e}")

    # Build result message
    result_message = f"🏁 *نتيجة الاختبار* 🏁\n\n"
    if timed_out:
        result_message += "⏰ انتهى وقت الاختبار!\n"
    result_message += f"🔢 إجمالي الأسئلة: {total_questions}\n"
    result_message += f"✅ الإجابات الصحيحة: {correct_answers}\n"
    result_message += f"❌ الإجابات الخاطئة: {incorrect_answers}\n"
    result_message += f"⏭️ الأسئلة المتخطاة/غير المجابة: {skipped_answers}\n"
    result_message += f"⏱️ الوقت المستغرق: {duration_str}\n"
    result_message += f"🎯 النسبة المئوية: {score_percentage:.1f}%\n\n"

    # Add a concluding remark based on score
    if score_percentage >= 90:
        result_message += "🎉 ممتاز! أداء رائع!"
    elif score_percentage >= 70:
        result_message += "👍 جيد جداً! استمر في التقدم!"
    elif score_percentage >= 50:
        result_message += "🙂 لا بأس، يمكنك التحسن في المرة القادمة!"
    else:
        result_message += "💪 لا تستسلم! حاول مرة أخرى وركز أكثر."

    # Clear quiz data *after* processing results
    context.user_data.pop("current_quiz", None)
    logger.debug(f"Cleared current_quiz data for user {user_id}")

    # Send results and main menu button
    reply_markup = create_back_button('main_menu')
    safe_send_message(context.bot, chat_id, text=result_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    return SHOWING_RESULTS # Stay in this state to handle back button

# --- Info Menu Handlers ---

def handle_info_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    data = query.data

    logger.debug(f"handle_info_menu called with data: {data}")

    info_content = ""
    info_title = ""

    if data == 'info_periodic_table':
        info_title = "⚛️ الجدول الدوري"
        info_content = PERIODIC_TABLE_INFO.get('description', 'لا توجد معلومات متاحة حالياً.')
        # Potentially add image or link later
    elif data == 'info_compounds':
        info_title = "🧪 المركبات الشائعة"
        info_content = COMPOUNDS.get('list', 'لا توجد معلومات متاحة حالياً.') # Assuming COMPOUNDS is a dict
    elif data == 'info_concepts':
        info_title = "💡 المفاهيم الأساسية"
        info_content = CONCEPTS.get('overview', 'لا توجد معلومات متاحة حالياً.') # Assuming CONCEPTS is a dict
    elif data == 'info_calculations':
        info_title = "🔢 الحسابات الكيميائية"
        info_content = CHEMICAL_CALCULATIONS_INFO.get('summary', 'لا توجد معلومات متاحة حالياً.')
    elif data == 'info_bonds':
        info_title = "🔗 الروابط الكيميائية"
        info_content = CHEMICAL_BONDS_INFO.get('types', 'لا توجد معلومات متاحة حالياً.')
    elif data == 'main_menu':
        text = "القائمة الرئيسية:"
        reply_markup = create_main_menu_keyboard(user_id)
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return MAIN_MENU
    else:
        # Unknown option, go back to info menu
        text = "📚 اختر الموضوع الذي تريد معرفة المزيد عنه:"
        reply_markup = create_info_menu_keyboard()
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return INFO_MENU

    if info_content:
        # Format the message
        message_text = f"*{info_title}*\n\n{process_text_with_chemical_notation(info_content)}"
        reply_markup = create_back_button('menu_info') # Back to info menu
        safe_edit_message_text(query, text=message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return SHOWING_INFO_CONTENT # Stay in a state to handle back button
    else:
        # Should not happen if default text is set
        query.answer("عذراً، حدث خطأ.")
        return INFO_MENU

# --- Reports Handler ---

def show_user_reports(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()

    logger.info(f"Fetching reports for user {user_id}")

    if not QUIZ_DB:
        safe_edit_message_text(query, text="عذراً، لا يمكن الوصول إلى قاعدة البيانات لعرض التقارير.", reply_markup=create_back_button('main_menu'))
        return SHOWING_REPORTS

    try:
        overall_stats = QUIZ_DB.get_user_overall_stats(user_id)
        # stats_by_type = QUIZ_DB.get_user_stats_by_type(user_id)
        last_quizzes = QUIZ_DB.get_user_last_quizzes(user_id, limit=5)

        text = "📊 *تقارير أدائك في الاختبارات:*\n\n"

        if overall_stats and overall_stats['total_quizzes'] > 0:
            # Format overall stats from the raw dictionary returned by DB function
            avg_time_int = int(overall_stats['avg_time']) if overall_stats['avg_time'] is not None else 0
            avg_minutes, avg_seconds = divmod(avg_time_int, 60)
            avg_time_str = f"{avg_minutes} د {avg_seconds} ث"
            avg_percentage = round(overall_stats['avg_percentage'], 1) if overall_stats['avg_percentage'] is not None else 0.0

            text += f"*📊 ملخص عام:*\n"
            text += f"- إجمالي الاختبارات: {overall_stats['total_quizzes']}\n"
            text += f"- متوسط النسبة المئوية: {avg_percentage}%\n"
            text += f"- متوسط وقت الاختبار: {avg_time_str}\n\n"
        else:
            text += "لم تكمل أي اختبارات بعد.\n\n"

        # Display last 5 quizzes
        if last_quizzes:
            text += "*📅 آخر 5 اختبارات:*\n"
            for q in last_quizzes:
                quiz_type_ar = {
                    'random': 'عشوائي',
                    'grade': 'مرحلة',
                    'chapter': 'فصل',
                    'lesson': 'درس'
                }.get(q['quiz_type'], q['quiz_type']) # Default to original if unknown

                # Format timestamp
                timestamp_dt = q['timestamp']
                # Adjust for local timezone if needed, assuming UTC for now
                timestamp_str = timestamp_dt.strftime("%Y-%m-%d %H:%M") # Example format

                duration_int = int(q['duration_seconds']) if q['duration_seconds'] is not None else 0
                q_minutes, q_seconds = divmod(duration_int, 60)
                q_duration_str = f"{q_minutes} د {q_seconds} ث"
                q_percentage = round(q['score_percentage'], 1) if q['score_percentage'] is not None else 0.0

                text += f"- {timestamp_str}: {quiz_type_ar} ({q['correct_answers']}/{q['total_questions']}) - {q_percentage}% - {q_duration_str}\n"
            text += "\n"
        else:
            text += "لا توجد سجلات لاختبارات سابقة.\n\n"

        # Add stats by type if implemented
        # if stats_by_type:
        #     text += "*📈 الأداء حسب النوع:*\n""        #     for type_stat in stats_by_type:
        #         # Format and add stats by type
        #         pass

        reply_markup = create_back_button('main_menu')
        safe_edit_message_text(query, text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.exception(f"Error fetching or formatting reports for user {user_id}: {e}")
        safe_edit_message_text(query, text="حدث خطأ أثناء جلب التقارير.", reply_markup=create_back_button('main_menu'))

    return SHOWING_REPORTS # Stay in state

# --- Admin Handlers (Placeholders/Simplified) ---

def handle_admin_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    data = query.data

    logger.debug(f"handle_admin_menu called with data: {data}")

    if not is_admin(user_id):
        query.answer(" وصول غير مصرح به!", show_alert=True)
        # Go back to main menu
        text = "القائمة الرئيسية:"
        reply_markup = create_main_menu_keyboard(user_id)
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return MAIN_MENU

    if data == 'admin_add_question':
        safe_edit_message_text(query, text="🚧 ميزة إضافة الأسئلة قيد التطوير.")
        # Placeholder: return ADDING_QUESTION
        return ADMIN_MENU # Stay in admin menu for now
    elif data == 'admin_delete_question':
        safe_edit_message_text(query, text="🚧 ميزة حذف الأسئلة قيد التطوير.")
        # Placeholder: return DELETING_QUESTION
        return ADMIN_MENU
    elif data == 'admin_show_question':
        safe_edit_message_text(query, text="🚧 ميزة عرض الأسئلة قيد التطوير.")
        # Placeholder: return SHOWING_QUESTION
        return ADMIN_MENU
    elif data == 'admin_manage_structure':
        text = "🏫 إدارة المراحل والفصول والدروس:"
        reply_markup = create_structure_admin_menu_keyboard()
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return ADMIN_MANAGE_STRUCTURE
    elif data == 'main_menu':
        text = "القائمة الرئيسية:"
        reply_markup = create_main_menu_keyboard(user_id)
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return MAIN_MENU
    else:
        return ADMIN_MENU # Stay in admin menu

def handle_admin_structure_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    data = query.data
    logger.debug(f"handle_admin_structure_menu called with data: {data}")

    if not is_admin(user_id):
        query.answer(" وصول غير مصرح به!", show_alert=True)
        return MAIN_MENU

    if data == 'admin_manage_grades':
        safe_edit_message_text(query, text="🚧 إدارة المراحل الدراسية قيد التطوير.", reply_markup=create_back_button('admin_manage_structure'))
        return ADMIN_MANAGE_GRADES
    elif data == 'admin_manage_chapters':
        safe_edit_message_text(query, text="🚧 إدارة الفصول قيد التطوير.", reply_markup=create_back_button('admin_manage_structure'))
        return ADMIN_MANAGE_CHAPTERS
    elif data == 'admin_manage_lessons':
        safe_edit_message_text(query, text="🚧 إدارة الدروس قيد التطوير.", reply_markup=create_back_button('admin_manage_structure'))
        return ADMIN_MANAGE_LESSONS
    elif data == 'menu_admin':
        text = "⚙️ قائمة الإدارة:"
        reply_markup = create_admin_menu_keyboard()
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return ADMIN_MENU
    else:
        return ADMIN_MANAGE_STRUCTURE

# --- Fallback and Error Handlers ---

def handle_unknown_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    logger.warning(f"Unhandled callback query data: {query.data} from user {user_id}")
    query.answer("عذراً، هذا الخيار غير معروف أو غير نشط حالياً.")

    # Attempt to send main menu as a fallback
    try:
        text = "القائمة الرئيسية:"
        reply_markup = create_main_menu_keyboard(user_id)
        # Use send_message instead of edit if the original message might be gone
        safe_send_message(context.bot, chat_id=query.message.chat_id, text=text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error sending fallback main menu: {e}")

    return ConversationHandler.END # End conversation on unknown state/callback

def handle_unknown_message(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    logger.warning(f"Received unknown message type or text from user {user_id}: {update.message.text[:50]}...")
    safe_send_message(context.bot, chat_id=update.effective_chat.id, text="عذراً، لم أفهم طلبك. يرجى استخدام الأزرار أو الأوامر المتاحة.")
    # Optionally, resend the main menu
    # text = "القائمة الرئيسية:"
    # reply_markup = create_main_menu_keyboard(user_id)
    # safe_send_message(context.bot, chat_id=update.effective_chat.id, text=text, reply_markup=reply_markup)
    return ConversationHandler.END # Or return current state if applicable

def error_handler(update: object, context: CallbackContext) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # Common error handling (you can expand this)
    if isinstance(context.error, BadRequest):
        # e.g., message is too long, chat not found, etc.
        logger.warning(f"Update {update} caused BadRequest error: {context.error}")
    elif isinstance(context.error, TimedOut):
        logger.warning(f"Network timeout error: {context.error}")
    elif isinstance(context.error, NetworkError):
        logger.warning(f"Other network error: {context.error}")
    elif isinstance(context.error, Unauthorized):
        # The user blocked the bot
        logger.info(f"User {update.effective_user.id if update and update.effective_user else 'N/A'} blocked the bot.")
        # You might want to remove user data here
    else:
        # Log other errors
        logger.exception(f"Unhandled error: {context.error}")

    # Optionally inform the user (be careful not to spam)
    # if update and update.effective_chat:
    #     safe_send_message(context.bot, chat_id=update.effective_chat.id, text="عذراً، حدث خطأ ما أثناء معالجة طلبك.")

# --- Main Function --- #

def main() -> None:
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN not found. Exiting.")
        return
    if not DATABASE_URL:
        logger.critical("DATABASE_URL not found. Exiting.")
        return
    if not APP_NAME:
        logger.critical("APP_NAME (for Render webhook) not found. Exiting.")
        return

    updater = Updater(BOT_TOKEN)
    dispatcher = updater.dispatcher

    # Conversation handler defines states and transitions
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MAIN_MENU: [CallbackQueryHandler(handle_main_menu)],
            QUIZ_MENU: [CallbackQueryHandler(handle_quiz_menu)],
            ADMIN_MENU: [CallbackQueryHandler(handle_admin_menu)],
            ADMIN_MANAGE_STRUCTURE: [CallbackQueryHandler(handle_admin_structure_menu)],
            SELECTING_QUIZ_DURATION: [CallbackQueryHandler(handle_select_quiz_duration)],
            SELECT_GRADE_LEVEL_FOR_QUIZ: [CallbackQueryHandler(handle_select_grade_for_quiz)],
            SELECT_CHAPTER_FOR_QUIZ: [CallbackQueryHandler(handle_select_chapter_for_quiz)],
            SELECT_CHAPTER_FOR_LESSON_QUIZ: [CallbackQueryHandler(handle_select_chapter_for_lesson_quiz)],
            SELECT_LESSON_FOR_QUIZ: [CallbackQueryHandler(handle_select_lesson_for_quiz)],
            TAKING_QUIZ: [
                CallbackQueryHandler(handle_quiz_answer, pattern='^quiz_answer_'),
                CallbackQueryHandler(handle_quiz_skip, pattern='^quiz_skip_'),
                CallbackQueryHandler(handle_quiz_cancel, pattern='^quiz_cancel_')
            ],
            SHOWING_RESULTS: [CallbackQueryHandler(handle_main_menu, pattern='^main_menu$')], # Back to main menu
            INFO_MENU: [CallbackQueryHandler(handle_info_menu)],
            SHOWING_INFO_CONTENT: [CallbackQueryHandler(handle_info_menu, pattern='^menu_info$')], # Back to info menu
            SHOWING_REPORTS: [CallbackQueryHandler(handle_main_menu, pattern='^main_menu$')], # Back to main menu
            # Add other admin states if/when implemented
            ADMIN_MANAGE_GRADES: [CallbackQueryHandler(handle_admin_structure_menu, pattern='^admin_manage_structure$')],
            ADMIN_MANAGE_CHAPTERS: [CallbackQueryHandler(handle_admin_structure_menu, pattern='^admin_manage_structure$')],
            ADMIN_MANAGE_LESSONS: [CallbackQueryHandler(handle_admin_structure_menu, pattern='^admin_manage_structure$')],
        },
        fallbacks=[
            CommandHandler('start', start), # Allow restarting
            CallbackQueryHandler(handle_unknown_callback), # Catch unknown button presses
            MessageHandler(filters.Filters.text & ~filters.Filters.command, handle_unknown_message) # Catch unknown text messages
        ],
        per_user=True,
        per_chat=True,
    )

    dispatcher.add_handler(conv_handler)
    dispatcher.add_error_handler(error_handler)

    # Start the Bot (Webhook for Render)
    webhook_url = f"https://{APP_NAME}.onrender.com/{BOT_TOKEN}"
    logger.info(f"Setting webhook to {webhook_url}")
    updater.start_webhook(listen="0.0.0.0",
                          port=PORT,
                          url_path=BOT_TOKEN,
                          webhook_url=webhook_url)

    logger.info("Bot started and running...")
    updater.idle()

if __name__ == '__main__':
    main()

