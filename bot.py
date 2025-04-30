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
    ReplyKeyboardRemove
)
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    CallbackQueryHandler,
    ConversationHandler,
)
from telegram.error import BadRequest, TelegramError

# --- Configuration & Constants ---

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get sensitive info from environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL") # Defined globally here
ADMIN_USER_IDS = [int(uid.strip()) for uid in os.environ.get("ADMIN_USER_IDS", "").split(",") if uid.strip().isdigit()]
PORT = int(os.environ.get("PORT", 8443))
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME")

# Quiz settings
DEFAULT_QUIZ_QUESTIONS = 10
QUIZ_DURATIONS = { # seconds
    "short": 300,  # 5 minutes
    "medium": 600, # 10 minutes
    "long": 900,   # 15 minutes
}
FEEDBACK_DELAY = 2 # seconds before showing correct answer

# --- Database Setup ---
try:
    from db_utils import connect_db, setup_database
    from quiz_db import QuizDatabase
    # استيراد الدالة المساعدة لمعالجة الأخطاء بأمان
    from helper_function import safe_edit_message_text
except ImportError as e:
    logger.error(f"Failed to import database modules: {e}. Make sure db_utils.py and quiz_db.py are present.")
    sys.exit("Critical import error, stopping bot.")

# استيراد البيانات الثابتة ووظائف المعادلات
try:
    from chemistry_equations import get_equation_details, ALL_EQUATIONS
    # Assuming chemistry_data.py contains dictionaries/lists for elements, compounds etc.
    # from chemistry_data import ELEMENTS, COMPOUNDS, CONCEPTS # Example import
except ImportError:
    logger.warning("Could not import chemistry_equations.py or chemistry_data.py. Equation/Data features might be limited.")
    ALL_EQUATIONS = {}
    # ELEMENTS, COMPOUNDS, CONCEPTS = {}, {}, {} # Define as empty if import fails

# Initialize database connection and QuizDatabase instance
# Check if DATABASE_URL was fetched successfully before using it
if not DATABASE_URL:
    logger.error("DATABASE_URL environment variable not set or empty. Bot cannot connect to DB.")
    sys.exit("Database configuration error.")

DB_CONN = connect_db(DATABASE_URL) # Use the globally defined variable
if DB_CONN:
    setup_database(DB_CONN)
    QUIZ_DB = QuizDatabase(DB_CONN)
else:
    logger.error("Failed to establish database connection. Bot cannot function properly.")
    sys.exit("Database connection failed.")

# --- States for Conversation Handler ---
MAIN_MENU, QUIZ_MENU, ADMIN_MENU, SELECTING_QUIZ_DURATION, SELECT_GRADE_LEVEL_FOR_QUIZ, SELECT_CHAPTER_FOR_QUIZ, SELECT_CHAPTER_FOR_LESSON, SELECT_LESSON_FOR_QUIZ, RUNNING_QUIZ, VIEWING_RESULTS, ADDING_QUESTION, ADDING_OPTIONS, ADDING_CORRECT_OPTION, ADDING_IMAGE, ADDING_GRADE_LEVEL, ADDING_CHAPTER, ADDING_LESSON, DELETING_QUESTION, SHOWING_QUESTION, ADMIN_MANAGE_STRUCTURE, ADMIN_MANAGE_GRADES, ADMIN_MANAGE_CHAPTERS, ADMIN_MANAGE_LESSONS, INFO_MENU = range(24) # Added INFO_MENU state



from info_menu_function import show_info_menu
from info_handlers import info_menu_conv_handler # Import the handler

# --- Helper Functions ---

def is_admin(user_id):
    """Check if a user is an admin."""
    return user_id in ADMIN_USER_IDS

def get_user_name(user):
    """Get user's full name or username."""
    if user.first_name and user.last_name:
        return f"{user.first_name} {user.last_name}"
    elif user.first_name:
        return user.first_name
    elif user.username:
        return user.username
    else:
        return str(user.id)

# --- Keyboard Creation Functions ---

def create_main_menu_keyboard(user_id):
    """Creates the main menu inline keyboard."""
    keyboard = [
        [InlineKeyboardButton("📚 المعلومات الكيميائية", callback_data="menu_info")],
        [InlineKeyboardButton("📝 الاختبارات", callback_data="menu_quiz")],
        [InlineKeyboardButton("📊 تقارير الأداء", callback_data="menu_reports")],
        [InlineKeyboardButton("ℹ️ حول البوت", callback_data="menu_about")],
    ]
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ إدارة البوت", callback_data="menu_admin")])
    return InlineKeyboardMarkup(keyboard)

def create_quiz_menu_keyboard():
    """Creates the quiz type selection inline keyboard."""
    keyboard = [
        [InlineKeyboardButton("🎲 اختبار عشوائي", callback_data="quiz_random_prompt")],
        [InlineKeyboardButton("🎓 حسب المرحلة الدراسية", callback_data="quiz_by_grade_prompt")],
        [InlineKeyboardButton("📖 حسب الفصل", callback_data="quiz_by_chapter_prompt")],
        [InlineKeyboardButton("📄 حسب الدرس", callback_data="quiz_by_lesson_prompt")],
        # [InlineKeyboardButton("🧐 مراجعة الأخطاء", callback_data="quiz_review_prompt")], # Future feature
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_quiz_duration_keyboard():
    """Creates the quiz duration selection inline keyboard."""
    keyboard = [
        [InlineKeyboardButton("⏱️ قصير (5 دقائق)", callback_data="duration_short")],
        [InlineKeyboardButton("⏱️ متوسط (10 دقائق)", callback_data="duration_medium")],
        [InlineKeyboardButton("⏱️ طويل (15 دقائق)", callback_data="duration_long")],
        [InlineKeyboardButton("🔙 إلغاء", callback_data="menu_quiz")] # Go back to quiz menu
    ]
    return InlineKeyboardMarkup(keyboard)

def create_grade_levels_keyboard(for_quiz=False, context=None):
    """Creates keyboard for selecting grade levels, optionally for quizzes."""
    grades = QUIZ_DB.get_all_grade_levels()
    keyboard = []
    if grades:
        for grade_id, grade_name in grades:
            callback_suffix = f"quiz_{grade_id}" if for_quiz else f"admin_{grade_id}"
            keyboard.append([InlineKeyboardButton(grade_name, callback_data=f"grade_{callback_suffix}")])
        if for_quiz:
             # Add an option for a general test across all grades
             keyboard.append([InlineKeyboardButton("📚 اختبار تحصيلي عام", callback_data="grade_quiz_all")])
    else:
        logger.info("No grade levels found in the database.")
        # Return None or an empty list if no grades exist
        return None

    # Add back button
    back_callback = "menu_quiz" if for_quiz else "admin_manage_structure"
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_chapters_keyboard(grade_level_id, for_quiz=False, for_lesson=False, context=None):
    """Creates keyboard for selecting chapters within a grade level."""
    chapters = QUIZ_DB.get_chapters_by_grade(grade_level_id)
    keyboard = []
    if chapters:
        for chapter_id, chapter_name in chapters:
            if for_quiz:
                callback_data = f"chapter_quiz_{chapter_id}"
            elif for_lesson:
                 callback_data = f"lesson_chapter_{chapter_id}" # For selecting chapter before lesson
            else: # Admin context
                callback_data = f"admin_chapter_{chapter_id}"
            keyboard.append([InlineKeyboardButton(chapter_name, callback_data=callback_data)])
    else:
        logger.info(f"No chapters found for grade level {grade_level_id}.")
        return None

    # Add back button
    if for_quiz or for_lesson:
        back_callback = "quiz_by_grade_prompt" # Go back to grade selection
    else: # Admin context
        back_callback = "admin_manage_structure"
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_lessons_keyboard(chapter_id, for_quiz=False, context=None):
    """Creates keyboard for selecting lessons within a chapter."""
    lessons = QUIZ_DB.get_lessons_by_chapter(chapter_id)
    keyboard = []
    if lessons:
        for lesson_id, lesson_name in lessons:
            callback_data = f"lesson_quiz_{lesson_id}" if for_quiz else f"admin_lesson_{lesson_id}"
            keyboard.append([InlineKeyboardButton(lesson_name, callback_data=callback_data)])
    else:
        logger.info(f"No lessons found for chapter {chapter_id}.")
        return None

    # Add back button
    if for_quiz:
        # Go back to chapter selection for lesson quiz
        # back_callback = "quiz_by_lesson_prompt" # Original, maybe less intuitive
        # Let's go back to the chapter selection prompt for the specific grade
        grade_id = context.user_data.get("selected_grade_id_for_lesson_quiz") # Use specific key
        if grade_id:
             # We need to trigger the chapter selection for this grade again.
             # The callback `grade_quiz_{grade_id}` expects to be in QUIZ_MENU state.
             # Let's just go back to the main quiz menu for simplicity for now.
             # back_callback = f"grade_quiz_{grade_id}" # This might require state adjustment
             back_callback = "quiz_by_lesson_prompt" # Go back to chapter selection prompt
        else:
             back_callback = "quiz_by_lesson_prompt" # Fallback

    else: # Admin context
        back_callback = "admin_manage_structure"
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def create_admin_menu_keyboard():
    """Creates the admin menu inline keyboard."""
    keyboard = [
        [InlineKeyboardButton("➕ إضافة سؤال", callback_data="admin_add_question")],
        [InlineKeyboardButton("🗑️ حذف سؤال", callback_data="admin_delete_question")],
        [InlineKeyboardButton("👁️ عرض سؤال", callback_data="admin_show_question")],
        [InlineKeyboardButton("🏗️ إدارة الهيكل الدراسي", callback_data="admin_manage_structure")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_structure_admin_menu_keyboard():
     """Creates the structure management admin menu."""
     keyboard = [
         [InlineKeyboardButton("🎓 إدارة المراحل", callback_data="admin_manage_grades")],
         [InlineKeyboardButton("📖 إدارة الفصول", callback_data="admin_manage_chapters")],
         [InlineKeyboardButton("📄 إدارة الدروس", callback_data="admin_manage_lessons")],
         [InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data="menu_admin")]
     ]
     return InlineKeyboardMarkup(keyboard)

def create_quiz_question_keyboard(options, question_id):
    """Creates the keyboard for a multiple-choice quiz question."""
    keyboard = []
    # Shuffle options for display, but keep track of original index for callback
    shuffled_options = list(enumerate(options))
    random.shuffle(shuffled_options)

    for original_index, option_text in shuffled_options:
        # Callback data format: answer_{question_id}_{selected_option_index}
        callback_data = f"answer_{question_id}_{original_index}"
        keyboard.append([InlineKeyboardButton(option_text, callback_data=callback_data)])

    # Add a button to skip the question
    keyboard.append([InlineKeyboardButton("⏭️ تخطي السؤال", callback_data=f"skip_{question_id}")])
    return InlineKeyboardMarkup(keyboard)

def create_results_menu_keyboard(quiz_id):
    """Creates keyboard for quiz results view."""
    keyboard = [
        # [InlineKeyboardButton("🧐 مراجعة الأخطاء", callback_data=f"review_{quiz_id}")], # Future feature
        [InlineKeyboardButton("🔄 إعادة الاختبار", callback_data="menu_quiz")], # Go back to quiz menu
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Command Handlers ---

def start(update: Update, context: CallbackContext) -> int:
    """Sends a welcome message and the main menu."""
    user = update.effective_user
    user_id = user.id
    name = get_user_name(user)
    logger.info(f"User {name} (ID: {user_id}) started the bot.")

    # Store or update user info in the database
    QUIZ_DB.add_or_update_user(user_id, user.username, user.first_name, user.last_name)
    context.user_data["user_id"] = user_id # Store user_id in context

    welcome_text = f"أهلاً بك يا {name} في بوت الكيمياء التعليمي! 👋\n\n"
    welcome_text += "استخدم الأزرار أدناه للتنقل بين الأقسام المختلفة."

    keyboard = create_main_menu_keyboard(user_id)
    update.message.reply_text(welcome_text, reply_markup=keyboard)

    return MAIN_MENU

def cancel(update: Update, context: CallbackContext) -> int:
    """Cancels the current operation and returns to the main menu."""
    user = update.effective_user
    user_id = user.id
    logger.info(f"User {user_id} canceled operation.")

    # Check if there's an active quiz timer and remove it
    job_name = f"quiz_timer_{user_id}"
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    if current_jobs:
        for job in current_jobs:
            job.schedule_removal()
        logger.info(f"Removed active quiz timer job for user {user_id}.")

    # Check if there's an active feedback timer and remove it
    feedback_job_name = f"feedback_timer_{user_id}"
    feedback_jobs = context.job_queue.get_jobs_by_name(feedback_job_name)
    if feedback_jobs:
        for job in feedback_jobs:
            job.schedule_removal()
        logger.info(f"Removed active feedback timer job for user {user_id}.")

    # Send cancellation message
    update.message.reply_text(
        "تم إلغاء العملية الحالية. العودة إلى القائمة الرئيسية.",
        reply_markup=create_main_menu_keyboard(user_id)
    )

    # Clear potentially sensitive user_data from previous operations
    keys_to_clear = [k for k in context.user_data if k not in ["user_id"]]
    for key in keys_to_clear:
        del context.user_data[key]

    return MAIN_MENU

def help_command(update: Update, context: CallbackContext):
    """Displays help information."""
    user = update.effective_user
    help_text = "مرحباً! أنا بوت الكيمياء التعليمي. يمكنك استخدامي لـ:\n"
    help_text += "- 📚 تصفح المعلومات الكيميائية.\n"  # تم التفعيل
    help_text += "- 📝 إجراء اختبارات في مواضيع مختلفة.\n"
    help_text += "- 📊 مراجعة أدائك في الاختبارات (قيد التطوير).\n\n"
    help_text += "استخدم الأوامر التالية:\n"
    help_text += "/start - لبدء البوت أو العودة للقائمة الرئيسية.\n"
    help_text += "/help - لعرض هذه الرسالة.\n"
    help_text += "/cancel - لإلغاء أي عملية جارية والعودة للقائمة الرئيسية.\n\n"
    help_text += "استخدم الأزرار التي تظهر لك للتنقل بين الأقسام."
    # يمكنك إضافة المزيد من عناصر المساعدة هنا إذا لزم الأمر
    # إرسال رسالة المساعدة مع لوحة مفاتيح القائمة الرئيسية
    update.message.reply_text(help_text, reply_markup=create_main_menu_keyboard(user.id))
    return MAIN_MENU # Ensure state returns to main menu if called mid-conversation

# --- Callback Query Handlers ---

def main_menu_callback(update: Update, context: CallbackContext) -> int:
    """Handles main menu button presses."""
    query = update.callback_query
    query.answer() # Answer the callback query
    user = query.from_user
    user_id = user.id
    data = query.data

    logger.info(f"User {user_id} chose {data} from main menu.")

    # Ensure user_id is in context if conversation was restarted
    if "user_id" not in context.user_data:
        context.user_data["user_id"] = user_id

    if data == 'menu_info':
        # Transition to the INFO_MENU state handled by the info_menu_conv_handler
        # We need to initiate the info menu conversation here
        return show_info_menu(update, context) # This function should return INFO_MENU
    elif data == 'menu_quiz':
        safe_edit_message_text(query,
            text="اختر نوع الاختبار الذي تريده:",
            reply_markup=create_quiz_menu_keyboard()
        )
        return QUIZ_MENU
    elif data == 'menu_reports':
        safe_edit_message_text(query, text="ميزة تقارير الأداء قيد التطوير حالياً. 🚧")
        return MAIN_MENU # Stay in main menu
    elif data == 'menu_about':
        about_text = "بوت الكيمياء التعليمي\n"
        about_text += "تم تطوير هذا البوت لمساعدتك في تعلم الكيمياء وإجراء الاختبارات.\n"
        about_text += "الإصدار: 1.1 (مع قائمة المعلومات وقاعدة البيانات الأساسية)\n"
        about_text += "للمساعدة، استخدم الأمر /help."
        safe_edit_message_text(query, text=about_text, reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU # Stay in main menu
    elif data == 'menu_admin':
        if is_admin(user_id):
            safe_edit_message_text(query,
                text="قائمة الإدارة:",
                reply_markup=create_admin_menu_keyboard()
            )
            return ADMIN_MENU
        else:
            query.answer("ليس لديك صلاحيات للوصول لهذه القائمة.", show_alert=True)
            return MAIN_MENU # Stay in main menu
    else:
        # Handle unexpected callback data in main menu
        logger.warning(f"Unexpected callback data '{data}' received in MAIN_MENU state.")
        safe_edit_message_text(query, text="حدث خطأ غير متوقع. العودة للقائمة الرئيسية.", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU

def quiz_menu_callback(update: Update, context: CallbackContext) -> int:
    """Handles quiz menu button presses."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    logger.info(f"User {user_id} chose {data} from quiz menu.")

    if data == 'main_menu':
        safe_edit_message_text(query, text="القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU
    elif data == 'quiz_random_prompt':
        # Ask for duration for random quiz
        safe_edit_message_text(query,
            text="اختر مدة الاختبار العشوائي:",
            reply_markup=create_quiz_duration_keyboard()
        )
        context.user_data['quiz_type'] = 'random'
        return SELECTING_QUIZ_DURATION
    elif data == 'quiz_by_grade_prompt':
        # Show grade levels to choose from
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
        if keyboard:
            safe_edit_message_text(query,
                text="اختر المرحلة الدراسية للاختبار:",
                reply_markup=keyboard
            )
            return SELECT_GRADE_LEVEL_FOR_QUIZ
        else:
            safe_edit_message_text(query, text="لم يتم إضافة أي مراحل دراسية بعد. يرجى التواصل مع المشرف.", reply_markup=create_quiz_menu_keyboard())
            return QUIZ_MENU # Stay in quiz menu
    elif data == 'quiz_by_chapter_prompt':
         # First, ask for grade level, then chapter
         keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
         if keyboard:
             safe_edit_message_text(query,
                 text="أولاً، اختر المرحلة الدراسية التي ينتمي إليها الفصل:",
                 reply_markup=keyboard
             )
             context.user_data['quiz_selection_mode'] = 'chapter' # Remember why we are selecting grade
             return SELECT_GRADE_LEVEL_FOR_QUIZ # Go to grade selection first
         else:
             safe_edit_message_text(query, text="لم يتم إضافة أي مراحل دراسية بعد.", reply_markup=create_quiz_menu_keyboard())
             return QUIZ_MENU
    elif data == 'quiz_by_lesson_prompt':
         # First, ask for grade level, then chapter, then lesson
         keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
         if keyboard:
             safe_edit_message_text(query,
                 text="أولاً، اختر المرحلة الدراسية التي ينتمي إليها الدرس:",
                 reply_markup=keyboard
             )
             context.user_data['quiz_selection_mode'] = 'lesson' # Remember why we are selecting grade
             return SELECT_GRADE_LEVEL_FOR_QUIZ # Go to grade selection first
         else:
             safe_edit_message_text(query, text="لم يتم إضافة أي مراحل دراسية بعد.", reply_markup=create_quiz_menu_keyboard())
             return QUIZ_MENU
    # elif data == 'quiz_review_prompt':
    #     safe_edit_message_text(query, text="ميزة مراجعة الأخطاء قيد التطوير. 🚧", reply_markup=create_quiz_menu_keyboard())
    #     return QUIZ_MENU
    else:
        logger.warning(f"Unexpected callback data '{data}' received in QUIZ_MENU state.")
        safe_edit_message_text(query, text="خيار غير معروف. العودة لقائمة الاختبارات.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

def select_quiz_duration_callback(update: Update, context: CallbackContext) -> int:
    """Handles quiz duration selection."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    logger.info(f"User {user_id} chose duration {data}.")

    if data.startswith('duration_'):
        duration_key = data.split('_')[1]
        if duration_key in QUIZ_DURATIONS:
            context.user_data['quiz_duration'] = QUIZ_DURATIONS[duration_key]
            quiz_type = context.user_data.get('quiz_type')
            quiz_filter_id = context.user_data.get('quiz_filter_id') # Grade, Chapter, Lesson ID or 'all'

            # Start the quiz immediately after duration selection
            return start_quiz(update, context, quiz_type, quiz_filter_id)
        else:
            logger.warning(f"Invalid duration key '{duration_key}' received.")
            safe_edit_message_text(query, text="مدة غير صالحة. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_duration_keyboard())
            return SELECTING_QUIZ_DURATION
    elif data == 'menu_quiz':
        # Go back to quiz menu
        safe_edit_message_text(query, text="اختر نوع الاختبار:", reply_markup=create_quiz_menu_keyboard())
        # Clear potentially set quiz type/filter if user goes back
        context.user_data.pop('quiz_type', None)
        context.user_data.pop('quiz_filter_id', None)
        return QUIZ_MENU
    else:
        logger.warning(f"Unexpected callback data '{data}' received in SELECTING_QUIZ_DURATION state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_quiz_duration_keyboard())
        return SELECTING_QUIZ_DURATION

def select_grade_level_for_quiz_callback(update: Update, context: CallbackContext) -> int:
    """Handles grade level selection for quizzes or further filtering."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    logger.info(f"User {user_id} selected grade level option: {data}")

    selection_mode = context.user_data.get('quiz_selection_mode') # 'chapter' or 'lesson'

    if data.startswith('grade_quiz_'):
        grade_id_str = data.split('_')[-1]

        if grade_id_str == 'all':
            # General comprehensive test across all grades
            context.user_data['quiz_type'] = 'grade'
            context.user_data['quiz_filter_id'] = 'all'
            context.user_data['selected_grade_name'] = 'كل المراحل (اختبار تحصيلي)'
            # Ask for duration
            safe_edit_message_text(query,
                text="اختر مدة الاختبار التحصيلي العام:",
                reply_markup=create_quiz_duration_keyboard()
            )
            return SELECTING_QUIZ_DURATION
        else:
            try:
                grade_id = int(grade_id_str)
                grade_name = QUIZ_DB.get_grade_level_name(grade_id) # Fetch name for context
                if not grade_name:
                     raise ValueError("Grade ID not found")

                context.user_data['selected_grade_id'] = grade_id
                context.user_data['selected_grade_name'] = grade_name

                if selection_mode == 'chapter':
                    # User wants to select a chapter within this grade
                    keyboard = create_chapters_keyboard(grade_id, for_quiz=True, context=context)
                    if keyboard:
                        safe_edit_message_text(query,
                            text=f"اختر الفصل للاختبار ضمن '{grade_name}':",
                            reply_markup=keyboard
                        )
                        return SELECT_CHAPTER_FOR_QUIZ
                    else:
                        safe_edit_message_text(query, text=f"لا توجد فصول متاحة للمرحلة '{grade_name}'.", reply_markup=create_quiz_menu_keyboard())
                        return QUIZ_MENU
                elif selection_mode == 'lesson':
                    # User wants to select a lesson, need chapter first
                    # Store grade_id specifically for lesson selection flow
                    context.user_data['selected_grade_id_for_lesson_quiz'] = grade_id
                    keyboard = create_chapters_keyboard(grade_id, for_lesson=True, context=context)
                    if keyboard:
                        safe_edit_message_text(query,
                            text=f"اختر الفصل الذي ينتمي إليه الدرس ضمن '{grade_name}':",
                            reply_markup=keyboard
                        )
                        return SELECT_CHAPTER_FOR_LESSON # Go to chapter selection for lesson
                    else:
                        safe_edit_message_text(query, text=f"لا توجد فصول متاحة للمرحلة '{grade_name}'.", reply_markup=create_quiz_menu_keyboard())
                        return QUIZ_MENU
                else:
                    # Default: Quiz by grade level, ask for duration
                    context.user_data['quiz_type'] = 'grade'
                    context.user_data['quiz_filter_id'] = grade_id
                    safe_edit_message_text(query,
                        text=f"اختر مدة الاختبار للمرحلة '{grade_name}':",
                        reply_markup=create_quiz_duration_keyboard()
                    )
                    return SELECTING_QUIZ_DURATION

            except (ValueError, TypeError) as e:
                logger.error(f"Invalid grade ID extracted from callback data '{data}': {e}")
                safe_edit_message_text(query, text="حدث خطأ في تحديد المرحلة. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_menu_keyboard())
                return QUIZ_MENU

    elif data == 'menu_quiz':
        # Go back to quiz menu
        safe_edit_message_text(query, text="اختر نوع الاختبار:", reply_markup=create_quiz_menu_keyboard())
        context.user_data.pop('quiz_selection_mode', None)
        return QUIZ_MENU
    else:
        logger.warning(f"Unexpected callback data '{data}' received in SELECT_GRADE_LEVEL_FOR_QUIZ state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

def select_chapter_for_quiz_callback(update: Update, context: CallbackContext) -> int:
    """Handles chapter selection specifically for starting a chapter quiz."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    logger.info(f"User {user_id} selected chapter for quiz: {data}")

    if data.startswith('chapter_quiz_'):
        try:
            chapter_id = int(data.split('_')[-1])
            chapter_name = QUIZ_DB.get_chapter_name(chapter_id)
            if not chapter_name:
                raise ValueError("Chapter ID not found")

            context.user_data['quiz_type'] = 'chapter'
            context.user_data['quiz_filter_id'] = chapter_id
            context.user_data['selected_chapter_name'] = chapter_name
            grade_name = context.user_data.get('selected_grade_name', 'المرحلة المحددة')

            # Ask for duration
            safe_edit_message_text(query,
                text=f"اختر مدة الاختبار للفصل '{chapter_name}' (ضمن '{grade_name}'):",
                reply_markup=create_quiz_duration_keyboard()
            )
            return SELECTING_QUIZ_DURATION

        except (ValueError, TypeError) as e:
            logger.error(f"Invalid chapter ID extracted from callback data '{data}': {e}")
            # Go back to grade selection as chapter selection failed
            keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
            if keyboard:
                 safe_edit_message_text(query,
                     text="حدث خطأ في تحديد الفصل. اختر المرحلة الدراسية مرة أخرى:",
                     reply_markup=keyboard
                 )
                 return SELECT_GRADE_LEVEL_FOR_QUIZ
            else:
                 safe_edit_message_text(query, text="حدث خطأ ولم يتم العثور على مراحل.", reply_markup=create_quiz_menu_keyboard())
                 return QUIZ_MENU

    elif data == 'quiz_by_grade_prompt': # Back button goes to grade selection
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
        if keyboard:
            safe_edit_message_text(query,
                text="اختر المرحلة الدراسية للاختبار:",
                reply_markup=keyboard
            )
            # Clear selection mode as we are going back to grade selection
            context.user_data.pop('quiz_selection_mode', None)
            return SELECT_GRADE_LEVEL_FOR_QUIZ
        else:
            safe_edit_message_text(query, text="لم يتم إضافة أي مراحل دراسية بعد.", reply_markup=create_quiz_menu_keyboard())
            return QUIZ_MENU
    else:
        logger.warning(f"Unexpected callback data '{data}' received in SELECT_CHAPTER_FOR_QUIZ state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

def select_chapter_for_lesson_callback(update: Update, context: CallbackContext) -> int:
    """Handles chapter selection when the goal is to select a lesson."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    logger.info(f"User {user_id} selected chapter for lesson selection: {data}")

    if data.startswith('lesson_chapter_'): # Note the prefix difference
        try:
            chapter_id = int(data.split('_')[-1])
            chapter_name = QUIZ_DB.get_chapter_name(chapter_id)
            if not chapter_name:
                raise ValueError("Chapter ID not found")

            context.user_data['selected_chapter_id_for_lesson_quiz'] = chapter_id
            context.user_data['selected_chapter_name'] = chapter_name # Store for context
            grade_name = context.user_data.get('selected_grade_name', 'المرحلة المحددة')

            # Now show lessons for this chapter
            keyboard = create_lessons_keyboard(chapter_id, for_quiz=True, context=context)
            if keyboard:
                safe_edit_message_text(query,
                    text=f"اختر الدرس للاختبار ضمن الفصل '{chapter_name}' (المرحلة '{grade_name}'):",
                    reply_markup=keyboard
                )
                return SELECT_LESSON_FOR_QUIZ
            else:
                safe_edit_message_text(query, text=f"لا توجد دروس متاحة للفصل '{chapter_name}'.", reply_markup=create_quiz_menu_keyboard())
                return QUIZ_MENU

        except (ValueError, TypeError) as e:
            logger.error(f"Invalid chapter ID extracted from callback data '{data}': {e}")
            # Go back to grade selection
            keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
            if keyboard:
                 safe_edit_message_text(query,
                     text="حدث خطأ في تحديد الفصل. اختر المرحلة الدراسية مرة أخرى:",
                     reply_markup=keyboard
                 )
                 return SELECT_GRADE_LEVEL_FOR_QUIZ
            else:
                 safe_edit_message_text(query, text="حدث خطأ ولم يتم العثور على مراحل.", reply_markup=create_quiz_menu_keyboard())
                 return QUIZ_MENU

    elif data == 'quiz_by_grade_prompt': # Back button goes to grade selection
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
        if keyboard:
            safe_edit_message_text(query,
                text="اختر المرحلة الدراسية التي ينتمي إليها الدرس:",
                reply_markup=keyboard
            )
            # Keep selection_mode='lesson'
            return SELECT_GRADE_LEVEL_FOR_QUIZ
        else:
            safe_edit_message_text(query, text="لم يتم إضافة أي مراحل دراسية بعد.", reply_markup=create_quiz_menu_keyboard())
            return QUIZ_MENU
    else:
        logger.warning(f"Unexpected callback data '{data}' received in SELECT_CHAPTER_FOR_LESSON state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

def select_lesson_for_quiz_callback(update: Update, context: CallbackContext) -> int:
    """Handles lesson selection for starting a lesson quiz."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    logger.info(f"User {user_id} selected lesson for quiz: {data}")

    if data.startswith('lesson_quiz_'):
        try:
            lesson_id = int(data.split('_')[-1])
            lesson_name = QUIZ_DB.get_lesson_name(lesson_id)
            if not lesson_name:
                raise ValueError("Lesson ID not found")

            context.user_data['quiz_type'] = 'lesson'
            context.user_data['quiz_filter_id'] = lesson_id
            context.user_data['selected_lesson_name'] = lesson_name
            chapter_name = context.user_data.get('selected_chapter_name', 'الفصل المحدد')
            grade_name = context.user_data.get('selected_grade_name', 'المرحلة المحددة')

            # Ask for duration
            safe_edit_message_text(query,
                text=f"اختر مدة الاختبار للدرس '{lesson_name}' (ضمن '{chapter_name}' - '{grade_name}'):",
                reply_markup=create_quiz_duration_keyboard()
            )
            return SELECTING_QUIZ_DURATION

        except (ValueError, TypeError) as e:
            logger.error(f"Invalid lesson ID extracted from callback data '{data}': {e}")
            # Go back to chapter selection for the lesson
            grade_id = context.user_data.get('selected_grade_id_for_lesson_quiz')
            if grade_id:
                keyboard = create_chapters_keyboard(grade_id, for_lesson=True, context=context)
                if keyboard:
                    safe_edit_message_text(query,
                        text="حدث خطأ في تحديد الدرس. اختر الفصل مرة أخرى:",
                        reply_markup=keyboard
                    )
                    return SELECT_CHAPTER_FOR_LESSON
            # Fallback to quiz menu if going back fails
            safe_edit_message_text(query, text="حدث خطأ. العودة لقائمة الاختبارات.", reply_markup=create_quiz_menu_keyboard())
            return QUIZ_MENU

    elif data == 'quiz_by_lesson_prompt': # Back button should go back to chapter selection for lesson
         grade_id = context.user_data.get('selected_grade_id_for_lesson_quiz')
         if grade_id:
             keyboard = create_chapters_keyboard(grade_id, for_lesson=True, context=context)
             if keyboard:
                 grade_name = context.user_data.get('selected_grade_name', 'المرحلة المحددة')
                 safe_edit_message_text(query,
                     text=f"اختر الفصل الذي ينتمي إليه الدرس ضمن '{grade_name}':",
                     reply_markup=keyboard
                 )
                 return SELECT_CHAPTER_FOR_LESSON
         # Fallback if going back fails
         safe_edit_message_text(query, text="اختر نوع الاختبار:", reply_markup=create_quiz_menu_keyboard())
         return QUIZ_MENU
    else:
        logger.warning(f"Unexpected callback data '{data}' received in SELECT_LESSON_FOR_QUIZ state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU


def admin_menu_callback(update: Update, context: CallbackContext) -> int:
    """Handles admin menu button presses."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    if not is_admin(user_id):
        query.answer("ليس لديك صلاحيات.", show_alert=True)
        # Attempt to return to main menu gracefully
        try:
            safe_edit_message_text(query, text="القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))
        except BadRequest:
            logger.warning(f"Failed to edit message for non-admin {user_id} in admin_menu_callback.")
        return MAIN_MENU

    logger.info(f"Admin {user_id} chose {data} from admin menu.")

    if data == 'main_menu':
        safe_edit_message_text(query, text="القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU
    elif data == 'admin_add_question':
        # Start the process of adding a question
        # 1. Ask for the grade level
        keyboard = create_grade_levels_keyboard(for_quiz=False, context=context)
        if keyboard:
            safe_edit_message_text(query, text="اختر المرحلة الدراسية للسؤال الجديد:", reply_markup=keyboard)
            context.user_data['admin_flow'] = 'add_question'
            return ADMIN_MANAGE_GRADES # Reuse grade selection state
        else:
            safe_edit_message_text(query, text="يجب إضافة مرحلة دراسية أولاً.", reply_markup=create_admin_menu_keyboard())
            return ADMIN_MENU
    elif data == 'admin_delete_question':
        safe_edit_message_text(query, text="ميزة حذف الأسئلة قيد التطوير. 🚧", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU
    elif data == 'admin_show_question':
        safe_edit_message_text(query, text="ميزة عرض الأسئلة قيد التطوير. 🚧", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU
    elif data == 'admin_manage_structure':
        safe_edit_message_text(query, text="إدارة الهيكل الدراسي (المراحل، الفصول، الدروس):", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE
    else:
        logger.warning(f"Unexpected callback data '{data}' received in ADMIN_MENU state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU

def admin_manage_structure_callback(update: Update, context: CallbackContext) -> int:
    """Handles structure management menu button presses."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    if not is_admin(user_id):
        query.answer("ليس لديك صلاحيات.", show_alert=True)
        try:
            safe_edit_message_text(query, text="القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))
        except BadRequest:
            pass # Ignore if message already gone
        return MAIN_MENU

    logger.info(f"Admin {user_id} chose {data} from structure management menu.")

    if data == 'menu_admin':
        safe_edit_message_text(query, text="قائمة الإدارة:", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU
    elif data == 'admin_manage_grades':
        # Show existing grades + Add button
        grades = QUIZ_DB.get_all_grade_levels()
        text = "المراحل الدراسية الحالية:\n"
        if grades:
            text += "\n".join([f"- {name} (ID: {gid})" for gid, name in grades])
        else:
            text += "لا توجد مراحل دراسية حالياً.\n"
        text += "\nاختر مرحلة للتعديل أو اضغط لإضافة مرحلة جديدة."

        keyboard_list = []
        if grades:
            for grade_id, grade_name in grades:
                 # For now, just viewing, no edit action defined yet
                 # keyboard_list.append([InlineKeyboardButton(f"✏️ {grade_name}", callback_data=f"admin_edit_grade_{grade_id}")])
                 keyboard_list.append([InlineKeyboardButton(grade_name, callback_data=f"admin_view_grade_{grade_id}")]) # Placeholder view
        keyboard_list.append([InlineKeyboardButton("➕ إضافة مرحلة جديدة", callback_data="admin_add_grade_prompt")])
        keyboard_list.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_structure")])
        reply_markup = InlineKeyboardMarkup(keyboard_list)

        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        return ADMIN_MANAGE_GRADES

    elif data == 'admin_manage_chapters':
        # Need to select grade first
        keyboard = create_grade_levels_keyboard(for_quiz=False, context=context)
        if keyboard:
            safe_edit_message_text(query, text="اختر المرحلة الدراسية لعرض/إدارة فصولها:", reply_markup=keyboard)
            context.user_data['admin_flow'] = 'manage_chapters'
            return ADMIN_MANAGE_GRADES # Reuse grade selection state
        else:
            safe_edit_message_text(query, text="يجب إضافة مرحلة دراسية أولاً.", reply_markup=create_structure_admin_menu_keyboard())
            return ADMIN_MANAGE_STRUCTURE

    elif data == 'admin_manage_lessons':
        # Need to select grade first, then chapter
        keyboard = create_grade_levels_keyboard(for_quiz=False, context=context)
        if keyboard:
            safe_edit_message_text(query, text="اختر المرحلة الدراسية لعرض/إدارة دروسها:", reply_markup=keyboard)
            context.user_data['admin_flow'] = 'manage_lessons_select_grade'
            return ADMIN_MANAGE_GRADES # Reuse grade selection state
        else:
            safe_edit_message_text(query, text="يجب إضافة مرحلة دراسية أولاً.", reply_markup=create_structure_admin_menu_keyboard())
            return ADMIN_MANAGE_STRUCTURE
    else:
        logger.warning(f"Unexpected callback data '{data}' received in ADMIN_MANAGE_STRUCTURE state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE

def admin_manage_grades_callback(update: Update, context: CallbackContext) -> int:
    """Handles grade management actions (add prompt, selection for next step)."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data
    admin_flow = context.user_data.get('admin_flow')

    if not is_admin(user_id):
        query.answer("ليس لديك صلاحيات.", show_alert=True)
        return MAIN_MENU

    logger.info(f"Admin {user_id} in grade management: chose {data}, flow: {admin_flow}")

    if data == 'admin_add_grade_prompt':
        # Ask for the name of the new grade level
        query.message.reply_text("أرسل اسم المرحلة الدراسية الجديدة (مثال: الصف الأول الثانوي). للإلغاء أرسل /cancel.")
        return ADDING_GRADE_LEVEL

    elif data.startswith('admin_grade_'): # Selecting a grade for chapter/lesson management or adding question
        try:
            grade_id = int(data.split('_')[-1])
            grade_name = QUIZ_DB.get_grade_level_name(grade_id)
            if not grade_name:
                 raise ValueError("Grade ID not found")

            context.user_data['selected_admin_grade_id'] = grade_id
            context.user_data['selected_admin_grade_name'] = grade_name

            if admin_flow == 'manage_chapters':
                # Show chapters for this grade + Add button
                chapters = QUIZ_DB.get_chapters_by_grade(grade_id)
                text = f"الفصول الدراسية للمرحلة '{grade_name}':\n"
                if chapters:
                    text += "\n".join([f"- {name} (ID: {cid})" for cid, name in chapters])
                else:
                    text += "لا توجد فصول حالياً.\n"
                text += "\nاختر فصلاً للتعديل أو اضغط لإضافة فصل جديد."

                keyboard_list = []
                if chapters:
                    for chapter_id, chapter_name in chapters:
                        # keyboard_list.append([InlineKeyboardButton(f"✏️ {chapter_name}", callback_data=f"admin_edit_chapter_{chapter_id}")])
                        keyboard_list.append([InlineKeyboardButton(chapter_name, callback_data=f"admin_view_chapter_{chapter_id}")]) # Placeholder
                keyboard_list.append([InlineKeyboardButton("➕ إضافة فصل جديد", callback_data="admin_add_chapter_prompt")])
                keyboard_list.append([InlineKeyboardButton("🔙 رجوع للمراحل", callback_data="admin_manage_grades")]) # Go back to grade list
                reply_markup = InlineKeyboardMarkup(keyboard_list)

                safe_edit_message_text(query, text=text, reply_markup=reply_markup)
                return ADMIN_MANAGE_CHAPTERS

            elif admin_flow == 'manage_lessons_select_grade':
                # Now need to select chapter for this grade
                keyboard = create_chapters_keyboard(grade_id, for_quiz=False, context=context)
                if keyboard:
                    safe_edit_message_text(query, text=f"اختر الفصل ضمن '{grade_name}' لعرض/إدارة دروسه:", reply_markup=keyboard)
                    context.user_data['admin_flow'] = 'manage_lessons_select_chapter'
                    return ADMIN_MANAGE_CHAPTERS # Reuse chapter selection state
                else:
                    safe_edit_message_text(query, text=f"لا توجد فصول للمرحلة '{grade_name}'. أضف فصلاً أولاً.", reply_markup=create_structure_admin_menu_keyboard())
                    return ADMIN_MANAGE_STRUCTURE

            elif admin_flow == 'add_question':
                 # Grade selected for new question, now ask for chapter
                 keyboard = create_chapters_keyboard(grade_id, for_quiz=False, context=context)
                 if keyboard:
                     safe_edit_message_text(query, text=f"اختر الفصل الذي ينتمي إليه السؤال الجديد (ضمن '{grade_name}'):", reply_markup=keyboard)
                     context.user_data['admin_flow'] = 'add_question_select_chapter'
                     return ADMIN_MANAGE_CHAPTERS # Reuse chapter selection state
                 else:
                     safe_edit_message_text(query, text=f"لا توجد فصول للمرحلة '{grade_name}'. أضف فصلاً أولاً.", reply_markup=create_admin_menu_keyboard())
                     return ADMIN_MENU
            else:
                 # Default action if just viewing grades
                 safe_edit_message_text(query, text=f"تم اختيار المرحلة: {grade_name}. (لا يوجد إجراء محدد حالياً)", reply_markup=create_structure_admin_menu_keyboard())
                 return ADMIN_MANAGE_STRUCTURE

        except (ValueError, TypeError) as e:
            logger.error(f"Invalid grade ID from callback '{data}' in admin flow: {e}")
            safe_edit_message_text(query, text="خطأ في تحديد المرحلة.", reply_markup=create_structure_admin_menu_keyboard())
            return ADMIN_MANAGE_STRUCTURE

    elif data == 'admin_manage_structure': # Back button
        safe_edit_message_text(query, text="إدارة الهيكل الدراسي:", reply_markup=create_structure_admin_menu_keyboard())
        context.user_data.pop('admin_flow', None)
        return ADMIN_MANAGE_STRUCTURE
    elif data.startswith('admin_view_grade_'): # Placeholder for viewing/editing grade
         grade_id = int(data.split('_')[-1])
         grade_name = QUIZ_DB.get_grade_level_name(grade_id)
         safe_edit_message_text(query, text=f"المرحلة المحددة: {grade_name} (ID: {grade_id}).\n(ميزات التعديل والحذف قيد التطوير).", reply_markup=create_structure_admin_menu_keyboard())
         return ADMIN_MANAGE_STRUCTURE # Go back for now
    else:
        logger.warning(f"Unexpected callback data '{data}' received in ADMIN_MANAGE_GRADES state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE

def admin_manage_chapters_callback(update: Update, context: CallbackContext) -> int:
    """Handles chapter management actions (add prompt, selection for next step)."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data
    admin_flow = context.user_data.get('admin_flow')
    grade_id = context.user_data.get('selected_admin_grade_id')
    grade_name = context.user_data.get('selected_admin_grade_name', 'المرحلة المحددة')

    if not is_admin(user_id) or not grade_id:
        query.answer("خطأ: الصلاحيات أو المرحلة غير محددة.", show_alert=True)
        return MAIN_MENU

    logger.info(f"Admin {user_id} in chapter management (Grade: {grade_id}): chose {data}, flow: {admin_flow}")

    if data == 'admin_add_chapter_prompt':
        # Ask for the name of the new chapter
        query.message.reply_text(f"أرسل اسم الفصل الجديد للمرحلة '{grade_name}'. للإلغاء أرسل /cancel.")
        return ADDING_CHAPTER

    elif data.startswith('admin_chapter_'): # Selecting a chapter
        try:
            chapter_id = int(data.split('_')[-1])
            chapter_name = QUIZ_DB.get_chapter_name(chapter_id)
            if not chapter_name:
                 raise ValueError("Chapter ID not found")

            context.user_data['selected_admin_chapter_id'] = chapter_id
            context.user_data['selected_admin_chapter_name'] = chapter_name

            if admin_flow == 'manage_lessons_select_chapter':
                # Show lessons for this chapter + Add button
                lessons = QUIZ_DB.get_lessons_by_chapter(chapter_id)
                text = f"الدروس للفصل '{chapter_name}' (المرحلة '{grade_name}'):\n"
                if lessons:
                    text += "\n".join([f"- {name} (ID: {lid})" for lid, name in lessons])
                else:
                    text += "لا توجد دروس حالياً.\n"
                text += "\nاختر درساً للتعديل أو اضغط لإضافة درس جديد."

                keyboard_list = []
                if lessons:
                    for lesson_id, lesson_name in lessons:
                        # keyboard_list.append([InlineKeyboardButton(f"✏️ {lesson_name}", callback_data=f"admin_edit_lesson_{lesson_id}")])
                        keyboard_list.append([InlineKeyboardButton(lesson_name, callback_data=f"admin_view_lesson_{lesson_id}")]) # Placeholder
                keyboard_list.append([InlineKeyboardButton("➕ إضافة درس جديد", callback_data="admin_add_lesson_prompt")])
                # Go back to chapter list for the current grade
                keyboard_list.append([InlineKeyboardButton("🔙 رجوع للفصول", callback_data=f"admin_grade_{grade_id}")])
                reply_markup = InlineKeyboardMarkup(keyboard_list)

                safe_edit_message_text(query, text=text, reply_markup=reply_markup)
                context.user_data['admin_flow'] = 'manage_lessons' # Update flow status
                return ADMIN_MANAGE_LESSONS

            elif admin_flow == 'add_question_select_chapter':
                 # Chapter selected for new question, now ask for lesson (optional)
                 # For simplicity, let's assume questions are tied to chapters for now.
                 # Ask for the question text directly.
                 query.message.reply_text(f"تم اختيار الفصل '{chapter_name}'.\nالآن أرسل نص السؤال الجديد. للإلغاء أرسل /cancel.")
                 context.user_data['new_question'] = {'chapter_id': chapter_id}
                 return ADDING_QUESTION
            else:
                 # Default action if just viewing chapters
                 safe_edit_message_text(query, text=f"تم اختيار الفصل: {chapter_name}. (لا يوجد إجراء محدد حالياً)", reply_markup=create_structure_admin_menu_keyboard())
                 return ADMIN_MANAGE_STRUCTURE

        except (ValueError, TypeError) as e:
            logger.error(f"Invalid chapter ID from callback '{data}' in admin flow: {e}")
            safe_edit_message_text(query, text="خطأ في تحديد الفصل.", reply_markup=create_structure_admin_menu_keyboard())
            return ADMIN_MANAGE_STRUCTURE

    elif data == 'admin_manage_grades': # Back button from chapter list
        # Go back to grade list
        keyboard = create_grade_levels_keyboard(for_quiz=False, context=context)
        if keyboard:
            safe_edit_message_text(query, text="اختر المرحلة الدراسية لعرض/إدارة فصولها:", reply_markup=keyboard)
            # Reset flow to indicate we are back at grade selection for chapters
            context.user_data['admin_flow'] = 'manage_chapters'
            return ADMIN_MANAGE_GRADES
        else:
            safe_edit_message_text(query, text="لم يتم العثور على مراحل.", reply_markup=create_structure_admin_menu_keyboard())
            return ADMIN_MANAGE_STRUCTURE
    elif data.startswith('admin_view_chapter_'): # Placeholder for viewing/editing chapter
         chapter_id = int(data.split('_')[-1])
         chapter_name = QUIZ_DB.get_chapter_name(chapter_id)
         safe_edit_message_text(query, text=f"الفصل المحدد: {chapter_name} (ID: {chapter_id}).\n(ميزات التعديل والحذف قيد التطوير).", reply_markup=create_structure_admin_menu_keyboard())
         return ADMIN_MANAGE_STRUCTURE # Go back for now
    else:
        logger.warning(f"Unexpected callback data '{data}' received in ADMIN_MANAGE_CHAPTERS state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE

def admin_manage_lessons_callback(update: Update, context: CallbackContext) -> int:
    """Handles lesson management actions (add prompt, selection)."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data
    admin_flow = context.user_data.get('admin_flow')
    chapter_id = context.user_data.get('selected_admin_chapter_id')
    chapter_name = context.user_data.get('selected_admin_chapter_name', 'الفصل المحدد')
    grade_id = context.user_data.get('selected_admin_grade_id') # Needed for back button

    if not is_admin(user_id) or not chapter_id or not grade_id:
        query.answer("خطأ: الصلاحيات أو الفصل/المرحلة غير محددة.", show_alert=True)
        return MAIN_MENU

    logger.info(f"Admin {user_id} in lesson management (Chapter: {chapter_id}): chose {data}, flow: {admin_flow}")

    if data == 'admin_add_lesson_prompt':
        # Ask for the name of the new lesson
        query.message.reply_text(f"أرسل اسم الدرس الجديد للفصل '{chapter_name}'. للإلغاء أرسل /cancel.")
        return ADDING_LESSON

    elif data.startswith('admin_grade_'): # Back button goes back to chapter list for the grade
        # We need to reconstruct the chapter list view for the parent grade
        chapters = QUIZ_DB.get_chapters_by_grade(grade_id)
        grade_name = context.user_data.get('selected_admin_grade_name', 'المرحلة المحددة')
        text = f"الفصول الدراسية للمرحلة '{grade_name}':\n"
        if chapters:
            text += "\n".join([f"- {name} (ID: {cid})" for cid, name in chapters])
        else:
            text += "لا توجد فصول حالياً.\n"
        text += "\nاختر فصلاً للتعديل أو اضغط لإضافة فصل جديد."
        keyboard_list = []
        if chapters:
            for chap_id, chap_name in chapters:
                 keyboard_list.append([InlineKeyboardButton(chap_name, callback_data=f"admin_chapter_{chap_id}")])
        keyboard_list.append([InlineKeyboardButton("➕ إضافة فصل جديد", callback_data="admin_add_chapter_prompt")])
        keyboard_list.append([InlineKeyboardButton("🔙 رجوع للمراحل", callback_data="admin_manage_grades")])
        reply_markup = InlineKeyboardMarkup(keyboard_list)

        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
        # Set flow back to indicate we are selecting chapter for lesson management
        context.user_data['admin_flow'] = 'manage_lessons_select_chapter'
        return ADMIN_MANAGE_CHAPTERS

    elif data.startswith('admin_view_lesson_'): # Placeholder for viewing/editing lesson
         lesson_id = int(data.split('_')[-1])
         lesson_name = QUIZ_DB.get_lesson_name(lesson_id)
         safe_edit_message_text(query, text=f"الدرس المحدد: {lesson_name} (ID: {lesson_id}).\n(ميزات التعديل والحذف قيد التطوير).", reply_markup=create_structure_admin_menu_keyboard())
         return ADMIN_MANAGE_STRUCTURE # Go back for now
    else:
        logger.warning(f"Unexpected callback data '{data}' received in ADMIN_MANAGE_LESSONS state.")
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE

# --- Quiz Logic Handlers ---

def start_quiz(update: Update, context: CallbackContext, quiz_type: str, filter_id) -> int:
    """Fetches questions, starts the quiz, and sets the timer."""
    query = update.callback_query # Can be None if called directly
    if query:
        query.answer()
        user_id = query.from_user.id
    else:
        # Called directly, e.g., from a command - need user_id from context
        user_id = context.user_data.get("user_id")
        if not user_id:
             logger.error("Cannot start quiz: user_id not found in context.")
             if update.message: # If called from command
                  update.message.reply_text("حدث خطأ. لا يمكن بدء الاختبار.")
             return ConversationHandler.END # Or MAIN_MENU

    duration = context.user_data.get('quiz_duration', QUIZ_DURATIONS['medium']) # Default duration
    num_questions = DEFAULT_QUIZ_QUESTIONS # Or make this configurable

    logger.info(f"Starting quiz for user {user_id}. Type: {quiz_type}, Filter: {filter_id}, Duration: {duration}s, Questions: {num_questions}")

    # Fetch questions based on type and filter
    questions = QUIZ_DB.get_quiz_questions(quiz_type, filter_id, num_questions)

    if not questions:
        logger.warning(f"No questions found for quiz type '{quiz_type}' with filter '{filter_id}'.")
        error_message = "عذراً، لم يتم العثور على أسئلة كافية لهذا النوع من الاختبار حالياً. 😥"
        if query:
            safe_edit_message_text(query, text=error_message, reply_markup=create_quiz_menu_keyboard())
        elif update.message:
             update.message.reply_text(error_message, reply_markup=create_main_menu_keyboard(user_id))
        return QUIZ_MENU # Go back to quiz selection

    # Initialize quiz state in user_data
    context.user_data['quiz_questions'] = questions
    context.user_data['current_question_index'] = 0
    context.user_data['user_answers'] = {}
    context.user_data['quiz_start_time'] = datetime.now()
    context.user_data['quiz_end_time'] = datetime.now() + timedelta(seconds=duration)
    context.user_data['quiz_id'] = f"quiz_{user_id}_{int(datetime.now().timestamp())}" # Unique ID

    # Remove any existing timers for this user
    job_name = f"quiz_timer_{user_id}"
    feedback_job_name = f"feedback_timer_{user_id}"
    for job in context.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()
    for job in context.job_queue.get_jobs_by_name(feedback_job_name):
        job.schedule_removal()

    # Schedule the quiz end timer
    context.job_queue.run_once(end_quiz_timed, duration, context={'user_id': user_id, 'chat_id': query.message.chat_id if query else update.message.chat_id}, name=job_name)

    logger.info(f"Quiz {context.user_data['quiz_id']} started for user {user_id}. Timer set for {duration} seconds.")

    # Send the first question
    send_question(update, context)
    return RUNNING_QUIZ

def send_question(update: Update, context: CallbackContext):
    """Sends the current quiz question to the user."""
    query = update.callback_query # Might be None if called after text message or timer
    user_id = context.user_data.get("user_id")
    if not user_id:
        logger.error("send_question: user_id not found in context.")
        # Try to end gracefully if possible
        if query:
            safe_edit_message_text(query, "حدث خطأ فني. سيتم إنهاء الاختبار.")
        # Cannot send message without chat_id if query is None
        return end_quiz(update, context, reason="Error: User context lost")

    current_index = context.user_data.get('current_question_index', 0)
    questions = context.user_data.get('quiz_questions', [])
    quiz_end_time = context.user_data.get('quiz_end_time')

    if not questions or current_index >= len(questions):
        logger.info(f"User {user_id} reached end of questions or no questions available.")
        return end_quiz(update, context, reason="End of questions")

    question_data = questions[current_index]
    question_id = question_data['question_id']
    question_text = question_data['question_text']
    options = question_data['options'] # This should be a list of strings
    image_url = question_data.get('image_url') # Optional image

    # Ensure options are correctly formatted (list of strings)
    if not isinstance(options, list) or not all(isinstance(opt, str) for opt in options):
        logger.error(f"Invalid options format for question {question_id}: {options}")
        # Skip this question and move to the next
        context.user_data['current_question_index'] += 1
        if query:
             query.answer("خطأ في تنسيق السؤال، سيتم تخطيه.", show_alert=True)
        # Try sending next question recursively
        return send_question(update, context)

    # Calculate remaining time
    remaining_time = quiz_end_time - datetime.now()
    remaining_seconds = max(0, int(remaining_time.total_seconds()))
    time_str = f"{remaining_seconds // 60}:{remaining_seconds % 60:02d}"

    # Format question message
    message_text = f"⏳ الوقت المتبقي: {time_str}\n"
    message_text += f"❓ السؤال {current_index + 1} من {len(questions)}:\n\n"
    message_text += f"{question_text}"

    keyboard = create_quiz_question_keyboard(options, question_id)

    try:
        # If called from a callback query, edit the existing message
        if query:
            # If there was an image previously, we might need to send a new message
            # or handle image updates carefully. For simplicity, let's assume editing text is fine.
            # If the previous message had an image and this one doesn't, or vice-versa,
            # editing might fail or look weird. Sending a new message might be safer.
            # Let's try editing first.
            if image_url:
                 # Editing message with media requires different handling, might be complex.
                 # Send as new message if image is present.
                 logger.info(f"Sending question {question_id} with image as new message.")
                 query.message.reply_photo(
                     photo=image_url,
                     caption=message_text,
                     reply_markup=keyboard,
                     parse_mode=ParseMode.MARKDOWN # Or HTML if needed
                 )
                 # Try deleting the previous message (optional, might fail)
                 try:
                      query.message.delete()
                 except TelegramError as del_err:
                      logger.warning(f"Could not delete previous message {query.message.message_id}: {del_err}")
            else:
                 # Edit text message
                 safe_edit_message_text(query, text=message_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

        # If called directly (e.g., first question, or after feedback delay)
        else:
            chat_id = update.effective_chat.id # Get chat_id from update
            if image_url:
                context.bot.send_photo(
                    chat_id=chat_id,
                    photo=image_url,
                    caption=message_text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                context.bot.send_message(
                    chat_id=chat_id,
                    text=message_text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN
                )
    except BadRequest as e:
        logger.error(f"Failed to send/edit question {question_id} for user {user_id}: {e}")
        # Attempt to send a simple error message if possible
        try:
            context.bot.send_message(user_id, "حدث خطأ أثناء عرض السؤال. قد تحتاج لإعادة الاختبار.")
        except Exception as send_e:
             logger.error(f"Failed to send error message to user {user_id}: {send_e}")
        return end_quiz(update, context, reason=f"Error sending question: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error sending question {question_id} for user {user_id}: {e}")
        return end_quiz(update, context, reason=f"Unexpected error: {e}")

def handle_answer(update: Update, context: CallbackContext) -> int:
    """Handles user's answer selection during a quiz."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    # Ensure quiz is still running
    if 'quiz_questions' not in context.user_data or 'current_question_index' not in context.user_data:
        logger.warning(f"User {user_id} answered, but no active quiz found in context.")
        safe_edit_message_text(query, text="انتهى وقت الاختبار أو حدث خطأ.", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU

    current_index = context.user_data['current_question_index']
    questions = context.user_data['quiz_questions']
    question_data = questions[current_index]
    question_id = question_data['question_id']
    correct_option_index = question_data['correct_option_index']
    options = question_data['options']

    # Parse callback data
    try:
        action, q_id, selected_index_str = data.split('_')
        q_id = int(q_id)
        selected_index = int(selected_index_str)

        if action != 'answer' or q_id != question_id:
            logger.warning(f"User {user_id} answered wrong question or invalid action. Expected answer_{question_id}, got {data}")
            # Maybe the message is old, ignore the callback
            query.answer("إجابة لسؤال قديم.")
            return RUNNING_QUIZ # Stay in quiz state

    except (ValueError, IndexError) as e:
        logger.error(f"Invalid callback data format received: {data}. Error: {e}")
        query.answer("خطأ في بيانات الإجابة.")
        return RUNNING_QUIZ

    # Record the answer
    is_correct = (selected_index == correct_option_index)
    context.user_data['user_answers'][question_id] = {
        'selected_index': selected_index,
        'correct_index': correct_option_index,
        'is_correct': is_correct,
        'timestamp': datetime.now()
    }

    logger.info(f"User {user_id} answered question {question_id}. Selected: {selected_index}, Correct: {correct_option_index}, Result: {'Correct' if is_correct else 'Incorrect'}")

    # Provide immediate feedback
    feedback_text = "✅ إجابة صحيحة!" if is_correct else f"❌ إجابة خاطئة.\nالصحيحة هي: {options[correct_option_index]}"

    # Edit the message to show feedback (remove keyboard)
    try:
        # If the question had an image, editing caption might be better
        if query.message.photo:
             safe_edit_message_caption(query, caption=f"{query.message.caption}\n\n---\n{feedback_text}", parse_mode=ParseMode.MARKDOWN)
        else:
             safe_edit_message_text(query, text=f"{query.message.text}\n\n---\n{feedback_text}", parse_mode=ParseMode.MARKDOWN)
    except BadRequest as e:
        # Message might have been deleted or changed, log and continue
        logger.warning(f"Failed to edit message for feedback (question {question_id}, user {user_id}): {e}")
        # Send feedback as a new message if editing fails
        try:
             query.message.reply_text(feedback_text)
        except Exception as reply_e:
             logger.error(f"Failed to send feedback as reply: {reply_e}")

    # Increment question index
    context.user_data['current_question_index'] += 1

    # Schedule the next question after a short delay
    feedback_job_name = f"feedback_timer_{user_id}"
    # Remove previous feedback timer if any
    for job in context.job_queue.get_jobs_by_name(feedback_job_name):
        job.schedule_removal()
    # Schedule next question
    context.job_queue.run_once(send_question_job, FEEDBACK_DELAY, context={'user_id': user_id, 'chat_id': query.message.chat_id}, name=feedback_job_name)

    return RUNNING_QUIZ

def handle_skip(update: Update, context: CallbackContext) -> int:
    """Handles skipping a question during a quiz."""
    query = update.callback_query
    query.answer("تم تخطي السؤال.")
    user_id = query.from_user.id
    data = query.data

    # Ensure quiz is still running
    if 'quiz_questions' not in context.user_data or 'current_question_index' not in context.user_data:
        logger.warning(f"User {user_id} skipped, but no active quiz found.")
        safe_edit_message_text(query, text="انتهى وقت الاختبار أو حدث خطأ.", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU

    current_index = context.user_data['current_question_index']
    questions = context.user_data['quiz_questions']
    question_data = questions[current_index]
    question_id = question_data['question_id']

    # Parse callback data
    try:
        action, q_id_str = data.split('_')
        q_id = int(q_id_str)

        if action != 'skip' or q_id != question_id:
            logger.warning(f"User {user_id} skipped wrong question. Expected skip_{question_id}, got {data}")
            return RUNNING_QUIZ # Ignore old callback

    except (ValueError, IndexError) as e:
        logger.error(f"Invalid skip callback data format: {data}. Error: {e}")
        return RUNNING_QUIZ

    logger.info(f"User {user_id} skipped question {question_id}.")

    # Record skip (mark as incorrect or special status)
    context.user_data['user_answers'][question_id] = {
        'selected_index': None, # Indicate skipped
        'correct_index': question_data['correct_option_index'],
        'is_correct': False,
        'skipped': True,
        'timestamp': datetime.now()
    }

    # Increment question index
    context.user_data['current_question_index'] += 1

    # Send the next question immediately (no feedback delay for skips)
    send_question(update, context)

    return RUNNING_QUIZ

def send_question_job(context: CallbackContext):
    """Job callback function to send the next question."""
    job_context = context.job.context
    user_id = job_context['user_id']
    chat_id = job_context['chat_id']
    logger.info(f"Job: Sending next question for user {user_id} in chat {chat_id}.")

    # We need to create a dummy Update object or pass necessary info differently
    # For simplicity, let's assume send_question can work with just context
    # (it needs user_id and chat_id, which we have)
    # We create a minimal Update-like structure if needed by send_question
    class MinimalUpdate:
        class MinimalMessage:
            chat_id = chat_id
        effective_chat = MinimalMessage()
        callback_query = None # Indicate it's not from a callback

    send_question(MinimalUpdate(), context)

def end_quiz_timed(context: CallbackContext):
    """Job callback function to end the quiz when the timer runs out."""
    job_context = context.job.context
    user_id = job_context['user_id']
    chat_id = job_context['chat_id']
    logger.info(f"Quiz timer ended for user {user_id} in chat {chat_id}.")

    # We need a way to send the message. Create a dummy Update.
    class MinimalUpdate:
        class MinimalUser:
            id = user_id
        class MinimalMessage:
            chat_id = chat_id
            from_user = MinimalUser()
            # reply_text method needed if end_quiz uses it directly on update.message
            def reply_text(self, text, reply_markup=None, parse_mode=None):
                 context.bot.send_message(chat_id=self.chat_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)

        effective_user = MinimalUser()
        message = MinimalMessage()
        callback_query = None # Not from a callback

    # Send timeout message before calculating results
    try:
        context.bot.send_message(chat_id, "⏰ انتهى الوقت المخصص للاختبار!")
    except Exception as e:
        logger.error(f"Failed to send timeout message to user {user_id}: {e}")

    end_quiz(MinimalUpdate(), context, reason="Time limit reached")

def end_quiz(update: Update, context: CallbackContext, reason: str = "Quiz finished") -> int:
    """Ends the quiz, calculates results, and shows them to the user."""
    query = update.callback_query # Might be None
    user_id = context.user_data.get("user_id")

    if not user_id:
        logger.error("end_quiz: user_id not found in context.")
        # Try to inform user if possible
        if query:
            safe_edit_message_text(query, "حدث خطأ فني أثناء إنهاء الاختبار.")
        elif update.message:
             update.message.reply_text("حدث خطأ فني أثناء إنهاء الاختبار.")
        return ConversationHandler.END # Or MAIN_MENU

    logger.info(f"Ending quiz for user {user_id}. Reason: {reason}")

    # Clean up any running timers
    job_name = f"quiz_timer_{user_id}"
    feedback_job_name = f"feedback_timer_{user_id}"
    for job in context.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()
    for job in context.job_queue.get_jobs_by_name(feedback_job_name):
        job.schedule_removal()

    # Retrieve quiz data from context
    questions = context.user_data.get('quiz_questions', [])
    user_answers = context.user_data.get('user_answers', {})
    quiz_id = context.user_data.get('quiz_id', 'unknown_quiz')
    start_time = context.user_data.get('quiz_start_time')
    end_time = datetime.now() # Mark actual end time

    if not questions:
        logger.warning(f"No questions found in context when ending quiz {quiz_id} for user {user_id}.")
        message_text = "لم يتم العثور على بيانات الاختبار لإنهاءه."
        reply_markup = create_main_menu_keyboard(user_id)
        if query:
            safe_edit_message_text(query, text=message_text, reply_markup=reply_markup)
        elif update.message:
             update.message.reply_text(text=message_text, reply_markup=reply_markup)
        # Clear context and return
        context.user_data.clear()
        context.user_data["user_id"] = user_id # Keep user_id
        return MAIN_MENU

    # Calculate results
    total_questions = len(questions)
    correct_answers = 0
    skipped_questions = 0
    answered_questions = 0

    for q_id, answer_info in user_answers.items():
        answered_questions += 1
        if answer_info.get('skipped'):
            skipped_questions += 1
        elif answer_info.get('is_correct'):
            correct_answers += 1

    # Score calculation
    score = (correct_answers / total_questions) * 100 if total_questions > 0 else 0
    incorrect_answers = answered_questions - correct_answers - skipped_questions
    unanswered_questions = total_questions - answered_questions

    # Time taken
    time_taken_str = "غير متاح"
    if start_time:
        time_taken = end_time - start_time
        total_seconds = int(time_taken.total_seconds())
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        time_taken_str = f"{minutes} دقيقة و {seconds} ثانية"

    # Save results to database (implement this in QuizDatabase)
    try:
        QUIZ_DB.save_quiz_result(
            quiz_id=quiz_id,
            user_id=user_id,
            score=score,
            correct_count=correct_answers,
            incorrect_count=incorrect_answers,
            skipped_count=skipped_questions,
            unanswered_count=unanswered_questions,
            total_questions=total_questions,
            start_time=start_time,
            end_time=end_time,
            quiz_type=context.user_data.get('quiz_type'),
            filter_id=context.user_data.get('quiz_filter_id')
            # Add details about grade/chapter/lesson if available
        )
        logger.info(f"Saved results for quiz {quiz_id} for user {user_id}.")
    except Exception as e:
        logger.error(f"Failed to save quiz results for user {user_id}, quiz {quiz_id}: {e}")
        # Continue anyway, but log the error

    # Prepare results message
    results_text = f"🏁 **نتائج الاختبار** 🏁\n\n"
    results_text += f"🔢 إجمالي الأسئلة: {total_questions}\n"
    results_text += f"✅ الإجابات الصحيحة: {correct_answers}\n"
    results_text += f"❌ الإجابات الخاطئة: {incorrect_answers}\n"
    results_text += f"⏭️ الأسئلة المتخطاة: {skipped_questions}\n"
    results_text += f"❓ الأسئلة غير المجابة: {unanswered_questions}\n"
    results_text += f"⏱️ الوقت المستغرق: {time_taken_str}\n\n"
    results_text += f"🎯 **النتيجة النهائية: {score:.1f}%**\n\n"

    # Add performance message
    if score >= 90:
        results_text += "🎉 ممتاز! أداء رائع!"
    elif score >= 75:
        results_text += "👍 جيد جداً! استمر في التقدم!"
    elif score >= 50:
        results_text += "🙂 جيد. يمكنك التحسن أكثر بالمراجعة."
    else:
        results_text += "😕 تحتاج إلى المزيد من المراجعة. لا تيأس!"

    keyboard = create_results_menu_keyboard(quiz_id)

    # Send results
    try:
        if query:
            # Edit the last message (which might be the feedback message)
            safe_edit_message_text(query, text=results_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        elif update.message:
            # Send as a new message if ended by timer or command
            update.message.reply_text(text=results_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        else:
             # Should not happen if user_id was found, but as fallback:
             context.bot.send_message(user_id, text=results_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

    except BadRequest as e:
        logger.warning(f"Failed to edit/send results message for quiz {quiz_id}, user {user_id}: {e}")
        # Try sending as a new message if editing failed
        if query:
            try:
                query.message.reply_text(text=results_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
            except Exception as send_e:
                 logger.error(f"Failed to send results as reply: {send_e}")
    except Exception as e:
        logger.exception(f"Unexpected error sending quiz results for user {user_id}: {e}")

    # Clear quiz-specific data from context, keep user_id
    keys_to_clear = [k for k in context.user_data if k not in ["user_id"]]
    for key in keys_to_clear:
        try:
            del context.user_data[key]
        except KeyError:
            pass # Already deleted

    return VIEWING_RESULTS # New state for results screen

def view_results_callback(update: Update, context: CallbackContext) -> int:
    """Handles buttons on the results screen."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    logger.info(f"User {user_id} chose {data} from results menu.")

    if data == 'menu_quiz':
        # Go back to quiz selection menu
        safe_edit_message_text(query, text="اختر نوع الاختبار:", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU
    elif data == 'main_menu':
        # Go back to main menu
        safe_edit_message_text(query, text="القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU
    # elif data.startswith('review_'):
    #     quiz_id = data.split('_')[1]
    #     safe_edit_message_text(query, text=f"ميزة مراجعة أخطاء الاختبار {quiz_id} قيد التطوير. 🚧")
    #     # Stay in results view for now, or return to main menu?
    #     # Let's keep the results keyboard for now.
    #     # return VIEWING_RESULTS
    #     # Or go back to main menu:
    #     # safe_edit_message_text(query, text="القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))
    #     # return MAIN_MENU
    else:
        logger.warning(f"Unexpected callback data '{data}' received in VIEWING_RESULTS state.")
        # Default to main menu if something unexpected happens
        safe_edit_message_text(query, text="القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU

# --- Admin Handlers for Adding Questions/Structure ---

def add_grade_level(update: Update, context: CallbackContext) -> int:
    """Receives and adds a new grade level name."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text("ليس لديك صلاحيات.")
        return ConversationHandler.END

    grade_name = update.message.text.strip()
    if not grade_name or len(grade_name) > 100: # Basic validation
        update.message.reply_text("اسم المرحلة غير صالح أو طويل جداً. حاول مرة أخرى أو أرسل /cancel.")
        return ADDING_GRADE_LEVEL

    try:
        grade_id = QUIZ_DB.add_grade_level(grade_name)
        if grade_id:
            logger.info(f"Admin {user_id} added new grade level: {grade_name} (ID: {grade_id})")
            update.message.reply_text(f"تمت إضافة المرحلة الدراسية '{grade_name}' بنجاح.", reply_markup=create_structure_admin_menu_keyboard())
            context.user_data.pop('admin_flow', None)
            return ADMIN_MANAGE_STRUCTURE
        else:
            update.message.reply_text("لم تتم إضافة المرحلة. قد تكون موجودة بالفعل أو حدث خطأ.", reply_markup=create_structure_admin_menu_keyboard())
            return ADMIN_MANAGE_STRUCTURE
    except Exception as e:
        logger.error(f"Error adding grade level '{grade_name}' by admin {user_id}: {e}")
        update.message.reply_text("حدث خطأ أثناء إضافة المرحلة الدراسية.", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU

def add_chapter(update: Update, context: CallbackContext) -> int:
    """Receives and adds a new chapter name for the selected grade."""
    user_id = update.effective_user.id
    grade_id = context.user_data.get('selected_admin_grade_id')
    grade_name = context.user_data.get('selected_admin_grade_name')

    if not is_admin(user_id) or not grade_id:
        update.message.reply_text("خطأ: الصلاحيات أو المرحلة غير محددة.")
        return ConversationHandler.END

    chapter_name = update.message.text.strip()
    if not chapter_name or len(chapter_name) > 150:
        update.message.reply_text("اسم الفصل غير صالح أو طويل جداً. حاول مرة أخرى أو أرسل /cancel.")
        return ADDING_CHAPTER

    try:
        chapter_id = QUIZ_DB.add_chapter(grade_id, chapter_name)
        if chapter_id:
            logger.info(f"Admin {user_id} added new chapter '{chapter_name}' to grade {grade_id}")
            update.message.reply_text(f"تمت إضافة الفصل '{chapter_name}' للمرحلة '{grade_name}' بنجاح.")
            # Go back to the chapter list for that grade
            chapters = QUIZ_DB.get_chapters_by_grade(grade_id)
            text = f"الفصول الدراسية للمرحلة '{grade_name}':\n"
            if chapters: text += "\n".join([f"- {name} (ID: {cid})" for cid, name in chapters])
            else: text += "لا توجد فصول حالياً.\n"
            text += "\nاختر فصلاً للتعديل أو اضغط لإضافة فصل جديد."
            keyboard_list = []
            if chapters: keyboard_list.extend([[InlineKeyboardButton(name, callback_data=f"admin_chapter_{cid}")] for cid, name in chapters])
            keyboard_list.append([InlineKeyboardButton("➕ إضافة فصل جديد", callback_data="admin_add_chapter_prompt")])
            keyboard_list.append([InlineKeyboardButton("🔙 رجوع للمراحل", callback_data="admin_manage_grades")])
            reply_markup = InlineKeyboardMarkup(keyboard_list)
            update.message.reply_text(text=text, reply_markup=reply_markup) # Send as new message
            return ADMIN_MANAGE_CHAPTERS
        else:
            update.message.reply_text("لم يتم إضافة الفصل. قد يكون موجوداً بالفعل أو حدث خطأ.", reply_markup=create_structure_admin_menu_keyboard())
            return ADMIN_MANAGE_STRUCTURE
    except Exception as e:
        logger.error(f"Error adding chapter '{chapter_name}' by admin {user_id}: {e}")
        update.message.reply_text("حدث خطأ أثناء إضافة الفصل.", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU

def add_lesson(update: Update, context: CallbackContext) -> int:
    """Receives and adds a new lesson name for the selected chapter."""
    user_id = update.effective_user.id
    chapter_id = context.user_data.get('selected_admin_chapter_id')
    chapter_name = context.user_data.get('selected_admin_chapter_name')
    grade_id = context.user_data.get('selected_admin_grade_id') # For back button

    if not is_admin(user_id) or not chapter_id or not grade_id:
        update.message.reply_text("خطأ: الصلاحيات أو الفصل/المرحلة غير محددة.")
        return ConversationHandler.END

    lesson_name = update.message.text.strip()
    if not lesson_name or len(lesson_name) > 150:
        update.message.reply_text("اسم الدرس غير صالح أو طويل جداً. حاول مرة أخرى أو أرسل /cancel.")
        return ADDING_LESSON

    try:
        lesson_id = QUIZ_DB.add_lesson(chapter_id, lesson_name)
        if lesson_id:
            logger.info(f"Admin {user_id} added new lesson '{lesson_name}' to chapter {chapter_id}")
            update.message.reply_text(f"تمت إضافة الدرس '{lesson_name}' للفصل '{chapter_name}' بنجاح.")
            # Go back to the lesson list for that chapter
            lessons = QUIZ_DB.get_lessons_by_chapter(chapter_id)
            text = f"الدروس للفصل '{chapter_name}':\n"
            if lessons: text += "\n".join([f"- {name} (ID: {lid})" for lid, name in lessons])
            else: text += "لا توجد دروس حالياً.\n"
            text += "\nاختر درساً للتعديل أو اضغط لإضافة درس جديد."
            keyboard_list = []
            if lessons: keyboard_list.extend([[InlineKeyboardButton(name, callback_data=f"admin_view_lesson_{lid}")] for lid, name in lessons])
            keyboard_list.append([InlineKeyboardButton("➕ إضافة درس جديد", callback_data="admin_add_lesson_prompt")])
            keyboard_list.append([InlineKeyboardButton("🔙 رجوع للفصول", callback_data=f"admin_grade_{grade_id}")]) # Back to chapter list
            reply_markup = InlineKeyboardMarkup(keyboard_list)
            update.message.reply_text(text=text, reply_markup=reply_markup) # Send as new message
            context.user_data['admin_flow'] = 'manage_lessons' # Ensure flow state is correct
            return ADMIN_MANAGE_LESSONS
        else:
            update.message.reply_text("لم يتم إضافة الدرس. قد يكون موجوداً بالفعل أو حدث خطأ.", reply_markup=create_structure_admin_menu_keyboard())
            return ADMIN_MANAGE_STRUCTURE
    except Exception as e:
        logger.error(f"Error adding lesson '{lesson_name}' by admin {user_id}: {e}")
        update.message.reply_text("حدث خطأ أثناء إضافة الدرس.", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU

def add_question_text(update: Update, context: CallbackContext) -> int:
    """Receives the text for the new question."""
    user_id = update.effective_user.id
    if not is_admin(user_id) or 'new_question' not in context.user_data:
        update.message.reply_text("خطأ: الصلاحيات أو بيانات السؤال غير موجودة.")
        return ConversationHandler.END

    question_text = update.message.text.strip()
    if not question_text or len(question_text) < 5: # Basic validation
        update.message.reply_text("نص السؤال قصير جداً أو غير صالح. حاول مرة أخرى أو أرسل /cancel.")
        return ADDING_QUESTION

    context.user_data['new_question']['text'] = question_text
    context.user_data['new_question']['options'] = [] # Initialize options list
    logger.info(f"Admin {user_id} added question text: '{question_text[:50]}...'" )

    update.message.reply_text("تم حفظ نص السؤال. الآن أرسل الخيار الأول (أ). للإلغاء أرسل /cancel.")
    return ADDING_OPTIONS

def add_question_option(update: Update, context: CallbackContext) -> int:
    """Receives options for the new question."""
    user_id = update.effective_user.id
    if not is_admin(user_id) or 'new_question' not in context.user_data or 'options' not in context.user_data['new_question']:
        update.message.reply_text("خطأ: الصلاحيات أو بيانات السؤال غير موجودة.")
        return ConversationHandler.END

    option_text = update.message.text.strip()
    if not option_text or len(option_text) > 200: # Basic validation
        update.message.reply_text("نص الخيار غير صالح أو طويل جداً. حاول مرة أخرى أو أرسل /cancel.")
        return ADDING_OPTIONS

    current_options = context.user_data['new_question']['options']
    current_options.append(option_text)
    num_options = len(current_options)

    logger.info(f"Admin {user_id} added option {num_options}: '{option_text[:50]}...'" )

    if num_options < 4: # Assuming 4 options (A, B, C, D)
        next_option_letter = chr(ord('أ') + num_options)
        update.message.reply_text(f"تمت إضافة الخيار {chr(ord('أ') + num_options - 1)}. الآن أرسل الخيار التالي ({next_option_letter}). للإلغاء أرسل /cancel.")
        return ADDING_OPTIONS
    else:
        # Got all 4 options, ask for the correct one
        option_letters = [chr(ord('أ') + i) for i in range(num_options)]
        keyboard = [[KeyboardButton(letter)] for letter in option_letters]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        update.message.reply_text("تمت إضافة جميع الخيارات. الآن اختر الحرف المقابل للإجابة الصحيحة من الأزرار أدناه. للإلغاء أرسل /cancel.", reply_markup=reply_markup)
        return ADDING_CORRECT_OPTION

def add_question_correct_option(update: Update, context: CallbackContext) -> int:
    """Receives the correct option letter for the new question."""
    user_id = update.effective_user.id
    if not is_admin(user_id) or 'new_question' not in context.user_data or not context.user_data['new_question'].get('options'):
        update.message.reply_text("خطأ: الصلاحيات أو بيانات السؤال غير موجودة.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    correct_letter = update.message.text.strip().upper() # Normalize input
    num_options = len(context.user_data['new_question']['options'])
    valid_letters = [chr(ord('أ') + i) for i in range(num_options)]

    # Convert Arabic letter to index (A=0, B=1, etc.)
    try:
        # Check if it's one of the expected Arabic letters
        if correct_letter in valid_letters:
             correct_index = valid_letters.index(correct_letter)
        else:
             # Try converting potential English letter input
             eng_letter = correct_letter
             if 'A' <= eng_letter <= 'D': # Assuming max 4 options
                  correct_index = ord(eng_letter) - ord('A')
                  if correct_index >= num_options:
                       raise ValueError("Index out of bounds")
             else:
                  raise ValueError("Invalid letter")
    except ValueError:
        update.message.reply_text(f"إدخال غير صالح. يرجى اختيار أحد الحروف {', '.join(valid_letters)} من الأزرار. حاول مرة أخرى أو أرسل /cancel.")
        # Resend the keyboard
        keyboard = [[KeyboardButton(letter)] for letter in valid_letters]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        update.message.reply_text("اختر الحرف الصحيح:", reply_markup=reply_markup)
        return ADDING_CORRECT_OPTION

    context.user_data['new_question']['correct_index'] = correct_index
    logger.info(f"Admin {user_id} selected correct option index: {correct_index} ({correct_letter})")

    # Ask if they want to add an image (optional)
    keyboard = [[KeyboardButton("نعم"), KeyboardButton("لا")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    update.message.reply_text("تم تحديد الإجابة الصحيحة. هل تريد إضافة صورة لهذا السؤال؟ (اختياري).", reply_markup=reply_markup)
    return ADDING_IMAGE

def add_question_image_prompt(update: Update, context: CallbackContext) -> int:
    """Handles the response to whether an image should be added."""
    user_id = update.effective_user.id
    if not is_admin(user_id) or 'new_question' not in context.user_data:
        update.message.reply_text("خطأ: الصلاحيات أو بيانات السؤال غير موجودة.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    response = update.message.text.strip()

    if response == "نعم":
        update.message.reply_text("حسناً، أرسل الصورة الآن. للإلغاء أرسل /cancel.", reply_markup=ReplyKeyboardRemove())
        return ADDING_IMAGE # Stay in state, waiting for photo
    elif response == "لا":
        update.message.reply_text("حسناً، لن يتم إضافة صورة.", reply_markup=ReplyKeyboardRemove())
        # Finalize question without image
        return finalize_question(update, context)
    else:
        # Invalid response, ask again
        keyboard = [[KeyboardButton("نعم"), KeyboardButton("لا")]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        update.message.reply_text("الرجاء الاختيار 'نعم' أو 'لا' من الأزرار.", reply_markup=reply_markup)
        return ADDING_IMAGE # Stay in state

def add_question_image(update: Update, context: CallbackContext) -> int:
    """Receives the image for the new question."""
    user_id = update.effective_user.id
    if not is_admin(user_id) or 'new_question' not in context.user_data:
        update.message.reply_text("خطأ: الصلاحيات أو بيانات السؤال غير موجودة.")
        return ConversationHandler.END

    if not update.message.photo:
        update.message.reply_text("لم يتم إرسال صورة. يرجى إرسال صورة أو اضغط /skip لتخطي إضافة الصورة أو /cancel للإلغاء.")
        return ADDING_IMAGE

    # Get the largest photo version (file_id)
    photo_file_id = update.message.photo[-1].file_id
    context.user_data['new_question']['image_file_id'] = photo_file_id
    logger.info(f"Admin {user_id} added image with file_id: {photo_file_id}")

    update.message.reply_text("تم استلام الصورة.")
    # Finalize question with image
    return finalize_question(update, context)

def skip_add_image(update: Update, context: CallbackContext) -> int:
    """Handles skipping the image addition step."""
    user_id = update.effective_user.id
    if not is_admin(user_id) or 'new_question' not in context.user_data:
        update.message.reply_text("خطأ: الصلاحيات أو بيانات السؤال غير موجودة.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    logger.info(f"Admin {user_id} skipped adding image.")
    update.message.reply_text("تم تخطي إضافة الصورة.", reply_markup=ReplyKeyboardRemove())
    # Finalize question without image
    return finalize_question(update, context)

def finalize_question(update: Update, context: CallbackContext) -> int:
    """Saves the completed question to the database."""
    user_id = update.effective_user.id
    question_data = context.user_data.get('new_question')

    if not is_admin(user_id) or not question_data:
        logger.error(f"Finalize question called for admin {user_id} but data is missing.")
        update.message.reply_text("حدث خطأ أثناء حفظ السؤال. البيانات غير مكتملة.", reply_markup=create_admin_menu_keyboard())
        context.user_data.pop('new_question', None)
        return ADMIN_MENU

    # Extract data
    chapter_id = question_data.get('chapter_id')
    question_text = question_data.get('text')
    options = question_data.get('options')
    correct_index = question_data.get('correct_index')
    image_file_id = question_data.get('image_file_id') # Can be None

    # Validate required fields
    if not all([chapter_id, question_text, options, correct_index is not None]):
        logger.error(f"Missing data when finalizing question for admin {user_id}: {question_data}")
        update.message.reply_text("بيانات السؤال غير مكتملة. لم يتم الحفظ.", reply_markup=create_admin_menu_keyboard())
        context.user_data.pop('new_question', None)
        return ADMIN_MENU

    try:
        question_id = QUIZ_DB.add_question(
            chapter_id=chapter_id,
            question_text=question_text,
            options=options,
            correct_option_index=correct_index,
            image_url=image_file_id # Pass file_id as URL for now
        )
        if question_id:
            logger.info(f"Admin {user_id} successfully added question {question_id} to chapter {chapter_id}.")
            update.message.reply_text(f"تم حفظ السؤال بنجاح! (ID: {question_id})", reply_markup=create_admin_menu_keyboard())
        else:
            logger.error(f"Failed to add question to DB (returned None) for admin {user_id}.")
            update.message.reply_text("حدث خطأ أثناء حفظ السؤال في قاعدة البيانات.", reply_markup=create_admin_menu_keyboard())

    except Exception as e:
        logger.exception(f"Exception while saving question by admin {user_id}: {e}")
        update.message.reply_text("حدث استثناء أثناء حفظ السؤال.", reply_markup=create_admin_menu_keyboard())

    # Clean up and return to admin menu
    context.user_data.pop('new_question', None)
    context.user_data.pop('admin_flow', None)
    context.user_data.pop('selected_admin_grade_id', None)
    context.user_data.pop('selected_admin_grade_name', None)
    context.user_data.pop('selected_admin_chapter_id', None)
    context.user_data.pop('selected_admin_chapter_name', None)
    return ADMIN_MENU

# --- Error Handler ---

def error_handler(update: object, context: CallbackContext):
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # Optionally, notify user about the error
    if isinstance(update, Update) and update.effective_message:
        try:
            update.effective_message.reply_text("عذراً، حدث خطأ ما أثناء معالجة طلبك. 😥")
        except Exception as e:
            logger.error(f"Failed to send error message to user: {e}")

# --- Main Function ---

def main():
    """Start the bot."""
    # Basic checks
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN environment variable not set.")
        sys.exit("Bot token not found.")
    if not DATABASE_URL:
        logger.critical("DATABASE_URL environment variable not set.")
        sys.exit("Database URL not found.")
    if not QUIZ_DB:
         logger.critical("QuizDatabase instance (QUIZ_DB) not initialized.")
         sys.exit("Database instance error.")

    # Create the Updater and pass it your bot's token.
    updater = Updater(BOT_TOKEN, use_context=True)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # --- Conversation Handler Setup ---
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CallbackQueryHandler(main_menu_callback, pattern='^main_menu$') # Allow re-entry via callback
            ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(main_menu_callback, pattern='^menu_'),
                # Include info menu handler entry point if needed directly from main
                # CallbackQueryHandler(show_info_menu, pattern='^menu_info$'), # Handled within main_menu_callback
                CommandHandler('help', help_command), # Allow help anytime
            ],
            QUIZ_MENU: [
                CallbackQueryHandler(quiz_menu_callback, pattern='^(quiz_|main_menu)'),
            ],
            ADMIN_MENU: [
                CallbackQueryHandler(admin_menu_callback, pattern='^(admin_|main_menu)'),
            ],
            SELECTING_QUIZ_DURATION: [
                CallbackQueryHandler(select_quiz_duration_callback, pattern='^(duration_|menu_quiz)'),
            ],
            SELECT_GRADE_LEVEL_FOR_QUIZ: [
                CallbackQueryHandler(select_grade_level_for_quiz_callback, pattern='^(grade_quiz_|menu_quiz)'),
            ],
            SELECT_CHAPTER_FOR_QUIZ: [
                CallbackQueryHandler(select_chapter_for_quiz_callback, pattern='^(chapter_quiz_|quiz_by_grade_prompt)'),
            ],
             SELECT_CHAPTER_FOR_LESSON: [
                 CallbackQueryHandler(select_chapter_for_lesson_callback, pattern='^(lesson_chapter_|quiz_by_grade_prompt)'),
             ],
            SELECT_LESSON_FOR_QUIZ: [
                CallbackQueryHandler(select_lesson_for_quiz_callback, pattern='^(lesson_quiz_|quiz_by_lesson_prompt)'),
            ],
            RUNNING_QUIZ: [
                CallbackQueryHandler(handle_answer, pattern='^answer_'),
                CallbackQueryHandler(handle_skip, pattern='^skip_'),
                # No other commands should interrupt the quiz except /cancel
            ],
            VIEWING_RESULTS: [
                CallbackQueryHandler(view_results_callback, pattern='^(menu_quiz|main_menu|review_)'),
            ],
            ADMIN_MANAGE_STRUCTURE: [
                 CallbackQueryHandler(admin_manage_structure_callback, pattern='^(admin_manage_|menu_admin)'),
            ],
            ADMIN_MANAGE_GRADES: [
                 CallbackQueryHandler(admin_manage_grades_callback, pattern='^(admin_add_grade_prompt|admin_grade_|admin_manage_structure|admin_view_grade_)'),
                 MessageHandler(Filters.text & ~Filters.command, add_grade_level), # Handles adding grade name
            ],
            ADMIN_MANAGE_CHAPTERS: [
                 CallbackQueryHandler(admin_manage_chapters_callback, pattern='^(admin_add_chapter_prompt|admin_chapter_|admin_manage_grades|admin_view_chapter_)'),
                 MessageHandler(Filters.text & ~Filters.command, add_chapter), # Handles adding chapter name
            ],
            ADMIN_MANAGE_LESSONS: [
                 CallbackQueryHandler(admin_manage_lessons_callback, pattern='^(admin_add_lesson_prompt|admin_grade_|admin_view_lesson_)'), # Back button uses admin_grade_ pattern
                 MessageHandler(Filters.text & ~Filters.command, add_lesson), # Handles adding lesson name
            ],
            ADDING_GRADE_LEVEL: [
                 MessageHandler(Filters.text & ~Filters.command, add_grade_level),
            ],
            ADDING_CHAPTER: [
                 MessageHandler(Filters.text & ~Filters.command, add_chapter),
            ],
            ADDING_LESSON: [
                 MessageHandler(Filters.text & ~Filters.command, add_lesson),
            ],
            ADDING_QUESTION: [ # State after selecting chapter/lesson for question
                MessageHandler(Filters.text & ~Filters.command, add_question_text),
            ],
            ADDING_OPTIONS: [
                MessageHandler(Filters.text & ~Filters.command, add_question_option),
            ],
            ADDING_CORRECT_OPTION: [
                MessageHandler(Filters.regex('^[أ-يA-D]$'), add_question_correct_option), # Accept Arabic/Eng letters
                MessageHandler(Filters.text & ~Filters.command, add_question_correct_option) # Catch invalid text
            ],
            ADDING_IMAGE: [
                MessageHandler(Filters.photo, add_question_image),
                MessageHandler(Filters.regex('^(نعم|لا)$'), add_question_image_prompt),
                CommandHandler('skip', skip_add_image), # Allow skipping image
                MessageHandler(Filters.text & ~Filters.command & ~Filters.regex('^(نعم|لا)$'), add_question_image_prompt) # Catch invalid text
            ],
            # Integrate the INFO_MENU states from info_handlers
            **info_menu_conv_handler.states,

            # Note: DELETING_QUESTION, SHOWING_QUESTION states are not implemented yet
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CommandHandler('start', start), # Allow restarting
            # Add a fallback for unexpected callbacks in any state?
            CallbackQueryHandler(lambda u,c: u.callback_query.answer("أمر غير متوقع في هذه المرحلة.") or MAIN_MENU) # Generic fallback
            ],
        # Allow re-entry into the main states via commands/callbacks
        allow_reentry=True,
        # Define conversation timeout (optional)
        # conversation_timeout=timedelta(minutes=30)
    )

    # Add ConversationHandler to dispatcher
    dp.add_handler(conv_handler)

    # Add the info menu handler separately if it's not fully integrated above
    # dp.add_handler(info_menu_conv_handler) # Already integrated via states dictionary merge

    # Add error handler
    dp.add_error_handler(error_handler)

    # Start the Bot using Webhook for Heroku
    if HEROKU_APP_NAME:
        logger.info(f"Starting webhook on port {PORT} for app {HEROKU_APP_NAME}")
        updater.start_webhook(listen="0.0.0.0",
                              port=PORT,
                              url_path=BOT_TOKEN,
                              webhook_url=f"https://{HEROKU_APP_NAME}.herokuapp.com/{BOT_TOKEN}")
        # Idle is handled by Heroku dyno
        # updater.idle() # Not needed for webhook
    else:
        # Start polling if not on Heroku (for local testing)
        logger.info("Starting bot in polling mode.")
        updater.start_polling()
        updater.idle()

if __name__ == '__main__':
    main()

