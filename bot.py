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
DATABASE_URL = os.environ.get("DATABASE_URL")
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
DB_CONN = connect_db(DATABASE_URL)
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
        # TODO: Implement performance reports
        safe_edit_message_text(query,
            text="قسم تقارير الأداء قيد التطوير. عد قريباً!",
            reply_markup=create_main_menu_keyboard(user_id)
        )
        return MAIN_MENU
    elif data == 'menu_about':
        about_text = "بوت الكيمياء التعليمي\n"
        about_text += "تم تطوير هذا البوت لمساعدتك في تعلم الكيمياء بطريقة تفاعلية.\n"
        about_text += "الإصدار: 1.1 (متوافق مع python-telegram-bot v13.x)\n"
        about_text += "المطور: فريق Manus (مثال)"
        safe_edit_message_text(query,
            text=about_text,
            reply_markup=create_main_menu_keyboard(user_id)
        )
        return MAIN_MENU
    elif data == 'menu_admin':
        if is_admin(user_id):
            safe_edit_message_text(query,
                text="أهلاً بك في قائمة الإدارة. اختر أحد الخيارات:",
                reply_markup=create_admin_menu_keyboard()
            )
            return ADMIN_MENU
        else:
            safe_edit_message_text(query,
                text="عذراً، ليس لديك صلاحية الوصول لهذه القائمة.",
                reply_markup=create_main_menu_keyboard(user_id)
            )
            return MAIN_MENU
    else:
        # Fallback for unknown main menu options
        safe_edit_message_text(query,
            text="خيار غير معروف. العودة للقائمة الرئيسية.",
            reply_markup=create_main_menu_keyboard(user_id)
        )
        return MAIN_MENU

def quiz_menu_callback(update: Update, context: CallbackContext) -> int:
    """Handles quiz menu button presses."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    logger.info(f"User {user_id} chose {data} from quiz menu.")

    if data == 'quiz_random_prompt':
        safe_edit_message_text(query,
            text="اختر مدة الاختبار العشوائي:",
            reply_markup=create_quiz_duration_keyboard()
        )
        context.user_data['quiz_type'] = 'random'
        return SELECTING_QUIZ_DURATION

    elif data == 'quiz_by_grade_prompt':
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
        if keyboard:
            safe_edit_message_text(query,
                text="اختر المرحلة الدراسية للاختبار:",
                reply_markup=keyboard
            )
            return SELECT_GRADE_LEVEL_FOR_QUIZ
        else:
            safe_edit_message_text(query,
                text="عذراً، لا توجد مراحل دراسية متاحة حالياً.",
                reply_markup=create_quiz_menu_keyboard()
            )
            return QUIZ_MENU

    elif data == 'quiz_by_chapter_prompt':
        # First, ask for grade level
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
        if keyboard:
            safe_edit_message_text(query,
                text="أولاً، اختر المرحلة الدراسية:",
                reply_markup=keyboard
            )
            context.user_data['quiz_selection_mode'] = 'chapter' # Indicate we want chapters next
            return SELECT_GRADE_LEVEL_FOR_QUIZ # Reuse grade selection state
        else:
            safe_edit_message_text(query,
                text="عذراً، لا توجد مراحل دراسية متاحة حالياً.",
                reply_markup=create_quiz_menu_keyboard()
            )
            return QUIZ_MENU

    elif data == 'quiz_by_lesson_prompt':
        # First, ask for grade level
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
        if keyboard:
            safe_edit_message_text(query,
                text="أولاً، اختر المرحلة الدراسية:",
                reply_markup=keyboard
            )
            context.user_data['quiz_selection_mode'] = 'lesson' # Indicate we want lessons next
            return SELECT_GRADE_LEVEL_FOR_QUIZ # Reuse grade selection state
        else:
            safe_edit_message_text(query,
                text="عذراً، لا توجد مراحل دراسية متاحة حالياً.",
                reply_markup=create_quiz_menu_keyboard()
            )
            return QUIZ_MENU

    elif data == 'main_menu':
        safe_edit_message_text(query,
            text="القائمة الرئيسية:",
            reply_markup=create_main_menu_keyboard(user_id)
        )
        return MAIN_MENU
    else:
        # Fallback for unknown quiz menu options
        safe_edit_message_text(query,
            text="خيار غير معروف. العودة لقائمة الاختبارات.",
            reply_markup=create_quiz_menu_keyboard()
        )
        return QUIZ_MENU

def select_quiz_duration_callback(update: Update, context: CallbackContext) -> int:
    """Handles quiz duration selection."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    if data.startswith('duration_'):
        duration_key = data.split('_')[1]
        duration_seconds = QUIZ_DURATIONS.get(duration_key)
        if duration_seconds:
            context.user_data['quiz_duration'] = duration_seconds
            quiz_type = context.user_data.get('quiz_type', 'random') # Default to random if not set
            logger.info(f"User {user_id} selected duration {duration_key} ({duration_seconds}s) for {quiz_type} quiz.")

            # Start the quiz based on type
            if quiz_type == 'random':
                return start_quiz(update, context, quiz_type='random')
            elif quiz_type == 'grade':
                grade_id = context.user_data.get('selected_grade_id')
                return start_quiz(update, context, quiz_type='grade', grade_level_id=grade_id)
            elif quiz_type == 'chapter':
                chapter_id = context.user_data.get('selected_chapter_id')
                return start_quiz(update, context, quiz_type='chapter', chapter_id=chapter_id)
            elif quiz_type == 'lesson':
                lesson_id = context.user_data.get('selected_lesson_id')
                return start_quiz(update, context, quiz_type='lesson', lesson_id=lesson_id)
            else:
                safe_edit_message_text(query, text="حدث خطأ غير متوقع عند بدء الاختبار.")
                return cancel(update, context) # Go back to main menu on error
        else:
            safe_edit_message_text(query, text="مدة غير صالحة. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_duration_keyboard())
            return SELECTING_QUIZ_DURATION
    elif data == 'menu_quiz': # Back button
        safe_edit_message_text(query, text="اختر نوع الاختبار:", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU
    else:
        safe_edit_message_text(query, text="خيار غير صالح. يرجى اختيار مدة.", reply_markup=create_quiz_duration_keyboard())
        return SELECTING_QUIZ_DURATION

def select_grade_level_callback(update: Update, context: CallbackContext) -> int:
    """Handles grade level selection for quizzes or structure navigation."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    quiz_selection_mode = context.user_data.get('quiz_selection_mode') # 'chapter' or 'lesson' or None

    if data.startswith('grade_quiz_'):
        grade_info = data.split('_')[2]
        if grade_info == 'all':
            # Handle general quiz across all grades
            context.user_data['quiz_type'] = 'grade'
            context.user_data['selected_grade_id'] = 'all' # Special marker
            logger.info(f"User {user_id} selected general quiz across all grades.")
            # Now ask for duration
            safe_edit_message_text(query,
                text="اختر مدة الاختبار التحصيلي العام:",
                reply_markup=create_quiz_duration_keyboard()
            )
            return SELECTING_QUIZ_DURATION
        else:
            try:
                grade_id = int(grade_info)
                context.user_data['selected_grade_id'] = grade_id
                logger.info(f"User {user_id} selected grade {grade_id} for quiz (mode: {quiz_selection_mode}).")

                if quiz_selection_mode == 'chapter':
                    # User wants quiz by chapter, show chapters for this grade
                    keyboard = create_chapters_keyboard(grade_id, for_quiz=True, context=context)
                    if keyboard:
                        safe_edit_message_text(query,
                            text="الآن، اختر الفصل للاختبار:",
                            reply_markup=keyboard
                        )
                        return SELECT_CHAPTER_FOR_QUIZ
                    else:
                        safe_edit_message_text(query,
                            text="لا توجد فصول متاحة لهذه المرحلة. العودة لقائمة الاختبارات.",
                            reply_markup=create_quiz_menu_keyboard()
                        )
                        return QUIZ_MENU
                elif quiz_selection_mode == 'lesson':
                    # User wants quiz by lesson, first show chapters for this grade
                    context.user_data['selected_grade_id_for_lesson_quiz'] = grade_id # Store specifically for lesson flow
                    keyboard = create_chapters_keyboard(grade_id, for_lesson=True, context=context)
                    if keyboard:
                        safe_edit_message_text(query,
                            text="الآن، اختر الفصل الذي يحتوي على الدرس:",
                            reply_markup=keyboard
                        )
                        return SELECT_CHAPTER_FOR_LESSON # Go to chapter selection for lesson
                    else:
                        safe_edit_message_text(query,
                            text="لا توجد فصول متاحة لهذه المرحلة. العودة لقائمة الاختبارات.",
                            reply_markup=create_quiz_menu_keyboard()
                        )
                        return QUIZ_MENU
                else:
                    # Default: Quiz for the entire grade level
                    context.user_data['quiz_type'] = 'grade'
                    # Now ask for duration
                    safe_edit_message_text(query,
                        text=f"اختر مدة الاختبار للمرحلة المحددة:",
                        reply_markup=create_quiz_duration_keyboard()
                    )
                    return SELECTING_QUIZ_DURATION
            except ValueError:
                logger.warning(f"Invalid grade ID format in callback: {data}")
                safe_edit_message_text(query, text="حدث خطأ. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_menu_keyboard())
                return QUIZ_MENU

    elif data == 'menu_quiz': # Back button
        safe_edit_message_text(query, text="اختر نوع الاختبار:", reply_markup=create_quiz_menu_keyboard())
        # Clear selection mode if going back
        if 'quiz_selection_mode' in context.user_data:
            del context.user_data['quiz_selection_mode']
        return QUIZ_MENU
    else:
        safe_edit_message_text(query, text="خيار غير صالح. يرجى اختيار مرحلة.", reply_markup=create_grade_levels_keyboard(for_quiz=True, context=context))
        return SELECT_GRADE_LEVEL_FOR_QUIZ

def select_chapter_for_quiz_callback(update: Update, context: CallbackContext) -> int:
    """Handles chapter selection specifically for starting a chapter quiz."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    if data.startswith('chapter_quiz_'):
        try:
            chapter_id = int(data.split('_')[2])
            context.user_data['selected_chapter_id'] = chapter_id
            context.user_data['quiz_type'] = 'chapter'
            logger.info(f"User {user_id} selected chapter {chapter_id} for quiz.")

            # Now ask for duration
            safe_edit_message_text(query,
                text=f"اختر مدة الاختبار للفصل المحدد:",
                reply_markup=create_quiz_duration_keyboard()
            )
            return SELECTING_QUIZ_DURATION
        except (ValueError, IndexError):
            logger.warning(f"Invalid chapter ID format in callback: {data}")
            safe_edit_message_text(query, text="حدث خطأ. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_menu_keyboard())
            return QUIZ_MENU

    elif data == 'quiz_by_grade_prompt': # Back button (goes back to grade selection)
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
        if keyboard:
            safe_edit_message_text(query,
                text="اختر المرحلة الدراسية للاختبار:",
                reply_markup=keyboard
            )
            # Keep quiz_selection_mode as 'chapter'
            return SELECT_GRADE_LEVEL_FOR_QUIZ
        else:
            safe_edit_message_text(query,
                text="عذراً، لا توجد مراحل دراسية متاحة حالياً.",
                reply_markup=create_quiz_menu_keyboard()
            )
            return QUIZ_MENU
    else:
        grade_id = context.user_data.get('selected_grade_id')
        keyboard = create_chapters_keyboard(grade_id, for_quiz=True, context=context) if grade_id else None
        safe_edit_message_text(query, text="خيار غير صالح. يرجى اختيار فصل.", reply_markup=keyboard)
        return SELECT_CHAPTER_FOR_QUIZ

def select_chapter_for_lesson_callback(update: Update, context: CallbackContext) -> int:
    """Handles chapter selection when the goal is to select a lesson."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    if data.startswith('lesson_chapter_'):
        try:
            chapter_id = int(data.split('_')[2])
            context.user_data['selected_chapter_id_for_lesson'] = chapter_id # Store chapter for lesson context
            logger.info(f"User {user_id} selected chapter {chapter_id} to find a lesson.")

            # Now show lessons for this chapter
            keyboard = create_lessons_keyboard(chapter_id, for_quiz=True, context=context)
            if keyboard:
                safe_edit_message_text(query,
                    text="الآن، اختر الدرس للاختبار:",
                    reply_markup=keyboard
                )
                return SELECT_LESSON_FOR_QUIZ
            else:
                safe_edit_message_text(query,
                    text="لا توجد دروس متاحة لهذا الفصل. العودة لقائمة الاختبارات.",
                    reply_markup=create_quiz_menu_keyboard()
                )
                # Clear selection mode if going back
                if 'quiz_selection_mode' in context.user_data:
                    del context.user_data['quiz_selection_mode']
                return QUIZ_MENU
        except (ValueError, IndexError):
            logger.warning(f"Invalid chapter ID format in callback: {data}")
            safe_edit_message_text(query, text="حدث خطأ. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_menu_keyboard())
            return QUIZ_MENU

    elif data == 'quiz_by_grade_prompt': # Back button (goes back to grade selection)
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
        if keyboard:
            safe_edit_message_text(query,
                text="اختر المرحلة الدراسية:",
                reply_markup=keyboard
            )
            # Keep quiz_selection_mode as 'lesson'
            return SELECT_GRADE_LEVEL_FOR_QUIZ
        else:
            safe_edit_message_text(query,
                text="عذراً، لا توجد مراحل دراسية متاحة حالياً.",
                reply_markup=create_quiz_menu_keyboard()
            )
            return QUIZ_MENU
    else:
        grade_id = context.user_data.get('selected_grade_id_for_lesson_quiz')
        keyboard = create_chapters_keyboard(grade_id, for_lesson=True, context=context) if grade_id else None
        safe_edit_message_text(query, text="خيار غير صالح. يرجى اختيار فصل.", reply_markup=keyboard)
        return SELECT_CHAPTER_FOR_LESSON

def select_lesson_for_quiz_callback(update: Update, context: CallbackContext) -> int:
    """Handles lesson selection specifically for starting a lesson quiz."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    if data.startswith('lesson_quiz_'):
        try:
            lesson_id = int(data.split('_')[2])
            context.user_data['selected_lesson_id'] = lesson_id
            context.user_data['quiz_type'] = 'lesson'
            logger.info(f"User {user_id} selected lesson {lesson_id} for quiz.")

            # Now ask for duration
            safe_edit_message_text(query,
                text=f"اختر مدة الاختبار للدرس المحدد:",
                reply_markup=create_quiz_duration_keyboard()
            )
            return SELECTING_QUIZ_DURATION
        except (ValueError, IndexError):
            logger.warning(f"Invalid lesson ID format in callback: {data}")
            safe_edit_message_text(query, text="حدث خطأ. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_menu_keyboard())
            return QUIZ_MENU

    # Back button logic needs refinement - go back to chapter selection for the correct grade
    elif data.startswith('grade_quiz_'): # Back button pressed, data contains grade info
         try:
            grade_id = int(data.split('_')[2])
            keyboard = create_chapters_keyboard(grade_id, for_lesson=True, context=context)
            if keyboard:
                safe_edit_message_text(query,
                    text="اختر الفصل الذي يحتوي على الدرس:",
                    reply_markup=keyboard
                )
                return SELECT_CHAPTER_FOR_LESSON
            else:
                # Fallback if chapters fail to load
                safe_edit_message_text(query, text="لا توجد فصول. العودة لقائمة الاختبارات.", reply_markup=create_quiz_menu_keyboard())
                return QUIZ_MENU
         except (ValueError, IndexError):
             logger.warning(f"Invalid grade ID in back callback: {data}")
             safe_edit_message_text(query, text="خطأ في الرجوع. العودة لقائمة الاختبارات.", reply_markup=create_quiz_menu_keyboard())
             return QUIZ_MENU
    elif data == 'quiz_by_lesson_prompt': # Fallback back button if grade_id wasn't found
         # This ideally shouldn't happen if context is managed well
         keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
         if keyboard:
             safe_edit_message_text(query,
                 text="اختر المرحلة الدراسية:",
                 reply_markup=keyboard
             )
             return SELECT_GRADE_LEVEL_FOR_QUIZ
         else:
             safe_edit_message_text(query, text="لا توجد مراحل. العودة لقائمة الاختبارات.", reply_markup=create_quiz_menu_keyboard())
             return QUIZ_MENU

    else:
        chapter_id = context.user_data.get('selected_chapter_id_for_lesson')
        keyboard = create_lessons_keyboard(chapter_id, for_quiz=True, context=context) if chapter_id else None
        safe_edit_message_text(query, text="خيار غير صالح. يرجى اختيار درس.", reply_markup=keyboard)
        return SELECT_LESSON_FOR_QUIZ

# --- Quiz Logic ---

def start_quiz(update: Update, context: CallbackContext, quiz_type='random', grade_level_id=None, chapter_id=None, lesson_id=None) -> int:
    """Starts a quiz based on selected criteria."""
    query = update.callback_query # Can be None if called directly after duration selection
    user_id = context.user_data.get("user_id")
    duration = context.user_data.get('quiz_duration', QUIZ_DURATIONS['medium']) # Default duration

    if not user_id:
        # Try to get user_id from update if context is missing it
        if update.effective_user:
            user_id = update.effective_user.id
            context.user_data["user_id"] = user_id
        else:
            logger.error("Cannot start quiz: User ID not found.")
            if query: query.message.reply_text("حدث خطأ: لم يتم العثور على معرف المستخدم.")
            return ConversationHandler.END

    logger.info(f"Starting quiz for user {user_id}. Type: {quiz_type}, Duration: {duration}s, Grade: {grade_level_id}, Chapter: {chapter_id}, Lesson: {lesson_id}")

    # Fetch questions based on criteria
    questions = []
    if quiz_type == 'random':
        questions = QUIZ_DB.get_random_questions(DEFAULT_QUIZ_QUESTIONS)
    elif quiz_type == 'grade':
        if grade_level_id == 'all': # General quiz
             questions = QUIZ_DB.get_questions_by_criteria(limit=DEFAULT_QUIZ_QUESTIONS)
        else:
             questions = QUIZ_DB.get_questions_by_criteria(grade_level_id=grade_level_id, limit=DEFAULT_QUIZ_QUESTIONS)
    elif quiz_type == 'chapter':
        questions = QUIZ_DB.get_questions_by_criteria(chapter_id=chapter_id, limit=DEFAULT_QUIZ_QUESTIONS)
    elif quiz_type == 'lesson':
        questions = QUIZ_DB.get_questions_by_criteria(lesson_id=lesson_id, limit=DEFAULT_QUIZ_QUESTIONS)

    if not questions:
        logger.warning(f"No questions found for quiz criteria: {quiz_type}, G:{grade_level_id}, C:{chapter_id}, L:{lesson_id}")
        message_text = "عذراً، لم يتم العثور على أسئلة تطابق اختيارك. يرجى المحاولة مرة أخرى أو اختيار معايير مختلفة."
        if query:
            safe_edit_message_text(query, text=message_text, reply_markup=create_quiz_menu_keyboard())
        else:
            # If called without a query (e.g., after duration), send a new message
            context.bot.send_message(chat_id=user_id, text=message_text, reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

    # Shuffle questions
    random.shuffle(questions)

    # Store quiz state in user_data
    context.user_data['quiz_questions'] = questions
    context.user_data['current_question_index'] = 0
    context.user_data['quiz_score'] = 0
    context.user_data['quiz_answers'] = [] # Store user answers (question_id, selected_option_index, is_correct)
    context.user_data['quiz_start_time'] = datetime.now()
    context.user_data['quiz_end_time'] = datetime.now() + timedelta(seconds=duration)
    context.user_data['quiz_active'] = True

    # Start the quiz timer
    job_name = f"quiz_timer_{user_id}"
    # Remove any existing timer for this user first
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    if current_jobs:
        for job in current_jobs:
            job.schedule_removal()
    context.job_queue.run_once(quiz_timeout, duration, context={'user_id': user_id, 'chat_id': query.message.chat_id if query else user_id}, name=job_name)

    logger.info(f"Quiz timer set for user {user_id} for {duration} seconds.")

    # Send the first question
    if query:
        # Edit the message that triggered the quiz start
        send_question(update, context, query=query)
    else:
        # Send a new message if no query (e.g., after duration selection)
        send_question(update, context)

    return RUNNING_QUIZ

def send_question(update: Update, context: CallbackContext, query=None):
    """Sends the current quiz question to the user."""
    user_id = context.user_data.get("user_id")
    if not user_id:
        logger.error("Cannot send question: User ID not found in context.")
        # Attempt to recover user_id if possible
        if update and update.effective_user:
            user_id = update.effective_user.id
            context.user_data["user_id"] = user_id
        else:
            # Cannot proceed without user_id
            if query: query.message.reply_text("خطأ: لم يتم العثور على المستخدم.")
            return cancel(update, context) if update else ConversationHandler.END

    if not context.user_data.get('quiz_active', False):
        logger.info(f"Attempted to send question to user {user_id}, but quiz is not active.")
        # Quiz might have timed out or ended
        return RUNNING_QUIZ # Stay in state, timeout/end logic handles transition

    questions = context.user_data.get('quiz_questions', [])
    current_index = context.user_data.get('current_question_index', 0)
    total_questions = len(questions)

    if current_index >= total_questions:
        # Should be handled by answer/skip logic, but as a fallback
        logger.info(f"Quiz finished for user {user_id}, but send_question called.")
        return end_quiz(update, context)

    current_question_data = questions[current_index]
    question_id = current_question_data['id']
    question_text = current_question_data['question_text']
    options = current_question_data['options'] # List of strings
    image_path = current_question_data.get('image_path') # Optional image path

    keyboard = create_quiz_question_keyboard(options, question_id)

    # Calculate remaining time
    end_time = context.user_data.get('quiz_end_time')
    remaining_time_str = ""
    if end_time:
        remaining_delta = end_time - datetime.now()
        if remaining_delta.total_seconds() > 0:
            remaining_minutes = int(remaining_delta.total_seconds() // 60)
            remaining_seconds = int(remaining_delta.total_seconds() % 60)
            remaining_time_str = f"⏳ الوقت المتبقي: {remaining_minutes:02d}:{remaining_seconds:02d}\n"
        else:
            # Time might have run out just now
            logger.info(f"Time ran out for user {user_id} just before sending question {current_index + 1}.")
            # The timer job should handle the timeout
            return RUNNING_QUIZ

    # Store the message ID of the question to edit it later with feedback
    sent_message = None

    # --- Corrected Code Block Start --- #
    # Send the question with image if available
    if image_path:
        try:
            # Send image first
            with open(image_path, 'rb') as img:
                context.bot.send_photo(chat_id=user_id, photo=img)
            # Then send the text and keyboard
            text = f"{remaining_time_str}*السؤال {current_index + 1} من {total_questions}:*\n\n{question_text}"
            sent_message = context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
        except FileNotFoundError:
            logger.error(f"Image file not found: {image_path} for question {question_id}")
            # Fallback to text only
            text = f"{remaining_time_str}*السؤال {current_index + 1} من {total_questions}:*\n\n{question_text}\n\n(تعذر تحميل الصورة المصاحبة)"
            sent_message = context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error sending question with image {image_path}: {e}")
            # General fallback to text only
            text = f"{remaining_time_str}*السؤال {current_index + 1} من {total_questions}:*\n\n{question_text}"
            sent_message = context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
    else:
        # Send text only
        text = f"{remaining_time_str}*السؤال {current_index + 1} من {total_questions}:*\n\n{question_text}"
        # Use query.edit_message_text if available, otherwise send new message
        if query:
             try:
                 sent_message = query.edit_message_text(
                     text=text,
                     reply_markup=keyboard,
                     parse_mode=ParseMode.MARKDOWN
                 )
             except BadRequest as e:
                 if "Message is not modified" in str(e):
                     logger.info("Message not modified, sending question anyway.")
                     # If editing fails (e.g., same content), send as new message
                     sent_message = context.bot.send_message(
                         chat_id=user_id,
                         text=text,
                         reply_markup=keyboard,
                         parse_mode=ParseMode.MARKDOWN
                     )
                 else:
                     logger.error(f"Error editing message to send question: {e}")
                     # Fallback to sending new message on other errors
                     sent_message = context.bot.send_message(
                         chat_id=user_id,
                         text=text,
                         reply_markup=keyboard,
                         parse_mode=ParseMode.MARKDOWN
                     )
        else:
             sent_message = context.bot.send_message(
                 chat_id=user_id,
                 text=text,
                 reply_markup=keyboard,
                 parse_mode=ParseMode.MARKDOWN
             )
    # --- Corrected Code Block End --- #

    if sent_message:
        context.user_data['last_question_message_id'] = sent_message.message_id
        context.user_data['last_question_chat_id'] = sent_message.chat_id

def handle_answer(update: Update, context: CallbackContext) -> int:
    """Handles user's answer selection during a quiz."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    if not context.user_data.get('quiz_active', False):
        logger.info(f"User {user_id} answered, but quiz is not active.")
        safe_edit_message_text(query, text="انتهى وقت الاختبار أو تم إلغاؤه.")
        # Attempt to show results if they exist
        if 'quiz_score' in context.user_data:
            return show_results(update, context, query=query)
        else:
            return cancel(update, context)

    try:
        _, question_id_str, selected_option_index_str = data.split('_')
        question_id = int(question_id_str)
        selected_option_index = int(selected_option_index_str)
    except (ValueError, IndexError):
        logger.error(f"Invalid answer callback data format: {data}")
        safe_edit_message_text(query, text="حدث خطأ في معالجة إجابتك. يرجى المحاولة مرة أخرى.")
        return RUNNING_QUIZ

    questions = context.user_data.get('quiz_questions', [])
    current_index = context.user_data.get('current_question_index', 0)

    # Basic check: is the answered question the current one?
    if current_index >= len(questions) or questions[current_index]['id'] != question_id:
        logger.warning(f"User {user_id} answered question {question_id}, but current is {questions[current_index]['id'] if current_index < len(questions) else 'None'}. Ignoring.")
        # Maybe they clicked an old button? Just ignore.
        return RUNNING_QUIZ

    current_question_data = questions[current_index]
    correct_option_index = current_question_data['correct_option_index']
    options = current_question_data['options']

    is_correct = (selected_option_index == correct_option_index)

    # Update score and record answer
    if is_correct:
        context.user_data['quiz_score'] = context.user_data.get('quiz_score', 0) + 1
        feedback_text = "✅ إجابة صحيحة!"
    else:
        correct_option_text = options[correct_option_index]
        feedback_text = f"❌ إجابة خاطئة.\nالإجابة الصحيحة: {correct_option_text}"

    context.user_data.setdefault('quiz_answers', []).append({
        'question_id': question_id,
        'selected_option_index': selected_option_index,
        'correct_option_index': correct_option_index,
        'is_correct': is_correct
    })

    # Edit the original question message to show feedback (remove keyboard)
    original_message_id = context.user_data.get('last_question_message_id')
    original_chat_id = context.user_data.get('last_question_chat_id')
    original_message_text = query.message.text # Get the text of the message the button was attached to

    if original_message_id and original_chat_id:
        # Combine original question text (without time) and feedback
        # Find the start of the actual question text after the time string if it exists
        question_start_index = original_message_text.find("*السؤال")
        if question_start_index != -1:
            original_question_part = original_message_text[question_start_index:]
        else:
            original_question_part = original_message_text # Fallback

        new_text = f"{original_question_part}\n\n{feedback_text}"

        try:
            context.bot.edit_message_text(
                chat_id=original_chat_id,
                message_id=original_message_id,
                text=new_text,
                reply_markup=None, # Remove keyboard
                parse_mode=ParseMode.MARKDOWN
            )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                logger.info(f"Feedback message for question {question_id} not modified.")
                # If not modified, maybe just log, no need to send new message here.
            else:
                logger.error(f"Error editing message to show feedback for question {question_id}: {e}")
                # Fallback: Send feedback as a new message if editing fails
                context.bot.send_message(chat_id=original_chat_id, text=feedback_text)
        except Exception as e:
             logger.error(f"Unexpected error editing message for feedback: {e}")
             context.bot.send_message(chat_id=original_chat_id, text=feedback_text)
    else:
        # Fallback if original message details are missing
        query.message.reply_text(feedback_text)

    # Move to the next question or end quiz
    context.user_data['current_question_index'] = current_index + 1

    if context.user_data['current_question_index'] < len(questions):
        # Schedule the next question after a short delay
        job_name = f"feedback_timer_{user_id}"
        context.job_queue.run_once(send_next_question_job, FEEDBACK_DELAY, context={'user_id': user_id, 'chat_id': original_chat_id}, name=job_name)
    else:
        # Schedule ending the quiz after feedback delay
        job_name = f"feedback_timer_{user_id}"
        context.job_queue.run_once(end_quiz_job, FEEDBACK_DELAY, context={'user_id': user_id, 'chat_id': original_chat_id}, name=job_name)

    return RUNNING_QUIZ

def skip_question(update: Update, context: CallbackContext) -> int:
    """Handles skipping the current question."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    if not context.user_data.get('quiz_active', False):
        logger.info(f"User {user_id} tried to skip, but quiz is not active.")
        safe_edit_message_text(query, text="انتهى وقت الاختبار أو تم إلغاؤه.")
        return cancel(update, context)

    try:
        _, question_id_str = data.split('_')
        question_id = int(question_id_str)
    except (ValueError, IndexError):
        logger.error(f"Invalid skip callback data format: {data}")
        safe_edit_message_text(query, text="حدث خطأ في معالجة التخطي.")
        return RUNNING_QUIZ

    questions = context.user_data.get('quiz_questions', [])
    current_index = context.user_data.get('current_question_index', 0)

    # Basic check: is the skipped question the current one?
    if current_index >= len(questions) or questions[current_index]['id'] != question_id:
        logger.warning(f"User {user_id} skipped question {question_id}, but current is {questions[current_index]['id'] if current_index < len(questions) else 'None'}. Ignoring.")
        return RUNNING_QUIZ

    current_question_data = questions[current_index]
    correct_option_index = current_question_data['correct_option_index']
    options = current_question_data['options']

    # Record skipped answer
    context.user_data.setdefault('quiz_answers', []).append({
        'question_id': question_id,
        'selected_option_index': None, # Mark as skipped
        'correct_option_index': correct_option_index,
        'is_correct': False
    })

    # Provide feedback for skipped question
    correct_option_text = options[correct_option_index]
    feedback_text = f"تم تخطي السؤال.\nالإجابة الصحيحة: {correct_option_text}"

    # Edit the original question message
    original_message_id = context.user_data.get('last_question_message_id')
    original_chat_id = context.user_data.get('last_question_chat_id')
    original_message_text = query.message.text

    if original_message_id and original_chat_id:
        question_start_index = original_message_text.find("*السؤال")
        original_question_part = original_message_text[question_start_index:] if question_start_index != -1 else original_message_text
        new_text = f"{original_question_part}\n\n{feedback_text}"
        try:
            context.bot.edit_message_text(
                chat_id=original_chat_id,
                message_id=original_message_id,
                text=new_text,
                reply_markup=None,
                parse_mode=ParseMode.MARKDOWN
            )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                logger.info(f"Skip feedback message for question {question_id} not modified.")
            else:
                logger.error(f"Error editing message for skip feedback: {e}")
                context.bot.send_message(chat_id=original_chat_id, text=feedback_text)
        except Exception as e:
             logger.error(f"Unexpected error editing message for skip feedback: {e}")
             context.bot.send_message(chat_id=original_chat_id, text=feedback_text)
    else:
        query.message.reply_text(feedback_text)

    # Move to the next question or end quiz
    context.user_data['current_question_index'] = current_index + 1

    if context.user_data['current_question_index'] < len(questions):
        job_name = f"feedback_timer_{user_id}"
        context.job_queue.run_once(send_next_question_job, FEEDBACK_DELAY, context={'user_id': user_id, 'chat_id': original_chat_id}, name=job_name)
    else:
        job_name = f"feedback_timer_{user_id}"
        context.job_queue.run_once(end_quiz_job, FEEDBACK_DELAY, context={'user_id': user_id, 'chat_id': original_chat_id}, name=job_name)

    return RUNNING_QUIZ

def send_next_question_job(context: CallbackContext):
    """Job to send the next question after feedback delay."""
    user_id = context.job.context['user_id']
    chat_id = context.job.context['chat_id']
    # We need to pass an Update object, but we don't have one here.
    # Let's create a dummy Update-like structure or modify send_question.
    # Modifying send_question to not require Update/query might be cleaner.

    # Let's try calling send_question without Update/query
    # We need to ensure user_data is accessible via context.dispatcher.user_data[user_id]
    bot_user_data = context.dispatcher.user_data.get(user_id, {})
    if not bot_user_data:
         logger.warning(f"User data not found for user {user_id} in send_next_question_job")
         return

    # Create a temporary context object with the correct user_data
    temp_context = CallbackContext(context.dispatcher)
    temp_context._user_data = bot_user_data
    temp_context._chat_data = context.dispatcher.chat_data.get(chat_id, {})
    temp_context._bot_data = context.dispatcher.bot_data

    # Ensure user_id is set in the temp context's user_data
    temp_context.user_data['user_id'] = user_id

    logger.info(f"Job: Sending next question to user {user_id}")
    send_question(None, temp_context) # Pass None for update

def end_quiz_job(context: CallbackContext):
    """Job to end the quiz after feedback delay for the last question."""
    user_id = context.job.context['user_id']
    chat_id = context.job.context['chat_id']

    bot_user_data = context.dispatcher.user_data.get(user_id, {})
    if not bot_user_data:
         logger.warning(f"User data not found for user {user_id} in end_quiz_job")
         return

    temp_context = CallbackContext(context.dispatcher)
    temp_context._user_data = bot_user_data
    temp_context._chat_data = context.dispatcher.chat_data.get(chat_id, {})
    temp_context._bot_data = context.dispatcher.bot_data
    temp_context.user_data['user_id'] = user_id # Ensure user_id is present

    logger.info(f"Job: Ending quiz for user {user_id}")
    end_quiz(None, temp_context) # Pass None for update

def quiz_timeout(context: CallbackContext):
    """Handles the quiz timeout."""
    user_id = context.job.context['user_id']
    chat_id = context.job.context['chat_id']
    logger.info(f"Quiz timed out for user {user_id}.")

    # Access user_data associated with the specific user
    user_data = context.dispatcher.user_data.get(user_id)

    if user_data and user_data.get('quiz_active', False):
        user_data['quiz_active'] = False # Mark quiz as inactive

        # Create a temporary context for this user
        temp_context = CallbackContext(context.dispatcher)
        temp_context._user_data = user_data
        temp_context._chat_data = context.dispatcher.chat_data.get(chat_id, {})
        temp_context._bot_data = context.dispatcher.bot_data
        temp_context.user_data['user_id'] = user_id # Ensure user_id is present

        context.bot.send_message(chat_id=chat_id, text="⏰ انتهى وقت الاختبار!")
        # Use the temporary context to call end_quiz
        end_quiz(None, temp_context) # Pass None for update
    else:
        logger.info(f"Quiz timeout job ran for user {user_id}, but quiz was already inactive or user_data missing.")

def end_quiz(update: Update, context: CallbackContext) -> int:
    """Ends the current quiz and shows the results."""
    user_id = context.user_data.get("user_id")
    if not user_id:
        logger.error("Cannot end quiz: User ID not found in context.")
        if update and update.effective_message:
             update.effective_message.reply_text("خطأ: لم يتم العثور على المستخدم.")
        return ConversationHandler.END # Or MAIN_MENU?

    logger.info(f"Ending quiz for user {user_id}.")

    # Ensure quiz is marked inactive
    context.user_data['quiz_active'] = False

    # Remove timer job if it exists (might be called before timeout)
    job_name = f"quiz_timer_{user_id}"
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    if current_jobs:
        for job in current_jobs:
            job.schedule_removal()
        logger.info(f"Removed quiz timer job for user {user_id} during end_quiz.")

    # Remove feedback timer job if it exists
    feedback_job_name = f"feedback_timer_{user_id}"
    feedback_jobs = context.job_queue.get_jobs_by_name(feedback_job_name)
    if feedback_jobs:
        for job in feedback_jobs:
            job.schedule_removal()
        logger.info(f"Removed feedback timer job for user {user_id} during end_quiz.")

    # Show results
    return show_results(update, context)

def show_results(update: Update, context: CallbackContext, query=None) -> int:
    """Displays the quiz results to the user."""
    user_id = context.user_data.get("user_id")
    if not user_id:
        logger.error("Cannot show results: User ID not found.")
        # Handle error appropriately
        if query: query.message.reply_text("خطأ في عرض النتائج.")
        elif update: update.effective_message.reply_text("خطأ في عرض النتائج.")
        return MAIN_MENU

    score = context.user_data.get('quiz_score', 0)
    questions = context.user_data.get('quiz_questions', [])
    total_questions = len(questions)
    quiz_answers = context.user_data.get('quiz_answers', [])

    if total_questions == 0:
        result_text = "لم يتم العثور على أسئلة لهذا الاختبار."
        keyboard = create_main_menu_keyboard(user_id)
    else:
        percentage = round((score / total_questions) * 100) if total_questions > 0 else 0
        result_text = f"🎉 انتهى الاختبار! 🎉\n\n"
        result_text += f"نتيجتك: {score} من {total_questions} ({percentage}%)\n"

        # Simple performance feedback
        if percentage == 100:
            result_text += "🥳 ممتاز! درجة كاملة!"
        elif percentage >= 80:
            result_text += "👍 جيد جداً!"
        elif percentage >= 60:
            result_text += "🙂 جيد."
        elif percentage >= 40:
            result_text += "🤔 تحتاج إلى المزيد من المراجعة."
        else:
            result_text += "😔 حاول مرة أخرى!"

        # Store results in the database
        quiz_id = QUIZ_DB.save_quiz_result(user_id, score, total_questions, percentage, context.user_data.get('quiz_type'), context.user_data.get('selected_grade_id'), context.user_data.get('selected_chapter_id'), context.user_data.get('selected_lesson_id'))
        if quiz_id:
            logger.info(f"Saved quiz result {quiz_id} for user {user_id}.")
            # Save individual answers
            for answer in quiz_answers:
                QUIZ_DB.save_quiz_answer(quiz_id, answer['question_id'], answer['selected_option_index'], answer['is_correct'])
            keyboard = create_results_menu_keyboard(quiz_id)
        else:
            logger.error(f"Failed to save quiz result for user {user_id}.")
            keyboard = create_main_menu_keyboard(user_id) # Fallback keyboard

    # Send results
    if query:
        # If called from a callback (like timeout or answer handler)
        safe_edit_message_text(query, text=result_text, reply_markup=keyboard)
    elif update and update.effective_message:
        # If called directly (e.g., end_quiz after last question)
        update.effective_message.reply_text(text=result_text, reply_markup=keyboard)
    else:
        # If called from a job (timeout, end_quiz_job)
        context.bot.send_message(chat_id=user_id, text=result_text, reply_markup=keyboard)

    # Clean up quiz-specific data, but keep user_id
    keys_to_clear = [k for k in context.user_data if k not in ['user_id']]
    for key in keys_to_clear:
        try:
            del context.user_data[key]
        except KeyError:
            pass # Key might have already been deleted

    return VIEWING_RESULTS # Stay in results view or transition back?
    # Let's transition back to main menu after showing results
    # return MAIN_MENU

def results_menu_callback(update: Update, context: CallbackContext) -> int:
    """Handles button presses on the results screen."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == 'menu_quiz':
        safe_edit_message_text(query, text="اختر نوع الاختبار:", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU
    elif data == 'main_menu':
        safe_edit_message_text(query, text="القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU
    # Add review logic here if implemented
    # elif data.startswith('review_'):
    #     quiz_id = int(data.split('_')[1])
    #     # ... implement review logic ...
    #     safe_edit_message_text(query, text="مراجعة الأخطاء قيد التطوير.")
    #     return VIEWING_RESULTS
    else:
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU

# --- Admin Handlers ---

def admin_menu_callback(update: Update, context: CallbackContext) -> int:
    """Handles admin menu button presses."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    if not is_admin(user_id):
        safe_edit_message_text(query, text=" وصول غير مصرح به.", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU

    logger.info(f"Admin {user_id} chose {data} from admin menu.")

    if data == 'admin_add_question':
        safe_edit_message_text(query, text="📝 يرجى إرسال نص السؤال الجديد:")
        return ADDING_QUESTION
    elif data == 'admin_delete_question':
        safe_edit_message_text(query, text="🗑️ يرجى إرسال ID السؤال الذي تريد حذفه:")
        return DELETING_QUESTION
    elif data == 'admin_show_question':
        safe_edit_message_text(query, text="👁️ يرجى إرسال ID السؤال الذي تريد عرضه:")
        return SHOWING_QUESTION
    elif data == 'admin_manage_structure':
         safe_edit_message_text(query, text="🏗️ اختر ما تريد إدارته:", reply_markup=create_structure_admin_menu_keyboard())
         return ADMIN_MANAGE_STRUCTURE
    elif data == 'main_menu':
        safe_edit_message_text(query, text="القائمة الرئيسية:", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU
    else:
        safe_edit_message_text(query, text="خيار إدارة غير معروف.", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU

# --- Add Question Flow ---

def add_question_text(update: Update, context: CallbackContext) -> int:
    """Receives the question text from the admin."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text(" وصول غير مصرح به.")
        return cancel(update, context)

    question_text = update.message.text
    context.user_data['new_question'] = {'text': question_text, 'options': []}
    logger.info(f"Admin {user_id} adding question: {question_text}")
    update.message.reply_text("👍 تم استلام نص السؤال. الآن أرسل الخيار الأول (أ).")
    return ADDING_OPTIONS

def add_question_option(update: Update, context: CallbackContext) -> int:
    """Receives options for the new question."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text(" وصول غير مصرح به.")
        return cancel(update, context)

    option_text = update.message.text
    new_question_data = context.user_data.get('new_question')

    if not new_question_data:
        update.message.reply_text("حدث خطأ. يرجى البدء من جديد بإرسال نص السؤال.")
        return ADDING_QUESTION

    new_question_data['options'].append(option_text)
    num_options = len(new_question_data['options'])
    logger.info(f"Admin {user_id} added option {num_options}: {option_text}")

    if num_options < 4:
        next_option_letter = chr(ord('أ') + num_options)
        update.message.reply_text(f"✅ تم إضافة الخيار. أرسل الخيار التالي ({next_option_letter}) أو أرسل /done إذا اكتملت الخيارات.")
        return ADDING_OPTIONS
    else:
        # Maximum options reached (assuming 4 for now)
        update.message.reply_text("✅ تم إضافة الخيار الرابع والأخير. الآن، أرسل رقم الخيار الصحيح (1, 2, 3, أو 4).")
        return ADDING_CORRECT_OPTION

def add_question_done_options(update: Update, context: CallbackContext) -> int:
    """Handles /done command when adding options."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text(" وصول غير مصرح به.")
        return cancel(update, context)

    new_question_data = context.user_data.get('new_question')
    if not new_question_data or len(new_question_data.get('options', [])) < 2:
        update.message.reply_text("يجب إضافة خيارين على الأقل. أرسل الخيار التالي أو /cancel.")
        return ADDING_OPTIONS

    num_options = len(new_question_data['options'])
    update.message.reply_text(f"👍 تم الانتهاء من إضافة الخيارات ({num_options} خيارات). الآن، أرسل رقم الخيار الصحيح (من 1 إلى {num_options}).")
    return ADDING_CORRECT_OPTION

def add_question_correct_option(update: Update, context: CallbackContext) -> int:
    """Receives the correct option index."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text(" وصول غير مصرح به.")
        return cancel(update, context)

    new_question_data = context.user_data.get('new_question')
    if not new_question_data or not new_question_data.get('options'):
        update.message.reply_text("حدث خطأ. يرجى البدء من جديد.")
        return cancel(update, context)

    try:
        correct_option_number = int(update.message.text)
        num_options = len(new_question_data['options'])
        if 1 <= correct_option_number <= num_options:
            # Store 0-based index
            new_question_data['correct_index'] = correct_option_number - 1
            logger.info(f"Admin {user_id} set correct option to {correct_option_number}.")
            update.message.reply_text("✅ تم تحديد الإجابة الصحيحة. هل تريد إضافة صورة للسؤال؟ أرسل الصورة الآن أو أرسل /skip لتخطي إضافة الصورة.")
            return ADDING_IMAGE
        else:
            update.message.reply_text(f"رقم غير صالح. يرجى إرسال رقم بين 1 و {num_options}.")
            return ADDING_CORRECT_OPTION
    except ValueError:
        update.message.reply_text("إدخال غير صالح. يرجى إرسال رقم الخيار الصحيح.")
        return ADDING_CORRECT_OPTION

def add_question_image(update: Update, context: CallbackContext) -> int:
    """Receives an optional image for the question."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text(" وصول غير مصرح به.")
        return cancel(update, context)

    new_question_data = context.user_data.get('new_question')
    if not new_question_data:
        update.message.reply_text("حدث خطأ. يرجى البدء من جديد.")
        return cancel(update, context)

    if not update.message.photo:
        update.message.reply_text("لم يتم إرسال صورة. يرجى إرسال صورة أو /skip.")
        return ADDING_IMAGE

    # Get the largest photo
    photo_file = update.message.photo[-1].get_file()
    # Define a path to save the image (consider a more robust naming scheme)
    image_dir = "/app/question_images" # Assuming running on Heroku, adjust if needed
    os.makedirs(image_dir, exist_ok=True)
    # Use file_id for uniqueness, but could lead to long names. Consider hashing or UUID.
    image_filename = f"{photo_file.file_id}.jpg"
    image_path = os.path.join(image_dir, image_filename)

    try:
        photo_file.download(image_path)
        new_question_data['image_path'] = image_path # Store the path
        logger.info(f"Admin {user_id} added image: {image_path}")
        update.message.reply_text("🖼️ تم حفظ الصورة.")
        # Proceed to ask for grade level
        return ask_for_grade_level(update, context)
    except Exception as e:
        logger.error(f"Failed to download/save image: {e}")
        update.message.reply_text("حدث خطأ أثناء حفظ الصورة. سنتخطى إضافة الصورة.")
        # Proceed without image
        return ask_for_grade_level(update, context)

def add_question_skip_image(update: Update, context: CallbackContext) -> int:
    """Handles skipping the image addition."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text(" وصول غير مصرح به.")
        return cancel(update, context)

    logger.info(f"Admin {user_id} skipped adding image.")
    update.message.reply_text("👍 تم تخطي إضافة الصورة.")
    # Proceed to ask for grade level
    return ask_for_grade_level(update, context)

def ask_for_grade_level(update: Update, context: CallbackContext) -> int:
    """Asks the admin to select the grade level for the new question."""
    keyboard = create_grade_levels_keyboard(for_quiz=False, context=context) # Use admin context
    if keyboard:
        update.message.reply_text(
            "🎓 الآن، اختر المرحلة الدراسية التي ينتمي إليها السؤال:",
            reply_markup=keyboard
        )
        return ADDING_GRADE_LEVEL
    else:
        update.message.reply_text("لا توجد مراحل دراسية معرفة. يجب إضافتها أولاً من قائمة إدارة الهيكل. سيتم حفظ السؤال بدون مرحلة.")
        # Skip directly to saving the question without structure info
        return save_new_question(update, context)

def add_question_grade_level(update: Update, context: CallbackContext) -> int:
    """Handles the grade level selection callback for adding a question."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    if not is_admin(user_id):
        safe_edit_message_text(query, text=" وصول غير مصرح به.")
        return cancel(update, context)

    new_question_data = context.user_data.get('new_question')
    if not new_question_data:
        safe_edit_message_text(query, text="حدث خطأ. يرجى البدء من جديد.")
        return cancel(update, context)

    if data.startswith('grade_admin_'):
        try:
            grade_id = int(data.split('_')[2])
            new_question_data['grade_level_id'] = grade_id
            logger.info(f"Admin {user_id} selected grade {grade_id} for new question.")

            # Now ask for chapter
            keyboard = create_chapters_keyboard(grade_id, for_quiz=False, context=context)
            if keyboard:
                safe_edit_message_text(query,
                    text="📖 اختر الفصل الذي ينتمي إليه السؤال:",
                    reply_markup=keyboard
                )
                return ADDING_CHAPTER
            else:
                safe_edit_message_text(query, text="لا توجد فصول لهذه المرحلة. سيتم حفظ السؤال بدون فصل أو درس.")
                return save_new_question(update, context)
        except (ValueError, IndexError):
            logger.warning(f"Invalid grade ID format in admin callback: {data}")
            safe_edit_message_text(query, text="حدث خطأ. يرجى المحاولة مرة أخرى.")
            # Resend grade selection
            keyboard = create_grade_levels_keyboard(for_quiz=False, context=context)
            safe_edit_message_text(query, text="اختر المرحلة الدراسية:", reply_markup=keyboard)
            return ADDING_GRADE_LEVEL
    elif data == 'admin_manage_structure': # Back button
         # Go back to admin menu? Or cancel add question?
         safe_edit_message_text(query, text="تم إلغاء إضافة السؤال.", reply_markup=create_admin_menu_keyboard())
         del context.user_data['new_question']
         return ADMIN_MENU
    else:
        keyboard = create_grade_levels_keyboard(for_quiz=False, context=context)
        safe_edit_message_text(query, text="خيار غير صالح. يرجى اختيار مرحلة.", reply_markup=keyboard)
        return ADDING_GRADE_LEVEL

def add_question_chapter(update: Update, context: CallbackContext) -> int:
    """Handles the chapter selection callback for adding a question."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    if not is_admin(user_id):
        safe_edit_message_text(query, text=" وصول غير مصرح به.")
        return cancel(update, context)

    new_question_data = context.user_data.get('new_question')
    if not new_question_data or 'grade_level_id' not in new_question_data:
        safe_edit_message_text(query, text="حدث خطأ (مفقود المرحلة). يرجى البدء من جديد.")
        return cancel(update, context)

    if data.startswith('admin_chapter_'):
        try:
            chapter_id = int(data.split('_')[2])
            new_question_data['chapter_id'] = chapter_id
            logger.info(f"Admin {user_id} selected chapter {chapter_id} for new question.")

            # Now ask for lesson
            keyboard = create_lessons_keyboard(chapter_id, for_quiz=False, context=context)
            if keyboard:
                safe_edit_message_text(query,
                    text="📄 اختر الدرس الذي ينتمي إليه السؤال (أو اختر 'رجوع' لحفظ السؤال تحت الفصل فقط):",
                    reply_markup=keyboard
                )
                return ADDING_LESSON
            else:
                safe_edit_message_text(query, text="لا توجد دروس لهذا الفصل. سيتم حفظ السؤال تحت الفصل المحدد.")
                return save_new_question(update, context)
        except (ValueError, IndexError):
            logger.warning(f"Invalid chapter ID format in admin callback: {data}")
            safe_edit_message_text(query, text="حدث خطأ. يرجى المحاولة مرة أخرى.")
            # Resend chapter selection
            grade_id = new_question_data['grade_level_id']
            keyboard = create_chapters_keyboard(grade_id, for_quiz=False, context=context)
            safe_edit_message_text(query, text="اختر الفصل:", reply_markup=keyboard)
            return ADDING_CHAPTER
    elif data == 'admin_manage_structure': # Back button (from chapter selection)
         # Go back to grade selection
         keyboard = create_grade_levels_keyboard(for_quiz=False, context=context)
         if keyboard:
             safe_edit_message_text(query, text="اختر المرحلة الدراسية:", reply_markup=keyboard)
             # Remove chapter_id if we go back
             if 'chapter_id' in new_question_data: del new_question_data['chapter_id']
             return ADDING_GRADE_LEVEL
         else:
             # Should not happen if grade selection was successful before
             safe_edit_message_text(query, text="خطأ في الرجوع. إلغاء الإضافة.", reply_markup=create_admin_menu_keyboard())
             del context.user_data['new_question']
             return ADMIN_MENU
    else:
        grade_id = new_question_data['grade_level_id']
        keyboard = create_chapters_keyboard(grade_id, for_quiz=False, context=context)
        safe_edit_message_text(query, text="خيار غير صالح. يرجى اختيار فصل.", reply_markup=keyboard)
        return ADDING_CHAPTER

def add_question_lesson(update: Update, context: CallbackContext) -> int:
    """Handles the lesson selection callback for adding a question."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    if not is_admin(user_id):
        safe_edit_message_text(query, text=" وصول غير مصرح به.")
        return cancel(update, context)

    new_question_data = context.user_data.get('new_question')
    if not new_question_data or 'chapter_id' not in new_question_data:
        safe_edit_message_text(query, text="حدث خطأ (مفقود الفصل). يرجى البدء من جديد.")
        return cancel(update, context)

    if data.startswith('admin_lesson_'):
        try:
            lesson_id = int(data.split('_')[2])
            new_question_data['lesson_id'] = lesson_id
            logger.info(f"Admin {user_id} selected lesson {lesson_id} for new question.")
            # All info gathered, save the question
            safe_edit_message_text(query, text="✅ تم تحديد الدرس. جارٍ حفظ السؤال...")
            return save_new_question(update, context)
        except (ValueError, IndexError):
            logger.warning(f"Invalid lesson ID format in admin callback: {data}")
            safe_edit_message_text(query, text="حدث خطأ. يرجى المحاولة مرة أخرى.")
            # Resend lesson selection
            chapter_id = new_question_data['chapter_id']
            keyboard = create_lessons_keyboard(chapter_id, for_quiz=False, context=context)
            safe_edit_message_text(query, text="اختر الدرس:", reply_markup=keyboard)
            return ADDING_LESSON
    elif data == 'admin_manage_structure': # Back button (from lesson selection)
         # Go back to chapter selection
         grade_id = new_question_data['grade_level_id']
         keyboard = create_chapters_keyboard(grade_id, for_quiz=False, context=context)
         if keyboard:
             safe_edit_message_text(query, text="اختر الفصل:", reply_markup=keyboard)
             # Remove lesson_id if we go back
             if 'lesson_id' in new_question_data: del new_question_data['lesson_id']
             return ADDING_CHAPTER
         else:
             # Should not happen
             safe_edit_message_text(query, text="خطأ في الرجوع. إلغاء الإضافة.", reply_markup=create_admin_menu_keyboard())
             del context.user_data['new_question']
             return ADMIN_MENU
    else:
        chapter_id = new_question_data['chapter_id']
        keyboard = create_lessons_keyboard(chapter_id, for_quiz=False, context=context)
        safe_edit_message_text(query, text="خيار غير صالح. يرجى اختيار درس أو الرجوع.", reply_markup=keyboard)
        return ADDING_LESSON

def save_new_question(update: Update, context: CallbackContext) -> int:
    """Saves the completed question to the database."""
    user_id = context.user_data.get("user_id") # Get user_id from context
    if not user_id or not is_admin(user_id):
        logger.warning("Unauthorized attempt to save question or missing user_id.")
        if update and update.effective_message:
             update.effective_message.reply_text("خطأ: غير مصرح لك أو خطأ في الجلسة.")
        return cancel(update, context) if update else ConversationHandler.END

    new_question_data = context.user_data.get('new_question')
    if not new_question_data or 'text' not in new_question_data or 'options' not in new_question_data or 'correct_index' not in new_question_data:
        logger.error(f"Incomplete question data for admin {user_id}: {new_question_data}")
        message = "بيانات السؤال غير مكتملة. تعذر الحفظ. يرجى المحاولة مرة أخرى."
        if update and update.callback_query:
            safe_edit_message_text(update.callback_query, text=message, reply_markup=create_admin_menu_keyboard())
        elif update and update.message:
            update.message.reply_text(message, reply_markup=create_admin_menu_keyboard())
        else: # If called from job or context without update
             context.bot.send_message(chat_id=user_id, text=message, reply_markup=create_admin_menu_keyboard())
        if 'new_question' in context.user_data: del context.user_data['new_question']
        return ADMIN_MENU

    # Extract data
    question_text = new_question_data['text']
    options = new_question_data['options']
    correct_option_index = new_question_data['correct_index']
    image_path = new_question_data.get('image_path') # Optional
    grade_level_id = new_question_data.get('grade_level_id') # Optional
    chapter_id = new_question_data.get('chapter_id') # Optional
    lesson_id = new_question_data.get('lesson_id') # Optional

    # Save to DB
    question_id = QUIZ_DB.add_question(
        question_text,
        options,
        correct_option_index,
        image_path,
        grade_level_id,
        chapter_id,
        lesson_id
    )

    final_message = ""
    if question_id:
        final_message = f"✅ تم حفظ السؤال بنجاح!\nID السؤال الجديد: {question_id}"
        logger.info(f"Admin {user_id} successfully added question {question_id}.")
    else:
        final_message = "❌ حدث خطأ أثناء حفظ السؤال في قاعدة البيانات."
        logger.error(f"Admin {user_id} failed to save question: {new_question_data}")

    # Send confirmation and return to admin menu
    keyboard = create_admin_menu_keyboard()
    if update and update.callback_query:
        # If triggered by a button press (like lesson selection)
        safe_edit_message_text(update.callback_query, text=final_message, reply_markup=keyboard)
    elif update and update.message:
        # If triggered by a message (like skipping grade/chapter/lesson)
        update.message.reply_text(final_message, reply_markup=keyboard)
    else:
        # If called without update (shouldn't happen in this flow normally)
        context.bot.send_message(chat_id=user_id, text=final_message, reply_markup=keyboard)

    # Clean up
    if 'new_question' in context.user_data: del context.user_data['new_question']
    return ADMIN_MENU

# --- Delete Question Flow ---

def delete_question_id(update: Update, context: CallbackContext) -> int:
    """Receives the ID of the question to delete."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text(" وصول غير مصرح به.")
        return cancel(update, context)

    try:
        question_id_to_delete = int(update.message.text)
        logger.info(f"Admin {user_id} attempting to delete question {question_id_to_delete}.")

        # Optional: Show question details before confirming deletion?
        question_data = QUIZ_DB.get_question_by_id(question_id_to_delete)

        if not question_data:
            update.message.reply_text(f"لم يتم العثور على سؤال بالـ ID: {question_id_to_delete}. يرجى التأكد من الـ ID والمحاولة مرة أخرى.", reply_markup=create_admin_menu_keyboard())
            return ADMIN_MENU

        # Attempt deletion
        success = QUIZ_DB.delete_question(question_id_to_delete)

        if success:
            update.message.reply_text(f"🗑️ تم حذف السؤال ذي الـ ID: {question_id_to_delete} بنجاح.", reply_markup=create_admin_menu_keyboard())
            logger.info(f"Admin {user_id} successfully deleted question {question_id_to_delete}.")
            # Consider deleting associated image file if it exists and is no longer needed
            if question_data.get('image_path'):
                 try:
                      # Check if other questions use the same image before deleting?
                      # For simplicity, let's just try deleting it.
                      os.remove(question_data['image_path'])
                      logger.info(f"Deleted associated image: {question_data['image_path']}")
                 except OSError as e:
                      logger.warning(f"Could not delete image file {question_data['image_path']}: {e}")
        else:
            update.message.reply_text(f"❌ حدث خطأ أثناء محاولة حذف السؤال ذي الـ ID: {question_id_to_delete}.", reply_markup=create_admin_menu_keyboard())
            logger.error(f"Admin {user_id} failed to delete question {question_id_to_delete}.")

        return ADMIN_MENU

    except ValueError:
        update.message.reply_text("إدخال غير صالح. يرجى إرسال رقم ID السؤال.", reply_markup=create_admin_menu_keyboard())
        return DELETING_QUESTION # Stay in this state to re-prompt

# --- Show Question Flow ---

def show_question_id(update: Update, context: CallbackContext) -> int:
    """Receives the ID of the question to show."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text(" وصول غير مصرح به.")
        return cancel(update, context)

    try:
        question_id_to_show = int(update.message.text)
        logger.info(f"Admin {user_id} requesting to view question {question_id_to_show}.")

        question_data = QUIZ_DB.get_question_by_id(question_id_to_show)

        if not question_data:
            update.message.reply_text(f"لم يتم العثور على سؤال بالـ ID: {question_id_to_show}.", reply_markup=create_admin_menu_keyboard())
            return ADMIN_MENU

        # Format question details
        text = f"👁️ تفاصيل السؤال (ID: {question_id_to_show})\n\n"
        text += f"*النص:* {question_data['question_text']}\n\n"
        text += "*الخيارات:*\n"
        for i, option in enumerate(question_data['options']):
            prefix = "✅" if i == question_data['correct_option_index'] else "🔘"
            text += f" {prefix} {i+1}. {option}\n"
        text += f"\n*المرحلة:* {question_data.get('grade_name', 'غير محدد')}\n"
        text += f"*الفصل:* {question_data.get('chapter_name', 'غير محدد')}\n"
        text += f"*الدرس:* {question_data.get('lesson_name', 'غير محدد')}\n"
        image_path = question_data.get('image_path')

        # Send details (with image if available)
        if image_path:
            try:
                with open(image_path, 'rb') as img:
                    update.message.reply_photo(photo=img, caption=text, reply_markup=create_admin_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)
            except FileNotFoundError:
                 logger.warning(f"Image file not found for showing question {question_id_to_show}: {image_path}")
                 update.message.reply_text(f"{text}\n\n(تعذر تحميل الصورة: {image_path})", reply_markup=create_admin_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                 logger.error(f"Error sending photo for question {question_id_to_show}: {e}")
                 update.message.reply_text(text, reply_markup=create_admin_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)
        else:
            update.message.reply_text(text, reply_markup=create_admin_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)

        return ADMIN_MENU

    except ValueError:
        update.message.reply_text("إدخال غير صالح. يرجى إرسال رقم ID السؤال.", reply_markup=create_admin_menu_keyboard())
        return SHOWING_QUESTION # Stay in this state to re-prompt

# --- Structure Management Callbacks ---

def structure_admin_menu_callback(update: Update, context: CallbackContext) -> int:
     """Handles structure management menu button presses."""
     query = update.callback_query
     query.answer()
     user_id = query.from_user.id
     data = query.data

     if not is_admin(user_id):
         safe_edit_message_text(query, text=" وصول غير مصرح به.", reply_markup=create_main_menu_keyboard(user_id))
         return MAIN_MENU

     logger.info(f"Admin {user_id} chose {data} from structure admin menu.")

     if data == 'admin_manage_grades':
         # TODO: Implement grade management (add/edit/delete)
         safe_edit_message_text(query, text="إدارة المراحل قيد التطوير.", reply_markup=create_structure_admin_menu_keyboard())
         return ADMIN_MANAGE_STRUCTURE
     elif data == 'admin_manage_chapters':
         # TODO: Implement chapter management
         safe_edit_message_text(query, text="إدارة الفصول قيد التطوير.", reply_markup=create_structure_admin_menu_keyboard())
         return ADMIN_MANAGE_STRUCTURE
     elif data == 'admin_manage_lessons':
         # TODO: Implement lesson management
         safe_edit_message_text(query, text="إدارة الدروس قيد التطوير.", reply_markup=create_structure_admin_menu_keyboard())
         return ADMIN_MANAGE_STRUCTURE
     elif data == 'menu_admin':
         safe_edit_message_text(query, text="قائمة الإدارة:", reply_markup=create_admin_menu_keyboard())
         return ADMIN_MENU
     else:
         safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_structure_admin_menu_keyboard())
         return ADMIN_MANAGE_STRUCTURE

# --- Error Handler ---

def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)
    # Optionally inform user about the error
    # if update and isinstance(update, Update) and update.effective_message:
    #     update.effective_message.reply_text("حدث خطأ ما. يرجى المحاولة مرة أخرى لاحقاً.")

# --- Main Function ---

def main() -> None:
    """Start the bot."""
    # Create the Updater and pass it your bot's token.
    updater = Updater(BOT_TOKEN)

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher

    # --- Conversation Handler Setup ---
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CallbackQueryHandler(main_menu_callback, pattern='^menu_info$') # Entry point for info menu
            ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(main_menu_callback, pattern='^(menu_|main_menu)$'),
                CommandHandler('help', help_command), # Allow help anytime
            ],
            QUIZ_MENU: [
                CallbackQueryHandler(quiz_menu_callback, pattern='^(quiz_|main_menu)$')
            ],
            ADMIN_MENU: [
                CallbackQueryHandler(admin_menu_callback, pattern='^(admin_|main_menu)$')
            ],
            SELECTING_QUIZ_DURATION: [
                CallbackQueryHandler(select_quiz_duration_callback, pattern='^(duration_|menu_quiz)$')
            ],
            SELECT_GRADE_LEVEL_FOR_QUIZ: [
                 CallbackQueryHandler(select_grade_level_callback, pattern='^(grade_quiz_|menu_quiz)$')
            ],
            SELECT_CHAPTER_FOR_QUIZ: [
                 CallbackQueryHandler(select_chapter_for_quiz_callback, pattern='^(chapter_quiz_|quiz_by_grade_prompt)$')
            ],
            SELECT_CHAPTER_FOR_LESSON: [
                 CallbackQueryHandler(select_chapter_for_lesson_callback, pattern='^(lesson_chapter_|quiz_by_grade_prompt)$')
            ],
            SELECT_LESSON_FOR_QUIZ: [
                 # Pattern needs to handle back button correctly
                 CallbackQueryHandler(select_lesson_for_quiz_callback, pattern='^(lesson_quiz_|grade_quiz_|quiz_by_lesson_prompt)$')
            ],
            RUNNING_QUIZ: [
                CallbackQueryHandler(handle_answer, pattern='^answer_'),
                CallbackQueryHandler(skip_question, pattern='^skip_')
                # No other handlers here, quiz ends via timer or last answer
            ],
            VIEWING_RESULTS: [
                CallbackQueryHandler(results_menu_callback, pattern='^(menu_quiz|main_menu|review_)')
            ],
            # Admin Add Question Flow
            ADDING_QUESTION: [MessageHandler(Filters.text & ~Filters.command, add_question_text)],
            ADDING_OPTIONS: [
                MessageHandler(Filters.text & ~Filters.command, add_question_option),
                CommandHandler('done', add_question_done_options)
            ],
            ADDING_CORRECT_OPTION: [MessageHandler(Filters.text & ~Filters.command, add_question_correct_option)],
            ADDING_IMAGE: [
                MessageHandler(Filters.photo, add_question_image),
                CommandHandler('skip', add_question_skip_image)
            ],
            ADDING_GRADE_LEVEL: [CallbackQueryHandler(add_question_grade_level, pattern='^(grade_admin_|admin_manage_structure)$')],
            ADDING_CHAPTER: [CallbackQueryHandler(add_question_chapter, pattern='^(admin_chapter_|admin_manage_structure)$')],
            ADDING_LESSON: [CallbackQueryHandler(add_question_lesson, pattern='^(admin_lesson_|admin_manage_structure)$')],
            # Admin Delete/Show Question Flow
            DELETING_QUESTION: [MessageHandler(Filters.text & ~Filters.command, delete_question_id)],
            SHOWING_QUESTION: [MessageHandler(Filters.text & ~Filters.command, show_question_id)],
            # Admin Structure Management Flow
            ADMIN_MANAGE_STRUCTURE: [CallbackQueryHandler(structure_admin_menu_callback, pattern='^(admin_manage_|menu_admin)$')],
            # INFO_MENU state is handled by info_menu_conv_handler
            INFO_MENU: [info_menu_conv_handler], # Delegate to the imported handler
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CommandHandler('start', start) # Allow restarting anytime
            ],
        # Allow re-entry into the conversation
        allow_reentry=True
    )

    dispatcher.add_handler(conv_handler)

    # Add the info menu handler separately if it's not fully integrated into the main one
    # dispatcher.add_handler(info_menu_conv_handler) # Might be redundant if INFO_MENU state points to it

    # Log all errors
    dispatcher.add_error_handler(error_handler)

    # Start the Bot (using Webhook for Heroku)
    if HEROKU_APP_NAME:
        logger.info(f"Starting webhook on port {PORT} for Heroku app {HEROKU_APP_NAME}")
        updater.start_webhook(listen="0.0.0.0",
                              port=PORT,
                              url_path=BOT_TOKEN,
                              webhook_url=f"https://{HEROKU_APP_NAME}.herokuapp.com/{BOT_TOKEN}")
        updater.idle()
    else:
        # Fallback to polling if not on Heroku (for local testing)
        logger.info("Starting bot with polling (not recommended for production).")
        updater.start_polling()
        updater.idle()

    # Close the database connection when the bot stops
    if DB_CONN:
        DB_CONN.close()
        logger.info("Database connection closed.")

if __name__ == '__main__':
    main()

