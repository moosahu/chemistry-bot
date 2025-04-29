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
        Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ParseMode,
        TelegramError, Unauthorized, BadRequest
    )
    # تم التعديل: استيراد NetworkError من telegram.error
    from telegram.error import NetworkError 
    from telegram.ext import (
        Updater, CommandHandler, MessageHandler, Filters, CallbackContext, 
        CallbackQueryHandler, ConversationHandler, JobQueue
    )
    logger.info("Successfully imported telegram modules for v12.8")
except ImportError as e:
    logger.critical(f"Failed to import core telegram modules (v12.8): {e}")
    # قد تحتاج لإيقاف البوت هنا إذا لم يتم استيراد الوحدات الأساسية
    sys.exit("Critical import error, stopping bot.")

# استيراد البيانات الثابتة ووظائف المعادلات
from chemistry_data import ELEMENTS, COMPOUNDS, CONCEPTS, PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO
from chemical_equations import process_text_with_chemical_notation, format_chemical_equation

# استيراد الفئة المحسنة لقاعدة البيانات
from quiz_db import QuizDatabase

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
    SELECTING_CHAPTER_FOR_LESSON_ADMIN
) = range(30)

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
        keyboard.append([InlineKeyboardButton("🔙 العودة لاختيار الفصل", callback_data='quiz_by_lesson_prompt')]) # قد تحتاج لتعديل هذا
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
    user_id = context.user_data.get('user_id') # نفترض أن معرف المستخدم مخزن
    quiz_id = context.user_data.get('quiz', {}).get('id')
    if user_id and quiz_id:
        job_name = f"quiz_timeout_{user_id}_{quiz_id}"
        current_jobs = context.job_queue.get_jobs_by_name(job_name)
        if not current_jobs:
            # logger.info(f"No active quiz timer found with name {job_name}")
            return
        for job in current_jobs:
            job.schedule_removal()
            logger.info(f"Removed quiz timer job: {job_name}")

def remove_question_timer(context: CallbackContext):
    """إزالة مؤقت السؤال إذا كان موجوداً."""
    user_id = context.user_data.get('user_id') # نفترض أن معرف المستخدم مخزن
    quiz_id = context.user_data.get('quiz', {}).get('id')
    if user_id and quiz_id:
        job_name = f"question_timer_{user_id}_{quiz_id}"
        current_jobs = context.job_queue.get_jobs_by_name(job_name)
        if not current_jobs:
            # logger.info(f"No active question timer found with name {job_name}")
            return
        for job in current_jobs:
            job.schedule_removal()
            logger.info(f"Removed question timer job: {job_name}")

# --- وظائف معالجة الأوامر ---

def start_command(update: Update, context: CallbackContext) -> int:
    """معالجة أمر /start."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    logger.info(f"User {user.id} in chat {chat_id} started the bot.")
    
    # تخزين معرف المستخدم للوصول إليه لاحقاً في المؤقتات
    context.user_data['user_id'] = user.id
    
    welcome_text = (
        f"🖋️ مرحباً بك في بوت الكيمياء التحصيلي\n\n"
        f"👋 أهلاً {user.first_name}!\n\n"
        f"اختر أحد الخيارات أدناه:"
    )
    
    reply_markup = create_main_menu_keyboard(user.id)
    
    try:
        update.message.reply_text(welcome_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error sending start message: {e}")
        
    return MAIN_MENU

def main_menu_callback(update: Update, context: CallbackContext) -> int:
    """معالجة العودة للقائمة الرئيسية."""
    query = update.callback_query
    query.answer()
    user = query.effective_user
    
    welcome_text = (
        f"🖋️ مرحباً بك مجدداً في بوت الكيمياء التحصيلي\n\n"
        f"👋 أهلاً {user.first_name}!\n\n"
        f"اختر أحد الخيارات أدناه:"
    )
    
    reply_markup = create_main_menu_keyboard(user.id)
    
    try:
        query.edit_message_text(welcome_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error editing message for main menu: {e}")
        
    return MAIN_MENU

def info_menu_callback(update: Update, context: CallbackContext) -> int:
    """معالجة قائمة المعلومات الكيميائية."""
    query = update.callback_query
    query.answer()
    
    info_text = (
        "📚 **المعلومات الكيميائية**\n\n"
        "اختر نوع المعلومات التي ترغب في استعراضها:"
    )
    
    keyboard = [
        [InlineKeyboardButton("🧪 العناصر الكيميائية", callback_data='info_elements')],
        [InlineKeyboardButton("🔬 المركبات الكيميائية", callback_data='info_compounds')],
        [InlineKeyboardButton("💡 المفاهيم الكيميائية", callback_data='info_concepts')],
        [InlineKeyboardButton("🔢 الحسابات الكيميائية", callback_data='info_calculations')],
        [InlineKeyboardButton("🔗 الروابط الكيميائية", callback_data='info_bonds')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        query.edit_message_text(info_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error editing message for info menu: {e}")
        
    return MAIN_MENU # البقاء في نفس الحالة أو الانتقال لحالة فرعية للمعلومات

def quiz_menu_callback(update: Update, context: CallbackContext) -> int:
    """معالجة قائمة الاختبارات."""
    query = update.callback_query
    query.answer()
    
    quiz_text = (
        "📝 **الاختبارات**\n\n"
        "اختر نوع الاختبار الذي ترغب في إجرائه:"
    )
    
    reply_markup = create_quiz_menu_keyboard()
    
    try:
        query.edit_message_text(quiz_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error editing message for quiz menu: {e}")
        
    return QUIZ_MENU

def admin_menu_callback(update: Update, context: CallbackContext) -> int:
    """معالجة قائمة الإدارة."""
    query = update.callback_query
    query.answer()
    user = query.effective_user
    
    if not is_admin(user.id):
        try:
            query.edit_message_text("🚫 عذراً، هذه المنطقة مخصصة للمسؤولين فقط.")
        except Exception as e:
            logger.error(f"Error sending admin restriction message: {e}")
        return MAIN_MENU
    
    admin_text = (
        "⚙️ **إدارة البوت**\n\n"
        "اختر المهمة التي ترغب في تنفيذها:"
    )
    
    reply_markup = create_admin_menu_keyboard()
    
    try:
        query.edit_message_text(admin_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error editing message for admin menu: {e}")
        
    return ADMIN_MENU

def manage_structure_callback(update: Update, context: CallbackContext) -> int:
    """معالجة قائمة إدارة الهيكل (المراحل/الفصول/الدروس)."""
    query = update.callback_query
    query.answer()
    user = query.effective_user

    if not is_admin(user.id):
        try:
            query.edit_message_text("🚫 عذراً، هذه المنطقة مخصصة للمسؤولين فقط.")
        except Exception as e:
            logger.error(f"Error sending admin restriction message: {e}")
        return MAIN_MENU

    structure_text = (
        "🏫 **إدارة المراحل/الفصول/الدروس**\n\n"
        "اختر القسم الذي ترغب في إدارته:"
    )

    reply_markup = create_structure_admin_menu_keyboard()

    try:
        query.edit_message_text(structure_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error editing message for structure admin menu: {e}")

    return ADMIN_MENU # البقاء في حالة الإدارة

def manage_grades_callback(update: Update, context: CallbackContext) -> int:
    """عرض قائمة المراحل الدراسية للإدارة."""
    query = update.callback_query
    query.answer()
    user = query.effective_user

    if not is_admin(user.id):
        # ... (نفس التحقق من المسؤول)
        return MAIN_MENU

    context.user_data['admin_context'] = 'manage_grades' # تحديد السياق
    grades_text = (
        "🏫 **إدارة المراحل الدراسية**\n\n"
        "اختر مرحلة لإدارتها أو قم بإضافة مرحلة جديدة:"
    )
    reply_markup = create_grade_levels_keyboard(for_quiz=False, context=context)
    
    # إضافة زر "إضافة مرحلة جديدة"
    if reply_markup:
        reply_markup.inline_keyboard.insert(0, [InlineKeyboardButton("➕ إضافة مرحلة جديدة", callback_data='admin_add_grade')])
    else:
        # في حالة عدم وجود مراحل، نعرض فقط زر الإضافة والعودة
        keyboard = [
            [InlineKeyboardButton("➕ إضافة مرحلة جديدة", callback_data='admin_add_grade')],
            [InlineKeyboardButton("🔙 العودة لقائمة إدارة الهيكل", callback_data='admin_manage_structure')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        query.edit_message_text(grades_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error editing message for manage grades menu: {e}")

    return ADMIN_GRADE_MENU

def manage_chapters_callback(update: Update, context: CallbackContext) -> int:
    """عرض قائمة المراحل لاختيار مرحلة لإدارة فصولها."""
    query = update.callback_query
    query.answer()
    user = query.effective_user

    if not is_admin(user.id):
        # ... (نفس التحقق من المسؤول)
        return MAIN_MENU

    context.user_data['admin_context'] = 'add_chapter' # تحديد السياق لاختيار مرحلة لإضافة فصل
    grades_text = (
        "📚 **إدارة الفصول**\n\n"
        "اختر المرحلة الدراسية التي ترغب في إدارة فصولها:"
    )
    reply_markup = create_grade_levels_keyboard(for_quiz=False, context=context)

    if not reply_markup:
        try:
            query.edit_message_text("⚠️ لا توجد مراحل دراسية لإدارة فصولها. قم بإضافة مراحل أولاً.", 
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة إدارة الهيكل", callback_data='admin_manage_structure')]]))
        except Exception as e:
            logger.error(f"Error sending no grades message (chapters): {e}")
        return ADMIN_MENU

    try:
        query.edit_message_text(grades_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error editing message for manage chapters (select grade): {e}")

    return ADMIN_CHAPTER_MENU # حالة اختيار المرحلة لإدارة الفصول

def manage_lessons_callback(update: Update, context: CallbackContext) -> int:
    """عرض قائمة المراحل لاختيار مرحلة لإدارة دروسها."""
    query = update.callback_query
    query.answer()
    user = query.effective_user

    if not is_admin(user.id):
        # ... (نفس التحقق من المسؤول)
        return MAIN_MENU

    context.user_data['admin_context'] = 'add_lesson' # تحديد السياق لاختيار مرحلة لإضافة درس
    grades_text = (
        "📝 **إدارة الدروس**\n\n"
        "اختر المرحلة الدراسية التي ترغب في إدارة دروسها:"
    )
    # نستخدم نفس لوحة المفاتيح ولكن السياق مختلف
    reply_markup = create_grade_levels_keyboard(for_quiz=False, context=context)

    if not reply_markup:
        try:
            query.edit_message_text("⚠️ لا توجد مراحل دراسية لإدارة دروسها. قم بإضافة مراحل أولاً.", 
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة إدارة الهيكل", callback_data='admin_manage_structure')]]))
        except Exception as e:
            logger.error(f"Error sending no grades message (lessons): {e}")
        return ADMIN_MENU

    try:
        query.edit_message_text(grades_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error editing message for manage lessons (select grade): {e}")

    return ADMIN_LESSON_MENU # حالة اختيار المرحلة لإدارة الدروس

def add_grade_prompt(update: Update, context: CallbackContext) -> int:
    """طلب إدخال اسم المرحلة الدراسية الجديدة."""
    query = update.callback_query
    query.answer()
    user = query.effective_user

    if not is_admin(user.id):
        # ... (نفس التحقق من المسؤول)
        return MAIN_MENU

    try:
        query.edit_message_text("🏫 أدخل اسم المرحلة الدراسية الجديدة:")
    except Exception as e:
        logger.error(f"Error asking for new grade name: {e}")

    return ADDING_GRADE_LEVEL

def add_chapter_prompt(update: Update, context: CallbackContext) -> int:
    """طلب إدخال اسم الفصل الجديد للمرحلة المحددة."""
    query = update.callback_query
    query.answer()
    user = query.effective_user
    selected_grade_id = context.user_data.get('selected_grade_id')

    if not is_admin(user.id) or selected_grade_id is None:
        # ... (تحقق من المسؤول ومن وجود مرحلة محددة)
        return ADMIN_MENU

    try:
        query.edit_message_text("📚 أدخل اسم الفصل الجديد لهذه المرحلة:")
    except Exception as e:
        logger.error(f"Error asking for new chapter name: {e}")

    return ADDING_CHAPTER

def add_lesson_prompt(update: Update, context: CallbackContext) -> int:
    """طلب إدخال اسم الدرس الجديد للفصل المحدد."""
    query = update.callback_query
    query.answer()
    user = query.effective_user
    selected_chapter_id = context.user_data.get('selected_chapter_id')

    if not is_admin(user.id) or selected_chapter_id is None:
        # ... (تحقق من المسؤول ومن وجود فصل محدد)
        return ADMIN_MENU

    try:
        query.edit_message_text("📝 أدخل اسم الدرس الجديد لهذا الفصل:")
    except Exception as e:
        logger.error(f"Error asking for new lesson name: {e}")

    return ADDING_LESSON

def add_grade_level(update: Update, context: CallbackContext) -> int:
    """إضافة المرحلة الدراسية الجديدة إلى قاعدة البيانات."""
    user = update.effective_user
    grade_name = update.message.text.strip()

    if not is_admin(user.id):
        # ... (نفس التحقق من المسؤول)
        return MAIN_MENU

    if not grade_name:
        update.message.reply_text("⚠️ اسم المرحلة لا يمكن أن يكون فارغاً. يرجى المحاولة مرة أخرى.")
        return ADDING_GRADE_LEVEL

    if QUIZ_DB:
        try:
            grade_id = QUIZ_DB.add_grade_level(grade_name)
            if grade_id:
                update.message.reply_text(f"✅ تم إضافة المرحلة الدراسية '{grade_name}' بنجاح.")
                logger.info(f"Admin {user.id} added grade level: {grade_name} (ID: {grade_id})")
            else:
                update.message.reply_text("⚠️ حدث خطأ أثناء إضافة المرحلة الدراسية.")
        except Exception as e:
            logger.error(f"Error adding grade level '{grade_name}': {e}")
            update.message.reply_text("❌ حدث خطأ غير متوقع. يرجى مراجعة السجلات.")
    else:
        logger.error("Cannot add grade level: QuizDatabase not initialized.")
        update.message.reply_text("❌ خطأ: قاعدة البيانات غير متاحة.")

    # العودة لقائمة إدارة المراحل
    context.user_data['admin_context'] = 'manage_grades'
    grades_text = "🏫 **إدارة المراحل الدراسية**\n\nاختر مرحلة لإدارتها أو قم بإضافة مرحلة جديدة:"
    reply_markup = create_grade_levels_keyboard(for_quiz=False, context=context)
    if reply_markup:
        reply_markup.inline_keyboard.insert(0, [InlineKeyboardButton("➕ إضافة مرحلة جديدة", callback_data='admin_add_grade')])
    else:
        keyboard = [[InlineKeyboardButton("➕ إضافة مرحلة جديدة", callback_data='admin_add_grade')], [InlineKeyboardButton("🔙 العودة لقائمة إدارة الهيكل", callback_data='admin_manage_structure')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        update.message.reply_text(grades_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error sending manage grades menu after adding grade: {e}")
        
    return ADMIN_GRADE_MENU

def add_chapter(update: Update, context: CallbackContext) -> int:
    """إضافة الفصل الجديد إلى قاعدة البيانات."""
    user = update.effective_user
    chapter_name = update.message.text.strip()
    selected_grade_id = context.user_data.get('selected_grade_id_for_chapter') # استخدام المعرف المخزن عند اختيار المرحلة

    if not is_admin(user.id) or selected_grade_id is None:
        # ... (تحقق)
        return ADMIN_MENU

    if not chapter_name:
        update.message.reply_text("⚠️ اسم الفصل لا يمكن أن يكون فارغاً. يرجى المحاولة مرة أخرى.")
        return ADDING_CHAPTER

    if QUIZ_DB:
        try:
            chapter_id = QUIZ_DB.add_chapter(selected_grade_id, chapter_name)
            if chapter_id:
                update.message.reply_text(f"✅ تم إضافة الفصل '{chapter_name}' للمرحلة المحددة بنجاح.")
                logger.info(f"Admin {user.id} added chapter: {chapter_name} (ID: {chapter_id}) to grade {selected_grade_id}")
            else:
                update.message.reply_text("⚠️ حدث خطأ أثناء إضافة الفصل.")
        except Exception as e:
            logger.error(f"Error adding chapter '{chapter_name}' to grade {selected_grade_id}: {e}")
            update.message.reply_text("❌ حدث خطأ غير متوقع. يرجى مراجعة السجلات.")
    else:
        logger.error("Cannot add chapter: QuizDatabase not initialized.")
        update.message.reply_text("❌ خطأ: قاعدة البيانات غير متاحة.")

    # العودة لقائمة إدارة الفصول للمرحلة المحددة
    context.user_data['selected_grade_id'] = selected_grade_id # تحديث المعرف للسياق التالي
    context.user_data['admin_context'] = 'manage_chapters'
    chapter_text = f"📚 **إدارة الفصول للمرحلة المحددة**\n\nاختر الفصل للإدارة أو قم بإضافة فصل جديد:"
    reply_markup = create_chapters_keyboard(selected_grade_id, context=context)
    # إضافة زر إضافة فصل جديد
    if reply_markup:
         reply_markup.inline_keyboard.insert(0, [InlineKeyboardButton("➕ إضافة فصل جديد", callback_data='admin_add_chapter_prompt')])
    else:
        keyboard = [[InlineKeyboardButton("➕ إضافة فصل جديد", callback_data='admin_add_chapter_prompt')], [InlineKeyboardButton("🔙 العودة لاختيار المرحلة", callback_data='admin_manage_chapters')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
    try:
        update.message.reply_text(chapter_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error sending manage chapters menu after adding chapter: {e}")
        
    return ADMIN_CHAPTER_MENU

def add_lesson(update: Update, context: CallbackContext) -> int:
    """إضافة الدرس الجديد إلى قاعدة البيانات."""
    user = update.effective_user
    lesson_name = update.message.text.strip()
    selected_chapter_id = context.user_data.get('selected_chapter_id_for_lesson') # استخدام المعرف المخزن عند اختيار الفصل

    if not is_admin(user.id) or selected_chapter_id is None:
        # ... (تحقق)
        return ADMIN_MENU

    if not lesson_name:
        update.message.reply_text("⚠️ اسم الدرس لا يمكن أن يكون فارغاً. يرجى المحاولة مرة أخرى.")
        return ADDING_LESSON

    if QUIZ_DB:
        try:
            lesson_id = QUIZ_DB.add_lesson(selected_chapter_id, lesson_name)
            if lesson_id:
                update.message.reply_text(f"✅ تم إضافة الدرس '{lesson_name}' للفصل المحدد بنجاح.")
                logger.info(f"Admin {user.id} added lesson: {lesson_name} (ID: {lesson_id}) to chapter {selected_chapter_id}")
            else:
                update.message.reply_text("⚠️ حدث خطأ أثناء إضافة الدرس.")
        except Exception as e:
            logger.error(f"Error adding lesson '{lesson_name}' to chapter {selected_chapter_id}: {e}")
            update.message.reply_text("❌ حدث خطأ غير متوقع. يرجى مراجعة السجلات.")
    else:
        logger.error("Cannot add lesson: QuizDatabase not initialized.")
        update.message.reply_text("❌ خطأ: قاعدة البيانات غير متاحة.")

    # العودة لقائمة إدارة الدروس للفصل المحدد
    context.user_data['selected_chapter_id'] = selected_chapter_id # تحديث المعرف للسياق التالي
    context.user_data['admin_context'] = 'manage_lessons'
    lesson_text = f"📝 **إدارة الدروس للفصل المحدد**\n\nاختر الدرس للإدارة أو قم بإضافة درس جديد:"
    reply_markup = create_lessons_keyboard(selected_chapter_id, context=context)
    # إضافة زر إضافة درس جديد
    if reply_markup:
         reply_markup.inline_keyboard.insert(0, [InlineKeyboardButton("➕ إضافة درس جديد", callback_data='admin_add_lesson_prompt')])
    else:
        keyboard = [[InlineKeyboardButton("➕ إضافة درس جديد", callback_data='admin_add_lesson_prompt')], [InlineKeyboardButton("🔙 العودة لاختيار الفصل", callback_data='admin_manage_lessons')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
    try:
        update.message.reply_text(lesson_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error sending manage lessons menu after adding lesson: {e}")
        
    return ADMIN_LESSON_MENU

def about_callback(update: Update, context: CallbackContext) -> int:
    """معالجة زر حول البوت."""
    query = update.callback_query
    query.answer()
    
    about_text = (
        "ℹ️ **حول بوت الكيمياء التحصيلي**\n\n"
        "هذا البوت مصمم لمساعدتك في الاستعداد لاختبار الكيمياء التحصيلي من خلال:\n"
        "- توفير معلومات عن العناصر والمركبات والمفاهيم الكيميائية.\n"
        "- تقديم اختبارات تفاعلية لتقييم معرفتك.\n"
        "- تتبع أدائك ومساعدتك على مراجعة الأخطاء.\n\n"
        "تم التطوير بواسطة: [اسم المطور أو الفريق]"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        query.edit_message_text(about_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error editing message for about menu: {e}")
        
    return MAIN_MENU

def info_callback(update: Update, context: CallbackContext) -> int:
    """معالجة طلبات المعلومات الكيميائية."""
    query = update.callback_query
    query.answer()
    data = query.data
    
    info_text = ""
    image_path = None
    
    if data == 'info_elements':
        info_text = "**🧪 العناصر الكيميائية**\n\n" + PERIODIC_TABLE_INFO
        # يمكنك إضافة صورة للجدول الدوري هنا إذا أردت
        # image_path = 'path/to/periodic_table.png'
    elif data == 'info_compounds':
        info_text = "**🔬 المركبات الكيميائية**\n\nأمثلة على المركبات الشائعة وخصائصها:\n"
        # إضافة أمثلة للمركبات
        for name, formula in list(COMPOUNDS.items())[:5]: # عرض أول 5 كأمثلة
            info_text += f"- {name} ({formula})\n"
        info_text += "\n(المزيد من المركبات سيتم إضافتها لاحقاً)"
    elif data == 'info_concepts':
        info_text = "**💡 المفاهيم الكيميائية**\n\nشرح لبعض المفاهيم الأساسية:\n"
        # إضافة أمثلة للمفاهيم
        for concept, description in list(CONCEPTS.items())[:3]: # عرض أول 3 كأمثلة
            info_text += f"- **{concept}:** {description}\n"
        info_text += "\n(المزيد من المفاهيم سيتم إضافتها لاحقاً)"
    elif data == 'info_calculations':
        info_text = "**🔢 الحسابات الكيميائية**\n\n" + CHEMICAL_CALCULATIONS_INFO
    elif data == 'info_bonds':
        info_text = "**🔗 الروابط الكيميائية**\n\n" + CHEMICAL_BONDS_INFO
    else:
        info_text = "⚠️ طلب معلومات غير معروف."

    # معالجة النص لإظهار الصيغ الكيميائية بشكل صحيح (مثال بسيط)
    info_text = process_text_with_chemical_notation(info_text)

    keyboard = [[InlineKeyboardButton("🔙 العودة لقائمة المعلومات", callback_data='menu_info')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        if image_path and os.path.exists(image_path):
            with open(image_path, 'rb') as img:
                query.edit_message_media(
                    media=InputMediaPhoto(media=img, caption=info_text, parse_mode=ParseMode.MARKDOWN),
                    reply_markup=reply_markup
                )
        else:
            query.edit_message_text(info_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass # تجاهل الخطأ إذا لم يتم تعديل الرسالة
        else:
            logger.error(f"Error editing message for info ({data}): {e}")
            # محاولة إرسال رسالة جديدة كحل بديل
            try:
                context.bot.send_message(chat_id=query.effective_chat.id, text=info_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception as send_error:
                 logger.error(f"Failed to send new message for info ({data}): {send_error}")
    except Exception as e:
        logger.error(f"Error editing message for info ({data}): {e}")
        # محاولة إرسال رسالة جديدة كحل بديل
        try:
            context.bot.send_message(chat_id=query.effective_chat.id, text=info_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception as send_error:
             logger.error(f"Failed to send new message for info ({data}): {send_error}")

    return MAIN_MENU

# --- وظائف إدارة الأسئلة --- 

def add_question_start(update: Update, context: CallbackContext) -> int:
    """بدء عملية إضافة سؤال جديد."""
    query = update.callback_query
    query.answer()
    user = query.effective_user

    if not is_admin(user.id):
        # ... (نفس التحقق من المسؤول)
        return MAIN_MENU

    context.user_data['new_question'] = {}
    try:
        query.edit_message_text("📝 أدخل نص السؤال (يمكنك استخدام Markdown للتنسيق والصيغ الكيميائية مثل H~2~O أو ^14^C):")
    except Exception as e:
        logger.error(f"Error asking for question text: {e}")
        
    return ADDING_QUESTION

def add_question_text(update: Update, context: CallbackContext) -> int:
    """تلقي نص السؤال."""
    user = update.effective_user
    if not is_admin(user.id):
        return MAIN_MENU
        
    question_text = update.message.text
    context.user_data['new_question']['text'] = question_text
    
    # طلب إدخال الخيارات
    update.message.reply_text("🔢 أدخل الخيارات الأربعة مفصولة بفاصلة منقوطة (؛)\nمثال: خيار1؛ خيار2؛ خيار3؛ خيار4")
    return ADDING_OPTIONS

def add_question_options(update: Update, context: CallbackContext) -> int:
    """تلقي خيارات السؤال."""
    user = update.effective_user
    if not is_admin(user.id):
        return MAIN_MENU
        
    options_text = update.message.text
    options = [opt.strip() for opt in options_text.split('؛')] # استخدام فاصلة منقوطة
    
    if len(options) != 4:
        update.message.reply_text("⚠️ يجب إدخال أربعة خيارات بالضبط مفصولة بفاصلة منقوطة (؛). حاول مرة أخرى.")
        return ADDING_OPTIONS
        
    context.user_data['new_question']['options'] = options
    
    # طلب رقم الإجابة الصحيحة
    update.message.reply_text("✅ أدخل رقم الخيار الصحيح (1، 2، 3، أو 4):")
    return ADDING_CORRECT_ANSWER

def add_question_correct_answer(update: Update, context: CallbackContext) -> int:
    """تلقي رقم الإجابة الصحيحة."""
    user = update.effective_user
    if not is_admin(user.id):
        return MAIN_MENU
        
    correct_answer_text = update.message.text
    try:
        correct_answer_index = int(correct_answer_text) - 1 # تحويل إلى فهرس (0-3)
        if not (0 <= correct_answer_index <= 3):
            raise ValueError("Index out of range")
    except ValueError:
        update.message.reply_text("⚠️ يجب إدخال رقم صحيح بين 1 و 4. حاول مرة أخرى.")
        return ADDING_CORRECT_ANSWER
        
    context.user_data['new_question']['correct_answer_index'] = correct_answer_index
    
    # طلب الشرح (اختياري)
    update.message.reply_text("💡 أدخل شرحاً للإجابة (اختياري، اكتب 'لا يوجد' إذا لم ترغب بإضافة شرح):")
    return ADDING_EXPLANATION

def add_question_explanation(update: Update, context: CallbackContext) -> int:
    """تلقي شرح الإجابة وحفظ السؤال."""
    user = update.effective_user
    if not is_admin(user.id):
        return MAIN_MENU
        
    explanation = update.message.text.strip()
    if explanation.lower() == 'لا يوجد':
        explanation = None
        
    context.user_data['new_question']['explanation'] = explanation
    
    # -- طلب تحديد المرحلة والفصل والدرس --
    context.user_data['admin_context'] = 'add_question_grade' # سياق جديد لتحديد المرحلة للسؤال
    grades_text = "🏫 اختر المرحلة الدراسية التي ينتمي إليها هذا السؤال:"
    reply_markup = create_grade_levels_keyboard(for_quiz=False, context=context) # استخدام لوحة مفاتيح المراحل للإدارة
    
    if not reply_markup:
         update.message.reply_text("⚠️ لا توجد مراحل دراسية. يرجى إضافة مراحل أولاً قبل إضافة الأسئلة.",
                                 reply_markup=create_admin_menu_keyboard())
         return ADMIN_MENU
         
    try:
        update.message.reply_text(grades_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error asking for grade level for new question: {e}")
        update.message.reply_text("حدث خطأ أثناء عرض المراحل.", reply_markup=create_admin_menu_keyboard())
        return ADMIN_MENU
        
    # لا ننتقل لحالة جديدة هنا، بل ننتظر رد المستخدم في callback_query_handler
    # الحالة تبقى ADDING_EXPLANATION أو يمكن تغييرها لحالة وسيطة مثل SELECTING_STRUCTURE_FOR_QUESTION
    return SELECT_GRADE_LEVEL # حالة انتظار اختيار المرحلة للسؤال

def save_question_to_db(context: CallbackContext, user_id):
    """حفظ السؤال المكتمل في قاعدة البيانات."""
    new_question_data = context.user_data.get('new_question')
    grade_id = new_question_data.get('grade_level_id')
    chapter_id = new_question_data.get('chapter_id')
    lesson_id = new_question_data.get('lesson_id')

    if not all([new_question_data, grade_id, chapter_id, lesson_id]):
        logger.error("Missing data to save question.")
        return False, "بيانات السؤال غير مكتملة."

    if QUIZ_DB:
        try:
            question_id = QUIZ_DB.add_question(
                text=new_question_data['text'],
                options=new_question_data['options'],
                correct_answer_index=new_question_data['correct_answer_index'],
                explanation=new_question_data.get('explanation'),
                grade_level_id=grade_id,
                chapter_id=chapter_id,
                lesson_id=lesson_id
            )
            if question_id:
                logger.info(f"Admin {user_id} added question ID {question_id}")
                context.user_data.pop('new_question', None) # مسح بيانات السؤال المؤقتة
                return True, f"✅ تم حفظ السؤال بنجاح (ID: {question_id})."
            else:
                return False, "⚠️ حدث خطأ أثناء حفظ السؤال في قاعدة البيانات."
        except Exception as e:
            logger.error(f"Error saving question to DB: {e}")
            return False, "❌ حدث خطأ غير متوقع أثناء الحفظ. يرجى مراجعة السجلات."
    else:
        logger.error("Cannot save question: QuizDatabase not initialized.")
        return False, "❌ خطأ: قاعدة البيانات غير متاحة."

def delete_question_start(update: Update, context: CallbackContext) -> int:
    """طلب إدخال ID السؤال المراد حذفه."""
    query = update.callback_query
    query.answer()
    user = query.effective_user

    if not is_admin(user.id):
        # ... (نفس التحقق من المسؤول)
        return MAIN_MENU

    try:
        query.edit_message_text("🗑️ أدخل ID السؤال الذي ترغب في حذفه:")
    except Exception as e:
        logger.error(f"Error asking for question ID to delete: {e}")
        
    return DELETING_QUESTION

def delete_question_confirm(update: Update, context: CallbackContext) -> int:
    """حذف السؤال من قاعدة البيانات."""
    user = update.effective_user
    if not is_admin(user.id):
        return MAIN_MENU
        
    question_id_text = update.message.text
    try:
        question_id = int(question_id_text)
    except ValueError:
        update.message.reply_text("⚠️ يجب إدخال رقم ID صحيح. حاول مرة أخرى.")
        return DELETING_QUESTION
        
    if QUIZ_DB:
        try:
            success = QUIZ_DB.delete_question(question_id)
            if success:
                update.message.reply_text(f"✅ تم حذف السؤال (ID: {question_id}) بنجاح.")
                logger.info(f"Admin {user.id} deleted question ID {question_id}")
            else:
                update.message.reply_text(f"⚠️ لم يتم العثور على سؤال بالـ ID {question_id} أو حدث خطأ أثناء الحذف.")
        except Exception as e:
            logger.error(f"Error deleting question ID {question_id}: {e}")
            update.message.reply_text("❌ حدث خطأ غير متوقع. يرجى مراجعة السجلات.")
    else:
        logger.error("Cannot delete question: QuizDatabase not initialized.")
        update.message.reply_text("❌ خطأ: قاعدة البيانات غير متاحة.")
        
    # العودة لقائمة الإدارة
    admin_text = "⚙️ **إدارة البوت**\n\nاختر المهمة التي ترغب في تنفيذها:"
    reply_markup = create_admin_menu_keyboard()
    try:
        update.message.reply_text(admin_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error sending admin menu after delete: {e}")
        
    return ADMIN_MENU

def show_question_start(update: Update, context: CallbackContext) -> int:
    """طلب إدخال ID السؤال المراد عرضه."""
    query = update.callback_query
    query.answer()
    user = query.effective_user

    if not is_admin(user.id):
        # ... (نفس التحقق من المسؤول)
        return MAIN_MENU

    try:
        query.edit_message_text("🔍 أدخل ID السؤال الذي ترغب في عرضه:")
    except Exception as e:
        logger.error(f"Error asking for question ID to show: {e}")
        
    return SHOWING_QUESTION

def show_question_details(update: Update, context: CallbackContext) -> int:
    """عرض تفاصيل السؤال المحدد."""
    user = update.effective_user
    if not is_admin(user.id):
        return MAIN_MENU
        
    question_id_text = update.message.text
    try:
        question_id = int(question_id_text)
    except ValueError:
        update.message.reply_text("⚠️ يجب إدخال رقم ID صحيح. حاول مرة أخرى.")
        return SHOWING_QUESTION
        
    if QUIZ_DB:
        question_data = QUIZ_DB.get_question_by_id(question_id)
        if question_data:
            text = f"**🔍 تفاصيل السؤال (ID: {question_id})**\n\n"
            text += f"**النص:** {process_text_with_chemical_notation(question_data['text'])}\n\n"
            text += "**الخيارات:**\n"
            for i, option in enumerate(question_data['options']):
                prefix = "✅" if i == question_data['correct_answer_index'] else "❌"
                text += f"{prefix} {i+1}. {process_text_with_chemical_notation(option)}\n"
            text += f"\n**الشرح:** {process_text_with_chemical_notation(question_data['explanation'] or 'لا يوجد')}\n"
            # عرض معلومات الهيكل
            structure_info = QUIZ_DB.get_question_structure_info(question_id)
            if structure_info:
                 text += f"\n**المرحلة:** {structure_info['grade_name']}\n"
                 text += f"**الفصل:** {structure_info['chapter_name']}\n"
                 text += f"**الدرس:** {structure_info['lesson_name']}"
            else:
                 text += "\n**الهيكل:** (غير محدد)"
                 
            try:
                update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logger.error(f"Error sending question details for ID {question_id}: {e}")
                update.message.reply_text("حدث خطأ أثناء عرض تفاصيل السؤال.")
        else:
            update.message.reply_text(f"⚠️ لم يتم العثور على سؤال بالـ ID {question_id}.")
    else:
        logger.error("Cannot show question: QuizDatabase not initialized.")
        update.message.reply_text("❌ خطأ: قاعدة البيانات غير متاحة.")
        
    # العودة لقائمة الإدارة
    admin_text = "⚙️ **إدارة البوت**\n\nاختر المهمة التي ترغب في تنفيذها:"
    reply_markup = create_admin_menu_keyboard()
    try:
        update.message.reply_text(admin_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error sending admin menu after show: {e}")
        
    return ADMIN_MENU

# --- وظائف الاختبارات --- 

def quiz_prompt_callback(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار نوع الاختبار (عشوائي، فصل، درس، مرحلة)."""
    query = update.callback_query
    query.answer()
    quiz_type = query.data.replace('quiz_', '').replace('_prompt', '') # random, by_chapter, by_lesson, by_grade, review
    
    context.user_data['quiz_settings'] = {'type': quiz_type}
    
    if quiz_type == 'random':
        # اختبار عشوائي، اطلب عدد الأسئلة والمدة
        # كإصدار مبسط، نبدأ مباشرة بعدد ومدة افتراضيين
        context.user_data['quiz_settings']['num_questions'] = DEFAULT_QUIZ_QUESTIONS
        # عرض خيارات المدة
        duration_text = "⏱️ **اختيار مدة الاختبار العشوائي**\n\nاختر المدة المناسبة:"
        reply_markup = create_quiz_duration_keyboard()
        try:
            query.edit_message_text(duration_text, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error asking for duration (random quiz): {e}")
        return SELECTING_QUIZ_DURATION
        
    elif quiz_type == 'by_grade':
        # اختبار حسب المرحلة، اطلب اختيار المرحلة
        grades_text = "🎓 **اختبار حسب المرحلة الدراسية**\n\nاختر المرحلة الدراسية للاختبار:"
        reply_markup = create_grade_levels_keyboard(for_quiz=True, context=context)
        if not reply_markup:
            try:
                query.edit_message_text("⚠️ لا توجد مراحل دراسية متاحة للاختبار.", reply_markup=create_quiz_menu_keyboard())
            except Exception as e:
                logger.error(f"Error sending no grades message (quiz): {e}")
            return QUIZ_MENU
        try:
            query.edit_message_text(grades_text, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error asking for grade level (quiz): {e}")
        return SELECT_GRADE_LEVEL_FOR_QUIZ
        
    elif quiz_type == 'by_chapter':
        # اختبار حسب الفصل، اطلب اختيار المرحلة أولاً
        context.user_data['quiz_settings']['sub_type'] = 'chapter'
        grades_text = "📄 **اختبار حسب الفصل**\n\nاختر المرحلة الدراسية أولاً:"
        reply_markup = create_grade_levels_keyboard(for_quiz=True, context=context)
        if not reply_markup:
            # ... (نفس معالجة عدم وجود مراحل)
            return QUIZ_MENU
        try:
            query.edit_message_text(grades_text, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error asking for grade level (chapter quiz): {e}")
        return SELECT_GRADE_LEVEL_FOR_QUIZ # نفس الحالة، لكن السياق مختلف
        
    elif quiz_type == 'by_lesson':
        # اختبار حسب الدرس، اطلب اختيار المرحلة أولاً
        context.user_data['quiz_settings']['sub_type'] = 'lesson'
        grades_text = "📝 **اختبار حسب الدرس**\n\nاختر المرحلة الدراسية أولاً:"
        reply_markup = create_grade_levels_keyboard(for_quiz=True, context=context)
        if not reply_markup:
            # ... (نفس معالجة عدم وجود مراحل)
            return QUIZ_MENU
        try:
            query.edit_message_text(grades_text, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error asking for grade level (lesson quiz): {e}")
        return SELECT_GRADE_LEVEL_FOR_QUIZ # نفس الحالة، لكن السياق مختلف
        
    elif quiz_type == 'review':
        # مراجعة الأخطاء
        user_id = query.effective_user.id
        if QUIZ_DB:
            incorrect_questions = QUIZ_DB.get_incorrectly_answered_questions(user_id)
            if not incorrect_questions:
                try:
                    query.edit_message_text("🎉 لا توجد أسئلة أخطأت بها لمراجعتها!", reply_markup=create_quiz_menu_keyboard())
                except Exception as e:
                    logger.error(f"Error sending no review questions message: {e}")
                return QUIZ_MENU
            
            context.user_data['quiz_settings'] = {
                'type': 'review',
                'questions': incorrect_questions,
                'num_questions': len(incorrect_questions)
            }
            # عرض خيارات المدة للمراجعة
            duration_text = "⏱️ **اختيار مدة مراجعة الأخطاء**\n\nاختر المدة المناسبة:"
            reply_markup = create_quiz_duration_keyboard()
            try:
                query.edit_message_text(duration_text, reply_markup=reply_markup)
            except Exception as e:
                logger.error(f"Error asking for duration (review quiz): {e}")
            return SELECTING_QUIZ_DURATION
        else:
            logger.error("Cannot start review quiz: QuizDatabase not initialized.")
            try:
                query.edit_message_text("❌ خطأ: قاعدة البيانات غير متاحة لبدء المراجعة.", reply_markup=create_quiz_menu_keyboard())
            except Exception as e:
                logger.error(f"Error sending DB error message (review): {e}")
            return QUIZ_MENU
            
    else:
        logger.warning(f"Unknown quiz type selected: {quiz_type}")
        try:
            query.edit_message_text("⚠️ نوع اختبار غير معروف.", reply_markup=create_quiz_menu_keyboard())
        except Exception as e:
            logger.error(f"Error sending unknown quiz type message: {e}")
        return QUIZ_MENU

def select_structure_for_quiz_callback(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار المرحلة/الفصل/الدرس للاختبار أو للسؤال الجديد."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.effective_user.id
    
    # تحديد ما إذا كان السياق لإضافة سؤال أو لبدء اختبار
    is_adding_question = context.user_data.get('admin_context', '').startswith('add_question')
    
    if data.startswith('select_grade_quiz_') or data.startswith('select_grade_admin_'):
        # اختيار المرحلة (للاختبار أو لإضافة سؤال)
        try:
            if data == 'select_grade_quiz_all':
                 grade_id = 'all'
                 grade_name = "جميع المراحل (تحصيلي عام)"
            elif data.startswith('select_grade_quiz_'):
                 grade_id = int(data.replace('select_grade_quiz_', ''))
            else: # select_grade_admin_
                 grade_id = int(data.replace('select_grade_admin_', ''))
                 # هنا يجب أن يكون السياق لإضافة سؤال
                 if not is_adding_question:
                      logger.warning(f"Admin grade selection outside add question context: {data}")
                      return ADMIN_MENU # أو حالة مناسبة
                 context.user_data['new_question']['grade_level_id'] = grade_id
                 # طلب اختيار الفصل التالي
                 chapters_text = f"📚 اختر الفصل الذي ينتمي إليه السؤال (المرحلة المحددة):"
                 reply_markup = create_chapters_keyboard(grade_id, for_lesson=True, context=context) # استخدام for_lesson=True لتضمين السياق الصحيح
                 if not reply_markup:
                     try:
                         query.edit_message_text("⚠️ لا توجد فصول لهذه المرحلة. يرجى إضافة فصول أولاً.", reply_markup=create_admin_menu_keyboard())
                     except Exception as e:
                         logger.error(f"Error sending no chapters message (add question): {e}")
                     return ADMIN_MENU
                 try:
                     query.edit_message_text(chapters_text, reply_markup=reply_markup)
                 except Exception as e:
                     logger.error(f"Error asking for chapter (add question): {e}")
                 return SELECT_CHAPTER_FOR_LESSON # حالة انتظار اختيار الفصل للسؤال
                 
            # --- استمرار منطق الاختبار --- 
            if grade_id == 'all':
                # اختبار تحصيلي عام
                context.user_data['quiz_settings']['grade_id'] = 'all'
                context.user_data['quiz_settings']['num_questions'] = DEFAULT_QUIZ_QUESTIONS # أو عدد آخر مناسب للتحصيلي
                # عرض خيارات المدة
                duration_text = f"⏱️ **اختيار مدة الاختبار التحصيلي العام**\n\nاختر المدة المناسبة:"
                reply_markup = create_quiz_duration_keyboard()
                try:
                    query.edit_message_text(duration_text, reply_markup=reply_markup)
                except Exception as e:
                    logger.error(f"Error asking for duration (general quiz): {e}")
                return SELECTING_QUIZ_DURATION
            else:
                # تم اختيار مرحلة محددة
                context.user_data['quiz_settings']['grade_id'] = grade_id
                quiz_sub_type = context.user_data['quiz_settings'].get('sub_type')
                
                if quiz_sub_type == 'chapter':
                    # طلب اختيار الفصل
                    chapters_text = f"📄 **اختبار حسب الفصل**\n\nاختر الفصل للاختبار (المرحلة المحددة):"
                    reply_markup = create_chapters_keyboard(grade_id, for_quiz=True, context=context)
                    if not reply_markup:
                        try:
                            query.edit_message_text("⚠️ لا توجد فصول متاحة للاختبار في هذه المرحلة.", reply_markup=create_quiz_menu_keyboard())
                        except Exception as e:
                            logger.error(f"Error sending no chapters message (quiz): {e}")
                        return QUIZ_MENU
                    try:
                        query.edit_message_text(chapters_text, reply_markup=reply_markup)
                    except Exception as e:
                        logger.error(f"Error asking for chapter (quiz): {e}")
                    return SELECT_CHAPTER_FOR_QUIZ
                    
                elif quiz_sub_type == 'lesson':
                    # طلب اختيار الفصل أولاً
                    chapters_text = f"📝 **اختبار حسب الدرس**\n\nاختر الفصل أولاً (المرحلة المحددة):"
                    reply_markup = create_chapters_keyboard(grade_id, for_lesson=True, context=context)
                    if not reply_markup:
                        # ... (نفس معالجة عدم وجود فصول)
                        return QUIZ_MENU
                    try:
                        query.edit_message_text(chapters_text, reply_markup=reply_markup)
                    except Exception as e:
                        logger.error(f"Error asking for chapter (lesson quiz): {e}")
                    return SELECT_CHAPTER_FOR_LESSON # حالة انتظار اختيار الفصل للدرس
                    
                else: # اختبار حسب المرحلة مباشرة
                    context.user_data['quiz_settings']['num_questions'] = DEFAULT_QUIZ_QUESTIONS
                    # عرض خيارات المدة
                    duration_text = f"⏱️ **اختيار مدة الاختبار للمرحلة المحددة**\n\nاختر المدة المناسبة:"
                    reply_markup = create_quiz_duration_keyboard()
                    try:
                        query.edit_message_text(duration_text, reply_markup=reply_markup)
                    except Exception as e:
                        logger.error(f"Error asking for duration (grade quiz): {e}")
                    return SELECTING_QUIZ_DURATION
                    
        except ValueError:
            logger.error(f"Invalid grade_id received: {data}")
            return QUIZ_MENU # أو حالة مناسبة للخطأ

    elif data.startswith('select_chapter_quiz_') or data.startswith('select_chapter_lesson_') or data.startswith('select_chapter_for_lesson_admin_'):
        # اختيار الفصل (للاختبار أو للدرس أو لإضافة سؤال)
        try:
            if data.startswith('select_chapter_quiz_'):
                chapter_id = int(data.replace('select_chapter_quiz_', ''))
                context.user_data['quiz_settings']['chapter_id'] = chapter_id
                context.user_data['quiz_settings']['num_questions'] = DEFAULT_QUIZ_QUESTIONS
                # عرض خيارات المدة
                duration_text = f"⏱️ **اختيار مدة الاختبار للفصل المحدد**\n\nاختر المدة المناسبة:"
                reply_markup = create_quiz_duration_keyboard()
                try:
                    query.edit_message_text(duration_text, reply_markup=reply_markup)
                except Exception as e:
                    logger.error(f"Error asking for duration (chapter quiz): {e}")
                return SELECTING_QUIZ_DURATION
                
            elif data.startswith('select_chapter_lesson_'):
                # اختيار الفصل لاختبار الدرس
                chapter_id = int(data.replace('select_chapter_lesson_', ''))
                context.user_data['quiz_settings']['chapter_id'] = chapter_id
                # طلب اختيار الدرس
                lessons_text = f"📝 **اختبار حسب الدرس**\n\nاختر الدرس للاختبار (الفصل المحدد):"
                reply_markup = create_lessons_keyboard(chapter_id, for_quiz=True, context=context)
                if not reply_markup:
                    try:
                        query.edit_message_text("⚠️ لا توجد دروس متاحة للاختبار في هذا الفصل.", reply_markup=create_quiz_menu_keyboard())
                    except Exception as e:
                        logger.error(f"Error sending no lessons message (quiz): {e}")
                    return QUIZ_MENU
                try:
                    query.edit_message_text(lessons_text, reply_markup=reply_markup)
                except Exception as e:
                    logger.error(f"Error asking for lesson (quiz): {e}")
                return SELECT_LESSON_FOR_QUIZ
                
            else: # select_chapter_for_lesson_admin_
                # اختيار الفصل لإضافة سؤال
                chapter_id = int(data.replace('select_chapter_for_lesson_admin_', ''))
                if not is_adding_question:
                     logger.warning(f"Admin chapter selection outside add question context: {data}")
                     return ADMIN_MENU
                context.user_data['new_question']['chapter_id'] = chapter_id
                # طلب اختيار الدرس التالي
                lessons_text = f"📝 اختر الدرس الذي ينتمي إليه السؤال (الفصل المحدد):"
                reply_markup = create_lessons_keyboard(chapter_id, context=context) # استخدام لوحة مفاتيح الدروس للإدارة
                if not reply_markup:
                    try:
                        # إذا لم تكن هناك دروس، ربما نسمح بحفظ السؤال على مستوى الفصل؟
                        # أو نجبر على إضافة درس أولاً
                        query.edit_message_text("⚠️ لا توجد دروس لهذا الفصل. يرجى إضافة دروس أولاً.", reply_markup=create_admin_menu_keyboard())
                    except Exception as e:
                        logger.error(f"Error sending no lessons message (add question): {e}")
                    return ADMIN_MENU
                try:
                    query.edit_message_text(lessons_text, reply_markup=reply_markup)
                except Exception as e:
                    logger.error(f"Error asking for lesson (add question): {e}")
                return SELECT_LESSON_FOR_QUIZ # استخدام نفس الحالة لانتظار اختيار الدرس للسؤال
                
        except ValueError:
            logger.error(f"Invalid chapter_id received: {data}")
            return QUIZ_MENU

    elif data.startswith('select_lesson_quiz_') or data.startswith('select_lesson_admin_'):
        # اختيار الدرس (للاختبار أو لإضافة سؤال)
        try:
            if data.startswith('select_lesson_quiz_'):
                lesson_id = int(data.replace('select_lesson_quiz_', ''))
                context.user_data['quiz_settings']['lesson_id'] = lesson_id
                context.user_data['quiz_settings']['num_questions'] = DEFAULT_QUIZ_QUESTIONS
                # عرض خيارات المدة
                duration_text = f"⏱️ **اختيار مدة الاختبار للدرس المحدد**\n\nاختر المدة المناسبة:"
                reply_markup = create_quiz_duration_keyboard()
                try:
                    query.edit_message_text(duration_text, reply_markup=reply_markup)
                except Exception as e:
                    logger.error(f"Error asking for duration (lesson quiz): {e}")
                return SELECTING_QUIZ_DURATION
            else: # select_lesson_admin_
                # اختيار الدرس لإضافة سؤال
                lesson_id = int(data.replace('select_lesson_admin_', ''))
                if not is_adding_question:
                     logger.warning(f"Admin lesson selection outside add question context: {data}")
                     return ADMIN_MENU
                context.user_data['new_question']['lesson_id'] = lesson_id
                # الآن لدينا كل المعلومات، يمكننا حفظ السؤال
                success, message = save_question_to_db(context, user_id)
                try:
                    query.edit_message_text(message, reply_markup=create_admin_menu_keyboard())
                except Exception as e:
                    logger.error(f"Error sending save question result message: {e}")
                return ADMIN_MENU # العودة لقائمة الإدارة بعد الحفظ
                
        except ValueError:
            logger.error(f"Invalid lesson_id received: {data}")
            return QUIZ_MENU
            
    elif data.startswith('select_chapter_admin_'):
         # اختيار فصل للإدارة (عرض الدروس أو إضافة درس)
         try:
             chapter_id = int(data.replace('select_chapter_admin_', ''))
             context.user_data['selected_chapter_id'] = chapter_id
             context.user_data['admin_context'] = 'manage_lessons' # السياق الآن إدارة الدروس لهذا الفصل
             
             lesson_text = f"📝 **إدارة الدروس للفصل المحدد**\n\nاختر الدرس للإدارة أو قم بإضافة درس جديد:"
             reply_markup = create_lessons_keyboard(chapter_id, context=context)
             # إضافة زر إضافة درس جديد
             if reply_markup:
                  reply_markup.inline_keyboard.insert(0, [InlineKeyboardButton("➕ إضافة درس جديد", callback_data='admin_add_lesson_prompt')])
             else:
                 keyboard = [[InlineKeyboardButton("➕ إضافة درس جديد", callback_data='admin_add_lesson_prompt')], [InlineKeyboardButton("🔙 العودة لاختيار الفصل", callback_data='admin_manage_chapters')]]
                 reply_markup = InlineKeyboardMarkup(keyboard)
                 
             try:
                 query.edit_message_text(lesson_text, reply_markup=reply_markup)
             except Exception as e:
                 logger.error(f"Error sending manage lessons menu: {e}")
                 
             return ADMIN_LESSON_MENU
         except ValueError:
             logger.error(f"Invalid chapter_id for admin: {data}")
             return ADMIN_MENU
             
    elif data.startswith('select_lesson_admin_'):
         # اختيار درس للإدارة (عرض الأسئلة أو تعديل الدرس - لاحقاً)
         try:
             lesson_id = int(data.replace('select_lesson_admin_', ''))
             context.user_data['selected_lesson_id'] = lesson_id
             # حالياً لا يوجد إجراء محدد لإدارة الدرس، نكتفي بعرض رسالة
             lesson_info = QUIZ_DB.get_lesson_info(lesson_id) # نفترض وجود وظيفة للحصول على اسم الدرس
             lesson_name = lesson_info['name'] if lesson_info else f"(ID: {lesson_id})"
             try:
                 query.edit_message_text(f"تم اختيار الدرس '{lesson_name}'.\n(سيتم إضافة خيارات إدارة الدرس لاحقاً)",
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الدروس", callback_data='select_chapter_admin_' + str(context.user_data.get('selected_chapter_id')))]]))
             except Exception as e:
                 logger.error(f"Error sending lesson selected message: {e}")
             return ADMIN_LESSON_MENU
         except ValueError:
             logger.error(f"Invalid lesson_id for admin: {data}")
             return ADMIN_MENU
             
    # --- اختيار المرحلة لإدارة الفصول (من manage_chapters_callback) ---
    elif data.startswith('select_grade_for_chapter_'):
        try:
            grade_id = int(data.replace('select_grade_for_chapter_', ''))
            context.user_data['selected_grade_id'] = grade_id # تخزين للسياق التالي
            context.user_data['admin_context'] = 'manage_chapters' # السياق الآن إدارة الفصول لهذه المرحلة
            
            chapter_text = f"📚 **إدارة الفصول للمرحلة المحددة**\n\nاختر الفصل للإدارة أو قم بإضافة فصل جديد:"
            reply_markup = create_chapters_keyboard(grade_id, context=context)
            # إضافة زر إضافة فصل جديد
            if reply_markup:
                 reply_markup.inline_keyboard.insert(0, [InlineKeyboardButton("➕ إضافة فصل جديد", callback_data='admin_add_chapter_prompt')])
            else:
                keyboard = [[InlineKeyboardButton("➕ إضافة فصل جديد", callback_data='admin_add_chapter_prompt')], [InlineKeyboardButton("🔙 العودة لاختيار المرحلة", callback_data='admin_manage_chapters')]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
            try:
                query.edit_message_text(chapter_text, reply_markup=reply_markup)
            except Exception as e:
                logger.error(f"Error sending manage chapters menu: {e}")
                
            return ADMIN_CHAPTER_MENU
        except ValueError:
            logger.error(f"Invalid grade_id for chapter management: {data}")
            return ADMIN_MENU
            
    # --- اختيار المرحلة لإدارة الدروس (من manage_lessons_callback) ---
    elif data.startswith('select_grade_for_lesson_'): # يجب أن يكون هذا مختلفاً عن select_grade_for_chapter_
        try:
            grade_id = int(data.replace('select_grade_for_lesson_', ''))
            context.user_data['selected_grade_id'] = grade_id # تخزين للسياق التالي
            context.user_data['admin_context'] = 'add_lesson' # السياق الآن اختيار فصل لإضافة درس
            
            chapters_text = f"📝 **إدارة الدروس**\n\nاختر الفصل الذي ترغب في إدارة دروسه (المرحلة المحددة):"
            # نستخدم for_lesson=True لتضمين السياق الصحيح في أزرار الفصول
            reply_markup = create_chapters_keyboard(grade_id, for_lesson=True, context=context)
            
            if not reply_markup:
                try:
                    query.edit_message_text("⚠️ لا توجد فصول لإدارة دروسها في هذه المرحلة. قم بإضافة فصول أولاً.", 
                                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لاختيار المرحلة", callback_data='admin_manage_lessons')]]))
                except Exception as e:
                    logger.error(f"Error sending no chapters message (lessons admin): {e}")
                return ADMIN_LESSON_MENU
                
            try:
                query.edit_message_text(chapters_text, reply_markup=reply_markup)
            except Exception as e:
                logger.error(f"Error sending select chapter for lesson menu: {e}")
                
            return SELECT_CHAPTER_FOR_LESSON_ADMIN # حالة انتظار اختيار الفصل لإدارة الدروس
        except ValueError:
            logger.error(f"Invalid grade_id for lesson management: {data}")
            return ADMIN_MENU
            
    # --- اختيار الفصل لإدارة الدروس (من الحالة السابقة) ---
    elif data.startswith('select_chapter_for_lesson_admin_'):
        try:
            chapter_id = int(data.replace('select_chapter_for_lesson_admin_', ''))
            context.user_data['selected_chapter_id'] = chapter_id # تخزين للسياق التالي
            context.user_data['admin_context'] = 'manage_lessons' # السياق الآن إدارة الدروس لهذا الفصل
            
            lesson_text = f"📝 **إدارة الدروس للفصل المحدد**\n\nاختر الدرس للإدارة أو قم بإضافة درس جديد:"
            reply_markup = create_lessons_keyboard(chapter_id, context=context)
            # إضافة زر إضافة درس جديد
            if reply_markup:
                 reply_markup.inline_keyboard.insert(0, [InlineKeyboardButton("➕ إضافة درس جديد", callback_data='admin_add_lesson_prompt')])
            else:
                keyboard = [[InlineKeyboardButton("➕ إضافة درس جديد", callback_data='admin_add_lesson_prompt')], [InlineKeyboardButton("🔙 العودة لاختيار الفصل", callback_data='admin_manage_lessons')]] # يجب أن نعود لاختيار الفصل للمرحلة الصحيحة
                # نحتاج لمعرف المرحلة هنا للعودة الصحيحة
                # كحل مؤقت، نعود لقائمة إدارة الدروس العامة
                keyboard[1][0] = InlineKeyboardButton("🔙 العودة لقائمة إدارة الدروس", callback_data='admin_manage_lessons')
                reply_markup = InlineKeyboardMarkup(keyboard)
                
            try:
                query.edit_message_text(lesson_text, reply_markup=reply_markup)
            except Exception as e:
                logger.error(f"Error sending manage lessons menu for chapter: {e}")
                
            return ADMIN_LESSON_MENU
        except ValueError:
            logger.error(f"Invalid chapter_id for lesson management admin: {data}")
            return ADMIN_MENU
            
    else:
        logger.warning(f"Unhandled callback data in select_structure_for_quiz_callback: {data}")
        return ConversationHandler.END # أو حالة مناسبة

def select_quiz_duration_callback(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار مدة الاختبار وبدء الاختبار."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.effective_user.id
    chat_id = query.effective_chat.id
    
    try:
        duration_minutes = int(data.replace('quiz_duration_', ''))
    except ValueError:
        logger.error(f"Invalid quiz duration data: {data}")
        try:
            query.edit_message_text("⚠️ حدث خطأ في تحديد مدة الاختبار.", reply_markup=create_quiz_menu_keyboard())
        except Exception as e:
            logger.error(f"Error sending duration error message: {e}")
        return QUIZ_MENU
        
    context.user_data['quiz_settings']['duration_minutes'] = duration_minutes
    quiz_settings = context.user_data['quiz_settings']
    quiz_type = quiz_settings['type']
    num_questions = quiz_settings.get('num_questions', DEFAULT_QUIZ_QUESTIONS)
    
    if not QUIZ_DB:
        logger.error("Cannot start quiz: QuizDatabase not initialized.")
        try:
            query.edit_message_text("❌ خطأ: قاعدة البيانات غير متاحة لبدء الاختبار.", reply_markup=create_quiz_menu_keyboard())
        except Exception as e:
            logger.error(f"Error sending DB error message (start quiz): {e}")
        return QUIZ_MENU

    questions = []
    if quiz_type == 'random':
        questions = QUIZ_DB.get_random_questions(num_questions)
    elif quiz_type == 'by_grade':
        grade_id = quiz_settings.get('grade_id')
        if grade_id == 'all': # اختبار تحصيلي عام
             questions = QUIZ_DB.get_random_questions(num_questions) # حالياً نفس العشوائي
             # لاحقاً: يمكن تحسين هذا لجلب أسئلة متنوعة من جميع المراحل
        elif grade_id:
             questions = QUIZ_DB.get_questions_by_grade(grade_id, num_questions)
    elif quiz_type == 'by_chapter':
        chapter_id = quiz_settings.get('chapter_id')
        if chapter_id:
            questions = QUIZ_DB.get_questions_by_chapter(chapter_id, num_questions)
    elif quiz_type == 'by_lesson':
        lesson_id = quiz_settings.get('lesson_id')
        if lesson_id:
            questions = QUIZ_DB.get_questions_by_lesson(lesson_id, num_questions)
    elif quiz_type == 'review':
        questions = quiz_settings.get('questions', []) # الأسئلة تم جلبها مسبقاً
        random.shuffle(questions) # خلط ترتيب أسئلة المراجعة
        num_questions = len(questions) # عدد الأسئلة هو عدد الأخطاء
        quiz_settings['num_questions'] = num_questions

    if not questions:
        error_message = "⚠️ لم يتم العثور على أسئلة تطابق معايير الاختبار المحددة."
        if quiz_type == 'review':
             error_message = "🎉 لا توجد أسئلة أخطأت بها لمراجعتها!"
        try:
            query.edit_message_text(error_message, reply_markup=create_quiz_menu_keyboard())
        except Exception as e:
            logger.error(f"Error sending no questions found message: {e}")
        return QUIZ_MENU

    # بدء الاختبار في قاعدة البيانات
    quiz_id = QUIZ_DB.start_quiz(user_id, quiz_type, quiz_settings.get('grade_id'), quiz_settings.get('chapter_id'), quiz_settings.get('lesson_id'), num_questions, duration_minutes)
    
    if not quiz_id:
        logger.error(f"Failed to start quiz in database for user {user_id}")
        try:
            query.edit_message_text("❌ حدث خطأ أثناء بدء الاختبار. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_menu_keyboard())
        except Exception as e:
            logger.error(f"Error sending quiz start DB error message: {e}")
        return QUIZ_MENU

    # تخزين بيانات الاختبار في user_data
    context.user_data['quiz'] = {
        'id': quiz_id,
        'questions': questions,
        'current_question_index': 0,
        'score': 0,
        'start_time': time.time(),
        'duration_minutes': duration_minutes
    }
    context.user_data['conversation_state'] = 'in_quiz' # حالة جديدة للإشارة إلى أن المستخدم في اختبار

    # إعداد مؤقت الاختبار الكلي (إذا كانت المدة محددة)
    quiz_timer_job = set_quiz_timer(context, chat_id, user_id, quiz_id, duration_minutes)
    context.user_data['quiz']['timer_job'] = quiz_timer_job # تخزين المؤقت للإلغاء لاحقاً

    # إرسال رسالة بدء الاختبار
    quiz_start_text = f"🚀 **بدء الاختبار!**\n\n"
    quiz_start_text += f"📝 النوع: {quiz_type_to_arabic(quiz_type)}\n"
    if quiz_settings.get('grade_id') and quiz_settings['grade_id'] != 'all':
        grade_info = QUIZ_DB.get_grade_info(quiz_settings['grade_id'])
        quiz_start_text += f"🎓 المرحلة: {grade_info['name'] if grade_info else 'غير محدد'}\n"
    if quiz_settings.get('chapter_id'):
        chapter_info = QUIZ_DB.get_chapter_info(quiz_settings['chapter_id'])
        quiz_start_text += f"📚 الفصل: {chapter_info['name'] if chapter_info else 'غير محدد'}\n"
    if quiz_settings.get('lesson_id'):
        lesson_info = QUIZ_DB.get_lesson_info(quiz_settings['lesson_id'])
        quiz_start_text += f"📝 الدرس: {lesson_info['name'] if lesson_info else 'غير محدد'}\n"
        
    quiz_start_text += f"🔢 عدد الأسئلة: {num_questions}\n"
    if duration_minutes > 0:
        quiz_start_text += f"⏱️ المدة: {duration_minutes} دقائق\n"
    else:
        quiz_start_text += "⏱️ المدة: مفتوحة\n"
        
    quiz_start_text += "\nبالتوفيق!"

    try:
        # حذف الرسالة السابقة (اختيار المدة) وإرسال رسالة البدء
        query.delete_message()
        context.bot.send_message(chat_id=chat_id, text=quiz_start_text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error sending quiz start message: {e}")

    # عرض السؤال الأول
    show_next_question_internal(context, chat_id, user_id)
    
    return TAKING_QUIZ

def quiz_type_to_arabic(quiz_type):
    """تحويل نوع الاختبار إلى نص عربي."""
    types = {
        'random': "عشوائي",
        'by_grade': "حسب المرحلة الدراسية",
        'by_chapter': "حسب الفصل",
        'by_lesson': "حسب الدرس",
        'review': "مراجعة الأخطاء"
    }
    return types.get(quiz_type, quiz_type)

def show_next_question_internal(context: CallbackContext, chat_id, user_id):
    """عرض السؤال التالي (وظيفة داخلية)."""
    user_data = context.dispatcher.user_data.get(user_id, {})
    if user_data.get('conversation_state') != 'in_quiz':
        logger.warning(f"show_next_question_internal called but user {user_id} is not in quiz state.")
        return
        
    quiz_data = user_data.get('quiz')
    if not quiz_data:
        logger.error(f"show_next_question_internal called but no quiz data found for user {user_id}.")
        return
        
    current_index = quiz_data['current_question_index']
    questions = quiz_data['questions']
    quiz_id = quiz_data['id']

    # إزالة مؤقت السؤال السابق (إذا كان موجوداً)
    remove_question_timer(context)

    if current_index < len(questions):
        question = questions[current_index]
        question_text = process_text_with_chemical_notation(question['text'])
        options = [process_text_with_chemical_notation(opt) for opt in question['options']]
        
        keyboard = []
        for i, option in enumerate(options):
            keyboard.append([InlineKeyboardButton(option, callback_data=f'quiz_answer_{i}')])
        
        # إضافة زر إنهاء الاختبار
        keyboard.append([InlineKeyboardButton("🛑 إنهاء الاختبار", callback_data='quiz_end')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        question_header = f"**❓ السؤال {current_index + 1} من {len(questions)}**\n\n"
        full_text = question_header + question_text
        
        try:
            # التحقق مما إذا كانت هناك رسالة سابقة لتعديلها
            last_message_id = quiz_data.get('last_question_message_id')
            if last_message_id:
                 context.bot.edit_message_text(
                     chat_id=chat_id,
                     message_id=last_message_id,
                     text=full_text,
                     reply_markup=reply_markup,
                     parse_mode=ParseMode.MARKDOWN
                 )
            else:
                 message = context.bot.send_message(
                     chat_id=chat_id,
                     text=full_text,
                     reply_markup=reply_markup,
                     parse_mode=ParseMode.MARKDOWN
                 )
                 quiz_data['last_question_message_id'] = message.message_id
                 
            # إعداد مؤقت السؤال التالي
            question_timer_job = set_question_timer(context, chat_id, user_id, quiz_id)
            quiz_data['question_timer_job'] = question_timer_job
                 
        except BadRequest as e:
            if "Message is not modified" in str(e):
                pass # تجاهل الخطأ إذا لم يتم تعديل الرسالة
            else:
                logger.error(f"Error sending/editing question {current_index + 1}: {e}")
                # محاولة إرسال رسالة جديدة إذا فشل التعديل
                try:
                    message = context.bot.send_message(chat_id=chat_id, text=full_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                    quiz_data['last_question_message_id'] = message.message_id
                    # إعداد مؤقت السؤال التالي
                    question_timer_job = set_question_timer(context, chat_id, user_id, quiz_id)
                    quiz_data['question_timer_job'] = question_timer_job
                except Exception as send_error:
                    logger.error(f"Failed to send new message for question {current_index + 1}: {send_error}")
                    # قد نحتاج لإنهاء الاختبار هنا إذا فشل إرسال السؤال
                    end_quiz_internal(context, chat_id, user_id, "حدث خطأ فني ولم نتمكن من عرض السؤال التالي.")
        except Exception as e:
            logger.error(f"Error sending/editing question {current_index + 1}: {e}")
            # محاولة إرسال رسالة جديدة إذا فشل التعديل
            try:
                message = context.bot.send_message(chat_id=chat_id, text=full_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                quiz_data['last_question_message_id'] = message.message_id
                # إعداد مؤقت السؤال التالي
                question_timer_job = set_question_timer(context, chat_id, user_id, quiz_id)
                quiz_data['question_timer_job'] = question_timer_job
            except Exception as send_error:
                logger.error(f"Failed to send new message for question {current_index + 1}: {send_error}")
                # قد نحتاج لإنهاء الاختبار هنا إذا فشل إرسال السؤال
                end_quiz_internal(context, chat_id, user_id, "حدث خطأ فني ولم نتمكن من عرض السؤال التالي.")
    else:
        # انتهت الأسئلة
        end_quiz_internal(context, chat_id, user_id)

def quiz_answer_callback(update: Update, context: CallbackContext) -> int:
    """معالجة إجابة المستخدم على سؤال الاختبار."""
    query = update.callback_query
    query.answer()
    user_id = query.effective_user.id
    chat_id = query.effective_chat.id
    
    user_data = context.user_data
    if user_data.get('conversation_state') != 'in_quiz':
        logger.warning(f"quiz_answer_callback called but user {user_id} is not in quiz state.")
        # قد نرغب في إرسال رسالة للمستخدم هنا
        try:
            query.edit_message_text("⚠️ يبدو أن الاختبار قد انتهى أو تم إلغاؤه.")
        except Exception as e:
            logger.error(f"Error sending quiz ended message: {e}")
        return QUIZ_MENU
        
    quiz_data = user_data.get('quiz')
    if not quiz_data:
        logger.error(f"quiz_answer_callback called but no quiz data found for user {user_id}.")
        # ... (معالجة الخطأ)
        return QUIZ_MENU

    try:
        selected_option_index = int(query.data.replace('quiz_answer_', ''))
    except ValueError:
        logger.error(f"Invalid answer callback data: {query.data}")
        return TAKING_QUIZ # البقاء في نفس الحالة

    current_index = quiz_data['current_question_index']
    questions = quiz_data['questions']
    quiz_id = quiz_data['id']

    if current_index < len(questions):
        question = questions[current_index]
        correct_answer_index = question['correct_answer_index']
        question_id = question['id']
        is_correct = (selected_option_index == correct_answer_index)

        if is_correct:
            quiz_data['score'] += 1
            feedback_text = "✅ إجابة صحيحة!"
        else:
            feedback_text = f"❌ إجابة خاطئة. الإجابة الصحيحة هي الخيار رقم {correct_answer_index + 1}."
            if question.get('explanation'):
                feedback_text += f"\n💡 **الشرح:** {process_text_with_chemical_notation(question['explanation'])}"
        
        # تسجيل الإجابة في قاعدة البيانات
        if QUIZ_DB:
            QUIZ_DB.record_answer(quiz_id, question_id, selected_option_index, is_correct)
        else:
            logger.error("Cannot record answer: QuizDatabase not initialized.")

        # إزالة مؤقت السؤال الحالي
        remove_question_timer(context)

        # تعديل رسالة السؤال لإظهار التغذية الراجعة (بدون أزرار)
        question_text = process_text_with_chemical_notation(question['text'])
        question_header = f"**❓ السؤال {current_index + 1} من {len(questions)}**\n\n"
        full_text = question_header + question_text + "\n\n" + feedback_text
        last_message_id = quiz_data.get('last_question_message_id')
        
        try:
            if last_message_id:
                 context.bot.edit_message_text(
                     chat_id=chat_id,
                     message_id=last_message_id,
                     text=full_text,
                     reply_markup=None, # إزالة الأزرار
                     parse_mode=ParseMode.MARKDOWN
                 )
                 # مسح معرف الرسالة لمنع التعديل مرة أخرى
                 quiz_data['last_question_message_id'] = None 
            else:
                 # إذا لم نتمكن من التعديل، نرسل رسالة جديدة
                 context.bot.send_message(chat_id=chat_id, text=full_text, parse_mode=ParseMode.MARKDOWN)
                 
        except BadRequest as e:
            if "Message to edit not found" in str(e) or "message can't be edited" in str(e):
                 logger.warning(f"Could not edit message {last_message_id} for feedback, sending new message.")
                 try:
                     context.bot.send_message(chat_id=chat_id, text=full_text, parse_mode=ParseMode.MARKDOWN)
                 except Exception as send_error:
                     logger.error(f"Failed to send new feedback message: {send_error}")
            else:
                 logger.error(f"Error editing message for feedback: {e}")
                 # محاولة إرسال رسالة جديدة كحل بديل
                 try:
                     context.bot.send_message(chat_id=chat_id, text=full_text, parse_mode=ParseMode.MARKDOWN)
                 except Exception as send_error:
                     logger.error(f"Failed to send new feedback message: {send_error}")
        except Exception as e:
            logger.error(f"Error editing message for feedback: {e}")
            # محاولة إرسال رسالة جديدة كحل بديل
            try:
                context.bot.send_message(chat_id=chat_id, text=full_text, parse_mode=ParseMode.MARKDOWN)
            except Exception as send_error:
                logger.error(f"Failed to send new feedback message: {send_error}")

        # الانتقال للسؤال التالي
        quiz_data['current_question_index'] += 1
        
        # إضافة تأخير بسيط قبل عرض السؤال التالي (اختياري)
        # time.sleep(2)
        
        # عرض السؤال التالي
        show_next_question_internal(context, chat_id, user_id)
        
    else:
        logger.warning(f"Received answer callback but quiz index {current_index} is out of bounds.")
        # قد يكون الاختبار انتهى للتو
        end_quiz_internal(context, chat_id, user_id)

    return TAKING_QUIZ

def end_quiz_callback(update: Update, context: CallbackContext) -> int:
    """معالجة طلب المستخدم لإنهاء الاختبار."""
    query = update.callback_query
    query.answer()
    user_id = query.effective_user.id
    chat_id = query.effective_chat.id
    
    logger.info(f"User {user_id} requested to end the quiz.")
    end_quiz_internal(context, chat_id, user_id, "تم إنهاء الاختبار بناءً على طلبك.")
    return QUIZ_MENU

def end_quiz_timeout(context: CallbackContext):
    """يتم استدعاؤها بواسطة مؤقت الاختبار لإنهاء الاختبار تلقائياً."""
    job_context = context.job.context
    chat_id = job_context['chat_id']
    user_id = job_context['user_id']
    quiz_id = job_context['quiz_id']
    
    # التحقق مما إذا كان الاختبار لا يزال نشطاً لهذا المستخدم
    user_data = context.dispatcher.user_data.get(user_id, {})
    if user_data.get('conversation_state') == 'in_quiz' and user_data.get('quiz', {}).get('id') == quiz_id:
        logger.info(f"Quiz timer expired for quiz {quiz_id}, user {user_id}. Ending quiz.")
        end_quiz_internal(context, chat_id, user_id, "⏱️ انتهى وقت الاختبار المحدد!")
    # لا نرجع حالة هنا لأن هذه وظيفة مؤقت

def end_quiz_internal(context: CallbackContext, chat_id, user_id, end_message="🏁 **انتهى الاختبار!**"):
    """وظيفة داخلية لإنهاء الاختبار وحساب النتيجة."""
    user_data = context.dispatcher.user_data.get(user_id, {})
    if user_data.get('conversation_state') != 'in_quiz':
        # الاختبار انتهى بالفعل أو لم يبدأ
        return
        
    quiz_data = user_data.get('quiz')
    if not quiz_data:
        logger.error(f"end_quiz_internal called but no quiz data for user {user_id}")
        return
        
    quiz_id = quiz_data['id']
    score = quiz_data['score']
    num_questions = len(quiz_data['questions'])
    start_time = quiz_data['start_time']
    duration_taken = time.time() - start_time
    
    # إزالة مؤقت الاختبار الكلي ومؤقت السؤال الحالي (إن وجد)
    remove_quiz_timer(context)
    remove_question_timer(context)
    
    # تحديث حالة الاختبار في قاعدة البيانات
    if QUIZ_DB:
        QUIZ_DB.end_quiz(quiz_id, score, duration_taken)
    else:
        logger.error("Cannot end quiz in DB: QuizDatabase not initialized.")

    # حساب النسبة المئوية
    percentage = (score / num_questions * 100) if num_questions > 0 else 0
    
    result_text = f"{end_message}\n\n"
    result_text += f"📊 **النتيجة:** {score} من {num_questions} ({percentage:.1f}%)\n"
    result_text += f"⏱️ **الوقت المستغرق:** {int(duration_taken // 60)} دقائق و {int(duration_taken % 60)} ثواني\n\n"
    
    # رسالة تشجيعية أو نصيحة
    if percentage >= 80:
        result_text += "🎉 ممتاز! أداء رائع."
    elif percentage >= 60:
        result_text += "👍 جيد جداً! استمر في التقدم."
    elif percentage >= 40:
        result_text += "💪 لا بأس! تحتاج إلى المزيد من المراجعة."
    else:
        result_text += "😔 حظ أوفر في المرة القادمة. ركز على مراجعة الأخطاء."
        
    # مسح بيانات الاختبار من user_data وتغيير الحالة
    user_data.pop('quiz', None)
    user_data['conversation_state'] = MAIN_MENU # العودة للقائمة الرئيسية بعد الاختبار
    
    # إرسال النتيجة النهائية
    reply_markup = create_quiz_menu_keyboard() # عرض قائمة الاختبارات مجدداً
    try:
        # محاولة تعديل آخر رسالة (التي قد تكون رسالة السؤال أو رسالة الخطأ)
        last_message_id = quiz_data.get('last_question_message_id')
        if last_message_id:
             context.bot.edit_message_text(
                 chat_id=chat_id,
                 message_id=last_message_id,
                 text=result_text,
                 reply_markup=reply_markup,
                 parse_mode=ParseMode.MARKDOWN
             )
        else:
             # إذا لم نتمكن من التعديل، نرسل رسالة جديدة
             context.bot.send_message(chat_id=chat_id, text=result_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
             
    except BadRequest as e:
         if "Message to edit not found" in str(e) or "message can't be edited" in str(e):
             logger.warning(f"Could not edit message {last_message_id} for quiz end, sending new message.")
             try:
                 context.bot.send_message(chat_id=chat_id, text=result_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
             except Exception as send_error:
                 logger.error(f"Failed to send new quiz end message: {send_error}")
         else:
             logger.error(f"Error editing message for quiz end: {e}")
             # محاولة إرسال رسالة جديدة كحل بديل
             try:
                 context.bot.send_message(chat_id=chat_id, text=result_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
             except Exception as send_error:
                 logger.error(f"Failed to send new quiz end message: {send_error}")
    except Exception as e:
        logger.error(f"Error sending quiz end result: {e}")
        # محاولة إرسال رسالة جديدة كحل بديل
        try:
            context.bot.send_message(chat_id=chat_id, text=result_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception as send_error:
            logger.error(f"Failed to send new quiz end message: {send_error}")

# --- معالج الأخطاء --- 

def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    
    # محاولة إعلام المستخدم بالخطأ إذا أمكن
    if isinstance(update, Update) and update.effective_chat:
        try:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ حدث خطأ غير متوقع أثناء معالجة طلبك. يرجى المحاولة مرة أخرى لاحقاً."
            )
        except Unauthorized:
            logger.warning(f"Bot unauthorized to send message to chat {update.effective_chat.id}")
        except Exception as e:
            logger.error(f"Exception while sending error message to user: {e}")

# --- الوظيفة الرئيسية --- 

def main() -> None:
    """بدء تشغيل البوت."""
    if not TOKEN:
        logger.critical("Bot token not found. Exiting.")
        return
        
    if not QUIZ_DB:
         logger.warning("QuizDatabase is not initialized. Some features might not work.")

    # إنشاء Updater وتمرير توكن البوت إليه.
    updater = Updater(TOKEN)

    # الحصول على المرسل لتسجيل المعالجات
    dispatcher = updater.dispatcher

    # --- معالج المحادثة الرئيسي --- 
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start_command)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(info_menu_callback, pattern='^menu_info$'),
                CallbackQueryHandler(quiz_menu_callback, pattern='^menu_quiz$'),
                CallbackQueryHandler(admin_menu_callback, pattern='^menu_admin$'),
                CallbackQueryHandler(about_callback, pattern='^menu_about$'),
                # CallbackQueryHandler(reports_callback, pattern='^menu_reports$'), # لم يتم التنفيذ بعد
                CallbackQueryHandler(info_callback, pattern='^info_'), # معالجة أزرار المعلومات
            ],
            QUIZ_MENU: [
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'),
                CallbackQueryHandler(quiz_prompt_callback, pattern='^quiz_(random|by_chapter|by_lesson|by_grade|review)_prompt$'),
            ],
            ADMIN_MENU: [
                CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'),
                CallbackQueryHandler(add_question_start, pattern='^admin_add_question$'),
                CallbackQueryHandler(delete_question_start, pattern='^admin_delete_question$'),
                CallbackQueryHandler(show_question_start, pattern='^admin_show_question$'),
                CallbackQueryHandler(manage_structure_callback, pattern='^admin_manage_structure$'),
                CallbackQueryHandler(manage_grades_callback, pattern='^admin_manage_grades$'),
                CallbackQueryHandler(manage_chapters_callback, pattern='^admin_manage_chapters$'),
                CallbackQueryHandler(manage_lessons_callback, pattern='^admin_manage_lessons$'),
            ],
            ADMIN_GRADE_MENU: [
                 CallbackQueryHandler(manage_structure_callback, pattern='^admin_manage_structure$'),
                 CallbackQueryHandler(add_grade_prompt, pattern='^admin_add_grade$'),
                 # معالجة اختيار مرحلة للإدارة (لعرض الفصول)
                 CallbackQueryHandler(select_structure_for_quiz_callback, pattern='^select_grade_admin_'), 
            ],
             ADMIN_CHAPTER_MENU: [
                 CallbackQueryHandler(manage_grades_callback, pattern='^admin_manage_grades$'), # العودة لاختيار المرحلة
                 CallbackQueryHandler(add_chapter_prompt, pattern='^admin_add_chapter_prompt$'),
                 # معالجة اختيار فصل للإدارة (لعرض الدروس)
                 CallbackQueryHandler(select_structure_for_quiz_callback, pattern='^select_chapter_admin_'),
             ],
             ADMIN_LESSON_MENU: [
                 CallbackQueryHandler(manage_chapters_callback, pattern='^admin_manage_chapters$'), # العودة لاختيار الفصل
                 CallbackQueryHandler(add_lesson_prompt, pattern='^admin_add_lesson_prompt$'),
                 # معالجة اختيار درس للإدارة (حالياً لا يوجد إجراء)
                 CallbackQueryHandler(select_structure_for_quiz_callback, pattern='^select_lesson_admin_'),
             ],
            ADDING_QUESTION: [MessageHandler(Filters.text & ~Filters.command, add_question_text)],
            ADDING_OPTIONS: [MessageHandler(Filters.text & ~Filters.command, add_question_options)],
            ADDING_CORRECT_ANSWER: [MessageHandler(Filters.text & ~Filters.command, add_question_correct_answer)],
            ADDING_EXPLANATION: [MessageHandler(Filters.text & ~Filters.command, add_question_explanation)],
            DELETING_QUESTION: [MessageHandler(Filters.text & ~Filters.command, delete_question_confirm)],
            SHOWING_QUESTION: [MessageHandler(Filters.text & ~Filters.command, show_question_details)],
            ADDING_GRADE_LEVEL: [MessageHandler(Filters.text & ~Filters.command, add_grade_level)],
            ADDING_CHAPTER: [MessageHandler(Filters.text & ~Filters.command, add_chapter)],
            ADDING_LESSON: [MessageHandler(Filters.text & ~Filters.command, add_lesson)],
            SELECT_GRADE_LEVEL_FOR_QUIZ: [
                CallbackQueryHandler(select_structure_for_quiz_callback, pattern='^select_grade_quiz_'),
                CallbackQueryHandler(quiz_menu_callback, pattern='^menu_quiz$'), # زر العودة
            ],
            SELECT_CHAPTER_FOR_QUIZ: [
                CallbackQueryHandler(select_structure_for_quiz_callback, pattern='^select_chapter_quiz_'),
                CallbackQueryHandler(quiz_prompt_callback, pattern='^quiz_by_chapter_prompt$'), # زر العودة
            ],
            SELECT_CHAPTER_FOR_LESSON: [
                CallbackQueryHandler(select_structure_for_quiz_callback, pattern='^select_chapter_lesson_'),
                CallbackQueryHandler(quiz_prompt_callback, pattern='^quiz_by_lesson_prompt$'), # زر العودة
            ],
            SELECT_LESSON_FOR_QUIZ: [
                CallbackQueryHandler(select_structure_for_quiz_callback, pattern='^select_lesson_quiz_'),
                # زر العودة هنا يعيد إلى اختيار الفصل، نحتاج لمعالجة هذا
                CallbackQueryHandler(quiz_prompt_callback, pattern='^quiz_by_lesson_prompt$'), 
            ],
            SELECTING_QUIZ_DURATION: [
                CallbackQueryHandler(select_quiz_duration_callback, pattern='^quiz_duration_'),
                CallbackQueryHandler(quiz_menu_callback, pattern='^menu_quiz$'), # زر العودة
            ],
            TAKING_QUIZ: [
                CallbackQueryHandler(quiz_answer_callback, pattern='^quiz_answer_'),
                CallbackQueryHandler(end_quiz_callback, pattern='^quiz_end$'),
            ],
            # حالات اختيار الهيكل لإضافة سؤال
            SELECT_GRADE_LEVEL: [
                 CallbackQueryHandler(select_structure_for_quiz_callback, pattern='^select_grade_admin_'),
                 CallbackQueryHandler(admin_menu_callback, pattern='^menu_admin$'), # زر العودة لقائمة الإدارة
            ],
            SELECT_CHAPTER_FOR_LESSON_ADMIN: [ # حالة انتظار اختيار الفصل لإدارة الدروس
                 CallbackQueryHandler(select_structure_for_quiz_callback, pattern='^select_chapter_for_lesson_admin_'),
                 CallbackQueryHandler(manage_lessons_callback, pattern='^admin_manage_lessons$'), # زر العودة
            ],
        },
        fallbacks=[CommandHandler('start', start_command)], # السماح بإعادة البدء من أي مكان
        map_to_parent={
            # يمكن إضافة انتقالات للعودة إلى القائمة الرئيسية أو إنهاء المحادثة
            ConversationHandler.END: MAIN_MENU 
        }
    )

    dispatcher.add_handler(conv_handler)

    # تسجيل معالج الأخطاء
    dispatcher.add_error_handler(error_handler)

    # بدء البوت
    logger.info("Starting bot polling...")
    updater.start_polling()

    # تشغيل البوت حتى تضغط Ctrl-C
    updater.idle()

if __name__ == '__main__':
    main()

