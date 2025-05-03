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
    if update.callback_query:
        safe_edit_message_text(update.callback_query.message, text=welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        safe_send_message(context.bot, chat_id=update.effective_chat.id, text=welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

    return MAIN_MENU

def about(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    about_text = ("هذا البوت مصمم لمساعدتك في تعلم الكيمياء من خلال الاختبارات والمعلومات المفيدة.\n"
                  "تم تطويره بواسطة [اسم المطور أو الفريق].\n\n"
                  "استخدم الأزرار للتنقل بين الأقسام.")
    reply_markup = create_back_button('main_menu')
    if update.callback_query:
        safe_edit_message_text(update.callback_query.message, text=about_text, reply_markup=reply_markup)
    else:
        safe_send_message(context.bot, chat_id=update.effective_chat.id, text=about_text, reply_markup=reply_markup)
    return MAIN_MENU # Stay in main menu context

def cancel(update: Update, context: CallbackContext) -> int:
    user = update.effective_user
    logger.info(f"User {user.id} cancelled the conversation.")
    safe_send_message(context.bot, chat_id=update.effective_chat.id, text="تم إلغاء العملية الحالية. العودة إلى القائمة الرئيسية.", reply_markup=ReplyKeyboardRemove())
    # Clean up any ongoing quiz data
    if 'current_quiz' in context.user_data:
        quiz_data = context.user_data['current_quiz']
        if quiz_data.get('quiz_timer_job_name'):
            remove_job_if_exists(quiz_data['quiz_timer_job_name'], context)
        if quiz_data.get('question_timer_job_name'):
            remove_job_if_exists(quiz_data['question_timer_job_name'], context)
        del context.user_data['current_quiz']
    # Clean up admin data if any
    admin_keys = ['question_to_add', 'question_to_delete_id']
    for key in admin_keys:
        if key in context.user_data:
            del context.user_data[key]

    return start(update, context) # Go back to start menu

# --- Menu Navigation Handlers ---

def handle_menu_button(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    data = query.data

    logger.info(f"User {user_id} pressed menu button: {data}")

    if data == 'main_menu':
        return start(update, context)
    elif data == 'menu_quiz':
        reply_markup = create_quiz_menu_keyboard()
        safe_edit_message_text(query.message, text="اختر نوع الاختبار الذي تريده:", reply_markup=reply_markup)
        return QUIZ_MENU
    elif data == 'menu_admin' and is_admin(user_id):
        reply_markup = create_admin_menu_keyboard()
        safe_edit_message_text(query.message, text="قائمة إدارة البوت:", reply_markup=reply_markup)
        return ADMIN_MENU
    elif data == 'menu_info':
        reply_markup = create_info_menu_keyboard()
        safe_edit_message_text(query.message, text="اختر الموضوع الذي تريد معرفة المزيد عنه:", reply_markup=reply_markup)
        return INFO_MENU
    elif data == 'menu_reports':
        return show_performance_reports(update, context)
    elif data == 'menu_about':
        return about(update, context)
    else:
        logger.warning(f"Unhandled menu button data: {data}")
        safe_edit_message_text(query.message, text="خيار غير معروف.")
        return MAIN_MENU # Go back to main menu safely

# --- Quiz Handling --- #

def prompt_quiz_duration(update: Update, context: CallbackContext, quiz_type: str, filter_id=None) -> int:
    """Asks the user to select the quiz duration."""
    query = update.callback_query
    if query:
        query.answer()
    user_id = update.effective_user.id

    context.user_data['quiz_selection'] = {'type': quiz_type, 'filter': filter_id}
    logger.info(f"User {user_id} selected quiz type '{quiz_type}' with filter '{filter_id}'. Prompting for duration.")

    reply_markup = create_quiz_duration_keyboard()
    message_text = "اختر مدة الاختبار:"
    if query:
        safe_edit_message_text(query.message, text=message_text, reply_markup=reply_markup)
    else:
        # Should ideally not happen if coming from inline buttons
        safe_send_message(context.bot, chat_id=update.effective_chat.id, text=message_text, reply_markup=reply_markup)

    return SELECTING_QUIZ_DURATION

def handle_quiz_selection(update: Update, context: CallbackContext) -> int:
    """Handles the selection of quiz type from the quiz menu."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = update.effective_user.id

    logger.info(f"User {user_id} selected quiz option: {data}")

    if data == 'quiz_random_prompt':
        # Directly prompt for duration for random quiz
        return prompt_quiz_duration(update, context, quiz_type='random')
    elif data == 'quiz_by_grade_prompt':
        # Ask for grade level first
        reply_markup = create_grade_levels_keyboard(for_quiz=True, context=context)
        if not reply_markup.inline_keyboard or len(reply_markup.inline_keyboard) <= 1: # Only back button
             safe_edit_message_text(query.message, text="عذراً، لا توجد مراحل دراسية متاحة حالياً.", reply_markup=create_back_button('menu_quiz'))
             return QUIZ_MENU
        safe_edit_message_text(query.message, text="اختر المرحلة الدراسية:", reply_markup=reply_markup)
        return SELECT_GRADE_LEVEL_FOR_QUIZ
    elif data == 'quiz_by_chapter_prompt':
        # Need to ask for grade first, then chapter
        reply_markup = create_grade_levels_keyboard(for_quiz=True, context=context) # Reuse grade selection
        if not reply_markup.inline_keyboard or len(reply_markup.inline_keyboard) <= 1:
             safe_edit_message_text(query.message, text="عذراً، لا توجد مراحل دراسية (وبالتالي فصول) متاحة حالياً.", reply_markup=create_back_button('menu_quiz'))
             return QUIZ_MENU
        safe_edit_message_text(query.message, text="أولاً، اختر المرحلة الدراسية للفصل:", reply_markup=reply_markup)
        return SELECT_GRADE_LEVEL_FOR_QUIZ # State to select grade, then chapter
    elif data == 'quiz_by_lesson_prompt':
        # Need grade -> chapter -> lesson
        reply_markup = create_grade_levels_keyboard(for_quiz=True, context=context) # Reuse grade selection
        if not reply_markup.inline_keyboard or len(reply_markup.inline_keyboard) <= 1:
             safe_edit_message_text(query.message, text="عذراً، لا توجد مراحل دراسية (وبالتالي فصول ودروس) متاحة حالياً.", reply_markup=create_back_button('menu_quiz'))
             return QUIZ_MENU
        safe_edit_message_text(query.message, text="أولاً، اختر المرحلة الدراسية للدرس:", reply_markup=reply_markup)
        return SELECT_GRADE_LEVEL_FOR_QUIZ # State to select grade, then chapter, then lesson
    elif data == 'main_menu':
        return start(update, context)
    else:
        logger.warning(f"Unhandled quiz selection data: {data}")
        safe_edit_message_text(query.message, text="خيار غير معروف.")
        return QUIZ_MENU

def handle_grade_selection_for_quiz(update: Update, context: CallbackContext) -> int:
    """Handles selection of grade level when starting a filtered quiz."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = update.effective_user.id

    if not data.startswith('select_grade_quiz_'):
        logger.warning(f"Unexpected data in handle_grade_selection_for_quiz: {data}")
        return QUIZ_MENU

    grade_id = int(data.split('_')[-1])
    context.user_data['selected_grade_id'] = grade_id
    logger.info(f"User {user_id} selected grade {grade_id} for quiz.")

    # Check which type of quiz was originally intended (from quiz_selection)
    original_intent = context.user_data.get('quiz_selection', {}).get('type')

    if original_intent == 'grade': # User wanted quiz by grade
        return prompt_quiz_duration(update, context, quiz_type='grade', filter_id=grade_id)
    elif original_intent == 'chapter': # User wants quiz by chapter, now show chapters for this grade
        reply_markup = create_chapters_keyboard(grade_id, for_quiz=True, context=context)
        if not reply_markup.inline_keyboard or len(reply_markup.inline_keyboard) <= 1:
            safe_edit_message_text(query.message, text=f"عذراً، لا توجد فصول متاحة لهذه المرحلة الدراسية.", reply_markup=create_back_button('quiz_by_grade_prompt'))
            return SELECT_GRADE_LEVEL_FOR_QUIZ # Go back to grade selection
        safe_edit_message_text(query.message, text="اختر الفصل:", reply_markup=reply_markup)
        return SELECT_CHAPTER_FOR_QUIZ
    elif original_intent == 'lesson': # User wants quiz by lesson, now show chapters for this grade
        reply_markup = create_chapters_keyboard(grade_id, for_lesson_selection=True, context=context)
        if not reply_markup.inline_keyboard or len(reply_markup.inline_keyboard) <= 1:
            safe_edit_message_text(query.message, text=f"عذراً، لا توجد فصول (وبالتالي دروس) متاحة لهذه المرحلة الدراسية.", reply_markup=create_back_button('quiz_by_grade_prompt'))
            return SELECT_GRADE_LEVEL_FOR_QUIZ # Go back to grade selection
        safe_edit_message_text(query.message, text="اختر الفصل الذي يحتوي على الدرس:", reply_markup=reply_markup)
        return SELECT_CHAPTER_FOR_LESSON_QUIZ # State to select chapter, then lesson
    else:
        logger.error(f"Invalid original quiz intent '{original_intent}' after selecting grade.")
        safe_edit_message_text(query.message, text="حدث خطأ غير متوقع. الرجاء المحاولة مرة أخرى.", reply_markup=create_back_button('menu_quiz'))
        return QUIZ_MENU

def handle_chapter_selection_for_quiz(update: Update, context: CallbackContext) -> int:
    """Handles selection of chapter when starting a chapter quiz."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = update.effective_user.id

    if not data.startswith('select_chapter_quiz_'):
        logger.warning(f"Unexpected data in handle_chapter_selection_for_quiz: {data}")
        return QUIZ_MENU

    chapter_id = int(data.split('_')[-1])
    context.user_data['selected_chapter_id'] = chapter_id
    logger.info(f"User {user_id} selected chapter {chapter_id} for quiz.")

    # Now prompt for duration
    return prompt_quiz_duration(update, context, quiz_type='chapter', filter_id=chapter_id)

def handle_chapter_selection_for_lesson_quiz(update: Update, context: CallbackContext) -> int:
    """Handles selection of chapter when the goal is to select a lesson."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = update.effective_user.id

    if not data.startswith('select_lesson_chapter_'):
        logger.warning(f"Unexpected data in handle_chapter_selection_for_lesson_quiz: {data}")
        return QUIZ_MENU

    chapter_id = int(data.split('_')[-1])
    context.user_data['selected_chapter_id'] = chapter_id
    logger.info(f"User {user_id} selected chapter {chapter_id} to find a lesson.")

    # Now show lessons for this chapter
    reply_markup = create_lessons_keyboard(chapter_id, for_quiz=True, context=context)
    if not reply_markup.inline_keyboard or len(reply_markup.inline_keyboard) <= 1:
        # Need grade_id to go back correctly
        grade_id = context.user_data.get('selected_grade_id')
        back_callback = f'select_grade_quiz_{grade_id}' if grade_id else 'quiz_by_grade_prompt'
        safe_edit_message_text(query.message, text=f"عذراً، لا توجد دروس متاحة لهذا الفصل.", reply_markup=create_back_button(back_callback))
        # Stay in a state where chapter can be re-selected for the same grade
        return SELECT_CHAPTER_FOR_LESSON_QUIZ

    safe_edit_message_text(query.message, text="اختر الدرس:", reply_markup=reply_markup)
    return SELECT_LESSON_FOR_QUIZ

def handle_lesson_selection_for_quiz(update: Update, context: CallbackContext) -> int:
    """Handles selection of lesson when starting a lesson quiz."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = update.effective_user.id

    if not data.startswith('select_lesson_quiz_'):
        logger.warning(f"Unexpected data in handle_lesson_selection_for_quiz: {data}")
        return QUIZ_MENU

    lesson_id = int(data.split('_')[-1])
    context.user_data['selected_lesson_id'] = lesson_id
    logger.info(f"User {user_id} selected lesson {lesson_id} for quiz.")

    # Now prompt for duration
    return prompt_quiz_duration(update, context, quiz_type='lesson', filter_id=lesson_id)

def start_quiz(update: Update, context: CallbackContext) -> int:
    """Starts the quiz after duration is selected."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if not data.startswith('quiz_duration_'):
        logger.warning(f"Unexpected data in start_quiz: {data}")
        return QUIZ_MENU

    duration_minutes = int(data.split('_')[-1])
    quiz_selection = context.user_data.get('quiz_selection', {})
    quiz_type = quiz_selection.get('type', 'random')
    filter_id = quiz_selection.get('filter')

    logger.info(f"Attempting to start quiz for user {user_id}: type={quiz_type}, filter={filter_id}, duration={duration_minutes}")

    # --- DEBUG LOGGING --- #
    logger.info(f"[DEBUG] Fetching questions. Quiz Type: {quiz_type}, Filter ID: {filter_id}")
    questions = []
    try:
        if quiz_type == 'random':
            logger.info("[DEBUG] Calling QUIZ_DB.get_random_questions()")
            questions = QUIZ_DB.get_random_questions(limit=DEFAULT_QUIZ_QUESTIONS)
        elif quiz_type == 'grade' and filter_id:
            logger.info(f"[DEBUG] Calling QUIZ_DB.get_questions_by_grade({filter_id})")
            questions = QUIZ_DB.get_questions_by_grade(filter_id, limit=DEFAULT_QUIZ_QUESTIONS)
        elif quiz_type == 'chapter' and filter_id:
            logger.info(f"[DEBUG] Calling QUIZ_DB.get_questions_by_chapter({filter_id})")
            questions = QUIZ_DB.get_questions_by_chapter(filter_id, limit=DEFAULT_QUIZ_QUESTIONS)
        elif quiz_type == 'lesson' and filter_id:
            logger.info(f"[DEBUG] Calling QUIZ_DB.get_questions_by_lesson({filter_id})")
            questions = QUIZ_DB.get_questions_by_lesson(filter_id, limit=DEFAULT_QUIZ_QUESTIONS)
        else:
            logger.warning(f"[DEBUG] Unknown quiz type '{quiz_type}' or missing filter_id. Defaulting to random.")
            questions = QUIZ_DB.get_random_questions(limit=DEFAULT_QUIZ_QUESTIONS)
        
        # --- MORE DEBUG LOGGING --- #
        logger.info(f"[DEBUG] Fetched questions result type: {type(questions)}")
        if isinstance(questions, list):
            logger.info(f"[DEBUG] Number of questions fetched: {len(questions)}")
            if len(questions) > 0:
                 # Log the structure of the first question to check format
                 logger.info(f"[DEBUG] First question data (sample): {questions[0]}") 
            else:
                 logger.info("[DEBUG] Fetched question list is empty.")
        else:
            logger.error(f"[DEBUG] Fetched questions is NOT a list: {questions}")

    except Exception as e:
        logger.error(f"[DEBUG] Exception occurred while fetching questions: {e}", exc_info=True)
        safe_edit_message_text(query.message, text="حدث خطأ أثناء جلب الأسئلة من قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً.", reply_markup=create_back_button('menu_quiz'))
        return QUIZ_MENU

    if not questions:
        logger.warning(f"[DEBUG] No questions found for quiz type '{quiz_type}' filter '{filter_id}'.")
        safe_edit_message_text(query.message, text="عذراً، لم يتم العثور على أسئلة لهذا النوع من الاختبار حالياً. الرجاء المحاولة لاحقاً أو اختيار نوع آخر.", reply_markup=create_back_button('menu_quiz'))
        return QUIZ_MENU

    # Shuffle questions just in case DB didn't randomize (though ORDER BY RANDOM() should handle it)
    random.shuffle(questions)

    quiz_id = f"quiz_{user_id}_{int(time.time())}" # Unique quiz ID
    quiz_data = {
        "quiz_id": quiz_id,
        "questions": questions,
        "current_question_index": 0,
        "answers": {},
        "score": 0,
        "start_time": time.time(),
        "duration_minutes": duration_minutes,
        "quiz_type": quiz_type,
        "filter_id": filter_id,
        "timed_out": False,
        "quiz_timer_job_name": None,
        "question_timer_job_name": None
    }
    context.user_data["current_quiz"] = quiz_data
    logger.info(f"[DEBUG] Quiz data initialized for quiz_id {quiz_id}: {quiz_data}")

    # Set overall quiz timer
    quiz_data["quiz_timer_job_name"] = set_quiz_timer(context, chat_id, user_id, quiz_id, duration_minutes)

    # Send the first question
    logger.info(f"[DEBUG] Attempting to send first question (index 0) for quiz_id {quiz_id}")
    send_question(update, context)

    return TAKING_QUIZ

def send_question(update: Update, context: CallbackContext):
    """Sends the current question to the user."""
    query = update.callback_query # Might be None if called directly
    if query:
        query.answer()

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    quiz_data = context.user_data.get("current_quiz")

    # --- DEBUG LOGGING --- #
    logger.info(f"[DEBUG] Entering send_question for user {user_id}, chat {chat_id}")
    if not quiz_data:
        logger.error(f"[DEBUG] No current_quiz data found for user {user_id} in send_question.")
        safe_send_message(context.bot, chat_id, text="حدث خطأ: لا يمكن العثور على بيانات الاختبار الحالية.", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU # Or ConversationHandler.END?

    quiz_id = quiz_data["quiz_id"]
    current_index = quiz_data["current_question_index"]
    questions = quiz_data["questions"]
    total_questions = len(questions)

    logger.info(f"[DEBUG] Sending question {current_index + 1}/{total_questions} for quiz_id {quiz_id}")

    if current_index >= total_questions:
        logger.info(f"[DEBUG] No more questions left. Ending quiz {quiz_id}.")
        return show_results(chat_id, user_id, quiz_id, context)

    question = questions[current_index]
    logger.info(f"[DEBUG] Current question data: {question}") # Log the question data being sent

    # Validate question structure (basic check)
    required_keys = ['question_text', 'option1', 'option2', 'option3', 'option4', 'correct_answer']
    if not all(key in question and question[key] is not None for key in ['question_text', 'option1', 'option2', 'option3', 'option4']) or 'correct_answer' not in question:
         logger.error(f"[DEBUG] Invalid question structure for question_id {question.get('question_id', 'N/A')}: {question}")
         safe_send_message(context.bot, chat_id, text=f"حدث خطأ في تنسيق السؤال رقم {current_index + 1}. سيتم تخطي هذا السؤال.")
         # Skip this question automatically
         handle_quiz_skip(chat_id, user_id, quiz_id, current_index, context, error_skip=True)
         return TAKING_QUIZ

    question_text = f"*السؤال {current_index + 1} من {total_questions}:*\n\n{process_text_with_chemical_notation(question['question_text'])}"

{process_text_with_chemical_notation(question['question_text'])}"

    options = [
        question['option1'],
        question['option2'],
        question['option3'],
        question['option4']
    ]
    # Filter out None options just in case, though quiz_db should handle this
    options = [opt for opt in options if opt is not None]
    logger.info(f"[DEBUG] Options for current question: {options}")

    # Create keyboard buttons for options
    keyboard = []
    for i, option_text in enumerate(options):
        callback_data = f"quiz_{quiz_id}_{current_index}_{i}" # quiz_id_questionindex_optionindex
        keyboard.append([InlineKeyboardButton(process_text_with_chemical_notation(option_text), callback_data=callback_data)])

    # Add skip button
    skip_callback_data = f"quiz_{quiz_id}_{current_index}_skip"
    keyboard.append([InlineKeyboardButton("⏭️ تخطي السؤال", callback_data=skip_callback_data)])

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Set question timer if enabled
    quiz_data["question_timer_job_name"] = set_question_timer(context, chat_id, user_id, quiz_id, current_index)

    # Send question text and options
    message_to_edit = query.message if query else None
    sent_message = None

    # Handle image if present
    image_url = question.get('image_url')
    logger.info(f"[DEBUG] Image URL for question: {image_url}")

    try:
        if image_url:
            logger.info(f"[DEBUG] Sending question with image: {image_url}")
            # If editing, we might need to delete the old message and send a new one with media
            if message_to_edit:
                try:
                    message_to_edit.delete()
                    logger.info("[DEBUG] Deleted previous message to send new one with image.")
                except BadRequest as e:
                    logger.warning(f"[DEBUG] Could not delete previous message: {e}")
                message_to_edit = None # Force sending new message
            
            sent_message = context.bot.send_photo(
                chat_id=chat_id,
                photo=image_url,
                caption=question_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            logger.info("[DEBUG] Sending question without image.")
            if message_to_edit:
                # Check if the message already has media; if so, cannot edit to text-only
                if message_to_edit.photo:
                     logger.info("[DEBUG] Previous message had photo, cannot edit to text. Sending new message.")
                     try:
                         message_to_edit.delete()
                     except BadRequest as e:
                         logger.warning(f"[DEBUG] Could not delete previous message with photo: {e}")
                     message_to_edit = None # Force sending new message
                 
            if message_to_edit:
                 logger.info("[DEBUG] Editing previous message.")
                 sent_message = safe_edit_message_text(message_to_edit, text=question_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            else:
                 logger.info("[DEBUG] Sending new message.")
                 sent_message = safe_send_message(context.bot, chat_id=chat_id, text=question_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

        # Store the message ID if needed for future edits (e.g., feedback)
        if sent_message:
            quiz_data['last_question_message_id'] = sent_message.message_id
            logger.info(f"[DEBUG] Question sent successfully. Message ID: {sent_message.message_id}")
        else:
            # This case might happen if safe_edit_message_text fails silently
            logger.error("[DEBUG] Failed to send or edit question message.")
            # Attempt to send a fallback error message
            safe_send_message(context.bot, chat_id, text="حدث خطأ أثناء عرض السؤال. الرجاء المحاولة مرة أخرى.")
            # Consider ending the quiz or retrying?
            return MAIN_MENU # Go back to main menu for safety

    except BadRequest as e:
        logger.error(f"[DEBUG] Telegram BadRequest sending question {current_index + 1}: {e}")
        safe_send_message(context.bot, chat_id, text=f"حدث خطأ في Telegram أثناء عرض السؤال {current_index + 1}. قد يكون بسبب تنسيق النص أو الصورة. سيتم تخطي هذا السؤال.")
        handle_quiz_skip(chat_id, user_id, quiz_id, current_index, context, error_skip=True)
    except Exception as e:
        logger.error(f"[DEBUG] Unexpected error sending question {current_index + 1}: {e}", exc_info=True)
        safe_send_message(context.bot, chat_id, text=f"حدث خطأ غير متوقع أثناء عرض السؤال {current_index + 1}. سيتم تخطي هذا السؤال.")
        handle_quiz_skip(chat_id, user_id, quiz_id, current_index, context, error_skip=True)

    return TAKING_QUIZ

def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    """Handles the user's answer to a quiz question."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    logger.info(f"[DEBUG] Received callback query: {data}")

    try:
        _, quiz_id_from_data, question_index_str, answer_index_str = data.split('_')
        question_index = int(question_index_str)
        is_skip = (answer_index_str == 'skip')
        selected_option_index = int(answer_index_str) if not is_skip else -1
    except ValueError:
        logger.error(f"[DEBUG] Invalid callback data format: {data}")
        safe_edit_message_text(query.message, text="حدث خطأ في بيانات الإجابة. الرجاء المحاولة مرة أخرى.")
        return TAKING_QUIZ # Stay in the quiz

    quiz_data = context.user_data.get("current_quiz")

    # --- DEBUG LOGGING --- #
    if not quiz_data:
        logger.error(f"[DEBUG] No current_quiz data found for user {user_id} in handle_quiz_answer.")
        safe_edit_message_text(query.message, text="حدث خطأ: بيانات الاختبار غير موجودة. العودة للقائمة الرئيسية.", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU

    # Check if the callback corresponds to the current quiz and question
    if quiz_data["quiz_id"] != quiz_id_from_data:
        logger.warning(f"[DEBUG] Received answer for an old/invalid quiz_id: {quiz_id_from_data} (current: {quiz_data['quiz_id']}). Ignoring.")
        # Optionally inform the user
        # query.message.reply_text("لقد انتهى هذا الاختبار بالفعل أو تم إلغاؤه.")
        return TAKING_QUIZ # Stay in the current state

    if quiz_data["current_question_index"] != question_index:
        logger.warning(f"[DEBUG] Received answer for a previous question index: {question_index} (current: {quiz_data['current_question_index']}). Ignoring.")
        # Optionally inform the user
        # query.message.reply_text("لقد أجبت على هذا السؤال بالفعل أو تم تخطيه.")
        return TAKING_QUIZ # Stay in the current state

    # Remove question timer if it exists
    if quiz_data.get("question_timer_job_name"):
        remove_job_if_exists(quiz_data["question_timer_job_name"], context)
        quiz_data["question_timer_job_name"] = None

    if is_skip:
        logger.info(f"[DEBUG] User {user_id} skipped question {question_index}")
        handle_quiz_skip(chat_id, user_id, quiz_id_from_data, question_index, context)
    else:
        logger.info(f"[DEBUG] User {user_id} answered question {question_index} with option {selected_option_index}")
        process_answer(update, context, quiz_id_from_data, question_index, selected_option_index)

    return TAKING_QUIZ

def handle_quiz_skip(chat_id, user_id, quiz_id, question_index, context, timed_out=False, error_skip=False):
    """Handles skipping a question, either by user or timeout or error."""
    quiz_data = context.user_data.get("current_quiz")
    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.warning(f"[DEBUG] Quiz data mismatch or missing in handle_quiz_skip for quiz {quiz_id}")
        return

    # Record skip (optional, could track skips vs timeouts vs errors)
    quiz_data["answers"][question_index] = {"selected": -1, "correct": -2, "time": time.time()} # -1 for user skip, -2 for correct (N/A)

    feedback_text = "تم تخطي السؤال." if not timed_out and not error_skip else ("انتهى وقت السؤال." if timed_out else "تم تخطي السؤال بسبب خطأ.")
    message_id = quiz_data.get('last_question_message_id')

    try:
        if message_id:
            # Edit the message to show feedback and remove buttons
            context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
            # Optionally add feedback text to the caption if it was a photo
            # message = context.bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption=f"{context.bot.get_chat(chat_id).get_message(message_id).caption}\n\n{feedback_text}")
            # For simplicity, just send a new message for feedback after removing markup
            safe_send_message(context.bot, chat_id, text=feedback_text)
        else:
            safe_send_message(context.bot, chat_id, text=feedback_text)
    except BadRequest as e:
        logger.warning(f"[DEBUG] Could not edit message markup/caption on skip: {e}")
        safe_send_message(context.bot, chat_id, text=feedback_text) # Send as new message
    except Exception as e:
        logger.error(f"[DEBUG] Error during skip feedback: {e}", exc_info=True)
        safe_send_message(context.bot, chat_id, text=feedback_text) # Fallback

    # Move to the next question after a delay
    quiz_data["current_question_index"] += 1
    context.job_queue.run_once(lambda ctx: send_question(Update(0, effective_chat=ctx.bot.get_chat(chat_id), effective_user=ctx.bot.get_chat(chat_id).get_member(user_id).user), ctx), FEEDBACK_DELAY, context=context)

def process_answer(update: Update, context: CallbackContext, quiz_id: str, question_index: int, selected_option_index: int):
    """Processes the user's selected answer, provides feedback, and moves to the next question."""
    query = update.callback_query
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    quiz_data = context.user_data.get("current_quiz")

    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.warning(f"[DEBUG] Quiz data mismatch or missing in process_answer for quiz {quiz_id}")
        return

    question = quiz_data["questions"][question_index]
    correct_answer_index = question['correct_answer']
    is_correct = (selected_option_index == correct_answer_index)

    logger.info(f"[DEBUG] Processing answer for Q{question_index}. Selected: {selected_option_index}, Correct: {correct_answer_index}, Result: {is_correct}")

    # Update score and record answer
    if is_correct:
        quiz_data["score"] += 1
    quiz_data["answers"][question_index] = {"selected": selected_option_index, "correct": correct_answer_index, "time": time.time()}

    # Provide feedback
    feedback_text = "✅ إجابة صحيحة!" if is_correct else "❌ إجابة خاطئة."
    if not is_correct and question.get('explanation'):
        feedback_text += f"\n\n*الشرح:*
{process_text_with_chemical_notation(question['explanation'])}"
    elif not is_correct:
         # Show the correct option text if no explanation
         try:
             correct_option_text = question[f'option{correct_answer_index + 1}']
             feedback_text += f"\n\n*الإجابة الصحيحة:* {process_text_with_chemical_notation(correct_option_text)}"
         except (KeyError, IndexError):
             logger.warning(f"[DEBUG] Could not retrieve correct option text for Q{question_index}")

    message_id = quiz_data.get('last_question_message_id')

    try:
        if message_id:
            # Edit the message to show feedback and remove buttons
            context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
            # Send feedback as a new message for clarity and to handle Markdown
            safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)
        else:
            safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN)
    except BadRequest as e:
        logger.warning(f"[DEBUG] Could not edit message markup on answer: {e}")
        safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN) # Send as new message
    except Exception as e:
        logger.error(f"[DEBUG] Error during answer feedback: {e}", exc_info=True)
        safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode=ParseMode.MARKDOWN) # Fallback

    # Move to the next question after a delay
    quiz_data["current_question_index"] += 1
    context.job_queue.run_once(lambda ctx: send_question(Update(0, effective_chat=ctx.bot.get_chat(chat_id), effective_user=ctx.bot.get_chat(chat_id).get_member(user_id).user), ctx), FEEDBACK_DELAY, context=context)

def show_results(chat_id, user_id, quiz_id, context, timed_out=False):
    """Calculates and displays the quiz results."""
    logger.info(f"[DEBUG] Calculating results for quiz {quiz_id}, user {user_id}")
    quiz_data = context.user_data.get("current_quiz")

    if not quiz_data or quiz_data["quiz_id"] != quiz_id:
        logger.warning(f"[DEBUG] Quiz data mismatch or missing in show_results for quiz {quiz_id}. Cannot show results.")
        # Maybe the quiz was already finished and cleaned up
        return MAIN_MENU # Go back to main menu

    # Ensure quiz timer is removed if quiz ends normally
    if quiz_data.get('quiz_timer_job_name'):
        remove_job_if_exists(quiz_data['quiz_timer_job_name'], context)
        quiz_data['quiz_timer_job_name'] = None
    # Ensure question timer is removed
    if quiz_data.get('question_timer_job_name'):
        remove_job_if_exists(quiz_data['question_timer_job_name'], context)
        quiz_data['question_timer_job_name'] = None

    score = quiz_data["score"]
    total_questions = len(quiz_data["questions"])
    end_time = time.time()
    time_taken = int(end_time - quiz_data["start_time"])
    quiz_type = quiz_data["quiz_type"]
    filter_id = quiz_data["filter_id"]

    if total_questions == 0:
        logger.warning(f"[DEBUG] Quiz {quiz_id} had 0 questions. Cannot calculate percentage.")
        percentage = 0.0
    else:
        percentage = (score / total_questions) * 100

    # Format time taken
    minutes, seconds = divmod(time_taken, 60)
    time_str = f"{minutes} دقيقة و {seconds} ثانية"

    result_text = f"🏁 *نتائج الاختبار* 🏁\n\n"
    if timed_out:
        result_text += "⏰ انتهى وقت الاختبار المحدد!\n"
    result_text += f"✨ نتيجتك: {score} من {total_questions} ({percentage:.1f}%)\n"
    result_text += f"⏱️ الوقت المستغرق: {time_str}\n\n"

    # Add performance feedback (optional)
    if percentage >= 80:
        result_text += "🎉 أداء رائع! استمر في التقدم."
    elif percentage >= 50:
        result_text += "👍 جيد جداً! يمكنك التحسن أكثر مع المراجعة."
    else:
        result_text += "💪 لا بأس، حاول مرة أخرى! المراجعة المستمرة هي مفتاح النجاح."

    # Save results to DB
    if QUIZ_DB:
        logger.info(f"[DEBUG] Saving quiz results to DB for quiz {quiz_id}")
        save_success = QUIZ_DB.save_quiz_result(
            quiz_id=quiz_id,
            user_id=user_id,
            score=score,
            total_questions=total_questions,
            time_taken_seconds=time_taken,
            quiz_type=quiz_type,
            filter_id=filter_id
        )
        if not save_success:
            logger.error(f"[DEBUG] Failed to save quiz results for quiz {quiz_id} to database.")
            result_text += "\n\n*(تحذير: لم يتم حفظ نتيجتك في قاعدة البيانات بسبب خطأ.)*"
        else:
             logger.info(f"[DEBUG] Quiz results saved successfully for quiz {quiz_id}.")

    # Clean up quiz data from user_data
    logger.info(f"[DEBUG] Cleaning up quiz data for user {user_id}")
    del context.user_data["current_quiz"]

    # Send results and back to main menu button
    reply_markup = create_back_button('main_menu')
    safe_send_message(context.bot, chat_id=chat_id, text=result_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    return MAIN_MENU

# --- Information Menu Handlers ---

def handle_info_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = update.effective_user.id

    logger.info(f"User {user_id} selected info option: {data}")

    content_map = {
        'info_periodic_table': ("الجدول الدوري", PERIODIC_TABLE_INFO),
        'info_compounds': ("المركبات الشائعة", COMPOUNDS),
        'info_concepts': ("المفاهيم الأساسية", CONCEPTS),
        'info_calculations': ("الحسابات الكيميائية", CHEMICAL_CALCULATIONS_INFO),
        'info_bonds': ("الروابط الكيميائية", CHEMICAL_BONDS_INFO),
    }

    if data in content_map:
        title, content_data = content_map[data]
        if isinstance(content_data, dict) and content_data: # Check if it's a non-empty dict
            # If it's a dictionary (like COMPOUNDS, CONCEPTS), list items
            info_text = f"*{title}:*\n\n"
            # Limit the number of items shown initially
            max_items = 15
            count = 0
            for key, value in content_data.items():
                if count >= max_items:
                    info_text += f"\n... وغيرها الكثير."
                    break
                # Simple display, might need formatting based on actual data structure
                info_text += f"- {key}\n"
                count += 1
            if count == 0:
                 info_text = f"عذراً، لا توجد معلومات متاحة حالياً عن *{title}*."
        elif isinstance(content_data, str) and content_data: # Check if it's a non-empty string
            info_text = f"*{title}:*\n\n{process_text_with_chemical_notation(content_data)}"
        else:
            info_text = f"عذراً، لا توجد معلومات متاحة حالياً عن *{title}*."

        reply_markup = create_back_button('menu_info')
        safe_edit_message_text(query.message, text=info_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return SHOWING_INFO_CONTENT
    elif data == 'main_menu':
        return start(update, context)
    else:
        logger.warning(f"Unhandled info menu data: {data}")
        safe_edit_message_text(query.message, text="خيار غير معروف.")
        return INFO_MENU

# --- Performance Reports Handler ---

def show_performance_reports(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    if query:
        query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    logger.info(f"User {user_id} requested performance reports.")

    if not QUIZ_DB:
        text = "عذراً، لا يمكن عرض التقارير حالياً بسبب مشكلة في الاتصال بقاعدة البيانات."
        reply_markup = create_back_button('main_menu')
    else:
        overall_stats = QUIZ_DB.get_user_overall_stats(user_id)
        # stats_by_type = QUIZ_DB.get_user_stats_by_type(user_id)
        last_quizzes = QUIZ_DB.get_user_last_quizzes(user_id, limit=5)

        text = "📊 *تقارير أدائك في الاختبارات:*

"

        if overall_stats and overall_stats['total_quizzes'] > 0:
            # Format overall stats from the raw dictionary returned by DB function
            avg_time_int = int(overall_stats['avg_time']) if overall_stats['avg_time'] is not None else 0
            avg_minutes, avg_seconds = divmod(avg_time_int, 60)
            avg_time_str = f"{avg_minutes} د {avg_seconds} ث"
            avg_percentage = round(overall_stats['avg_percentage'], 1) if overall_stats['avg_percentage'] is not None else 0.0

            text += f"*📊 ملخص عام:*
"
            text += f"- إجمالي الاختبارات: {overall_stats['total_quizzes']}\n"
            text += f"- متوسط النسبة المئوية: {avg_percentage}%\n"
            text += f"- متوسط وقت الاختبار: {avg_time_str}\n\n"
        else:
            text += "لم تكمل أي اختبارات بعد.\n\n"

        # Display last 5 quizzes
        if last_quizzes:
            text += "*📅 آخر 5 اختبارات:*
"
            for q in last_quizzes:
                quiz_type_ar = {
                    'random': 'عشوائي',
                    'grade': 'مرحلة',
                    'chapter': 'فصل',
                    'lesson': 'درس'
                }.get(q['quiz_type'], q['quiz_type']) # Translate type
                percentage = round(q['percentage'], 1) if q['percentage'] is not None else 0.0
                # Format timestamp
                try:
                    date_str = q['completed_at'].strftime('%Y-%m-%d %H:%M')
                except:
                    date_str = "غير معروف"
                text += f"- {date_str}: {quiz_type_ar} ({percentage}%)\n"
        else:
             if overall_stats and overall_stats['total_quizzes'] > 0:
                 text += "لا توجد تفاصيل لآخر الاختبارات.\n"

        reply_markup = create_back_button('main_menu')

    # Send or edit message
    if query:
        safe_edit_message_text(query.message, text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        safe_send_message(context.bot, chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    return SHOWING_REPORTS

# --- Admin Handlers ---

def handle_admin_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = update.effective_user.id

    if not is_admin(user_id):
        logger.warning(f"Non-admin user {user_id} tried to access admin menu with data: {data}")
        safe_edit_message_text(query.message, text="ليس لديك صلاحيات للوصول لهذه القائمة.")
        return start(update, context)

    logger.info(f"Admin {user_id} selected admin option: {data}")

    if data == 'admin_add_question':
        safe_edit_message_text(query.message, text="أرسل نص السؤال الجديد:")
        return ADDING_QUESTION
    elif data == 'admin_delete_question':
        safe_edit_message_text(query.message, text="أرسل رقم ID للسؤال الذي تريد حذفه:")
        return DELETING_QUESTION
    elif data == 'admin_show_question':
        safe_edit_message_text(query.message, text="أرسل رقم ID للسؤال الذي تريد عرضه:")
        return SHOWING_QUESTION
    elif data == 'admin_manage_structure':
        reply_markup = create_structure_admin_menu_keyboard()
        safe_edit_message_text(query.message, text="إدارة المراحل والفصول والدروس:", reply_markup=reply_markup)
        return ADMIN_MANAGE_STRUCTURE
    elif data == 'main_menu':
        return start(update, context)
    else:
        logger.warning(f"Unhandled admin menu data: {data}")
        safe_edit_message_text(query.message, text="خيار إدارة غير معروف.")
        return ADMIN_MENU

# --- Admin: Add Question --- #

def admin_receive_question_text(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END # Should not happen in conv handler

    question_text = update.message.text
    context.user_data['question_to_add'] = {'text': question_text, 'options': []}
    logger.info(f"Admin {user_id} provided question text: {question_text}")
    safe_send_message(context.bot, chat_id=update.effective_chat.id, text="أرسل نص الخيار الأول:")
    return ADDING_OPTIONS

def admin_receive_option(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END

    option_text = update.message.text
    question_data = context.user_data['question_to_add']
    question_data['options'].append(option_text)
    num_options = len(question_data['options'])

    logger.info(f"Admin {user_id} provided option {num_options}: {option_text}")

    if num_options < 4:
        safe_send_message(context.bot, chat_id=update.effective_chat.id, text=f"أرسل نص الخيار التالي ({num_options + 1}):")
        return ADDING_OPTIONS
    else:
        # Ask for correct answer index (0-3)
        options_preview = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(question_data['options'])])
        safe_send_message(context.bot, chat_id=update.effective_chat.id, text=f"أدخل رقم الخيار الصحيح (1-4):\n{options_preview}")
        return ADDING_CORRECT_ANSWER

def admin_receive_correct_answer(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END

    try:
        correct_index = int(update.message.text) - 1 # User inputs 1-4, we store 0-3
        if not (0 <= correct_index < 4):
            raise ValueError("Index out of range")
    except ValueError:
        safe_send_message(context.bot, chat_id=update.effective_chat.id, text="إدخال غير صالح. الرجاء إدخال رقم بين 1 و 4.")
        return ADDING_CORRECT_ANSWER

    context.user_data['question_to_add']['correct_answer'] = correct_index
    logger.info(f"Admin {user_id} provided correct answer index: {correct_index}")
    safe_send_message(context.bot, chat_id=update.effective_chat.id, text="أرسل الشرح (اختياري، أرسل /skip للتخطي):")
    return ADDING_EXPLANATION

def admin_receive_explanation(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END

    explanation = update.message.text
    context.user_data['question_to_add']['explanation'] = explanation
    logger.info(f"Admin {user_id} provided explanation: {explanation}")

    # Final step: Add to DB
    q_data = context.user_data['question_to_add']
    if QUIZ_DB:
        logger.warning("Calling add_question which might be incomplete for the new DB structure.")
        new_id = QUIZ_DB.add_question(
            text=q_data['text'],
            opt1=q_data['options'][0],
            opt2=q_data['options'][1],
            opt3=q_data['options'][2],
            opt4=q_data['options'][3],
            correct_option_index=q_data['correct_answer'], # Pass 0-3 index
            explanation=q_data['explanation']
            # Add image_url and quiz_id later if needed
        )
        if new_id:
            safe_send_message(context.bot, chat_id=update.effective_chat.id, text=f"تمت إضافة السؤال بنجاح! ID الجديد: {new_id}")
            logger.info(f"Admin {user_id} successfully added question {new_id}")
        else:
            safe_send_message(context.bot, chat_id=update.effective_chat.id, text="فشل في إضافة السؤال إلى قاعدة البيانات.")
            logger.error(f"Admin {user_id} failed to add question.")
    else:
        safe_send_message(context.bot, chat_id=update.effective_chat.id, text="خطأ: لا يوجد اتصال بقاعدة البيانات.")

    del context.user_data['question_to_add']
    return start(update, context) # Back to main menu

def admin_skip_explanation(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END

    context.user_data['question_to_add']['explanation'] = None
    logger.info(f"Admin {user_id} skipped explanation.")

    # Final step: Add to DB
    q_data = context.user_data['question_to_add']
    if QUIZ_DB:
        logger.warning("Calling add_question which might be incomplete for the new DB structure.")
        new_id = QUIZ_DB.add_question(
            text=q_data['text'],
            opt1=q_data['options'][0],
            opt2=q_data['options'][1],
            opt3=q_data['options'][2],
            opt4=q_data['options'][3],
            correct_option_index=q_data['correct_answer'], # Pass 0-3 index
            explanation=None
        )
        if new_id:
            safe_send_message(context.bot, chat_id=update.effective_chat.id, text=f"تمت إضافة السؤال بنجاح! ID الجديد: {new_id}")
            logger.info(f"Admin {user_id} successfully added question {new_id}")
        else:
            safe_send_message(context.bot, chat_id=update.effective_chat.id, text="فشل في إضافة السؤال إلى قاعدة البيانات.")
            logger.error(f"Admin {user_id} failed to add question.")
    else:
        safe_send_message(context.bot, chat_id=update.effective_chat.id, text="خطأ: لا يوجد اتصال بقاعدة البيانات.")

    del context.user_data['question_to_add']
    return start(update, context) # Back to main menu

# --- Admin: Delete Question --- #

def admin_receive_delete_id(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END

    try:
        question_id_to_delete = int(update.message.text)
    except ValueError:
        safe_send_message(context.bot, chat_id=update.effective_chat.id, text="إدخال غير صالح. الرجاء إرسال رقم ID صحيح.")
        return DELETING_QUESTION

    logger.info(f"Admin {user_id} requested deletion of question ID: {question_id_to_delete}")

    if QUIZ_DB:
        # First, check if question exists to provide better feedback
        existing_question = QUIZ_DB.get_question_by_id(question_id_to_delete)
        if not existing_question:
            safe_send_message(context.bot, chat_id=update.effective_chat.id, text=f"لم يتم العثور على سؤال بالـ ID: {question_id_to_delete}")
            return start(update, context)
        
        # Attempt deletion
        deleted = QUIZ_DB.delete_question(question_id_to_delete)
        if deleted:
            safe_send_message(context.bot, chat_id=update.effective_chat.id, text=f"تم حذف السؤال رقم {question_id_to_delete} بنجاح.")
            logger.info(f"Admin {user_id} successfully deleted question {question_id_to_delete}")
        else:
            safe_send_message(context.bot, chat_id=update.effective_chat.id, text=f"فشل في حذف السؤال رقم {question_id_to_delete} من قاعدة البيانات.")
            logger.error(f"Admin {user_id} failed to delete question {question_id_to_delete}")
    else:
        safe_send_message(context.bot, chat_id=update.effective_chat.id, text="خطأ: لا يوجد اتصال بقاعدة البيانات.")

    return start(update, context) # Back to main menu

# --- Admin: Show Question --- #

def admin_receive_show_id(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END

    try:
        question_id_to_show = int(update.message.text)
    except ValueError:
        safe_send_message(context.bot, chat_id=update.effective_chat.id, text="إدخال غير صالح. الرجاء إرسال رقم ID صحيح.")
        return SHOWING_QUESTION

    logger.info(f"Admin {user_id} requested to show question ID: {question_id_to_show}")

    if QUIZ_DB:
        question_data = QUIZ_DB.get_question_by_id(question_id_to_show)
        if question_data:
            # Format the question data for display
            text = f"*السؤال ID: {question_data['question_id']}*

"
            text += f"*النص:* {process_text_with_chemical_notation(question_data['question_text'])}\n\n"
            text += "*الخيارات:*
"
            options = [question_data.get('option1'), question_data.get('option2'), question_data.get('option3'), question_data.get('option4')]
            options = [opt for opt in options if opt is not None]
            for i, opt in enumerate(options):
                text += f"{i+1}. {process_text_with_chemical_notation(opt)}\n"
            
            correct_index = question_data.get('correct_answer') # This is 0-based now
            if correct_index is not None and 0 <= correct_index < len(options):
                 text += f"\n*الإجابة الصحيحة:* {correct_index + 1}\n"
            else:
                 text += f"\n*الإجابة الصحيحة:* غير محددة أو خاطئة! (القيمة المخزنة: {question_data.get('correct_answer')})
"

            if question_data.get('explanation'):
                text += f"\n*الشرح:* {process_text_with_chemical_notation(question_data['explanation'])}\n"
            if question_data.get('image_url'):
                text += f"\n*رابط الصورة:* {question_data['image_url']}\n"
            
            # Send the formatted text
            reply_markup = create_back_button('menu_admin')
            safe_send_message(context.bot, chat_id=update.effective_chat.id, text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

        else:
            safe_send_message(context.bot, chat_id=update.effective_chat.id, text=f"لم يتم العثور على سؤال بالـ ID: {question_id_to_show}")
            return start(update, context) # Back to main menu if not found
    else:
        safe_send_message(context.bot, chat_id=update.effective_chat.id, text="خطأ: لا يوجد اتصال بقاعدة البيانات.")
        return start(update, context)

    return ADMIN_MENU # Stay in admin menu context after showing

# --- Admin: Manage Structure (Placeholder Handlers) ---

def handle_manage_structure_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = update.effective_user.id

    if not is_admin(user_id):
        logger.warning(f"Non-admin user {user_id} tried to access structure menu: {data}")
        return start(update, context)

    logger.info(f"Admin {user_id} selected structure management option: {data}")

    if data == 'admin_manage_grades':
        # Placeholder: Show existing grades + Add button
        text = "إدارة المراحل الدراسية (قيد الإنشاء)."
        reply_markup = create_back_button('admin_manage_structure')
        safe_edit_message_text(query.message, text=text, reply_markup=reply_markup)
        return ADMIN_MANAGE_GRADES
    elif data == 'admin_manage_chapters':
        # Placeholder: Ask for grade -> Show chapters + Add button
        text = "إدارة الفصول (قيد الإنشاء)."
        reply_markup = create_back_button('admin_manage_structure')
        safe_edit_message_text(query.message, text=text, reply_markup=reply_markup)
        return ADMIN_MANAGE_CHAPTERS
    elif data == 'admin_manage_lessons':
        # Placeholder: Ask for grade -> Ask for chapter -> Show lessons + Add button
        text = "إدارة الدروس (قيد الإنشاء)."
        reply_markup = create_back_button('admin_manage_structure')
        safe_edit_message_text(query.message, text=text, reply_markup=reply_markup)
        return ADMIN_MANAGE_LESSONS
    elif data == 'menu_admin':
        reply_markup = create_admin_menu_keyboard()
        safe_edit_message_text(query.message, text="قائمة إدارة البوت:", reply_markup=reply_markup)
        return ADMIN_MENU
    else:
        logger.warning(f"Unhandled structure management data: {data}")
        return ADMIN_MANAGE_STRUCTURE

# --- Error Handler ---

def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    # Add more specific error handling if needed
    # e.g., handle specific Telegram errors like BadRequest, TimedOut, etc.
    # if isinstance(context.error, BadRequest):
    #     # Handle bad requests, maybe inform user if message format is wrong
    #     pass

# --- Main Function ---

def main() -> None:
    """Start the bot."""
    # Create the Updater and pass it your bot's token.
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN not found. Exiting.")
        return
    
    updater = Updater(BOT_TOKEN)

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher

    # --- Conversation Handler Setup ---
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start), CallbackQueryHandler(handle_menu_button, pattern='^main_menu$')],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(handle_menu_button, pattern='^(menu_quiz|menu_admin|menu_info|menu_reports|menu_about)$'),
                CommandHandler('start', start) # Allow restarting
            ],
            QUIZ_MENU: [
                CallbackQueryHandler(handle_quiz_selection, pattern='^(quiz_random_prompt|quiz_by_grade_prompt|quiz_by_chapter_prompt|quiz_by_lesson_prompt|main_menu)$'),
                CallbackQueryHandler(start, pattern='^main_menu$') # Allow going back
            ],
            ADMIN_MENU: [
                CallbackQueryHandler(handle_admin_menu, pattern='^(admin_add_question|admin_delete_question|admin_show_question|admin_manage_structure|main_menu)$'),
                CallbackQueryHandler(start, pattern='^main_menu$')
            ],
            INFO_MENU: [
                CallbackQueryHandler(handle_info_menu, pattern='^info_'),
                CallbackQueryHandler(start, pattern='^main_menu$')
            ],
            SHOWING_INFO_CONTENT: [
                CallbackQueryHandler(handle_info_menu, pattern='^menu_info$'), # Back to info menu
                CallbackQueryHandler(start, pattern='^main_menu$')
            ],
            SHOWING_REPORTS: [
                 CallbackQueryHandler(start, pattern='^main_menu$') # Back to main menu
            ],
            # --- Quiz Selection States ---
            SELECTING_QUIZ_DURATION: [
                CallbackQueryHandler(start_quiz, pattern='^quiz_duration_')
            ],
            SELECT_GRADE_LEVEL_FOR_QUIZ: [
                CallbackQueryHandler(handle_grade_selection_for_quiz, pattern='^select_grade_quiz_'),
                CallbackQueryHandler(handle_quiz_selection, pattern='^menu_quiz$') # Back button
            ],
            SELECT_CHAPTER_FOR_QUIZ: [
                CallbackQueryHandler(handle_chapter_selection_for_quiz, pattern='^select_chapter_quiz_'),
                CallbackQueryHandler(handle_quiz_selection, pattern='^quiz_by_grade_prompt$') # Back button
            ],
            SELECT_CHAPTER_FOR_LESSON_QUIZ: [
                CallbackQueryHandler(handle_chapter_selection_for_lesson_quiz, pattern='^select_lesson_chapter_'),
                CallbackQueryHandler(handle_quiz_selection, pattern='^quiz_by_grade_prompt$') # Back button
            ],
            SELECT_LESSON_FOR_QUIZ: [
                CallbackQueryHandler(handle_lesson_selection_for_quiz, pattern='^select_lesson_quiz_'),
                # Back button needs chapter_id - handled by create_lessons_keyboard callback
                CallbackQueryHandler(handle_chapter_selection_for_lesson_quiz, pattern='^select_lesson_chapter_')
            ],
            # --- Taking Quiz State ---
            TAKING_QUIZ: [
                CallbackQueryHandler(handle_quiz_answer, pattern='^quiz_') # Handles answers and skips
            ],
            # --- Admin Add/Delete/Show States ---
            ADDING_QUESTION: [MessageHandler(filters.Filters.text & ~filters.Filters.command, admin_receive_question_text)],
            ADDING_OPTIONS: [MessageHandler(filters.Filters.text & ~filters.Filters.command, admin_receive_option)],
            ADDING_CORRECT_ANSWER: [MessageHandler(filters.Filters.text & ~filters.Filters.command, admin_receive_correct_answer)],
            ADDING_EXPLANATION: [
                MessageHandler(filters.Filters.text & ~filters.Filters.command, admin_receive_explanation),
                CommandHandler('skip', admin_skip_explanation)
            ],
            DELETING_QUESTION: [MessageHandler(filters.Filters.text & ~filters.Filters.command, admin_receive_delete_id)],
            SHOWING_QUESTION: [MessageHandler(filters.Filters.text & ~filters.Filters.command, admin_receive_show_id)],
            # --- Admin Manage Structure States (Placeholders) ---
            ADMIN_MANAGE_STRUCTURE: [
                CallbackQueryHandler(handle_manage_structure_menu, pattern='^(admin_manage_grades|admin_manage_chapters|admin_manage_lessons|menu_admin)$'),
                CallbackQueryHandler(handle_admin_menu, pattern='^menu_admin$') # Back button
            ],
            ADMIN_MANAGE_GRADES: [CallbackQueryHandler(handle_manage_structure_menu, pattern='^admin_manage_structure$')], # Back
            ADMIN_MANAGE_CHAPTERS: [CallbackQueryHandler(handle_manage_structure_menu, pattern='^admin_manage_structure$')], # Back
            ADMIN_MANAGE_LESSONS: [CallbackQueryHandler(handle_manage_structure_menu, pattern='^admin_manage_structure$')], # Back
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CommandHandler('start', start), # Allow restarting from anywhere
            CallbackQueryHandler(start, pattern='^main_menu$') # Allow returning to main menu
            ],
        # Allow re-entry into the conversation
        allow_reentry=True,
        # Optional: Persist conversation state (requires setup)
        # name="chemistry_bot_conversation",
        # persistent=True,
    )

    dispatcher.add_handler(conv_handler)

    # Add error handler
    dispatcher.add_error_handler(error_handler)

    # Pass dispatcher to context for timer callbacks
    # This is a bit of a workaround; ideally use application context if using v20+
    dispatcher.bot_data["dispatcher"] = dispatcher 

    # Start the Bot (Webhook for Render)
    if APP_NAME:
        logger.info(f"Starting webhook for Render app {APP_NAME}")
        updater.start_webhook(listen="0.0.0.0",
                              port=PORT,
                              url_path=BOT_TOKEN,
                              webhook_url=f"https://{APP_NAME}.onrender.com/{BOT_TOKEN}")
        logger.info(f"Webhook set to https://{APP_NAME}.onrender.com/{BOT_TOKEN}")
    else:
        logger.warning("APP_NAME not set. Starting in polling mode (not recommended for production).")
        updater.start_polling()

    logger.info("Bot started and running...")
    updater.idle()

    # Close DB connection on exit
    if DB_CONN:
        DB_CONN.close()
        logger.info("Database connection closed.")

if __name__ == '__main__':
    main()

