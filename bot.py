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

from telegram.constants import ParseMode
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters, CallbackContext, 
    CallbackQueryHandler, ConversationHandler, JobQueue
)
from telegram.error import NetworkError, TelegramError, Unauthorized, BadRequest

# استيراد البيانات الثابتة ووظائف المعادلات
from chemistry_data import ELEMENTS, COMPOUNDS, CONCEPTS, PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO
from chemical_equations import process_text_with_chemical_notation, format_chemical_equation

# استيراد الفئة المحسنة لقاعدة البيانات
from quiz_db import QuizDatabase

# --- إعدادات --- 
# ضع معرف المستخدم الرقمي الخاص بك هنا لتقييد الوصول إلى إدارة قاعدة البيانات
ADMIN_USER_ID = 6448526509 # !!! استبدل هذا بمعرف المستخدم الرقمي الخاص بك !!!
# توكن البوت
TOKEN = "8167394360:AAG-b3v-VDmxLtWVQCuBkc694Mt3ZCs18IY" # !!! استبدل هذا بتوكن البوت الخاص بك بدقة تامة !!!

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

# --- الملف المصحح ---
# تم إصلاح استيراد ParseMode وإضافة استيرادات أخرى

def is_admin(user_id):
    """التحقق مما إذا كان المستخدم مسؤولاً."""
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
        keyboard.append([InlineKeyboardButton("⚙️ إدارة الأسئلة", callback_data='menu_admin')])
    
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
        [InlineKeyboardButton("🏫 إدارة المراحل والفصول والدروس", callback_data='admin_manage_structure')],
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

def create_grade_levels_keyboard(for_quiz=False):
    """إنشاء لوحة مفاتيح لاختيار المرحلة الدراسية."""
    grade_levels = QUIZ_DB.get_grade_levels()
    keyboard = []
    
    for grade_id, grade_name in grade_levels:
        if for_quiz:
            callback_data = f'select_grade_quiz_{grade_id}'
        else:
            callback_data = f'select_grade_{grade_id}'
        keyboard.append([InlineKeyboardButton(grade_name, callback_data=callback_data)])
    
    # إضافة خيار الاختبار التحصيلي العام (جميع المراحل) إذا كان للاختبار
    if for_quiz:
        keyboard.append([InlineKeyboardButton("اختبار تحصيلي عام (جميع المراحل)", callback_data='select_grade_quiz_all')])
    
    # إضافة زر العودة
    if for_quiz:
        keyboard.append([InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data='menu_quiz')])
    else:
        keyboard.append([InlineKeyboardButton("🔙 العودة لقائمة إدارة الهيكل", callback_data='admin_manage_structure')])
    
    return InlineKeyboardMarkup(keyboard)

def create_chapters_keyboard(grade_level_id, for_quiz=False, for_lesson=False):
    """إنشاء لوحة مفاتيح لاختيار الفصل."""
    chapters = QUIZ_DB.get_chapters_by_grade(grade_level_id)
    keyboard = []
    
    for chapter_id, chapter_name in chapters:
        if for_quiz:
            callback_data = f'select_chapter_quiz_{chapter_id}'
        elif for_lesson:
            callback_data = f'select_chapter_lesson_{chapter_id}'
        else:
            callback_data = f'select_chapter_{chapter_id}'
        keyboard.append([InlineKeyboardButton(chapter_name, callback_data=callback_data)])
    
    # إضافة زر العودة
    if for_quiz:
        keyboard.append([InlineKeyboardButton("🔙 العودة لاختيار المرحلة", callback_data='quiz_by_grade_prompt')])
    elif for_lesson:
        keyboard.append([InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data='menu_quiz')])
    else:
        keyboard.append([InlineKeyboardButton("🔙 العودة لقائمة إدارة المراحل", callback_data='admin_manage_grades')])
    
    return InlineKeyboardMarkup(keyboard)

def create_lessons_keyboard(chapter_id, for_quiz=False):
    """إنشاء لوحة مفاتيح لاختيار الدرس."""
    lessons = QUIZ_DB.get_lessons_by_chapter(chapter_id)
    keyboard = []
    
    for lesson_id, lesson_name in lessons:
        if for_quiz:
            callback_data = f'select_lesson_quiz_{lesson_id}'
        else:
            callback_data = f'select_lesson_{lesson_id}'
        keyboard.append([InlineKeyboardButton(lesson_name, callback_data=callback_data)])
    
    # إضافة زر العودة
    if for_quiz:
        keyboard.append([InlineKeyboardButton("🔙 العودة لاختيار الفصل", callback_data='quiz_by_lesson_prompt')])
    else:
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
    
    # إضافة مهمة مؤقتة لإنهاء الاختبار بعد انتهاء الوقت
    job = context.job_queue.run_once(
        end_quiz_timeout,
        duration_minutes * 60,  # تحويل الدقائق إلى ثواني
        context=job_context
    )
    
    return job

def set_question_timer(context: CallbackContext, chat_id, user_id, quiz_id):
    """إعداد مؤقت للانتقال التلقائي للسؤال التالي بعد 4 دقائق."""
    job_context = {
        'chat_id': chat_id,
        'user_id': user_id,
        'quiz_id': quiz_id,
        'type': 'question_timer'
    }
    
    # إضافة مهمة مؤقتة للانتقال للسؤال التالي بعد 4 دقائق
    job = context.job_queue.run_once(
        question_timer_callback,
        QUESTION_TIMER_SECONDS,  # 4 دقائق
        context=job_context
    )
    
    return job

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
            QUIZ_DB.record_answer(quiz_id, question_id, -1, False)
            
            # إرسال رسالة للمستخدم
            context.bot.send_message(
                chat_id=chat_id,
                text="⏱️ انتهى وقت السؤال! سيتم الانتقال للسؤال التالي تلقائياً.",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # الانتقال للسؤال التالي
            quiz_data['current_question_index'] += 1
            
            # إنشاء كائن Update وهمي
            class DummyMessage:
                def __init__(self, chat_id):
                    self.chat_id = chat_id
                    self.message_id = None
                
                def reply_text(self, *args, **kwargs):
                    return context.bot.send_message(chat_id=self.chat_id, *args, **kwargs)
            
            class DummyChat:
                def __init__(self, chat_id):
                    self.id = chat_id
            
            class DummyUpdate:
                def __init__(self, chat_id):
                    self.effective_chat = DummyChat(chat_id)
                    self.effective_message = DummyMessage(chat_id)
                    self.callback_query = None
                    self.effective_user = type('obj', (object,), {'id': user_id})
            
            dummy_update = DummyUpdate(chat_id)
            
            # عرض السؤال التالي
            show_next_question(dummy_update, context)

def remove_quiz_timer(context: CallbackContext):
    """إزالة مؤقت الاختبار إذا كان موجوداً."""
    if 'quiz_timer_job' in context.user_data:
        job = context.user_data['quiz_timer_job']
        if job:
            job.schedule_removal()
        del context.user_data['quiz_timer_job']

def remove_question_timer(context: CallbackContext):
    """إزالة مؤقت السؤال إذا كان موجوداً."""
    if 'question_timer_job' in context.user_data:
        job = context.user_data['question_timer_job']
        if job:
            job.schedule_removal()
        del context.user_data['question_timer_job']

# --- وظائف معالجة الأوامر ---

def start_command(update: Update, context: CallbackContext) -> None:
    """معالجة أمر /start."""
    user = update.effective_user
    logger.info(f"User {user.id} started the bot.")
    
    welcome_text = (
        f"🖋️ مرحباً بك في بوت الكيمياء التحصيلي\n\n"
        f"👋 أهلاً {user.first_name}!\n\n"
        f"اختر أحد الخيارات أدناه:"
    )
    
    reply_markup = create_main_menu_keyboard(user.id)
    update.message.reply_text(welcome_text, reply_markup=reply_markup)
    
    # تنظيف بيانات المستخدم عند بدء محادثة جديدة
    context.user_data.clear()
    
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
    
    update.message.reply_text(about_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

# --- وظائف معالجة أزرار القوائم ---

def main_menu_button_handler(update: Update, context: CallbackContext) -> None:
    """معالجة أزرار القائمة الرئيسية."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # تنظيف بيانات المستخدم عند العودة للقائمة الرئيسية
    if query.data == 'main_menu':
        context.user_data.clear()
        
        welcome_text = (
            f"🖋️ مرحباً بك في بوت الكيمياء التحصيلي\n\n"
            f"👋 أهلاً {query.from_user.first_name}!\n\n"
            f"اختر أحد الخيارات أدناه:"
        )
        
        reply_markup = create_main_menu_keyboard(user_id)
        query.edit_message_text(welcome_text, reply_markup=reply_markup)
        return MAIN_MENU
    
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
        
        query.edit_message_text(info_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    elif query.data == 'menu_quiz':
        quiz_text = "📝 **الاختبارات**\n\nاختر نوع الاختبار:"
        reply_markup = create_quiz_menu_keyboard()
        query.edit_message_text(quiz_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return QUIZ_MENU
    
    elif query.data == 'menu_reports':
        # جلب تقارير المستخدم
        reports = QUIZ_DB.get_user_quiz_history(user_id)
        
        if not reports:
            reports_text = "📊 **تقارير الأداء**\n\nلم تقم بإجراء أي اختبارات بعد."
        else:
            reports_text = "📊 **تقارير الأداء**\n\nاختباراتك السابقة:\n"
            for i, report in enumerate(reports[:10], 1):  # عرض آخر 10 اختبارات فقط
                quiz_type = report.get('quiz_type', 'غير معروف')
                score = report.get('score_percentage', 0)
                date = report.get('start_time', '').split(' ')[0]  # استخراج التاريخ فقط
                reports_text += f"{i}. {quiz_type}: {score}% ({date})\n"
        
        keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        query.edit_message_text(reports_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
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
        
        query.edit_message_text(about_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    elif query.data == 'menu_admin':
        if is_admin(user_id):
            admin_text = "⚙️ **إدارة الأسئلة**\n\nاختر إحدى العمليات:"
            reply_markup = create_admin_menu_keyboard()
            query.edit_message_text(admin_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            return ADMIN_MENU
        else:
            query.edit_message_text(
                "⚠️ ليس لديك صلاحية الوصول إلى هذا القسم.",
                reply_markup=create_main_menu_keyboard(user_id)
            )
    
    # معالجة أزرار إدارة المراحل والفصول والدروس
    elif query.data == 'admin_manage_structure':
        if is_admin(user_id):
            structure_text = "🏫 **إدارة المراحل والفصول والدروس**\n\nاختر إحدى العمليات:"
            reply_markup = create_structure_admin_menu_keyboard()
            query.edit_message_text(structure_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            return ADMIN_GRADE_MENU
        else:
            query.edit_message_text(
                "⚠️ ليس لديك صلاحية الوصول إلى هذا القسم.",
                reply_markup=create_main_menu_keyboard(user_id)
            )
    
    elif query.data == 'admin_manage_grades':
        if is_admin(user_id):
            grades_text = "🏫 **إدارة المراحل الدراسية**\n\nاختر مرحلة دراسية للإدارة أو أضف مرحلة جديدة:"
            
            # إنشاء لوحة مفاتيح للمراحل الدراسية
            grade_levels = QUIZ_DB.get_grade_levels()
            keyboard = []
            
            for grade_id, grade_name in grade_levels:
                keyboard.append([InlineKeyboardButton(grade_name, callback_data=f'admin_edit_grade_{grade_id}')])
            
            keyboard.append([InlineKeyboardButton("➕ إضافة مرحلة جديدة", callback_data='admin_add_grade')])
            keyboard.append([InlineKeyboardButton("🔙 العودة لقائمة إدارة الهيكل", callback_data='admin_manage_structure')])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            query.edit_message_text(grades_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            return ADMIN_GRADE_MENU
        else:
            query.edit_message_text(
                "⚠️ ليس لديك صلاحية الوصول إلى هذا القسم.",
                reply_markup=create_main_menu_keyboard(user_id)
            )
    
    elif query.data == 'admin_manage_chapters':
        if is_admin(user_id):
            chapters_text = "📚 **إدارة الفصول**\n\nاختر المرحلة الدراسية أولاً:"
            reply_markup = create_grade_levels_keyboard()
            query.edit_message_text(chapters_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            return SELECTING_GRADE_FOR_CHAPTER
        else:
            query.edit_message_text(
                "⚠️ ليس لديك صلاحية الوصول إلى هذا القسم.",
                reply_markup=create_main_menu_keyboard(user_id)
            )
    
    elif query.data == 'admin_manage_lessons':
        if is_admin(user_id):
            lessons_text = "📝 **إدارة الدروس**\n\nاختر المرحلة الدراسية أولاً:"
            reply_markup = create_grade_levels_keyboard()
            query.edit_message_text(lessons_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            return SELECTING_GRADE_FOR_CHAPTER
        else:
            query.edit_message_text(
                "⚠️ ليس لديك صلاحية الوصول إلى هذا القسم.",
                reply_markup=create_main_menu_keyboard(user_id)
            )
    
    elif query.data == 'admin_add_grade':
        if is_admin(user_id):
            query.edit_message_text(
                "🏫 **إضافة مرحلة دراسية جديدة**\n\nأرسل اسم المرحلة الدراسية الجديدة:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data='admin_manage_grades')]])
            )
            return ADDING_GRADE_LEVEL
        else:
            query.edit_message_text(
                "⚠️ ليس لديك صلاحية الوصول إلى هذا القسم.",
                reply_markup=create_main_menu_keyboard(user_id)
            )
    
    # معالجة أزرار اختيار المرحلة الدراسية للاختبار
    elif query.data == 'quiz_by_grade_prompt':
        grade_text = "🎓 **اختبار حسب المرحلة الدراسية**\n\nاختر المرحلة الدراسية:"
        reply_markup = create_grade_levels_keyboard(for_quiz=True)
        query.edit_message_text(grade_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return SELECT_GRADE_LEVEL_FOR_QUIZ
    
    # معالجة أزرار اختيار المرحلة الدراسية
    elif query.data.startswith('select_grade_quiz_'):
        grade_id = query.data.split('_')[-1]
        
        if grade_id == 'all':
            # اختبار تحصيلي عام (جميع المراحل)
            context.user_data['quiz_settings'] = {
                'type': 'grade_level',
                'grade_level_id': None,  # None يعني جميع المراحل
                'grade_level_name': 'اختبار تحصيلي عام'
            }
            
            # الانتقال مباشرة إلى اختيار مدة الاختبار
            duration_text = "⏱️ **اختيار مدة الاختبار**\n\nاختر المدة المناسبة للاختبار:"
            reply_markup = create_quiz_duration_keyboard()
            query.edit_message_text(duration_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            return SELECT_QUIZ_DURATION
        else:
            # اختبار لمرحلة دراسية محددة
            grade_levels = QUIZ_DB.get_grade_levels()
            grade_name = next((name for id, name in grade_levels if str(id) == grade_id), "مرحلة غير معروفة")
            
            context.user_data['quiz_settings'] = {
                'type': 'grade_level',
                'grade_level_id': int(grade_id),
                'grade_level_name': grade_name
            }
            
            # الانتقال مباشرة إلى اختيار مدة الاختبار
            duration_text = "⏱️ **اختيار مدة الاختبار**\n\nاختر المدة المناسبة للاختبار:"
            reply_markup = create_quiz_duration_keyboard()
            query.edit_message_text(duration_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            return SELECT_QUIZ_DURATION
    
    # معالجة أزرار اختيار الفصل للاختبار
    elif query.data == 'quiz_by_chapter_prompt':
        chapter_text = "📄 **اختبار حسب الفصل**\n\nاختر المرحلة الدراسية أولاً:"
        reply_markup = create_grade_levels_keyboard(for_quiz=True)
        query.edit_message_text(chapter_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return SELECT_GRADE_LEVEL_FOR_QUIZ
    
    # معالجة أزرار اختيار الدرس للاختبار
    elif query.data == 'quiz_by_lesson_prompt':
        lesson_text = "📝 **اختبار حسب الدرس**\n\nاختر المرحلة الدراسية أولاً:"
        reply_markup = create_grade_levels_keyboard(for_quiz=True)
        query.edit_message_text(lesson_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return SELECT_GRADE_LEVEL_FOR_QUIZ
    
    return None

# --- وظائف معالجة الاختبارات ---

def show_chapter_selection(update: Update, context: CallbackContext) -> int:
    """عرض قائمة الفصول للاختيار."""
    query = update.callback_query
    query.answer()
    
    # التحقق من وجود إعدادات الاختبار
    if 'quiz_settings' not in context.user_data:
        context.user_data['quiz_settings'] = {'type': 'chapter'}
    
    # التحقق من وجود معرف المرحلة الدراسية
    if 'grade_level_id' not in context.user_data['quiz_settings']:
        # إذا لم يتم اختيار المرحلة بعد، نعرض قائمة المراحل
        grade_text = "📄 **اختبار حسب الفصل**\n\nاختر المرحلة الدراسية أولاً:"
        reply_markup = create_grade_levels_keyboard(for_quiz=True)
        query.edit_message_text(grade_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return SELECT_GRADE_LEVEL_FOR_QUIZ
    
    grade_level_id = context.user_data['quiz_settings']['grade_level_id']
    
    # إذا كان الاختبار تحصيلي عام (جميع المراحل)
    if grade_level_id is None:
        # جلب جميع الفصول من جميع المراحل
        chapters = []
        grade_levels = QUIZ_DB.get_grade_levels()
        
        for grade_id, grade_name in grade_levels:
            grade_chapters = QUIZ_DB.get_chapters_by_grade(grade_id)
            for chapter_id, chapter_name in grade_chapters:
                chapters.append((chapter_id, f"{grade_name} - {chapter_name}"))
    else:
        # جلب الفصول للمرحلة المحددة
        chapters = QUIZ_DB.get_chapters_by_grade(grade_level_id)
    
    if not chapters:
        query.edit_message_text(
            "⚠️ لا توجد فصول متاحة لهذه المرحلة الدراسية.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data='quiz_by_chapter_prompt')]])
        )
        return SELECT_CHAPTER_FOR_QUIZ
    
    keyboard = []
    for chapter_id, chapter_name in chapters:
        keyboard.append([InlineKeyboardButton(chapter_name, callback_data=f'select_chapter_quiz_{chapter_id}')])
    
    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data='quiz_by_chapter_prompt')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.edit_message_text(
        "📄 **اختبار حسب الفصل**\n\nاختر الفصل:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    
    return SELECT_CHAPTER_FOR_QUIZ

def show_chapter_for_lesson_selection(update: Update, context: CallbackContext) -> int:
    """عرض قائمة الفصول لاختيار الدرس."""
    query = update.callback_query
    query.answer()
    
    # التحقق من وجود إعدادات الاختبار
    if 'quiz_settings' not in context.user_data:
        context.user_data['quiz_settings'] = {'type': 'lesson'}
    
    # التحقق من وجود معرف المرحلة الدراسية
    if 'grade_level_id' not in context.user_data['quiz_settings']:
        # إذا لم يتم اختيار المرحلة بعد، نعرض قائمة المراحل
        grade_text = "📝 **اختبار حسب الدرس**\n\nاختر المرحلة الدراسية أولاً:"
        reply_markup = create_grade_levels_keyboard(for_quiz=True)
        query.edit_message_text(grade_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return SELECT_GRADE_LEVEL_FOR_QUIZ
    
    grade_level_id = context.user_data['quiz_settings']['grade_level_id']
    
    # إذا كان الاختبار تحصيلي عام (جميع المراحل)
    if grade_level_id is None:
        # جلب جميع الفصول من جميع المراحل
        chapters = []
        grade_levels = QUIZ_DB.get_grade_levels()
        
        for grade_id, grade_name in grade_levels:
            grade_chapters = QUIZ_DB.get_chapters_by_grade(grade_id)
            for chapter_id, chapter_name in grade_chapters:
                chapters.append((chapter_id, f"{grade_name} - {chapter_name}"))
    else:
        # جلب الفصول للمرحلة المحددة
        chapters = QUIZ_DB.get_chapters_by_grade(grade_level_id)
    
    if not chapters:
        query.edit_message_text(
            "⚠️ لا توجد فصول متاحة لهذه المرحلة الدراسية.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data='quiz_by_lesson_prompt')]])
        )
        return SELECT_CHAPTER_FOR_LESSON
    
    keyboard = []
    for chapter_id, chapter_name in chapters:
        keyboard.append([InlineKeyboardButton(chapter_name, callback_data=f'select_chapter_lesson_{chapter_id}')])
    
    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data='quiz_by_lesson_prompt')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.edit_message_text(
        "📝 **اختبار حسب الدرس**\n\nاختر الفصل أولاً:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    
    return SELECT_CHAPTER_FOR_LESSON

def show_lesson_selection(update: Update, context: CallbackContext) -> int:
    """عرض قائمة الدروس للاختيار."""
    query = update.callback_query
    query.answer()
    
    # استخراج معرف الفصل من البيانات
    chapter_id = query.data.split('_')[-1]
    context.user_data['quiz_settings']['chapter_id'] = int(chapter_id)
    
    # جلب الدروس للفصل المحدد
    lessons = QUIZ_DB.get_lessons_by_chapter(chapter_id)
    
    if not lessons:
        query.edit_message_text(
            "⚠️ لا توجد دروس متاحة لهذا الفصل.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data='quiz_by_lesson_prompt')]])
        )
        return SELECT_LESSON_FOR_QUIZ
    
    keyboard = []
    for lesson_id, lesson_name in lessons:
        keyboard.append([InlineKeyboardButton(lesson_name, callback_data=f'select_lesson_quiz_{lesson_id}')])
    
    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data='quiz_by_lesson_prompt')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.edit_message_text(
        "📝 **اختبار حسب الدرس**\n\nاختر الدرس:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    
    return SELECT_LESSON_FOR_QUIZ

def handle_chapter_selection_for_quiz(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار الفصل للاختبار."""
    query = update.callback_query
    query.answer()
    
    # استخراج معرف الفصل من البيانات
    chapter_id = query.data.split('_')[-1]
    
    # جلب اسم الفصل
    chapter_name = "فصل غير معروف"
    chapters = QUIZ_DB.get_chapters_by_grade(context.user_data['quiz_settings'].get('grade_level_id'))
    for c_id, c_name in chapters:
        if str(c_id) == chapter_id:
            chapter_name = c_name
            break
    
    # تخزين معلومات الفصل في إعدادات الاختبار
    context.user_data['quiz_settings']['type'] = 'chapter'
    context.user_data['quiz_settings']['chapter_id'] = int(chapter_id)
    context.user_data['quiz_settings']['chapter_name'] = chapter_name
    
    # الانتقال إلى اختيار مدة الاختبار
    duration_text = "⏱️ **اختيار مدة الاختبار**\n\nاختر المدة المناسبة للاختبار:"
    reply_markup = create_quiz_duration_keyboard()
    query.edit_message_text(duration_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    return SELECT_QUIZ_DURATION

def handle_lesson_selection_for_quiz(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار الدرس للاختبار."""
    query = update.callback_query
    query.answer()
    
    # استخراج معرف الدرس من البيانات
    lesson_id = query.data.split('_')[-1]
    
    # جلب اسم الدرس
    lesson_name = "درس غير معروف"
    lessons = QUIZ_DB.get_lessons_by_chapter(context.user_data['quiz_settings'].get('chapter_id'))
    for l_id, l_name in lessons:
        if str(l_id) == lesson_id:
            lesson_name = l_name
            break
    
    # تخزين معلومات الدرس في إعدادات الاختبار
    context.user_data['quiz_settings']['type'] = 'lesson'
    context.user_data['quiz_settings']['lesson_id'] = int(lesson_id)
    context.user_data['quiz_settings']['lesson_name'] = lesson_name
    
    # الانتقال إلى اختيار مدة الاختبار
    duration_text = "⏱️ **اختيار مدة الاختبار**\n\nاختر المدة المناسبة للاختبار:"
    reply_markup = create_quiz_duration_keyboard()
    query.edit_message_text(duration_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    return SELECT_QUIZ_DURATION

def prompt_quiz_duration(update: Update, context: CallbackContext) -> int:
    """عرض خيارات مدة الاختبار."""
    query = update.callback_query
    query.answer()
    
    # تحديد نوع الاختبار
    quiz_type = 'random'
    if query.data == 'quiz_review_prompt':
        quiz_type = 'review'
    
    # تخزين نوع الاختبار في إعدادات الاختبار
    if 'quiz_settings' not in context.user_data:
        context.user_data['quiz_settings'] = {}
    
    context.user_data['quiz_settings']['type'] = quiz_type
    
    # عرض خيارات مدة الاختبار
    duration_text = "⏱️ **اختيار مدة الاختبار**\n\nاختر المدة المناسبة للاختبار:"
    reply_markup = create_quiz_duration_keyboard()
    query.edit_message_text(duration_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    return SELECT_QUIZ_DURATION

def handle_quiz_duration_selection(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار مدة الاختبار وبدء الاختبار."""
    query = update.callback_query
    query.answer()
    
    # استخراج مدة الاختبار من البيانات
    duration_minutes = int(query.data.split('_')[-1])
    
    # تخزين مدة الاختبار في إعدادات الاختبار
    context.user_data['quiz_settings']['duration_minutes'] = duration_minutes
    
    # بدء الاختبار
    start_quiz(update, context)
    
    return ConversationHandler.END

def start_quiz(update: Update, context: CallbackContext) -> None:
    """بدء اختبار جديد."""
    query = update.callback_query
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # التحقق من وجود إعدادات الاختبار
    if 'quiz_settings' not in context.user_data:
        query.edit_message_text(
            "⚠️ حدث خطأ أثناء بدء الاختبار. يرجى المحاولة مرة أخرى.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data='menu_quiz')]])
        )
        return
    
    quiz_settings = context.user_data['quiz_settings']
    quiz_type = quiz_settings.get('type', 'random')
    duration_minutes = quiz_settings.get('duration_minutes', DEFAULT_QUIZ_DURATION_MINUTES)
    
    # جلب الأسئلة حسب نوع الاختبار
    questions = []
    
    if quiz_type == 'random':
        # اختبار عشوائي
        questions = QUIZ_DB.get_random_questions(DEFAULT_QUIZ_QUESTIONS)
        quiz_name = "اختبار عشوائي"
    
    elif quiz_type == 'review':
        # اختبار مراجعة الأخطاء
        questions = QUIZ_DB.get_review_questions(user_id, DEFAULT_QUIZ_QUESTIONS)
        quiz_name = "مراجعة الأخطاء"
    
    elif quiz_type == 'chapter':
        # اختبار حسب الفصل
        chapter_id = quiz_settings.get('chapter_id')
        chapter_name = quiz_settings.get('chapter_name', 'فصل غير معروف')
        questions = QUIZ_DB.get_questions_by_chapter(chapter_id, DEFAULT_QUIZ_QUESTIONS)
        quiz_name = f"اختبار الفصل: {chapter_name}"
    
    elif quiz_type == 'lesson':
        # اختبار حسب الدرس
        lesson_id = quiz_settings.get('lesson_id')
        lesson_name = quiz_settings.get('lesson_name', 'درس غير معروف')
        questions = QUIZ_DB.get_questions_by_lesson(lesson_id, DEFAULT_QUIZ_QUESTIONS)
        quiz_name = f"اختبار الدرس: {lesson_name}"
    
    elif quiz_type == 'grade_level':
        # اختبار حسب المرحلة الدراسية
        grade_level_id = quiz_settings.get('grade_level_id')
        grade_level_name = quiz_settings.get('grade_level_name', 'مرحلة غير معروفة')
        
        if grade_level_id is None:
            # اختبار تحصيلي عام (جميع المراحل)
            questions = QUIZ_DB.get_random_questions(DEFAULT_QUIZ_QUESTIONS)
            quiz_name = "اختبار تحصيلي عام"
        else:
            # اختبار لمرحلة دراسية محددة
            questions = QUIZ_DB.get_questions_by_grade_level(grade_level_id, DEFAULT_QUIZ_QUESTIONS)
            quiz_name = f"اختبار المرحلة: {grade_level_name}"
    
    # التحقق من وجود أسئلة كافية
    if not questions or len(questions) < 3:  # على الأقل 3 أسئلة للاختبار
        query.edit_message_text(
            "⚠️ لا توجد أسئلة كافية لهذا النوع من الاختبارات. يرجى اختيار نوع آخر.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data='menu_quiz')]])
        )
        return
    
    # إنشاء اختبار جديد في قاعدة البيانات
    quiz_id = QUIZ_DB.create_quiz(
        user_id=user_id,
        quiz_type=quiz_type,
        grade_level_id=quiz_settings.get('grade_level_id'),
        chapter_id=quiz_settings.get('chapter_id'),
        lesson_id=quiz_settings.get('lesson_id'),
        total_questions=len(questions)
    )
    
    if not quiz_id:
        query.edit_message_text(
            "⚠️ حدث خطأ أثناء إنشاء الاختبار. يرجى المحاولة مرة أخرى.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data='menu_quiz')]])
        )
        return
    
    # تخزين بيانات الاختبار في بيانات المستخدم
    context.user_data['quiz'] = {
        'id': quiz_id,
        'type': quiz_type,
        'name': quiz_name,
        'questions': questions,
        'current_question_index': 0,
        'correct_answers': 0,
        'start_time': time.time(),
        'duration_minutes': duration_minutes
    }
    
    # تعيين حالة المحادثة
    context.user_data['conversation_state'] = 'in_quiz'
    
    # إعداد مؤقت للاختبار إذا كان هناك وقت محدد
    if duration_minutes > 0:
        quiz_timer_job = set_quiz_timer(context, chat_id, user_id, quiz_id, duration_minutes)
        context.user_data['quiz_timer_job'] = quiz_timer_job
    
    # عرض رسالة بدء الاختبار
    start_text = (
        f"🏁 **بدء {quiz_name}** 🏁\n\n"
        f"• عدد الأسئلة: {len(questions)}\n"
    )
    
    if duration_minutes > 0:
        start_text += f"• المدة: {duration_minutes} دقيقة\n"
    else:
        start_text += "• المدة: غير محددة\n"
    
    start_text += f"• وقت كل سؤال: {QUESTION_TIMER_SECONDS // 60} دقائق\n\n"
    start_text += "سيتم الانتقال تلقائياً للسؤال التالي بعد انتهاء وقت السؤال.\n\n"
    start_text += "استعد... الاختبار سيبدأ الآن!"
    
    query.edit_message_text(start_text, parse_mode=ParseMode.MARKDOWN)
    
    # عرض السؤال الأول بعد ثانيتين
    context.job_queue.run_once(
        lambda ctx: show_next_question(update, ctx),
        2,
        context=None
    )

def show_next_question(update: Update, context: CallbackContext) -> None:
    """عرض السؤال التالي في الاختبار."""
    query = update.callback_query
    if query:
        query.answer()
    
    user_data = context.user_data
    
    # التحقق من وجود اختبار نشط
    if 'quiz' not in user_data or user_data.get('conversation_state') != 'in_quiz':
        if query:
            query.edit_message_text(
                "⚠️ لا يوجد اختبار نشط. يرجى بدء اختبار جديد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data='menu_quiz')]])
            )
        return
    
    quiz_data = user_data['quiz']
    current_index = quiz_data['current_question_index']
    questions = quiz_data['questions']
    
    # إزالة مؤقت السؤال السابق إذا كان موجوداً
    remove_question_timer(context)
    
    # التحقق مما إذا كان الاختبار قد انتهى
    if current_index >= len(questions):
        end_quiz(update, context)
        return

    question = questions[current_index]
    q_text = question.get('question', 'N/A')
    options = question.get('options', [])
    q_image_id = question.get('question_image_id')
    opt_image_ids = question.get('option_image_ids') or [None] * len(options)

    # تنسيق نص السؤال مع المؤقت
    duration_minutes = quiz_data.get('duration_minutes', 0)
    time_elapsed = int(time.time() - quiz_data['start_time'])
    time_remaining_str = ""
    
    if duration_minutes > 0:
        time_remaining = max(0, (duration_minutes * 60) - time_elapsed)
        mins, secs = divmod(time_remaining, 60)
        time_remaining_str = f"⏳ الوقت المتبقي للاختبار: {mins:02d}:{secs:02d}\n"
    
    # إضافة مؤقت السؤال
    question_timer_str = f"⏱️ وقت السؤال: {QUESTION_TIMER_SECONDS // 60} دقائق\n"
    
    question_header = f"**السؤال {current_index + 1} من {len(questions)}**\n{time_remaining_str}{question_timer_str}\n{q_text}"

    keyboard = []
    media_to_send = None
    caption = question_header

    # التحقق من وجود صور للخيارات
    has_option_images = any(opt_image_ids)

    if q_image_id and not has_option_images:
        # إرسال صورة السؤال مع الخيارات كأزرار نصية
        media_to_send = q_image_id
        for i, option in enumerate(options):
            keyboard.append([InlineKeyboardButton(f"{i+1}. {option}", callback_data=f'quiz_answer_{i}')])
    elif has_option_images:
        # إرسال صور الخيارات كمجموعة وسائط، والسؤال في رسالة منفصلة
        media_group = []
        if q_image_id:
             media_group.append(InputMediaPhoto(media=q_image_id, caption=f"صورة السؤال {current_index + 1}"))
             
        option_captions = []
        for i, opt_img_id in enumerate(opt_image_ids):
            option_text = options[i]
            prefix = f"{i+1}. {option_text}"
            if opt_img_id:
                media_group.append(InputMediaPhoto(media=opt_img_id, caption=prefix))
            else:
                option_captions.append(prefix) # إضافة الخيارات النصية إلى الكابشن
        
        caption += "\n\n**الخيارات:**\n" + "\n".join(option_captions)
        
        # إرسال رسالة السؤال أولاً
        try:
            sent_message = context.bot.send_message(chat_id=update.effective_chat.id, text=caption, parse_mode=ParseMode.MARKDOWN)
            # تخزين معرف الرسالة لتعديلها لاحقاً إذا لزم الأمر
            user_data['quiz']['last_message_id'] = sent_message.message_id 
        except Exception as e:
            logger.error(f"Error sending question text before media group: {e}")
            # محاولة إنهاء الاختبار بأمان
            end_quiz(update, context, error_message="حدث خطأ أثناء عرض السؤال.")
            return
            
        # إرسال مجموعة الصور
        if media_group:
            try:
                context.bot.send_media_group(chat_id=update.effective_chat.id, media=media_group)
            except Exception as e:
                logger.error(f"Error sending option images media group: {e}")
                # لا نوقف الاختبار، فقط نسجل الخطأ

        # إنشاء أزرار الأرقام للاختيار
        for i in range(len(options)):
             keyboard.append([InlineKeyboardButton(str(i + 1), callback_data=f'quiz_answer_{i}')])
        media_to_send = None # تم إرسال السؤال والصور بالفعل
        caption = "اختر رقم الإجابة الصحيحة:" # رسالة جديدة للأزرار

    else:
        # لا توجد صور للسؤال أو الخيارات، إرسال نص فقط
        media_to_send = None
        caption = question_header
        for i, option in enumerate(options):
            keyboard.append([InlineKeyboardButton(f"{i+1}. {option}", callback_data=f'quiz_answer_{i}')])

    # إضافة زر إنهاء الاختبار
    keyboard.append([InlineKeyboardButton("⏹️ إنهاء الاختبار", callback_data='quiz_end')])
    reply_markup = InlineKeyboardMarkup(keyboard)

    # إرسال أو تعديل الرسالة
    message_target = update.effective_message
    edit_failed = False
    if query: # إذا كان ناتجاً عن زر (مثل Next)
        try:
            if media_to_send:
                 # لا يمكن تعديل رسالة نصية إلى رسالة وسائط، أرسل جديد
                 query.message.delete() # حذف الرسالة القديمة
                 sent_message = context.bot.send_photo(chat_id=update.effective_chat.id, photo=media_to_send, caption=caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                 user_data['quiz']['last_message_id'] = sent_message.message_id
            else:
                query.edit_message_text(caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                user_data['quiz']['last_message_id'] = query.message.message_id
        except BadRequest as e:
            if "Message to edit not found" in str(e) or "Message can't be edited" in str(e) or "Message is not modified" in str(e):
                 logger.warning(f"Failed to edit message for next question (likely deleted or too old): {e}")
                 edit_failed = True
            else:
                 logger.error(f"Error editing message for next question: {e}")
                 edit_failed = True # Assume failure on other errors too
        except Exception as e:
             logger.error(f"Unexpected error editing message for next question: {e}")
             edit_failed = True
             
        if edit_failed:
             # إرسال رسالة جديدة إذا فشل التعديل
             try:
                 if media_to_send:
                     sent_message = context.bot.send_photo(chat_id=update.effective_chat.id, photo=media_to_send, caption=caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                 else:
                     sent_message = context.bot.send_message(chat_id=update.effective_chat.id, text=caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                 user_data['quiz']['last_message_id'] = sent_message.message_id
             except Exception as send_error:
                 logger.error(f"Failed to send new message for next question after edit failure: {send_error}")
                 # محاولة إنهاء الاختبار بأمان
                 end_quiz(update, context, error_message="حدث خطأ أثناء عرض السؤال التالي.")
                 return
                 
    else: # إذا كان هذا هو السؤال الأول (ليس ناتجاً عن زر)
         if media_to_send:
             sent_message = context.bot.send_photo(chat_id=update.effective_chat.id, photo=media_to_send, caption=caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
         else:
             sent_message = context.bot.send_message(chat_id=update.effective_chat.id, text=caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
         user_data['quiz']['last_message_id'] = sent_message.message_id
    
    # إعداد مؤقت للسؤال (4 دقائق)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    quiz_id = quiz_data['id']
    
    question_timer_job = set_question_timer(context, chat_id, user_id, quiz_id)
    context.user_data['question_timer_job'] = question_timer_job

def handle_quiz_answer(update: Update, context: CallbackContext) -> None:
    """معالجة إجابة المستخدم على سؤال الاختبار."""
    query = update.callback_query
    query.answer()
    user_data = context.user_data

    if 'quiz' not in user_data or user_data.get('conversation_state') != 'in_quiz':
        logger.warning("handle_quiz_answer called outside of an active quiz.")
        try:
            query.edit_message_text("انتهى الاختبار أو تم إلغاؤه.")
        except BadRequest as e:
             if "Message is not modified" not in str(e):
                 logger.error(f"Error editing message in handle_quiz_answer: {e}")
        return

    # إزالة مؤقت السؤال
    remove_question_timer(context)

    quiz_data = user_data['quiz']
    current_index = quiz_data['current_question_index']
    questions = quiz_data['questions']
    question = questions[current_index]
    correct_index = question.get('correct_answer', -1)
    
    # استخراج إجابة المستخدم
    user_answer_index = int(query.data.split('_')[-1])
    is_correct = (user_answer_index == correct_index)

    # تسجيل الإجابة في قاعدة البيانات
    quiz_id = quiz_data['id']
    question_id = question['id']
    QUIZ_DB.record_answer(quiz_id, question_id, user_answer_index, is_correct)

    # تحديث النتيجة
    if is_correct:
        quiz_data['correct_answers'] += 1
        feedback_text = "✅ إجابة صحيحة!" 
    else:
        feedback_text = f"❌ إجابة خاطئة. الإجابة الصحيحة هي: {correct_index + 1}"
        # عرض الشرح إذا وجد
        explanation = question.get('explanation')
        if explanation:
            feedback_text += f"\n\n**الشرح:** {explanation}"

    # تعديل الرسالة لعرض النتيجة وزر التالي
    keyboard = [[InlineKeyboardButton("التالي ⬅️", callback_data='quiz_next')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        # محاولة تعديل الرسالة الأصلية
        # نحتاج إلى معرف الرسالة الأصلية التي عرضت السؤال
        last_message_id = user_data['quiz'].get('last_message_id')
        if last_message_id:
             context.bot.edit_message_text(
                 chat_id=update.effective_chat.id,
                 message_id=last_message_id,
                 text=query.message.text + "\n\n" + feedback_text, # إضافة النتيجة للنص الأصلي
                 reply_markup=reply_markup,
                 parse_mode=ParseMode.MARKDOWN
             )
        else:
             # إذا لم نجد معرف الرسالة، نعدل رسالة الزر الحالية
             query.edit_message_text(feedback_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
             user_data['quiz']['last_message_id'] = query.message.message_id # تحديث المعرف
             
    except BadRequest as e:
        if "Message to edit not found" in str(e) or "Message can't be edited" in str(e) or "Message is not modified" in str(e):
            logger.warning(f"Failed to edit message for answer feedback (likely deleted or too old): {e}")
            # إرسال رسالة جديدة إذا فشل التعديل
            try:
                sent_message = query.message.reply_text(feedback_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                user_data['quiz']['last_message_id'] = sent_message.message_id
            except Exception as send_error:
                logger.error(f"Failed to send new message for answer feedback after edit failure: {send_error}")
        else:
            logger.error(f"Error editing message for answer feedback: {e}")
            # إرسال رسالة جديدة كحل بديل
            try:
                sent_message = query.message.reply_text(feedback_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                user_data['quiz']['last_message_id'] = sent_message.message_id
            except Exception as send_error:
                logger.error(f"Failed to send new message for answer feedback after edit failure: {send_error}")
    except Exception as e:
        logger.error(f"Unexpected error editing message for answer feedback: {e}")
        # إرسال رسالة جديدة كحل بديل
        try:
            sent_message = query.message.reply_text(feedback_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            user_data['quiz']['last_message_id'] = sent_message.message_id
        except Exception as send_error:
            logger.error(f"Failed to send new message for answer feedback after edit failure: {send_error}")

    # الانتقال للسؤال التالي
    quiz_data['current_question_index'] += 1
    # لا نستدعي show_next_question هنا، ننتظر المستخدم ليضغط "التالي"

def end_quiz(update: Update, context: CallbackContext, error_message: str = None) -> None:
    """إنهاء الاختبار وعرض النتائج."""
    query = update.callback_query
    if query:
        query.answer()
        
    user_data = context.user_data
    if 'quiz' not in user_data or user_data.get('conversation_state') != 'in_quiz':
        logger.warning("end_quiz called outside of an active quiz.")
        if query:
            try:
                query.edit_message_text("انتهى الاختبار بالفعل أو تم إلغاؤه.")
            except BadRequest as e:
                 if "Message is not modified" not in str(e):
                     logger.error(f"Error editing message in end_quiz: {e}")
        return

    quiz_data = user_data['quiz']
    quiz_id = quiz_data['id']
    correct_answers = quiz_data['correct_answers']
    total_questions = len(quiz_data['questions'])
    
    # إزالة مؤقت الاختبار إذا كان موجوداً
    remove_quiz_timer(context)
    
    # إزالة مؤقت السؤال إذا كان موجوداً
    remove_question_timer(context)

    # إنهاء الاختبار في قاعدة البيانات
    QUIZ_DB.end_quiz(quiz_id, correct_answers)
    
    # جلب تقرير الاختبار
    report = QUIZ_DB.get_quiz_report(quiz_id)
    
    if error_message:
        result_text = f"⚠️ {error_message}\n\nتم إنهاء الاختبار." 
    elif report:
        score_percentage = report.get('score_percentage', 0)
        time_taken_seconds = report.get('time_taken', 0)
        mins, secs = divmod(time_taken_seconds, 60)
        time_taken_str = f"{mins} دقيقة و {secs} ثانية"
        
        result_text = (
            f"🏁 **نتائج الاختبار (ID: {quiz_id})** 🏁\n\n"
            f"عدد الأسئلة: {total_questions}\n"
            f"الإجابات الصحيحة: {correct_answers}\n"
            f"النسبة المئوية: {score_percentage}%\n"
            f"الوقت المستغرق: {time_taken_str}\n\n"
        )
        if score_percentage >= 80:
            result_text += "🎉 أداء رائع!"
        elif score_percentage >= 50:
            result_text += "👍 جيد جداً!"
        else:
            result_text += "😕 تحتاج إلى المزيد من المراجعة."
    else:
         result_text = f"🏁 **نتائج الاختبار** 🏁\n\nحدث خطأ أثناء جلب التقرير المفصل."
         result_text += f"\nالإجابات الصحيحة: {correct_answers} من {total_questions}"

    # تنظيف بيانات المستخدم
    del user_data['quiz']
    if 'quiz_settings' in user_data:
        del user_data['quiz_settings']
    if 'conversation_state' in user_data:
        del user_data['conversation_state']

    # عرض النتائج مع زر للعودة للقائمة الرئيسية وزر لعرض التقرير المفصل
    keyboard = [
        [InlineKeyboardButton("📊 عرض التقرير المفصل", callback_data=f'view_report_{quiz_id}')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message_target = update.effective_message
    if query:
        try:
            query.edit_message_text(result_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except BadRequest as e:
            if "Message to edit not found" in str(e) or "Message can't be edited" in str(e) or "Message is not modified" in str(e):
                logger.warning(f"Failed to edit message for quiz results: {e}")
                message_target.reply_text(result_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            else:
                logger.error(f"Error editing message for quiz results: {e}")
                message_target.reply_text(result_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Unexpected error editing message for quiz results: {e}")
            message_target.reply_text(result_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else: # إذا انتهى الاختبار بسبب الوقت
        message_target.reply_text(result_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

def end_quiz_timeout(context: CallbackContext):
    """يتم استدعاؤها بواسطة المؤقت لإنهاء الاختبار."""
    job_context = context.job.context
    chat_id = job_context['chat_id']
    user_id = job_context['user_id']
    quiz_id = job_context['quiz_id']
    logger.info(f"Quiz timeout reached for quiz {quiz_id}, user {user_id}")

    # التحقق مما إذا كان الاختبار لا يزال نشطاً لهذا المستخدم
    user_data = context.dispatcher.user_data.get(user_id, {})
    if user_data.get('conversation_state') == 'in_quiz' and user_data.get('quiz', {}).get('id') == quiz_id:
        logger.info(f"Ending quiz {quiz_id} due to timeout.")
        
        # إنهاء الاختبار في قاعدة البيانات
        quiz_data = user_data['quiz']
        correct_answers = quiz_data['correct_answers']
        QUIZ_DB.end_quiz(quiz_id, correct_answers)
        
        # جلب التقرير
        report = QUIZ_DB.get_quiz_report(quiz_id)
        total_questions = len(quiz_data['questions'])
        
        if report:
            score_percentage = report.get('score_percentage', 0)
            time_taken_seconds = report.get('time_taken', 0)
            mins, secs = divmod(time_taken_seconds, 60)
            time_taken_str = f"{mins} دقيقة و {secs} ثانية"
            
            result_text = (
                f"⏱️ **انتهى وقت الاختبار!** ⏱️\n\n"
                f"🏁 **نتائج الاختبار (ID: {quiz_id})** 🏁\n\n"
                f"عدد الأسئلة: {total_questions}\n"
                f"الأسئلة المجابة: {quiz_data['current_question_index']}\n"
                f"الإجابات الصحيحة: {correct_answers}\n"
                f"النسبة المئوية: {score_percentage}%\n"
                f"الوقت المستغرق: {time_taken_str}\n\n"
            )
            if score_percentage >= 80:
                result_text += "🎉 أداء رائع!"
            elif score_percentage >= 50:
                result_text += "👍 جيد جداً!"
            else:
                result_text += "😕 تحتاج إلى المزيد من المراجعة."
        else:
            result_text = (
                f"⏱️ **انتهى وقت الاختبار!** ⏱️\n\n"
                f"🏁 **نتائج الاختبار** 🏁\n\n"
                f"حدث خطأ أثناء جلب التقرير المفصل.\n"
                f"الإجابات الصحيحة: {correct_answers} من {total_questions}"
            )
        
        # تنظيف بيانات المستخدم
        if 'quiz' in user_data:
            del user_data['quiz']
        if 'quiz_settings' in user_data:
            del user_data['quiz_settings']
        if 'conversation_state' in user_data:
            del user_data['conversation_state']
        
        # عرض النتائج مع زر للعودة للقائمة الرئيسية وزر لعرض التقرير المفصل
        keyboard = [
            [InlineKeyboardButton("📊 عرض التقرير المفصل", callback_data=f'view_report_{quiz_id}')],
            [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        context.bot.send_message(
            chat_id=chat_id,
            text=result_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

# --- وظائف معالجة الاستعلامات النصية ---

def handle_info_query(update: Update, context: CallbackContext) -> None:
    """معالجة استعلامات المعلومات النصية."""
    query_text = update.message.text.strip()
    
    # التحقق مما إذا كان المستخدم في محادثة نشطة
    if context.user_data.get('conversation_state') in ['adding_question', 'adding_options', 'adding_correct_answer', 'adding_explanation']:
        # المستخدم في وضع إضافة سؤال، لا نعالج الاستعلام
        return
    
    # البحث في العناصر
    element_info = None
    for symbol, element in ELEMENTS.items():
        if query_text.upper() == symbol or query_text.lower() == element['name'].lower():
            element_info = element
            element_info['symbol'] = symbol
            break
    
    if element_info:
        # تنسيق معلومات العنصر
        response = (
            f"**{element_info['name']} ({element_info['symbol']})**\n\n"
            f"الرقم الذري: {element_info['atomic_number']}\n"
            f"الكتلة الذرية: {element_info['atomic_mass']}\n"
            f"التصنيف: {element_info['category']}\n"
            f"الحالة: {element_info['state']}\n\n"
            f"**الوصف:**\n{element_info['description']}"
        )
        
        # إضافة زر للعودة للقائمة الرئيسية
        keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(response, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return
    
    # البحث في المركبات
    compound_info = None
    for formula, compound in COMPOUNDS.items():
        if query_text.upper() == formula or query_text.lower() == compound['name'].lower():
            compound_info = compound
            compound_info['formula'] = formula
            break
    
    if compound_info:
        # تنسيق معلومات المركب
        response = (
            f"**{compound_info['name']} ({compound_info['formula']})**\n\n"
            f"التصنيف: {compound_info['category']}\n"
            f"الحالة: {compound_info['state']}\n\n"
            f"**الوصف:**\n{compound_info['description']}\n\n"
            f"**الاستخدامات:**\n{compound_info['uses']}"
        )
        
        # إضافة زر للعودة للقائمة الرئيسية
        keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(response, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return
    
    # البحث في المفاهيم
    concept_info = None
    for concept_name, concept in CONCEPTS.items():
        if query_text.lower() in concept_name.lower():
            concept_info = concept
            concept_info['name'] = concept_name
            break
    
    if concept_info:
        # تنسيق معلومات المفهوم
        response = (
            f"**{concept_info['name']}**\n\n"
            f"**التعريف:**\n{concept_info['definition']}\n\n"
            f"**الأمثلة:**\n{concept_info['examples']}"
        )
        
        # إضافة زر للعودة للقائمة الرئيسية
        keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(response, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return
    
    # البحث في معلومات الجدول الدوري
    if "جدول" in query_text.lower() and "دوري" in query_text.lower():
        response = PERIODIC_TABLE_INFO
        
        # إضافة زر للعودة للقائمة الرئيسية
        keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(response, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return
    
    # البحث في معلومات الحسابات الكيميائية
    if "حساب" in query_text.lower() or "معادل" in query_text.lower():
        response = CHEMICAL_CALCULATIONS_INFO
        
        # إضافة زر للعودة للقائمة الرئيسية
        keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(response, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return
    
    # البحث في معلومات الروابط الكيميائية
    if "رابط" in query_text.lower() or "روابط" in query_text.lower():
        response = CHEMICAL_BONDS_INFO
        
        # إضافة زر للعودة للقائمة الرئيسية
        keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(response, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return
    
    # معالجة المعادلات الكيميائية
    if "+" in query_text or "->" in query_text or "→" in query_text:
        try:
            formatted_equation = format_chemical_equation(query_text)
            response = f"**المعادلة الكيميائية:**\n{formatted_equation}"
            
            # إضافة زر للعودة للقائمة الرئيسية
            keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            update.message.reply_text(response, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            return
        except Exception as e:
            logger.error(f"Error formatting chemical equation: {e}")
    
    # إذا لم يتم العثور على معلومات مطابقة
    response = "لم أجد معلومات تطابق استعلامك. حاول البحث عن:\n- رمز عنصر (مثل H)\n- صيغة مركب (مثل H2O)\n- اسم مفهوم كيميائي"
    
    # إضافة زر للعودة للقائمة الرئيسية
    keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(response, reply_markup=reply_markup)

# --- وظائف معالجة الأخطاء ---

def error_handler(update: Update, context: CallbackContext) -> None:
    """معالجة الأخطاء."""
    logger.error(f"Update {update} caused error {context.error}")
    
    try:
        if update and update.effective_message:
            update.effective_message.reply_text(
                "حدث خطأ أثناء معالجة طلبك. يرجى المحاولة مرة أخرى لاحقاً.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]])
            )
    except Exception as e:
        logger.error(f"Error in error handler: {e}")

# --- الوظيفة الرئيسية ---

def main():
    """الوظيفة الرئيسية لتشغيل البوت."""
    # إنشاء Updater
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher
    
    # إضافة معالجات الأوامر
    dispatcher.add_handler(CommandHandler('start', start_command))
    dispatcher.add_handler(CommandHandler('about', about_command))
    
    # إضافة معالج أزرار القوائم الرئيسية
    dispatcher.add_handler(CallbackQueryHandler(main_menu_button_handler))
    
    # إضافة معالج الاختبارات
    dispatcher.add_handler(CallbackQueryHandler(show_next_question, pattern='^quiz_next$'))
    dispatcher.add_handler(CallbackQueryHandler(handle_quiz_answer, pattern='^quiz_answer_'))
    dispatcher.add_handler(CallbackQueryHandler(end_quiz, pattern='^quiz_end$'))
    
    # إضافة معالج استعلامات المعلومات النصية
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_info_query))
    
    # إضافة معالج الأخطاء
    dispatcher.add_error_handler(error_handler)
    
    # بدء البوت
    updater.start_polling()
    logger.info("Bot started polling...")
    
    # تشغيل البوت حتى تضغط Ctrl-C
    updater.idle()
    
    # إغلاق اتصال قاعدة البيانات عند إيقاف البوت
    QUIZ_DB.close_connection()

if __name__ == '__main__':
    main()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto