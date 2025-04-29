#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import random
import os
import time
import sys
import base64
import re
from io import BytesIO
from datetime import datetime, timedelta

# تكوين التسجيل (تم نقله للأعلى)
log_file_path = os.path.join(os.path.dirname(__file__), 'bot_log.txt')
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout) # تسجيل في المخرجات القياسية (Heroku logs)
    ]
)
logger = logging.getLogger(__name__)

# --- استيراد مكتبات تيليجرام (متوافق مع الإصدار 12.8) ---
try:
    # في الإصدار 12.x، يتم استيراد ParseMode مباشرة من telegram
    from telegram import (
        Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ParseMode
    )
    from telegram.error import NetworkError, Unauthorized, BadRequest, TimedOut, ChatMigrated, TelegramError
    from telegram.ext import (
        Updater, CommandHandler, MessageHandler, Filters, CallbackContext,
        CallbackQueryHandler, ConversationHandler, JobQueue
    )
    logger.info("Successfully imported telegram modules for v12.8")
except ImportError as e:
    logger.critical(f"Failed to import core telegram modules (v12.8): {e}")
    # قد تحتاج لإيقاف البوت هنا إذا لم يتم استيراد الوحدات الأساسية
    sys.exit("Critical import error, stopping bot.")

# استيراد الدالة المساعدة لمعالجة الأخطاء بأمان
from helper_function import safe_edit_message_text

# استيراد البيانات الثابتة ووظائف المعادلات
# Ensure these files exist in the same directory or adjust the import path
try:
    from chemistry_data import ELEMENTS, COMPOUNDS, CONCEPTS, PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO
    from chemical_equations import process_text_with_chemical_notation, format_chemical_equation
    # استيراد الفئة المحسنة لقاعدة البيانات
    from quiz_db import QuizDatabase
except ImportError as e:
    logger.critical(f"Failed to import local modules (chemistry_data, chemical_equations, quiz_db): {e}")
    sys.exit("Local module import error, stopping bot.")

# --- إعدادات --- 
# ضع معرف المستخدم الرقمي الخاص بك هنا لتقييد الوصول إلى إدارة قاعدة البيانات
ADMIN_USER_ID = 6448526509 # !!! استبدل هذا بمعرف المستخدم الرقمي الخاص بك !!!
# توكن البوت
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") # !!! اقرأ التوكن من متغيرات البيئة !!!
if not TOKEN:
    logger.critical("TELEGRAM_BOT_TOKEN environment variable not set!")
    sys.exit("Bot token not found.")

# إعدادات الاختبارات
DEFAULT_QUIZ_QUESTIONS = 10
DEFAULT_QUIZ_DURATION_MINUTES = 10 # مدة الاختبار الافتراضية بالدقائق
QUESTION_TIMER_SECONDS = 240  # 4 دقائق لكل سؤال

# تهيئة قاعدة بيانات الأسئلة (باستخدام PostgreSQL المحسنة)
try:
    QUIZ_DB = QuizDatabase()
    logger.info("Enhanced QuizDatabase initialized successfully.")
except Exception as e:
    logger.error(f"Error initializing QuizDatabase: {e}")
    QUIZ_DB = None
    # قد ترغب في إيقاف البوت إذا لم تعمل قاعدة البيانات
    # sys.exit("Database initialization failed.")

# حالات المحادثة
(
    MAIN_MENU, QUIZ_MENU, ADMIN_MENU, ADDING_QUESTION, ADDING_OPTIONS,
    ADDING_CORRECT_ANSWER, ADDING_EXPLANATION, DELETING_QUESTION,
    SHOWING_QUESTION, SELECTING_QUIZ_TYPE, SELECTING_CHAPTER,
    SELECTING_LESSON, SELECTING_QUIZ_DURATION, TAKING_QUIZ,
    SELECT_CHAPTER_FOR_LESSON, SELECT_LESSON_FOR_QUIZ, SELECT_CHAPTER_FOR_QUIZ,
    SELECT_GRADE_LEVEL, SELECT_GRADE_LEVEL_FOR_QUIZ, ADMIN_GRADE_MENU,
    ADMIN_CHAPTER_MENU, ADMIN_LESSON_MENU, ADDING_GRADE_LEVEL,
    ADDING_CHAPTER, ADDING_LESSON, SELECTING_GRADE_FOR_CHAPTER,
    SELECTING_CHAPTER_FOR_LESSON_ADMIN, ADMIN_MANAGE_STRUCTURE, # Added state
    ADMIN_MANAGE_GRADES, ADMIN_MANAGE_CHAPTERS, ADMIN_MANAGE_LESSONS # Added states
) = range(31) # Corrected range to match 31 states

# --- وظائف مساعدة ---

def is_admin(user_id):
    """التحقق مما إذا كان المستخدم مسؤولاً."""
    # تأكد من مقارنة الأرقام أو السلاسل النصية بشكل متسق
    return str(user_id) == str(ADMIN_USER_ID)

def create_main_menu_keyboard(user_id):
    """إنشاء لوحة مفاتيح القائمة الرئيسية."""
    keyboard = [
        [InlineKeyboardButton("📚 المعلومات الكيميائية", callback_data='menu_info')],
        [InlineKeyboardButton("📝 الاختبارات", callback_data='menu_quiz')],
        [InlineKeyboardButton("📊 تقارير الأداء", callback_data='menu_reports')],
        [InlineKeyboardButton("ℹ️ حول البوت", callback_data='menu_about')]
    ]

    # إضافة قسم الإدارة للمسؤولين فقط
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ إدارة البوت", callback_data='menu_admin')]) # تغيير النص ليكون أوضح

    return InlineKeyboardMarkup(keyboard)

def create_quiz_menu_keyboard():
    """إنشاء لوحة مفاتيح قائمة الاختبارات."""
    keyboard = [
        [InlineKeyboardButton("🎯 اختبار عشوائي", callback_data='quiz_random_prompt')],
        [InlineKeyboardButton("📄 اختبار حسب الفصل", callback_data='quiz_by_chapter_prompt')],
        [InlineKeyboardButton("📝 اختبار حسب الدرس", callback_data='quiz_by_lesson_prompt')],
        [InlineKeyboardButton("🎓 اختبار حسب المرحلة الدراسية", callback_data='quiz_by_grade_prompt')],
        [InlineKeyboardButton("🔄 مراجعة الأخطاء", callback_data='quiz_review_prompt')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_admin_menu_keyboard():
    """إنشاء لوحة مفاتيح قائمة الإدارة."""
    keyboard = [
        [InlineKeyboardButton("➕ إضافة سؤال", callback_data='admin_add_question')],
        [InlineKeyboardButton("🗑️ حذف سؤال", callback_data='admin_delete_question')],
        [InlineKeyboardButton("🔍 عرض سؤال", callback_data='admin_show_question')],
        [InlineKeyboardButton("🏫 إدارة المراحل/الفصول/الدروس", callback_data='admin_manage_structure')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_structure_admin_menu_keyboard():
    """إنشاء لوحة مفاتيح قائمة إدارة المراحل والفصول والدروس."""
    keyboard = [
        [InlineKeyboardButton("🏫 إدارة المراحل الدراسية", callback_data='admin_manage_grades')],
        [InlineKeyboardButton("📚 إدارة الفصول", callback_data='admin_manage_chapters')],
        [InlineKeyboardButton("📝 إدارة الدروس", callback_data='admin_manage_lessons')],
        [InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data='menu_admin')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_grade_levels_keyboard(for_quiz=False, context: CallbackContext = None):
    """إنشاء لوحة مفاتيح لاختيار المرحلة الدراسية."""
    if not QUIZ_DB:
        logger.error("Cannot create grade levels keyboard: QuizDatabase not initialized.")
        return None
    grade_levels = QUIZ_DB.get_grade_levels()
    keyboard = []

    if not grade_levels:
        logger.warning("No grade levels found in the database.")
        # يمكنك إضافة رسالة للمستخدم هنا إذا لزم الأمر

    for grade_id, grade_name in grade_levels:
        if for_quiz:
            callback_data = f'select_grade_quiz_{grade_id}'
        else:
            # تحديد السياق للإدارة
            current_state = context.user_data.get('admin_context', 'manage_grades')
            if current_state == 'add_chapter':
                 callback_data = f'select_grade_for_chapter_{grade_id}'
            else:
                 callback_data = f'select_grade_admin_{grade_id}' # للإدارة العامة للمراحل
        keyboard.append([InlineKeyboardButton(grade_name, callback_data=callback_data)])

    # إضافة خيار الاختبار التحصيلي العام (جميع المراحل) إذا كان للاختبار
    if for_quiz:
        keyboard.append([InlineKeyboardButton("اختبار تحصيلي عام (جميع المراحل)", callback_data='select_grade_quiz_all')])

    # إضافة زر العودة
    if for_quiz:
        keyboard.append([InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data='menu_quiz')])
    else:
        # تحديد زر العودة بناءً على السياق
        current_state = context.user_data.get('admin_context', 'manage_grades')
        if current_state == 'add_chapter':
            keyboard.append([InlineKeyboardButton("🔙 إلغاء إضافة فصل", callback_data='admin_manage_chapters')])
        else:
            keyboard.append([InlineKeyboardButton("🔙 العودة لقائمة إدارة الهيكل", callback_data='admin_manage_structure')])

    return InlineKeyboardMarkup(keyboard)

def create_chapters_keyboard(grade_level_id, for_quiz=False, for_lesson=False, context: CallbackContext = None):
    """إنشاء لوحة مفاتيح لاختيار الفصل."""
    if not QUIZ_DB:
        logger.error("Cannot create chapters keyboard: QuizDatabase not initialized.")
        return None
    chapters = QUIZ_DB.get_chapters_by_grade(grade_level_id)
    keyboard = []

    if not chapters:
        logger.warning(f"No chapters found for grade_level_id: {grade_level_id}")

    for chapter_id, chapter_name in chapters:
        if for_quiz:
            callback_data = f'select_chapter_quiz_{chapter_id}'
        elif for_lesson:
             # تحديد السياق للإدارة أو الاختبار
            current_state = context.user_data.get('admin_context', 'quiz') # الافتراضي هو سياق الاختبار
            if current_state == 'add_lesson':
                callback_data = f'select_chapter_for_lesson_admin_{chapter_id}'
            else: # سياق الاختبار
                callback_data = f'select_chapter_lesson_{chapter_id}'
        else: # إدارة الفصول نفسها
            callback_data = f'select_chapter_admin_{chapter_id}'
        keyboard.append([InlineKeyboardButton(chapter_name, callback_data=callback_data)])

    # إضافة زر العودة
    if for_quiz:
        # العودة لاختيار المرحلة الدراسية في سياق الاختبار حسب الفصل
        keyboard.append([InlineKeyboardButton("🔙 العودة لاختيار المرحلة", callback_data='quiz_by_chapter_prompt')])
    elif for_lesson:
        # تحديد زر العودة بناءً على السياق
        current_state = context.user_data.get('admin_context', 'quiz')
        if current_state == 'add_lesson':
            keyboard.append([InlineKeyboardButton("🔙 إلغاء إضافة درس", callback_data='admin_manage_lessons')])
        else: # سياق الاختبار
             # العودة لاختيار المرحلة الدراسية في سياق الاختبار حسب الدرس
            keyboard.append([InlineKeyboardButton("🔙 العودة لاختيار المرحلة", callback_data='quiz_by_lesson_prompt')])
    else: # إدارة الفصول
        keyboard.append([InlineKeyboardButton("🔙 العودة لقائمة إدارة المراحل", callback_data='admin_manage_grades')])

    return InlineKeyboardMarkup(keyboard)

def create_lessons_keyboard(chapter_id, for_quiz=False, context: CallbackContext = None):
    """إنشاء لوحة مفاتيح لاختيار الدرس."""
    if not QUIZ_DB:
        logger.error("Cannot create lessons keyboard: QuizDatabase not initialized.")
        return None
    lessons = QUIZ_DB.get_lessons_by_chapter(chapter_id)
    keyboard = []

    if not lessons:
         logger.warning(f"No lessons found for chapter_id: {chapter_id}")

    for lesson_id, lesson_name in lessons:
        if for_quiz:
            callback_data = f'select_lesson_quiz_{lesson_id}'
        else: # إدارة الدروس
            callback_data = f'select_lesson_admin_{lesson_id}'
        keyboard.append([InlineKeyboardButton(lesson_name, callback_data=callback_data)])

    # إضافة زر العودة
    if for_quiz:
        # العودة لاختيار الفصل في سياق الاختبار حسب الدرس
        # نحتاج لمعرفة المرحلة الدراسية الأصلية للعودة إليها
        # هذا يتطلب تخزين المرحلة عند اختيارها في الخطوة السابقة
        # كحل مؤقت، نعود لقائمة الاختبارات
        # FIX: Go back to chapter selection instead of main quiz menu
        # We need the grade_level_id to go back properly, store it in user_data earlier
        # For now, let's try going back to the chapter prompt which asks for grade again
        keyboard.append([InlineKeyboardButton("🔙 العودة لاختيار الفصل", callback_data='quiz_by_lesson_prompt')])
    else: # إدارة الدروس
        keyboard.append([InlineKeyboardButton("🔙 العودة لقائمة إدارة الفصول", callback_data='admin_manage_chapters')])

    return InlineKeyboardMarkup(keyboard)

def create_quiz_duration_keyboard():
    """إنشاء لوحة مفاتيح لاختيار مدة الاختبار."""
    keyboard = [
        [InlineKeyboardButton("5 دقائق", callback_data='quiz_duration_5')],
        [InlineKeyboardButton("10 دقائق", callback_data='quiz_duration_10')],
        [InlineKeyboardButton("15 دقيقة", callback_data='quiz_duration_15')],
        [InlineKeyboardButton("20 دقيقة", callback_data='quiz_duration_20')],
        [InlineKeyboardButton("30 دقيقة", callback_data='quiz_duration_30')],
        [InlineKeyboardButton("بدون وقت محدد", callback_data='quiz_duration_0')],
        [InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data='menu_quiz')]
    ]
    return InlineKeyboardMarkup(keyboard)

def set_quiz_timer(context: CallbackContext, chat_id, user_id, quiz_id, duration_minutes):
    """إعداد مؤقت لإنهاء الاختبار بعد انتهاء الوقت المحدد."""
    if duration_minutes <= 0:
        return None  # لا مؤقت للاختبارات بدون وقت محدد

    job_context = {
        'chat_id': chat_id,
        'user_id': user_id,
        'quiz_id': quiz_id
    }

    try:
        # إضافة مهمة مؤقتة لإنهاء الاختبار بعد انتهاء الوقت
        job = context.job_queue.run_once(
            end_quiz_timeout,
            duration_minutes * 60,  # تحويل الدقائق إلى ثواني
            context=job_context,
            name=f"quiz_timeout_{user_id}_{quiz_id}" # اسم مميز للمهمة
        )
        logger.info(f"Quiz timer set for quiz {quiz_id}, user {user_id} for {duration_minutes} minutes.")
        return job
    except Exception as e:
        logger.error(f"Error setting quiz timer: {e}")
        return None

def set_question_timer(context: CallbackContext, chat_id, user_id, quiz_id):
    """إعداد مؤقت للانتقال التلقائي للسؤال التالي بعد 4 دقائق."""
    job_context = {
        'chat_id': chat_id,
        'user_id': user_id,
        'quiz_id': quiz_id,
        'type': 'question_timer'
    }

    try:
        # إضافة مهمة مؤقتة للانتقال للسؤال التالي بعد 4 دقائق
        job = context.job_queue.run_once(
            question_timer_callback,
            QUESTION_TIMER_SECONDS,  # 4 دقائق
            context=job_context,
            name=f"question_timer_{user_id}_{quiz_id}" # اسم مميز للمهمة
        )
        logger.info(f"Question timer set for quiz {quiz_id}, user {user_id}.")
        return job
    except Exception as e:
        logger.error(f"Error setting question timer: {e}")
        return None

def question_timer_callback(context: CallbackContext):
    """يتم استدعاؤها بواسطة المؤقت للانتقال التلقائي للسؤال التالي."""
    job_context = context.job.context
    chat_id = job_context['chat_id']
    user_id = job_context['user_id']
    quiz_id = job_context['quiz_id']

    # التحقق مما إذا كان الاختبار لا يزال نشطاً لهذا المستخدم
    # Use context.dispatcher.user_data instead of context.user_data
    user_data = context.dispatcher.user_data.get(user_id, {})
    if user_data.get('conversation_state') == 'in_quiz' and user_data.get('quiz', {}).get('id') == quiz_id:
        logger.info(f"Question timer expired for quiz {quiz_id}, user {user_id}. Moving to next question.")

        # تسجيل إجابة فارغة (غير صحيحة) للسؤال الحالي
        quiz_data = user_data['quiz']
        current_index = quiz_data['current_question_index']
        questions = quiz_data['questions']

        if current_index < len(questions):
            question = questions[current_index]
            question_id = question['id']

            # تسجيل إجابة فارغة (غير صحيحة) في قاعدة البيانات
            if QUIZ_DB:
                QUIZ_DB.record_answer(quiz_id, question_id, -1, False)
            else:
                logger.error("Cannot record answer: QuizDatabase not initialized.")

            # إرسال رسالة للمستخدم
            try:
                context.bot.send_message(
                    chat_id=chat_id,
                    text="⏱️ انتهى وقت السؤال! سيتم الانتقال للسؤال التالي تلقائياً.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                 logger.error(f"Error sending question timeout message: {e}")

            # الانتقال للسؤال التالي
            quiz_data['current_question_index'] += 1

            # عرض السؤال التالي (لا نستخدم كائن وهمي، نستدعي الوظيفة مباشرة)
            # نحتاج إلى طريقة لاستدعاء show_next_question بدون update
            # يمكن تمرير chat_id و user_id مباشرة
            show_next_question_internal(context, chat_id, user_id)

def remove_quiz_timer(context: CallbackContext):
    """إزالة مؤقت الاختبار إذا كان موجوداً."""
    # Use context.dispatcher.user_data
    user_id = context.dispatcher.user_data.get(context.job.context['user_id'], {}).get('user_id')
    quiz_id = context.dispatcher.user_data.get(context.job.context['user_id'], {}).get('quiz', {}).get('id')

    if not user_id or not quiz_id:
        logger.warning("Could not remove quiz timer: user_id or quiz_id not found in context.")
        return

    job_name = f"quiz_timeout_{user_id}_{quiz_id}"
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    if not current_jobs:
        logger.info(f"No quiz timer found with name {job_name} to remove.")
        return
    for job in current_jobs:
        job.schedule_removal()
        logger.info(f"Removed quiz timer job: {job_name}")

def remove_question_timer(context: CallbackContext):
    """إزالة مؤقت السؤال إذا كان موجوداً."""
    # Use context.dispatcher.user_data
    user_id = context.dispatcher.user_data.get(context.job.context['user_id'], {}).get('user_id')
    quiz_id = context.dispatcher.user_data.get(context.job.context['user_id'], {}).get('quiz', {}).get('id')

    if not user_id or not quiz_id:
        logger.warning("Could not remove question timer: user_id or quiz_id not found in context.")
        return

    job_name = f"question_timer_{user_id}_{quiz_id}"
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    if not current_jobs:
        # logger.info(f"No question timer found with name {job_name} to remove.") # Can be noisy
        return
    for job in current_jobs:
        job.schedule_removal()
        # logger.info(f"Removed question timer job: {job_name}") # Can be noisy

# --- معالجات الأوامر والرسائل ---

def start_command(update: Update, context: CallbackContext):
    """إرسال رسالة ترحيبية وعرض القائمة الرئيسية."""
    # FIX: Access user from update.message.from_user when using CommandHandler with use_context=True
    user = update.message.from_user
    chat_id = update.message.chat_id
    user_id = user.id
    logger.info(f"User {user_id} in chat {chat_id} started the bot.")

    # تخزين معرف المستخدم في بيانات المستخدم إذا لم يكن موجوداً
    if 'user_id' not in context.user_data:
        context.user_data['user_id'] = user_id

    welcome_message = f"أهلاً بك يا {user.first_name} في بوت الكيمياء التعليمي!\n\n"
    welcome_message += "يمكنك استخدام هذا البوت لـ:\n"
    welcome_message += "- 📚 استعراض معلومات عن العناصر والمركبات والمفاهيم الكيميائية.\n"
    welcome_message += "- 📝 إجراء اختبارات متنوعة لقياس معرفتك.\n"
    welcome_message += "- 📊 تتبع أدائك في الاختبارات السابقة.\n\n"
    welcome_message += "اختر أحد الخيارات أدناه للبدء:"

    keyboard = create_main_menu_keyboard(user_id)
    update.message.reply_text(welcome_message, reply_markup=keyboard)
    return MAIN_MENU

def main_menu_callback(update: Update, context: CallbackContext):
    """معالجة اختيارات القائمة الرئيسية."""
    query = update.callback_query
    query.answer() # مهم لإيقاف علامة التحميل على الزر
    # FIX: Access user from query.from_user in CallbackQueryHandler
    user = query.from_user
    user_id = user.id
    chat_id = query.message.chat_id
    data = query.data

    logger.info(f"User {user_id} chose {data} from main menu.")

    # تخزين معرف المستخدم في بيانات المستخدم إذا لم يكن موجوداً
    if 'user_id' not in context.user_data:
        context.user_data['user_id'] = user_id

    if data == 'menu_info':
        # TODO: Implement chemical info browsing
        safe_edit_message_text(query,
            text="قسم المعلومات الكيميائية قيد التطوير. عد قريباً!",
            reply_markup=create_main_menu_keyboard(user_id)
        )
        return MAIN_MENU
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
        logger.error(f"Invalid callback data for chapter (for lesson) selection: {data}")
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

    if data == 'quiz_by_lesson_prompt':
        # Go back to chapter selection for lesson quiz
        grade_id = context.user_data.get('selected_grade_id')
        if grade_id:
            keyboard = create_chapters_keyboard(grade_id, for_lesson=True, context=context)
            if keyboard:
                query.edit_message_text(
                    text="اختر الفصل مجدداً:",
                    reply_markup=keyboard
                )
                return SELECT_CHAPTER_FOR_LESSON
        # Fallback
        query.edit_message_text("العودة لاختيار المرحلة.", reply_markup=create_grade_levels_keyboard(for_quiz=True, context=context))
        return SELECT_GRADE_LEVEL_FOR_QUIZ

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

def select_quiz_duration_callback(update: Update, context: CallbackContext):
    """Handles selecting the quiz duration and starts the quiz."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    if data == 'menu_quiz':
        query.edit_message_text("العودة لقائمة الاختبارات.", reply_markup=create_quiz_menu_keyboard())
        return QUIZ_MENU

    try:
        duration_minutes = int(data.split('_')[-1])
        context.user_data['quiz_duration'] = duration_minutes
        logger.info(f"User {user_id} selected duration {duration_minutes} minutes.")

        # --- Start the quiz based on selected type --- 
        quiz_type = context.user_data.get('quiz_type')
        grade_id = context.user_data.get('selected_grade_id')
        chapter_id = context.user_data.get('selected_chapter_id')
        lesson_id = context.user_data.get('selected_lesson_id')

        questions = []
        if not QUIZ_DB:
            query.edit_message_text("خطأ حرج: قاعدة البيانات غير متاحة لبدء الاختبار.")
            return ConversationHandler.END # Or back to main menu?

        if quiz_type == 'random':
            questions = QUIZ_DB.get_questions_by_grade(None, DEFAULT_QUIZ_QUESTIONS) # Use get_questions_by_grade with None for random
        elif quiz_type == 'grade':
            if grade_id == 'all':
                 questions = QUIZ_DB.get_questions_by_grade(None, DEFAULT_QUIZ_QUESTIONS) # None for all grades
            else:
                 questions = QUIZ_DB.get_questions_by_grade(grade_id, DEFAULT_QUIZ_QUESTIONS)
        elif quiz_type == 'chapter':
            if chapter_id:
                questions = QUIZ_DB.get_questions_by_chapter(chapter_id, DEFAULT_QUIZ_QUESTIONS)
            else:
                 logger.error(f"Cannot start chapter quiz for user {user_id}: chapter_id missing.")
                 query.edit_message_text("خطأ: لم يتم تحديد الفصل. حاول مرة أخرى.", reply_markup=create_quiz_menu_keyboard())
                 return QUIZ_MENU
        elif quiz_type == 'lesson':
            if lesson_id:
                questions = QUIZ_DB.get_questions_by_lesson(lesson_id, DEFAULT_QUIZ_QUESTIONS)
            else:
                 logger.error(f"Cannot start lesson quiz for user {user_id}: lesson_id missing.")
                 query.edit_message_text("خطأ: لم يتم تحديد الدرس. حاول مرة أخرى.", reply_markup=create_quiz_menu_keyboard())
                 return QUIZ_MENU
        # Add review quiz type later
        # elif quiz_type == 'review':
        #     questions = QUIZ_DB.get_incorrectly_answered_questions(user_id, DEFAULT_QUIZ_QUESTIONS)

        if not questions:
            query.edit_message_text("عذراً، لم يتم العثور على أسئلة لهذا الاختيار. حاول اختيار نوع آخر.", reply_markup=create_quiz_menu_keyboard())
            return QUIZ_MENU

        # Shuffle questions
        random.shuffle(questions)

        # Start quiz history
        quiz_id = QUIZ_DB.start_quiz(user_id, quiz_type, grade_id, chapter_id, lesson_id, duration_minutes)
        if not quiz_id:
             query.edit_message_text("حدث خطأ أثناء بدء الاختبار في قاعدة البيانات. حاول مرة أخرى.")
             return QUIZ_MENU

        # Store quiz data in context
        context.user_data['quiz'] = {
            'id': quiz_id,
            'questions': questions,
            'current_question_index': 0,
            'score': 0,
            'start_time': datetime.now(),
            'duration_minutes': duration_minutes
        }
        context.user_data['conversation_state'] = 'in_quiz' # Mark user as in quiz

        # Set quiz timer if duration is specified
        quiz_timer_job = set_quiz_timer(context, chat_id, user_id, quiz_id, duration_minutes)
        context.user_data['quiz_timer_job'] = quiz_timer_job

        # Show the first question
        query.edit_message_text(f"🚀 تم بدء الاختبار! مدة الاختبار: {duration_minutes if duration_minutes > 0 else 'غير محددة'} دقائق. السؤال الأول:")
        show_next_question(update, context)
        return TAKING_QUIZ

    except (ValueError, IndexError):
        logger.error(f"Invalid callback data for duration selection: {data}")
        query.edit_message_text("حدث خطأ أثناء اختيار المدة. حاول مرة أخرى.", reply_markup=create_quiz_duration_keyboard())
        return SELECTING_QUIZ_DURATION

# --- Taking Quiz Callbacks & Functions ---

def show_next_question(update: Update, context: CallbackContext):
    """Displays the next question in the quiz."""
    query = update.callback_query # Might be None if called internally
    if query:
        chat_id = query.message.chat_id
        user_id = query.from_user.id
    else: # Called internally (e.g., after timer)
        # We need chat_id and user_id passed somehow, maybe via context.job.context?
        # Or retrieve from context.user_data if reliable
        user_id = context.user_data.get('user_id')
        # How to get chat_id reliably without update?
        # This internal call path needs rethinking or removal.
        # For now, assume it's always called from a callback for simplicity.
        # Let's call the internal version directly from timers.
        logger.error("show_next_question called without CallbackQuery, this path is deprecated.")
        # Try to get chat_id from user_data if stored previously (less reliable)
        chat_id = context.user_data.get('chat_id')
        if not chat_id or not user_id:
             logger.error("Cannot show next question internally: chat_id or user_id missing.")
             return TAKING_QUIZ # Stay in state, but log error

    show_next_question_internal(context, chat_id, user_id)
    return TAKING_QUIZ # Stay in the quiz state

def show_next_question_internal(context: CallbackContext, chat_id: int, user_id: int):
    """Internal logic to display the next question."""
    quiz_data = context.user_data.get('quiz')
    if not quiz_data:
        logger.warning(f"User {user_id} - show_next_question_internal: No active quiz data found.")
        try:
            context.bot.send_message(chat_id, "لا يوجد اختبار نشط حالياً.", reply_markup=create_main_menu_keyboard(user_id))
        except Exception as e:
            logger.error(f"Error sending 'no active quiz' message: {e}")
        context.user_data.pop('conversation_state', None)
        return MAIN_MENU # Go back to main menu

    current_index = quiz_data['current_question_index']
    questions = quiz_data['questions']

    # Remove any existing question timer
    remove_question_timer(context)

    if current_index >= len(questions):
        # Quiz finished
        end_quiz(context, chat_id, user_id)
        return ConversationHandler.END # End the conversation

    question = questions[current_index]
    question_text = question['question_text']
    options = question['options'] # Already a list
    image_data_base64 = question.get('image_data') # May be None

    # Shuffle options for display
    display_options = list(enumerate(options))
    random.shuffle(display_options)
    quiz_data['current_options_map'] = {i: original_index for i, (original_index, _) in enumerate(display_options)}

    keyboard_buttons = []
    for i, (_, option_text) in enumerate(display_options):
        # Use index i (0, 1, 2, 3) for callback data
        keyboard_buttons.append([InlineKeyboardButton(option_text, callback_data=f'ans_{i}')])

    reply_markup = InlineKeyboardMarkup(keyboard_buttons)

    # Format question number (Fixed string literal)
    q_num_text = f"*السؤال {current_index + 1} من {len(questions)}:*" + "\n\n"    # Send question (with image if available)
    try:
        if image_data_base64:
            image_data = base64.b64decode(image_data_base64)
            image_stream = BytesIO(image_data)
            image_stream.name = 'question_image.png' # Name is needed for sending
            context.bot.send_photo(
                chat_id=chat_id,
                photo=image_stream,
                caption=q_num_text + process_text_with_chemical_notation(question_text),
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            context.bot.send_message(
                chat_id=chat_id,
                text=q_num_text + process_text_with_chemical_notation(question_text),
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        # Set timer for this question
        question_timer_job = set_question_timer(context, chat_id, user_id, quiz_data['id'])
        context.user_data['question_timer_job'] = question_timer_job

    except BadRequest as e:
         logger.error(f"Error sending question {question['id']} (BadRequest): {e}")
         # Try sending without Markdown
         try:
             if image_data_base64:
                 image_stream.seek(0) # Reset stream position
                 context.bot.send_photo(
                     chat_id=chat_id,
                     photo=image_stream,
                     caption=q_num_text + question_text, # No Markdown processing
                     reply_markup=reply_markup
                 )
             else:
                 context.bot.send_message(
                     chat_id=chat_id,
                     text=q_num_text + question_text, # No Markdown processing
                     reply_markup=reply_markup
                 )
             question_timer_job = set_question_timer(context, chat_id, user_id, quiz_data['id'])
             context.user_data['question_timer_job'] = question_timer_job
         except Exception as inner_e:
             logger.error(f"Failed to send question {question['id']} even without Markdown: {inner_e}")
             context.bot.send_message(chat_id, "حدث خطأ أثناء عرض السؤال. سيتم تخطي هذا السؤال.")
             # Move to next question immediately
             quiz_data['current_question_index'] += 1
             # Use job queue to call next question to avoid recursion/stack issues
             context.job_queue.run_once(lambda ctx: show_next_question_internal(ctx, chat_id, user_id), 0, context=context.user_data)

    except Exception as e:
        logger.error(f"Error sending question {question['id']}: {e}")
        context.bot.send_message(chat_id, "حدث خطأ أثناء عرض السؤال. سيتم تخطي هذا السؤال.")
        # Move to next question immediately
        quiz_data['current_question_index'] += 1
        # Use job queue to call next question
        context.job_queue.run_once(lambda ctx: show_next_question_internal(ctx, chat_id, user_id), 0, context=context.user_data)

def handle_answer(update: Update, context: CallbackContext):
    """Handles the user's answer selection during a quiz."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    quiz_data = context.user_data.get('quiz')
    if not quiz_data or context.user_data.get('conversation_state') != 'in_quiz':
        logger.warning(f"User {user_id} answered, but no active quiz found or not in quiz state.")
        query.edit_message_text("لم يتم العثور على اختبار نشط. ابدأ اختباراً جديداً من القائمة.", reply_markup=create_main_menu_keyboard(user_id))
        context.user_data.pop('conversation_state', None)
        return MAIN_MENU

    try:
        selected_display_index = int(data.split('_')[-1])
        # Map display index back to original option index
        original_option_index = quiz_data['current_options_map'].get(selected_display_index)

        if original_option_index is None:
            logger.error(f"Invalid answer index mapping for user {user_id}, data {data}")
            context.bot.send_message(chat_id, "حدث خطأ في معالجة إجابتك. حاول مرة أخرى.")
            return TAKING_QUIZ # Stay in state

        current_q_index = quiz_data['current_question_index']
        question = quiz_data['questions'][current_q_index]
        correct_option_index = question['correct_option']
        is_correct = (original_option_index == correct_option_index)

        # Remove question timer as answer was received
        remove_question_timer(context)

        # Record answer in DB
        if QUIZ_DB:
            QUIZ_DB.record_answer(quiz_data['id'], question['id'], original_option_index, is_correct)
        else:
            logger.error("Cannot record answer: QuizDatabase not initialized.")

        feedback_text = ""
        if is_correct:
            quiz_data['score'] += 1
            feedback_text = "✅ إجابة صحيحة!" + ("\n*الشرح:* " + process_text_with_chemical_notation(question['explanation']) if question.get('explanation') else "")
        else:
            correct_option_text = question['options'][correct_option_index]
            feedback_text = f"❌ إجابة خاطئة. الإجابة الصحيحة هي: *{correct_option_text}*" + ("\n*الشرح:* " + process_text_with_chemical_notation(question['explanation']) if question.get('explanation') else "")

        # Edit the original question message to show feedback and remove buttons
        try:
            # Reconstruct original message text/caption
            # Format question number (Fixed string literal)
            q_num_text = f"*السؤال {current_q_index + 1} من {len(quiz_data['questions'])}:*" + "\n\n"

            original_caption = q_num_text + process_text_with_chemical_notation(question['question_text'])
            final_text = original_caption + "\n\n" + feedback_text

            # Removed duplicate lines below

            if query.message.photo:
                query.edit_message_caption(
                    caption=final_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=None # Remove buttons
                )
            else:
                query.edit_message_text(
                    text=final_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=None # Remove buttons
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # This is expected if the user clicks the button twice quickly
                logger.info(f"Message not modified (likely duplicate button press): {e}")
            else:
                # Assume other BadRequest errors are due to Markdown or other issues
                logger.warning(f"Failed to edit message with feedback (potential Markdown error?): {e}")
                # Try sending feedback as a new message as a fallback
                try:
                    context.bot.send_message(chat_id, feedback_text, parse_mode=ParseMode.MARKDOWN)
                except Exception as send_e:
                    logger.error(f"Failed to send feedback as a new message after edit failed: {send_e}")
        except Exception as e:
            logger.error(f"Error editing message with feedback: {e}")
            # Try sending feedback as a new message
            context.bot.send_message(chat_id, feedback_text, parse_mode=ParseMode.MARKDOWN)

        # Move to the next question
        quiz_data['current_question_index'] += 1

        # Schedule showing the next question slightly delayed to allow user to read feedback
        context.job_queue.run_once(lambda ctx: show_next_question_internal(ctx, chat_id, user_id), 2, context=context.user_data)

        return TAKING_QUIZ # Stay in the quiz state

    except (ValueError, IndexError):
        logger.error(f"Invalid callback data for answer: {data}")
        context.bot.send_message(chat_id, "حدث خطأ في استقبال إجابتك.")
        return TAKING_QUIZ

def end_quiz_timeout(context: CallbackContext):
    """Called by the job queue when the overall quiz time limit is reached."""
    job_context = context.job.context
    chat_id = job_context['chat_id']
    user_id = job_context['user_id']
    quiz_id = job_context['quiz_id']

    # Check if the user is still in this specific quiz
    # Use context.dispatcher.user_data
    user_data = context.dispatcher.user_data.get(user_id, {})
    if user_data.get('conversation_state') == 'in_quiz' and user_data.get('quiz', {}).get('id') == quiz_id:
        logger.info(f"Quiz {quiz_id} timed out for user {user_id}.")
        context.bot.send_message(chat_id, "⏰ انتهى وقت الاختبار!")
        end_quiz(context, chat_id, user_id) # Pass context directly
    else:
        logger.info(f"Quiz timer fired for quiz {quiz_id}, user {user_id}, but user is no longer in that quiz state.")

def end_quiz(context: CallbackContext, chat_id: int, user_id: int):
    """Ends the current quiz, calculates score, and shows results."""
    quiz_data = context.user_data.get('quiz')
    if not quiz_data:
        logger.warning(f"User {user_id} - end_quiz called but no quiz data found.")
        # Maybe send a message? Or just clean up state.
        context.user_data.pop('conversation_state', None)
        context.user_data.pop('quiz', None)
        context.user_data.pop('quiz_timer_job', None)
        context.user_data.pop('question_timer_job', None)
        return # Or return MAIN_MENU?

    # Remove any pending timers
    remove_quiz_timer(context)
    remove_question_timer(context)

    score = quiz_data['score']
    total_questions = len(quiz_data['questions'])
    quiz_id = quiz_data['id']

    # Update quiz end time and score in DB
    if QUIZ_DB:
        QUIZ_DB.end_quiz(quiz_id, score)
    else:
        logger.error("Cannot end quiz in DB: QuizDatabase not initialized.")

    percentage = (score / total_questions * 100) if total_questions > 0 else 0

    result_message = f"🏁 انتهى الاختبار!\n\n"
    result_message += f"نتيجتك: {score} من {total_questions} ({percentage:.1f}%)\n"
    # Add encouragement based on score
    if percentage >= 80:
        result_message += "🎉 ممتاز! أداء رائع!"
    elif percentage >= 60:
        result_message += "👍 جيد جداً! استمر في التعلم."
    elif percentage >= 40:
        result_message += "😐 لا بأس. تحتاج إلى المزيد من المراجعة."
    else:
        result_message += "😥 حاول مرة أخرى! يمكنك فعل ما هو أفضل."

    # Clean up user data related to the quiz
    context.user_data.pop('conversation_state', None)
    context.user_data.pop('quiz', None)
    context.user_data.pop('quiz_timer_job', None)
    context.user_data.pop('question_timer_job', None)
    # Keep quiz type/selection criteria? Maybe not needed now.
    context.user_data.pop('quiz_type', None)
    context.user_data.pop('selected_grade_id', None)
    context.user_data.pop('selected_chapter_id', None)
    context.user_data.pop('selected_lesson_id', None)
    context.user_data.pop('quiz_duration', None)

    # Send results and main menu keyboard
    keyboard = create_main_menu_keyboard(user_id)
    try:
        context.bot.send_message(chat_id, result_message, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error sending end quiz message: {e}")

# --- Admin Question Management Callbacks & Functions ---

def handle_new_question_text(update: Update, context: CallbackContext):
    """Handles receiving the text for a new question."""
    user_id = update.message.from_user.id
    if not is_admin(user_id):
        update.message.reply_text("غير مصرح لك.")
        return ConversationHandler.END

    question_text = update.message.text
    context.user_data['new_question']['text'] = question_text
    update.message.reply_text("تم استلام نص السؤال. الآن أرسل الخيارات الأربعة، كل خيار في رسالة منفصلة.\nالخيار الأول:")
    context.user_data['new_question']['options'] = []
    return ADDING_OPTIONS

def handle_new_question_options(update: Update, context: CallbackContext):
    """Handles receiving the options for a new question."""
    user_id = update.message.from_user.id
    if not is_admin(user_id):
        update.message.reply_text("غير مصرح لك.")
        return ConversationHandler.END

    option_text = update.message.text
    options_list = context.user_data['new_question']['options']
    options_list.append(option_text)

    if len(options_list) < 4:
        update.message.reply_text(f"الخيار {len(options_list) + 1}:")
        return ADDING_OPTIONS
    else:
        # All options received, ask for correct answer index
        options_display = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options_list)])
        update.message.reply_text(f"تم استلام الخيارات الأربعة:\n{options_display}\n\nالآن أرسل *رقم* الخيار الصحيح (1-4):")
        return ADDING_CORRECT_ANSWER

def handle_new_question_correct_answer(update: Update, context: CallbackContext):
    """Handles receiving the correct answer index for a new question."""
    user_id = update.message.from_user.id
    if not is_admin(user_id):
        update.message.reply_text("غير مصرح لك.")
        return ConversationHandler.END

    try:
        correct_index = int(update.message.text) - 1 # User enters 1-4, we store 0-3
        if not (0 <= correct_index < 4):
            raise ValueError("Index out of range")
        context.user_data['new_question']['correct'] = correct_index
        update.message.reply_text("تم تحديد الإجابة الصحيحة. الآن أرسل الشرح (اختياري)، أو أرسل /skip لتخطيه:")
        return ADDING_EXPLANATION
    except ValueError:
        update.message.reply_text("إدخال غير صالح. يرجى إرسال رقم بين 1 و 4.")
        return ADDING_CORRECT_ANSWER # Ask again

def handle_new_question_explanation(update: Update, context: CallbackContext):
    """Handles receiving the explanation for a new question."""
    user_id = update.message.from_user.id
    if not is_admin(user_id):
        update.message.reply_text("غير مصرح لك.")
        return ConversationHandler.END

    explanation = update.message.text
    context.user_data['new_question']['explanation'] = explanation
    # Now save the question
    save_new_question(update, context)
    return ConversationHandler.END

def skip_explanation(update: Update, context: CallbackContext):
    """Handles skipping the explanation for a new question."""
    user_id = update.message.from_user.id
    if not is_admin(user_id):
        update.message.reply_text("غير مصرح لك.")
        return ConversationHandler.END

    context.user_data['new_question']['explanation'] = None
    update.message.reply_text("تم تخطي الشرح.")
    # Now save the question
    save_new_question(update, context)
    return ConversationHandler.END

def save_new_question(update: Update, context: CallbackContext):
    """Saves the newly added question to the database."""
    new_question_data = context.user_data.get('new_question')
    if not QUIZ_DB or not new_question_data:
        logger.error("Cannot save question: DB not init or data missing.")
        update.message.reply_text("حدث خطأ أثناء حفظ السؤال.", reply_markup=create_admin_menu_keyboard())
        context.user_data.pop('new_question', None)
        return ADMIN_MENU

    try:
        # TODO: Need to associate question with grade/chapter/lesson
        # For now, adding without association or with a default?
        # Let's assume we need to ask for this info earlier in the flow.
        # TEMPORARY: Add without association
        question_id = QUIZ_DB.add_question(
            question_text=new_question_data['text'],
            options=new_question_data['options'],
            correct_option_index=new_question_data['correct'],
            explanation=new_question_data.get('explanation'),
            grade_level_id=None, # Needs to be selected
            chapter_id=None,     # Needs to be selected
            lesson_id=None,      # Needs to be selected
            image_data=None      # Image adding not implemented yet
        )
        if question_id:
            logger.info(f"Admin {update.message.from_user.id} added question {question_id}")
            update.message.reply_text(f"تمت إضافة السؤال بنجاح! رقم السؤال: {question_id}", reply_markup=create_admin_menu_keyboard())
        else:
            update.message.reply_text("فشل إضافة السؤال إلى قاعدة البيانات.", reply_markup=create_admin_menu_keyboard())

    except Exception as e:
        logger.error(f"Error saving new question: {e}")
        update.message.reply_text(f"حدث خطأ أثناء حفظ السؤال: {e}", reply_markup=create_admin_menu_keyboard())

    # Clean up
    context.user_data.pop('new_question', None)
    return ADMIN_MENU

def handle_delete_question_id(update: Update, context: CallbackContext):
    """Handles receiving the ID of the question to delete."""
    user_id = update.message.from_user.id
    if not is_admin(user_id):
        update.message.reply_text("غير مصرح لك.")
        return ConversationHandler.END

    try:
        question_id_to_delete = int(update.message.text)
        if not QUIZ_DB:
             update.message.reply_text("خطأ: قاعدة البيانات غير متاحة.", reply_markup=create_admin_menu_keyboard())
             return ADMIN_MENU

        success = QUIZ_DB.delete_question(question_id_to_delete)
        if success:
            logger.info(f"Admin {user_id} deleted question {question_id_to_delete}")
            update.message.reply_text(f"تم حذف السؤال رقم {question_id_to_delete} بنجاح.", reply_markup=create_admin_menu_keyboard())
        else:
            update.message.reply_text(f"لم يتم العثور على سؤال بالرقم {question_id_to_delete} أو حدث خطأ أثناء الحذف.", reply_markup=create_admin_menu_keyboard())

    except ValueError:
        update.message.reply_text("إدخال غير صالح. يرجى إرسال رقم السؤال العددي.")
        return DELETING_QUESTION # Ask again
    except Exception as e:
        logger.error(f"Error deleting question: {e}")
        update.message.reply_text(f"حدث خطأ أثناء حذف السؤال: {e}", reply_markup=create_admin_menu_keyboard())

    return ADMIN_MENU

def handle_show_question_id(update: Update, context: CallbackContext):
    """Handles receiving the ID of the question to show."""
    user_id = update.message.from_user.id
    if not is_admin(user_id):
        update.message.reply_text("غير مصرح لك.")
        return ConversationHandler.END

    try:
        question_id_to_show = int(update.message.text)
        if not QUIZ_DB:
             update.message.reply_text("خطأ: قاعدة البيانات غير متاحة.", reply_markup=create_admin_menu_keyboard())
             return ADMIN_MENU

        question_data = QUIZ_DB.get_question_by_id(question_id_to_show)

        if question_data:
            q_text = process_text_with_chemical_notation(question_data['question_text'])
            options_str = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(question_data['options'])])
            correct_opt_num = question_data['correct_option'] + 1
            explanation = process_text_with_chemical_notation(question_data.get('explanation') or "لا يوجد")
            grade_id = question_data.get('grade_level_id', 'غير محدد')
            chapter_id = question_data.get('chapter_id', 'غير محدد')
            lesson_id = question_data.get('lesson_id', 'غير محدد')
            image_exists = "نعم" if question_data.get('image_data') else "لا"

            message = f"*السؤال رقم:* {question_data['id']}\n"
            message += f"*النص:* {q_text}\n"
            message += f"*الخيارات:*\n{options_str}\n"
            message += f"*الإجابة الصحيحة:* {correct_opt_num}\n"
            message += f"*الشرح:* {explanation}\n"
            message += f"*المرحلة:* {grade_id} | *الفصل:* {chapter_id} | *الدرس:* {lesson_id}\n"
            message += f"*يحتوي على صورة:* {image_exists}"

            # Send message (handle potential Markdown errors)
            try:
                update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=create_admin_menu_keyboard())
            except BadRequest:
                 update.message.reply_text(message.replace('*',''), reply_markup=create_admin_menu_keyboard()) # Send without markdown

        else:
            update.message.reply_text(f"لم يتم العثور على سؤال بالرقم {question_id_to_show}.", reply_markup=create_admin_menu_keyboard())

    except ValueError:
        update.message.reply_text("إدخال غير صالح. يرجى إرسال رقم السؤال العددي.")
        return SHOWING_QUESTION # Ask again
    except Exception as e:
        logger.error(f"Error showing question: {e}")
        update.message.reply_text(f"حدث خطأ أثناء عرض السؤال: {e}", reply_markup=create_admin_menu_keyboard())

    return ADMIN_MENU

# --- Admin Structure Management Callbacks ---
# Placeholder functions - Need implementation
def handle_admin_grade_selection(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data
    admin_context = context.user_data.get('admin_context')

    if not is_admin(user_id):
        query.edit_message_text("Unauthorized.")
        return MAIN_MENU

    if data == 'admin_manage_structure':
        query.edit_message_text("العودة لقائمة إدارة الهيكل.", reply_markup=create_structure_admin_menu_keyboard())
        return ADMIN_MANAGE_STRUCTURE

    grade_id_str = data.split('_')[-1]
    # TODO: Handle 'add grade' text input

    if admin_context == 'manage_chapters' or admin_context == 'add_chapter':
        try:
            grade_id = int(grade_id_str)
            context.user_data['selected_admin_grade_id'] = grade_id
            context.user_data['admin_context'] = 'manage_chapters' # Set context for chapter management
            keyboard = create_chapters_keyboard(grade_id, for_quiz=False, for_lesson=False, context=context)
            query.edit_message_text(
                f"إدارة الفصول للمرحلة {grade_id}. اختر فصلاً للتعديل أو أضف فصلاً جديداً.",
                reply_markup=keyboard
            )
            query.message.reply_text("لإضافة فصل جديد لهذه المرحلة، أرسل اسمه.")
            return ADMIN_MANAGE_CHAPTERS
        except ValueError:
            query.edit_message_text("خطأ في اختيار المرحلة.")
            return ADMIN_MANAGE_GRADES

    elif admin_context == 'manage_lessons' or admin_context == 'add_lesson':
         try:
            grade_id = int(grade_id_str)
            context.user_data['selected_admin_grade_id'] = grade_id
            # Now need to select chapter
            keyboard = create_chapters_keyboard(grade_id, for_quiz=False, for_lesson=True, context=context)
            query.edit_message_text(
                f"إدارة الدروس للمرحلة {grade_id}. اختر الفصل أولاً:",
                reply_markup=keyboard
            )
            return ADMIN_MANAGE_CHAPTERS # Reuse state, context determines next step
         except ValueError:
            query.edit_message_text("خطأ في اختيار المرحلة.")
            return ADMIN_MANAGE_GRADES

    elif admin_context == 'manage_grades':
         # TODO: Handle editing/deleting selected grade
         query.edit_message_text(f"تم اختيار المرحلة {grade_id_str}. (وظيفة التعديل/الحذف غير مكتملة)")
         return ADMIN_MANAGE_GRADES
    else:
         query.edit_message_text("سياق غير معروف.")
         return ADMIN_MANAGE_STRUCTURE

def handle_admin_chapter_selection(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data
    admin_context = context.user_data.get('admin_context')

    if not is_admin(user_id):
        query.edit_message_text("Unauthorized.")
        return MAIN_MENU

    if data == 'admin_manage_grades': # Back button from chapter list
        context.user_data['admin_context'] = 'manage_chapters' # Reset context
        keyboard = create_grade_levels_keyboard(for_quiz=False, context=context)
        query.edit_message_text("العودة لاختيار المرحلة لإدارة الفصول.", reply_markup=keyboard)
        return ADMIN_MANAGE_GRADES

    chapter_id_str = data.split('_')[-1]
    # TODO: Handle 'add chapter' text input

    if admin_context == 'manage_lessons' or admin_context == 'add_lesson':
        try:
            chapter_id = int(chapter_id_str)
            context.user_data['selected_admin_chapter_id'] = chapter_id
            context.user_data['admin_context'] = 'manage_lessons' # Set context for lesson management
            keyboard = create_lessons_keyboard(chapter_id, for_quiz=False, context=context)
            query.edit_message_text(
                f"إدارة الدروس للفصل {chapter_id}. اختر درساً للتعديل أو أضف درساً جديداً.",
                reply_markup=keyboard
            )
            query.message.reply_text("لإضافة درس جديد لهذا الفصل، أرسل اسمه.")
            return ADMIN_MANAGE_LESSONS
        except ValueError:
            query.edit_message_text("خطأ في اختيار الفصل.")
            return ADMIN_MANAGE_CHAPTERS

    elif admin_context == 'manage_chapters':
         # TODO: Handle editing/deleting selected chapter
         query.edit_message_text(f"تم اختيار الفصل {chapter_id_str}. (وظيفة التعديل/الحذف غير مكتملة)")
         return ADMIN_MANAGE_CHAPTERS
    else:
         query.edit_message_text("سياق غير معروف.")
         return ADMIN_MANAGE_STRUCTURE

def handle_admin_lesson_selection(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    if not is_admin(user_id):
        query.edit_message_text("Unauthorized.")
        return MAIN_MENU

    if data == 'admin_manage_chapters': # Back button from lesson list
        context.user_data['admin_context'] = 'manage_lessons' # Reset context
        grade_id = context.user_data.get('selected_admin_grade_id')
        if grade_id:
            keyboard = create_chapters_keyboard(grade_id, for_quiz=False, for_lesson=True, context=context)
            query.edit_message_text("العودة لاختيار الفصل لإدارة الدروس.", reply_markup=keyboard)
            return ADMIN_MANAGE_CHAPTERS
        else: # Fallback if grade_id was lost
            keyboard = create_grade_levels_keyboard(for_quiz=False, context=context)
            query.edit_message_text("العودة لاختيار المرحلة.", reply_markup=keyboard)
            return ADMIN_MANAGE_GRADES

    lesson_id_str = data.split('_')[-1]
    # TODO: Handle 'add lesson' text input
    # TODO: Handle editing/deleting selected lesson
    query.edit_message_text(f"تم اختيار الدرس {lesson_id_str}. (وظيفة التعديل/الحذف غير مكتملة)")
    return ADMIN_MANAGE_LESSONS

# --- Fallback and Error Handlers ---

def unknown_command(update: Update, context: CallbackContext):
    """Handles unknown commands."""
    logger.warning(f"Received unknown command: {update.message.text}")
    update.message.reply_text("عذراً، لم أفهم هذا الأمر. استخدم /start للبدء.")

def unknown_message(update: Update, context: CallbackContext):
    """Handles messages that are not part of a conversation."""
    user_id = update.message.from_user.id
    logger.warning(f"Received unknown message from user {user_id}: {update.message.text}")
    keyboard = create_main_menu_keyboard(user_id)
    update.message.reply_text("عذراً، لم أفهم ما تقصده. يرجى استخدام الأزرار أو الأوامر المعروفة.", reply_markup=keyboard)
    return MAIN_MENU # Send back to main menu

def cancel_conversation(update: Update, context: CallbackContext):
    """Cancels the current conversation (e.g., adding question)."""
    user = update.message.from_user
    logger.info(f"User {user.id} canceled conversation.")
    # Clean up any temporary data
    context.user_data.pop('new_question', None)
    context.user_data.pop('quiz', None)
    context.user_data.pop('conversation_state', None)
    # Remove timers if any
    remove_quiz_timer(context)
    remove_question_timer(context)

    keyboard = create_main_menu_keyboard(user.id)
    update.message.reply_text('تم إلغاء العملية الحالية. العودة إلى القائمة الرئيسية.', reply_markup=keyboard)
    return ConversationHandler.END

# FIX: Correct error_handler signature for v12.8 with use_context=True
def error_handler(update: object, context: CallbackContext):
    """Log Errors caused by Updates."""
    # The error is stored in context.error
    error = context.error
    logger.error(msg="Exception while handling an update:", exc_info=error)

    # Optionally, notify the user or admin about the error
    # traceback_str = ''.join(traceback.format_exception(etype=type(error), value=error, tb=error.__traceback__))
    # logger.error(f"Traceback:\n{traceback_str}")

    # Attempt to notify the user in the chat where the error occurred
    if isinstance(update, Update) and update.effective_chat:
        try:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="حدث خطأ غير متوقع أثناء معالجة طلبك. تم إبلاغ المطورين."
            )
        except Exception as e:
            logger.error(f"Exception while sending error message to user: {e}")

# --- Main Function --- 
def main():
    """Start the bot."""
    if not TOKEN:
        logger.critical("Bot token not found. Exiting.")
        return
    if not QUIZ_DB:
        logger.warning("QuizDatabase not initialized. Quiz features will be unavailable.")
        # Decide if the bot should run without DB or exit
        # return # Uncomment to exit if DB is essential

    # Create the Updater and pass it your bot's token.
    # Make sure to set use_context=True to use the new context based callbacks
    # Post version 12 this will no longer be necessary
    updater = Updater(TOKEN, use_context=True)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # --- Conversation Handler Setup ---
    # This handler manages the multi-step interactions like adding questions or taking quizzes
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start_command),
            CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'), # Allow re-entry via button
            CallbackQueryHandler(quiz_menu_callback, pattern='^menu_quiz$'), # Allow re-entry via button
            CallbackQueryHandler(admin_menu_callback, pattern='^menu_admin$') # Allow re-entry via button
        ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(main_menu_callback, pattern='^(menu_info|menu_quiz|menu_reports|menu_about|menu_admin)$'),
                # Add handler for unknown messages/commands in main menu?
                MessageHandler(Filters.text & ~Filters.command, unknown_message)
            ],
            QUIZ_MENU: [
                CallbackQueryHandler(quiz_menu_callback, pattern='^(quiz_random_prompt|quiz_by_chapter_prompt|quiz_by_lesson_prompt|quiz_by_grade_prompt|quiz_review_prompt|main_menu)$'),
                CallbackQueryHandler(select_grade_level_quiz_callback, pattern='^select_grade_quiz_'), # Handle grade selection for quiz
            ],
            ADMIN_MENU: [
                CallbackQueryHandler(admin_menu_callback, pattern='^(admin_add_question|admin_delete_question|admin_show_question|admin_manage_structure|main_menu)$'),
            ],
            ADMIN_MANAGE_STRUCTURE: [
                 CallbackQueryHandler(admin_structure_menu_callback, pattern='^(admin_manage_grades|admin_manage_chapters|admin_manage_lessons|menu_admin)$'),
            ],
            ADMIN_MANAGE_GRADES: [
                 CallbackQueryHandler(handle_admin_grade_selection, pattern='^select_grade_admin_|^select_grade_for_chapter_|^admin_manage_structure$'),
                 # TODO: Add MessageHandler for adding new grade name
                 # MessageHandler(Filters.text & ~Filters.command, handle_add_grade_name)
            ],
             ADMIN_MANAGE_CHAPTERS: [
                 CallbackQueryHandler(handle_admin_chapter_selection, pattern='^select_chapter_admin_|^select_chapter_for_lesson_admin_|^admin_manage_grades$'),
                 # TODO: Add MessageHandler for adding new chapter name
                 # MessageHandler(Filters.text & ~Filters.command, handle_add_chapter_name)
            ],
             ADMIN_MANAGE_LESSONS: [
                 CallbackQueryHandler(handle_admin_lesson_selection, pattern='^select_lesson_admin_|^admin_manage_chapters$'),
                 # TODO: Add MessageHandler for adding new lesson name
                 # MessageHandler(Filters.text & ~Filters.command, handle_add_lesson_name)
            ],
            ADDING_QUESTION: [
                MessageHandler(Filters.text & ~Filters.command, handle_new_question_text)
            ],
            ADDING_OPTIONS: [
                MessageHandler(Filters.text & ~Filters.command, handle_new_question_options)
            ],
            ADDING_CORRECT_ANSWER: [
                MessageHandler(Filters.regex('^[1-4]$'), handle_new_question_correct_answer)
            ],
            ADDING_EXPLANATION: [
                MessageHandler(Filters.text & ~Filters.command, handle_new_question_explanation),
                CommandHandler('skip', skip_explanation)
            ],
            DELETING_QUESTION: [
                MessageHandler(Filters.regex('^[0-9]+$'), handle_delete_question_id)
            ],
            SHOWING_QUESTION: [
                MessageHandler(Filters.regex('^[0-9]+$'), handle_show_question_id)
            ],
            SELECT_GRADE_LEVEL_FOR_QUIZ: [
                CallbackQueryHandler(select_grade_level_quiz_callback, pattern='^select_grade_quiz_|^menu_quiz$')
            ],
            SELECT_CHAPTER_FOR_QUIZ: [
                 CallbackQueryHandler(select_chapter_quiz_callback, pattern='^select_chapter_quiz_|^quiz_by_chapter_prompt$')
            ],
            SELECT_CHAPTER_FOR_LESSON: [ # State for selecting chapter when quiz type is lesson
                 CallbackQueryHandler(select_chapter_for_lesson_quiz_callback, pattern='^select_chapter_lesson_|^quiz_by_lesson_prompt$')
            ],
            SELECT_LESSON_FOR_QUIZ: [
                 CallbackQueryHandler(select_lesson_quiz_callback, pattern='^select_lesson_quiz_|^quiz_by_lesson_prompt$')
            ],
            SELECTING_QUIZ_DURATION: [
                CallbackQueryHandler(select_quiz_duration_callback, pattern='^quiz_duration_|^menu_quiz$')
            ],
            TAKING_QUIZ: [
                CallbackQueryHandler(handle_answer, pattern='^ans_')
                # No other messages expected here, maybe add a handler for /cancel?
            ],
        },
        fallbacks=[
            CommandHandler('cancel', cancel_conversation),
            CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'), # Allow cancel via main menu button?
            # Add a fallback for unexpected messages/commands in conversation?
            MessageHandler(Filters.text, unknown_message) # Or a more specific fallback message
            ]
    )

    dp.add_handler(conv_handler)

    # log all errors
    dp.add_error_handler(error_handler)

    # Start the Bot
    try:
        updater.start_polling()
        logger.info("Bot polling started successfully.")
    except NetworkError as e:
        logger.error(f"Network Error starting polling: {e}")
    except Unauthorized:
        logger.critical("Unauthorized: Invalid bot token?")
    except Exception as e:
        logger.critical(f"Unhandled exception starting polling: {e}")
        return # Exit if polling fails critically

    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()
    logger.info("Bot stopped gracefully.")

if __name__ == '__main__':
    main()
