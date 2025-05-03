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
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

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
    # Assuming these files exist and contain the necessary data/functions
    # from chemistry_data import ELEMENTS, COMPOUNDS, CONCEPTS, PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO
    # from chemical_equations import process_text_with_chemical_notation, format_chemical_equation
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

# --- Timer Functions (Corrected Dictionary Access) ---

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
            context={"chat_id": chat_id, "user_id": user_id, "quiz_id": quiz_id}, # Corrected
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
            context={"chat_id": chat_id, "user_id": user_id, "quiz_id": quiz_id, "question_index": question_index}, # Corrected
            name=job_name
        )
        logger.info(f"Set question timer for {QUESTION_TIMER_SECONDS} seconds. Job: {job_name}")
        return job_name
    return None

def end_quiz_timeout(context: CallbackContext):
    """Callback function when the overall quiz timer expires."""
    job_context = context.job.context
    chat_id = job_context["chat_id"] # Corrected
    user_id = job_context["user_id"] # Corrected
    quiz_id = job_context["quiz_id"] # Corrected
    logger.info(f"Quiz timer expired for quiz {quiz_id} for user {user_id} in chat {chat_id}.")

    # Access user_data via bot_data (requires passing dispatcher to main)
    # Ensure dispatcher is passed in main() function
    if not hasattr(context, 'dispatcher'):
         logger.error("Dispatcher not found in context for end_quiz_timeout. Cannot access user_data.")
         return

    user_data = context.dispatcher.user_data.get(user_id, {})
    quiz_data = user_data.get("current_quiz") # Corrected

    # Check if the quiz is still the active one
    if quiz_data and quiz_data["quiz_id"] == quiz_id and not quiz_data.get("timed_out"): # Corrected
        quiz_data["timed_out"] = True # Mark as timed out # Corrected
        # Remove question timer if it exists
        if quiz_data.get("question_timer_job_name"): # Corrected
            remove_job_if_exists(quiz_data["question_timer_job_name"], context) # Corrected
            quiz_data["question_timer_job_name"] = None # Corrected

        safe_send_message(context.bot, chat_id, text="⏰ انتهى وقت الاختبار!")
        # Call show_results to finalize and display
        show_results(chat_id, user_id, quiz_id, context, timed_out=True)
    else:
        logger.info(f"Quiz {quiz_id} already finished or cancelled, ignoring timeout.")

def question_timer_callback(context: CallbackContext):
    """Callback function when the question timer expires."""
    job_context = context.job.context
    chat_id = job_context["chat_id"] # Corrected
    user_id = job_context["user_id"] # Corrected
    quiz_id = job_context["quiz_id"] # Corrected
    question_index = job_context["question_index"] # Corrected
    logger.info(f"Question timer expired for question {question_index} in quiz {quiz_id} for user {user_id}.")

    if not hasattr(context, 'dispatcher'):
         logger.error("Dispatcher not found in context for question_timer_callback. Cannot access user_data.")
         return

    user_data = context.dispatcher.user_data.get(user_id, {})
    quiz_data = user_data.get("current_quiz") # Corrected

    # Check if the quiz and question index match the current state
    if quiz_data and quiz_data["quiz_id"] == quiz_id and quiz_data["current_question_index"] == question_index and not quiz_data.get("timed_out"): # Corrected
        safe_send_message(context.bot, chat_id, text=f"⏰ انتهى وقت السؤال {question_index + 1}! سيتم اعتباره متخطى.")
        # Treat as skip
        handle_quiz_skip(chat_id, user_id, quiz_id, question_index, context, timed_out=True)
    else:
        logger.info(f"Question {question_index} already answered/skipped or quiz ended, ignoring timer.")

# --- Keyboard Creation Functions (Corrected callback_data) ---

def create_main_menu_keyboard(user_id):
    keyboard = [
        [InlineKeyboardButton("📚 المعلومات الكيميائية", callback_data='menu_info')], # Corrected
        [InlineKeyboardButton("📝 الاختبارات", callback_data='menu_quiz')], # Corrected
        [InlineKeyboardButton("📊 تقارير الأداء", callback_data='menu_reports')], # Corrected
        [InlineKeyboardButton("ℹ️ حول البوت", callback_data='menu_about')] # Corrected
    ]
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ إدارة البوت", callback_data='menu_admin')]) # Corrected
    return InlineKeyboardMarkup(keyboard)

def create_quiz_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📚 اختبار تحصيلي عام", callback_data='quiz_random_prompt')], # Corrected
        [InlineKeyboardButton("📄 اختبار حسب الفصل", callback_data='quiz_by_chapter_prompt')], # Corrected
        [InlineKeyboardButton("📝 اختبار حسب الدرس", callback_data='quiz_by_lesson_prompt')], # Corrected
        [InlineKeyboardButton("🎓 اختبار حسب المرحلة الدراسية", callback_data='quiz_by_grade_prompt')], # Corrected
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')] # Corrected
    ]
    return InlineKeyboardMarkup(keyboard)

def create_admin_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ إضافة سؤال", callback_data='admin_add_question')], # Corrected
        [InlineKeyboardButton("🗑️ حذف سؤال", callback_data='admin_delete_question')], # Corrected
        [InlineKeyboardButton("🔍 عرض سؤال", callback_data='admin_show_question')], # Corrected
        [InlineKeyboardButton("🏫 إدارة المراحل/الفصول/الدروس", callback_data='admin_manage_structure')], # Corrected
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')] # Corrected
    ]
    return InlineKeyboardMarkup(keyboard)

def create_structure_admin_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🏫 إدارة المراحل الدراسية", callback_data='admin_manage_grades')], # Corrected
        [InlineKeyboardButton("📚 إدارة الفصول", callback_data='admin_manage_chapters')], # Corrected
        [InlineKeyboardButton("📝 إدارة الدروس", callback_data='admin_manage_lessons')], # Corrected
        [InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data='menu_admin')] # Corrected
    ]
    return InlineKeyboardMarkup(keyboard)

def create_quiz_duration_keyboard():
    keyboard = [
        [InlineKeyboardButton("5 دقائق", callback_data='quiz_duration_5')], # Corrected
        [InlineKeyboardButton("10 دقائق", callback_data='quiz_duration_10')], # Corrected
        [InlineKeyboardButton("15 دقائق", callback_data='quiz_duration_15')], # Corrected
        [InlineKeyboardButton("20 دقائق", callback_data='quiz_duration_20')], # Corrected
        [InlineKeyboardButton("30 دقائق", callback_data='quiz_duration_30')], # Corrected
        [InlineKeyboardButton("بدون وقت محدد", callback_data='quiz_duration_0')], # Corrected
        [InlineKeyboardButton("🔙 العودة لاختيار النوع", callback_data='menu_quiz')] # Corrected
    ]
    return InlineKeyboardMarkup(keyboard)

def create_grade_levels_keyboard(for_quiz=False, context=None):
    grades = QUIZ_DB.get_all_grade_levels()
    keyboard = []
    if grades:
        for grade_id, grade_name in grades:
            callback_data = f'select_grade_quiz_{grade_id}' if for_quiz else f'admin_grade_{grade_id}' # Corrected
            keyboard.append([InlineKeyboardButton(grade_name, callback_data=callback_data)])
    else:
        logger.info("No grade levels found in the database.")

    back_callback = 'menu_quiz' if for_quiz else 'admin_manage_structure' # Corrected
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_chapters_keyboard(grade_level_id, for_quiz=False, for_lesson_selection=False, context=None):
    chapters = QUIZ_DB.get_chapters_by_grade(grade_level_id)
    keyboard = []
    if chapters:
        for chapter_id, chapter_name in chapters:
            if for_quiz:
                callback_data = f'select_chapter_quiz_{chapter_id}' # Corrected
            elif for_lesson_selection:
                 callback_data = f'select_lesson_chapter_{chapter_id}' # Corrected
            else: # Admin context
                callback_data = f'admin_chapter_{chapter_id}' # Corrected
            keyboard.append([InlineKeyboardButton(chapter_name, callback_data=callback_data)])
    else:
        logger.info(f"No chapters found for grade level {grade_level_id}.")

    # Determine correct back button logic based on context
    if for_quiz:
        back_callback = 'quiz_by_grade_prompt' # Back to grade selection for quiz
    elif for_lesson_selection:
        back_callback = 'quiz_by_grade_prompt' # Back to grade selection for lesson quiz
    else: # Admin context
        back_callback = 'admin_manage_grades' # Back to grade management

    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_lessons_keyboard(chapter_id, for_quiz=False, context=None):
    lessons = QUIZ_DB.get_lessons_by_chapter(chapter_id)
    keyboard = []
    if lessons:
        for lesson_id, lesson_name in lessons:
            callback_data = f'select_lesson_quiz_{lesson_id}' if for_quiz else f'admin_lesson_{lesson_id}' # Corrected
            keyboard.append([InlineKeyboardButton(lesson_name, callback_data=callback_data)])
    else:
        logger.info(f"No lessons found for chapter {chapter_id}.")

    # Determine correct back button logic based on context
    if for_quiz:
        # Need the grade_level_id to go back to chapter selection for that grade
        # This requires passing grade_level_id or storing it in user_data
        # For simplicity, going back to the main quiz menu for now
        back_callback = 'quiz_by_chapter_prompt' # Or store grade_id and go back to chapter list
    else: # Admin context
        back_callback = 'admin_manage_chapters' # Back to chapter management

    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_quiz_question_keyboard(options, question_id, question_index):
    keyboard = []
    shuffled_options = list(enumerate(options))
    random.shuffle(shuffled_options)
    for original_index, option_text in shuffled_options:
        # Ensure option_text is a string
        option_display = str(option_text) if option_text is not None else ""
        callback_data = f'answer_{question_id}_{original_index}_{question_index}' # Corrected
        keyboard.append([InlineKeyboardButton(option_display, callback_data=callback_data)])
    keyboard.append([InlineKeyboardButton("⏭️ تخطي السؤال", callback_data=f'skip_{question_id}_{question_index}')]) # Corrected
    return InlineKeyboardMarkup(keyboard)

def create_results_menu_keyboard(quiz_id):
    keyboard = [
        [InlineKeyboardButton("🔄 اختبار جديد", callback_data='menu_quiz')], # Corrected
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data='main_menu')] # Corrected
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Integrated Info Menu Functions (Corrected callback_data) ---
def create_info_menu_keyboard():
    """Creates the info menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("🧪 العناصر الكيميائية", callback_data='info_elements')], # Corrected
        [InlineKeyboardButton("🔬 المركبات الكيميائية", callback_data='info_compounds')], # Corrected
        [InlineKeyboardButton("📘 المفاهيم الكيميائية", callback_data='info_concepts')], # Corrected
        [InlineKeyboardButton("📊 الجدول الدوري", callback_data='info_periodic_table')], # Corrected
        [InlineKeyboardButton("🔢 الحسابات الكيميائية", callback_data='info_calculations')], # Corrected
        [InlineKeyboardButton("🔗 الروابط الكيميائية", callback_data='info_bonds')], # Corrected
        [InlineKeyboardButton("📜 أهم قوانين التحصيلي", callback_data='info_laws')], # Corrected
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')] # Corrected
    ]
    return InlineKeyboardMarkup(keyboard)

def handle_info_menu(update: Update, context: CallbackContext):
    """Handles showing the info menu."""
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    message_id = query.message.message_id

    text = "اختر أحد أقسام المعلومات الكيميائية:"
    keyboard = create_info_menu_keyboard()
    safe_edit_message_text(query, text=text, reply_markup=keyboard)
    return INFO_MENU

def handle_info_selection(update: Update, context: CallbackContext):
    """Handles selection from the info menu."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    selection = query.data

    content = ""
    title = ""

    if selection == 'info_elements':
        title = "🧪 العناصر الكيميائية"
        content = "\n".join([f"**{k}:** {v}" for k, v in ELEMENTS.items()]) if ELEMENTS else "لا توجد بيانات حالياً."
    elif selection == 'info_compounds':
        title = "🔬 المركبات الكيميائية"
        content = "\n".join([f"**{k}:** {v}" for k, v in COMPOUNDS.items()]) if COMPOUNDS else "لا توجد بيانات حالياً."
    elif selection == 'info_concepts':
        title = "📘 المفاهيم الكيميائية"
        content = "\n".join([f"**{k}:** {v}" for k, v in CONCEPTS.items()]) if CONCEPTS else "لا توجد بيانات حالياً."
    elif selection == 'info_periodic_table':
        title = "📊 الجدول الدوري"
        content = PERIODIC_TABLE_INFO if PERIODIC_TABLE_INFO else "لا توجد بيانات حالياً."
    elif selection == 'info_calculations':
        title = "🔢 الحسابات الكيميائية"
        content = CHEMICAL_CALCULATIONS_INFO if CHEMICAL_CALCULATIONS_INFO else "لا توجد بيانات حالياً."
    elif selection == 'info_bonds':
        title = "🔗 الروابط الكيميائية"
        content = CHEMICAL_BONDS_INFO if CHEMICAL_BONDS_INFO else "لا توجد بيانات حالياً."
    elif selection == 'info_laws':
        title = "📜 أهم قوانين التحصيلي"
        try:
            with open("chemistry_laws_content.md", "r", encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            logger.error("chemistry_laws_content.md not found!")
            content = "عذراً، لم يتم العثور على ملف محتوى القوانين."
        except Exception as e:
            logger.error(f"Error reading chemistry_laws_content.md: {e}")
            content = "عذراً، حدث خطأ أثناء قراءة محتوى القوانين."
    else:
        content = "اختيار غير صالح."

    # Process content for chemical notation if needed
    processed_content = process_text_with_chemical_notation(content)
    text = f"""*{title}*\n\n{processed_content}"""
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]])
    safe_edit_message_text(query, text=text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    return INFO_MENU

# --- Quiz Interaction Functions (Corrected Dictionary Access) ---

def start_quiz(chat_id, user_id, quiz_type, filter_id, duration_minutes, context):
    """Starts a new quiz based on selected parameters."""
    logger.info(f"Starting quiz for user {user_id}: type={quiz_type}, filter={filter_id}, duration={duration_minutes}")
    user_data = context.user_data

    # Fetch questions based on type and filter
    questions = []
    num_questions = DEFAULT_QUIZ_QUESTIONS # Default, can be adjusted

    if quiz_type == 'random':
        questions = QUIZ_DB.get_random_questions(limit=num_questions)
    elif quiz_type == 'grade':
        questions = QUIZ_DB.get_questions_by_grade(filter_id, limit=num_questions)
    elif quiz_type == 'chapter':
        questions = QUIZ_DB.get_questions_by_chapter(filter_id, limit=num_questions)
    elif quiz_type == 'lesson':
        questions = QUIZ_DB.get_questions_by_lesson(filter_id, limit=num_questions)

    if not questions:
        safe_send_message(context.bot, chat_id, text="عذراً، لم يتم العثور على أسئلة لهذا الاختيار. الرجاء المحاولة مرة أخرى أو اختيار نوع آخر.")
        # Go back to quiz menu or appropriate state
        quiz_menu(Update(0, message=context.bot.get_chat(chat_id).get_member(user_id).user), context) # Simulate update to show menu
        return ConversationHandler.END # Or return to QUIZ_MENU

    quiz_id = int(time.time() * 1000) # Unique enough ID based on timestamp
    start_time = time.time()

    quiz_data = {
        "quiz_id": quiz_id,
        "questions": questions,
        "current_question_index": 0,
        "answers": {},
        "score": 0,
        "start_time": start_time,
        "duration_minutes": duration_minutes,
        "quiz_type": quiz_type,
        "filter_id": filter_id,
        "timed_out": False,
        "quiz_timer_job_name": None,
        "question_timer_job_name": None
    }

    # Set overall quiz timer if duration is specified
    quiz_data["quiz_timer_job_name"] = set_quiz_timer(context, chat_id, user_id, quiz_id, duration_minutes)

    user_data["current_quiz"] = quiz_data # Corrected

    safe_send_message(context.bot, chat_id, text=f"🚀 تم بدء الاختبار! عدد الأسئلة: {len(questions)}.")
    display_question(chat_id, user_id, quiz_id, 0, context)
    return TAKING_QUIZ

def display_question(chat_id, user_id, quiz_id, question_index, context):
    """Displays the specified question to the user."""
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz") # Corrected

    if not quiz_data or quiz_data["quiz_id"] != quiz_id: # Corrected
        logger.warning(f"Quiz data mismatch or not found for quiz {quiz_id} in display_question.")
        safe_send_message(context.bot, chat_id, text="حدث خطأ أثناء عرض السؤال. الرجاء بدء اختبار جديد.")
        return MAIN_MENU # Or appropriate state

    if question_index >= len(quiz_data["questions"]): # Corrected
        logger.info(f"All questions answered for quiz {quiz_id}. Showing results.")
        show_results(chat_id, user_id, quiz_id, context)
        return SHOWING_RESULTS

    quiz_data["current_question_index"] = question_index # Corrected
    question = quiz_data["questions"][question_index] # Corrected
    question_id = question["id"] # Corrected
    question_text = question["question_text"] # Corrected
    options = [
        question["option1"], # Corrected
        question["option2"], # Corrected
        question["option3"], # Corrected
        question["option4"]  # Corrected
    ]
    image_data = question.get("image_data") # Corrected

    # Process question text for chemical notation
    processed_question_text = process_text_with_chemical_notation(question_text)

    text = f"""*السؤال {question_index + 1} من {len(quiz_data['questions'])}:*

{processed_question_text}"""
    keyboard = create_quiz_question_keyboard(options, question_id, question_index)

    # Set question timer if enabled
    quiz_data["question_timer_job_name"] = set_question_timer(context, chat_id, user_id, quiz_id, question_index) # Corrected

    # Send question with or without image
    if image_data:
        try:
            photo = BytesIO(image_data)
            # Send photo first, then text with keyboard
            context.bot.send_photo(chat_id=chat_id, photo=photo)
            safe_send_message(context.bot, chat_id, text=text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Error sending question image for question {question_id}: {e}")
            # Fallback to sending text only
            safe_send_message(context.bot, chat_id, text=text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    else:
        safe_send_message(context.bot, chat_id, text=text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

    return TAKING_QUIZ

def handle_quiz_answer(update: Update, context: CallbackContext):
    """Handles user's answer to a quiz question."""
    query = update.callback_query
    query.answer() # Acknowledge callback
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    message_id = query.message.message_id

    user_data = context.user_data
    quiz_data = user_data.get("current_quiz") # Corrected

    if not quiz_data:
        safe_edit_message_text(query, text="لم يتم العثور على اختبار نشط. الرجاء بدء اختبار جديد.")
        return MAIN_MENU

    # Extract info from callback_data: answer_{q_id}_{opt_idx}_{q_idx}
    try:
        _, q_id_str, selected_option_idx_str, q_idx_str = query.data.split('_')
        question_id = int(q_id_str)
        selected_option_idx = int(selected_option_idx_str)
        question_index = int(q_idx_str)
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing quiz answer callback_data '{query.data}': {e}")
        safe_edit_message_text(query, text="حدث خطأ في معالجة إجابتك.")
        return TAKING_QUIZ

    quiz_id = quiz_data["quiz_id"] # Corrected

    # --- Input Validation ---
    # Check if the answer is for the current question
    if question_index != quiz_data.get("current_question_index"): # Corrected
        logger.warning(f"User {user_id} answered question {question_index}, but current is {quiz_data.get('current_question_index')}. Ignoring.")
        # Optionally send a message like "لقد تم تجاوز هذا السؤال"
        return TAKING_QUIZ

    # Check if the question ID matches
    current_question = quiz_data["questions"][question_index] # Corrected
    if question_id != current_question["id"]: # Corrected
        logger.error(f"Question ID mismatch in answer callback! Expected {current_question['id']}, got {question_id}.")
        safe_edit_message_text(query, text="حدث خطأ في مزامنة السؤال. سيتم تخطي هذا السؤال.")
        handle_quiz_skip(chat_id, user_id, quiz_id, question_index, context)
        return TAKING_QUIZ

    # --- Process Answer --- 
    # Remove timers for the current question
    if quiz_data.get("question_timer_job_name"): # Corrected
        remove_job_if_exists(quiz_data["question_timer_job_name"], context) # Corrected
        quiz_data["question_timer_job_name"] = None # Corrected

    correct_answer_db_index = current_question["correct_answer"] # Corrected (1-based index from DB)
    # Convert DB index (1-4) to 0-based index used in options list
    correct_option_idx = correct_answer_db_index - 1

    is_correct = (selected_option_idx == correct_option_idx)

    # Store the answer (selected index and correctness)
    quiz_data["answers"][question_index] = {"selected": selected_option_idx, "correct": is_correct} # Corrected

    feedback_text = ""
    if is_correct:
        quiz_data["score"] += 1 # Corrected
        feedback_text = "✅ إجابة صحيحة!" 
    else:
        feedback_text = "❌ إجابة خاطئة."
        explanation = current_question.get("explanation") # Corrected
        if explanation:
            feedback_text += f"\n*الشرح:* {explanation}"

    # Edit the original question message to show feedback (remove keyboard)
    original_question_text = query.message.text # Get the original text
    safe_edit_message_text(query, text=f"{original_question_text}\n\n---\n*{feedback_text}*", reply_markup=None, parse_mode=ParseMode.MARKDOWN)

    # Schedule the next question display after a short delay
    context.job_queue.run_once(
        lambda ctx: display_question(chat_id, user_id, quiz_id, question_index + 1, ctx),
        FEEDBACK_DELAY,
        context=context # Pass the main context
    )

    return TAKING_QUIZ

def handle_quiz_skip(chat_id, user_id, quiz_id, question_index, context, timed_out=False):
    """Handles skipping a question, either by user or timeout."""
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz") # Corrected

    if not quiz_data or quiz_data["quiz_id"] != quiz_id: # Corrected
        logger.warning(f"Quiz data mismatch or not found for quiz {quiz_id} in handle_quiz_skip.")
        # Avoid sending message if called internally from timeout where message was already sent
        if not timed_out:
             safe_send_message(context.bot, chat_id, text="لم يتم العثور على اختبار نشط.")
        return MAIN_MENU

    # --- Input Validation ---
    # Check if the skip is for the current question
    if question_index != quiz_data.get("current_question_index"): # Corrected
        logger.warning(f"User {user_id} skipped question {question_index}, but current is {quiz_data.get('current_question_index')}. Ignoring.")
        return TAKING_QUIZ

    # --- Process Skip --- 
    # Remove timers for the current question
    if quiz_data.get("question_timer_job_name"): # Corrected
        remove_job_if_exists(quiz_data["question_timer_job_name"], context) # Corrected
        quiz_data["question_timer_job_name"] = None # Corrected

    # Mark question as skipped in answers
    quiz_data["answers"][question_index] = {"selected": None, "correct": False, "skipped": True} # Corrected

    feedback_text = "⏭️ تم تخطي السؤال."

    # Edit the original question message if triggered by user callback
    if not timed_out and isinstance(context, CallbackContext) and hasattr(context, 'update') and context.update.callback_query:
        query = context.update.callback_query
        query.answer()
        original_question_text = query.message.text
        safe_edit_message_text(query, text=f"{original_question_text}\n\n---\n*{feedback_text}*", reply_markup=None, parse_mode=ParseMode.MARKDOWN)
    elif not timed_out: # If called internally but not timeout (e.g., error handling)
        # We might not have a message to edit, just proceed
        pass
    # If timed_out, message was already sent by timer callback

    # Schedule the next question display after a short delay
    context.job_queue.run_once(
        lambda ctx: display_question(chat_id, user_id, quiz_id, question_index + 1, ctx),
        FEEDBACK_DELAY,
        context=context # Pass the main context
    )

    return TAKING_QUIZ

def handle_quiz_skip_callback(update: Update, context: CallbackContext):
    """Handles the callback query when user presses the skip button."""
    query = update.callback_query
    chat_id = query.message.chat_id
    user_id = query.from_user.id

    user_data = context.user_data
    quiz_data = user_data.get("current_quiz") # Corrected

    if not quiz_data:
        query.answer("لا يوجد اختبار نشط!")
        safe_edit_message_text(query, text="لم يتم العثور على اختبار نشط. الرجاء بدء اختبار جديد.")
        return MAIN_MENU

    # Extract info from callback_data: skip_{q_id}_{q_idx}
    try:
        _, q_id_str, q_idx_str = query.data.split('_')
        question_id = int(q_id_str)
        question_index = int(q_idx_str)
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing quiz skip callback_data '{query.data}': {e}")
        query.answer("خطأ في معالجة الطلب")
        return TAKING_QUIZ

    quiz_id = quiz_data["quiz_id"] # Corrected

    # Call the main skip handler, passing the callback context
    return handle_quiz_skip(chat_id, user_id, quiz_id, question_index, context, timed_out=False)


def show_results(chat_id, user_id, quiz_id, context, timed_out=False):
    """Calculates and displays the quiz results."""
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz") # Corrected

    if not quiz_data or quiz_data["quiz_id"] != quiz_id: # Corrected
        logger.warning(f"Quiz data mismatch or not found for quiz {quiz_id} in show_results.")
        # Avoid sending message if called internally from timeout where message was already sent
        if not timed_out:
            safe_send_message(context.bot, chat_id, text="لم يتم العثور على نتائج لهذا الاختبار.")
        return MAIN_MENU # Or appropriate state

    # --- Finalize Quiz --- 
    # Remove any remaining timers
    if quiz_data.get("quiz_timer_job_name"): # Corrected
        remove_job_if_exists(quiz_data["quiz_timer_job_name"], context) # Corrected
    if quiz_data.get("question_timer_job_name"): # Corrected
        remove_job_if_exists(quiz_data["question_timer_job_name"], context) # Corrected

    end_time = time.time()
    time_taken_seconds = int(end_time - quiz_data["start_time"]) # Corrected
    total_questions = len(quiz_data["questions"]) # Corrected
    score = quiz_data["score"] # Corrected
    answers_data = quiz_data["answers"] # Corrected

    correct_count = score
    incorrect_count = 0
    skipped_count = 0

    for idx in range(total_questions):
        answer_info = answers_data.get(idx)
        if answer_info is None: # Question wasn't reached (e.g., quiz timed out early)
            skipped_count += 1
        elif answer_info.get("skipped"):
            skipped_count += 1
        elif not answer_info.get("correct"):
            incorrect_count += 1

    # Ensure counts add up
    if correct_count + incorrect_count + skipped_count != total_questions:
         logger.warning(f"Result count mismatch for quiz {quiz_id}: C={correct_count}, I={incorrect_count}, S={skipped_count}, Total={total_questions}")
         # Adjust skipped count as the most likely discrepancy
         skipped_count = total_questions - correct_count - incorrect_count

    percentage = (correct_count / total_questions) * 100.0 if total_questions > 0 else 0.0

    # --- Format Results Message --- 
    time_str = time.strftime("%M:%S", time.gmtime(time_taken_seconds))
    result_message = f"🏁 *نتائج الاختبار* 🏁\n\n"
    if timed_out:
        result_message += "⚠️ *انتهى وقت الاختبار المحدد!*\n\n"

    result_message += f"🔢 إجمالي الأسئلة: {total_questions}\n"
    result_message += f"✅ الإجابات الصحيحة: {correct_count}\n"
    result_message += f"❌ الإجابات الخاطئة: {incorrect_count}\n"
    result_message += f"⏭️ الأسئلة المتخطاة: {skipped_count}\n"
    result_message += f"⏱️ الوقت المستغرق: {time_str}\n"
    result_message += f"🎯 النسبة المئوية: {percentage:.2f}%\n\n"

    # Add encouragement
    if percentage >= 85:
        result_message += "🎉 ممتاز! أداء رائع!"
    elif percentage >= 70:
        result_message += "👍 جيد جداً! استمر في التقدم!"
    elif percentage >= 50:
        result_message += "💪 لا بأس! يمكنك التحسن مع المزيد من المراجعة."
    else:
        result_message += "📖 تحتاج إلى المزيد من المذاكرة. لا تيأس!"

    # --- Save Results --- 
    quiz_type = quiz_data.get("quiz_type", "unknown") # Corrected
    filter_id = quiz_data.get("filter_id") # Corrected
    try:
        save_success = QUIZ_DB.save_quiz_result(
            quiz_id=quiz_id,
            user_id=user_id,
            score=correct_count,
            total_questions=total_questions,
            time_taken_seconds=time_taken_seconds,
            quiz_type=quiz_type,
            filter_id=filter_id
        )
        if save_success:
            logger.info(f"Successfully saved results for quiz {quiz_id}, user {user_id}.")
        else:
            logger.error(f"Failed to save results for quiz {quiz_id}, user {user_id}.")
    except Exception as e:
        logger.error(f"Exception saving quiz results for quiz {quiz_id}: {e}")

    # --- Display Results and Cleanup --- 
    keyboard = create_results_menu_keyboard(quiz_id)
    safe_send_message(context.bot, chat_id, text=result_message, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

    # Clean up quiz data from user_data
    if "current_quiz" in user_data: # Corrected
        del user_data["current_quiz"] # Corrected
        logger.info(f"Cleaned up quiz data for user {user_id}.")

    return SHOWING_RESULTS

# --- Quiz Selection Handlers (Corrected Dictionary Access & Logic) ---

def quiz_menu(update: Update, context: CallbackContext):
    """Displays the main quiz menu."""
    query = update.callback_query
    user_id = query.from_user.id
    text = "اختر نوع الاختبار الذي تريده:"
    keyboard = create_quiz_menu_keyboard()
    safe_edit_message_text(query, text=text, reply_markup=keyboard)
    return SELECTING_QUIZ_TYPE

def prompt_quiz_duration(update: Update, context: CallbackContext):
    """Asks the user to select the quiz duration."""
    query = update.callback_query
    query.answer()
    quiz_type = query.data.split('_', 1)[1] # e.g., 'random_prompt' -> 'random_prompt'

    # Store the base type (random, grade, chapter, lesson)
    if quiz_type.startswith('random'):
        context.user_data['quiz_selection'] = {'type': 'random'} # Corrected
        text = "اختر مدة الاختبار العشوائي:"
        keyboard = create_quiz_duration_keyboard()
        safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECTING_QUIZ_DURATION
    elif quiz_type.startswith('by_grade'):
        context.user_data['quiz_selection'] = {'type': 'grade'} # Corrected
        # Show grade level selection first
        return prompt_grade_level(update, context, for_quiz=True)
    elif quiz_type.startswith('by_chapter'):
        context.user_data['quiz_selection'] = {'type': 'chapter'} # Corrected
        # Show grade level selection first (to select chapter within grade)
        return prompt_grade_level(update, context, for_quiz=True, next_step='chapter')
    elif quiz_type.startswith('by_lesson'):
        context.user_data['quiz_selection'] = {'type': 'lesson'} # Corrected
        # Show grade level selection first (to select lesson within chapter within grade)
        return prompt_grade_level(update, context, for_quiz=True, next_step='lesson')
    else:
        logger.warning(f"Unknown quiz type prompt: {quiz_type}")
        safe_edit_message_text(query, text="اختيار غير صالح.")
        return QUIZ_MENU

def prompt_grade_level(update: Update, context: CallbackContext, for_quiz=False, next_step=None):
    """Prompts user to select a grade level."""
    query = update.callback_query
    if query: query.answer()

    # Store the next step if provided (e.g., 'chapter', 'lesson')
    if next_step:
        context.user_data.setdefault('quiz_selection', {})['next_step'] = next_step # Corrected

    text = "اختر المرحلة الدراسية:"
    keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
    if query:
        safe_edit_message_text(query, text=text, reply_markup=keyboard)
    else: # If called directly without a query
        safe_send_message(context.bot, update.effective_chat.id, text=text, reply_markup=keyboard)
    return SELECT_GRADE_LEVEL_FOR_QUIZ

def prompt_chapter(update: Update, context: CallbackContext):
    """Prompts user to select a chapter after selecting a grade."""
    query = update.callback_query
    query.answer()
    try:
        grade_level_id = int(query.data.split('_')[-1])
    except (ValueError, IndexError):
        logger.error(f"Could not parse grade_level_id from callback: {query.data}")
        safe_edit_message_text(query, text="حدث خطأ. الرجاء المحاولة مرة أخرى.")
        return SELECT_GRADE_LEVEL_FOR_QUIZ

    context.user_data.setdefault('quiz_selection', {})['grade_id'] = grade_level_id # Corrected

    quiz_selection = context.user_data.get('quiz_selection', {}) # Corrected
    quiz_type = quiz_selection.get('type') # Corrected
    next_step = quiz_selection.get('next_step') # Corrected

    if quiz_type == 'grade': # If quiz is by grade, proceed to duration
        text = f"اختر مدة الاختبار للمرحلة المحددة:"
        keyboard = create_quiz_duration_keyboard()
        safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECTING_QUIZ_DURATION
    elif next_step == 'chapter' or next_step == 'lesson': # Need to select chapter
        text = "اختر الفصل:"
        # Pass for_lesson_selection=True if the final target is a lesson
        keyboard = create_chapters_keyboard(grade_level_id, for_quiz=False, for_lesson_selection=(next_step == 'lesson'), context=context)
        safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_CHAPTER_FOR_QUIZ # State for selecting chapter for quiz/lesson
    else:
        logger.error(f"Invalid state in prompt_chapter: quiz_type={quiz_type}, next_step={next_step}")
        safe_edit_message_text(query, text="حدث خطأ في تحديد الخطوة التالية.")
        return QUIZ_MENU

def prompt_lesson(update: Update, context: CallbackContext):
    """Prompts user to select a lesson after selecting a chapter."""
    query = update.callback_query
    query.answer()
    try:
        # Callback can be select_lesson_chapter_{id} or select_chapter_quiz_{id}
        if query.data.startswith('select_lesson_chapter_'):
             chapter_id = int(query.data.split('_')[-1])
        elif query.data.startswith('select_chapter_quiz_'):
             chapter_id = int(query.data.split('_')[-1])
        else:
             raise ValueError("Invalid callback prefix")
    except (ValueError, IndexError):
        logger.error(f"Could not parse chapter_id from callback: {query.data}")
        safe_edit_message_text(query, text="حدث خطأ. الرجاء المحاولة مرة أخرى.")
        return SELECT_CHAPTER_FOR_QUIZ

    context.user_data.setdefault('quiz_selection', {})['chapter_id'] = chapter_id # Corrected

    quiz_selection = context.user_data.get('quiz_selection', {}) # Corrected
    quiz_type = quiz_selection.get('type') # Corrected
    next_step = quiz_selection.get('next_step') # Corrected

    if quiz_type == 'chapter': # If quiz is by chapter, proceed to duration
        text = f"اختر مدة الاختبار للفصل المحدد:"
        keyboard = create_quiz_duration_keyboard()
        safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECTING_QUIZ_DURATION
    elif next_step == 'lesson': # Need to select lesson
        text = "اختر الدرس:"
        keyboard = create_lessons_keyboard(chapter_id, for_quiz=True, context=context)
        safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_LESSON_FOR_QUIZ # State for selecting lesson for quiz
    else:
        logger.error(f"Invalid state in prompt_lesson: quiz_type={quiz_type}, next_step={next_step}")
        safe_edit_message_text(query, text="حدث خطأ في تحديد الخطوة التالية.")
        return QUIZ_MENU

def handle_lesson_selection_for_quiz(update: Update, context: CallbackContext):
    """Handles final lesson selection and prompts for duration."""
    query = update.callback_query
    query.answer()
    try:
        lesson_id = int(query.data.split('_')[-1])
    except (ValueError, IndexError):
        logger.error(f"Could not parse lesson_id from callback: {query.data}")
        safe_edit_message_text(query, text="حدث خطأ. الرجاء المحاولة مرة أخرى.")
        return SELECT_LESSON_FOR_QUIZ

    context.user_data.setdefault('quiz_selection', {})['lesson_id'] = lesson_id # Corrected

    text = f"اختر مدة الاختبار للدرس المحدد:"
    keyboard = create_quiz_duration_keyboard()
    safe_edit_message_text(query, text=text, reply_markup=keyboard)
    return SELECTING_QUIZ_DURATION

def handle_quiz_duration_selection(update: Update, context: CallbackContext):
    """Handles the selection of quiz duration and starts the quiz."""
    query = update.callback_query
    query.answer()
    chat_id = query.message.chat_id
    user_id = query.from_user.id

    try:
        duration_minutes = int(query.data.split('_')[-1])
    except (ValueError, IndexError):
        logger.error(f"Could not parse duration from callback: {query.data}")
        safe_edit_message_text(query, text="حدث خطأ. الرجاء اختيار مدة صالحة.")
        return SELECTING_QUIZ_DURATION

    quiz_selection = context.user_data.get('quiz_selection') # Corrected
    if not quiz_selection:
        logger.error(f"Quiz selection data not found for user {user_id} in duration handler.")
        safe_edit_message_text(query, text="حدث خطأ في بيانات الاختبار. الرجاء البدء من جديد.")
        return QUIZ_MENU

    quiz_type = quiz_selection.get('type') # Corrected
    filter_id = None
    if quiz_type == 'grade':
        filter_id = quiz_selection.get('grade_id') # Corrected
    elif quiz_type == 'chapter':
        filter_id = quiz_selection.get('chapter_id') # Corrected
    elif quiz_type == 'lesson':
        filter_id = quiz_selection.get('lesson_id') # Corrected

    # Clear the selection data now that we have everything
    # del context.user_data['quiz_selection']

    # Edit message to show confirmation before starting
    safe_edit_message_text(query, text="جاري تجهيز الاختبار...", reply_markup=None)

    # Start the quiz
    return start_quiz(chat_id, user_id, quiz_type, filter_id, duration_minutes, context)

# --- Back Button Handlers for Quiz Selection ---

def handle_quiz_selection_back(update: Update, context: CallbackContext):
    """Handles various back buttons during quiz selection."""
    query = update.callback_query
    callback_data = query.data

    if callback_data == 'quiz_selection_back_to_grades':
        # Go back to grade selection
        return prompt_grade_level(update, context, for_quiz=True)
    elif callback_data == 'quiz_selection_back_to_chapters':
        # Go back to chapter selection (needs grade_id)
        quiz_selection = context.user_data.get('quiz_selection', {}) # Corrected
        grade_id = quiz_selection.get('grade_id') # Corrected
        if grade_id:
             query.answer()
             text = "اختر الفصل:"
             keyboard = create_chapters_keyboard(grade_id, for_quiz=False, for_lesson_selection=(quiz_selection.get('next_step') == 'lesson'), context=context)
             safe_edit_message_text(query, text=text, reply_markup=keyboard)
             return SELECT_CHAPTER_FOR_QUIZ
        else:
             # Fallback if grade_id is lost
             logger.warning("Grade ID not found in user_data for back_to_chapters.")
             return quiz_menu(update, context)
    else:
        # Default back action (e.g., from duration selection)
        return quiz_menu(update, context)

# --- Main Menu and Start --- 

def start(update: Update, context: CallbackContext):
    """Sends a welcome message and the main menu."""
    user = update.effective_user
    user_id = user.id
    username = user.username
    first_name = user.first_name
    last_name = user.last_name

    # Add or update user in DB
    QUIZ_DB.add_or_update_user(user_id, username, first_name, last_name)

    user_display_name = get_user_name(user)
    text = f"أهلاً بك يا {user_display_name} في بوت الكيمياء التعليمي! 👋\n\nماذا تريد أن تفعل اليوم؟"
    keyboard = create_main_menu_keyboard(user_id)
    safe_send_message(context.bot, update.effective_chat.id, text=text, reply_markup=keyboard)
    return MAIN_MENU

def main_menu_callback(update: Update, context: CallbackContext):
    """Handles returning to the main menu via callback."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    text = "القائمة الرئيسية. ماذا تريد أن تفعل؟"
    keyboard = create_main_menu_keyboard(user_id)
    safe_edit_message_text(query, text=text, reply_markup=keyboard)
    return MAIN_MENU

# --- Placeholder Handlers --- 

def handle_reports(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    safe_edit_message_text(query, text="📊 قسم تقارير الأداء قيد التطوير حالياً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]])) # Corrected
    return MAIN_MENU

def handle_about(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    text = """ℹ️ *حول البوت*

هذا البوت مصمم لمساعدتك في دراسة الكيمياء من خلال:
- اختبارات متنوعة (تحصيلي، حسب الفصل، الدرس، المرحلة).
- معلومات كيميائية مفيدة (عناصر، مركبات، مفاهيم، قوانين).
- (قريباً) تقارير أداء لتتبع تقدمك.

تم التطوير بواسطة الاستاذ حسين الموسى."""
    safe_edit_message_text(query, text=text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]])) # Corrected
    return MAIN_MENU

def handle_admin_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if not is_admin(query.from_user.id):
        safe_edit_message_text(query, text="عذراً، هذه المنطقة مخصصة للمشرف فقط.", reply_markup=create_main_menu_keyboard(query.from_user.id))
        return MAIN_MENU
    text = "⚙️ قائمة إدارة البوت:"
    keyboard = create_admin_menu_keyboard()
    safe_edit_message_text(query, text=text, reply_markup=keyboard)
    return ADMIN_MENU

def handle_admin_structure_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if not is_admin(query.from_user.id):
        return MAIN_MENU # Redirect non-admins
    text = "🏫 إدارة المراحل/الفصول/الدروس:"
    keyboard = create_structure_admin_menu_keyboard()
    safe_edit_message_text(query, text=text, reply_markup=keyboard)
    return ADMIN_MANAGE_STRUCTURE

# --- Error Handler --- 
def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # Optionally inform user about the error
    # if update and update.effective_chat:
    #     safe_send_message(context.bot, update.effective_chat.id, text="عذرًا، حدث خطأ ما. الرجاء المحاولة مرة أخرى لاحقًا.")

# --- Main Function --- 
def main() -> None:
    """Start the bot."""
    # Create the Updater and pass it your bot's token.
    updater = Updater(BOT_TOKEN)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # --- Conversation Handler Setup ---
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(quiz_menu, pattern='^menu_quiz$'),
                CallbackQueryHandler(handle_info_menu, pattern='^menu_info$'),
                CallbackQueryHandler(handle_reports, pattern='^menu_reports$'),
                CallbackQueryHandler(handle_about, pattern='^menu_about$'),
                CallbackQueryHandler(handle_admin_menu, pattern='^menu_admin$'),
            ],
            QUIZ_MENU: [
                CallbackQueryHandler(prompt_quiz_duration, pattern='^quiz_random_prompt$'),
                CallbackQueryHandler(prompt_quiz_duration, pattern='^quiz_by_chapter_prompt$'),
                CallbackQueryHandler(prompt_quiz_duration, pattern='^quiz_by_lesson_prompt$'),
                CallbackQueryHandler(prompt_quiz_duration, pattern='^quiz_by_grade_prompt$'),
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'),
            ],
            SELECTING_QUIZ_TYPE: [ # State after selecting 'Quiz Menu'
                CallbackQueryHandler(prompt_quiz_duration, pattern='^quiz_random_prompt$'),
                CallbackQueryHandler(prompt_grade_level, pattern='^quiz_by_grade_prompt$'),
                CallbackQueryHandler(prompt_grade_level, pattern='^quiz_by_chapter_prompt$'), # Go to grade first
                CallbackQueryHandler(prompt_grade_level, pattern='^quiz_by_lesson_prompt$'), # Go to grade first
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'),
            ],
            SELECT_GRADE_LEVEL_FOR_QUIZ: [
                CallbackQueryHandler(prompt_chapter, pattern='^select_grade_quiz_\d+$'),
                CallbackQueryHandler(quiz_menu, pattern='^menu_quiz$'), # Back button from grade list
            ],
            SELECT_CHAPTER_FOR_QUIZ: [
                CallbackQueryHandler(prompt_lesson, pattern='^select_chapter_quiz_\d+$'), # If quiz type is chapter
                CallbackQueryHandler(prompt_lesson, pattern='^select_lesson_chapter_\d+$'), # If quiz type is lesson
                CallbackQueryHandler(handle_quiz_selection_back, pattern='^quiz_selection_back_to_grades$'), # Back button
            ],
            SELECT_LESSON_FOR_QUIZ: [
                CallbackQueryHandler(handle_lesson_selection_for_quiz, pattern='^select_lesson_quiz_\d+$'),
                CallbackQueryHandler(handle_quiz_selection_back, pattern='^quiz_selection_back_to_chapters$'), # Back button
            ],
            SELECTING_QUIZ_DURATION: [
                CallbackQueryHandler(handle_quiz_duration_selection, pattern='^quiz_duration_\d+$'),
                CallbackQueryHandler(quiz_menu, pattern='^menu_quiz$'), # Back button from duration list
            ],
            TAKING_QUIZ: [
                CallbackQueryHandler(handle_quiz_answer, pattern='^answer_\d+_\d+_\d+$'),
                CallbackQueryHandler(handle_quiz_skip_callback, pattern='^skip_\d+_\d+$'),
                # Add handler for potential unexpected messages?
            ],
            SHOWING_RESULTS: [
                 CallbackQueryHandler(quiz_menu, pattern='^menu_quiz$'),
                 CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'),
            ],
            INFO_MENU: [
                CallbackQueryHandler(handle_info_selection, pattern='^info_'),
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'),
            ],
            ADMIN_MENU: [
                # Add admin action handlers here (add/delete/show question, manage structure)
                # CallbackQueryHandler(prompt_add_question, pattern='^admin_add_question$'),
                # CallbackQueryHandler(prompt_delete_question, pattern='^admin_delete_question$'),
                # CallbackQueryHandler(prompt_show_question, pattern='^admin_show_question$'),
                CallbackQueryHandler(handle_admin_structure_menu, pattern='^admin_manage_structure$'),
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'),
            ],
            ADMIN_MANAGE_STRUCTURE: [
                # CallbackQueryHandler(handle_manage_grades, pattern='^admin_manage_grades$'),
                # CallbackQueryHandler(handle_manage_chapters, pattern='^admin_manage_chapters$'),
                # CallbackQueryHandler(handle_manage_lessons, pattern='^admin_manage_lessons$'),
                CallbackQueryHandler(handle_admin_menu, pattern='^menu_admin$'), # Back to admin menu
            ],
            # Add other admin states (ADDING_QUESTION, etc.) as needed
        },
        fallbacks=[CommandHandler('start', start)], # Allow restarting
        # per_user=True, per_chat=False # Default is True, True
    )

    dp.add_handler(conv_handler)

    # Log all errors
    dp.add_error_handler(error_handler)

    # --- Webhook Setup for Render ---
    if APP_NAME:
        # Running on Render (or similar PaaS)
        logger.info(f"Starting webhook for Render app {APP_NAME}")
        updater.start_webhook(listen="0.0.0.0",
                              port=PORT,
                              url_path=BOT_TOKEN,
                              webhook_url=f"https://{APP_NAME}.onrender.com/{BOT_TOKEN}")
        # Pass dispatcher to context for timer callbacks
        dp.bot_data["dispatcher"] = dp
        logger.info(f"Webhook set to https://{APP_NAME}.onrender.com/{BOT_TOKEN}")
    else:
        # Running locally
        logger.info("Starting bot locally using polling.")
        # Pass dispatcher to context for timer callbacks
        dp.bot_data["dispatcher"] = dp
        updater.start_polling()

    logger.info("Bot started and running...")
    updater.idle()

if __name__ == '__main__':
    main()

