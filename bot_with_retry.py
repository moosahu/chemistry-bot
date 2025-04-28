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
ADMIN_USER_ID = 6448526509 # استبدل هذا بمعرف المستخدم الرقمي الخاص بك (مثال: 123456789)
# توكن البوت
TOKEN = "8167394360:AAG-b3v-VDmxLtWVQCuBkc694Mt3ZCs18IY" # !!! استبدل هذا بتوكن البوت الخاص بك !!!

# تكوين التسجيل
log_file_path = os.path.join(os.path.dirname(__file__), 'bot_log.txt')
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO, # تغيير المستوى إلى DEBUG للحصول على تفاصيل أكثر
    handlers=[
        # logging.FileHandler(log_file_path, encoding='utf-8'), # تعطيل التسجيل في ملف مؤقتاً لتسهيل القراءة من Heroku logs
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


# حالات المحادثة لإضافة سؤال وحذف/عرض سؤال
(ADD_QUESTION_TEXT, ADD_OPTIONS, ADD_CORRECT_ANSWER, ADD_EXPLANATION, ADD_CHAPTER, ADD_LESSON, 
 ADD_QUESTION_IMAGE_PROMPT, WAITING_QUESTION_IMAGE, DELETE_CONFIRM, SHOW_ID, IMPORT_CHANNEL_PROMPT) = range(11)

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

# --- استيراد الأسئلة من قناة تليجرام ---
def import_channel_start(update: Update, context: CallbackContext) -> int:
    """بدء عملية استيراد الأسئلة من قناة تليجرام."""
    user_id = update.effective_user.id
    logger.info(f"Admin {user_id}: Starting channel import conversation")
    
    if not is_admin(user_id):
        update.callback_query.answer("عذراً، هذا القسم متاح للمسؤول فقط.", show_alert=True)
        return ConversationHandler.END
    
    context.user_data['conversation_state'] = 'import_channel'
    update.callback_query.edit_message_text(
        "📥 استيراد أسئلة من قناة تليجرام\n\n"
        "الرجاء إرسال معرف القناة أو رابطها (مثال: @channel_name أو https://t.me/channel_name)\n\n"
        "ملاحظة: يجب أن يكون البوت عضواً في القناة ليتمكن من قراءة الرسائل."
    )
    return IMPORT_CHANNEL_PROMPT

def process_channel_import(update: Update, context: CallbackContext) -> int:
    """معالجة معرف القناة واستيراد الأسئلة منها."""
    user_id = update.effective_user.id
    channel_id = update.message.text.strip()
    logger.info(f"Admin {user_id}: Processing channel import from {channel_id}")
    
    # تنظيف معرف القناة
    if channel_id.startswith('https://t.me/'):
        channel_id = '@' + channel_id.split('/')[-1]
    elif not channel_id.startswith('@'):
        channel_id = '@' + channel_id
    
    # إرسال رسالة انتظار
    status_message = update.message.reply_text(
        f"جاري محاولة الوصول إلى القناة {channel_id}...\n"
        "قد تستغرق هذه العملية بعض الوقت حسب عدد الرسائل في القناة."
    )
    
    try:
        # محاولة الوصول إلى القناة
        context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
        
        # هنا نقوم بمحاولة الحصول على آخر 100 رسالة من القناة
        # ملاحظة: هذا يتطلب أن يكون البوت عضواً في القناة
        imported_count = 0
        failed_count = 0
        
        try:
            # محاولة استخدام getHistory API (قد لا تكون متاحة في python-telegram-bot 13.15)
            # لذلك نستخدم طريقة بديلة للحصول على الرسائل
            
            # إرسال رسالة إلى القناة للتأكد من الوصول (سيتم حذفها لاحقاً)
            test_msg = context.bot.send_message(chat_id=channel_id, text="اختبار الوصول")
            context.bot.delete_message(chat_id=channel_id, message_id=test_msg.message_id)
            
            status_message.edit_text(
                f"تم الوصول إلى القناة {channel_id} بنجاح!\n"
                "جاري تحليل الرسائل واستخراج الأسئلة...\n\n"
                "ملاحظة: سيتم استيراد الأسئلة التي تتبع التنسيق التالي:\n"
                "- نص السؤال\n"
                "- أربعة خيارات (أ، ب، ج، د) أو (1، 2، 3، 4)\n"
                "- الإجابة الصحيحة مشار إليها بوضوح"
            )
            
            # في هذه المرحلة، نحتاج إلى تنفيذ عملية استيراد الأسئلة من القناة
            # هذا يتطلب تحليل محتوى الرسائل واستخراج الأسئلة والخيارات والإجابات
            
            # نظراً لقيود API تليجرام، سنقوم بإرسال رسالة توضح للمستخدم كيفية تنسيق الأسئلة
            # ليتم استيرادها بشكل صحيح في المستقبل
            
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
            
            # في هذه المرحلة، سنقوم بإضافة وظيفة لاستيراد الأسئلة من القناة
            # ولكن نظراً لتعقيد هذه العملية، سنقوم بتنفيذها في تحديث مستقبلي
            
            update.message.reply_text(
                "⚠️ ميزة استيراد الأسئلة من القناة قيد التطوير حالياً.\n\n"
                "في الإصدار الحالي، يمكنك إضافة الأسئلة يدوياً باستخدام زر 'إضافة سؤال جديد'.\n\n"
                "سيتم إطلاق ميزة الاستيراد التلقائي في تحديث قريب. شكراً لتفهمك!"
            )
            
        except Unauthorized:
            update.message.reply_text(
                f"❌ خطأ: البوت ليس عضواً في القناة {channel_id}.\n\n"
                "يجب إضافة البوت كعضو في القناة أولاً ليتمكن من قراءة الرسائل."
            )
        except Exception as e:
            logger.error(f"Error importing from channel: {e}", exc_info=True)
            update.message.reply_text(
                f"❌ حدث خطأ أثناء محاولة استيراد الأسئلة: {str(e)}\n\n"
                "يرجى التأكد من صحة معرف القناة وأن البوت عضو فيها."
            )
    
    except Exception as e:
        logger.error(f"Error in channel import: {e}", exc_info=True)
        update.message.reply_text(f"❌ حدث خطأ: {str(e)}")
    
    # إنهاء المحادثة
    if 'conversation_state' in context.user_data:
        del context.user_data['conversation_state']
    
    # إعادة عرض قائمة الإدارة
    keyboard = [[InlineKeyboardButton("🔙 العودة لقائمة الإدارة", callback_data='menu_admin')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("العملية انتهت. يمكنك العودة إلى قائمة الإدارة.", reply_markup=reply_markup)
    
    return ConversationHandler.END

def cancel_import_channel(update: Update, context: CallbackContext) -> int:
    """إلغاء عملية استيراد الأسئلة من القناة."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} cancelled channel import.")
    update.message.reply_text('تم إلغاء عملية استيراد الأسئلة من القناة.')
    if 'conversation_state' in context.user_data:
        del context.user_data['conversation_state']
    return ConversationHandler.END

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
    # إنشاء Updater وتمرير توكن البوت إليه.
    updater = Updater(TOKEN, use_context=True)

    # الحصول على المرسل لتسجيل المعالجات
    dispatcher = updater.dispatcher

    # --- محادثة استيراد الأسئلة من قناة ---
    import_channel_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(import_channel_start, pattern='^admin_import_channel$')],
        states={
            IMPORT_CHANNEL_PROMPT: [MessageHandler(Filters.text & ~Filters.command, process_channel_import)],
        },
        fallbacks=[CommandHandler('cancel', cancel_import_channel)],
        per_message=False,
    )
    dispatcher.add_handler(import_channel_conv_handler)

    # تسجيل معالج الأخطاء
    dispatcher.add_error_handler(error_handler)

    # بدء البوت
    updater.start_polling()
    logger.info("Bot started polling...")

    # تشغيل البوت حتى يتم الضغط على Ctrl-C
    updater.idle()
    logger.info("Bot stopped.")

if __name__ == '__main__':
    main()
