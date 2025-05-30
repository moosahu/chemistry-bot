#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
أداة تصدير بيانات المستخدمين إلى ملف إكسل - خاصة بالمدير فقط
هذا الملف يضيف أمر /export_users للبوت ليتمكن المدير من تصدير بيانات المستخدمين إلى ملف إكسل
"""

import os
import logging
from telegram import Update
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    Application
)

# استيراد أداة التصدير
from admin_tools.export_users_to_excel import export_users_to_excel

# تكوين التسجيل
logger = logging.getLogger(__name__)

async def export_users_command(update: Update, context: CallbackContext):
    """
    معالج أمر /export_users لتصدير بيانات المستخدمين إلى ملف إكسل
    هذا الأمر متاح للمدير فقط
    """
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    try:
        # التحقق من صلاحيات المدير
        is_admin = await check_admin_rights(user_id, context)
        
        if not is_admin:
            logger.warning(f"محاولة غير مصرح بها للوصول إلى أمر التصدير من قبل المستخدم {user_id}")
            await context.bot.send_message(
                chat_id=chat_id,
                text="⛔️ عذراً، هذا الأمر متاح للمدير فقط."
            )
            return
        
        # إرسال رسالة انتظار
        wait_message = await context.bot.send_message(
            chat_id=chat_id,
            text="⏳ جاري استخراج بيانات المستخدمين وتصديرها إلى ملف إكسل...\nقد تستغرق هذه العملية بضع ثوانٍ."
        )
        
        # تصدير بيانات المستخدمين إلى ملف إكسل
        excel_path = export_users_to_excel(admin_user_id=user_id)
        
        if not excel_path or not os.path.exists(excel_path):
            logger.error(f"فشل تصدير بيانات المستخدمين للمدير {user_id}")
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ حدث خطأ أثناء تصدير بيانات المستخدمين. يرجى المحاولة مرة أخرى لاحقاً."
            )
            return
        
        # إرسال ملف الإكسل
        logger.info(f"إرسال ملف تصدير بيانات المستخدمين للمدير {user_id}: {excel_path}")
        with open(excel_path, 'rb') as excel_file:
            await context.bot.send_document(
                chat_id=chat_id,
                document=excel_file,
                filename=os.path.basename(excel_path),
                caption="📊 إليك ملف إكسل يحتوي على بيانات جميع المستخدمين المسجلين في البوت."
            )
        
        # تحديث رسالة الانتظار
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=wait_message.message_id,
            text="✅ تم تصدير بيانات المستخدمين بنجاح وإرسال الملف."
        )
        
        logger.info(f"تم تصدير بيانات المستخدمين بنجاح للمدير {user_id}")
    
    except Exception as e:
        logger.error(f"خطأ أثناء معالجة أمر تصدير المستخدمين للمستخدم {user_id}: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ حدث خطأ غير متوقع أثناء تنفيذ الأمر. يرجى المحاولة مرة أخرى لاحقاً."
        )

async def check_admin_rights(user_id, context):
    """
    التحقق مما إذا كان المستخدم مديراً
    
    المعلمات:
        user_id (int): معرف المستخدم للتحقق
        context (CallbackContext): سياق المحادثة
    
    العائد:
        bool: True إذا كان المستخدم مديراً، False خلاف ذلك
    """
    try:
        # الحصول على مدير قاعدة البيانات من سياق البوت
        db_manager = context.application.bot_data.get('DB_MANAGER')
        
        if not db_manager:
            logger.error("لم يتم العثور على مدير قاعدة البيانات في سياق البوت")
            return False
        
        # استعلام للتحقق من صلاحيات المدير
        query = "SELECT is_admin FROM users WHERE user_id = :user_id"
        result = await db_manager.fetch_one(query, {'user_id': user_id})
        
        if result and result.get('is_admin'):
            logger.info(f"تم التحقق من صلاحيات المدير للمستخدم {user_id}: صلاحيات مدير مؤكدة")
            return True
        
        logger.warning(f"تم التحقق من صلاحيات المدير للمستخدم {user_id}: ليس مديراً")
        return False
    
    except Exception as e:
        logger.error(f"خطأ أثناء التحقق من صلاحيات المدير للمستخدم {user_id}: {e}")
        return False

def register_admin_handlers(application: Application):
    """
    تسجيل معالجات الأوامر الإدارية
    
    المعلمات:
        application (Application): تطبيق البوت
    """
    try:
        # تسجيل أمر تصدير بيانات المستخدمين
        export_handler = CommandHandler("export_users", export_users_command)
        application.add_handler(export_handler)
        
        logger.info("تم تسجيل معالجات الأوامر الإدارية بنجاح")
    except Exception as e:
        logger.error(f"خطأ أثناء تسجيل معالجات الأوامر الإدارية: {e}")
