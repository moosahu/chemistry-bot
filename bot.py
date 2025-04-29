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
        back_callback = "quiz_by_lesson_prompt" # Or maybe store grade_id and go back to chapter selection for that grade?
        # Let's go back to the chapter selection prompt for the specific grade
        grade_id = context.user_data.get("selected_grade_id")
        if grade_id:
             back_callback = f"grade_quiz_{grade_id}" # This should trigger chapter selection again
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
    # FIX: Access user from update.effective_user
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
    # FIX: Access user from query.from_user
    user = query.from_user
    user_id = user.id
    data = query.data

    logger.info(f"User {user_id} chose {data} from main menu.")

    # Ensure user_id is in context if conversation was restarted
    if "user_id" not in context.user_data:
        context.user_data["user_id"] = user_id

    if data == 'menu_info':
        # Call the function to show the info menu
        return show_info_menu(update, context)
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
        about_text += "الإصدار: 1.0 (متوافق مع python-telegram-bot v12.8)"
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
        # حالة غير متوقعة، العودة للقائمة الرئيسية
        safe_edit_message_text(query,
            text="خيار غير معروف. العودة للقائمة الرئيسية.",
            reply_markup=create_main_menu_keyboard(user_id)
        )
        return MAIN_MENU

def quiz_menu_callback(update: Update, context: CallbackContext):
    """معالجة اختيارات قائمة الاختبارات."""
    query = update.callback_query
    query.answer()
    # FIX: Access user from query.from_user
    user = query.from_user
    user_id = user.id
    chat_id = query.message.chat_id
    data = query.data

    logger.info(f"User {user_id} chose {data} from quiz menu.")

    if data == 'main_menu':
        keyboard = create_main_menu_keyboard(user_id)
        query.edit_message_text("العودة إلى القائمة الرئيسية.", reply_markup=keyboard)
        return MAIN_MENU
    elif data == 'quiz_random_prompt':
        context.user_data['quiz_type'] = 'random'
        query.edit_message_text(
            text="اختر مدة الاختبار العشوائي:",
            reply_markup=create_quiz_duration_keyboard()
        )
        return SELECTING_QUIZ_DURATION
    elif data == 'quiz_by_grade_prompt':
        context.user_data['quiz_type'] = 'grade'
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
        if keyboard:
            query.edit_message_text(
                text="اختر المرحلة الدراسية للاختبار:",
                reply_markup=keyboard
            )
            return SELECT_GRADE_LEVEL_FOR_QUIZ
        else:
            query.edit_message_text(
                text="عذراً، لا توجد مراحل دراسية متاحة حالياً.",
                reply_markup=create_quiz_menu_keyboard()
            )
            return QUIZ_MENU
    elif data == 'quiz_by_chapter_prompt':
        context.user_data['quiz_type'] = 'chapter'
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context) # Start by selecting grade
        if keyboard:
            query.edit_message_text(
                text="أولاً، اختر المرحلة الدراسية:",
                reply_markup=keyboard
            )
            return SELECT_GRADE_LEVEL_FOR_QUIZ # Go to grade selection first
        else:
            query.edit_message_text(
                text="عذراً، لا توجد مراحل دراسية متاحة حالياً.",
                reply_markup=create_quiz_menu_keyboard()
            )
            return QUIZ_MENU
    elif data == 'quiz_by_lesson_prompt':
        context.user_data['quiz_type'] = 'lesson'
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context) # Start by selecting grade
        if keyboard:
            query.edit_message_text(
                text="أولاً، اختر المرحلة الدراسية:",
                reply_markup=keyboard
            )
            return SELECT_GRADE_LEVEL_FOR_QUIZ # Go to grade selection first
        else:
            query.edit_message_text(
                text="عذراً، لا توجد مراحل دراسية متاحة حالياً.",
                reply_markup=create_quiz_menu_keyboard()
            )
            return QUIZ_MENU
    elif data == 'quiz_review_prompt':
        # TODO: Implement quiz review feature
        query.edit_message_text(
            text="ميزة مراجعة الأخطاء قيد التطوير.",
            reply_markup=create_quiz_menu_keyboard()
        )
        return QUIZ_MENU
    else:
        query.edit_message_text(
            text="خيار غير معروف. العودة لقائمة الاختبارات.",
            reply_markup=create_quiz_menu_keyboard()
        )
        return QUIZ_MENU

def admin_menu_callback(update: Update, context: CallbackContext):
    """معالجة اختيارات قائمة الإدارة."""
    query = update.callback_query
    query.answer()
    # FIX: Access user from query.from_user
    user = query.from_user
    user_id = user.id
    chat_id = query.message.chat_id
    data = query.data

    logger.info(f"Admin {user_id} chose {data} from admin menu.")

    if not is_admin(user_id):
        query.edit_message_text(
            text="عذراً، ليس لديك صلاحية الوصول لهذه القائمة.",
            reply_markup=create_main_menu_keyboard(user_id)
        )
        return MAIN_MENU

    if data == 'main_menu':
        keyboard = create_main_menu_keyboard(user_id)
        query.edit_message_text("العودة إلى القائمة الرئيسية.", reply_markup=keyboard)
        return MAIN_MENU
    elif data == 'admin_add_question':
        # Start the process of adding a question
        context.user_data['new_question'] = {}
        query.edit_message_text("أرسل نص السؤال الجديد:")
        return ADDING_QUESTION
    elif data == 'admin_delete_question':
        query.edit_message_text("أرسل رقم السؤال الذي تريد حذفه:")
        return DELETING_QUESTION
    elif data == 'admin_show_question':
        query.edit_message_text("أرسل رقم السؤال الذي تريد عرضه:")
        return SHOWING_QUESTION
    elif data == 'admin_manage_structure':
        query.edit_message_text(
            text="اختر القسم الذي تريد إدارته:",
            reply_markup=create_structure_admin_menu_keyboard()
        )
        return ADMIN_MANAGE_STRUCTURE # New state for structure management
    else:
        query.edit_message_text(
            text="خيار غير معروف. العودة لقائمة الإدارة.",
            reply_markup=create_admin_menu_keyboard()
        )
        return ADMIN_MENU

def admin_structure_menu_callback(update: Update, context: CallbackContext):
    """Callback for the structure management menu."""
    query = update.callback_query
    query.answer()
    # FIX: Access user from query.from_user
    user = query.from_user
    user_id = user.id
    data = query.data

    logger.info(f"Admin {user_id} chose {data} from structure admin menu.")

    if not is_admin(user_id):
        query.edit_message_text("Unauthorized access.", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU

    if data == 'admin_manage_grades':
        context.user_data['admin_context'] = 'manage_grades'
        keyboard = create_grade_levels_keyboard(for_quiz=False, context=context)
        query.edit_message_text(
            text="إدارة المراحل الدراسية. اختر مرحلة للتعديل أو أضف مرحلة جديدة.",
            reply_markup=keyboard # Show existing grades + Add button?
            # TODO: Add 'Add Grade' button here or handle via message
        )
        # Need a way to add/edit/delete grades - maybe handle text input?
        query.message.reply_text("لإضافة مرحلة جديدة، أرسل اسمها.") # Prompt for adding
        return ADMIN_MANAGE_GRADES
    elif data == 'admin_manage_chapters':
        context.user_data['admin_context'] = 'manage_chapters'
        # First, select the grade level to manage chapters for
        keyboard = create_grade_levels_keyboard(for_quiz=False, context=context)
        query.edit_message_text(
            text="إدارة الفصول. اختر المرحلة الدراسية أولاً:",
            reply_markup=keyboard
        )
        return ADMIN_MANAGE_GRADES # Reuse state, context determines action
    elif data == 'admin_manage_lessons':
        context.user_data['admin_context'] = 'manage_lessons'
        # First, select the grade level, then the chapter
        keyboard = create_grade_levels_keyboard(for_quiz=False, context=context)
        query.edit_message_text(
            text="إدارة الدروس. اختر المرحلة الدراسية أولاً:",
            reply_markup=keyboard
        )
        return ADMIN_MANAGE_GRADES # Reuse state
    elif data == 'menu_admin':
        query.edit_message_text(
            text="العودة لقائمة الإدارة الرئيسية.",
            reply_markup=create_admin_menu_keyboard()
        )
        return ADMIN_MENU
    else:
        query.edit_message_text("خيار غير معروف.", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE

# --- Quiz Selection Callbacks ---

def select_grade_level_quiz_callback(update: Update, context: CallbackContext):
    """Handles selecting a grade level for a quiz."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == 'menu_quiz':
        query.edit_message_text("العودة لقائمة الاختبارات.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

    grade_level_id_str = data.split('_')[-1]

    if grade_level_id_str == 'all':
        context.user_data['selected_grade_id'] = 'all'
        logger.info(f"User {user_id} selected all grade levels for quiz.")
        # If quiz type was grade, proceed to duration selection
        if context.user_data.get('quiz_type') == 'grade':
             query.edit_message_text(
                 text="اختر مدة الاختبار التحصيلي العام:",
                 reply_markup=create_quiz_duration_keyboard()
             )
             return SELECTING_QUIZ_DURATION
        else:
             # Should not happen if flow is correct, go back
             query.edit_message_text("خطأ في التدفق. العودة لقائمة الاختبارات.", reply_markup=create_quiz_menu_keyboard())
             return QUIZ_MENU

    try:
        grade_level_id = int(grade_level_id_str)
        context.user_data['selected_grade_id'] = grade_level_id
        logger.info(f"User {user_id} selected grade level {grade_level_id} for quiz.")

        quiz_type = context.user_data.get('quiz_type')
        if quiz_type == 'grade':
            query.edit_message_text(
                text="اختر مدة الاختبار لهذه المرحلة:",
                reply_markup=create_quiz_duration_keyboard()
            )
            return SELECTING_QUIZ_DURATION
        elif quiz_type == 'chapter':
            keyboard = create_chapters_keyboard(grade_level_id, for_quiz=True, context=context)
            if keyboard:
                query.edit_message_text(
                    text="الآن، اختر الفصل:",
                    reply_markup=keyboard
                )
                return SELECT_CHAPTER_FOR_QUIZ
            else:
                query.edit_message_text(
                    text="لا توجد فصول متاحة لهذه المرحلة. العودة لقائمة الاختبارات.",
                    reply_markup=create_quiz_menu_keyboard()
                )
                return QUIZ_MENU
        elif quiz_type == 'lesson':
            keyboard = create_chapters_keyboard(grade_level_id, for_lesson=True, context=context) # Need chapters to select lesson
            if keyboard:
                query.edit_message_text(
                    text="الآن، اختر الفصل الذي يحتوي على الدرس:",
                    reply_markup=keyboard
                )
                return SELECT_CHAPTER_FOR_LESSON # Go to chapter selection for lesson quiz
            else:
                query.edit_message_text(
                    text="لا توجد فصول متاحة لهذه المرحلة. العودة لقائمة الاختبارات.",
                    reply_markup=create_quiz_menu_keyboard()
                )
                return QUIZ_MENU
        else:
            # Should not happen
            query.edit_message_text("خطأ: نوع اختبار غير معروف. العودة لقائمة الاختبارات.", reply_markup=create_quiz_menu_keyboard())
            return QUIZ_MENU

    except (ValueError, IndexError):
        logger.error(f"Invalid callback data for grade selection: {data}")
        query.edit_message_text("حدث خطأ أثناء اختيار المرحلة. حاول مرة أخرى.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

def select_chapter_quiz_callback(update: Update, context: CallbackContext):
    """Handles selecting a chapter for a chapter-based quiz."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == 'quiz_by_chapter_prompt':
        # Go back to grade selection for chapter quiz
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
        if keyboard:
            query.edit_message_text(
                text="اختر المرحلة الدراسية مجدداً:",
                reply_markup=keyboard
            )
            return SELECT_GRADE_LEVEL_FOR_QUIZ
        else:
            query.edit_message_text("لا توجد مراحل متاحة.", reply_markup=create_quiz_menu_keyboard())
            return QUIZ_MENU

    try:
        chapter_id = int(data.split('_')[-1])
        context.user_data['selected_chapter_id'] = chapter_id
        logger.info(f"User {user_id} selected chapter {chapter_id} for quiz.")

        # Now ask for duration
        query.edit_message_text(
            text="اختر مدة الاختبار لهذا الفصل:",
            reply_markup=create_quiz_duration_keyboard()
        )
        return SELECTING_QUIZ_DURATION

    except (ValueError, IndexError):
        logger.error(f"Invalid callback data for chapter selection: {data}")
        # Try going back to chapter selection for the stored grade
        grade_id = context.user_data.get('selected_grade_id')
        if grade_id:
            keyboard = create_chapters_keyboard(grade_id, for_quiz=True, context=context)
            if keyboard:
                 query.edit_message_text("حدث خطأ. اختر الفصل مرة أخرى:", reply_markup=keyboard)
                 return SELECT_CHAPTER_FOR_QUIZ
        # Fallback to main quiz menu
        query.edit_message_text("حدث خطأ. العودة لقائمة الاختبارات.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

def select_chapter_for_lesson_quiz_callback(update: Update, context: CallbackContext):
    """Handles selecting the chapter when the goal is a lesson-based quiz."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == 'quiz_by_lesson_prompt':
        # Go back to grade selection for lesson quiz
        keyboard = create_grade_levels_keyboard(for_quiz=True, context=context)
        if keyboard:
            query.edit_message_text(
                text="اختر المرحلة الدراسية مجدداً:",
                reply_markup=keyboard
            )
            return SELECT_GRADE_LEVEL_FOR_QUIZ
        else:
            query.edit_message_text("لا توجد مراحل متاحة.", reply_markup=create_quiz_menu_keyboard())
            return QUIZ_MENU

    try:
        chapter_id = int(data.split('_')[-1])
        context.user_data['selected_chapter_id'] = chapter_id # Store chapter for lesson selection
        logger.info(f"User {user_id} selected chapter {chapter_id} to find a lesson for quiz.")

        # Now show lessons for this chapter
        keyboard = create_lessons_keyboard(chapter_id, for_quiz=True, context=context)
        if keyboard:
            query.edit_message_text(
                text="الآن، اختر الدرس:",
                reply_markup=keyboard
            )
            return SELECT_LESSON_FOR_QUIZ
        else:
            query.edit_message_text(
                text="لا توجد دروس متاحة لهذا الفصل. العودة لقائمة الاختبارات.",
                reply_markup=create_quiz_menu_keyboard()
            )
            return QUIZ_MENU

    except (ValueError, IndexError):
        logger.error(f"Invalid callback data for chapter selection (for lesson): {data}")
        # Try going back to chapter selection for the stored grade
        grade_id = context.user_data.get('selected_grade_id')
        if grade_id:
            keyboard = create_chapters_keyboard(grade_id, for_lesson=True, context=context)
            if keyboard:
                 query.edit_message_text("حدث خطأ. اختر الفصل مرة أخرى:", reply_markup=keyboard)
                 return SELECT_CHAPTER_FOR_LESSON
        # Fallback to main quiz menu
        query.edit_message_text("حدث خطأ. العودة لقائمة الاختبارات.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

def select_lesson_quiz_callback(update: Update, context: CallbackContext):
    """Handles selecting a lesson for a lesson-based quiz."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == 'quiz_by_lesson_prompt': # Go back to chapter selection
        grade_id = context.user_data.get('selected_grade_id')
        if grade_id:
            keyboard = create_chapters_keyboard(grade_id, for_lesson=True, context=context)
            if keyboard:
                query.edit_message_text("اختر الفصل مجدداً:", reply_markup=keyboard)
                return SELECT_CHAPTER_FOR_LESSON
        # Fallback
        query.edit_message_text("العودة لقائمة الاختبارات.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

    try:
        lesson_id = int(data.split('_')[-1])
        context.user_data['selected_lesson_id'] = lesson_id
        logger.info(f"User {user_id} selected lesson {lesson_id} for quiz.")

        # Now ask for duration
        query.edit_message_text(
            text="اختر مدة الاختبار لهذا الدرس:",
            reply_markup=create_quiz_duration_keyboard()
        )
        return SELECTING_QUIZ_DURATION

    except (ValueError, IndexError):
        logger.error(f"Invalid callback data for lesson selection: {data}")
        # Try going back to lesson selection for the stored chapter
        chapter_id = context.user_data.get('selected_chapter_id')
        if chapter_id:
            keyboard = create_lessons_keyboard(chapter_id, for_quiz=True, context=context)
            if keyboard:
                 query.edit_message_text("حدث خطأ. اختر الدرس مرة أخرى:", reply_markup=keyboard)
                 return SELECT_LESSON_FOR_QUIZ
        # Fallback to main quiz menu
        query.edit_message_text("حدث خطأ. العودة لقائمة الاختبارات.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

def select_quiz_duration_callback(update: Update, context: CallbackContext) -> int:
    """Handles selecting the quiz duration and starts the quiz."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == 'menu_quiz':
        query.edit_message_text("العودة لقائمة الاختبارات.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

    duration_key = data.split('_')[-1]
    if duration_key not in QUIZ_DURATIONS:
        logger.warning(f"Invalid duration key: {duration_key}")
        query.edit_message_text("مدة غير صالحة. حاول مرة أخرى.", reply_markup=create_quiz_duration_keyboard())
        return SELECTING_QUIZ_DURATION

    duration = QUIZ_DURATIONS[duration_key]
    context.user_data['quiz_duration'] = duration
    context.user_data['quiz_start_time'] = datetime.now()
    context.user_data['current_question_index'] = 0
    context.user_data['score'] = 0
    context.user_data['answered_questions'] = [] # Store (q_id, selected_option, correct_option, is_correct)

    quiz_type = context.user_data.get('quiz_type')
    grade_id = context.user_data.get('selected_grade_id')
    chapter_id = context.user_data.get('selected_chapter_id')
    lesson_id = context.user_data.get('selected_lesson_id')

    questions = []
    try:
        if quiz_type == 'random':
            # Get random questions (across all grades or implement specific logic)
            questions = QUIZ_DB.get_questions_by_grade(None, DEFAULT_QUIZ_QUESTIONS) # Use get_questions_by_grade with None for random
            logger.info(f"Starting random quiz for user {user_id} with {len(questions)} questions, duration {duration}s.")
        elif quiz_type == 'grade':
            target_grade = grade_id if grade_id != 'all' else None
            questions = QUIZ_DB.get_questions_by_grade(target_grade, DEFAULT_QUIZ_QUESTIONS)
            logger.info(f"Starting grade quiz (Grade: {target_grade if target_grade else 'All'}) for user {user_id} with {len(questions)} questions, duration {duration}s.")
        elif quiz_type == 'chapter':
            questions = QUIZ_DB.get_questions_by_chapter(chapter_id, DEFAULT_QUIZ_QUESTIONS)
            logger.info(f"Starting chapter quiz (Chapter: {chapter_id}) for user {user_id} with {len(questions)} questions, duration {duration}s.")
        elif quiz_type == 'lesson':
            questions = QUIZ_DB.get_questions_by_lesson(lesson_id, DEFAULT_QUIZ_QUESTIONS)
            logger.info(f"Starting lesson quiz (Lesson: {lesson_id}) for user {user_id} with {len(questions)} questions, duration {duration}s.")
        else:
            raise ValueError("Unknown quiz type")

    except Exception as e:
        logger.error(f"Error fetching questions for quiz: {e}")
        query.edit_message_text("حدث خطأ أثناء إعداد الاختبار. يرجى المحاولة مرة أخرى لاحقاً.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

    if not questions:
        query.edit_message_text("عذراً، لا توجد أسئلة متاحة لهذا الاختيار حالياً.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

    context.user_data['quiz_questions'] = questions
    context.user_data['total_questions'] = len(questions)

    # Start the quiz timer
    context.job_queue.run_once(quiz_timer_expired, duration, context=query.message.chat_id, name=f"quiz_timer_{query.message.chat_id}")

    # Send the first question
    send_question(update, context, query.message.chat_id)
    return RUNNING_QUIZ

# --- Quiz Logic ---

def send_question(update: Update, context: CallbackContext, chat_id: int):
    """Sends the current quiz question to the user."""
    current_index = context.user_data.get('current_question_index', 0)
    questions = context.user_data.get('quiz_questions', [])
    total_questions = context.user_data.get('total_questions', 0)

    if not questions or current_index >= len(questions):
        logger.warning("send_question called with no questions or index out of bounds.")
        # End quiz if something went wrong
        end_quiz(update, context, chat_id)
        return ConversationHandler.END # Or appropriate state

    question_data = questions[current_index]
    question_id = question_data['id']
    question_text = question_data['question_text']
    options = question_data['options'] # List of strings
    image_data = question_data.get('image_data') # Optional image data (bytes)

    # Format question message
    message_text = f"*السؤال {current_index + 1} من {total_questions}:*

{question_text}"

    keyboard = create_quiz_question_keyboard(options, question_id)

    try:
        # Check if we need to edit a previous message or send a new one
        query = update.callback_query
        message_to_edit = query.message if query else None

        if image_data:
            # If there's an image, we usually need to send a new message
            # (Editing photo captions with inline keyboards can be tricky)
            # Delete previous message if possible to avoid clutter
            if message_to_edit:
                try:
                    context.bot.delete_message(chat_id=chat_id, message_id=message_to_edit.message_id)
                except TelegramError as e:
                    logger.warning(f"Could not delete previous message: {e}")
            context.bot.send_photo(
                chat_id=chat_id,
                photo=bytes(image_data),
                caption=message_text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            # If no image, edit the existing message
            if message_to_edit:
                 # Use safe_edit_message_text for robustness
                 safe_edit_message_text(query, text=message_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
            else:
                 # Should not happen in normal flow, but send new if needed
                 context.bot.send_message(
                     chat_id=chat_id,
                     text=message_text,
                     reply_markup=keyboard,
                     parse_mode=ParseMode.MARKDOWN
                 )

    except TelegramError as e:
        logger.error(f"Error sending question {question_id}: {e}")
        # Try sending a plain text message as fallback
        try:
            context.bot.send_message(chat_id=chat_id, text="حدث خطأ أثناء عرض السؤال. حاول التخطي أو إلغاء الاختبار.")
        except Exception as fallback_e:
            logger.error(f"Failed to send fallback error message: {fallback_e}")
        # Consider ending the quiz or allowing skip

def handle_answer(update: Update, context: CallbackContext) -> int:
    """Handles user's answer to a quiz question."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    # Parse callback data: answer_{question_id}_{selected_option_index} or skip_{question_id}
    parts = data.split('_')
    action = parts[0]
    try:
        question_id = int(parts[1])
    except (IndexError, ValueError):
        logger.error(f"Invalid callback data format: {data}")
        return RUNNING_QUIZ # Remain in the quiz state

    # --- Check if quiz time is up --- (Do this first)
    start_time = context.user_data.get('quiz_start_time')
    duration = context.user_data.get('quiz_duration')
    if start_time and duration and (datetime.now() - start_time).total_seconds() > duration:
        logger.info(f"Quiz time expired for user {user_id} during answer handling.")
        query.edit_message_text("⏳ انتهى وقت الاختبار!")
        end_quiz(update, context, chat_id)
        return VIEWING_RESULTS
    # --------------------------------

    questions = context.user_data.get('quiz_questions', [])
    current_index = context.user_data.get('current_question_index', 0)

    # Find the question data based on question_id (more robust than relying on index)
    current_question_data = next((q for q in questions if q['id'] == question_id), None)

    if not current_question_data:
        logger.warning(f"Question ID {question_id} not found in user's quiz data.")
        # Maybe the quiz ended or data got corrupted, try ending gracefully
        safe_edit_message_text(query, text="حدث خطأ غير متوقع. إنهاء الاختبار.")
        end_quiz(update, context, chat_id)
        return VIEWING_RESULTS

    # Prevent answering the same question twice
    if any(aq[0] == question_id for aq in context.user_data.get('answered_questions', [])):
        logger.info(f"User {user_id} tried to answer question {question_id} again.")
        # Optionally notify user: query.answer("لقد أجبت على هذا السؤال بالفعل.")
        return RUNNING_QUIZ # Stay in quiz state

    feedback_text = ""
    is_correct = None
    selected_option_index = -1
    correct_option_index = current_question_data['correct_option']

    if action == 'skip':
        logger.info(f"User {user_id} skipped question {question_id}.")
        feedback_text = f"تم تخطي السؤال.
الإجابة الصحيحة: {current_question_data['options'][correct_option_index]}"
        is_correct = False # Treat skip as incorrect for scoring
        # Record skipped question
        context.user_data['answered_questions'].append((question_id, -1, correct_option_index, False))

    elif action == 'answer':
        try:
            selected_option_index = int(parts[2])
            is_correct = (selected_option_index == correct_option_index)

            if is_correct:
                context.user_data['score'] = context.user_data.get('score', 0) + 1
                feedback_text = "✅ إجابة صحيحة!"
                logger.info(f"User {user_id} answered question {question_id} correctly.")
            else:
                feedback_text = f"❌ إجابة خاطئة.
الإجابة الصحيحة: {current_question_data['options'][correct_option_index]}"
                logger.info(f"User {user_id} answered question {question_id} incorrectly (chose {selected_option_index}, correct was {correct_option_index}).")

            # Record answered question
            context.user_data['answered_questions'].append((question_id, selected_option_index, correct_option_index, is_correct))

        except (IndexError, ValueError):
            logger.error(f"Invalid answer callback data format: {data}")
            return RUNNING_QUIZ # Remain in quiz state

    else:
        logger.warning(f"Unknown action in quiz callback: {action}")
        return RUNNING_QUIZ

    # --- Show Feedback --- (Edit the message to show feedback)
    original_message_text = query.message.caption if query.message.photo else query.message.text
    # Remove the old keyboard by setting reply_markup=None
    # Append feedback to the original question text
    new_text = f"{original_message_text}

{feedback_text}"

    try:
        if query.message.photo:
             # Edit caption if it was a photo message
             context.bot.edit_message_caption(
                 chat_id=chat_id,
                 message_id=query.message.message_id,
                 caption=new_text,
                 parse_mode=ParseMode.MARKDOWN,
                 reply_markup=None # Remove keyboard
             )
        else:
             # Edit text message
             # Use safe_edit_message_text but ensure it doesn't fail on identical content
             # We are *adding* feedback, so it shouldn't be identical unless error occurs
             try:
                 query.edit_message_text(
                     text=new_text,
                     parse_mode=ParseMode.MARKDOWN,
                     reply_markup=None # Remove keyboard
                 )
             except BadRequest as e:
                 if "Message is not modified" in str(e):
                     logger.info(f"Message not modified during feedback (likely already shown?): {e}")
                 else:
                     logger.warning(f"BadRequest editing message for feedback: {e}")
                     # Fallback: Send feedback as a new message if edit fails
                     context.bot.send_message(chat_id=chat_id, text=feedback_text)
             except Exception as e:
                 logger.error(f"Unexpected error editing message for feedback: {e}")
                 # Fallback: Send feedback as a new message
                 context.bot.send_message(chat_id=chat_id, text=feedback_text)

    except TelegramError as e:
        logger.error(f"Error showing feedback for question {question_id}: {e}")
        # Fallback: Send feedback as a new message
        context.bot.send_message(chat_id=chat_id, text=feedback_text)

    # --- Proceed to Next Question or End Quiz ---
    context.user_data['current_question_index'] = current_index + 1

    if context.user_data['current_question_index'] < context.user_data['total_questions']:
        # Schedule next question after a delay
        context.job_queue.run_once(lambda ctx: send_question(update, ctx, chat_id), FEEDBACK_DELAY, context=context, name=f"next_q_{chat_id}")
    else:
        # End of quiz
        logger.info(f"User {user_id} finished quiz.")
        # Schedule end_quiz after a delay
        context.job_queue.run_once(lambda ctx: end_quiz(update, ctx, chat_id), FEEDBACK_DELAY, context=context, name=f"end_quiz_{chat_id}")
        return VIEWING_RESULTS # Transition to results state

    return RUNNING_QUIZ # Stay in quiz state while waiting for next question

def quiz_timer_expired(context: CallbackContext):
    """Callback function when the quiz timer runs out."""
    chat_id = context.job.context
    bot = context.bot
    logger.info(f"Quiz timer expired for chat {chat_id}.")

    # Check if the quiz is still running for this chat
    # We need a way to access the user's context or pass the update object
    # This is tricky with run_once. A better approach might be needed,
    # maybe storing quiz state globally or passing user_id.
    # For now, just send a message.
    try:
        bot.send_message(chat_id=chat_id, text="⏳ انتهى وقت الاختبار!")
        # Ideally, we should also call end_quiz here, but we need the 'update' object
        # or access to the specific user's context.user_data which is hard from job context.
        # A workaround: The next time the user interacts (e.g., answers), handle_answer
        # will check the time and call end_quiz.
    except TelegramError as e:
        logger.error(f"Error sending timer expired message to {chat_id}: {e}")

def end_quiz(update: Update, context: CallbackContext, chat_id: int):
    """Ends the quiz, calculates results, and shows them to the user."""
    user_id = context.user_data.get("user_id")
    score = context.user_data.get('score', 0)
    total_questions = context.user_data.get('total_questions', 0)
    answered_q_list = context.user_data.get('answered_questions', [])
    quiz_type = context.user_data.get('quiz_type', 'N/A')
    grade_id = context.user_data.get('selected_grade_id')
    chapter_id = context.user_data.get('selected_chapter_id')
    lesson_id = context.user_data.get('selected_lesson_id')

    logger.info(f"Ending quiz for user {user_id}. Score: {score}/{total_questions}")

    # Cancel timer if it's still running (e.g., quiz ended early)
    current_jobs = context.job_queue.get_jobs_by_name(f"quiz_timer_{chat_id}")
    for job in current_jobs:
        job.schedule_removal()
        logger.info(f"Removed active quiz timer job for chat {chat_id}.")
    # Also remove any pending next question jobs
    current_jobs = context.job_queue.get_jobs_by_name(f"next_q_{chat_id}")
    for job in current_jobs:
        job.schedule_removal()

    if total_questions > 0:
        percentage = round((score / total_questions) * 100)
        result_text = f"🎉 انتهى الاختبار! 🎉

نتيجتك: {score} من {total_questions} ({percentage}%)
"
        # Add performance feedback based on percentage
        if percentage == 100:
            result_text += "ممتاز جداً! أداء رائع! 🌟"
        elif percentage >= 80:
            result_text += "جيد جداً! استمر في التقدم! 👍"
        elif percentage >= 60:
            result_text += "جيد. يمكنك التحسن أكثر بالمراجعة. 💪"
        else:
            result_text += "تحتاج إلى المزيد من المراجعة والتركيز. لا تيأس! 📚"

        # Save quiz results to database
        quiz_id = QUIZ_DB.save_quiz_result(
            user_id=user_id,
            quiz_type=quiz_type,
            grade_level_id=grade_id if isinstance(grade_id, int) else None,
            chapter_id=chapter_id,
            lesson_id=lesson_id,
            score=score,
            total_questions=total_questions,
            percentage=percentage,
            duration=context.user_data.get('quiz_duration', 0) # Or calculate actual time
        )
        if quiz_id:
            logger.info(f"Saved quiz result with ID {quiz_id} for user {user_id}.")
            # Save detailed answers
            for q_id, selected, correct, is_correct_flag in answered_q_list:
                QUIZ_DB.save_quiz_answer(quiz_id, q_id, selected, is_correct_flag)
        else:
            logger.error(f"Failed to save quiz result for user {user_id}.")

        keyboard = create_results_menu_keyboard(quiz_id if quiz_id else 0)
        # Send results - check if we need to edit or send new
        query = update.callback_query
        if query and query.message:
             # Try editing the last message (which might be feedback)
             safe_edit_message_text(query, text=result_text, reply_markup=keyboard)
        else:
             # Send as a new message
             context.bot.send_message(chat_id=chat_id, text=result_text, reply_markup=keyboard)

    else:
        # No questions were answered or quiz had no questions
        result_text = "لم يتم إكمال الاختبار أو لم تكن هناك أسئلة."
        keyboard = create_main_menu_keyboard(user_id)
        query = update.callback_query
        if query and query.message:
             safe_edit_message_text(query, text=result_text, reply_markup=keyboard)
        else:
             context.bot.send_message(chat_id=chat_id, text=result_text, reply_markup=keyboard)
        return MAIN_MENU # Go back to main menu if quiz was invalid

    # Clean up quiz-specific data from context
    keys_to_clear = [
        'quiz_type', 'selected_grade_id', 'selected_chapter_id', 'selected_lesson_id',
        'quiz_duration', 'quiz_start_time', 'current_question_index', 'score',
        'answered_questions', 'quiz_questions', 'total_questions'
    ]
    for key in keys_to_clear:
        context.user_data.pop(key, None)

    return VIEWING_RESULTS # Stay in results state

# --- Admin Handlers ---

def handle_add_question_text(update: Update, context: CallbackContext) -> int:
    """Handles receiving the text for a new question."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text("غير مصرح لك.")
        return ConversationHandler.END

    question_text = update.message.text
    context.user_data['new_question']['text'] = question_text
    context.user_data['new_question']['options'] = [] # Initialize options list

    update.message.reply_text("حسناً، الآن أرسل الخيار الأول (أ).")
    return ADDING_OPTIONS

def handle_add_question_options(update: Update, context: CallbackContext) -> int:
    """Handles receiving options for the new question."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text("غير مصرح لك.")
        return ConversationHandler.END

    option_text = update.message.text
    options_list = context.user_data['new_question']['options']
    options_list.append(option_text)

    num_options = len(options_list)
    if num_options < 4: # Assuming 4 options (أ, ب, ج, د)
        next_option_letter = chr(ord('أ') + num_options)
        update.message.reply_text(f"تمت إضافة الخيار {chr(ord('أ') + num_options - 1)}. أرسل الخيار التالي ({next_option_letter}).")
        return ADDING_OPTIONS
    else:
        # Got all 4 options
        update.message.reply_text("تمت إضافة جميع الخيارات. الآن، أرسل رقم الخيار الصحيح (0 لـ أ, 1 لـ ب, 2 لـ ج, 3 لـ د).")
        return ADDING_CORRECT_OPTION

def handle_add_question_correct_option(update: Update, context: CallbackContext) -> int:
    """Handles receiving the correct option index."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text("غير مصرح لك.")
        return ConversationHandler.END

    try:
        correct_option_index = int(update.message.text.strip())
        if not (0 <= correct_option_index < 4):
            raise ValueError("Index out of range")
        context.user_data['new_question']['correct'] = correct_option_index

        # Ask for image (optional)
        keyboard = [[
            InlineKeyboardButton("🖼️ نعم، إضافة صورة", callback_data="add_image_yes"),
            InlineKeyboardButton("✏️ لا، حفظ بدون صورة", callback_data="add_image_no")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text("هل تريد إضافة صورة للسؤال؟", reply_markup=reply_markup)
        return ADDING_IMAGE # State to handle image yes/no

    except ValueError:
        update.message.reply_text("إدخال غير صالح. الرجاء إرسال رقم بين 0 و 3.")
        return ADDING_CORRECT_OPTION

def handle_add_question_image_decision(update: Update, context: CallbackContext) -> int:
    """Handles the admin's decision on adding an image."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.from_user.id

    if not is_admin(user_id):
        safe_edit_message_text(query, text="غير مصرح لك.")
        return ConversationHandler.END

    if data == 'add_image_yes':
        safe_edit_message_text(query, text="حسناً، أرسل الصورة الآن.")
        # Stay in ADDING_IMAGE state, waiting for photo message
        return ADDING_IMAGE
    elif data == 'add_image_no':
        # Save question without image
        context.user_data['new_question']['image'] = None
        # Ask for grade level
        keyboard = create_grade_levels_keyboard(for_quiz=False, context=context)
        if keyboard:
             safe_edit_message_text(query, text="اختر المرحلة الدراسية للسؤال:", reply_markup=keyboard)
             return ADDING_GRADE_LEVEL
        else:
             safe_edit_message_text(query, text="لا توجد مراحل دراسية. أضف مرحلة أولاً.", reply_markup=create_admin_menu_keyboard())
             return ADMIN_MENU
    else:
        safe_edit_message_text(query, text="خيار غير صالح.")
        return ADDING_IMAGE

def handle_add_question_image_upload(update: Update, context: CallbackContext) -> int:
    """Handles receiving the image for the new question."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text("غير مصرح لك.")
        return ConversationHandler.END

    if not update.message.photo:
        update.message.reply_text("الرجاء إرسال صورة.")
        return ADDING_IMAGE

    # Get the largest photo version
    photo_file = update.message.photo[-1].get_file()
    # Download photo as bytes
    image_bytes = photo_file.download_as_bytearray()
    context.user_data['new_question']['image'] = bytes(image_bytes)
    logger.info(f"Received image for new question, size: {len(image_bytes)} bytes.")

    # Ask for grade level
    keyboard = create_grade_levels_keyboard(for_quiz=False, context=context)
    if keyboard:
        update.message.reply_text("تم استلام الصورة. اختر المرحلة الدراسية للسؤال:", reply_markup=keyboard)
        return ADDING_GRADE_LEVEL
    else:
        update.message.reply_text("لا توجد مراحل دراسية. أضف مرحلة أولاً.", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU

def handle_add_question_grade(update: Update, context: CallbackContext) -> int:
    """Handles selecting the grade level for the new question."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.from_user.id

    if not is_admin(user_id):
        safe_edit_message_text(query, text="غير مصرح لك.")
        return ConversationHandler.END

    if data == 'admin_manage_structure': # Back button
        safe_edit_message_text(query, text="العودة لقائمة الإدارة.", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU

    try:
        grade_id = int(data.split('_')[-1])
        context.user_data['new_question']['grade_id'] = grade_id
        logger.info(f"Selected grade {grade_id} for new question.")

        # Ask for chapter
        keyboard = create_chapters_keyboard(grade_id, for_quiz=False, context=context)
        if keyboard:
            safe_edit_message_text(query, text="اختر الفصل للسؤال:", reply_markup=keyboard)
            return ADDING_CHAPTER
        else:
            # No chapters, ask to add one or save without chapter/lesson
            # For simplicity, let's save without chapter/lesson for now
            # TODO: Allow adding chapter/lesson directly here
            context.user_data['new_question']['chapter_id'] = None
            context.user_data['new_question']['lesson_id'] = None
            save_new_question(update, context, query)
            return ADMIN_MENU # Go back to admin menu after saving

    except (ValueError, IndexError):
        logger.error(f"Invalid callback data for grade selection (admin): {data}")
        safe_edit_message_text(query, text="خطأ في اختيار المرحلة.", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU

def handle_add_question_chapter(update: Update, context: CallbackContext) -> int:
    """Handles selecting the chapter for the new question."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.from_user.id

    if not is_admin(user_id):
        safe_edit_message_text(query, text="غير مصرح لك.")
        return ConversationHandler.END

    grade_id = context.user_data['new_question'].get('grade_id')
    if data == 'admin_manage_structure': # Back button
        # Go back to grade selection
        keyboard = create_grade_levels_keyboard(for_quiz=False, context=context)
        if keyboard:
             safe_edit_message_text(query, text="اختر المرحلة الدراسية مجدداً:", reply_markup=keyboard)
             return ADDING_GRADE_LEVEL
        else:
             safe_edit_message_text(query, text="العودة لقائمة الإدارة.", reply_markup=create_admin_menu_keyboard())
             return ADMIN_MENU

    try:
        chapter_id = int(data.split('_')[-1])
        context.user_data['new_question']['chapter_id'] = chapter_id
        logger.info(f"Selected chapter {chapter_id} for new question.")

        # Ask for lesson
        keyboard = create_lessons_keyboard(chapter_id, for_quiz=False, context=context)
        if keyboard:
            safe_edit_message_text(query, text="اختر الدرس للسؤال (أو اختر رجوع للحفظ بدون درس):", reply_markup=keyboard)
            return ADDING_LESSON
        else:
            # No lessons, save without lesson
            context.user_data['new_question']['lesson_id'] = None
            save_new_question(update, context, query)
            return ADMIN_MENU

    except (ValueError, IndexError):
        logger.error(f"Invalid callback data for chapter selection (admin): {data}")
        safe_edit_message_text(query, text="خطأ في اختيار الفصل.", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU

def handle_add_question_lesson(update: Update, context: CallbackContext) -> int:
    """Handles selecting the lesson for the new question."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.from_user.id

    if not is_admin(user_id):
        safe_edit_message_text(query, text="غير مصرح لك.")
        return ConversationHandler.END

    chapter_id = context.user_data['new_question'].get('chapter_id')
    grade_id = context.user_data['new_question'].get('grade_id')

    # Handle back button - go back to chapter selection
    if data == 'admin_manage_structure':
        if grade_id:
            keyboard = create_chapters_keyboard(grade_id, for_quiz=False, context=context)
            if keyboard:
                safe_edit_message_text(query, text="اختر الفصل مجدداً:", reply_markup=keyboard)
                return ADDING_CHAPTER
        # Fallback
        safe_edit_message_text(query, text="العودة لقائمة الإدارة.", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU

    try:
        lesson_id = int(data.split('_')[-1])
        context.user_data['new_question']['lesson_id'] = lesson_id
        logger.info(f"Selected lesson {lesson_id} for new question.")

        # All info gathered, save the question
        save_new_question(update, context, query)
        return ADMIN_MENU

    except (ValueError, IndexError):
        logger.error(f"Invalid callback data for lesson selection (admin): {data}")
        safe_edit_message_text(query, text="خطأ في اختيار الدرس.", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU

def save_new_question(update: Update, context: CallbackContext, query):
    """Helper function to save the completed new question to the database."""
    q_data = context.user_data.get('new_question')
    if not q_data or 'text' not in q_data or 'options' not in q_data or 'correct' not in q_data:
        logger.error("Incomplete question data in context during save.")
        safe_edit_message_text(query, text="حدث خطأ داخلي أثناء حفظ السؤال.", reply_markup=create_admin_menu_keyboard())
        return

    try:
        question_id = QUIZ_DB.add_question(
            question_text=q_data['text'],
            options=q_data['options'],
            correct_option=q_data['correct'],
            grade_level_id=q_data.get('grade_id'),
            chapter_id=q_data.get('chapter_id'),
            lesson_id=q_data.get('lesson_id'),
            image_data=q_data.get('image')
        )
        if question_id:
            logger.info(f"Successfully added new question with ID: {question_id}")
            safe_edit_message_text(query, text=f"تم حفظ السؤال بنجاح! (ID: {question_id})", reply_markup=create_admin_menu_keyboard())
        else:
            logger.error("Failed to add question to database (add_question returned None).")
            safe_edit_message_text(query, text="فشل حفظ السؤال في قاعدة البيانات.", reply_markup=create_admin_menu_keyboard())

    except Exception as e:
        logger.error(f"Exception while saving new question: {e}")
        safe_edit_message_text(query, text=f"حدث استثناء أثناء حفظ السؤال: {e}", reply_markup=create_admin_menu_keyboard())

    finally:
        # Clean up context
        context.user_data.pop('new_question', None)

def handle_delete_question(update: Update, context: CallbackContext) -> int:
    """Handles receiving the ID of the question to delete."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text("غير مصرح لك.")
        return ConversationHandler.END

    try:
        question_id_to_delete = int(update.message.text.strip())
        success = QUIZ_DB.delete_question(question_id_to_delete)
        if success:
            logger.info(f"Admin {user_id} deleted question {question_id_to_delete}.")
            update.message.reply_text(f"تم حذف السؤال رقم {question_id_to_delete} بنجاح.", reply_markup=create_admin_menu_keyboard())
        else:
            logger.warning(f"Admin {user_id} tried to delete non-existent question {question_id_to_delete}.")
            update.message.reply_text(f"لم يتم العثور على سؤال بهذا الرقم ({question_id_to_delete}).", reply_markup=create_admin_menu_keyboard())

    except ValueError:
        update.message.reply_text("إدخال غير صالح. الرجاء إرسال رقم السؤال.")
        return DELETING_QUESTION # Stay in state
    except Exception as e:
        logger.error(f"Error deleting question: {e}")
        update.message.reply_text(f"حدث خطأ أثناء الحذف: {e}", reply_markup=create_admin_menu_keyboard())

    return ADMIN_MENU # Return to admin menu

def handle_show_question(update: Update, context: CallbackContext) -> int:
    """Handles receiving the ID of the question to show."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text("غير مصرح لك.")
        return ConversationHandler.END

    try:
        question_id_to_show = int(update.message.text.strip())
        q_data = QUIZ_DB.get_question_by_id(question_id_to_show)

        if q_data:
            logger.info(f"Admin {user_id} viewed question {question_id_to_show}.")
            text = f"*السؤال {q_data['id']}*

*النص:* {q_data['question_text']}

*الخيارات:*
" + "\n".join([f"{chr(ord('أ') + i)}: {opt}" for i, opt in enumerate(q_data['options'])]) + "

" + f"*الإجابة الصحيحة:* {chr(ord('أ') + q_data['correct_option'])} ({q_data['options'][q_data['correct_option']]})
"
            grade = QUIZ_DB.get_grade_level_name(q_data.get('grade_level_id'))
            chapter = QUIZ_DB.get_chapter_name(q_data.get('chapter_id'))
            lesson = QUIZ_DB.get_lesson_name(q_data.get('lesson_id'))
            text += f"*المرحلة:* {grade if grade else 'غير محدد'}
"
            text += f"*الفصل:* {chapter if chapter else 'غير محدد'}
"
            text += f"*الدرس:* {lesson if lesson else 'غير محدد'}
"

            image_data = q_data.get('image_data')
            if image_data:
                update.message.reply_photo(
                    photo=bytes(image_data),
                    caption=text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=create_admin_menu_keyboard()
                )
            else:
                update.message.reply_text(
                    text=text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=create_admin_menu_keyboard()
                )
        else:
            logger.warning(f"Admin {user_id} tried to view non-existent question {question_id_to_show}.")
            update.message.reply_text(f"لم يتم العثور على سؤال بهذا الرقم ({question_id_to_show}).", reply_markup=create_admin_menu_keyboard())

    except ValueError:
        update.message.reply_text("إدخال غير صالح. الرجاء إرسال رقم السؤال.")
        return SHOWING_QUESTION # Stay in state
    except Exception as e:
        logger.error(f"Error showing question: {e}")
        update.message.reply_text(f"حدث خطأ أثناء عرض السؤال: {e}", reply_markup=create_admin_menu_keyboard())

    return ADMIN_MENU # Return to admin menu

# --- Structure Management Handlers (Admin) ---

def handle_manage_grades(update: Update, context: CallbackContext) -> int:
    """Handles adding/editing/deleting grade levels (Receives text input)."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text("غير مصرح لك.")
        return ConversationHandler.END

    admin_context = context.user_data.get('admin_context')
    if admin_context != 'manage_grades':
         # If user sent text but wasn't in the right context, ignore or guide them
         logger.warning(f"Admin {user_id} sent text '{update.message.text}' while in context '{admin_context}'. Ignoring.")
         return ADMIN_MANAGE_GRADES # Stay in state

    grade_name = update.message.text.strip()
    if not grade_name:
        update.message.reply_text("اسم المرحلة لا يمكن أن يكون فارغاً.")
        return ADMIN_MANAGE_GRADES

    try:
        grade_id = QUIZ_DB.add_grade_level(grade_name)
        if grade_id:
            logger.info(f"Admin {user_id} added new grade level: {grade_name} (ID: {grade_id})")
            update.message.reply_text(f"تمت إضافة المرحلة '{grade_name}' بنجاح.")
            # Refresh the keyboard
            keyboard = create_grade_levels_keyboard(for_quiz=False, context=context)
            update.message.reply_text("إدارة المراحل الدراسية:", reply_markup=keyboard)
        else:
            update.message.reply_text("فشل إضافة المرحلة (قد تكون موجودة بالفعل؟).")
    except Exception as e:
        logger.error(f"Error adding grade level '{grade_name}': {e}")
        update.message.reply_text(f"حدث خطأ: {e}")

    return ADMIN_MANAGE_GRADES # Stay in state to allow adding more

def handle_manage_grades_callback(update: Update, context: CallbackContext) -> int:
    """Handles selecting a grade level in admin context (for chapters/lessons)."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.from_user.id

    if not is_admin(user_id):
        safe_edit_message_text(query, text="غير مصرح لك.")
        return ConversationHandler.END

    admin_context = context.user_data.get('admin_context')

    if data == 'admin_manage_structure': # Back button
        safe_edit_message_text(query, text="العودة لقائمة إدارة الهيكل.", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE

    try:
        grade_id = int(data.split('_')[-1])
        context.user_data['selected_admin_grade_id'] = grade_id
        grade_name = QUIZ_DB.get_grade_level_name(grade_id)
        logger.info(f"Admin {user_id} selected grade {grade_id} ({grade_name}) for context '{admin_context}'.")

        if admin_context == 'manage_chapters':
            keyboard = create_chapters_keyboard(grade_id, for_quiz=False, context=context)
            safe_edit_message_text(query,
                text=f"إدارة فصول المرحلة '{grade_name}'. اختر فصلاً للتعديل أو أضف فصلاً جديداً.",
                reply_markup=keyboard
            )
            query.message.reply_text("لإضافة فصل جديد لهذه المرحلة، أرسل اسمه.")
            return ADMIN_MANAGE_CHAPTERS
        elif admin_context == 'manage_lessons':
            # Need to select chapter first
            keyboard = create_chapters_keyboard(grade_id, for_quiz=False, context=context)
            safe_edit_message_text(query,
                text=f"إدارة دروس المرحلة '{grade_name}'. اختر الفصل أولاً:",
                reply_markup=keyboard
            )
            return ADMIN_MANAGE_CHAPTERS # Go to chapter selection, context remains 'manage_lessons'
        elif admin_context == 'manage_grades':
             # TODO: Implement editing/deleting selected grade
             safe_edit_message_text(query, text=f"تم اختيار المرحلة '{grade_name}'. (ميزة التعديل/الحذف قيد التطوير)")
             return ADMIN_MANAGE_GRADES
        else:
             logger.warning(f"Unknown admin context '{admin_context}' in handle_manage_grades_callback")
             safe_edit_message_text(query, text="خطأ في السياق.", reply_markup=create_structure_admin_menu_keyboard())
             return ADMIN_MANAGE_STRUCTURE

    except (ValueError, IndexError):
        logger.error(f"Invalid callback data for admin grade selection: {data}")
        safe_edit_message_text(query, text="خطأ في اختيار المرحلة.", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE

def handle_manage_chapters(update: Update, context: CallbackContext) -> int:
    """Handles adding chapters (Receives text input)."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text("غير مصرح لك.")
        return ConversationHandler.END

    admin_context = context.user_data.get('admin_context')
    grade_id = context.user_data.get('selected_admin_grade_id')

    if admin_context not in ['manage_chapters', 'manage_lessons'] or not grade_id:
         logger.warning(f"Admin {user_id} sent text '{update.message.text}' in chapter context without proper setup.")
         return ADMIN_MANAGE_CHAPTERS # Stay in state or return?

    chapter_name = update.message.text.strip()
    if not chapter_name:
        update.message.reply_text("اسم الفصل لا يمكن أن يكون فارغاً.")
        return ADMIN_MANAGE_CHAPTERS

    try:
        chapter_id = QUIZ_DB.add_chapter(grade_id, chapter_name)
        if chapter_id:
            logger.info(f"Admin {user_id} added new chapter '{chapter_name}' to grade {grade_id} (ID: {chapter_id})")
            update.message.reply_text(f"تمت إضافة الفصل '{chapter_name}' بنجاح.")
            # Refresh keyboard
            keyboard = create_chapters_keyboard(grade_id, for_quiz=False, context=context)
            grade_name = QUIZ_DB.get_grade_level_name(grade_id)
            update.message.reply_text(f"إدارة فصول المرحلة '{grade_name}':", reply_markup=keyboard)
        else:
            update.message.reply_text("فشل إضافة الفصل (قد يكون موجوداً بالفعل؟).")
    except Exception as e:
        logger.error(f"Error adding chapter '{chapter_name}': {e}")
        update.message.reply_text(f"حدث خطأ: {e}")

    return ADMIN_MANAGE_CHAPTERS # Stay in state

def handle_manage_chapters_callback(update: Update, context: CallbackContext) -> int:
    """Handles selecting a chapter in admin context (for lessons)."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.from_user.id

    if not is_admin(user_id):
        safe_edit_message_text(query, text="غير مصرح لك.")
        return ConversationHandler.END

    admin_context = context.user_data.get('admin_context')
    grade_id = context.user_data.get('selected_admin_grade_id')

    # Handle back button
    if data == 'admin_manage_structure':
        # Go back to grade selection for the current context
        keyboard = create_grade_levels_keyboard(for_quiz=False, context=context)
        context_text = "الفصول" if admin_context == 'manage_chapters' else "الدروس"
        safe_edit_message_text(query,
            text=f"إدارة {context_text}. اختر المرحلة الدراسية أولاً:",
            reply_markup=keyboard
        )
        return ADMIN_MANAGE_GRADES

    try:
        chapter_id = int(data.split('_')[-1])
        context.user_data['selected_admin_chapter_id'] = chapter_id
        chapter_name = QUIZ_DB.get_chapter_name(chapter_id)
        logger.info(f"Admin {user_id} selected chapter {chapter_id} ({chapter_name}) for context '{admin_context}'.")

        if admin_context == 'manage_lessons':
            keyboard = create_lessons_keyboard(chapter_id, for_quiz=False, context=context)
            safe_edit_message_text(query,
                text=f"إدارة دروس الفصل '{chapter_name}'. اختر درساً للتعديل أو أضف درساً جديداً.",
                reply_markup=keyboard
            )
            query.message.reply_text("لإضافة درس جديد لهذا الفصل، أرسل اسمه.")
            return ADMIN_MANAGE_LESSONS
        elif admin_context == 'manage_chapters':
            # TODO: Implement editing/deleting selected chapter
            safe_edit_message_text(query, text=f"تم اختيار الفصل '{chapter_name}'. (ميزة التعديل/الحذف قيد التطوير)")
            return ADMIN_MANAGE_CHAPTERS
        else:
             logger.warning(f"Unknown admin context '{admin_context}' in handle_manage_chapters_callback")
             safe_edit_message_text(query, text="خطأ في السياق.", reply_markup=create_structure_admin_menu_keyboard())
             return ADMIN_MANAGE_STRUCTURE

    except (ValueError, IndexError):
        logger.error(f"Invalid callback data for admin chapter selection: {data}")
        safe_edit_message_text(query, text="خطأ في اختيار الفصل.", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE

def handle_manage_lessons(update: Update, context: CallbackContext) -> int:
    """Handles adding lessons (Receives text input)."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text("غير مصرح لك.")
        return ConversationHandler.END

    admin_context = context.user_data.get('admin_context')
    chapter_id = context.user_data.get('selected_admin_chapter_id')

    if admin_context != 'manage_lessons' or not chapter_id:
         logger.warning(f"Admin {user_id} sent text '{update.message.text}' in lesson context without proper setup.")
         return ADMIN_MANAGE_LESSONS

    lesson_name = update.message.text.strip()
    if not lesson_name:
        update.message.reply_text("اسم الدرس لا يمكن أن يكون فارغاً.")
        return ADMIN_MANAGE_LESSONS

    try:
        lesson_id = QUIZ_DB.add_lesson(chapter_id, lesson_name)
        if lesson_id:
            logger.info(f"Admin {user_id} added new lesson '{lesson_name}' to chapter {chapter_id} (ID: {lesson_id})")
            update.message.reply_text(f"تمت إضافة الدرس '{lesson_name}' بنجاح.")
            # Refresh keyboard
            keyboard = create_lessons_keyboard(chapter_id, for_quiz=False, context=context)
            chapter_name = QUIZ_DB.get_chapter_name(chapter_id)
            update.message.reply_text(f"إدارة دروس الفصل '{chapter_name}':", reply_markup=keyboard)
        else:
            update.message.reply_text("فشل إضافة الدرس (قد يكون موجوداً بالفعل؟).")
    except Exception as e:
        logger.error(f"Error adding lesson '{lesson_name}': {e}")
        update.message.reply_text(f"حدث خطأ: {e}")

    return ADMIN_MANAGE_LESSONS # Stay in state

def handle_manage_lessons_callback(update: Update, context: CallbackContext) -> int:
    """Handles selecting a lesson in admin context."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.from_user.id

    if not is_admin(user_id):
        safe_edit_message_text(query, text="غير مصرح لك.")
        return ConversationHandler.END

    admin_context = context.user_data.get('admin_context')
    chapter_id = context.user_data.get('selected_admin_chapter_id')

    # Handle back button
    if data == 'admin_manage_structure':
        # Go back to chapter selection for the current context
        grade_id = context.user_data.get('selected_admin_grade_id')
        if grade_id:
            keyboard = create_chapters_keyboard(grade_id, for_quiz=False, context=context)
            safe_edit_message_text(query,
                text=f"إدارة دروس المرحلة '{QUIZ_DB.get_grade_level_name(grade_id)}'. اختر الفصل أولاً:",
                reply_markup=keyboard
            )
            return ADMIN_MANAGE_CHAPTERS
        else:
            # Fallback
            safe_edit_message_text(query, text="العودة لقائمة إدارة الهيكل.", reply_markup=create_structure_admin_menu_keyboard())
            return ADMIN_MANAGE_STRUCTURE

    try:
        lesson_id = int(data.split('_')[-1])
        lesson_name = QUIZ_DB.get_lesson_name(lesson_id)
        logger.info(f"Admin {user_id} selected lesson {lesson_id} ({lesson_name}) for context '{admin_context}'.")

        if admin_context == 'manage_lessons':
            # TODO: Implement editing/deleting selected lesson
            safe_edit_message_text(query, text=f"تم اختيار الدرس '{lesson_name}'. (ميزة التعديل/الحذف قيد التطوير)")
            return ADMIN_MANAGE_LESSONS
        else:
             logger.warning(f"Unknown admin context '{admin_context}' in handle_manage_lessons_callback")
             safe_edit_message_text(query, text="خطأ في السياق.", reply_markup=create_structure_admin_menu_keyboard())
             return ADMIN_MANAGE_STRUCTURE

    except (ValueError, IndexError):
        logger.error(f"Invalid callback data for admin lesson selection: {data}")
        safe_edit_message_text(query, text="خطأ في اختيار الدرس.", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE

# --- Error Handler ---

def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # Try to notify the user about the error, if possible
    if isinstance(update, Update) and update.effective_chat:
        try:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="حدث خطأ غير متوقع أثناء معالجة طلبك. تم إبلاغ المطورين."
            )
        except Exception as e:
            logger.error(f"Failed to send error message to user: {e}")

# --- Main Function ---

def main() -> None:
    """Start the bot."""
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN environment variable not set.")
        sys.exit("BOT_TOKEN not set.")
    if not DATABASE_URL:
        logger.critical("DATABASE_URL environment variable not set.")
        sys.exit("DATABASE_URL not set.")

    # Create the Updater and pass it your bot's token.
    updater = Updater(BOT_TOKEN, use_context=True)

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher

    # --- Conversation Handler Setup ---
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CallbackQueryHandler(main_menu_callback, pattern='^main_menu$') # Allow returning via callback
            # Add other entry points if needed (e.g., deep linking)
        ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(main_menu_callback, pattern='^menu_'),
                CommandHandler('help', help_command) # Allow help in main menu
            ],
            QUIZ_MENU: [
                CallbackQueryHandler(quiz_menu_callback, pattern='^quiz_'),
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$') # Back to main
            ],
            SELECTING_QUIZ_DURATION: [
                CallbackQueryHandler(select_quiz_duration_callback, pattern='^duration_'),
                CallbackQueryHandler(quiz_menu_callback, pattern='^menu_quiz$') # Back to quiz menu
            ],
            SELECT_GRADE_LEVEL_FOR_QUIZ: [
                 CallbackQueryHandler(select_grade_level_quiz_callback, pattern='^grade_quiz_'),
                 CallbackQueryHandler(quiz_menu_callback, pattern='^menu_quiz$') # Back to quiz menu
            ],
            SELECT_CHAPTER_FOR_QUIZ: [
                 CallbackQueryHandler(select_chapter_quiz_callback, pattern='^chapter_quiz_'),
                 CallbackQueryHandler(select_grade_level_quiz_callback, pattern='^quiz_by_chapter_prompt$') # Back to grade selection
            ],
             SELECT_CHAPTER_FOR_LESSON: [ # State for selecting chapter before lesson
                 CallbackQueryHandler(select_chapter_for_lesson_quiz_callback, pattern='^lesson_chapter_'),
                 CallbackQueryHandler(select_grade_level_quiz_callback, pattern='^quiz_by_lesson_prompt$') # Back to grade selection
             ],
            SELECT_LESSON_FOR_QUIZ: [
                 CallbackQueryHandler(select_lesson_quiz_callback, pattern='^lesson_quiz_'),
                 CallbackQueryHandler(select_chapter_for_lesson_quiz_callback, pattern='^quiz_by_lesson_prompt$') # Back to chapter selection
            ],
            RUNNING_QUIZ: [
                CallbackQueryHandler(handle_answer, pattern='^(answer_|skip_)')
                # No direct exit from here except timer or end of questions
            ],
            VIEWING_RESULTS: [
                # CallbackQueryHandler(review_errors_callback, pattern='^review_'), # Future
                CallbackQueryHandler(quiz_menu_callback, pattern='^menu_quiz$'), # Re-take quiz
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$') # Back to main
            ],
            ADMIN_MENU: [
                CallbackQueryHandler(admin_menu_callback, pattern='^admin_'),
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$')
            ],
            ADDING_QUESTION: [
                MessageHandler(Filters.text & ~Filters.command, handle_add_question_text)
            ],
            ADDING_OPTIONS: [
                MessageHandler(Filters.text & ~Filters.command, handle_add_question_options)
            ],
            ADDING_CORRECT_OPTION: [
                MessageHandler(Filters.text & ~Filters.command, handle_add_question_correct_option)
            ],
            ADDING_IMAGE: [
                 CallbackQueryHandler(handle_add_question_image_decision, pattern='^add_image_'),
                 MessageHandler(Filters.photo, handle_add_question_image_upload)
                 # Allow text message here? Maybe to cancel?
            ],
             ADDING_GRADE_LEVEL: [
                 CallbackQueryHandler(handle_add_question_grade, pattern='^grade_admin_'),
                 CallbackQueryHandler(admin_menu_callback, pattern='^admin_manage_structure$') # Back button
             ],
             ADDING_CHAPTER: [
                 CallbackQueryHandler(handle_add_question_chapter, pattern='^admin_chapter_'),
                 CallbackQueryHandler(handle_add_question_grade, pattern='^admin_manage_structure$') # Back button
             ],
             ADDING_LESSON: [
                 CallbackQueryHandler(handle_add_question_lesson, pattern='^admin_lesson_'),
                 CallbackQueryHandler(handle_add_question_chapter, pattern='^admin_manage_structure$') # Back button
             ],
            DELETING_QUESTION: [
                MessageHandler(Filters.text & ~Filters.command, handle_delete_question)
            ],
            SHOWING_QUESTION: [
                MessageHandler(Filters.text & ~Filters.command, handle_show_question)
            ],
            ADMIN_MANAGE_STRUCTURE: [
                 CallbackQueryHandler(admin_structure_menu_callback, pattern='^admin_manage_'),
                 CallbackQueryHandler(admin_menu_callback, pattern='^menu_admin$') # Back button
            ],
            ADMIN_MANAGE_GRADES: [
                 MessageHandler(Filters.text & ~Filters.command, handle_manage_grades), # Add grade via text
                 CallbackQueryHandler(handle_manage_grades_callback, pattern='^grade_admin_'), # Select grade for next step
                 CallbackQueryHandler(admin_structure_menu_callback, pattern='^admin_manage_structure$') # Back button
            ],
            ADMIN_MANAGE_CHAPTERS: [
                 MessageHandler(Filters.text & ~Filters.command, handle_manage_chapters), # Add chapter via text
                 CallbackQueryHandler(handle_manage_chapters_callback, pattern='^admin_chapter_'), # Select chapter for next step
                 CallbackQueryHandler(handle_manage_grades_callback, pattern='^admin_manage_structure$') # Back button
            ],
            ADMIN_MANAGE_LESSONS: [
                 MessageHandler(Filters.text & ~Filters.command, handle_manage_lessons), # Add lesson via text
                 CallbackQueryHandler(handle_manage_lessons_callback, pattern='^admin_lesson_'), # Select lesson (for edit/delete - TODO)
                 CallbackQueryHandler(handle_manage_chapters_callback, pattern='^admin_manage_structure$') # Back button
            ],
            # INFO_MENU state and handlers will be added in the next step
        },
        fallbacks=[
            CommandHandler('start', start), # Allow restarting
            CommandHandler('cancel', cancel),
            CommandHandler('help', help_command),
            # Add a fallback for unexpected callbacks in certain states?
            # CallbackQueryHandler(main_menu_callback, pattern='^main_menu$') # General fallback to main?
        ],
        # Optional: Add persistence here if needed
    )

    dispatcher.add_handler(conv_handler)

    # log all errors
    dispatcher.add_error_handler(error_handler)

    # Start the Bot (using webhook for Heroku)
    if HEROKU_APP_NAME:
        logger.info(f"Starting webhook for Heroku app {HEROKU_APP_NAME} on port {PORT}")
        updater.start_webhook(listen="0.0.0.0",
                              port=PORT,
                              url_path=BOT_TOKEN,
                              webhook_url=f"https://{HEROKU_APP_NAME}.herokuapp.com/{BOT_TOKEN}")
        updater.idle()
    else:
        logger.info("Starting bot with polling (not for Heroku deployment).")
        updater.start_polling()
        updater.idle()

    # Close db connection on exit
    if DB_CONN:
        DB_CONN.close()
        logger.info("Database connection closed.")

if __name__ == '__main__':
    main()

