#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ملف معالجة أوامر المدير
يحتوي على أوامر خاصة بالمدير فقط مثل تصدير بيانات المستخدمين
"""

import os
import logging
import pandas as pd
import psycopg2
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from sqlalchemy import text

# إعداد التسجيل
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def export_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    أمر تصدير بيانات المستخدمين إلى ملف إكسل
    متاح للمدير فقط
    
    المعلمات:
        update (Update): تحديث تيليجرام
        context (ContextTypes.DEFAULT_TYPE): سياق المحادثة
    """
    user_id = update.effective_user.id
    
    # التحقق من صلاحيات المدير
    is_admin = await check_admin_rights(user_id, context)
    
    if not is_admin:
        logger.warning(f"محاولة غير مصرح بها للوصول إلى أمر التصدير من قبل المستخدم {user_id}")
        await update.message.reply_text("عذراً، هذا الأمر متاح للمدير فقط.")
        return
    
    # إرسال رسالة انتظار
    await update.message.reply_text("جاري استخراج بيانات المستخدمين...")
    
    try:
        # الحصول على مدير قاعدة البيانات من سياق البوت
        db_manager = context.bot_data.get("DB_MANAGER")
        
        if not db_manager:
            logger.error(f"لم يتم العثور على مدير قاعدة البيانات في سياق البوت للمستخدم {user_id}")
            await update.message.reply_text("حدث خطأ أثناء الاتصال بقاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً.")
            return
        
        # تصدير بيانات المستخدمين إلى ملف إكسل
        excel_path = await export_users_to_excel(db_manager, user_id)
        
        if excel_path:
            # إرسال ملف الإكسل للمستخدم
            await update.message.reply_document(
                document=open(excel_path, 'rb'),
                filename=os.path.basename(excel_path),
                caption="تم استخراج بيانات المستخدمين بنجاح."
            )
            logger.info(f"تم تصدير بيانات المستخدمين بنجاح للمدير {user_id}")
        else:
            await update.message.reply_text("حدث خطأ أثناء تصدير بيانات المستخدمين. يرجى المحاولة مرة أخرى لاحقاً.")
            logger.error(f"فشل تصدير بيانات المستخدمين للمدير {user_id}")
    
    except Exception as e:
        logger.error(f"حدث خطأ أثناء تصدير بيانات المستخدمين: {e}")
        await update.message.reply_text("حدث خطأ أثناء تصدير بيانات المستخدمين. يرجى المحاولة مرة أخرى لاحقاً.")

async def check_admin_rights(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    التحقق من صلاحيات المدير للمستخدم
    
    المعلمات:
        user_id (int): معرف المستخدم
        context (ContextTypes.DEFAULT_TYPE): سياق المحادثة
    
    العائد:
        bool: True إذا كان المستخدم مديراً، False خلاف ذلك
    """
    try:
        # الحصول على مدير قاعدة البيانات من سياق البوت
        db_manager = context.bot_data.get("DB_MANAGER")
        
        if not db_manager:
            logger.error(f"لم يتم العثور على مدير قاعدة البيانات في سياق البوت للمستخدم {user_id}")
            return False
        
        # استخدام دالة is_user_admin المخصصة في DatabaseManager
        is_admin = db_manager.is_user_admin(user_id)
        
        logger.info(f"تم التحقق من صلاحيات المدير للمستخدم {user_id}: {'صلاحيات مدير مؤكدة' if is_admin else 'ليس مديراً'}")
        return is_admin
    
    except Exception as e:
        logger.error(f"خطأ أثناء التحقق من صلاحيات المدير للمستخدم {user_id}: {e}")
        return False

async def export_users_to_excel(db_manager, admin_user_id: int) -> str:
    """
    تصدير بيانات المستخدمين إلى ملف إكسل
    
    المعلمات:
        db_manager: مدير قاعدة البيانات
        admin_user_id (int): معرف المستخدم المدير
    
    العائد:
        str: مسار ملف الإكسل إذا نجحت العملية، None خلاف ذلك
    """
    try:
        # إنشاء مجلد للتصدير إذا لم يكن موجوداً
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(script_dir, "exports")
        os.makedirs(output_dir, exist_ok=True)
        
        # الاستعلام عن بيانات المستخدمين المسجلين فقط - تم تعديله ليتوافق مع هيكل الجدول الفعلي
        query = """
        SELECT 
            user_id as "معرف المستخدم",
            username as "اسم المستخدم",
            first_name as "الاسم الأول",
            last_name as "الاسم الأخير",
            full_name as "الاسم الكامل",
            email as "البريد الإلكتروني",
            phone as "رقم الجوال",
            grade as "الصف الدراسي",
            is_registered as "مسجل",
            is_admin as "مدير",
            language_code as "رمز اللغة",
            first_seen_timestamp as "تاريخ أول ظهور",
            last_active_timestamp as "تاريخ آخر نشاط",
            last_interaction_date as "تاريخ آخر تفاعل"
        FROM users
        WHERE is_registered = TRUE
        ORDER BY user_id
        """
        
        # تنفيذ الاستعلام
        connection = db_manager.engine.connect()
        result = connection.execute(text(query))
        
        # تحويل النتائج إلى DataFrame
        df = pd.DataFrame(result.fetchall())
        
        # إغلاق الاتصال
        connection.close()
        
        if df.empty:
            logger.warning("لا توجد بيانات مستخدمين مسجلين لتصديرها")
            return None
        
        # معالجة الحقول الزمنية لإزالة معلومات المنطقة الزمنية
        datetime_columns = [
            "تاريخ أول ظهور", 
            "تاريخ آخر نشاط", 
            "تاريخ آخر تفاعل"
        ]
        
        for col in datetime_columns:
            if col in df.columns:
                # تحويل الحقول الزمنية إلى قيم بدون منطقة زمنية
                df[col] = pd.to_datetime(df[col]).dt.tz_localize(None)
        
        # إنشاء اسم الملف مع الطابع الزمني ومعرف المدير
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        admin_suffix = f"_by_admin_{admin_user_id}"
        excel_filename = f"users_data_{timestamp}{admin_suffix}.xlsx"
        excel_path = os.path.join(output_dir, excel_filename)
        
        # تصدير البيانات إلى ملف إكسل
        logger.info(f"جاري تصدير بيانات المستخدمين إلى ملف إكسل: {excel_path}")
        
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
        logger.error(f"حدث خطأ أثناء تصدير بيانات المستخدمين إلى ملف إكسل: {e}")
        return None
