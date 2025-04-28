#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import random
import os
import time
import sys
import base64
import re # استيراد وحدة التعبيرات النمطية
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler, ConversationHandler
from telegram.error import NetworkError, TelegramError, Unauthorized

# استيراد البيانات الثابتة ووظائف المعادلات
from chemistry_data import ELEMENTS, COMPOUNDS, CONCEPTS, QUIZ_QUESTIONS, PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO
from chemical_equations import process_text_with_chemical_notation, format_chemical_equation

# استيراد الفئة الجديدة لقاعدة البيانات
from quiz_db import QuizDatabase

# --- إعدادات --- 
# ضع معرف المستخدم الرقمي الخاص بك هنا لتقييد الوصول إلى إدارة قاعدة البيانات
ADMIN_USER_ID = 6448526509 # !!! استبدل هذا بمعرف المستخدم الرقمي الخاص بك !!!
# توكن البوت
TOKEN = "YOUR_BOT_8167394360:AAG-b3v-VDmxLtWVQCuBkc694Mt3ZCs18IY" # !!! استبدل هذا بتوكن البوت الخاص بك بدقة تامة !!!

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

# تهيئة قاعدة بيانات الأسئلة (باستخدام PostgreSQL)
try:
    QUIZ_DB = QuizDatabase()
    logger.info("QuizDatabase initialized successfully.")
except ValueError as e:
    logger.error(f"Failed to initialize QuizDatabase: {e}")
    sys.exit(f"Error initializing database: {e}")
except Exception as e:
    logger.error(f"An unexpected error occurred during QuizDatabase initialization: {e}")
    sys.exit(f"Unexpected error initializing database: {e}")


# حالات المحادثة لإضافة سؤال وحذف/عرض سؤال واستيراد
(ADD_QUESTION_TEXT, ADD_OPTIONS, ADD_CORRECT_ANSWER, ADD_EXPLANATION, ADD_CHAPTER, ADD_LESSON, 
 ADD_QUESTION_IMAGE_PROMPT, WAITING_QUESTION_IMAGE, ADD_OPTION_IMAGES_PROMPT, WAITING_OPTION_IMAGE,
 DELETE_CONFIRM, SHOW_ID, IMPORT_CHANNEL_PROMPT, WAITING_FORWARDED_QUESTIONS) = range(14)

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
        except TelegramError as e:
            if "Message is not modified" not in str(e):
                logger.error(f"Error editing message: {e}")
                try:
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
        [InlineKeyboardButton("📥 استيراد أسئلة من قناة", callback_data='admin_import_channel')],
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
        [InlineKeyboardButton("🎯 اختبار عشوائي", callback_data='quiz_random')],
        [InlineKeyboardButton("📑 اختبار حسب الفصل", callback_data='quiz_by_chapter')],
        [InlineKeyboardButton("📝 اختبار حسب الدرس", callback_data='quiz_by_lesson')],
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
        "- اختبارات تفاعلية لتقييم معرفتك.\n"
        "- معلومات حول الجدول الدوري، الحسابات الكيميائية، والروابط الكيميائية.\n"
        "- (للمسؤول) إدارة قاعدة بيانات الأسئلة.\n\n"
        "نتمنى لك كل التوفيق في دراستك! 👍"
    )
    keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        update.callback_query.edit_message_text(about_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
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
    if data in ['main_menu', 'menu_info', 'menu_quiz', 'menu_admin'] and 'conversation_state' in context.user_data:
        logger.info(f"Ending conversation for user {user_id} due to menu navigation.")
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
    # --- معالجات أزرار قائمة الإدارة ---
    elif data == 'admin_add':
        # Check if user is admin before starting conversation
        if not is_admin(user_id):
            query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
            return ConversationHandler.END # End conversation if not admin
        return add_question_start(update, context) # Return the next state
    elif data == 'admin_list':
        list_questions(update, context)
    elif data == 'admin_delete_prompt':
        # Check if user is admin before starting conversation
        if not is_admin(user_id):
            query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
            return ConversationHandler.END
        return delete_question_prompt(update, context)
    elif data == 'admin_show_prompt':
         # Check if user is admin before starting conversation
        if not is_admin(user_id):
            query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
            return ConversationHandler.END
        return show_question_prompt(update, context)
    elif data == 'admin_import_channel':
        # Check if user is admin before starting conversation
        if not is_admin(user_id):
            query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
            return ConversationHandler.END
        return import_channel_start(update, context)
    # --- معالجات أزرار قائمة الاختبارات ---
    elif data == 'quiz_random':
        start_random_quiz(update, context)
    elif data == 'quiz_by_chapter':
        show_chapter_selection(update, context)
    elif data == 'quiz_by_lesson':
        show_chapter_for_lesson_selection(update, context)
    # --- معالجات أزرار الاختبار ---
    elif data.startswith('quiz_answer_'):
        handle_quiz_answer(update, context)
    elif data == 'quiz_next':
        show_next_question(update, context)
    elif data == 'quiz_end':
        end_quiz(update, context)

# --- إدارة الأسئلة: إضافة سؤال جديد ---
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
        "تم استلام نص السؤال. الآن، الرجاء إرسال الخيارات الأربعة، كل خيار في سطر منفصل.\n\n"
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
    
    # تقسيم النص إلى أسطر وإزالة الأسطر الفارغة
    options = [line.strip() for line in options_text.split('\n') if line.strip()]
    
    if len(options) < 2:
        update.message.reply_text(
            "يجب توفير خيارين على الأقل. الرجاء إرسال الخيارات مرة أخرى، كل خيار في سطر منفصل:"
        )
        return ADD_OPTIONS
    
    context.user_data['new_question']['options'] = options
    
    # إنشاء أزرار للخيارات
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
    
    # استخراج رقم الخيار الصحيح من callback_data
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
    
    # سؤال المستخدم عما إذا كان يريد إضافة صورة للسؤال
    keyboard = [
        [InlineKeyboardButton("نعم، أريد إضافة صورة", callback_data='add_image_yes')],
        [InlineKeyboardButton("لا، أكمل بدون صورة", callback_data='add_image_no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(
        "تم استلام اسم الدرس. هل تريد إضافة صورة للسؤال؟",
        reply_markup=reply_markup
    )
    return ADD_QUESTION_IMAGE_PROMPT

def add_question_image_prompt(update: Update, context: CallbackContext) -> int:
    """معالجة الرد على سؤال إضافة صورة."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    
    choice = query.data.split('_')[-1]
    logger.info(f"Admin {user_id}: Image choice: {choice}")
    
    if choice == 'yes':
        query.edit_message_text(
            "الرجاء إرسال الصورة التي تريد إضافتها للسؤال:"
        )
        return WAITING_QUESTION_IMAGE
    else:
        # المستخدم لا يريد إضافة صورة للسؤال، نسأل عن صور الخيارات
        return ask_about_option_images(update, context)

def add_question_image(update: Update, context: CallbackContext) -> int:
    """استلام صورة السؤال."""
    user_id = update.effective_user.id
    logger.info(f"Admin {user_id}: Received question image")
    
    # الحصول على معرف الصورة من تليجرام
    photo = update.message.photo[-1]  # أخذ أكبر نسخة من الصورة
    file_id = photo.file_id
    
    context.user_data['new_question']['question_image_id'] = file_id
    
    # إرسال رسالة تأكيد مع معاينة الصورة
    update.message.reply_photo(
        photo=file_id,
        caption="تم استلام صورة السؤال بنجاح."
    )
    
    # الانتقال إلى سؤال عن صور الخيارات
    return ask_about_option_images(update, context)

def ask_about_option_images(update: Update, context: CallbackContext) -> int:
    """سؤال المستخدم عما إذا كان يريد إضافة صور للخيارات."""
    keyboard = [
        [InlineKeyboardButton("نعم، أريد إضافة صور للخيارات", callback_data='add_option_images_yes')],
        [InlineKeyboardButton("لا، أكمل بدون صور للخيارات", callback_data='add_option_images_no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        update.message.reply_text(
            "هل تريد إضافة صور للخيارات؟",
            reply_markup=reply_markup
        )
    else:
        update.callback_query.edit_message_text(
            "هل تريد إضافة صور للخيارات؟",
            reply_markup=reply_markup
        )
    
    return ADD_OPTION_IMAGES_PROMPT

def add_option_images_prompt(update: Update, context: CallbackContext) -> int:
    """معالجة الرد على سؤال إضافة صور للخيارات."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    
    choice = query.data.split('_')[-1]
    logger.info(f"Admin {user_id}: Option images choice: {choice}")
    
    if choice == 'yes':
        # تهيئة قائمة لتخزين معرفات صور الخيارات
        context.user_data['new_question']['option_image_ids'] = [None] * len(context.user_data['new_question']['options'])
        context.user_data['current_option_index'] = 0
        
        # طلب صورة للخيار الأول
        option_text = context.user_data['new_question']['options'][0]
        query.edit_message_text(
            f"الرجاء إرسال صورة للخيار الأول: {option_text}\n\n"
            "(يمكنك إرسال أي رسالة نصية للتخطي)"
        )
        return WAITING_OPTION_IMAGE
    else:
        # المستخدم لا يريد إضافة صور للخيارات، نتابع لحفظ السؤال
        return save_question(update, context)

def add_option_image(update: Update, context: CallbackContext) -> int:
    """استلام صورة خيار أو تخطيها."""
    user_id = update.effective_user.id
    current_index = context.user_data['current_option_index']
    file_id = None
    
    if update.message.photo:
        # الحصول على معرف الصورة من تليجرام
        photo = update.message.photo[-1]  # أخذ أكبر نسخة من الصورة
        file_id = photo.file_id
        logger.info(f"Admin {user_id}: Received option image for option {current_index+1}")
        # تخزين معرف الصورة للخيار الحالي
        context.user_data['new_question']['option_image_ids'][current_index] = file_id
        # إرسال رسالة تأكيد مع معاينة الصورة
        option_text = context.user_data['new_question']['options'][current_index]
        update.message.reply_photo(
            photo=file_id,
            caption=f"تم استلام صورة للخيار {current_index+1}: {option_text}"
        )
    else:
        # المستخدم أرسل نصاً للتخطي
        logger.info(f"Admin {user_id}: Skipped option image for option {current_index+1}")
        update.message.reply_text(f"تم تخطي صورة الخيار {current_index+1}.")
        context.user_data['new_question']['option_image_ids'][current_index] = None
    
    # التحقق مما إذا كان هناك المزيد من الخيارات
    current_index += 1
    if current_index < len(context.user_data['new_question']['options']):
        # طلب صورة للخيار التالي
        context.user_data['current_option_index'] = current_index
        option_text = context.user_data['new_question']['options'][current_index]
        update.message.reply_text(
            f"الرجاء إرسال صورة للخيار {current_index+1}: {option_text}\n\n"
            "(يمكنك إرسال أي رسالة نصية للتخطي)"
        )
        return WAITING_OPTION_IMAGE
    else:
        # تم استلام صور لجميع الخيارات، نتابع لحفظ السؤال
        update.message.reply_text("تم الانتهاء من إضافة صور الخيارات. جاري حفظ السؤال...")
        return save_question(update, context)

def save_question(update: Update, context: CallbackContext) -> int:
    """حفظ السؤال في قاعدة البيانات."""
    user_id = update.effective_user.id
    logger.info(f"Admin {user_id}: Saving question to database")
    
    new_question = context.user_data['new_question']
    
    # استخراج البيانات من context.user_data
    question_text = new_question['text']
    options = new_question['options']
    correct_answer_index = new_question['correct_answer']
    explanation = new_question.get('explanation')
    chapter = new_question.get('chapter')
    lesson = new_question.get('lesson')
    question_image_id = new_question.get('question_image_id')
    option_image_ids = new_question.get('option_image_ids')
    
    # حفظ السؤال في قاعدة البيانات
    try:
        success = QUIZ_DB.add_question(
            question_text=question_text,
            options=options,
            correct_answer_index=correct_answer_index,
            explanation=explanation,
            chapter=chapter,
            lesson=lesson,
            question_image_id=question_image_id,
            option_image_ids=option_image_ids
        )
        
        if success:
            message = "✅ تم حفظ السؤال بنجاح في قاعدة البيانات!"
            logger.info(f"Admin {user_id}: Question saved successfully")
        else:
            message = "❌ حدث خطأ أثناء حفظ السؤال. الرجاء المحاولة مرة أخرى."
            logger.error(f"Admin {user_id}: Failed to save question")
    except Exception as e:
        message = f"❌ حدث خطأ غير متوقع: {str(e)}"
        logger.error(f"Admin {user_id}: Error saving question: {e}", exc_info=True)
    
    # تنظيف بيانات المستخدم
    if 'new_question' in context.user_data:
        del context.user_data['new_question']
    if 'current_option_index' in context.user_data:
        del context.user_data['current_option_index']
    if 'conversation_state' in context.user_data:
        del context.user_data['conversation_state']
    
    # إرسال رسالة التأكيد مع زر العودة
    keyboard = [[InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data='menu_admin')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    else:
        update.message.reply_text(message, reply_markup=reply_markup)
    
    return ConversationHandler.END

def cancel_add_question(update: Update, context: CallbackContext) -> int:
    """إلغاء محادثة إضافة سؤال."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} cancelled add question conversation")
    
    # تنظيف بيانات المستخدم
    if 'new_question' in context.user_data:
        del context.user_data['new_question']
    if 'current_option_index' in context.user_data:
        del context.user_data['current_option_index']
    if 'conversation_state' in context.user_data:
        del context.user_data['conversation_state']
    
    update.message.reply_text('تم إلغاء عملية إضافة السؤال.')
    
    # إرسال زر العودة لقائمة الإدارة
    keyboard = [[InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data='menu_admin')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("يمكنك العودة إلى قائمة الإدارة:", reply_markup=reply_markup)
    
    return ConversationHandler.END

# --- إدارة الأسئلة: عرض قائمة الأسئلة ---
def list_questions(update: Update, context: CallbackContext) -> None:
    """عرض قائمة الأسئلة المخزنة في قاعدة البيانات."""
    user_id = update.effective_user.id
    logger.info(f"Admin {user_id}: Listing questions")
    
    if not is_admin(user_id):
        update.callback_query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
        return
    
    # جلب جميع الأسئلة من قاعدة البيانات
    questions = QUIZ_DB.get_all_questions()
    
    if not questions:
        # لا توجد أسئلة في قاعدة البيانات
        keyboard = [[InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data='menu_admin')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.callback_query.edit_message_text(
            "لا توجد أسئلة في قاعدة البيانات حالياً.",
            reply_markup=reply_markup
        )
        return
    
    # إنشاء نص يعرض ملخصاً للأسئلة
    message_text = f"📋 قائمة الأسئلة (العدد الإجمالي: {len(questions)}):\n\n"
    
    for i, q in enumerate(questions, 1):
        # إضافة معلومات مختصرة عن كل سؤال
        question_preview = q['question'][:50] + "..." if len(q['question']) > 50 else q['question']
        chapter_info = f" | الفصل: {q['chapter']}" if q['chapter'] else ""
        lesson_info = f" | الدرس: {q['lesson']}" if q['lesson'] else ""
        has_image = " 🖼️" if q['question_image_id'] else ""
        has_option_images = " 🖼️🖼️" if q['option_image_ids'] and any(q['option_image_ids']) else ""
        
        message_text += f"{i}. ID: {q['id']} | {question_preview}{chapter_info}{lesson_info}{has_image}{has_option_images}\n\n"
        
        # تقسيم الرسالة إذا أصبحت طويلة جداً
        if len(message_text) > 3500 and i < len(questions):
            message_text += f"... وهناك {len(questions) - i} سؤال إضافي."
            break
    
    keyboard = [
        [InlineKeyboardButton("🔍 عرض سؤال معين", callback_data='admin_show_prompt')],
        [InlineKeyboardButton("🗑️ حذف سؤال", callback_data='admin_delete_prompt')],
        [InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data='menu_admin')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.callback_query.edit_message_text(
        message_text,
        reply_markup=reply_markup
    )

# --- إدارة الأسئلة: عرض سؤال معين ---
def show_question_prompt(update: Update, context: CallbackContext) -> int:
    """طلب معرف السؤال المراد عرضه."""
    user_id = update.effective_user.id
    logger.info(f"Admin {user_id}: Show question prompt")
    
    if not is_admin(user_id):
        update.callback_query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
        return ConversationHandler.END
    
    context.user_data['conversation_state'] = 'show_question'
    
    update.callback_query.edit_message_text(
        "الرجاء إرسال معرف (ID) السؤال الذي تريد عرضه:"
    )
    return SHOW_ID

def show_question_by_id(update: Update, context: CallbackContext) -> int:
    """عرض سؤال معين بواسطة معرفه."""
    user_id = update.effective_user.id
    try:
        question_id = int(update.message.text.strip())
        logger.info(f"Admin {user_id}: Showing question ID: {question_id}")
    except ValueError:
        update.message.reply_text(
            "معرف السؤال يجب أن يكون رقماً. الرجاء إرسال رقم صحيح:"
        )
        return SHOW_ID
    
    # جلب السؤال من قاعدة البيانات
    question = QUIZ_DB.get_question_by_id(question_id)
    
    if not question:
        update.message.reply_text(
            f"لم يتم العثور على سؤال بالمعرف {question_id}. الرجاء التحقق من المعرف وإرسال معرف صحيح:"
        )
        return SHOW_ID
    
    # إنشاء نص يعرض تفاصيل السؤال
    message_text = f"📝 السؤال (ID: {question['id']}):\n\n"
    message_text += f"{question['question']}\n\n"
    
    message_text += "الخيارات:\n"
    for i, option in enumerate(question['options']):
        correct_mark = "✅ " if i == question['correct_answer'] else ""
        message_text += f"{i+1}. {correct_mark}{option}\n"
    
    if question['explanation']:
        message_text += f"\nالشرح: {question['explanation']}\n"
    
    if question['chapter']:
        message_text += f"\nالفصل: {question['chapter']}"
    
    if question['lesson']:
        message_text += f"\nالدرس: {question['lesson']}"
    
    # إنشاء أزرار التنقل
    keyboard = [
        [InlineKeyboardButton("🗑️ حذف هذا السؤال", callback_data=f"delete_{question['id']}")],
        [InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data='menu_admin')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # إرسال الصورة إذا كانت موجودة
    if question['question_image_id']:
        update.message.reply_photo(
            photo=question['question_image_id'],
            caption=message_text,
            reply_markup=reply_markup
        )
    else:
        update.message.reply_text(
            message_text,
            reply_markup=reply_markup
        )
    
    # إرسال صور الخيارات إذا كانت موجودة
    if question['option_image_ids'] and any(question['option_image_ids']):
        for i, image_id in enumerate(question['option_image_ids']):
            if image_id:
                option_text = question['options'][i]
                correct_mark = "✅ " if i == question['correct_answer'] else ""
                update.message.reply_photo(
                    photo=image_id,
                    caption=f"صورة الخيار {i+1}: {correct_mark}{option_text}"
                )
    
    # تنظيف بيانات المستخدم
    if 'conversation_state' in context.user_data:
        del context.user_data['conversation_state']
    
    return ConversationHandler.END

# --- إدارة الأسئلة: حذف سؤال ---
def delete_question_prompt(update: Update, context: CallbackContext) -> int:
    """طلب معرف السؤال المراد حذفه."""
    user_id = update.effective_user.id
    logger.info(f"Admin {user_id}: Delete question prompt")
    
    if not is_admin(user_id):
        update.callback_query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
        return ConversationHandler.END
    
    context.user_data['conversation_state'] = 'delete_question'
    
    update.callback_query.edit_message_text(
        "الرجاء إرسال معرف (ID) السؤال الذي تريد حذفه:"
    )
    return DELETE_CONFIRM

def delete_question_confirm(update: Update, context: CallbackContext) -> int:
    """تأكيد حذف سؤال معين."""
    user_id = update.effective_user.id
    try:
        question_id = int(update.message.text.strip())
        logger.info(f"Admin {user_id}: Confirming delete for question ID: {question_id}")
    except ValueError:
        update.message.reply_text(
            "معرف السؤال يجب أن يكون رقماً. الرجاء إرسال رقم صحيح:"
        )
        return DELETE_CONFIRM
    
    # جلب السؤال من قاعدة البيانات للتأكد من وجوده
    question = QUIZ_DB.get_question_by_id(question_id)
    
    if not question:
        update.message.reply_text(
            f"لم يتم العثور على سؤال بالمعرف {question_id}. الرجاء التحقق من المعرف وإرسال معرف صحيح:"
        )
        return DELETE_CONFIRM
    
    # حفظ معرف السؤال في بيانات المستخدم
    context.user_data['delete_question_id'] = question_id
    
    # عرض تفاصيل السؤال وطلب تأكيد الحذف
    message_text = f"📝 هل أنت متأكد من حذف السؤال التالي؟\n\n"
    message_text += f"ID: {question['id']}\n"
    message_text += f"السؤال: {question['question'][:100]}...\n\n"
    
    keyboard = [
        [InlineKeyboardButton("✅ نعم، احذف السؤال", callback_data=f"confirm_delete_{question_id}")],
        [InlineKeyboardButton("❌ لا، إلغاء الحذف", callback_data='cancel_delete')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(
        message_text,
        reply_markup=reply_markup
    )
    
    return ConversationHandler.END

def delete_question_execute(update: Update, context: CallbackContext) -> None:
    """تنفيذ حذف السؤال بعد التأكيد."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    
    if not query.data.startswith('confirm_delete_'):
        # إلغاء الحذف
        logger.info(f"Admin {user_id}: Cancelled question deletion")
        
        keyboard = [[InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data='menu_admin')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        query.edit_message_text(
            "تم إلغاء عملية حذف السؤال.",
            reply_markup=reply_markup
        )
        
        # تنظيف بيانات المستخدم
        if 'delete_question_id' in context.user_data:
            del context.user_data['delete_question_id']
        if 'conversation_state' in context.user_data:
            del context.user_data['conversation_state']
        
        return
    
    # استخراج معرف السؤال من callback_data
    question_id = int(query.data.split('_')[-1])
    logger.info(f"Admin {user_id}: Executing delete for question ID: {question_id}")
    
    # حذف السؤال من قاعدة البيانات
    success = QUIZ_DB.delete_question(question_id)
    
    if success:
        message = f"✅ تم حذف السؤال بمعرف {question_id} بنجاح."
        logger.info(f"Admin {user_id}: Successfully deleted question ID: {question_id}")
    else:
        message = f"❌ حدث خطأ أثناء محاولة حذف السؤال بمعرف {question_id}."
        logger.error(f"Admin {user_id}: Failed to delete question ID: {question_id}")
    
    # تنظيف بيانات المستخدم
    if 'delete_question_id' in context.user_data:
        del context.user_data['delete_question_id']
    if 'conversation_state' in context.user_data:
        del context.user_data['conversation_state']
    
    # إرسال رسالة التأكيد مع زر العودة
    keyboard = [[InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data='menu_admin')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.edit_message_text(
        message,
        reply_markup=reply_markup
    )

# --- استيراد الأسئلة من قناة تليجرام (باستخدام إعادة التوجيه) ---
def import_channel_start(update: Update, context: CallbackContext) -> int:
    """بدء عملية استيراد الأسئلة من قناة تليجرام."""
    user_id = update.effective_user.id
    logger.info(f"Admin {user_id}: Starting channel import conversation")
    
    if not is_admin(user_id):
        update.callback_query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
        return ConversationHandler.END
    
    context.user_data['conversation_state'] = 'import_channel'
    context.user_data['import_stats'] = {'success': 0, 'failed': 0}
    
    update.callback_query.edit_message_text(
        "📥 **استيراد أسئلة من قناة تليجرام**\n\n"
        "نظراً لقيود واجهة برمجة تطبيقات تليجرام، لا يمكن للبوت قراءة سجل الرسائل القديمة مباشرة.\n\n"
        "**الحل:**\n"
        "1. اذهب إلى القناة التي تحتوي على الأسئلة.\n"
        "2. قم **بإعادة توجيه (Forward)** الرسائل التي تحتوي على الأسئلة إلى هذه المحادثة (مع البوت).\n"
        "3. يجب أن تكون الرسائل بالتنسيق الموضح أدناه.\n"
        "4. عند الانتهاء، أرسل الأمر /done\n\n"
        "**التنسيق المطلوب للرسالة:**\n"
        "```"
        "السؤال: نص السؤال هنا\n"
        "الخيارات:\n"
        "أ. الخيار الأول\n"
        "ب. الخيار الثاني\n"
        "ج. الخيار الثالث\n"
        "د. الخيار الرابع\n"
        "الإجابة الصحيحة: أ\n"
        "الشرح: شرح الإجابة هنا (اختياري)\n"
        "الفصل: اسم الفصل هنا (اختياري)\n"
        "الدرس: اسم الدرس هنا (اختياري)"
        "```\n"
        "(يمكن إرفاق صورة مع الرسالة لتكون صورة السؤال)"
        , parse_mode=ParseMode.MARKDOWN
    )
    return WAITING_FORWARDED_QUESTIONS

def parse_question_text(text: str, photo_id: str = None) -> dict | None:
    """تحليل نص الرسالة لاستخراج بيانات السؤال."""
    if not text:
        return None

    data = {
        'question_text': None,
        'options': [],
        'correct_answer_index': None,
        'explanation': None,
        'chapter': None,
        'lesson': None,
        'question_image_id': photo_id
    }

    # تعبيرات نمطية لاستخراج الأجزاء المختلفة
    question_match = re.search(r"(?:السؤال|Question)[:]\s+(.+)", text, re.IGNORECASE | re.MULTILINE)
    options_match = re.search(r"(?:الخيارات|Options)[:]\s+\n?((?:[أ-د]|[a-d]|[1-4])[.]\s+.+\n?)+?", text, re.IGNORECASE | re.MULTILINE)
    correct_answer_match = re.search(r"(?:الإجابة الصحيحة|Correct Answer)[:]\s+([أ-د]|[a-d]|[1-4])", text, re.IGNORECASE | re.MULTILINE)
    explanation_match = re.search(r"(?:الشرح|Explanation)[:]\s+(.+)", text, re.IGNORECASE | re.MULTILINE)
    chapter_match = re.search(r"(?:الفصل|Chapter)[:]\s+(.+)", text, re.IGNORECASE | re.MULTILINE)
    lesson_match = re.search(r"(?:الدرس|Lesson)[:]\s+(.+)", text, re.IGNORECASE | re.MULTILINE)

    if not question_match or not options_match or not correct_answer_match:
        logger.warning("Parsing failed: Missing required fields (Question, Options, Correct Answer)")
        return None

    data['question_text'] = question_match.group(1).strip()
    data['explanation'] = explanation_match.group(1).strip() if explanation_match else None
    data['chapter'] = chapter_match.group(1).strip() if chapter_match else None
    data['lesson'] = lesson_match.group(1).strip() if lesson_match else None

    # تحليل الخيارات
    option_lines = options_match.group(1).strip().split('\n')
    option_map = {}
    option_labels = ['أ', 'ب', 'ج', 'د', 'a', 'b', 'c', 'd', '1', '2', '3', '4']
    for line in option_lines:
        line = line.strip()
        match = re.match(r"([أ-د]|[a-d]|[1-4])[.]\s+(.+)", line)
        if match:
            label = match.group(1).lower()
            option_text = match.group(2).strip()
            data['options'].append(option_text)
            option_map[label] = len(data['options']) - 1 # Store index based on label

    if len(data['options']) < 2:
        logger.warning("Parsing failed: Less than 2 options found.")
        return None

    # تحديد فهرس الإجابة الصحيحة
    correct_label = correct_answer_match.group(1).lower()
    if correct_label in option_map:
        data['correct_answer_index'] = option_map[correct_label]
    else:
        logger.warning(f"Parsing failed: Correct answer label '{correct_label}' not found in options.")
        return None

    return data

def handle_forwarded_question(update: Update, context: CallbackContext) -> int:
    """معالجة رسالة معاد توجيهها تحتوي على سؤال."""
    user_id = update.effective_user.id
    logger.info(f"Admin {user_id}: Received forwarded message for import.")

    # التأكد من أن الرسالة معاد توجيهها
    if not update.message.forward_date:
        update.message.reply_text("الرجاء إعادة توجيه الرسائل من القناة. أرسل /done عند الانتهاء.")
        return WAITING_FORWARDED_QUESTIONS

    # استخراج النص والصورة
    text_content = update.message.text or update.message.caption
    photo_id = update.message.photo[-1].file_id if update.message.photo else None

    # تحليل النص
    parsed_data = parse_question_text(text_content, photo_id)

    if parsed_data:
        try:
            success = QUIZ_DB.add_question(**parsed_data)
            if success:
                context.user_data['import_stats']['success'] += 1
                update.message.reply_text(f"✅ تم استيراد السؤال بنجاح: {parsed_data['question_text'][:50]}...")
            else:
                context.user_data['import_stats']['failed'] += 1
                update.message.reply_text(f"❌ فشل حفظ السؤال في قاعدة البيانات: {parsed_data['question_text'][:50]}...")
        except Exception as e:
            context.user_data['import_stats']['failed'] += 1
            logger.error(f"Error adding imported question to DB: {e}", exc_info=True)
            update.message.reply_text(f"❌ حدث خطأ أثناء حفظ السؤال: {str(e)}")
    else:
        context.user_data['import_stats']['failed'] += 1
        update.message.reply_text("⚠️ لم يتم التعرف على تنسيق السؤال في هذه الرسالة. تم تجاهلها.")

    return WAITING_FORWARDED_QUESTIONS

def end_channel_import(update: Update, context: CallbackContext) -> int:
    """إنهاء عملية استيراد الأسئلة من القناة."""
    user_id = update.effective_user.id
    stats = context.user_data.get('import_stats', {'success': 0, 'failed': 0})
    logger.info(f"Admin {user_id}: Finished channel import. Success: {stats['success']}, Failed: {stats['failed']}")
    
    update.message.reply_text(
        f"🏁 انتهت عملية استيراد الأسئلة.\n\n"
        f"✅ الأسئلة المستوردة بنجاح: {stats['success']}\n"
        f"❌ الرسائل التي فشل استيرادها: {stats['failed']}"
    )
    
    # تنظيف بيانات المستخدم
    if 'import_stats' in context.user_data:
        del context.user_data['import_stats']
    if 'conversation_state' in context.user_data:
        del context.user_data['conversation_state']
        
    # إعادة عرض قائمة الإدارة
    keyboard = [[InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data='menu_admin')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("يمكنك العودة إلى قائمة الإدارة:", reply_markup=reply_markup)
    
    return ConversationHandler.END

# --- وظائف الاختبار ---
def start_random_quiz(update: Update, context: CallbackContext) -> None:
    """بدء اختبار عشوائي."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id}: Starting random quiz")
    
    # جلب سؤال عشوائي من قاعدة البيانات
    question = QUIZ_DB.get_random_question()
    
    if not question:
        # لا توجد أسئلة في قاعدة البيانات
        update.callback_query.edit_message_text(
            "عذراً، لا توجد أسئلة في قاعدة البيانات حالياً. يرجى إضافة أسئلة أولاً.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]])
        )
        return
    
    # تهيئة بيانات الاختبار
    context.user_data['quiz'] = {
        'current_question': question,
        'score': 0,
        'total': 0
    }
    
    # عرض السؤال
    show_question(update, context)

def show_chapter_selection(update: Update, context: CallbackContext) -> None:
    """عرض قائمة الفصول للاختيار منها."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id}: Showing chapter selection")
    
    # جلب قائمة الفصول من قاعدة البيانات
    chapters = QUIZ_DB.get_chapters()
    
    if not chapters:
        # لا توجد فصول في قاعدة البيانات
        update.callback_query.edit_message_text(
            "عذراً، لا توجد فصول محددة في قاعدة البيانات حالياً.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data='menu_quiz')]])
        )
        return
    
    # إنشاء أزرار للفصول
    keyboard = []
    for chapter in chapters:
        keyboard.append([InlineKeyboardButton(f"الفصل {chapter}", callback_data=f"quiz_chapter_{chapter}")])
    
    keyboard.append([InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data='menu_quiz')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.callback_query.edit_message_text(
        "اختر الفصل الذي تريد الاختبار فيه:",
        reply_markup=reply_markup
    )

def show_chapter_for_lesson_selection(update: Update, context: CallbackContext) -> None:
    """عرض قائمة الفصول لاختيار الدرس منها."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id}: Showing chapter selection for lesson")
    
    # جلب قائمة الفصول من قاعدة البيانات
    chapters = QUIZ_DB.get_chapters()
    
    if not chapters:
        # لا توجد فصول في قاعدة البيانات
        update.callback_query.edit_message_text(
            "عذراً، لا توجد فصول محددة في قاعدة البيانات حالياً.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data='menu_quiz')]])
        )
        return
    
    # إنشاء أزرار للفصول
    keyboard = []
    for chapter in chapters:
        keyboard.append([InlineKeyboardButton(f"الفصل {chapter}", callback_data=f"quiz_lesson_chapter_{chapter}")])
    
    keyboard.append([InlineKeyboardButton("🔙 العودة لقائمة الاختبارات", callback_data='menu_quiz')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.callback_query.edit_message_text(
        "اختر الفصل أولاً:",
        reply_markup=reply_markup
    )

def show_lesson_selection(update: Update, context: CallbackContext) -> None:
    """عرض قائمة الدروس للاختيار منها."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    
    # استخراج الفصل من callback_data
    chapter = query.data.split('_')[-1]
    logger.info(f"User {user_id}: Showing lesson selection for chapter {chapter}")
    
    # جلب قائمة الدروس للفصل المحدد
    lessons = QUIZ_DB.get_lessons(chapter)
    
    if not lessons:
        # لا توجد دروس في الفصل المحدد
        query.edit_message_text(
            f"عذراً، لا توجد دروس محددة للفصل {chapter} في قاعدة البيانات حالياً.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لاختيار الفصل", callback_data='quiz_by_lesson')]])
        )
        return
    
    # إنشاء أزرار للدروس
    keyboard = []
    for lesson in lessons:
        keyboard.append([InlineKeyboardButton(f"{lesson}", callback_data=f"quiz_lesson_{chapter}_{lesson}")])
    
    keyboard.append([InlineKeyboardButton("🔙 العودة لاختيار الفصل", callback_data='quiz_by_lesson')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.edit_message_text(
        f"اختر الدرس من الفصل {chapter}:",
        reply_markup=reply_markup
    )

def start_chapter_quiz(update: Update, context: CallbackContext) -> None:
    """بدء اختبار لفصل محدد."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    
    # استخراج الفصل من callback_data
    chapter = query.data.split('_')[-1]
    logger.info(f"User {user_id}: Starting quiz for chapter {chapter}")
    
    # جلب سؤال عشوائي من الفصل المحدد
    question = QUIZ_DB.get_random_question(chapter=chapter)
    
    if not question:
        # لا توجد أسئلة في الفصل المحدد
        query.edit_message_text(
            f"عذراً، لا توجد أسئلة للفصل {chapter} في قاعدة البيانات حالياً.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لاختيار الفصل", callback_data='quiz_by_chapter')]])
        )
        return
    
    # تهيئة بيانات الاختبار
    context.user_data['quiz'] = {
        'current_question': question,
        'score': 0,
        'total': 0,
        'chapter': chapter
    }
    
    # عرض السؤال
    show_question(update, context)

def start_lesson_quiz(update: Update, context: CallbackContext) -> None:
    """بدء اختبار لدرس محدد."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    
    # استخراج الفصل والدرس من callback_data
    parts = query.data.split('_')
    chapter = parts[-2]
    lesson = parts[-1]
    logger.info(f"User {user_id}: Starting quiz for chapter {chapter}, lesson {lesson}")
    
    # جلب سؤال عشوائي من الدرس المحدد
    question = QUIZ_DB.get_random_question(chapter=chapter, lesson=lesson)
    
    if not question:
        # لا توجد أسئلة في الدرس المحدد
        query.edit_message_text(
            f"عذراً، لا توجد أسئلة للدرس {lesson} في الفصل {chapter} في قاعدة البيانات حالياً.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لاختيار الدرس", callback_data=f'quiz_lesson_chapter_{chapter}')]])
        )
        return
    
    # تهيئة بيانات الاختبار
    context.user_data['quiz'] = {
        'current_question': question,
        'score': 0,
        'total': 0,
        'chapter': chapter,
        'lesson': lesson
    }
    
    # عرض السؤال
    show_question(update, context)

def show_question(update: Update, context: CallbackContext) -> None:
    """عرض السؤال الحالي في الاختبار."""
    query = update.callback_query
    
    # الحصول على السؤال الحالي
    question = context.user_data['quiz']['current_question']
    
    # إنشاء نص السؤال
    question_text = f"📝 السؤال:\n\n{question['question']}\n\n"
    question_text += "الخيارات:\n"
    
    # إنشاء أزرار للخيارات
    keyboard = []
    for i, option in enumerate(question['options']):
        option_text = f"{i+1}. {option}"
        keyboard.append([InlineKeyboardButton(option_text, callback_data=f"quiz_answer_{i}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # إرسال السؤال
    if question['question_image_id']:
        # إذا كان السؤال يحتوي على صورة
        if query:
            # إذا كان هناك callback_query، نحتاج إلى إرسال رسالة جديدة
            context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=question['question_image_id'],
                caption=question_text,
                reply_markup=reply_markup
            )
            # حذف الرسالة السابقة إذا لم تكن الرسالة الأولى في الاختبار
            if context.user_data['quiz']['total'] > 0:
                query.delete_message()
        else:
            # إذا لم يكن هناك callback_query (مثلاً عند بدء الاختبار)
            update.effective_message.reply_photo(
                photo=question['question_image_id'],
                caption=question_text,
                reply_markup=reply_markup
            )
    else:
        # إذا كان السؤال بدون صورة
        if query:
            query.edit_message_text(
                text=question_text,
                reply_markup=reply_markup
            )
        else:
            update.effective_message.reply_text(
                text=question_text,
                reply_markup=reply_markup
            )
    
    # إرسال صور الخيارات إذا كانت موجودة
    if question['option_image_ids'] and any(question['option_image_ids']):
        chat_id = update.effective_chat.id
        for i, image_id in enumerate(question['option_image_ids']):
            if image_id:
                option_text = f"صورة الخيار {i+1}: {question['options'][i]}"
                context.bot.send_photo(
                    chat_id=chat_id,
                    photo=image_id,
                    caption=option_text
                )

def handle_quiz_answer(update: Update, context: CallbackContext) -> None:
    """معالجة إجابة المستخدم على سؤال الاختبار."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    
    # استخراج رقم الخيار المختار من callback_data
    selected_index = int(query.data.split('_')[-1])
    logger.info(f"User {user_id}: Selected answer index: {selected_index}")
    
    # الحصول على السؤال الحالي
    question = context.user_data['quiz']['current_question']
    correct_index = question['correct_answer']
    
    # التحقق من الإجابة
    is_correct = selected_index == correct_index
    
    # تحديث النتيجة
    context.user_data['quiz']['total'] += 1
    if is_correct:
        context.user_data['quiz']['score'] += 1
    
    # إنشاء نص النتيجة
    result_text = f"📝 السؤال:\n\n{question['question']}\n\n"
    result_text += "الخيارات:\n"
    
    for i, option in enumerate(question['options']):
        if i == selected_index and i == correct_index:
            prefix = "✅ "  # إجابة صحيحة
        elif i == selected_index:
            prefix = "❌ "  # إجابة خاطئة
        elif i == correct_index:
            prefix = "✓ "  # الإجابة الصحيحة
        else:
            prefix = ""
        
        result_text += f"{i+1}. {prefix}{option}\n"
    
    # إضافة الشرح إذا كان موجوداً
    if question['explanation']:
        result_text += f"\nالشرح: {question['explanation']}\n"
    
    # إضافة النتيجة الحالية
    score = context.user_data['quiz']['score']
    total = context.user_data['quiz']['total']
    result_text += f"\nالنتيجة الحالية: {score}/{total} ({int(score/total*100)}%)"
    
    # إنشاء أزرار التنقل
    keyboard = [
        [InlineKeyboardButton("📝 سؤال آخر", callback_data='quiz_next')],
        [InlineKeyboardButton("🏁 إنهاء الاختبار", callback_data='quiz_end')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # إرسال النتيجة
    if question['question_image_id']:
        # إذا كان السؤال يحتوي على صورة، نرسل رسالة جديدة
        context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=question['question_image_id'],
            caption=result_text,
            reply_markup=reply_markup
        )
        # حذف الرسالة السابقة
        query.delete_message()
    else:
        # إذا كان السؤال بدون صورة
        query.edit_message_text(
            text=result_text,
            reply_markup=reply_markup
        )

def show_next_question(update: Update, context: CallbackContext) -> None:
    """عرض السؤال التالي في الاختبار."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id}: Requesting next question")
    
    # التحقق من نوع الاختبار وجلب السؤال التالي
    quiz_data = context.user_data['quiz']
    
    if 'lesson' in quiz_data:
        # اختبار حسب الدرس
        question = QUIZ_DB.get_random_question(chapter=quiz_data['chapter'], lesson=quiz_data['lesson'])
    elif 'chapter' in quiz_data:
        # اختبار حسب الفصل
        question = QUIZ_DB.get_random_question(chapter=quiz_data['chapter'])
    else:
        # اختبار عشوائي
        question = QUIZ_DB.get_random_question()
    
    if not question:
        # لا توجد أسئلة إضافية
        query.edit_message_text(
            "عذراً، لا توجد أسئلة إضافية متاحة.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]])
        )
        return
    
    # تحديث السؤال الحالي
    context.user_data['quiz']['current_question'] = question
    
    # عرض السؤال
    show_question(update, context)

def end_quiz(update: Update, context: CallbackContext) -> None:
    """إنهاء الاختبار وعرض النتيجة النهائية."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id}: Ending quiz")
    
    # الحصول على النتيجة
    score = context.user_data['quiz']['score']
    total = context.user_data['quiz']['total']
    percentage = int(score/total*100) if total > 0 else 0
    
    # إنشاء نص النتيجة النهائية
    result_text = "🏁 انتهى الاختبار!\n\n"
    result_text += f"النتيجة النهائية: {score}/{total} ({percentage}%)\n\n"
    
    # تقييم الأداء
    if percentage >= 90:
        result_text += "🌟 ممتاز! أداء رائع!"
    elif percentage >= 80:
        result_text += "👍 جيد جداً! استمر في التعلم."
    elif percentage >= 70:
        result_text += "👌 جيد. يمكنك التحسن أكثر."
    elif percentage >= 60:
        result_text += "🙂 مقبول. تحتاج إلى مزيد من الدراسة."
    else:
        result_text += "📚 تحتاج إلى مزيد من الدراسة والمراجعة."
    
    # إنشاء أزرار التنقل
    keyboard = [
        [InlineKeyboardButton("🔄 اختبار جديد", callback_data='menu_quiz')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # إرسال النتيجة النهائية
    # تعديل: التحقق مما إذا كانت الرسالة الحالية تحتوي على صورة
    try:
        query.edit_message_text(
            text=result_text,
            reply_markup=reply_markup
        )
    except TelegramError as e:
        # إذا كانت الرسالة تحتوي على صورة، نرسل رسالة جديدة بدلاً من تعديل الرسالة الحالية
        if "There is no text in the message to edit" in str(e):
            context.bot.send_message(
                chat_id=query.message.chat_id,
                text=result_text,
                reply_markup=reply_markup
            )
        else:
            logger.error(f"Error ending quiz: {e}")
            raise
    
    # تنظيف بيانات الاختبار
    if 'quiz' in context.user_data:
        del context.user_data['quiz']

# --- معالج الأخطاء ---
def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error("Update \"%s\" caused error \"%s\"", update, context.error, exc_info=context.error)
    # يمكنك إضافة إرسال رسالة للمستخدم هنا إذا أردت
    if isinstance(context.error, Unauthorized):
        # التعامل مع خطأ التوكن غير المصرح به
        logger.error("Unauthorized error - check bot token")
    elif isinstance(context.error, NetworkError):
        # التعامل مع أخطاء الشبكة
        logger.error("Network error - check internet connection")

# --- الدالة الرئيسية ---
def main() -> None:
    """بدء تشغيل البوت."""
    # التحقق من وجود التوكن
    if TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.critical("CRITICAL ERROR: Bot token is not set! Please replace 'YOUR_BOT_TOKEN_HERE' with your actual bot token.")
        sys.exit("Bot token not configured.")
    
    # إنشاء Updater وتمرير توكن البوت إليه.
    updater = Updater(TOKEN, use_context=True)

    # الحصول على المرسل لتسجيل المعالجات
    dispatcher = updater.dispatcher

    # --- تسجيل المعالجات --- 
    
    # 1. معالج الأمر /start
    dispatcher.add_handler(CommandHandler("start", start_command))

    # 2. معالج الأمر /about (إذا كنت تريد استخدامه كأمر أيضاً)
    dispatcher.add_handler(CommandHandler("about", about_command))

    # 3. محادثة إضافة سؤال جديد
    add_question_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_question_start, pattern='^admin_add$')],
        states={
            ADD_QUESTION_TEXT: [MessageHandler(Filters.text & ~Filters.command, add_question_text)],
            ADD_OPTIONS: [MessageHandler(Filters.text & ~Filters.command, add_question_options)],
            ADD_CORRECT_ANSWER: [CallbackQueryHandler(add_question_correct_answer, pattern='^correct_[0-9]+$')],
            ADD_EXPLANATION: [MessageHandler(Filters.text & ~Filters.command, add_question_explanation)],
            ADD_CHAPTER: [MessageHandler(Filters.text & ~Filters.command, add_question_chapter)],
            ADD_LESSON: [MessageHandler(Filters.text & ~Filters.command, add_question_lesson)],
            ADD_QUESTION_IMAGE_PROMPT: [CallbackQueryHandler(add_question_image_prompt, pattern='^add_image_(yes|no)$')],
            WAITING_QUESTION_IMAGE: [MessageHandler(Filters.photo, add_question_image)],
            ADD_OPTION_IMAGES_PROMPT: [CallbackQueryHandler(add_option_images_prompt, pattern='^add_option_images_(yes|no)$')],
            WAITING_OPTION_IMAGE: [MessageHandler(Filters.photo | (Filters.text & ~Filters.command), add_option_image)], # السماح بالنص للتخطي
        },
        fallbacks=[CommandHandler('cancel', cancel_add_question)],
        per_message=False,
    )
    dispatcher.add_handler(add_question_conv_handler)

    # 4. محادثة عرض سؤال معين
    show_question_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(show_question_prompt, pattern='^admin_show_prompt$')],
        states={
            SHOW_ID: [MessageHandler(Filters.text & ~Filters.command, show_question_by_id)],
        },
        fallbacks=[CommandHandler('cancel', cancel_add_question)], # يمكن استخدام نفس دالة الإلغاء
        per_message=False,
    )
    dispatcher.add_handler(show_question_conv_handler)

    # 5. محادثة حذف سؤال
    delete_question_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(delete_question_prompt, pattern='^admin_delete_prompt$')],
        states={
            DELETE_CONFIRM: [MessageHandler(Filters.text & ~Filters.command, delete_question_confirm)],
        },
        fallbacks=[CommandHandler('cancel', cancel_add_question)], # يمكن استخدام نفس دالة الإلغاء
        per_message=False,
    )
    dispatcher.add_handler(delete_question_conv_handler)

    # 6. معالج تأكيد/إلغاء حذف سؤال
    dispatcher.add_handler(CallbackQueryHandler(delete_question_execute, pattern='^(confirm_delete_[0-9]+|cancel_delete)$'))

    # 7. محادثة استيراد الأسئلة من قناة (باستخدام إعادة التوجيه)
    import_channel_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(import_channel_start, pattern='^admin_import_channel$')],
        states={
            WAITING_FORWARDED_QUESTIONS: [MessageHandler(Filters.forwarded & (Filters.text | Filters.caption | Filters.photo), handle_forwarded_question)],
        },
        fallbacks=[CommandHandler('done', end_channel_import)],
        per_message=False,
    )
    dispatcher.add_handler(import_channel_conv_handler)

    # 8. معالجات أزرار الاختبار
    dispatcher.add_handler(CallbackQueryHandler(start_random_quiz, pattern='^quiz_random$'))
    dispatcher.add_handler(CallbackQueryHandler(show_chapter_selection, pattern='^quiz_by_chapter$'))
    dispatcher.add_handler(CallbackQueryHandler(show_chapter_for_lesson_selection, pattern='^quiz_by_lesson$'))
    dispatcher.add_handler(CallbackQueryHandler(start_chapter_quiz, pattern='^quiz_chapter_'))
    dispatcher.add_handler(CallbackQueryHandler(show_lesson_selection, pattern='^quiz_lesson_chapter_'))
    dispatcher.add_handler(CallbackQueryHandler(start_lesson_quiz, pattern='^quiz_lesson_[^c]')) # نمط معدل لتجنب التعارض
    dispatcher.add_handler(CallbackQueryHandler(handle_quiz_answer, pattern='^quiz_answer_'))
    dispatcher.add_handler(CallbackQueryHandler(show_next_question, pattern='^quiz_next$'))
    dispatcher.add_handler(CallbackQueryHandler(end_quiz, pattern='^quiz_end$'))

    # 9. معالج أزرار القوائم (يجب أن يكون بعد معالجات المحادثات المحددة)
    dispatcher.add_handler(CallbackQueryHandler(main_menu_button_handler))

    # 10. تسجيل معالج الأخطاء
    dispatcher.add_error_handler(error_handler)

    # بدء البوت
    updater.start_polling()
    logger.info("Bot started polling...")

    # تشغيل البوت حتى يتم الضغط على Ctrl-C
    updater.idle()
    logger.info("Bot stopped.")

if __name__ == '__main__':
    main()
