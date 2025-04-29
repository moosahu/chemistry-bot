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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
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
        return MAIN_MENU
    
    # معالجة زر قائمة الاختبارات
    elif query.data == 'menu_quiz':
        quiz_text = (
            "📝 **الاختبارات**\n\n"
            "اختر نوع الاختبار الذي ترغب في إجرائه:"
        )
        
        reply_markup = create_quiz_menu_keyboard()
        query.edit_message_text(quiz_text, reply_markup=reply_markup)
        return QUIZ_MENU
    
    # معالجة زر تقارير الأداء
    elif query.data == 'menu_reports':
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
                quiz_id = report['quiz_id']
                quiz_type = report['quiz_type']
                score = report['score_percentage']
                date = report['date']
                
                reports_text += (
                    f"**{i}. {quiz_type}**\n"
                    f"التاريخ: {date}\n"
                    f"النتيجة: {score}%\n"
                    f"معرف الاختبار: {quiz_id}\n\n"
                )
            
            if len(reports) > 5:
                reports_text += f"*وأكثر من ذلك... ({len(reports) - 5} اختبارات إضافية)*"
        
        keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        query.edit_message_text(reports_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return MAIN_MENU
    
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
        
        query.edit_message_text(about_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return MAIN_MENU
    
    # معالجة زر قائمة الإدارة (للمسؤولين فقط)
    elif query.data == 'menu_admin':
        if not is_admin(user_id):
            query.edit_message_text(
                "⛔ غير مصرح لك بالوصول إلى هذا القسم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]])
            )
            return MAIN_MENU
        
        admin_text = (
            "⚙️ **إدارة الأسئلة**\n\n"
            "اختر العملية التي ترغب في إجرائها:"
        )
        
        reply_markup = create_admin_menu_keyboard()
        query.edit_message_text(admin_text, reply_markup=reply_markup)
        return ADMIN_MENU
    
    return MAIN_MENU

# --- وظائف معالجة أزرار قائمة الاختبارات ---

def quiz_menu_button_handler(update: Update, context: CallbackContext) -> None:
    """معالجة أزرار قائمة الاختبارات."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
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
        query.edit_message_text(duration_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return SELECTING_QUIZ_DURATION
    
    # معالجة زر الاختبار حسب الفصل
    elif query.data == 'quiz_by_chapter_prompt':
        # عرض خيارات المراحل الدراسية أولاً
        grade_text = (
            "🏫 **اختيار المرحلة الدراسية**\n\n"
            "اختر المرحلة الدراسية للاختبار:"
        )
        
        reply_markup = create_grade_levels_keyboard(for_quiz=True)
        query.edit_message_text(grade_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return SELECT_GRADE_LEVEL_FOR_QUIZ
    
    # معالجة زر الاختبار حسب الدرس
    elif query.data == 'quiz_by_lesson_prompt':
        # عرض خيارات المراحل الدراسية أولاً
        grade_text = (
            "🏫 **اختيار المرحلة الدراسية**\n\n"
            "اختر المرحلة الدراسية للاختبار:"
        )
        
        reply_markup = create_grade_levels_keyboard(for_quiz=True)
        query.edit_message_text(grade_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return SELECT_GRADE_LEVEL_FOR_QUIZ
    
    # معالجة زر الاختبار حسب المرحلة الدراسية
    elif query.data == 'quiz_by_grade_prompt':
        grade_text = (
            "🏫 **اختيار المرحلة الدراسية**\n\n"
            "اختر المرحلة الدراسية للاختبار:"
        )
        
        reply_markup = create_grade_levels_keyboard(for_quiz=True)
        query.edit_message_text(grade_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return SELECT_GRADE_LEVEL_FOR_QUIZ
    
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
        query.edit_message_text(duration_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return SELECTING_QUIZ_DURATION
    
    return QUIZ_MENU

# --- وظائف معالجة اختيار المرحلة الدراسية ---

def grade_level_selection_handler(update: Update, context: CallbackContext) -> None:
    """معالجة اختيار المرحلة الدراسية."""
    query = update.callback_query
    query.answer()
    
    # التحقق من نوع الاختيار (للاختبار أو للإدارة)
    if query.data.startswith('select_grade_quiz_'):
        # اختيار المرحلة للاختبار
        grade_id = query.data.replace('select_grade_quiz_', '')
        
        if grade_id == 'all':
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
            query.edit_message_text(duration_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            return SELECTING_QUIZ_DURATION
        else:
            # تخزين معرف المرحلة المختارة
            context.user_data['selected_grade_id'] = int(grade_id)
            
            # التحقق من الخطوة التالية (اختيار فصل أو درس أو بدء اختبار المرحلة)
            if 'next_step' in context.user_data:
                if context.user_data['next_step'] == 'select_chapter':
                    # عرض قائمة الفصول للمرحلة المختارة
                    chapter_text = (
                        f"📚 **اختيار الفصل**\n\n"
                        f"اختر الفصل للاختبار:"
                    )
                    
                    reply_markup = create_chapters_keyboard(int(grade_id), for_quiz=True)
                    query.edit_message_text(chapter_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                    return SELECT_CHAPTER_FOR_QUIZ
                
                elif context.user_data['next_step'] == 'select_lesson':
                    # عرض قائمة الفصول للمرحلة المختارة (لاختيار درس)
                    chapter_text = (
                        f"📚 **اختيار الفصل**\n\n"
                        f"اختر الفصل الذي يحتوي على الدرس المطلوب:"
                    )
                    
                    reply_markup = create_chapters_keyboard(int(grade_id), for_lesson=True)
                    query.edit_message_text(chapter_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                    return SELECT_CHAPTER_FOR_LESSON
                
                # تنظيف متغير الخطوة التالية
                del context.user_data['next_step']
            else:
                # اختبار حسب المرحلة الدراسية
                context.user_data['quiz_settings'] = {
                    'type': 'by_grade',
                    'grade_id': int(grade_id),
                    'num_questions': DEFAULT_QUIZ_QUESTIONS
                }
                
                # عرض خيارات مدة الاختبار
                duration_text = (
                    "⏱️ **اختيار مدة الاختبار**\n\n"
                    "اختر المدة المناسبة لإجراء الاختبار:"
                )
                
                reply_markup = create_quiz_duration_keyboard()
                query.edit_message_text(duration_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                return SELECTING_QUIZ_DURATION
    
    elif query.data.startswith('select_grade_'):
        # اختيار المرحلة للإدارة
        grade_id = query.data.replace('select_grade_', '')
        
        # تخزين معرف المرحلة المختارة
        context.user_data['selected_grade_id'] = int(grade_id)
        
        # عرض قائمة الفصول للمرحلة المختارة
        chapter_text = (
            f"📚 **إدارة الفصول**\n\n"
            f"اختر الفصل للإدارة:"
        )
        
        reply_markup = create_chapters_keyboard(int(grade_id))
        query.edit_message_text(chapter_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return ADMIN_CHAPTER_MENU
    
    return MAIN_MENU

# --- وظائف معالجة اختيار الفصل ---

def chapter_selection_handler(update: Update, context: CallbackContext) -> None:
    """معالجة اختيار الفصل."""
    query = update.callback_query
    query.answer()
    
    # التحقق من نوع الاختيار (للاختبار أو للإدارة)
    if query.data.startswith('select_chapter_quiz_'):
        # اختيار الفصل للاختبار
        chapter_id = query.data.replace('select_chapter_quiz_', '')
        
        # تخزين إعدادات الاختبار
        context.user_data['quiz_settings'] = {
            'type': 'by_chapter',
            'chapter_id': int(chapter_id),
            'num_questions': DEFAULT_QUIZ_QUESTIONS
        }
        
        # عرض خيارات مدة الاختبار
        duration_text = (
            "⏱️ **اختيار مدة الاختبار**\n\n"
            "اختر المدة المناسبة لإجراء الاختبار:"
        )
        
        reply_markup = create_quiz_duration_keyboard()
        query.edit_message_text(duration_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return SELECTING_QUIZ_DURATION
    
    elif query.data.startswith('select_chapter_lesson_'):
        # اختيار الفصل لاختيار درس منه
        chapter_id = query.data.replace('select_chapter_lesson_', '')
        
        # تخزين معرف الفصل المختار
        context.user_data['selected_chapter_id'] = int(chapter_id)
        
        # عرض قائمة الدروس للفصل المختار
        lesson_text = (
            f"📝 **اختيار الدرس**\n\n"
            f"اختر الدرس للاختبار:"
        )
        
        reply_markup = create_lessons_keyboard(int(chapter_id), for_quiz=True)
        query.edit_message_text(lesson_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return SELECT_LESSON_FOR_QUIZ
    
    elif query.data.startswith('select_chapter_'):
        # اختيار الفصل للإدارة
        chapter_id = query.data.replace('select_chapter_', '')
        
        # تخزين معرف الفصل المختار
        context.user_data['selected_chapter_id'] = int(chapter_id)
        
        # عرض قائمة الدروس للفصل المختار
        lesson_text = (
            f"📝 **إدارة الدروس**\n\n"
            f"اختر الدرس للإدارة:"
        )
        
        reply_markup = create_lessons_keyboard(int(chapter_id))
        query.edit_message_text(lesson_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return ADMIN_LESSON_MENU
    
    return MAIN_MENU

# --- وظائف معالجة اختيار الدرس ---

def lesson_selection_handler(update: Update, context: CallbackContext) -> None:
    """معالجة اختيار الدرس."""
    query = update.callback_query
    query.answer()
    
    # التحقق من نوع الاختيار (للاختبار أو للإدارة)
    if query.data.startswith('select_lesson_quiz_'):
        # اختيار الدرس للاختبار
        lesson_id = query.data.replace('select_lesson_quiz_', '')
        
        # تخزين إعدادات الاختبار
        context.user_data['quiz_settings'] = {
            'type': 'by_lesson',
            'lesson_id': int(lesson_id),
            'num_questions': DEFAULT_QUIZ_QUESTIONS
        }
        
        # عرض خيارات مدة الاختبار
        duration_text = (
            "⏱️ **اختيار مدة الاختبار**\n\n"
            "اختر المدة المناسبة لإجراء الاختبار:"
        )
        
        reply_markup = create_quiz_duration_keyboard()
        query.edit_message_text(duration_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return SELECTING_QUIZ_DURATION
    
    elif query.data.startswith('select_lesson_'):
        # اختيار الدرس للإدارة
        lesson_id = query.data.replace('select_lesson_', '')
        
        # تخزين معرف الدرس المختار
        context.user_data['selected_lesson_id'] = int(lesson_id)
        
        # عرض خيارات إدارة الدرس
        lesson_admin_text = (
            f"📝 **إدارة الدرس**\n\n"
            f"اختر العملية التي ترغب في إجرائها:"
        )
        
        keyboard = [
            [InlineKeyboardButton("➕ إضافة سؤال للدرس", callback_data=f'add_question_to_lesson_{lesson_id}')],
            [InlineKeyboardButton("🔍 عرض أسئلة الدرس", callback_data=f'view_lesson_questions_{lesson_id}')],
            [InlineKeyboardButton("🔙 العودة لقائمة الدروس", callback_data=f'back_to_lessons_{context.user_data["selected_chapter_id"]}')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        query.edit_message_text(lesson_admin_text, reply_markup=reply_markup)
        return ADMIN_LESSON_MENU
    
    return MAIN_MENU

# --- وظائف معالجة اختيار مدة الاختبار ---

def quiz_duration_selection_handler(update: Update, context: CallbackContext) -> None:
    """معالجة اختيار مدة الاختبار."""
    query = update.callback_query
    query.answer()
    
    if query.data.startswith('quiz_duration_'):
        # استخراج المدة المختارة بالدقائق
        duration_minutes = int(query.data.replace('quiz_duration_', ''))
        
        # تخزين مدة الاختبار في إعدادات الاختبار
        if 'quiz_settings' in context.user_data:
            context.user_data['quiz_settings']['duration_minutes'] = duration_minutes
            
            # بدء الاختبار
            return start_quiz(update, context)
    
    return QUIZ_MENU

# --- وظائف إدارة الاختبار ---

def start_quiz(update: Update, context: CallbackContext) -> None:
    """بدء اختبار جديد."""
    query = update.callback_query
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # التحقق من وجود إعدادات الاختبار
    if 'quiz_settings' not in context.user_data:
        query.edit_message_text(
            "⚠️ حدث خطأ أثناء بدء الاختبار. يرجى المحاولة مرة أخرى.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]])
        )
        return MAIN_MENU
    
    quiz_settings = context.user_data['quiz_settings']
    quiz_type = quiz_settings['type']
    num_questions = quiz_settings['num_questions']
    duration_minutes = quiz_settings.get('duration_minutes', DEFAULT_QUIZ_DURATION_MINUTES)
    
    # جلب الأسئلة حسب نوع الاختبار
    questions = []
    
    try:
        if quiz_type == 'random':
            questions = QUIZ_DB.get_random_questions(num_questions)
        elif quiz_type == 'by_chapter':
            chapter_id = quiz_settings['chapter_id']
            questions = QUIZ_DB.get_questions_by_chapter(chapter_id, num_questions)
        elif quiz_type == 'by_lesson':
            lesson_id = quiz_settings['lesson_id']
            questions = QUIZ_DB.get_questions_by_lesson(lesson_id, num_questions)
        elif quiz_type == 'by_grade':
            grade_id = quiz_settings.get('grade_id')
            questions = QUIZ_DB.get_questions_by_grade(grade_id, num_questions)
        elif quiz_type == 'review':
            questions = QUIZ_DB.get_incorrect_questions(user_id, num_questions)
    except Exception as e:
        logger.error(f"Error getting questions for quiz: {e}")
        query.edit_message_text(
            "⚠️ حدث خطأ أثناء جلب الأسئلة. يرجى المحاولة مرة أخرى.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]])
        )
        return MAIN_MENU
    
    if not questions:
        query.edit_message_text(
            "⚠️ لا توجد أسئلة كافية لهذا النوع من الاختبارات. يرجى اختيار نوع آخر.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data='menu_quiz')]])
        )
        return QUIZ_MENU
    
    # إنشاء اختبار جديد في قاعدة البيانات
    quiz_id = QUIZ_DB.create_quiz(user_id, quiz_type, len(questions))
    
    if not quiz_id:
        query.edit_message_text(
            "⚠️ حدث خطأ أثناء إنشاء الاختبار. يرجى المحاولة مرة أخرى.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]])
        )
        return MAIN_MENU
    
    # تخزين معلومات الاختبار في بيانات المستخدم
    context.user_data['quiz'] = {
        'id': quiz_id,
        'questions': questions,
        'current_question_index': 0,
        'correct_answers': 0,
        'start_time': datetime.now()
    }
    
    # تعيين حالة المحادثة
    context.user_data['conversation_state'] = 'in_quiz'
    
    # إعداد مؤقت للاختبار إذا كان هناك وقت محدد
    if duration_minutes > 0:
        quiz_timer_job = set_quiz_timer(context, chat_id, user_id, quiz_id, duration_minutes)
        if quiz_timer_job:
            context.user_data['quiz_timer_job'] = quiz_timer_job
    
    # إرسال رسالة بدء الاختبار
    quiz_info_text = (
        f"🎯 **بدء اختبار جديد**\n\n"
        f"نوع الاختبار: {get_quiz_type_name(quiz_type)}\n"
        f"عدد الأسئلة: {len(questions)}\n"
    )
    
    if duration_minutes > 0:
        quiz_info_text += f"المدة: {duration_minutes} دقيقة\n"
    else:
        quiz_info_text += "المدة: غير محددة\n"
    
    quiz_info_text += "\nسيتم عرض السؤال الأول الآن. بالتوفيق! 🍀"
    
    query.edit_message_text(
        quiz_info_text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👉 ابدأ", callback_data='quiz_next')]]),
        parse_mode=ParseMode.MARKDOWN
    )
    
    return TAKING_QUIZ

def get_quiz_type_name(quiz_type):
    """الحصول على اسم نوع الاختبار بالعربية."""
    quiz_types = {
        'random': 'اختبار عشوائي',
        'by_chapter': 'اختبار حسب الفصل',
        'by_lesson': 'اختبار حسب الدرس',
        'by_grade': 'اختبار حسب المرحلة الدراسية',
        'review': 'مراجعة الأخطاء'
    }
    return quiz_types.get(quiz_type, 'اختبار')

def show_next_question(update: Update, context: CallbackContext) -> None:
    """عرض السؤال التالي في الاختبار."""
    query = update.callback_query
    if query:
        query.answer()
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # التحقق من وجود اختبار نشط
    if 'quiz' not in context.user_data or context.user_data.get('conversation_state') != 'in_quiz':
        if query:
            query.edit_message_text(
                "⚠️ لا يوجد اختبار نشط. يرجى بدء اختبار جديد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]])
            )
        else:
            update.effective_message.reply_text(
                "⚠️ لا يوجد اختبار نشط. يرجى بدء اختبار جديد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]])
            )
        return MAIN_MENU
    
    quiz_data = context.user_data['quiz']
    current_index = quiz_data['current_question_index']
    questions = quiz_data['questions']
    
    # التحقق مما إذا كان الاختبار قد انتهى
    if current_index >= len(questions):
        return end_quiz(update, context)
    
    # الحصول على السؤال الحالي
    question = questions[current_index]
    question_id = question['id']
    question_text = question['question']
    options = question['options']
    
    # إزالة مؤقت السؤال السابق إذا كان موجوداً
    remove_question_timer(context)
    
    # إعداد مؤقت جديد للسؤال الحالي
    question_timer_job = set_question_timer(context, chat_id, user_id, quiz_data['id'])
    if question_timer_job:
        context.user_data['question_timer_job'] = question_timer_job
    
    # حساب الوقت المتبقي للسؤال
    remaining_time = QUESTION_TIMER_SECONDS
    
    # إنشاء نص السؤال مع رقم السؤال والوقت المتبقي
    question_text_with_timer = (
        f"⏱️ الوقت المتبقي: {remaining_time // 60}:{remaining_time % 60:02d}\n\n"
        f"❓ **السؤال {current_index + 1} من {len(questions)}**\n\n"
        f"{question_text}"
    )
    
    # إنشاء أزرار الخيارات
    keyboard = []
    for i, option in enumerate(options):
        keyboard.append([InlineKeyboardButton(f"{chr(65 + i)}. {option}", callback_data=f'quiz_answer_{i}')])
    
    # إضافة زر إنهاء الاختبار
    keyboard.append([InlineKeyboardButton("🚫 إنهاء الاختبار", callback_data='quiz_end')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # عرض السؤال
    if query:
        try:
            query.edit_message_text(question_text_with_timer, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # إذا لم يتغير النص، نرسل رسالة جديدة
                update.effective_message.reply_text(question_text_with_timer, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            else:
                logger.error(f"Error editing message for question: {e}")
                update.effective_message.reply_text(question_text_with_timer, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        update.effective_message.reply_text(question_text_with_timer, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    return TAKING_QUIZ

def handle_quiz_answer(update: Update, context: CallbackContext) -> None:
    """معالجة إجابة المستخدم على سؤال في الاختبار."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    
    # التحقق من وجود اختبار نشط
    if 'quiz' not in context.user_data or context.user_data.get('conversation_state') != 'in_quiz':
        query.edit_message_text(
            "⚠️ لا يوجد اختبار نشط. يرجى بدء اختبار جديد.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]])
        )
        return MAIN_MENU
    
    # استخراج رقم الإجابة المختارة
    selected_option = int(query.data.replace('quiz_answer_', ''))
    
    quiz_data = context.user_data['quiz']
    current_index = quiz_data['current_question_index']
    questions = quiz_data['questions']
    
    # التحقق مما إذا كان الاختبار قد انتهى
    if current_index >= len(questions):
        return end_quiz(update, context)
    
    # الحصول على السؤال الحالي
    question = questions[current_index]
    question_id = question['id']
    correct_option = question['correct_option']
    explanation = question.get('explanation', '')
    
    # التحقق مما إذا كانت الإجابة صحيحة
    is_correct = (selected_option == correct_option)
    
    # تسجيل الإجابة في قاعدة البيانات
    QUIZ_DB.record_answer(quiz_data['id'], question_id, selected_option, is_correct)
    
    # تحديث عدد الإجابات الصحيحة
    if is_correct:
        quiz_data['correct_answers'] += 1
    
    # إزالة مؤقت السؤال
    remove_question_timer(context)
    
    # إنشاء نص نتيجة الإجابة
    if is_correct:
        result_text = "✅ **إجابة صحيحة!**\n\n"
    else:
        result_text = f"❌ **إجابة خاطئة!**\n\nالإجابة الصحيحة هي: {chr(65 + correct_option)}. {question['options'][correct_option]}\n\n"
    
    if explanation:
        result_text += f"**الشرح:**\n{explanation}\n\n"
    
    result_text += "انقر على 'التالي' للانتقال إلى السؤال التالي."
    
    # إنشاء زر للانتقال إلى السؤال التالي
    keyboard = [[InlineKeyboardButton("⏭️ التالي", callback_data='quiz_next')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # عرض نتيجة الإجابة
    query.edit_message_text(result_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    # الانتقال إلى السؤال التالي
    quiz_data['current_question_index'] += 1
    
    return TAKING_QUIZ

def end_quiz(update: Update, context: CallbackContext) -> None:
    """إنهاء الاختبار وعرض النتائج."""
    query = update.callback_query
    if query:
        query.answer()
    
    # التحقق من وجود اختبار نشط
    if 'quiz' not in context.user_data:
        if query:
            query.edit_message_text(
                "⚠️ لا يوجد اختبار نشط لإنهائه.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]])
            )
        else:
            update.effective_message.reply_text(
                "⚠️ لا يوجد اختبار نشط لإنهائه.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]])
            )
        return MAIN_MENU
    
    quiz_data = context.user_data['quiz']
    quiz_id = quiz_data['id']
    correct_answers = quiz_data['correct_answers']
    total_questions = len(quiz_data['questions'])
    answered_questions = min(quiz_data['current_question_index'], total_questions)
    
    # إزالة مؤقتات الاختبار
    remove_quiz_timer(context)
    remove_question_timer(context)
    
    # إنهاء الاختبار في قاعدة البيانات
    QUIZ_DB.end_quiz(quiz_id, correct_answers)
    
    # جلب تقرير الاختبار
    report = QUIZ_DB.get_quiz_report(quiz_id)
    
    if report:
        score_percentage = report.get('score_percentage', 0)
        time_taken_seconds = report.get('time_taken', 0)
        mins, secs = divmod(time_taken_seconds, 60)
        time_taken_str = f"{mins} دقيقة و {secs} ثانية"
        
        result_text = (
            f"🏁 **نتائج الاختبار (ID: {quiz_id})** 🏁\n\n"
            f"عدد الأسئلة: {total_questions}\n"
            f"الأسئلة المجابة: {answered_questions}\n"
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
            f"🏁 **نتائج الاختبار** 🏁\n\n"
            f"حدث خطأ أثناء جلب التقرير المفصل.\n"
            f"الإجابات الصحيحة: {correct_answers} من {total_questions}"
        )
    
    # تنظيف بيانات المستخدم
    if 'quiz' in context.user_data:
        del context.user_data['quiz']
    if 'quiz_settings' in context.user_data:
        del context.user_data['quiz_settings']
    if 'conversation_state' in context.user_data:
        del context.user_data['conversation_state']

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
