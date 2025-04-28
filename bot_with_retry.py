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
from datetime import datetime, timedelta # إضافة timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ParseMode
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters, CallbackContext, 
    CallbackQueryHandler, ConversationHandler, JobQueue # إضافة JobQueue
)
from telegram.error import NetworkError, TelegramError, Unauthorized, BadRequest

# استيراد البيانات الثابتة ووظائف المعادلات
from chemistry_data import ELEMENTS, COMPOUNDS, CONCEPTS, PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO
from chemical_equations import process_text_with_chemical_notation, format_chemical_equation

# استيراد الفئة المحسنة لقاعدة البيانات
from quiz_db_enhanced import QuizDatabase

# --- إعدادات --- 
# ضع معرف المستخدم الرقمي الخاص بك هنا لتقييد الوصول إلى إدارة قاعدة البيانات
ADMIN_USER_ID = 6448526509 # !!! استبدل هذا بمعرف المستخدم الرقمي الخاص بك !!!
# توكن البوت
TOKEN = "8167394360:AAG-b3v-VDmxLtWVQCuBkc694Mt3ZCs18IY" # !!! استبدل هذا بتوكن البوت الخاص بك بدقة تامة !!!

# إعدادات الاختبارات
DEFAULT_QUIZ_QUESTIONS = 10
DEFAULT_QUIZ_DURATION_MINUTES = 10 # مدة الاختبار الافتراضية بالدقائق

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
except ValueError as e:
    logger.error(f"Failed to initialize QuizDatabase: {e}")
    sys.exit(f"Error initializing database: {e}")
except Exception as e:
    logger.error(f"An unexpected error occurred during QuizDatabase initialization: {e}")
    sys.exit(f"Unexpected error initializing database: {e}")


# حالات المحادثة لإضافة سؤال وحذف/عرض سؤال
(ADD_QUESTION_TEXT, ADD_OPTIONS, ADD_CORRECT_ANSWER, ADD_EXPLANATION, ADD_CHAPTER, ADD_LESSON, 
 ADD_QUESTION_IMAGE_PROMPT, WAITING_QUESTION_IMAGE, ADD_OPTION_IMAGES_PROMPT, WAITING_OPTION_IMAGE,
 DELETE_CONFIRM, SHOW_ID, SELECT_CHAPTER_FOR_LESSON, SELECT_LESSON, SELECT_CHAPTER_FOR_QUIZ, 
 SELECT_LESSON_FOR_QUIZ, SELECT_QUIZ_DURATION) = range(17) # إضافة حالات جديدة

# --- وظائف التحقق من الصلاحيات ---
def is_admin(user_id: int) -> bool:
    """التحقق مما إذا كان المستخدم هو المسؤول."""
    if ADMIN_USER_ID is None:
        logger.warning("ADMIN_USER_ID غير معين. سيتم السماح للجميع بإدارة قاعدة البيانات.")
        return True # السماح للجميع إذا لم يتم تعيين المسؤول
    return user_id == ADMIN_USER_ID

# --- الدوال المساعدة للقوائم ---
def show_main_menu(update: Update, context: CallbackContext, message_text: str = None) -> None:
    """عرض القائمة الرئيسية مع الأزرار."""
    logger.info("Showing main menu")
    keyboard = [
        [InlineKeyboardButton("📚 المعلومات الكيميائية", callback_data='menu_info')],
        [InlineKeyboardButton("📝 الاختبارات", callback_data='menu_quiz')],
        [InlineKeyboardButton("📊 تقارير الأداء", callback_data='menu_reports')], # زر جديد للتقارير
        [InlineKeyboardButton("ℹ️ حول البوت", callback_data='menu_about')],
    ]
    if is_admin(update.effective_user.id):
        keyboard.append([InlineKeyboardButton("⚙️ إدارة الأسئلة", callback_data='menu_admin')])

    reply_markup = InlineKeyboardMarkup(keyboard)

    if message_text is None:
        user = update.effective_user
        message_text = (
            f"مرحباً بك في بوت الكيمياء التحصيلي 🧪\n\n"
            f"أهلاً {user.first_name}! 👋\n\n"
            f"اختر أحد الخيارات أدناه:"
        )

    if update.callback_query:
        try:
            update.callback_query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.error(f"Error editing message: {e}")
                try:
                    # إرسال رسالة جديدة إذا فشل التعديل (قد تكون الرسالة قديمة جداً)
                    update.effective_message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
                except Exception as send_error:
                     logger.error(f"Failed to send new message after edit error: {send_error}")
    elif update.message:
        update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

def show_admin_menu(update: Update, context: CallbackContext) -> None:
    """عرض قائمة إدارة الأسئلة للمسؤول."""
    logger.info("Showing admin menu")
    if not is_admin(update.effective_user.id):
        update.callback_query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton("➕ إضافة سؤال جديد", callback_data='admin_add')],
        [InlineKeyboardButton("📋 عرض قائمة الأسئلة", callback_data='admin_list')],
        [InlineKeyboardButton("🗑️ حذف سؤال", callback_data='admin_delete_prompt')],
        [InlineKeyboardButton("ℹ️ عرض سؤال معين", callback_data='admin_show_prompt')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.callback_query.edit_message_text("⚙️ اختر عملية إدارة الأسئلة:", reply_markup=reply_markup)

def show_info_menu(update: Update, context: CallbackContext) -> None:
    """عرض قائمة المعلومات الكيميائية."""
    logger.info("Showing info menu")
    keyboard = [
        [InlineKeyboardButton("🧪 العناصر الكيميائية", callback_data='info_elements')],
        [InlineKeyboardButton("🔬 المركبات الكيميائية", callback_data='info_compounds')],
        [InlineKeyboardButton("📘 المفاهيم الكيميائية", callback_data='info_concepts')],
        [InlineKeyboardButton("📊 الجدول الدوري", callback_data='info_periodic_table')],
        [InlineKeyboardButton("🔢 الحسابات الكيميائية", callback_data='info_calculations')],
        [InlineKeyboardButton("🔗 الروابط الكيميائية", callback_data='info_bonds')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.callback_query.edit_message_text("📚 اختر نوع المعلومات الكيميائية:", reply_markup=reply_markup)

def show_quiz_menu(update: Update, context: CallbackContext) -> None:
    """عرض قائمة الاختبارات."""
    logger.info("Showing quiz menu")
    keyboard = [
        [InlineKeyboardButton("🎯 اختبار عشوائي", callback_data='quiz_random_prompt')],
        [InlineKeyboardButton("📑 اختبار حسب الفصل", callback_data='quiz_by_chapter_prompt')],
        [InlineKeyboardButton("📝 اختبار حسب الدرس", callback_data='quiz_by_lesson_prompt')],
        [InlineKeyboardButton("🔄 مراجعة الأخطاء", callback_data='quiz_review_prompt')], # زر جديد للمراجعة
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.callback_query.edit_message_text("📝 اختر نوع الاختبار:", reply_markup=reply_markup)

# --- معالجات الأوامر الأساسية ---
def start_command(update: Update, context: CallbackContext) -> None:
    """معالجة الأمر /start."""
    user_id = update.effective_user.id
    logger.info(f"Received /start command from user {user_id}")
    # إيقاف أي محادثة نشطة عند البدء
    if 'conversation_state' in context.user_data:
        logger.info(f"Ending active conversation for user {user_id} due to /start command.")
        # إزالة مؤقت الاختبار إذا كان موجوداً
        remove_quiz_timer(context)
        del context.user_data['conversation_state']
    show_main_menu(update, context)

def about_command(update: Update, context: CallbackContext) -> None:
    """عرض معلومات حول البوت."""
    about_text = (
        "ℹ️ **حول بوت الكيمياء التحصيلي** 🧪\n\n"
        "تم تصميم هذا البوت لمساعدتك في الاستعداد لاختبار التحصيلي في مادة الكيمياء.\n\n"
        "**الميزات:**\n"
        "- البحث عن معلومات العناصر والمركبات الكيميائية.\n"
        "- معلومات حول المفاهيم الكيميائية الهامة.\n"
        "- اختبارات تفاعلية (عشوائية، حسب الفصل/الدرس، مراجعة الأخطاء، محددة بوقت).\n"
        "- تقارير أداء بعد كل اختبار.\n"
        "- معلومات حول الجدول الدوري، الحسابات الكيميائية، والروابط الكيميائية.\n"
        "- (للمسؤول) إدارة قاعدة بيانات الأسئلة.\n\n"
        "نتمنى لك كل التوفيق في دراستك! 👍"
    )
    keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        try:
            update.callback_query.edit_message_text(about_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except BadRequest as e:
             if "Message is not modified" not in str(e):
                 logger.error(f"Error editing about message: {e}")
    elif update.message:
        update.message.reply_text(about_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

# --- معالجات أزرار القوائم الرئيسية ---
def main_menu_button_handler(update: Update, context: CallbackContext) -> None:
    """معالجة الضغط على أزرار القائمة الرئيسية وقوائم فرعية أخرى."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = update.effective_user.id
    logger.info(f"Button pressed: {data} by user {user_id}")

    # إيقاف أي محادثة نشطة عند العودة للقائمة الرئيسية أو قوائم أخرى
    if data in ['main_menu', 'menu_info', 'menu_quiz', 'menu_admin', 'menu_reports'] and 'conversation_state' in context.user_data:
        logger.info(f"Ending conversation for user {user_id} due to menu navigation.")
        # إزالة مؤقت الاختبار إذا كان موجوداً
        remove_quiz_timer(context)
        del context.user_data['conversation_state']
        # يمكنك إضافة رسالة للمستخدم هنا إذا أردت

    if data == 'main_menu':
        show_main_menu(update, context, message_text="القائمة الرئيسية 👇")
    elif data == 'menu_info':
        show_info_menu(update, context)
    elif data == 'menu_quiz':
        show_quiz_menu(update, context)
    elif data == 'menu_about':
        about_command(update, context)
    elif data == 'menu_admin':
        show_admin_menu(update, context)
    elif data == 'menu_reports':
        show_user_reports(update, context)
    # --- معالجات أزرار قائمة الإدارة ---
    elif data == 'admin_add':
        if not is_admin(user_id):
            query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
            return ConversationHandler.END
        return add_question_start(update, context)
    elif data == 'admin_list':
        list_questions(update, context)
    elif data == 'admin_delete_prompt':
        if not is_admin(user_id):
            query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
            return ConversationHandler.END
        return delete_question_prompt(update, context)
    elif data == 'admin_show_prompt':
        if not is_admin(user_id):
            query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
            return ConversationHandler.END
        return show_question_prompt(update, context)
    # --- معالجات أزرار قائمة الاختبارات (الجديدة) ---
    elif data == 'quiz_random_prompt':
        return prompt_quiz_duration(update, context, 'random')
    elif data == 'quiz_by_chapter_prompt':
        return show_chapter_selection(update, context, for_quiz=True)
    elif data == 'quiz_by_lesson_prompt':
        return show_chapter_for_lesson_selection(update, context)
    elif data == 'quiz_review_prompt':
        return prompt_quiz_duration(update, context, 'review')
    # --- معالجات أزرار الاختبار ---
    elif data.startswith('quiz_answer_'):
        handle_quiz_answer(update, context)
    elif data == 'quiz_next':
        show_next_question(update, context)
    elif data == 'quiz_end':
        end_quiz(update, context)
    elif data.startswith('quiz_duration_'):
        handle_quiz_duration_selection(update, context)
    elif data.startswith('select_chapter_quiz_'):
        handle_chapter_selection_for_quiz(update, context)
    elif data.startswith('select_lesson_quiz_'):
        handle_lesson_selection_for_quiz(update, context)
    elif data.startswith('view_report_'):
        show_detailed_report(update, context)

# --- إدارة الأسئلة: إضافة سؤال جديد (نفس الكود السابق) ---
# ... (الكود الخاص بإضافة سؤال يبقى كما هو) ...

def add_question_start(update: Update, context: CallbackContext) -> int:
    """بدء محادثة إضافة سؤال جديد."""
    user_id = update.effective_user.id
    logger.info(f"Admin {user_id}: Starting add question conversation")
    
    if not is_admin(user_id):
        update.callback_query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
        return ConversationHandler.END
    
    context.user_data['conversation_state'] = 'add_question'
    context.user_data['new_question'] = {}
    
    update.callback_query.edit_message_text(
        "لنبدأ بإضافة سؤال جديد. الرجاء إرسال نص السؤال:"
    )
    return ADD_QUESTION_TEXT

def add_question_text(update: Update, context: CallbackContext) -> int:
    """استلام نص السؤال."""
    user_id = update.effective_user.id
    question_text = update.message.text.strip()
    logger.info(f"Admin {user_id}: Received question text: {question_text[:50]}...")
    
    if len(question_text) < 3:
        update.message.reply_text("نص السؤال قصير جداً. الرجاء إرسال نص أطول:")
        return ADD_QUESTION_TEXT
    
    context.user_data['new_question']['text'] = question_text
    
    update.message.reply_text(
        "تم استلام نص السؤال. الآن، الرجاء إرسال الخيارات (2-6 خيارات)، كل خيار في سطر منفصل.\n\n"
        "مثال:\n"
        "الخيار الأول\n"
        "الخيار الثاني\n"
        "الخيار الثالث\n"
        "الخيار الرابع"
    )
    return ADD_OPTIONS

def add_question_options(update: Update, context: CallbackContext) -> int:
    """استلام خيارات السؤال."""
    user_id = update.effective_user.id
    options_text = update.message.text.strip()
    logger.info(f"Admin {user_id}: Received options text")
    
    options = [line.strip() for line in options_text.split('\n') if line.strip()]
    
    if not (2 <= len(options) <= 6):
        update.message.reply_text(
            "يجب توفير ما بين 2 و 6 خيارات. الرجاء إرسال الخيارات مرة أخرى، كل خيار في سطر منفصل:"
        )
        return ADD_OPTIONS
    
    context.user_data['new_question']['options'] = options
    
    keyboard = []
    for i, option in enumerate(options):
        display_text = f"{i+1}. {option[:30]}" + ("..." if len(option) > 30 else "")
        keyboard.append([InlineKeyboardButton(display_text, callback_data=f'correct_{i}')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(
        "تم استلام الخيارات. الآن، اختر الإجابة الصحيحة من الخيارات أدناه:",
        reply_markup=reply_markup
    )
    return ADD_CORRECT_ANSWER

def add_question_correct_answer(update: Update, context: CallbackContext) -> int:
    """استلام الإجابة الصحيحة."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    
    correct_index = int(query.data.split('_')[1])
    logger.info(f"Admin {user_id}: Selected correct answer index: {correct_index}")
    
    context.user_data['new_question']['correct_answer'] = correct_index
    
    query.edit_message_text(
        "تم تحديد الإجابة الصحيحة. الآن، الرجاء إرسال شرح للإجابة (اختياري، يمكنك إرسال '-' للتخطي):"
    )
    return ADD_EXPLANATION

def add_question_explanation(update: Update, context: CallbackContext) -> int:
    """استلام شرح الإجابة."""
    user_id = update.effective_user.id
    explanation = update.message.text.strip()
    logger.info(f"Admin {user_id}: Received explanation")
    
    if explanation == '-':
        explanation = None
    
    context.user_data['new_question']['explanation'] = explanation
    
    update.message.reply_text(
        "تم استلام الشرح. الآن، الرجاء إرسال اسم الفصل (اختياري، يمكنك إرسال '-' للتخطي):"
    )
    return ADD_CHAPTER

def add_question_chapter(update: Update, context: CallbackContext) -> int:
    """استلام اسم الفصل."""
    user_id = update.effective_user.id
    chapter = update.message.text.strip()
    logger.info(f"Admin {user_id}: Received chapter: {chapter}")
    
    if chapter == '-':
        chapter = None
    
    context.user_data['new_question']['chapter'] = chapter
    
    update.message.reply_text(
        "تم استلام اسم الفصل. الآن، الرجاء إرسال اسم الدرس (اختياري، يمكنك إرسال '-' للتخطي):"
    )
    return ADD_LESSON

def add_question_lesson(update: Update, context: CallbackContext) -> int:
    """استلام اسم الدرس."""
    user_id = update.effective_user.id
    lesson = update.message.text.strip()
    logger.info(f"Admin {user_id}: Received lesson: {lesson}")
    
    if lesson == '-':
        lesson = None
    
    context.user_data['new_question']['lesson'] = lesson
    
    keyboard = [
        [InlineKeyboardButton("نعم، أريد إضافة صورة للسؤال", callback_data='add_image_yes')],
        [InlineKeyboardButton("لا، أكمل بدون صورة للسؤال", callback_data='add_image_no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("هل تريد إضافة صورة للسؤال؟", reply_markup=reply_markup)
    return ADD_QUESTION_IMAGE_PROMPT

def add_question_image_prompt(update: Update, context: CallbackContext) -> int:
    """معالجة الرد على طلب إضافة صورة للسؤال."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    
    if query.data == 'add_image_yes':
        logger.info(f"Admin {user_id}: Chose to add question image")
        query.edit_message_text("حسناً، الرجاء إرسال صورة السؤال الآن.")
        return WAITING_QUESTION_IMAGE
    else:
        logger.info(f"Admin {user_id}: Chose not to add question image")
        context.user_data['new_question']['question_image_id'] = None
        # الانتقال لسؤال إضافة صور الخيارات
        keyboard = [
            [InlineKeyboardButton("نعم، أريد إضافة صور للخيارات", callback_data='add_opt_images_yes')],
            [InlineKeyboardButton("لا، أكمل بدون صور للخيارات", callback_data='add_opt_images_no')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text("هل تريد إضافة صور للخيارات؟", reply_markup=reply_markup)
        return ADD_OPTION_IMAGES_PROMPT

def add_question_image(update: Update, context: CallbackContext) -> int:
    """استلام صورة السؤال."""
    user_id = update.effective_user.id
    if not update.message.photo:
        update.message.reply_text("الرجاء إرسال صورة.")
        return WAITING_QUESTION_IMAGE
        
    # الحصول على file_id لأكبر حجم للصورة
    photo_file_id = update.message.photo[-1].file_id
    logger.info(f"Admin {user_id}: Received question image with file_id: {photo_file_id}")
    context.user_data['new_question']['question_image_id'] = photo_file_id
    
    # الانتقال لسؤال إضافة صور الخيارات
    keyboard = [
        [InlineKeyboardButton("نعم، أريد إضافة صور للخيارات", callback_data='add_opt_images_yes')],
        [InlineKeyboardButton("لا، أكمل بدون صور للخيارات", callback_data='add_opt_images_no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("تم استلام صورة السؤال. هل تريد إضافة صور للخيارات؟", reply_markup=reply_markup)
    return ADD_OPTION_IMAGES_PROMPT

def add_option_images_prompt(update: Update, context: CallbackContext) -> int:
    """معالجة الرد على طلب إضافة صور للخيارات."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    
    if query.data == 'add_opt_images_yes':
        logger.info(f"Admin {user_id}: Chose to add option images")
        context.user_data['new_question']['option_image_ids'] = [None] * len(context.user_data['new_question']['options'])
        context.user_data['current_option_image_index'] = 0
        option_index = context.user_data['current_option_image_index']
        option_text = context.user_data['new_question']['options'][option_index]
        query.edit_message_text(f"حسناً، الرجاء إرسال صورة الخيار {option_index + 1}: '{option_text[:50]}...' (أو أرسل '-' للتخطي)")
        return WAITING_OPTION_IMAGE
    else:
        logger.info(f"Admin {user_id}: Chose not to add option images")
        context.user_data['new_question']['option_image_ids'] = None
        # حفظ السؤال النهائي
        return save_new_question(update, context)

def add_option_image(update: Update, context: CallbackContext) -> int:
    """استلام صورة الخيار أو التخطي."""
    user_id = update.effective_user.id
    option_index = context.user_data['current_option_image_index']
    num_options = len(context.user_data['new_question']['options'])
    photo_file_id = None

    if update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
        logger.info(f"Admin {user_id}: Received image for option {option_index + 1}")
        context.user_data['new_question']['option_image_ids'][option_index] = photo_file_id
    elif update.message.text and update.message.text.strip() == '-':
        logger.info(f"Admin {user_id}: Skipped image for option {option_index + 1}")
        context.user_data['new_question']['option_image_ids'][option_index] = None
    else:
        update.message.reply_text("الرجاء إرسال صورة أو '-' للتخطي.")
        return WAITING_OPTION_IMAGE

    # الانتقال للخيار التالي أو الحفظ
    context.user_data['current_option_image_index'] += 1
    next_option_index = context.user_data['current_option_image_index']

    if next_option_index < num_options:
        option_text = context.user_data['new_question']['options'][next_option_index]
        update.message.reply_text(f"تم استلام صورة الخيار {option_index + 1}. الآن، أرسل صورة الخيار {next_option_index + 1}: '{option_text[:50]}...' (أو أرسل '-' للتخطي)")
        return WAITING_OPTION_IMAGE
    else:
        logger.info(f"Admin {user_id}: Finished collecting option images")
        return save_new_question(update, context)

def save_new_question(update: Update, context: CallbackContext) -> int:
    """حفظ السؤال الجديد في قاعدة البيانات وإنهاء المحادثة."""
    user_id = update.effective_user.id
    new_q = context.user_data['new_question']
    logger.info(f"Admin {user_id}: Saving new question: {new_q.get('text', '')[:50]}...")

    success = QUIZ_DB.add_question(
        question_text=new_q.get('text'),
        options=new_q.get('options'),
        correct_answer_index=new_q.get('correct_answer'),
        explanation=new_q.get('explanation'),
        chapter=new_q.get('chapter'),
        lesson=new_q.get('lesson'),
        question_image_id=new_q.get('question_image_id'),
        option_image_ids=new_q.get('option_image_ids')
    )

    message_target = update.effective_message
    if update.callback_query:
        # If the last interaction was a button press (e.g., skipping images)
        message_target = update.callback_query.message

    if success:
        message_target.reply_text("✅ تم حفظ السؤال بنجاح!")
    else:
        message_target.reply_text("❌ حدث خطأ أثناء حفظ السؤال. يرجى المحاولة مرة أخرى أو مراجعة السجلات.")

    # تنظيف بيانات المستخدم وإنهاء المحادثة
    del context.user_data['new_question']
    if 'current_option_image_index' in context.user_data:
        del context.user_data['current_option_image_index']
    if 'conversation_state' in context.user_data:
        del context.user_data['conversation_state']
        
    # العودة لقائمة الإدارة
    # We need to send a new message for the admin menu as we might be replying to a message
    keyboard = [
        [InlineKeyboardButton("➕ إضافة سؤال جديد", callback_data='admin_add')],
        [InlineKeyboardButton("📋 عرض قائمة الأسئلة", callback_data='admin_list')],
        [InlineKeyboardButton("🗑️ حذف سؤال", callback_data='admin_delete_prompt')],
        [InlineKeyboardButton("ℹ️ عرض سؤال معين", callback_data='admin_show_prompt')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_target.reply_text("⚙️ اختر عملية إدارة الأسئلة:", reply_markup=reply_markup)

    return ConversationHandler.END

def cancel_add_question(update: Update, context: CallbackContext) -> int:
    """إلغاء عملية إضافة السؤال."""
    user_id = update.effective_user.id
    logger.info(f"Admin {user_id}: Canceled add question conversation")
    update.message.reply_text("تم إلغاء عملية إضافة السؤال.")
    
    # تنظيف بيانات المستخدم
    if 'new_question' in context.user_data:
        del context.user_data['new_question']
    if 'current_option_image_index' in context.user_data:
        del context.user_data['current_option_image_index']
    if 'conversation_state' in context.user_data:
        del context.user_data['conversation_state']
        
    # العودة للقائمة الرئيسية
    show_main_menu(update, context)
    return ConversationHandler.END

# --- إدارة الأسئلة: عرض القائمة والحذف والعرض ---
def list_questions(update: Update, context: CallbackContext) -> None:
    """عرض قائمة بجميع الأسئلة مع معرفاتها."""
    user_id = update.effective_user.id
    logger.info(f"Admin {user_id}: Listing questions")
    if not is_admin(user_id):
        update.callback_query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
        return

    questions = QUIZ_DB.get_all_questions()
    if not questions:
        update.callback_query.edit_message_text("لا توجد أسئلة في قاعدة البيانات حالياً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data='menu_admin')]]))
        return

    message_text = "📋 **قائمة الأسئلة:**\n\n"
    for q in questions:
        q_text = q.get('question', 'N/A')
        q_id = q.get('id', 'N/A')
        # إضافة رموز للصور
        img_indicator = "" 
        if q.get('question_image_id'):
            img_indicator += "🖼️" # صورة للسؤال
        if q.get('option_image_ids') and any(q.get('option_image_ids')):
             img_indicator += "🎨" # صور للخيارات
             
        message_text += f"`{q_id}`: {q_text[:50]}{'...' if len(q_text)>50 else ''} {img_indicator}\n"

    # تقسيم الرسالة إذا كانت طويلة جداً
    max_length = 4096
    if len(message_text) > max_length:
        message_text = message_text[:max_length - 20] + "\n... (القائمة طويلة جداً)"

    keyboard = [[InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data='menu_admin')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.callback_query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

def delete_question_prompt(update: Update, context: CallbackContext) -> int:
    """طلب معرف السؤال المراد حذفه."""
    user_id = update.effective_user.id
    logger.info(f"Admin {user_id}: Prompting for question ID to delete")
    if not is_admin(user_id):
        update.callback_query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
        return ConversationHandler.END
        
    context.user_data['conversation_state'] = 'delete_question'
    update.callback_query.edit_message_text("🗑️ الرجاء إرسال `ID` السؤال الذي تريد حذفه (أو أرسل /cancel للإلغاء):")
    return DELETE_CONFIRM

def delete_question_confirm(update: Update, context: CallbackContext) -> int:
    """تأكيد وحذف السؤال."""
    user_id = update.effective_user.id
    try:
        question_id_to_delete = int(update.message.text.strip())
        logger.info(f"Admin {user_id}: Attempting to delete question ID: {question_id_to_delete}")
    except ValueError:
        update.message.reply_text("معرف السؤال غير صالح. الرجاء إرسال رقم صحيح.")
        return DELETE_CONFIRM

    question = QUIZ_DB.get_question_by_id(question_id_to_delete)
    if not question:
        update.message.reply_text(f"لم يتم العثور على سؤال بالمعرف `{question_id_to_delete}`.")
        # البقاء في نفس الحالة لطلب معرف آخر
        return DELETE_CONFIRM

    success = QUIZ_DB.delete_question(question_id_to_delete)
    if success:
        update.message.reply_text(f"✅ تم حذف السؤال بالمعرف `{question_id_to_delete}` بنجاح.")
    else:
        update.message.reply_text("❌ حدث خطأ أثناء حذف السؤال.")

    # تنظيف وإنهاء المحادثة
    if 'conversation_state' in context.user_data:
        del context.user_data['conversation_state']
        
    # العودة لقائمة الإدارة
    keyboard = [
        [InlineKeyboardButton("➕ إضافة سؤال جديد", callback_data='admin_add')],
        [InlineKeyboardButton("📋 عرض قائمة الأسئلة", callback_data='admin_list')],
        [InlineKeyboardButton("🗑️ حذف سؤال آخر", callback_data='admin_delete_prompt')],
        [InlineKeyboardButton("ℹ️ عرض سؤال معين", callback_data='admin_show_prompt')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("⚙️ اختر عملية إدارة الأسئلة:", reply_markup=reply_markup)
    return ConversationHandler.END

def show_question_prompt(update: Update, context: CallbackContext) -> int:
    """طلب معرف السؤال المراد عرضه."""
    user_id = update.effective_user.id
    logger.info(f"Admin {user_id}: Prompting for question ID to show")
    if not is_admin(user_id):
        update.callback_query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
        return ConversationHandler.END
        
    context.user_data['conversation_state'] = 'show_question'
    update.callback_query.edit_message_text("ℹ️ الرجاء إرسال `ID` السؤال الذي تريد عرضه (أو أرسل /cancel للإلغاء):")
    return SHOW_ID

def show_question_details(update: Update, context: CallbackContext) -> int:
    """عرض تفاصيل سؤال معين."""
    user_id = update.effective_user.id
    try:
        question_id_to_show = int(update.message.text.strip())
        logger.info(f"Admin {user_id}: Attempting to show question ID: {question_id_to_show}")
    except ValueError:
        update.message.reply_text("معرف السؤال غير صالح. الرجاء إرسال رقم صحيح.")
        return SHOW_ID

    question = QUIZ_DB.get_question_by_id(question_id_to_show)
    if not question:
        update.message.reply_text(f"لم يتم العثور على سؤال بالمعرف `{question_id_to_show}`.")
        return SHOW_ID

    q_text = question.get('question', 'N/A')
    options = question.get('options', [])
    correct_index = question.get('correct_answer', -1)
    explanation = question.get('explanation', 'لا يوجد')
    chapter = question.get('chapter', 'غير محدد')
    lesson = question.get('lesson', 'غير محدد')
    q_image_id = question.get('question_image_id')
    opt_image_ids = question.get('option_image_ids') or []

    message_text = f"**تفاصيل السؤال (ID: {question_id_to_show})**\n\n"
    message_text += f"**النص:** {q_text}\n"
    if q_image_id:
        message_text += f"**صورة السؤال:** (موجودة)\n"
        
    message_text += "\n**الخيارات:**\n"
    for i, option in enumerate(options):
        correct_marker = "✅" if i == correct_index else ""
        opt_img_marker = "🎨" if i < len(opt_image_ids) and opt_image_ids[i] else ""
        message_text += f"{i+1}. {option} {correct_marker} {opt_img_marker}\n"
        
    message_text += f"\n**الشرح:** {explanation}\n"
    message_text += f"**الفصل:** {chapter}\n"
    message_text += f"**الدرس:** {lesson}\n"

    # إرسال الصور إذا كانت موجودة
    media_group = []
    if q_image_id:
        media_group.append(InputMediaPhoto(media=q_image_id, caption=f"صورة السؤال (ID: {question_id_to_show})"))
        
    for i, opt_img_id in enumerate(opt_image_ids):
        if opt_img_id:
             media_group.append(InputMediaPhoto(media=opt_img_id, caption=f"صورة الخيار {i+1}"))
             
    if media_group:
        try:
            update.message.reply_media_group(media=media_group)
        except Exception as e:
            logger.error(f"Failed to send media group for question {question_id_to_show}: {e}")
            update.message.reply_text("(حدث خطأ أثناء إرسال الصور)")

    # إرسال النص
    update.message.reply_text(message_text, parse_mode=ParseMode.MARKDOWN)

    # تنظيف وإنهاء المحادثة
    if 'conversation_state' in context.user_data:
        del context.user_data['conversation_state']
        
    # العودة لقائمة الإدارة
    keyboard = [
        [InlineKeyboardButton("➕ إضافة سؤال جديد", callback_data='admin_add')],
        [InlineKeyboardButton("📋 عرض قائمة الأسئلة", callback_data='admin_list')],
        [InlineKeyboardButton("🗑️ حذف سؤال", callback_data='admin_delete_prompt')],
        [InlineKeyboardButton("ℹ️ عرض سؤال آخر", callback_data='admin_show_prompt')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("⚙️ اختر عملية إدارة الأسئلة:", reply_markup=reply_markup)
    return ConversationHandler.END

def cancel_admin_action(update: Update, context: CallbackContext) -> int:
    """إلغاء عملية الحذف أو العرض."""
    user_id = update.effective_user.id
    action = context.user_data.get('conversation_state', 'العملية')
    logger.info(f"Admin {user_id}: Canceled {action}")
    update.message.reply_text(f"تم إلغاء {action}.")
    
    if 'conversation_state' in context.user_data:
        del context.user_data['conversation_state']
        
    # العودة لقائمة الإدارة
    keyboard = [
        [InlineKeyboardButton("➕ إضافة سؤال جديد", callback_data='admin_add')],
        [InlineKeyboardButton("📋 عرض قائمة الأسئلة", callback_data='admin_list')],
        [InlineKeyboardButton("🗑️ حذف سؤال", callback_data='admin_delete_prompt')],
        [InlineKeyboardButton("ℹ️ عرض سؤال معين", callback_data='admin_show_prompt')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("⚙️ اختر عملية إدارة الأسئلة:", reply_markup=reply_markup)
    return ConversationHandler.END

# --- المعلومات الكيميائية (نفس الكود السابق) ---
# ... (الكود الخاص بالمعلومات الكيميائية يبقى كما هو) ...
def info_elements_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    message_text = "🧪 **العناصر الكيميائية:**\n\n"
    for symbol, name in ELEMENTS.items():
        message_text += f"- `{symbol}`: {name}\n"
    message_text += "\nأرسل رمز العنصر للحصول على معلومات عنه (مثال: `H`)."
    keyboard = [[InlineKeyboardButton("🔙 العودة لقائمة المعلومات", callback_data='menu_info')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

def info_compounds_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    message_text = "🔬 **المركبات الكيميائية:**\n\n"
    for formula, name in COMPOUNDS.items():
        message_text += f"- `{formula}`: {name}\n"
    message_text += "\nأرسل صيغة المركب للحصول على معلومات عنه (مثال: `H2O`)."
    keyboard = [[InlineKeyboardButton("🔙 العودة لقائمة المعلومات", callback_data='menu_info')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

def info_concepts_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    message_text = "📘 **المفاهيم الكيميائية:**\n\n"
    for i, concept in enumerate(CONCEPTS.keys()):
        message_text += f"- {concept}\n"
    message_text += "\nأرسل اسم المفهوم للحصول على شرح له."
    keyboard = [[InlineKeyboardButton("🔙 العودة لقائمة المعلومات", callback_data='menu_info')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

def info_periodic_table_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    message_text = f"📊 **الجدول الدوري:**\n\n{PERIODIC_TABLE_INFO}"
    keyboard = [[InlineKeyboardButton("🔙 العودة لقائمة المعلومات", callback_data='menu_info')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

def info_calculations_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    message_text = f"🔢 **الحسابات الكيميائية:**\n\n{CHEMICAL_CALCULATIONS_INFO}"
    keyboard = [[InlineKeyboardButton("🔙 العودة لقائمة المعلومات", callback_data='menu_info')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

def info_bonds_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    message_text = f"🔗 **الروابط الكيميائية:**\n\n{CHEMICAL_BONDS_INFO}"
    keyboard = [[InlineKeyboardButton("🔙 العودة لقائمة المعلومات", callback_data='menu_info')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

def handle_info_query(update: Update, context: CallbackContext) -> None:
    """معالجة استعلامات المعلومات المرسلة كنص."""
    query_text = update.message.text.strip()
    logger.info(f"Received info query: {query_text}")
    response = "لم أجد معلومات تطابق استعلامك. حاول البحث عن:\n- رمز عنصر (مثل H)\n- صيغة مركب (مثل H2O)\n- اسم مفهوم كيميائي"

    # البحث في العناصر
    if query_text.upper() in ELEMENTS:
        response = f"**{ELEMENTS[query_text.upper()]} ({query_text.upper()})**\n\n[معلومات إضافية عن العنصر سيتم إضافتها لاحقاً]"
    # البحث في المركبات
    elif query_text.upper() in COMPOUNDS:
        response = f"**{COMPOUNDS[query_text.upper()]} ({query_text.upper()})**\n\n[معلومات إضافية عن المركب سيتم إضافتها لاحقاً]"
    # البحث في المفاهيم
    elif query_text in CONCEPTS:
        response = f"**{query_text}**\n\n{CONCEPTS[query_text]}"
        
    # معالجة المعادلات الكيميائية
    if any(c.isdigit() or c in '+->' for c in query_text):
        formatted_equation = format_chemical_equation(query_text)
        if formatted_equation != query_text: # إذا تم التنسيق بنجاح
             response = f"المعادلة المنسقة:\n`{formatted_equation}`"

    # إضافة زر العودة للقائمة الرئيسية
    keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(response, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

# --- الاختبارات المحسنة ---

def prompt_quiz_duration(update: Update, context: CallbackContext, quiz_type: str) -> int:
    """يسأل المستخدم عن مدة الاختبار."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id}: Prompting for duration for quiz type: {quiz_type}")

    context.user_data['quiz_settings'] = {'type': quiz_type}

    # تحديد مدة الاختبار
    keyboard = [
        [InlineKeyboardButton("5 دقائق", callback_data='quiz_duration_5'),
         InlineKeyboardButton("10 دقائق", callback_data='quiz_duration_10')],
        [InlineKeyboardButton("15 دقيقة", callback_data='quiz_duration_15'),
         InlineKeyboardButton("بدون وقت", callback_data='quiz_duration_0')] # 0 يعني بدون وقت
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    quiz_type_text = {
        'random': 'الاختبار العشوائي',
        'review': 'مراجعة الأخطاء',
        'chapter': 'الاختبار حسب الفصل',
        'lesson': 'الاختبار حسب الدرس'
    }.get(quiz_type, 'الاختبار')
    
    # إذا كان الاختبار حسب الفصل أو الدرس، نحتاج لتخزين الفصل/الدرس أولاً
    if quiz_type == 'chapter':
        context.user_data['quiz_settings']['chapter'] = context.user_data.get('selected_chapter')
    elif quiz_type == 'lesson':
        context.user_data['quiz_settings']['chapter'] = context.user_data.get('selected_chapter')
        context.user_data['quiz_settings']['lesson'] = context.user_data.get('selected_lesson')
        
    query.edit_message_text(f"اختر مدة {quiz_type_text}:", reply_markup=reply_markup)
    return SELECT_QUIZ_DURATION

def handle_quiz_duration_selection(update: Update, context: CallbackContext) -> None:
    """معالجة اختيار مدة الاختبار وبدء الاختبار المناسب."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    duration_minutes = int(query.data.split('_')[-1])
    logger.info(f"User {user_id}: Selected duration: {duration_minutes} minutes")

    context.user_data['quiz_settings']['duration'] = duration_minutes
    quiz_type = context.user_data['quiz_settings']['type']

    # بدء الاختبار المناسب
    if quiz_type == 'random':
        start_quiz_flow(update, context, quiz_type='random', duration_minutes=duration_minutes)
    elif quiz_type == 'review':
        start_quiz_flow(update, context, quiz_type='review', duration_minutes=duration_minutes)
    elif quiz_type == 'chapter':
        chapter = context.user_data['quiz_settings'].get('chapter')
        start_quiz_flow(update, context, quiz_type='chapter', chapter=chapter, duration_minutes=duration_minutes)
    elif quiz_type == 'lesson':
        chapter = context.user_data['quiz_settings'].get('chapter')
        lesson = context.user_data['quiz_settings'].get('lesson')
        start_quiz_flow(update, context, quiz_type='lesson', chapter=chapter, lesson=lesson, duration_minutes=duration_minutes)
    else:
        logger.error(f"Unknown quiz type in duration selection: {quiz_type}")
        query.edit_message_text("حدث خطأ غير متوقع.")

def start_quiz_flow(update: Update, context: CallbackContext, quiz_type: str, chapter: str = None, lesson: str = None, duration_minutes: int = DEFAULT_QUIZ_DURATION_MINUTES) -> None:
    """يبدأ تدفق الاختبار (عشوائي، فصل، درس، مراجعة)."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id}: Starting quiz flow - Type: {quiz_type}, Chapter: {chapter}, Lesson: {lesson}, Duration: {duration_minutes} min")

    questions = []
    if quiz_type == 'review':
        questions = QUIZ_DB.get_incorrect_questions(user_id, limit=DEFAULT_QUIZ_QUESTIONS)
        if not questions:
            update.callback_query.edit_message_text("🎉 لا توجد أسئلة أخطأت فيها لمراجعتها!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data='menu_quiz')]]))
            return
    elif quiz_type == 'chapter':
        if not chapter:
             logger.error("Chapter not provided for chapter quiz")
             update.callback_query.edit_message_text("لم يتم تحديد الفصل.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data='menu_quiz')]]))
             return
        questions = QUIZ_DB.get_questions_by_chapter(chapter)
    elif quiz_type == 'lesson':
        if not chapter or not lesson:
             logger.error("Chapter or lesson not provided for lesson quiz")
             update.callback_query.edit_message_text("لم يتم تحديد الفصل أو الدرس.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data='menu_quiz')]]))
             return
        questions = QUIZ_DB.get_questions_by_lesson(chapter, lesson)
    else: # random
        # جلب أسئلة عشوائية (يمكن تحسينها لجلب العدد المطلوب مباشرة)
        all_q_ids = [q['id'] for q in QUIZ_DB.get_all_questions()]
        if not all_q_ids:
             update.callback_query.edit_message_text("لا توجد أسئلة متاحة لبدء الاختبار.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data='menu_quiz')]]))
             return
        num_to_fetch = min(DEFAULT_QUIZ_QUESTIONS, len(all_q_ids))
        selected_ids = random.sample(all_q_ids, num_to_fetch)
        questions = [QUIZ_DB.get_question_by_id(qid) for qid in selected_ids if QUIZ_DB.get_question_by_id(qid)]

    if not questions:
        update.callback_query.edit_message_text("لم يتم العثور على أسئلة لهذا الاختبار.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data='menu_quiz')]]))
        return
        
    # تحديد عدد الأسئلة الفعلي
    num_questions = min(DEFAULT_QUIZ_QUESTIONS, len(questions))
    questions = random.sample(questions, num_questions) # أخذ عينة عشوائية بالعدد المطلوب

    # بدء الاختبار في قاعدة البيانات
    quiz_id = QUIZ_DB.start_quiz(user_id, quiz_type, chapter, lesson, total_questions=num_questions)
    if not quiz_id:
        logger.error(f"Failed to start quiz in database for user {user_id}")
        update.callback_query.edit_message_text("حدث خطأ أثناء بدء الاختبار. حاول مرة أخرى.")
        return

    context.user_data['quiz'] = {
        'id': quiz_id,
        'questions': questions,
        'current_question_index': 0,
        'correct_answers': 0,
        'start_time': time.time(),
        'duration_minutes': duration_minutes,
        'timer_job': None
    }
    context.user_data['conversation_state'] = 'in_quiz'

    # إعداد المؤقت إذا كانت المدة محددة
    if duration_minutes > 0:
        job = context.job_queue.run_once(end_quiz_timeout, duration_minutes * 60, context={'chat_id': update.effective_chat.id, 'user_id': user_id, 'quiz_id': quiz_id})
        context.user_data['quiz']['timer_job'] = job
        logger.info(f"Quiz timer set for {duration_minutes} minutes for quiz {quiz_id}")

    # عرض السؤال الأول
    show_next_question(update, context)

def show_next_question(update: Update, context: CallbackContext) -> None:
    """عرض السؤال التالي في الاختبار."""
    query = update.callback_query
    if query:
        query.answer()
        
    user_data = context.user_data
    if 'quiz' not in user_data or user_data.get('conversation_state') != 'in_quiz':
        logger.warning("show_next_question called outside of an active quiz.")
        # قد يكون الاختبار انتهى بسبب الوقت
        if query:
            try:
                query.edit_message_text("انتهى الاختبار أو تم إلغاؤه.")
            except BadRequest as e:
                 if "Message is not modified" not in str(e):
                     logger.error(f"Error editing message in show_next_question: {e}")
        return

    quiz_data = user_data['quiz']
    current_index = quiz_data['current_question_index']
    questions = quiz_data['questions']

    if current_index >= len(questions):
        # انتهى الاختبار
        end_quiz(update, context)
        return

    question = questions[current_index]
    q_text = question.get('question', 'N/A')
    options = question.get('options', [])
    q_image_id = question.get('question_image_id')
    opt_image_ids = question.get('option_image_ids') or [None] * len(options)

    # تنسيق نص السؤال مع المؤقت (إذا وجد)
    duration_minutes = quiz_data.get('duration_minutes', 0)
    time_elapsed = int(time.time() - quiz_data['start_time'])
    time_remaining_str = ""
    if duration_minutes > 0:
        time_remaining = max(0, (duration_minutes * 60) - time_elapsed)
        mins, secs = divmod(time_remaining, 60)
        time_remaining_str = f"⏳ الوقت المتبقي: {mins:02d}:{secs:02d}\n"
        
    question_header = f"**السؤال {current_index + 1} من {len(questions)}**\n{time_remaining_str}\n{q_text}"

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
        # نحتاج إلى كائن Update وهمي أو طريقة أخرى لاستدعاء end_quiz
        # الحل الأبسط هو إرسال رسالة مباشرة
        # end_quiz(None, context) # لا يمكن استدعاؤها بدون Update
        
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
                f"⏰ **انتهى الوقت!** ⏰\n\n"
                f"🏁 **نتائج الاختبار (ID: {quiz_id})** 🏁\n\n"
                f"عدد الأسئلة المجابة: {report.get('correct_answers', 0) + len([a for a in report.get('answers', []) if not a['is_correct']])} من {total_questions}\n"
                f"الإجابات الصحيحة: {correct_answers}\n"
                f"النسبة المئوية: {score_percentage}%\n"
                f"الوقت المستغرق: {time_taken_str}\n\n"
            )
        else:
            result_text = f"⏰ **انتهى الوقت!** ⏰\n\n🏁 **نتائج الاختبار** 🏁\n\nحدث خطأ أثناء جلب التقرير."
            result_text += f"\nالإجابات الصحيحة: {correct_answers} من {total_questions}"
            
        # تنظيف بيانات المستخدم
        if 'quiz' in user_data: del user_data['quiz']
        if 'quiz_settings' in user_data: del user_data['quiz_settings']
        if 'conversation_state' in user_data: del user_data['conversation_state']
        
        # إرسال رسالة النتائج
        keyboard = [
            [InlineKeyboardButton("📊 عرض التقرير المفصل", callback_data=f'view_report_{quiz_id}')],
            [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(chat_id=chat_id, text=result_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        logger.info(f"Quiz {quiz_id} already ended or user {user_id} not in quiz state.")

def remove_quiz_timer(context: CallbackContext):
    """إزالة مؤقت الاختبار إذا كان موجوداً."""
    if 'quiz' in context.user_data and context.user_data['quiz'].get('timer_job'):
        logger.info(f"Removing quiz timer for quiz {context.user_data['quiz'].get('id')}")
        context.user_data['quiz']['timer_job'].schedule_removal()
        context.user_data['quiz']['timer_job'] = None

# --- اختيار الفصل والدرس للاختبار ---
def show_chapter_selection(update: Update, context: CallbackContext, for_quiz: bool = False) -> int:
    """عرض قائمة الفصول للاختيار."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id}: Showing chapter selection (for_quiz={for_quiz})")

    chapters = QUIZ_DB.get_chapters()
    if not chapters:
        query.edit_message_text("لا توجد فصول متاحة حالياً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data='menu_quiz')]]))
        return ConversationHandler.END

    keyboard = []
    callback_prefix = 'select_chapter_quiz_' if for_quiz else 'select_chapter_lesson_'
    for chapter in chapters:
        keyboard.append([InlineKeyboardButton(chapter, callback_data=f'{callback_prefix}{chapter}')])
    keyboard.append([InlineKeyboardButton("🔙 إلغاء", callback_data='menu_quiz')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = "اختر الفصل:" if for_quiz else "اختر الفصل لعرض الدروس:"
    query.edit_message_text(message_text, reply_markup=reply_markup)
    
    context.user_data['conversation_state'] = 'selecting_chapter_for_quiz' if for_quiz else 'selecting_chapter_for_lesson'
    return SELECT_CHAPTER_FOR_QUIZ if for_quiz else SELECT_CHAPTER_FOR_LESSON

def handle_chapter_selection_for_quiz(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار الفصل لبدء اختبار حسب الفصل."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    selected_chapter = query.data.split('select_chapter_quiz_')[-1]
    logger.info(f"User {user_id}: Selected chapter '{selected_chapter}' for quiz")
    
    context.user_data['selected_chapter'] = selected_chapter
    # الانتقال لسؤال مدة الاختبار
    return prompt_quiz_duration(update, context, 'chapter')

def show_chapter_for_lesson_selection(update: Update, context: CallbackContext) -> int:
    """عرض قائمة الفصول لاختيار الدرس."""
    return show_chapter_selection(update, context, for_quiz=False)

def show_lesson_selection(update: Update, context: CallbackContext) -> int:
    """عرض قائمة الدروس لفصل معين."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    selected_chapter = query.data.split('select_chapter_lesson_')[-1]
    logger.info(f"User {user_id}: Selected chapter '{selected_chapter}' to view lessons")
    context.user_data['selected_chapter'] = selected_chapter

    lessons = QUIZ_DB.get_lessons(chapter=selected_chapter)
    if not lessons:
        query.edit_message_text(f"لا توجد دروس متاحة للفصل '{selected_chapter}'.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لاختيار الفصل", callback_data='quiz_by_lesson_prompt')]]))
        # العودة لحالة اختيار الفصل
        return SELECT_CHAPTER_FOR_LESSON 

    keyboard = []
    for lesson in lessons:
        keyboard.append([InlineKeyboardButton(lesson, callback_data=f'select_lesson_quiz_{lesson}')])
    keyboard.append([InlineKeyboardButton("🔙 العودة لاختيار الفصل", callback_data='quiz_by_lesson_prompt')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.edit_message_text(f"اختر الدرس من فصل '{selected_chapter}':", reply_markup=reply_markup)
    context.user_data['conversation_state'] = 'selecting_lesson_for_quiz'
    return SELECT_LESSON_FOR_QUIZ

def handle_lesson_selection_for_quiz(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار الدرس لبدء اختبار حسب الدرس."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    selected_lesson = query.data.split('select_lesson_quiz_')[-1]
    selected_chapter = context.user_data.get('selected_chapter')
    logger.info(f"User {user_id}: Selected lesson '{selected_lesson}' from chapter '{selected_chapter}' for quiz")
    
    if not selected_chapter:
        logger.error("Chapter not found in user_data during lesson selection.")
        query.edit_message_text("حدث خطأ، لم يتم العثور على الفصل المحدد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data='menu_quiz')]]))
        return ConversationHandler.END
        
    context.user_data['selected_lesson'] = selected_lesson
    # الانتقال لسؤال مدة الاختبار
    return prompt_quiz_duration(update, context, 'lesson')

def cancel_selection(update: Update, context: CallbackContext) -> int:
    """إلغاء عملية اختيار الفصل/الدرس."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id}: Canceled chapter/lesson selection")
    
    if 'conversation_state' in context.user_data:
        del context.user_data['conversation_state']
    if 'selected_chapter' in context.user_data:
        del context.user_data['selected_chapter']
    if 'selected_lesson' in context.user_data:
        del context.user_data['selected_lesson']
    if 'quiz_settings' in context.user_data:
        del context.user_data['quiz_settings']
        
    show_quiz_menu(update, context)
    return ConversationHandler.END

# --- تقارير الأداء ---
def show_user_reports(update: Update, context: CallbackContext) -> None:
    """عرض قائمة بأحدث تقارير اختبارات المستخدم."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id}: Requesting quiz reports")

    history = QUIZ_DB.get_user_quiz_history(user_id, limit=10)

    if not history:
        query.edit_message_text("لم تقم بإجراء أي اختبارات بعد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]]))
        return

    message_text = "📊 **أحدث تقارير الاختبارات:**\n\n"
    keyboard = []
    for quiz in history:
        quiz_id = quiz['quiz_id']
        start_time_str = quiz['start_time'].strftime('%Y-%m-%d %H:%M')
        score = quiz['score_percentage']
        quiz_type_ar = {
            'random': 'عشوائي',
            'chapter': f"فصل: {quiz.get('chapter', '')}",
            'lesson': f"درس: {quiz.get('lesson', '')}",
            'review': 'مراجعة'
        }.get(quiz['quiz_type'], quiz['quiz_type'])
        
        message_text += f"- {start_time_str}: {quiz_type_ar} - النتيجة: {score}%\n"
        keyboard.append([InlineKeyboardButton(f"{start_time_str} ({score}%) - عرض التفاصيل", callback_data=f'view_report_{quiz_id}')])

    keyboard.append([InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # تقسيم الرسالة إذا كانت طويلة
    max_length = 4096
    if len(message_text) > max_length:
        message_text = message_text[:max_length - 20] + "\n... (القائمة طويلة جداً)"
        
    query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

def show_detailed_report(update: Update, context: CallbackContext) -> None:
    """عرض التقرير المفصل لاختبار معين."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    quiz_id = int(query.data.split('_')[-1])
    logger.info(f"User {user_id}: Requesting detailed report for quiz {quiz_id}")

    report = QUIZ_DB.get_quiz_report(quiz_id)

    if not report or report.get('user_id') != user_id:
        query.edit_message_text("لم يتم العثور على التقرير أو لا تملك صلاحية الوصول إليه.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للتقارير", callback_data='menu_reports')]]))
        return

    total_questions = report.get('total_questions', 0)
    correct_answers = report.get('correct_answers', 0)
    score_percentage = report.get('score_percentage', 0)
    time_taken_seconds = report.get('time_taken', 0)
    mins, secs = divmod(time_taken_seconds, 60)
    time_taken_str = f"{mins} دقيقة و {secs} ثانية"
    start_time_str = report['start_time'].strftime('%Y-%m-%d %H:%M')
    quiz_type_ar = {
        'random': 'عشوائي',
        'chapter': f"فصل: {report.get('chapter', '')}",
        'lesson': f"درس: {report.get('lesson', '')}",
        'review': 'مراجعة'
    }.get(report['quiz_type'], report['quiz_type'])

    report_text = (
        f"📊 **التقرير المفصل للاختبار (ID: {quiz_id})** 📊\n\n"
        f"**الوقت:** {start_time_str}\n"
        f"**النوع:** {quiz_type_ar}\n"
        f"**النتيجة:** {correct_answers}/{total_questions} ({score_percentage}%)\n"
        f"**الوقت المستغرق:** {time_taken_str}\n\n"
        f"**تفاصيل الإجابات:**\n"
    )

    answers = report.get('answers', [])
    if not answers:
        report_text += "(لم يتم تسجيل إجابات لهذا الاختبار)"
    else:
        for i, answer in enumerate(answers):
            q_text = answer.get('question_text', 'N/A')
            options = answer.get('options', [])
            user_ans_idx = answer.get('user_answer_index', -1)
            correct_ans_idx = answer.get('correct_answer_index', -1)
            is_correct = answer.get('is_correct', False)
            
            user_ans_text = options[user_ans_idx] if 0 <= user_ans_idx < len(options) else "N/A"
            correct_ans_text = options[correct_ans_idx] if 0 <= correct_ans_idx < len(options) else "N/A"
            
            status_icon = "✅" if is_correct else "❌"
            
            report_text += f"\n**{i+1}. {q_text[:60]}{'...' if len(q_text)>60 else ''}**\n"
            report_text += f"   إجابتك: {user_ans_idx + 1}. {user_ans_text} {status_icon}\n"
            if not is_correct:
                report_text += f"   الصحيحة: {correct_ans_idx + 1}. {correct_ans_text}\n"

    # تقسيم الرسالة إذا كانت طويلة
    max_length = 4096
    message_parts = []
    while len(report_text) > max_length:
        split_pos = report_text.rfind('\n\n', 0, max_length) # البحث عن آخر فقرة
        if split_pos == -1:
            split_pos = max_length # قص في المنتصف إذا لم نجد فقرة
        message_parts.append(report_text[:split_pos])
        report_text = report_text[split_pos:]
    message_parts.append(report_text)

    # إرسال أجزاء الرسالة
    keyboard = [[InlineKeyboardButton("🔙 العودة للتقارير", callback_data='menu_reports')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    for i, part in enumerate(message_parts):
        if i == len(message_parts) - 1: # إضافة الأزرار للجزء الأخير فقط
            query.message.reply_text(part, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            query.message.reply_text(part, parse_mode=ParseMode.MARKDOWN)
            time.sleep(0.5) # تأخير بسيط بين الرسائل
            
    # حذف الرسالة الأصلية التي تحتوي على زر "عرض التفاصيل"
    try:
        query.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete original report button message: {e}")

# --- معالج الأخطاء ---
def error_handler(update: Update, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    
    # محاولة إعلام المستخدم بالخطأ
    if update and update.effective_message:
        try:
            update.effective_message.reply_text("حدث خطأ ما أثناء معالجة طلبك. يرجى المحاولة مرة أخرى لاحقاً.")
        except Exception as e:
            logger.error(f"Failed to send error message to user: {e}")
            
    # إذا كان الخطأ في محادثة، حاول إنهاء المحادثة بأمان
    if isinstance(context.error, (NetworkError, Unauthorized)):
        # تجاهل الأخطاء المتعلقة بالشبكة أو الصلاحيات التي قد تكون مؤقتة
        pass
    elif 'conversation_state' in context.user_data:
        state = context.user_data.get('conversation_state')
        logger.warning(f"Error occurred during conversation state: {state}. Attempting to end conversation.")
        # تنظيف بيانات المستخدم الخاصة بالمحادثة
        keys_to_delete = ['conversation_state', 'new_question', 'current_option_image_index', 'quiz', 'quiz_settings', 'selected_chapter', 'selected_lesson']
        for key in keys_to_delete:
            if key in context.user_data:
                del context.user_data[key]
        # إزالة المؤقت إذا كان موجوداً
        remove_quiz_timer(context)
        # لا يمكن إرجاع ConversationHandler.END هنا، لكننا قمنا بالتنظيف

# --- الدالة الرئيسية ---
def main() -> None:
    """Start the bot."""
    # التحقق من التوكن
    if TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("Bot token is not set! Please replace 'YOUR_BOT_TOKEN_HERE' with your actual bot token.")
        return
        
    # إنشاء Updater وتمرير التوكن
    updater = Updater(TOKEN, use_context=True)

    # الحصول على المرسل لتسجيل المعالجات
    dispatcher = updater.dispatcher

    # --- محادثة إضافة سؤال ---
    add_question_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_question_start, pattern='^admin_add$')],
        states={
            ADD_QUESTION_TEXT: [MessageHandler(Filters.text & ~Filters.command, add_question_text)],
            ADD_OPTIONS: [MessageHandler(Filters.text & ~Filters.command, add_question_options)],
            ADD_CORRECT_ANSWER: [CallbackQueryHandler(add_question_correct_answer, pattern='^correct_')],
            ADD_EXPLANATION: [MessageHandler(Filters.text & ~Filters.command, add_question_explanation)],
            ADD_CHAPTER: [MessageHandler(Filters.text & ~Filters.command, add_question_chapter)],
            ADD_LESSON: [MessageHandler(Filters.text & ~Filters.command, add_question_lesson)],
            ADD_QUESTION_IMAGE_PROMPT: [CallbackQueryHandler(add_question_image_prompt, pattern='^add_image_')],
            WAITING_QUESTION_IMAGE: [MessageHandler(Filters.photo | (Filters.text & Filters.regex('^-?$')), add_question_image)],
            ADD_OPTION_IMAGES_PROMPT: [CallbackQueryHandler(add_option_images_prompt, pattern='^add_opt_images_')],
            WAITING_OPTION_IMAGE: [MessageHandler(Filters.photo | (Filters.text & Filters.regex('^-?$')), add_option_image)],
        },
        fallbacks=[CommandHandler('cancel', cancel_add_question)],
        map_to_parent={
            # العودة إلى القائمة الرئيسية عند الانتهاء أو الإلغاء
            ConversationHandler.END: ConversationHandler.END
        }
    )

    # --- محادثة حذف سؤال ---
    delete_question_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(delete_question_prompt, pattern='^admin_delete_prompt$')],
        states={
            DELETE_CONFIRM: [MessageHandler(Filters.text & ~Filters.command, delete_question_confirm)]
        },
        fallbacks=[CommandHandler('cancel', cancel_admin_action)],
        map_to_parent={
            ConversationHandler.END: ConversationHandler.END
        }
    )

    # --- محادثة عرض سؤال ---
    show_question_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(show_question_prompt, pattern='^admin_show_prompt$')],
        states={
            SHOW_ID: [MessageHandler(Filters.text & ~Filters.command, show_question_details)]
        },
        fallbacks=[CommandHandler('cancel', cancel_admin_action)],
         map_to_parent={
            ConversationHandler.END: ConversationHandler.END
        }
    )
    
    # --- محادثة اختيار الفصل/الدرس للاختبار ---
    quiz_selection_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(show_chapter_selection, pattern='^quiz_by_chapter_prompt$', pass_args=True, pass_chat_data=True, pass_user_data=True),
            CallbackQueryHandler(show_chapter_for_lesson_selection, pattern='^quiz_by_lesson_prompt$')
        ],
        states={
            SELECT_CHAPTER_FOR_LESSON: [CallbackQueryHandler(show_lesson_selection, pattern='^select_chapter_lesson_')],
            SELECT_LESSON_FOR_QUIZ: [CallbackQueryHandler(handle_lesson_selection_for_quiz, pattern='^select_lesson_quiz_')],
            SELECT_CHAPTER_FOR_QUIZ: [CallbackQueryHandler(handle_chapter_selection_for_quiz, pattern='^select_chapter_quiz_')],
            SELECT_QUIZ_DURATION: [CallbackQueryHandler(handle_quiz_duration_selection, pattern='^quiz_duration_')]
        },
        fallbacks=[CallbackQueryHandler(cancel_selection, pattern='^menu_quiz$')], # الإلغاء يعود لقائمة الاختبارات
        map_to_parent={
            ConversationHandler.END: ConversationHandler.END,
            SELECT_QUIZ_DURATION: SELECT_QUIZ_DURATION # البقاء في حالة اختيار المدة
        }
    )
    
    # --- محادثة اختيار مدة الاختبار (للاختبار العشوائي والمراجعة) ---
    duration_selection_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(prompt_quiz_duration, pattern='^quiz_random_prompt$', pass_args=True, pass_chat_data=True, pass_user_data=True),
            CallbackQueryHandler(prompt_quiz_duration, pattern='^quiz_review_prompt$', pass_args=True, pass_chat_data=True, pass_user_data=True)
        ],
        states={
            SELECT_QUIZ_DURATION: [CallbackQueryHandler(handle_quiz_duration_selection, pattern='^quiz_duration_')]
        },
        fallbacks=[CallbackQueryHandler(cancel_selection, pattern='^menu_quiz$')],
        map_to_parent={
            ConversationHandler.END: ConversationHandler.END
        }
    )

    # --- المعالجات الرئيسية ---
    # استخدام محادثة وهمية لتضمين المحادثات الفرعية
    main_conversation = ConversationHandler(
         entry_points=[CommandHandler('start', start_command)],
         states={
             ConversationHandler.TIMEOUT: [MessageHandler(Filters.text, start_command)], # إعادة البدء عند انتهاء المهلة
             # تضمين المحادثات الفرعية هنا
             0: [add_question_handler],
             1: [delete_question_handler],
             2: [show_question_handler],
             3: [quiz_selection_handler],
             4: [duration_selection_handler],
         },
         fallbacks=[CommandHandler('start', start_command)], # السماح بإعادة البدء دائماً
         conversation_timeout=timedelta(hours=1) # مهلة للمحادثة الرئيسية
    )
    
    # dispatcher.add_handler(main_conversation) # إضافة المحادثة الرئيسية
    # ملاحظة: استخدام محادثة رئيسية بهذا الشكل قد يكون معقداً. سنضيف المعالجات بشكل منفصل.
    
    dispatcher.add_handler(CommandHandler('start', start_command))
    dispatcher.add_handler(CommandHandler('about', about_command))
    
    # إضافة معالجات المحادثات الفرعية مباشرة
    dispatcher.add_handler(add_question_handler)
    dispatcher.add_handler(delete_question_handler)
    dispatcher.add_handler(show_question_handler)
    dispatcher.add_handler(quiz_selection_handler)
    dispatcher.add_handler(duration_selection_handler)

    # معالج أزرار القوائم الرئيسية (يجب أن يكون له أولوية أقل من المحادثات)
    dispatcher.add_handler(CallbackQueryHandler(main_menu_button_handler), group=1)
    
    # معالج استعلامات المعلومات النصية (يجب أن يكون له أولوية أقل)
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_info_query), group=1)

    # معالج الأخطاء
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

