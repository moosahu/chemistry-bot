#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
أداة تصدير بيانات المستخدمين إلى ملف إكسل - خاصة بالمدير فقط
تقوم هذه الأداة باستخراج جميع بيانات المستخدمين المسجلين من قاعدة البيانات وتصديرها إلى ملف إكسل
"""

import os
import sys
import logging
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
    تصدير بيانات المستخدمين إلى ملف إكسل
    
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
        
        # استعلام لاستخراج بيانات المستخدمين المسجلين
        query = """
        SELECT 
            user_id, 
            username, 
            first_name, 
            last_name, 
            full_name,
            email, 
            phone, 
            grade, 
            is_registered,
            is_admin,
            language_code,
            first_seen_timestamp,
            last_active_timestamp,
            last_interaction_date
        FROM 
            users
        WHERE 
            is_registered = TRUE
        ORDER BY 
            last_interaction_date DESC
        """
        
        # تنفيذ الاستعلام وتحويل النتائج إلى DataFrame
        logger.info("جاري استخراج بيانات المستخدمين من قاعدة البيانات...")
        df = pd.read_sql(query, engine)
        
        # تحقق من وجود بيانات
        if df.empty:
            logger.warning("لا توجد بيانات مستخدمين مسجلين في قاعدة البيانات")
            return None
        
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
            'last_interaction_date': 'تاريخ آخر تفاعل'
        }
        df = df.rename(columns=column_mapping)
        
        # تنسيق قيم البوليان لتكون أكثر وضوحاً
        df['مسجل'] = df['مسجل'].map({True: 'نعم', False: 'لا'})
        df['مدير'] = df['مدير'].map({True: 'نعم', False: 'لا'})
        
        # إنشاء مجلد للتصدير إذا لم يكن موجوداً
        export_dir = '/home/ubuntu/upload/admin_tools/exports'
        os.makedirs(export_dir, exist_ok=True)
        
        # إنشاء اسم ملف فريد باستخدام الطابع الزمني
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        admin_suffix = f"_by_admin_{admin_user_id}" if admin_user_id else ""
        excel_filename = f"users_data_{timestamp}{admin_suffix}.xlsx"
        excel_path = os.path.join(export_dir, excel_filename)
        
        # تصدير DataFrame إلى ملف إكسل
        logger.info(f"جاري تصدير البيانات إلى ملف إكسل: {excel_path}")
        
        # إنشاء كاتب إكسل
        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            # كتابة البيانات إلى ورقة العمل
            df.to_excel(writer, sheet_name='بيانات المستخدمين', index=False)
            
            # الحصول على ورقة العمل لتطبيق التنسيق
            worksheet = writer.sheets['بيانات المستخدمين']
            
            # تعيين عرض الأعمدة بناءً على محتوى الخلايا
            for i, column in enumerate(df.columns):
                max_length = max(
                    df[column].astype(str).map(len).max(),  # أطول قيمة في العمود
                    len(str(column))  # طول اسم العمود
                ) + 2  # إضافة هامش
                
                # تحويل من وحدات البكسل إلى وحدات العرض في إكسل
                worksheet.column_dimensions[chr(65 + i)].width = max_length
        
        logger.info(f"تم تصدير بيانات المستخدمين بنجاح إلى: {excel_path}")
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
