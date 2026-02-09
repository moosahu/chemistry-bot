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
        result = await export_users_to_excel(db_manager, user_id)
        
        if result and isinstance(result, tuple):
            excel_path, stats = result
            
            # إرسال ملف الإكسل للمستخدم مع الإحصائيات
            caption = f"""تم استخراج بيانات المستخدمين بنجاح 📊

📈 الإحصائيات:
• إجمالي المستخدمين: {stats['total']}
• المستخدمون النشطون: {stats['active']}
• المستخدمون المحظورون: {stats['blocked']}

📁 الملف يحتوي على ورقتين:
• بيانات المستخدمين (مع حالة الحظر)
• الإحصائيات التفصيلية"""
            
            await update.message.reply_document(
                document=open(excel_path, 'rb'),
                filename=os.path.basename(excel_path),
                caption=caption
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
        
        # فحص وجود جدول blocked_users أولاً
        check_table_query = """
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'blocked_users'
        );
        """
        
        connection = db_manager.engine.connect()
        table_exists = connection.execute(text(check_table_query)).scalar()
        
        # الاستعلام عن بيانات المستخدمين مع معلومات الحظر
        if table_exists:
            logger.info("جدول blocked_users موجود، سيتم تضمين معلومات الحظر")
            query = """
            SELECT 
                u.user_id as "معرف المستخدم",
                u.username as "اسم المستخدم",
                u.first_name as "الاسم الأول",
                u.last_name as "الاسم الأخير",
                u.full_name as "الاسم الكامل",
                u.email as "البريد الإلكتروني",
                u.phone as "رقم الجوال",
                u.grade as "الصف الدراسي",
                u.is_registered as "مسجل",
                u.is_admin as "مدير",
                u.language_code as "رمز اللغة",
                u.first_seen_timestamp as "تاريخ أول ظهور",
                u.last_active_timestamp as "تاريخ آخر نشاط",
                u.last_interaction_date as "تاريخ آخر تفاعل",
                CASE 
                    WHEN b.user_id IS NOT NULL AND b.is_active = true THEN 'محظور'
                    ELSE 'نشط'
                END as "حالة الحظر",
                COALESCE(b.reason, '-') as "سبب الحظر",
                CASE 
                    WHEN b.blocked_at IS NOT NULL THEN b.blocked_at::text
                    ELSE '-'
                END as "تاريخ الحظر"
            FROM users u
            LEFT JOIN blocked_users b ON u.user_id = b.user_id AND b.is_active = true
            WHERE u.is_registered = TRUE
            ORDER BY u.user_id
            """
        else:
            logger.warning("جدول blocked_users غير موجود، سيتم عرض جميع المستخدمين كنشطين")
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
                last_interaction_date as "تاريخ آخر تفاعل",
                'نشط' as "حالة الحظر",
                '-' as "سبب الحظر",
                '-' as "تاريخ الحظر"
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
        
        # تحويل القيم المنطقية إلى نصوص عربية (نعم/لا)
        boolean_columns = ["مسجل", "مدير"]
        for col in boolean_columns:
            if col in df.columns:
                df[col] = df[col].map({True: "نعم", False: "لا"})
        
        # معالجة الحقول الزمنية وتحويلها إلى تنسيق نصي واضح
        datetime_columns = [
            "تاريخ أول ظهور", 
            "تاريخ آخر نشاط", 
            "تاريخ آخر تفاعل"
        ]
        
        for col in datetime_columns:
            if col in df.columns:
                # تحويل الحقول الزمنية إلى قيم بدون منطقة زمنية ثم إلى نص بتنسيق واضح
                df[col] = pd.to_datetime(df[col]).dt.tz_localize(None)
                df[col] = df[col].dt.strftime("%Y-%m-%d %H:%M:%S")
        
        # إنشاء اسم الملف مع الطابع الزمني ومعرف المدير
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        admin_suffix = f"_by_admin_{admin_user_id}"
        excel_filename = f"users_data_{timestamp}{admin_suffix}.xlsx"
        excel_path = os.path.join(output_dir, excel_filename)
        
        # تصدير البيانات إلى ملف إكسل
        logger.info(f"جاري تصدير بيانات المستخدمين إلى ملف إكسل: {excel_path}")
        
        # حساب الإحصائيات
        total_users = len(df)
        blocked_users = len(df[df["حالة الحظر"] == "محظور"]) if "حالة الحظر" in df.columns else 0
        active_users = total_users - blocked_users
        
        # إنشاء DataFrame للإحصائيات
        stats_data = {
            "الإحصائية": [
                "إجمالي المستخدمين المسجلين",
                "المستخدمون النشطون", 
                "المستخدمون المحظورون",
                "تاريخ التصدير",
                "المدير المصدر"
            ],
            "القيمة": [
                total_users,
                active_users,
                blocked_users,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                admin_user_id
            ]
        }
        stats_df = pd.DataFrame(stats_data)
        
        # إنشاء كاتب إكسل
        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            # كتابة البيانات الرئيسية
            df.to_excel(writer, sheet_name='بيانات المستخدمين', index=False)
            
            # كتابة الإحصائيات
            stats_df.to_excel(writer, sheet_name='الإحصائيات', index=False)
            
            # الحصول على ورقة العمل لتنسيقها
            workbook = writer.book
            
            # تنسيق ورقة البيانات الرئيسية
            worksheet = writer.sheets['بيانات المستخدمين']
            for i, column in enumerate(df.columns):
                column_width = max(df[column].astype(str).map(len).max(), len(column)) + 2
                worksheet.column_dimensions[chr(65 + i)].width = min(column_width, 50)  # حد أقصى 50 حرف
            
            # تنسيق ورقة الإحصائيات
            stats_worksheet = writer.sheets['الإحصائيات']
            stats_worksheet.column_dimensions['A'].width = 30
            stats_worksheet.column_dimensions['B'].width = 20
        
        logger.info(f"تم تصدير بيانات المستخدمين بنجاح إلى: {excel_path}")
        
        # إرجاع مسار الملف والإحصائيات
        stats = {
            'total': total_users,
            'active': active_users,
            'blocked': blocked_users
        }
        return excel_path, stats
    
    except Exception as e:
        logger.error(f"حدث خطأ أثناء تصدير بيانات المستخدمين إلى ملف إكسل: {e}")
        return None
