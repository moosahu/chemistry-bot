#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
أداة تصدير بيانات المستخدمين إلى ملف إكسل - خاصة بالمدير فقط
هذا الملف يحتوي على دالة export_users_command التي تتيح للمدير تصدير بيانات المستخدمين إلى ملف إكسل
"""

import os
import logging
import pandas as pd
from datetime import datetime
from sqlalchemy import text
from telegram import Update
from telegram.ext import CallbackContext

# إعداد التسجيل
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
        excel_path = await export_users_to_excel(admin_user_id=user_id)
        
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
        
        # استخدام دالة is_user_admin المخصصة في DatabaseManager
        is_admin = db_manager.is_user_admin(user_id)
        
        if is_admin:
            logger.info(f"تم التحقق من صلاحيات المدير للمستخدم {user_id}: صلاحيات مدير مؤكدة")
            return True
        
        logger.warning(f"تم التحقق من صلاحيات المدير للمستخدم {user_id}: ليس مديراً")
        return False
    
    except Exception as e:
        logger.error(f"خطأ أثناء التحقق من صلاحيات المدير للمستخدم {user_id}: {e}")
        return False

async def export_users_to_excel(output_dir=None, admin_user_id=None):
    """
    تصدير بيانات المستخدمين المسجلين إلى ملف إكسل
    
    المعلمات:
        output_dir (str): مسار المجلد لحفظ ملف الإكسل. إذا كان None، سيتم استخدام المجلد الحالي.
        admin_user_id (int): معرف المستخدم المدير الذي طلب التصدير. سيتم تضمينه في اسم الملف.
    
    العائد:
        str: المسار الكامل لملف الإكسل المُصدَّر
    """
    try:
        # إنشاء مجلد للتصدير إذا لم يكن موجوداً
        if output_dir is None:
            output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports")
        
        os.makedirs(output_dir, exist_ok=True)
        
        # الحصول على محرك قاعدة البيانات من مدير قاعدة البيانات
        conn = None
        try:
            from database.connection import connect_db
            conn = connect_db()
        except ImportError:
            logger.error("فشل استيراد وحدة الاتصال بقاعدة البيانات")
            return None
        
        if not conn:
            logger.error("فشل الاتصال بقاعدة البيانات. تأكد من صحة معلومات الاتصال.")
            return None
        
        # استعلام SQL لاستخراج بيانات المستخدمين المسجلين فقط
        query = """
        SELECT 
            user_id AS "معرف المستخدم",
            username AS "اسم المستخدم",
            first_name AS "الاسم الأول",
            last_name AS "الاسم الأخير",
            full_name AS "الاسم الكامل",
            email AS "البريد الإلكتروني",
            phone AS "رقم الجوال",
            grade AS "الصف الدراسي",
            is_registered AS "مسجل",
            is_admin AS "مدير",
            language_code AS "رمز اللغة",
            first_seen_timestamp AS "تاريخ أول ظهور",
            last_active_timestamp AS "تاريخ آخر نشاط",
            last_interaction_date AS "تاريخ آخر تفاعل"
        FROM 
            users
        WHERE 
            is_registered = TRUE
        ORDER BY 
            last_interaction_date DESC
        """
        
        # تنفيذ الاستعلام وتحويل النتائج إلى DataFrame
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query)
        result = cur.fetchall()
        df = pd.DataFrame([dict(row) for row in result])
        
        # معالجة الحقول الزمنية لإزالة معلومات المنطقة الزمنية
        datetime_columns = [
            "تاريخ أول ظهور", 
            "تاريخ آخر نشاط", 
            "تاريخ آخر تفاعل"
        ]
        
        for col in datetime_columns:
            if col in df.columns and not df[col].empty:
                # تحويل الحقول الزمنية إلى قيم بدون منطقة زمنية
                df[col] = df[col].dt.tz_localize(None)
        
        # إنشاء اسم الملف مع الطابع الزمني ومعرف المدير
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        admin_suffix = f"_by_admin_{admin_user_id}" if admin_user_id else ""
        excel_filename = f"users_data_{timestamp}{admin_suffix}.xlsx"
        excel_path = os.path.join(output_dir, excel_filename)
        
        # تصدير البيانات إلى ملف إكسل
        logger.info(f"جاري تصدير البيانات إلى ملف إكسل: {excel_path}")
        
        # إنشاء كاتب إكسل
        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            # كتابة البيانات
            df.to_excel(writer, sheet_name='بيانات المستخدمين', index=False)
            
            # الحصول على ورقة العمل لتنسيقها
            workbook = writer.book
            worksheet = writer.sheets['بيانات المستخدمين']
            
            # ضبط عرض الأعمدة تلقائياً
            for i, column in enumerate(df.columns):
                column_width = max(df[column].astype(str).map(len).max(), len(column)) + 2
                worksheet.column_dimensions[chr(65 + i)].width = column_width
        
        logger.info(f"تم تصدير بيانات المستخدمين بنجاح إلى: {excel_path}")
        return excel_path
    
    except Exception as e:
        logger.error(f"حدث خطأ أثناء تصدير بيانات المستخدمين: {e}")
        return None
