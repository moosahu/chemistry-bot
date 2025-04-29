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

# --- استيراد مكتبات تيليجرام (متوافق مع الإصدار 12.8) ---
try:
    # في الإصدار 12.x، يتم استيراد ParseMode مباشرة من telegram
    from telegram import (
        Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ParseMode,
        TelegramError, NetworkError, Unauthorized, BadRequest
    )
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

# تكوين التسجيل
log_file_path = os.path.join(os.path.dirname(__file__), 'bot_log.txt')
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout) # تسجيل في المخرجات القياسية (Heroku logs)
    ]
)
logger = logging.getLogger(__name__)

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
    
    # تنظيف بيانات المستخدم عند بدء محادثة جديدة (باستثناء user_id)
    keys_to_clear = [k for k in context.user_data if k != 'user_id']
    for key in keys_to_clear:
        del context.user_data[key]
        
    context.user_data['conversation_state'] = MAIN_MENU # تعيين الحالة الافتراضية
    return MAIN_MENU

def about_command(update: Update, context: CallbackContext) -> None:
    """معالجة أمر /about."""
    about_text = (
        "ℹ️ **حول البوت**\n\n"
        "بوت الكيمياء التحصيلي هو أداة تعليمية تفاعلية لمساعدة طلاب المرحلة الثانوية في دراسة الكيمياء.\n\n"
        "**الميزات:**\n"
        "• معلومات عن العناصر والمركبات والمفاهيم الكيميائية\n"
        "• اختبارات تفاعلية متنوعة\n"
        "• تقارير أداء مفصلة\n"
        "• دعم للمعادلات الكيميائية\n\n"
        "**المراحل الدراسية المدعومة:**\n"
        "• أول ثانوي\n"
        "• ثاني ثانوي\n"
        "• ثالث ثانوي\n\n"
        "تم تطوير البوت بواسطة فريق متخصص في تعليم الكيمياء وتقنية المعلومات."
    )
    
    keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        update.message.reply_text(about_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error sending about message: {e}")

# --- وظائف معالجة أزرار القوائم ---

def main_menu_button_handler(update: Update, context: CallbackContext) -> int:
    """معالجة أزرار القائمة الرئيسية."""
    query = update.callback_query
    if not query:
        logger.warning("main_menu_button_handler called without callback query.")
        return MAIN_MENU
        
    try:
        query.answer()
    except Exception as e:
        logger.warning(f"Error answering callback query in main_menu: {e}")
        
    user_id = query.from_user.id
    context.user_data['user_id'] = user_id # التأكد من تخزين معرف المستخدم
    next_state = MAIN_MENU # الحالة الافتراضية
    
    # تنظيف بيانات المستخدم عند العودة للقائمة الرئيسية
    if query.data == 'main_menu':
        keys_to_clear = [k for k in context.user_data if k != 'user_id']
        for key in keys_to_clear:
            del context.user_data[key]
        
        welcome_text = (
            f"🖋️ مرحباً بك في بوت الكيمياء التحصيلي\n\n"
            f"👋 أهلاً {query.from_user.first_name}!\n\n"
            f"اختر أحد الخيارات أدناه:"
        )
        
        reply_markup = create_main_menu_keyboard(user_id)
        try:
            query.edit_message_text(welcome_text, reply_markup=reply_markup)
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                 logger.error(f"Error editing message for main menu: {e}")
        except Exception as e:
            logger.error(f"Error editing message for main menu: {e}")
        next_state = MAIN_MENU
    
    # معالجة أزرار القائمة الرئيسية
    elif query.data == 'menu_info':
        info_text = (
            "📚 **المعلومات الكيميائية**\n\n"
            "يمكنك البحث عن معلومات حول:\n"
            "• العناصر الكيميائية (مثل H أو Na)\n"
            "• المركبات الكيميائية (مثل H2O أو NaCl)\n"
            "• المفاهيم الكيميائية (مثل التأكسد أو الروابط)\n\n"
            "**للبحث:** أرسل اسم أو رمز ما تبحث عنه\n\n"
            "**أمثلة:**\n"
            "• H (للحصول على معلومات عن الهيدروجين)\n"
            "• الجدول الدوري (للحصول على معلومات عن الجدول الدوري)\n"
            "• H2SO4 (للحصول على معلومات عن حمض الكبريتيك)"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            query.edit_message_text(info_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except BadRequest as e:
             if "Message is not modified" not in str(e):
                 logger.error(f"Error editing message for info menu: {e}")
        except Exception as e:
            logger.error(f"Error editing message for info menu: {e}")
        next_state = MAIN_MENU # يبقى في القائمة الرئيسية لاستقبال البحث
    
    # معالجة زر قائمة الاختبارات
    elif query.data == 'menu_quiz':
        quiz_text = (
            "📝 **الاختبارات**\n\n"
            "اختر نوع الاختبار الذي ترغب في إجرائه:"
        )
        
        reply_markup = create_quiz_menu_keyboard()
        try:
            query.edit_message_text(quiz_text, reply_markup=reply_markup)
        except BadRequest as e:
             if "Message is not modified" not in str(e):
                 logger.error(f"Error editing message for quiz menu: {e}")
        except Exception as e:
            logger.error(f"Error editing message for quiz menu: {e}")
        next_state = QUIZ_MENU
    
    # معالجة زر تقارير الأداء
    elif query.data == 'menu_reports':
        if not QUIZ_DB:
            reports_text = "📊 **تقارير الأداء**\n\n⚠️ حدث خطأ في الاتصال بقاعدة البيانات."
            logger.error("Cannot fetch reports: QuizDatabase not initialized.")
        else:
            reports = QUIZ_DB.get_user_reports(user_id)
            
            if not reports:
                reports_text = (
                    "📊 **تقارير الأداء**\n\n"
                    "لم تقم بإجراء أي اختبارات بعد.\n"
                    "قم بإجراء بعض الاختبارات لعرض تقارير أدائك هنا."
                )
            else:
                reports_text = "📊 **تقارير الأداء**\n\n"
                
                for i, report in enumerate(reports[:5], 1):  # عرض آخر 5 تقارير فقط
                    quiz_id = report.get('quiz_id', 'N/A')
                    quiz_type = report.get('quiz_type', 'N/A')
                    score = report.get('score_percentage', 'N/A')
                    date = report.get('date', 'N/A')
                    
                    reports_text += (
                        f"**{i}. {get_quiz_type_name(quiz_type)}**\n"
                        f"التاريخ: {date}\n"
                        f"النتيجة: {score}%\n"
                        f"معرف الاختبار: {quiz_id}\n\n"
                    )
                
                if len(reports) > 5:
                    reports_text += f"*وأكثر من ذلك... ({len(reports) - 5} اختبارات إضافية)*"
        
        keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            query.edit_message_text(reports_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except BadRequest as e:
             if "Message is not modified" not in str(e):
                 logger.error(f"Error editing message for reports menu: {e}")
        except Exception as e:
            logger.error(f"Error editing message for reports menu: {e}")
        next_state = MAIN_MENU
    
    # معالجة زر حول البوت
    elif query.data == 'menu_about':
        about_text = (
            "ℹ️ **حول البوت**\n\n"
            "بوت الكيمياء التحصيلي هو أداة تعليمية تفاعلية لمساعدة طلاب المرحلة الثانوية في دراسة الكيمياء.\n\n"
            "**الميزات:**\n"
            "• معلومات عن العناصر والمركبات والمفاهيم الكيميائية\n"
            "• اختبارات تفاعلية متنوعة\n"
            "• تقارير أداء مفصلة\n"
            "• دعم للمعادلات الكيميائية\n\n"
            "**المراحل الدراسية المدعومة:**\n"
            "• أول ثانوي\n"
            "• ثاني ثانوي\n"
            "• ثالث ثانوي\n\n"
            "تم تطوير البوت بواسطة فريق متخصص في تعليم الكيمياء وتقنية المعلومات."
        )
        
        keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            query.edit_message_text(about_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except BadRequest as e:
             if "Message is not modified" not in str(e):
                 logger.error(f"Error editing message for about menu: {e}")
        except Exception as e:
            logger.error(f"Error editing message for about menu: {e}")
        next_state = MAIN_MENU
    
    # معالجة زر قائمة الإدارة (للمسؤولين فقط)
    elif query.data == 'menu_admin':
        if not is_admin(user_id):
            try:
                query.edit_message_text(
                    "⛔ غير مصرح لك بالوصول إلى هذا القسم.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]])
                )
            except Exception as e:
                logger.error(f"Error sending unauthorized message: {e}")
            next_state = MAIN_MENU
        else:
            admin_text = (
                "⚙️ **إدارة البوت**\n\n"
                "اختر العملية التي ترغب في إجرائها:"
            )
            
            reply_markup = create_admin_menu_keyboard()
            try:
                query.edit_message_text(admin_text, reply_markup=reply_markup)
            except BadRequest as e:
                 if "Message is not modified" not in str(e):
                     logger.error(f"Error editing message for admin menu: {e}")
            except Exception as e:
                logger.error(f"Error editing message for admin menu: {e}")
            next_state = ADMIN_MENU
            
    context.user_data['conversation_state'] = next_state
    return next_state

# --- وظائف معالجة أزرار قائمة الاختبارات ---

def quiz_menu_button_handler(update: Update, context: CallbackContext) -> int:
    """معالجة أزرار قائمة الاختبارات."""
    query = update.callback_query
    if not query:
        logger.warning("quiz_menu_button_handler called without callback query.")
        return QUIZ_MENU
        
    try:
        query.answer()
    except Exception as e:
        logger.warning(f"Error answering callback query in quiz_menu: {e}")
        
    user_id = query.from_user.id
    context.user_data['user_id'] = user_id # التأكد من تخزين معرف المستخدم
    next_state = QUIZ_MENU # الحالة الافتراضية
    
    # معالجة زر الاختبار العشوائي
    if query.data == 'quiz_random_prompt':
        # تخزين إعدادات الاختبار
        context.user_data['quiz_settings'] = {
            'type': 'random',
            'num_questions': DEFAULT_QUIZ_QUESTIONS
        }
        
        # عرض خيارات مدة الاختبار
        duration_text = (
            "⏱️ **اختيار مدة الاختبار**\n\n"
            "اختر المدة المناسبة لإجراء الاختبار:"
        )
        
        reply_markup = create_quiz_duration_keyboard()
        try:
            query.edit_message_text(duration_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Error editing message for quiz duration selection: {e}")
        next_state = SELECTING_QUIZ_DURATION
    
    # معالجة زر الاختبار حسب الفصل
    elif query.data == 'quiz_by_chapter_prompt':
        # عرض خيارات المراحل الدراسية أولاً
        grade_text = (
            "🏫 **اختيار المرحلة الدراسية**\n\n"
            "اختر المرحلة الدراسية للاختبار:"
        )
        context.user_data['quiz_context'] = 'by_chapter' # تحديد سياق الاختبار
        reply_markup = create_grade_levels_keyboard(for_quiz=True, context=context)
        if reply_markup:
            try:
                query.edit_message_text(grade_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logger.error(f"Error editing message for grade selection (chapter quiz): {e}")
            next_state = SELECT_GRADE_LEVEL_FOR_QUIZ
        else:
            try:
                query.edit_message_text("⚠️ حدث خطأ أثناء تحميل المراحل الدراسية.")
            except Exception as e:
                 logger.error(f"Error sending grade loading error message: {e}")
            next_state = QUIZ_MENU
    
    # معالجة زر الاختبار حسب الدرس
    elif query.data == 'quiz_by_lesson_prompt':
        # عرض خيارات المراحل الدراسية أولاً
        grade_text = (
            "🏫 **اختيار المرحلة الدراسية**\n\n"
            "اختر المرحلة الدراسية للاختبار:"
        )
        context.user_data['quiz_context'] = 'by_lesson' # تحديد سياق الاختبار
        reply_markup = create_grade_levels_keyboard(for_quiz=True, context=context)
        if reply_markup:
            try:
                query.edit_message_text(grade_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logger.error(f"Error editing message for grade selection (lesson quiz): {e}")
            next_state = SELECT_GRADE_LEVEL_FOR_QUIZ
        else:
            try:
                query.edit_message_text("⚠️ حدث خطأ أثناء تحميل المراحل الدراسية.")
            except Exception as e:
                 logger.error(f"Error sending grade loading error message: {e}")
            next_state = QUIZ_MENU

    # معالجة زر الاختبار حسب المرحلة الدراسية
    elif query.data == 'quiz_by_grade_prompt':
        grade_text = (
            "🏫 **اختيار المرحلة الدراسية**\n\n"
            "اختر المرحلة الدراسية للاختبار:"
        )
        context.user_data['quiz_context'] = 'by_grade' # تحديد سياق الاختبار
        reply_markup = create_grade_levels_keyboard(for_quiz=True, context=context)
        if reply_markup:
            try:
                query.edit_message_text(grade_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logger.error(f"Error editing message for grade selection (grade quiz): {e}")
            next_state = SELECT_GRADE_LEVEL_FOR_QUIZ
        else:
            try:
                query.edit_message_text("⚠️ حدث خطأ أثناء تحميل المراحل الدراسية.")
            except Exception as e:
                 logger.error(f"Error sending grade loading error message: {e}")
            next_state = QUIZ_MENU
    
    # معالجة زر مراجعة الأخطاء
    elif query.data == 'quiz_review_prompt':
        # تخزين إعدادات الاختبار
        context.user_data['quiz_settings'] = {
            'type': 'review',
            'num_questions': DEFAULT_QUIZ_QUESTIONS
        }
        
        # عرض خيارات مدة الاختبار
        duration_text = (
            "⏱️ **اختيار مدة الاختبار**\n\n"
            "اختر المدة المناسبة لإجراء اختبار مراجعة الأخطاء:"
        )
        
        reply_markup = create_quiz_duration_keyboard()
        try:
            query.edit_message_text(duration_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Error editing message for review quiz duration: {e}")
        next_state = SELECTING_QUIZ_DURATION
        
    context.user_data['conversation_state'] = next_state
    return next_state

# --- وظائف معالجة اختيار المرحلة الدراسية ---

def grade_level_selection_handler(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار المرحلة الدراسية."""
    query = update.callback_query
    if not query:
        logger.warning("grade_level_selection_handler called without callback query.")
        return context.user_data.get('conversation_state', MAIN_MENU)
        
    try:
        query.answer()
    except Exception as e:
        logger.warning(f"Error answering callback query in grade_level_selection: {e}")
        
    user_id = query.from_user.id
    context.user_data['user_id'] = user_id # التأكد من تخزين معرف المستخدم
    next_state = context.user_data.get('conversation_state', MAIN_MENU) # الحالة الافتراضية
    quiz_context = context.user_data.get('quiz_context', None)

    # التحقق من نوع الاختيار (للاختبار أو للإدارة)
    if query.data.startswith('select_grade_quiz_'):
        # اختيار المرحلة للاختبار
        grade_id_str = query.data.replace('select_grade_quiz_', '')
        
        if grade_id_str == 'all':
            # اختيار اختبار تحصيلي عام (جميع المراحل)
            context.user_data['quiz_settings'] = {
                'type': 'by_grade',
                'grade_id': None,  # None تعني جميع المراحل
                'num_questions': DEFAULT_QUIZ_QUESTIONS
            }
            
            # عرض خيارات مدة الاختبار
            duration_text = (
                "⏱️ **اختيار مدة الاختبار**\n\n"
                "اختر المدة المناسبة لإجراء الاختبار التحصيلي العام:"
            )
            
            reply_markup = create_quiz_duration_keyboard()
            try:
                query.edit_message_text(duration_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logger.error(f"Error editing message for duration (all grades quiz): {e}")
            next_state = SELECTING_QUIZ_DURATION
        else:
            try:
                grade_id = int(grade_id_str)
                context.user_data['selected_grade_id'] = grade_id
                
                # التحقق من سياق الاختبار
                if quiz_context == 'by_chapter':
                    # عرض قائمة الفصول للمرحلة المختارة
                    chapter_text = (
                        f"📚 **اختيار الفصل**\n\n"
                        f"اختر الفصل للاختبار:"
                    )
                    reply_markup = create_chapters_keyboard(grade_id, for_quiz=True, context=context)
                    if reply_markup:
                        try:
                            query.edit_message_text(chapter_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                        except Exception as e:
                            logger.error(f"Error editing message for chapter selection (chapter quiz): {e}")
                        next_state = SELECT_CHAPTER_FOR_QUIZ
                    else:
                        try:
                            query.edit_message_text("⚠️ لا توجد فصول متاحة لهذه المرحلة.")
                        except Exception as e:
                            logger.error(f"Error sending no chapters message: {e}")
                        next_state = QUIZ_MENU # العودة لقائمة الاختبارات
                
                elif quiz_context == 'by_lesson':
                    # عرض قائمة الفصول للمرحلة المختارة (لاختيار درس)
                    chapter_text = (
                        f"📚 **اختيار الفصل**\n\n"
                        f"اختر الفصل الذي يحتوي على الدرس المطلوب:"
                    )
                    reply_markup = create_chapters_keyboard(grade_id, for_lesson=True, context=context)
                    if reply_markup:
                        try:
                            query.edit_message_text(chapter_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                        except Exception as e:
                            logger.error(f"Error editing message for chapter selection (lesson quiz): {e}")
                        next_state = SELECT_CHAPTER_FOR_LESSON
                    else:
                        try:
                            query.edit_message_text("⚠️ لا توجد فصول متاحة لهذه المرحلة.")
                        except Exception as e:
                            logger.error(f"Error sending no chapters message: {e}")
                        next_state = QUIZ_MENU # العودة لقائمة الاختبارات
                
                elif quiz_context == 'by_grade':
                    # اختبار حسب المرحلة الدراسية مباشرة
                    context.user_data['quiz_settings'] = {
                        'type': 'by_grade',
                        'grade_id': grade_id,
                        'num_questions': DEFAULT_QUIZ_QUESTIONS
                    }
                    
                    # عرض خيارات مدة الاختبار
                    duration_text = (
                        "⏱️ **اختيار مدة الاختبار**\n\n"
                        "اختر المدة المناسبة لإجراء الاختبار:"
                    )
                    reply_markup = create_quiz_duration_keyboard()
                    try:
                        query.edit_message_text(duration_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                    except Exception as e:
                        logger.error(f"Error editing message for duration (grade quiz): {e}")
                    next_state = SELECTING_QUIZ_DURATION
                else:
                    logger.warning(f"Unknown quiz context: {quiz_context}")
                    next_state = QUIZ_MENU
                    
            except ValueError:
                logger.error(f"Invalid grade_id received: {grade_id_str}")
                next_state = QUIZ_MENU
    
    elif query.data.startswith('select_grade_admin_') or query.data.startswith('select_grade_for_chapter_'):
        # اختيار المرحلة للإدارة
        try:
            if query.data.startswith('select_grade_admin_'):
                 grade_id = int(query.data.replace('select_grade_admin_', ''))
                 admin_context = 'manage_chapters' # السياق التالي هو إدارة الفصول
            else: # select_grade_for_chapter_
                 grade_id = int(query.data.replace('select_grade_for_chapter_', ''))
                 admin_context = 'add_chapter' # لا يزال في سياق إضافة فصل
                 context.user_data['selected_grade_id_for_chapter'] = grade_id # تخزين للمرحلة المختارة
                 # هنا يجب أن نطلب اسم الفصل الجديد بدلاً من عرض الفصول
                 try:
                     query.edit_message_text("📝 أدخل اسم الفصل الجديد:")
                 except Exception as e:
                     logger.error(f"Error asking for new chapter name: {e}")
                 next_state = ADDING_CHAPTER # الانتقال لحالة إدخال اسم الفصل
                 context.user_data['conversation_state'] = next_state
                 return next_state
                 
            context.user_data['selected_grade_id'] = grade_id
            context.user_data['admin_context'] = admin_context
            
            # عرض قائمة الفصول للمرحلة المختارة
            chapter_text = (
                f"📚 **إدارة الفصول للمرحلة المحددة**\n\n"
                f"اختر الفصل للإدارة أو قم بإضافة فصل جديد:"
            )
            reply_markup = create_chapters_keyboard(grade_id, context=context)
            if reply_markup:
                # إضافة زر "إضافة فصل جديد" لاحقاً إذا لزم الأمر
                # query.edit_message_text(chapter_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                # next_state = ADMIN_CHAPTER_MENU # أو حالة أخرى مناسبة
                pass # مؤقتاً، يجب إضافة منطق هنا لعرض الفصول أو زر الإضافة
            else:
                # التعامل مع حالة عدم وجود فصول
                try:
                    query.edit_message_text("⚠️ لا توجد فصول متاحة لهذه المرحلة.")
                except Exception as e:
                    logger.error(f"Error sending no chapters message (admin): {e}")
                next_state = ADMIN_GRADE_MENU # العودة لقائمة المراحل 
        except ValueError:
            logger.error(f"Invalid grade_id format in admin selection: {query.data}")
            next_state = ADMIN_GRADE_MENU # العودة لقائمة إدارة المراحل
        except Exception as e:
            logger.error(f"Unexpected error in admin grade/chapter selection: {e}")
            next_state = ADMIN_GRADE_MENU # العودة لقائمة إدارة المراحل 
