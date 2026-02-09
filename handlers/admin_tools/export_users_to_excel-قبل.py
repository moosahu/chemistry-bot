#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
أداة تصدير بيانات المستخدمين إلى ملف إكسل مع حالة الحظر - خاصة بالمدير فقط
تقوم هذه الأداة باستخراج جميع بيانات المستخدمين المسجلين من قاعدة البيانات وتصديرها إلى ملف إكسل
مع إضافة أعمدة حالة الحظر وسبب الحظر وتاريخ الحظر
"""

import logging
import os
import sys
import pandas as pd
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

# إضافة المسار الرئيسي للمشروع إلى مسارات البحث
sys.path.append('/opt/render/project/src')

# تكوين التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_database_url():
    """الحصول على رابط قاعدة البيانات من المتغيرات البيئية"""
    database_url_env = os.environ.get("DATABASE_URL")
    if database_url_env:
        if database_url_env.startswith("postgres://"):
            database_url_env = database_url_env.replace("postgres://", "postgresql://", 1)
        _url_prefix_for_log = database_url_env.split("@")[0]
        logger.info(f"استخدام DATABASE_URL من البيئة: {_url_prefix_for_log}@...")
        return database_url_env

    # الرجوع إلى المكونات الفردية إذا لم يتم تعيين DATABASE_URL
    db_host = os.environ.get("DB_HOST", "dpg-d09mk5p5pdvs73dv4qeg-a.oregon-postgres.render.com")
    db_name = os.environ.get("DB_NAME", "chemistry_db")
    db_user = os.environ.get("DB_USER", "chemistry_db_user")
    db_password = os.environ.get("DB_PASSWORD", "2ewIvDpOHiKe8pFVVz15pba6FVDTKaB1")
    
    constructed_url = f"postgresql://{db_user}:{db_password}@{db_host}/{db_name}"
    _constructed_url_prefix_for_log = constructed_url.split("@")[0]
    logger.info(f"تم إنشاء رابط PostgreSQL من المتغيرات البيئية الفردية: {_constructed_url_prefix_for_log}@...")
    return constructed_url

def get_engine():
    """إنشاء محرك SQLAlchemy بناءً على رابط قاعدة البيانات"""
    db_url = get_database_url()
    
    try:
        engine = create_engine(db_url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        logger.info(f"تم إنشاء محرك SQLAlchemy والاتصال بنجاح بـ: {engine.url.drivername}")
        return engine
    except Exception as e:
        # إخفاء كلمة المرور في السجل إذا كانت موجودة في الرابط
        safe_url = str(db_url)
        if "@" in safe_url and ":" in safe_url.split("@")[0]:
            parts = safe_url.split("://")
            if len(parts) > 1:
                auth_part = parts[1].split("@")[0]
                safe_url = safe_url.replace(auth_part, f"{auth_part.split(':')[0]}:********")

        logger.error(f"خطأ في إنشاء محرك SQLAlchemy للرابط \'{safe_url}\': {e}")
        return None

def export_users_to_excel(admin_user_id=None):
    """
    تصدير بيانات المستخدمين إلى ملف إكسل مع حالة الحظر
    
    المعلمات:
        admin_user_id (int, اختياري): معرف المستخدم المدير الذي طلب التصدير
    
    العائد:
        str: مسار ملف الإكسل المُصدَّر
    """
    try:
        # الحصول على محرك قاعدة البيانات
        engine = get_engine()
        if not engine:
            logger.error("فشل الاتصال بقاعدة البيانات")
            return None
        
        # التحقق من وجود جدول blocked_users أولاً
        table_check_query = """
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'blocked_users'
        )
        """
        
        # فحص وجود الجدول
        table_exists = False
        try:
            with engine.connect() as conn:
                result = conn.execute(text(table_check_query))
                table_exists = result.scalar()
                logger.info(f"فحص جدول blocked_users: {'موجود' if table_exists else 'غير موجود'}")
        except Exception as e:
            logger.warning(f"فشل فحص وجود جدول blocked_users: {e}")
            table_exists = False
        
        # استعلام مع أو بدون جدول الحظر
        if table_exists:
            logger.info("جدول blocked_users موجود - سيتم تضمين معلومات الحظر الحقيقية")
            query = """
            SELECT 
                u.user_id, 
                u.username, 
                u.first_name, 
                u.last_name, 
                u.full_name,
                u.email, 
                u.phone, 
                u.grade, 
                u.is_registered,
                u.is_admin,
                u.language_code,
                u.first_seen_timestamp,
                u.last_active_timestamp,
                u.last_interaction_date,
                CASE 
                    WHEN b.user_id IS NOT NULL AND b.is_active = TRUE THEN 'محظور'
                    ELSE 'نشط'
                END as blocked_status,
                COALESCE(b.reason, '-') as block_reason,
                CASE 
                    WHEN b.blocked_at IS NOT NULL THEN b.blocked_at
                    ELSE NULL
                END as blocked_date
            FROM 
                users u
            LEFT JOIN 
                blocked_users b ON u.user_id = b.user_id AND b.is_active = TRUE
            WHERE 
                u.is_registered = TRUE
            ORDER BY 
                u.last_interaction_date DESC
            """
        else:
            logger.warning("جدول blocked_users غير موجود - سيتم إضافة أعمدة حظر افتراضية")
            query = """
            SELECT 
                u.user_id, 
                u.username, 
                u.first_name, 
                u.last_name, 
                u.full_name,
                u.email, 
                u.phone, 
                u.grade, 
                u.is_registered,
                u.is_admin,
                u.language_code,
                u.first_seen_timestamp,
                u.last_active_timestamp,
                u.last_interaction_date,
                'نشط' as blocked_status,
                '-' as block_reason,
                NULL as blocked_date
            FROM 
                users u
            WHERE 
                u.is_registered = TRUE
            ORDER BY 
                u.last_interaction_date DESC
            """
        
        # تنفيذ الاستعلام وتحويل النتائج إلى DataFrame
        logger.info("جاري استخراج بيانات المستخدمين من قاعدة البيانات...")
        
        with engine.connect() as conn:
            result = conn.execute(text(query))
            columns = result.keys()
            data = result.fetchall()
            
        # تحويل إلى DataFrame
        df = pd.DataFrame(data, columns=columns)
        
        # تحقق من وجود بيانات
        if df.empty:
            logger.warning("لا توجد بيانات مستخدمين مسجلين في قاعدة البيانات")
            return None
        
        logger.info(f"تم استخراج {len(df)} مستخدم من قاعدة البيانات")
        
        # إعادة تسمية الأعمدة بالعربية لتحسين قراءة ملف الإكسل
        column_mapping = {
            'user_id': 'معرف المستخدم',
            'username': 'اسم المستخدم',
            'first_name': 'الاسم الأول',
            'last_name': 'الاسم الأخير',
            'full_name': 'الاسم الكامل',
            'email': 'البريد الإلكتروني',
            'phone': 'رقم الجوال',
            'grade': 'الصف الدراسي',
            'is_registered': 'مسجل',
            'is_admin': 'مدير',
            'language_code': 'رمز اللغة',
            'first_seen_timestamp': 'تاريخ أول ظهور',
            'last_active_timestamp': 'تاريخ آخر نشاط',
            'last_interaction_date': 'تاريخ آخر تفاعل',
            'blocked_status': 'حالة الحظر',
            'block_reason': 'سبب الحظر',
            'blocked_date': 'تاريخ الحظر'
        }
        df = df.rename(columns=column_mapping)
        
        # تنسيق قيم البوليان لتكون أكثر وضوحاً
        df['مسجل'] = df['مسجل'].map({True: 'نعم', False: 'لا'})
        df['مدير'] = df['مدير'].map({True: 'نعم', False: 'لا'})
        
        # تنسيق أعمدة الحظر - استبدال القيم الفارغة
        if 'سبب الحظر' in df.columns:
            df['سبب الحظر'] = df['سبب الحظر'].fillna('-')
        if 'تاريخ الحظر' in df.columns:
            df['تاريخ الحظر'] = df['تاريخ الحظر'].fillna('-')
        
        # إحصائيات سريعة
        total_users = len(df)
        blocked_users = len(df[df['حالة الحظر'] == 'محظور']) if 'حالة الحظر' in df.columns else 0
        active_users = total_users - blocked_users
        
        logger.info(f"إحصائيات التصدير: إجمالي {total_users}, نشط {active_users}, محظور {blocked_users}")
        
        # إنشاء مجلد للتصدير إذا لم يكن موجوداً
        export_dir = '/tmp/admin_exports'
        os.makedirs(export_dir, exist_ok=True)
        
        # إنشاء اسم ملف فريد باستخدام الطابع الزمني
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        admin_suffix = f"_by_admin_{admin_user_id}" if admin_user_id else ""
        excel_filename = f"users_with_blocked_status_{timestamp}{admin_suffix}.xlsx"
        excel_path = os.path.join(export_dir, excel_filename)
        
        # تصدير DataFrame إلى ملف إكسل
        logger.info(f"جاري تصدير البيانات إلى ملف إكسل: {excel_path}")
        
        # إنشاء كاتب إكسل مع ورقتين
        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            # كتابة البيانات إلى ورقة العمل الأولى
            df.to_excel(writer, sheet_name='بيانات المستخدمين', index=False)
            
            # إنشاء ورقة إحصائيات
            stats_data = {
                'الإحصائية': [
                    'إجمالي المستخدمين',
                    'المستخدمون النشطون', 
                    'المستخدمون المحظورون',
                    'تاريخ التصدير',
                    'المدير المصدر'
                ],
                'القيمة': [
                    total_users,
                    active_users,
                    blocked_users,
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    admin_user_id or 'غير محدد'
                ]
            }
            stats_df = pd.DataFrame(stats_data)
            stats_df.to_excel(writer, sheet_name='الإحصائيات', index=False)
            
            # الحصول على ورقة العمل لتطبيق التنسيق
            worksheet = writer.sheets['بيانات المستخدمين']
            
            # تعيين عرض الأعمدة بناءً على محتوى الخلايا
            for i, column in enumerate(df.columns):
                max_length = max(
                    df[column].astype(str).map(len).max(),  # أطول قيمة في العمود
                    len(str(column))  # طول اسم العمود
                ) + 2  # إضافة هامش
                
                # تحديد الحد الأقصى لعرض العمود
                max_length = min(max_length, 50)
                
                # تحويل من وحدات البكسل إلى وحدات العرض في إكسل
                col_letter = chr(65 + i) if i < 26 else chr(65 + i // 26 - 1) + chr(65 + i % 26)
                worksheet.column_dimensions[col_letter].width = max_length
        
        logger.info(f"تم تصدير بيانات المستخدمين بنجاح إلى: {excel_path}")
        logger.info(f"الملف يحتوي على {len(df.columns)} عمود و {len(df)} صف")
        logger.info(f"الأعمدة: {list(df.columns)}")
        
        return excel_path
    
    except SQLAlchemyError as e:
        logger.error(f"خطأ في قاعدة البيانات أثناء تصدير بيانات المستخدمين: {e}")
        return None
    except Exception as e:
        logger.error(f"خطأ غير متوقع أثناء تصدير بيانات المستخدمين: {e}")
        return None

def main():
    """الدالة الرئيسية للتشغيل المباشر من سطر الأوامر"""
    try:
        # تصدير بيانات المستخدمين إلى ملف إكسل
        excel_path = export_users_to_excel()
        
        if excel_path:
            print(f"تم تصدير بيانات المستخدمين بنجاح إلى: {excel_path}")
        else:
            print("فشل تصدير بيانات المستخدمين")
    except Exception as e:
        print(f"حدث خطأ أثناء تنفيذ البرنامج: {e}")

if __name__ == "__main__":
    main()

