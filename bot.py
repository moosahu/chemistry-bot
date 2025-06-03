#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
بوت اختبارات كيمياء تحصيلي
"""

import logging
import os
import sys
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# استيراد الوحدات الأخرى
try:
    # استيراد الثوابت من ملف config.py
    from config import (
        MAIN_MENU, QUIZ_MENU, INFO_MENU, STATS_MENU, END,
        REGISTRATION_NAME, REGISTRATION_EMAIL, REGISTRATION_PHONE, REGISTRATION_GRADE, REGISTRATION_CONFIRM,
        EDIT_USER_INFO_MENU, EDIT_USER_NAME, EDIT_USER_EMAIL, EDIT_USER_PHONE, EDIT_USER_GRADE,
        TELEGRAM_BOT_TOKEN, DATABASE_URL,
        initialize_db_manager, post_initialize_db_manager
    )
    
    # استيراد معالجات المحادثة من الوحدات المختلفة
    try:
        # محاولة استيراد معالجات التسجيل من المسار المباشر أولاً
        from registration import (
            registration_conv_handler,
            edit_info_conv_handler,
            start_command as registration_start_command
        )
    except ImportError:
        # محاولة استيراد معالجات التسجيل من المسار الكامل
        from handlers.registration import (
            registration_conv_handler,
            edit_info_conv_handler,
            start_command as registration_start_command
        )
        
    # استيراد معالجات القائمة الرئيسية
    try:
        from common import (
            start_command,
            main_menu_callback,
            main_menu_nav_handler
        )
    except ImportError:
        from handlers.common import (
            start_command,
            main_menu_callback,
            main_menu_nav_handler
        )
    
    # استيراد معالجات الاختبارات
    try:
        from quiz import quiz_conv_handler
    except ImportError:
        from handlers.quiz import quiz_conv_handler
    
    # استيراد معالجات المعلومات
    try:
        from info import info_conv_handler
    except ImportError:
        from handlers.info import info_conv_handler
    
    # استيراد معالجات الإحصائيات
    try:
        from stats import stats_conv_handler
    except ImportError:
        from handlers.stats import stats_conv_handler
    
    # استيراد معالجات أدوات الإدارة
    try:
        from admin_new_tools import (
            admin_show_tools_menu_callback,
            admin_back_to_start_callback,
            admin_edit_specific_message_callback,
            admin_edit_other_messages_menu_callback,
            admin_broadcast_start_callback,
            admin_broadcast_confirm_callback,
            admin_broadcast_cancel_callback,
            received_new_message_text,
            received_broadcast_text,
            cancel_edit_command,
            cancel_broadcast_command,
            EDIT_MESSAGE_TEXT,
            BROADCAST_MESSAGE_TEXT,
            BROADCAST_CONFIRM
        )
    except ImportError:
        from handlers.admin_tools.admin_new_tools import (
            admin_show_tools_menu_callback,
            admin_back_to_start_callback,
            admin_edit_specific_message_callback,
            admin_edit_other_messages_menu_callback,
            admin_broadcast_start_callback,
            admin_broadcast_confirm_callback,
            admin_broadcast_cancel_callback,
            received_new_message_text,
            received_broadcast_text,
            cancel_edit_command,
            cancel_broadcast_command,
            EDIT_MESSAGE_TEXT,
            BROADCAST_MESSAGE_TEXT,
            BROADCAST_CONFIRM
        )
    
except ImportError as e:
    logger.error(f"خطأ في استيراد الوحدات: {e}")
    sys.exit(1)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة الأخطاء أثناء تنفيذ البوت"""
    logger.error(f"حدث خطأ أثناء معالجة التحديث: {context.error}")
    
    # إرسال رسالة خطأ للمستخدم
    if update and update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ حدث خطأ أثناء معالجة طلبك. يرجى المحاولة مرة أخرى لاحقاً."
        )

def main() -> None:
    """النقطة الرئيسية لتشغيل البوت"""
    # إنشاء تطبيق البوت
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # تهيئة مدير قاعدة البيانات
    db_manager = initialize_db_manager(DATABASE_URL)
    application.bot_data["DB_MANAGER"] = db_manager
    
    # إجراءات ما بعد التهيئة
    post_initialize_db_manager(application.bot_data)
    
    # إضافة معالج الأخطاء
    application.add_error_handler(error_handler)
    
    # إضافة معالج التسجيل أولاً (مهم لضمان أولوية معالجة التسجيل)
    application.add_handler(registration_conv_handler)
    
    # إضافة معالج تعديل معلومات المستخدم
    application.add_handler(edit_info_conv_handler)
    
    # إضافة معالج أمر /start
    application.add_handler(CommandHandler("start", start_command))
    
    # إضافة معالج الاختبارات
    application.add_handler(quiz_conv_handler)
    
    # إضافة معالج المعلومات
    application.add_handler(info_conv_handler)
    
    # إضافة معالج الإحصائيات
    application.add_handler(stats_conv_handler)
    
    # إضافة معالج أدوات الإدارة
    admin_edit_message_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_edit_specific_message_callback, pattern=r"^admin_edit_specific_msg_"),
        ],
        states={
            EDIT_MESSAGE_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_new_message_text)],
        },
        fallbacks=[CommandHandler("cancel_edit", cancel_edit_command)],
        name="admin_edit_message_conversation",
        persistent=False
    )
    
    admin_broadcast_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_broadcast_start_callback, pattern=r"^admin_broadcast_start$"),
        ],
        states={
            BROADCAST_MESSAGE_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_broadcast_text)],
            BROADCAST_CONFIRM: [
                CallbackQueryHandler(admin_broadcast_confirm_callback, pattern=r"^admin_broadcast_confirm$"),
                CallbackQueryHandler(admin_broadcast_cancel_callback, pattern=r"^admin_broadcast_cancel$"),
            ],
        },
        fallbacks=[CommandHandler("cancel_broadcast", cancel_broadcast_command)],
        name="admin_broadcast_conversation",
        persistent=False
    )
    
    # إضافة معالجات أدوات الإدارة
    application.add_handler(admin_edit_message_conv_handler)
    application.add_handler(admin_broadcast_conv_handler)
    application.add_handler(CallbackQueryHandler(admin_show_tools_menu_callback, pattern=r"^admin_show_tools_menu$"))
    application.add_handler(CallbackQueryHandler(admin_back_to_start_callback, pattern=r"^admin_back_to_start$"))
    application.add_handler(CallbackQueryHandler(admin_edit_other_messages_menu_callback, pattern=r"^admin_edit_other_messages_menu$"))
    
    # إضافة معالج التنقل في القائمة الرئيسية
    application.add_handler(main_menu_nav_handler)
    
    # بدء تشغيل البوت
    application.run_polling()

if __name__ == '__main__':
    main()
