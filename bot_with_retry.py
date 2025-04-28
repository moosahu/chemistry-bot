#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import random
import os
import time
import sys
import base64
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
ADMIN_USER_ID = 6448526509 # !!! استبدل هذا بمعرف المستخدم الرقمي الخاص بك (مثال: 123456789) !!!
# توكن البوت
TOKEN = "8167394360:AAG-b3v-VDmxLtWVQCuBkc694Mt3ZCs18IY" # !!! استبدل هذا بتوكن البوت الخاص بك بدقة تامة !!!

# تكوين التسجيل (مستوى DEBUG للتشخيص)
log_file_path = os.path.join(os.path.dirname(__file__), 'bot_log.txt')
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG, # تغيير المستوى إلى DEBUG للحصول على تفاصيل أكثر
    handlers=[
        logging.StreamHandler(sys.stdout) # تسجيل في المخرجات القياسية (Heroku logs)
    ]
)
logger = logging.getLogger(__name__)

logger.debug("DEBUG: Script started, basic configurations set.")

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


# حالات المحادثة لإضافة سؤال وحذف/عرض سؤال
(ADD_QUESTION_TEXT, ADD_OPTIONS, ADD_CORRECT_ANSWER, ADD_EXPLANATION, ADD_CHAPTER, ADD_LESSON, 
 ADD_QUESTION_IMAGE_PROMPT, WAITING_QUESTION_IMAGE, DELETE_CONFIRM, SHOW_ID, IMPORT_CHANNEL_PROMPT) = range(11)

# --- وظائف التحقق من الصلاحيات ---
def is_admin(user_id: int) -> bool:
    """التحقق مما إذا كان المستخدم هو المسؤول."""
    logger.debug(f"DEBUG: Checking admin status for user_id: {user_id}")
    if ADMIN_USER_ID is None:
        logger.warning("ADMIN_USER_ID غير معين. سيتم السماح للجميع بإدارة قاعدة البيانات.")
        return True # السماح للجميع إذا لم يتم تعيين المسؤول
    is_admin_check = (user_id == ADMIN_USER_ID)
    logger.debug(f"DEBUG: Is user {user_id} admin? {is_admin_check}")
    return is_admin_check

# --- الدوال المساعدة للقوائم ---
def show_main_menu(update: Update, context: CallbackContext, message_text: str = None) -> None:
    """عرض القائمة الرئيسية مع الأزرار."""
    logger.debug("DEBUG: Entering show_main_menu function")
    keyboard = [
        [InlineKeyboardButton("📚 المعلومات الكيميائية", callback_data='menu_info')],
        [InlineKeyboardButton("📝 الاختبارات", callback_data='menu_quiz')],
        [InlineKeyboardButton("ℹ️ حول البوت", callback_data='menu_about')],
    ]
    if is_admin(update.effective_user.id):
        logger.debug("DEBUG: User is admin, adding admin menu button.")
        keyboard.append([InlineKeyboardButton("⚙️ إدارة الأسئلة", callback_data='menu_admin')])

    reply_markup = InlineKeyboardMarkup(keyboard)

    if message_text is None:
        user = update.effective_user
        message_text = (
            f"مرحباً بك في بوت الكيمياء التحصيلي 🧪\n\n"
            f"أهلاً {user.first_name}! 👋\n\n"
            f"اختر أحد الخيارات أدناه:"
        )

    logger.debug(f"DEBUG: Preparing to send/edit main menu message. Callback query: {update.callback_query is not None}, Message: {update.message is not None}")
    if update.callback_query:
        try:
            logger.debug("DEBUG: Editing message to show main menu.")
            update.callback_query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        except TelegramError as e:
            logger.error(f"Error editing message: {e}")
            if "Message is not modified" not in str(e):
                try:
                    logger.debug("DEBUG: Sending new message after edit error.")
                    update.effective_message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
                except Exception as send_error:
                     logger.error(f"Failed to send new message after edit error: {send_error}")
    elif update.message:
        logger.debug("DEBUG: Replying with main menu.")
        update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    logger.debug("DEBUG: Exiting show_main_menu function")

def show_admin_menu(update: Update, context: CallbackContext) -> None:
    """عرض قائمة إدارة الأسئلة للمسؤول."""
    logger.debug("DEBUG: Entering show_admin_menu function")
    if not is_admin(update.effective_user.id):
        logger.warning(f"DEBUG: Non-admin user {update.effective_user.id} tried to access admin menu.")
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
    logger.debug("DEBUG: Editing message to show admin menu.")
    update.callback_query.edit_message_text("⚙️ اختر عملية إدارة الأسئلة:", reply_markup=reply_markup)
    logger.debug("DEBUG: Exiting show_admin_menu function")

# --- معالجات الأوامر الأساسية ---
def start_command(update: Update, context: CallbackContext) -> None:
    """معالجة الأمر /start."""
    user_id = update.effective_user.id
    logger.info(f"Received /start command from user {user_id}")
    logger.debug(f"DEBUG: Entering start_command function for user {user_id}")
    # إيقاف أي محادثة نشطة عند البدء
    if 'conversation_state' in context.user_data:
        logger.info(f"Ending active conversation for user {user_id} due to /start command.")
        del context.user_data['conversation_state']
    show_main_menu(update, context)
    logger.debug(f"DEBUG: Exiting start_command function for user {user_id}")

def about_command(update: Update, context: CallbackContext) -> None:
    """عرض معلومات حول البوت."""
    logger.debug("DEBUG: Entering about_command function")
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
        logger.debug("DEBUG: Editing message to show about info.")
        update.callback_query.edit_message_text(about_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    elif update.message:
        logger.debug("DEBUG: Replying with about info.")
        update.message.reply_text(about_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    logger.debug("DEBUG: Exiting about_command function")

# --- معالجات أزرار القوائم الرئيسية وقوائم أخرى (مهم جداً!) ---
def main_menu_button_handler(update: Update, context: CallbackContext) -> int:
    """معالجة الضغط على أزرار القائمة الرئيسية وقوائم فرعية أخرى."""
    query = update.callback_query
    query.answer() # مهم جداً لإعلام تليجرام باستلام الاستعلام
    data = query.data
    user_id = update.effective_user.id
    logger.info(f"Button pressed: {data} by user {user_id}")
    logger.debug(f"DEBUG: Entering main_menu_button_handler. Data: {data}, User: {user_id}")

    # إيقاف أي محادثة نشطة عند العودة للقائمة الرئيسية أو قوائم أخرى
    # يجب التحقق من وجود المفتاح قبل حذفه
    if data in ['main_menu', 'menu_info', 'menu_quiz', 'menu_admin'] and 'conversation_state' in context.user_data:
        logger.info(f"Ending conversation for user {user_id} due to menu navigation to {data}.")
        del context.user_data['conversation_state']
        # يمكنك إضافة رسالة للمستخدم هنا إذا أردت

    next_state = ConversationHandler.END # القيمة الافتراضية هي إنهاء أي محادثة

    if data == 'main_menu':
        show_main_menu(update, context, message_text="القائمة الرئيسية 👇")
    elif data == 'menu_info':
        # show_info_menu(update, context) # يجب إضافة هذه الدالة إذا كانت موجودة
        logger.warning("DEBUG: show_info_menu function not implemented yet.")
        query.edit_message_text("قائمة المعلومات الكيميائية (قيد الإنشاء)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data='main_menu')]]))
    elif data == 'menu_quiz':
        # show_quiz_menu(update, context) # يجب إضافة هذه الدالة إذا كانت موجودة
        logger.warning("DEBUG: show_quiz_menu function not implemented yet.")
        query.edit_message_text("قائمة الاختبارات (قيد الإنشاء)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data='main_menu')]]))
    elif data == 'menu_about':
        about_command(update, context)
    elif data == 'menu_admin':
        show_admin_menu(update, context)
    # --- معالجات أزرار قائمة الإدارة ---
    elif data == 'admin_add':
        if not is_admin(user_id):
            logger.warning(f"DEBUG: Non-admin user {user_id} tried admin_add.")
            query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
        else:
            logger.debug("DEBUG: Starting add_question conversation.")
            # next_state = add_question_start(update, context) # يجب إضافة هذه الدالة
            logger.warning("DEBUG: add_question_start function not implemented yet.")
            query.edit_message_text("ميزة إضافة سؤال (قيد الإنشاء)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data='menu_admin')]]))
            next_state = ConversationHandler.END # مؤقتاً حتى يتم إضافة المحادثة
    elif data == 'admin_list':
        # list_questions(update, context) # يجب إضافة هذه الدالة
        logger.warning("DEBUG: list_questions function not implemented yet.")
        query.edit_message_text("قائمة الأسئلة (قيد الإنشاء)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data='menu_admin')]]))
    elif data == 'admin_delete_prompt':
        if not is_admin(user_id):
            logger.warning(f"DEBUG: Non-admin user {user_id} tried admin_delete_prompt.")
            query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
        else:
            logger.debug("DEBUG: Starting delete_question conversation.")
            # next_state = delete_question_prompt(update, context) # يجب إضافة هذه الدالة
            logger.warning("DEBUG: delete_question_prompt function not implemented yet.")
            query.edit_message_text("ميزة حذف سؤال (قيد الإنشاء)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data='menu_admin')]]))
            next_state = ConversationHandler.END # مؤقتاً
    elif data == 'admin_show_prompt':
        if not is_admin(user_id):
            logger.warning(f"DEBUG: Non-admin user {user_id} tried admin_show_prompt.")
            query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
        else:
            logger.debug("DEBUG: Starting show_question conversation.")
            # next_state = show_question_prompt(update, context) # يجب إضافة هذه الدالة
            logger.warning("DEBUG: show_question_prompt function not implemented yet.")
            query.edit_message_text("ميزة عرض سؤال (قيد الإنشاء)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data='menu_admin')]]))
            next_state = ConversationHandler.END # مؤقتاً
    elif data == 'admin_import_channel':
        if not is_admin(user_id):
            logger.warning(f"DEBUG: Non-admin user {user_id} tried admin_import_channel.")
            query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
        else:
            logger.debug("DEBUG: Starting import_channel conversation.")
            next_state = import_channel_start(update, context) # هذه الدالة موجودة
    else:
        logger.warning(f"DEBUG: Unhandled button data: {data}")
        query.edit_message_text("خيار غير معروف.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')]]))

    logger.debug(f"DEBUG: Exiting main_menu_button_handler. Returning state: {next_state}")
    return next_state

# --- استيراد الأسئلة من قناة تليجرام ---
def import_channel_start(update: Update, context: CallbackContext) -> int:
    """بدء عملية استيراد الأسئلة من قناة تليجرام."""
    user_id = update.effective_user.id
    logger.info(f"Admin {user_id}: Starting channel import conversation")
    logger.debug("DEBUG: Entering import_channel_start function")
    
    if not is_admin(user_id):
        logger.warning(f"DEBUG: Non-admin user {user_id} blocked from import_channel_start.")
        update.callback_query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
        return ConversationHandler.END
    
    context.user_data['conversation_state'] = 'import_channel'
    logger.debug("DEBUG: Set conversation_state to 'import_channel'")
    update.callback_query.edit_message_text(
        "📥 استيراد أسئلة من قناة تليجرام\n\n"
        "الرجاء إرسال معرف القناة أو رابطها (مثال: @channel_name أو https://t.me/channel_name)\n\n"
        "ملاحظة: يجب أن يكون البوت عضواً في القناة ليتمكن من قراءة الرسائل."
    )
    logger.debug("DEBUG: Exiting import_channel_start function, returning IMPORT_CHANNEL_PROMPT state.")
    return IMPORT_CHANNEL_PROMPT

def process_channel_import(update: Update, context: CallbackContext) -> int:
    """معالجة معرف القناة واستيراد الأسئلة منها."""
    user_id = update.effective_user.id
    channel_id_input = update.message.text.strip()
    logger.info(f"Admin {user_id}: Processing channel import from input: {channel_id_input}")
    logger.debug("DEBUG: Entering process_channel_import function")
    
    # تنظيف معرف القناة
    if channel_id_input.startswith('https://t.me/'):
        channel_id = '@' + channel_id_input.split('/')[-1]
    elif not channel_id_input.startswith('@'):
        channel_id = '@' + channel_id_input
    else:
        channel_id = channel_id_input
    logger.debug(f"DEBUG: Cleaned channel_id: {channel_id}")
    
    # إرسال رسالة انتظار
    status_message = update.message.reply_text(
        f"جاري محاولة الوصول إلى القناة {channel_id}...\n"
        "قد تستغرق هذه العملية بعض الوقت حسب عدد الرسائل في القناة."
    )
    logger.debug("DEBUG: Sent status message.")
    
    try:
        # محاولة الوصول إلى القناة
        logger.debug(f"DEBUG: Sending typing action to chat {update.effective_chat.id}")
        context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
        
        imported_count = 0
        failed_count = 0
        
        try:
            logger.debug(f"DEBUG: Attempting to send and delete test message in channel {channel_id}")
            test_msg = context.bot.send_message(chat_id=channel_id, text="اختبار الوصول")
            context.bot.delete_message(chat_id=channel_id, message_id=test_msg.message_id)
            logger.debug("DEBUG: Test message sent and deleted successfully.")
            
            status_message.edit_text(
                f"تم الوصول إلى القناة {channel_id} بنجاح!\n"
                "جاري تحليل الرسائل واستخراج الأسئلة...\n\n"
                "ملاحظة: سيتم استيراد الأسئلة التي تتبع التنسيق التالي:\n"
                "- نص السؤال\n"
                "- أربعة خيارات (أ، ب، ج، د) أو (1، 2، 3، 4)\n"
                "- الإجابة الصحيحة مشار إليها بوضوح"
            )
            logger.debug("DEBUG: Edited status message - channel access successful.")
            
            # --- قسم الاستيراد الفعلي (قيد التطوير) ---
            logger.warning("DEBUG: Actual channel import logic is not implemented yet.")
            # هنا يجب إضافة الكود لتحليل الرسائل واستخراج الأسئلة
            # مثال بسيط جداً (للتوضيح فقط):
            # messages = context.bot.get_chat_history(chat_id=channel_id, limit=100) # هذا قد لا يعمل في v13.15
            # for msg in messages:
            #     if msg.text and "السؤال:" in msg.text:
            #         try:
            #             # تحليل السؤال وإضافته لقاعدة البيانات
            #             # ...
            #             imported_count += 1
            #         except Exception as parse_error:
            #             logger.error(f"Error parsing message {msg.message_id}: {parse_error}")
            #             failed_count += 1
            # --- نهاية قسم الاستيراد الفعلي ---
            
            update.message.reply_text(
                "🔍 تعليمات استيراد الأسئلة من القناة:\n\n"
                "لضمان استيراد الأسئلة بشكل صحيح، يجب أن تكون الرسائل في القناة بالتنسيق التالي:\n\n"
                "<b>السؤال:</b> نص السؤال هنا\n"
                "<b>الخيارات:</b>\n"
                "أ. الخيار الأول\n"
                "ب. الخيار الثاني\n"
                "ج. الخيار الثالث\n"
                "د. الخيار الرابع\n"
                "<b>الإجابة الصحيحة:</b> أ\n"
                "<b>الشرح:</b> شرح الإجابة هنا (اختياري)\n"
                "<b>الفصل:</b> اسم الفصل هنا (اختياري)\n"
                "<b>الدرس:</b> اسم الدرس هنا (اختياري)\n\n"
                "يمكنك أيضاً إرفاق صورة مع السؤال إذا كنت ترغب في ذلك.",
                parse_mode=ParseMode.HTML
            )
            logger.debug("DEBUG: Sent import instructions.")
            
            update.message.reply_text(
                f"⚠️ ميزة استيراد الأسئلة من القناة قيد التطوير حالياً.\n\n"
                f"تم استيراد {imported_count} سؤال بنجاح وفشل استيراد {failed_count} سؤال (في هذا الإصدار التجريبي).\n\n"
                "سيتم إطلاق ميزة الاستيراد التلقائي الكاملة في تحديث قريب. شكراً لتفهمك!"
            )
            logger.debug("DEBUG: Sent 'under development' message.")
            
        except Unauthorized as e:
            logger.error(f"Unauthorized error accessing channel {channel_id}: {e}")
            update.message.reply_text(
                f"❌ خطأ: البوت ليس عضواً في القناة {channel_id} أو لا يملك الصلاحيات الكافية.\n\n"
                "يجب إضافة البوت كعضو في القناة أولاً والتأكد من صلاحياته."
            )
        except TelegramError as e:
            # التعامل مع أخطاء تليجرام الأخرى مثل عدم العثور على القناة
            logger.error(f"Telegram error accessing channel {channel_id}: {e}")
            update.message.reply_text(
                f"❌ خطأ تليجرام أثناء محاولة الوصول للقناة {channel_id}: {e}\n\n"
                "يرجى التأكد من صحة معرف القناة وأنها موجودة."
            )
        except Exception as e:
            logger.error(f"Unexpected error during channel import processing: {e}", exc_info=True)
            update.message.reply_text(
                f"❌ حدث خطأ غير متوقع أثناء محاولة استيراد الأسئلة: {str(e)}"
            )
    
    except Exception as e:
        logger.error(f"General error in channel import conversation: {e}", exc_info=True)
        update.message.reply_text(f"❌ حدث خطأ عام: {str(e)}")
    
    # إنهاء المحادثة
    if 'conversation_state' in context.user_data:
        logger.debug("DEBUG: Clearing conversation_state.")
        del context.user_data['conversation_state']
    
    # إعادة عرض قائمة الإدارة
    keyboard = [[InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data='menu_admin')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("انتهت عملية الاستيراد. يمكنك العودة إلى قائمة الإدارة.", reply_markup=reply_markup)
    logger.debug("DEBUG: Exiting process_channel_import function, returning ConversationHandler.END state.")
    return ConversationHandler.END

def cancel_import_channel(update: Update, context: CallbackContext) -> int:
    """إلغاء عملية استيراد الأسئلة من القناة."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} cancelled channel import.")
    logger.debug("DEBUG: Entering cancel_import_channel function")
    update.message.reply_text('تم إلغاء عملية استيراد الأسئلة من القناة.')
    if 'conversation_state' in context.user_data:
        logger.debug("DEBUG: Clearing conversation_state on cancel.")
        del context.user_data['conversation_state']
    logger.debug("DEBUG: Exiting cancel_import_channel function, returning ConversationHandler.END state.")
    return ConversationHandler.END

# --- معالج الأخطاء ---
def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error("Update \"%s\" caused error \"%s\"", update, context.error, exc_info=context.error)
    # تسجيل نوع الخطأ
    error_type = type(context.error).__name__
    logger.error(f"Error Type: {error_type}")
    
    if isinstance(context.error, Unauthorized):
        # التعامل مع خطأ التوكن غير المصرح به
        logger.critical("CRITICAL: Unauthorized error - BOT TOKEN IS LIKELY INVALID OR REVOKED! Please check the token immediately.")
        # يمكنك محاولة إرسال رسالة للمسؤول إذا كان معرفه متاحاً
        if ADMIN_USER_ID:
            try:
                context.bot.send_message(chat_id=ADMIN_USER_ID, text="🚨 خطأ فادح: البوت غير مصرح له بالوصول (Unauthorized). يرجى التحقق من توكن البوت فوراً!")
            except Exception as send_admin_error:
                logger.error(f"Failed to send critical error message to admin: {send_admin_error}")
    elif isinstance(context.error, NetworkError):
        # التعامل مع أخطاء الشبكة
        logger.error("Network error - check internet connection and Telegram API status.")
        # قد يكون من المفيد إعادة المحاولة بعد فترة
    elif isinstance(context.error, TelegramError):
        # أخطاء تليجرام أخرى
        logger.error(f"Telegram API error: {context.error}")
    else:
        # أخطاء أخرى غير متوقعة
        logger.error(f"An unexpected error occurred: {context.error}")

# --- الدالة الرئيسية ---
def main() -> None:
    """بدء تشغيل البوت."""
    logger.info("--- Starting Bot --- ")
    
    # التحقق من وجود التوكن
    if TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.critical("CRITICAL ERROR: Bot token is not set! Please replace 'YOUR_BOT_TOKEN_HERE' with your actual bot token.")
        sys.exit("Bot token not configured.")
    if ADMIN_USER_ID == 123456789:
         logger.warning("WARNING: ADMIN_USER_ID is set to the default example value. Please replace it with your actual Telegram user ID for admin functions to work correctly.")

    # إنشاء Updater وتمرير توكن البوت إليه.
    updater = Updater(TOKEN, use_context=True)
    logger.debug("DEBUG: Updater created.")

    # الحصول على المرسل لتسجيل المعالجات
    dispatcher = updater.dispatcher
    logger.debug("DEBUG: Dispatcher obtained.")

    # --- تسجيل المعالجات (Handlers) --- 
    logger.debug("DEBUG: Registering handlers...")
    
    # 1. معالج الأمر /start
    dispatcher.add_handler(CommandHandler("start", start_command))
    logger.debug("DEBUG: Registered start_command handler.")

    # 2. معالج الأمر /about (إذا كنت تريد استخدامه كأمر أيضاً)
    dispatcher.add_handler(CommandHandler("about", about_command))
    logger.debug("DEBUG: Registered about_command handler.")

    # 3. معالج أزرار القوائم (مهم جداً!)
    # يجب أن يكون هذا المعالج قادراً على التعامل مع جميع بيانات callback_data
    dispatcher.add_handler(CallbackQueryHandler(main_menu_button_handler))
    logger.debug("DEBUG: Registered main_menu_button_handler (CallbackQueryHandler).")

    # 4. محادثة استيراد الأسئلة من قناة (موجودة بالفعل)
    import_channel_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(import_channel_start, pattern='^admin_import_channel$')],
        states={
            IMPORT_CHANNEL_PROMPT: [MessageHandler(Filters.text & ~Filters.command, process_channel_import)],
        },
        fallbacks=[CommandHandler('cancel', cancel_import_channel)],
        # per_message=False, # يفضل تعيينها لـ False لتجنب المشاكل مع الأزرار
        # conversation_timeout=300 # إضافة مهلة للمحادثة (اختياري)
    )
    dispatcher.add_handler(import_channel_conv_handler)
    logger.debug("DEBUG: Registered import_channel_conv_handler.")

    # --- إضافة محادثات الإدارة الأخرى (إضافة/حذف/عرض سؤال) --- 
    # يجب إضافة هذه المحادثات هنا إذا كانت موجودة في ملفات أخرى أو في نفس الملف
    # مثال:
    # add_question_conv_handler = ConversationHandler(...)
    # dispatcher.add_handler(add_question_conv_handler)
    # logger.debug("DEBUG: Registered add_question_conv_handler.")
    # delete_question_conv_handler = ConversationHandler(...)
    # dispatcher.add_handler(delete_question_conv_handler)
    # logger.debug("DEBUG: Registered delete_question_conv_handler.")
    # show_question_conv_handler = ConversationHandler(...)
    # dispatcher.add_handler(show_question_conv_handler)
    # logger.debug("DEBUG: Registered show_question_conv_handler.")
    logger.warning("DEBUG: Handlers for add/delete/show question conversations are NOT registered yet!")

    # 5. تسجيل معالج الأخطاء (يجب أن يكون من آخر المعالجات)
    dispatcher.add_error_handler(error_handler)
    logger.debug("DEBUG: Registered error_handler.")

    logger.info("All handlers registered.")

    # بدء البوت
    logger.info("Starting polling...")
    updater.start_polling()
    logger.info("Bot started polling successfully.")

    # تشغيل البوت حتى يتم الضغط على Ctrl-C
    updater.idle()
    logger.info("Bot polling stopped.")

if __name__ == '__main__':
    logger.debug("DEBUG: Script execution started (__name__ == '__main__').")
    main()
    logger.debug("DEBUG: Script execution finished.")

