#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
سكريبت اختبار تصدير بيانات المستخدمين إلى ملف إكسل
هذا السكريبت يقوم بإنشاء بيانات تجريبية واختبار وظيفة التصدير
"""

import os
import sys
import logging
import pandas as pd
from sqlalchemy import create_engine, text, MetaData, Table, Column, BigInteger, Text, Boolean, TIMESTAMP
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta

# إضافة المسار الرئيسي للمشروع إلى مسارات البحث
sys.path.append('/home/ubuntu/upload')
sys.path.append('/home/ubuntu/upload/admin_tools')

# استيراد أداة التصدير
from admin_tools.export_users_to_excel import export_users_to_excel, get_engine

# تكوين التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_test_data():
    """
    إنشاء بيانات تجريبية للمستخدمين في قاعدة بيانات مؤقتة للاختبار
    
    العائد:
        engine: محرك قاعدة البيانات المؤقتة
    """
    try:
        # إنشاء قاعدة بيانات SQLite مؤقتة للاختبار
        test_db_path = '/home/ubuntu/upload/admin_tools/test_users_db.sqlite'
        
        # حذف قاعدة البيانات المؤقتة إذا كانت موجودة
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
        
        # إنشاء محرك قاعدة البيانات
        engine = create_engine(f'sqlite:///{test_db_path}')
        
        # إنشاء جدول المستخدمين
        metadata = MetaData()
        users_table = Table(
            "users", metadata,
            Column("user_id", BigInteger, primary_key=True),
            Column("username", Text, nullable=True),
            Column("first_name", Text, nullable=True),
            Column("last_name", Text, nullable=True),
            Column("full_name", Text, nullable=True),
            Column("email", Text, nullable=True),
            Column("phone", Text, nullable=True),
            Column("grade", Text, nullable=True),
            Column("is_registered", Boolean, default=False),
            Column("is_admin", Boolean, default=False),
            Column("language_code", Text, nullable=True),
            Column("first_seen_timestamp", TIMESTAMP, nullable=True),
            Column("last_active_timestamp", TIMESTAMP, nullable=True),
            Column("last_interaction_date", TIMESTAMP, nullable=True)
        )
        
        # إنشاء الجدول في قاعدة البيانات
        metadata.create_all(engine)
        
        # إنشاء بيانات تجريبية
        now = datetime.now()
        test_users = [
            {
                "user_id": 123456789,
                "username": "admin_user",
                "first_name": "أحمد",
                "last_name": "المدير",
                "full_name": "أحمد المدير",
                "email": "admin@example.com",
                "phone": "0501234567",
                "grade": "معلم",
                "is_registered": True,
                "is_admin": True,
                "language_code": "ar",
                "first_seen_timestamp": now - timedelta(days=30),
                "last_active_timestamp": now,
                "last_interaction_date": now
            },
            {
                "user_id": 987654321,
                "username": "student1",
                "first_name": "محمد",
                "last_name": "الطالب",
                "full_name": "محمد الطالب",
                "email": "student1@example.com",
                "phone": "0507654321",
                "grade": "الصف الأول الثانوي",
                "is_registered": True,
                "is_admin": False,
                "language_code": "ar",
                "first_seen_timestamp": now - timedelta(days=20),
                "last_active_timestamp": now - timedelta(hours=2),
                "last_interaction_date": now - timedelta(hours=2)
            },
            {
                "user_id": 555555555,
                "username": "teacher1",
                "first_name": "فاطمة",
                "last_name": "المعلمة",
                "full_name": "فاطمة المعلمة",
                "email": "teacher1@example.com",
                "phone": "0505555555",
                "grade": "معلم",
                "is_registered": True,
                "is_admin": False,
                "language_code": "ar",
                "first_seen_timestamp": now - timedelta(days=15),
                "last_active_timestamp": now - timedelta(days=1),
                "last_interaction_date": now - timedelta(days=1)
            },
            {
                "user_id": 111111111,
                "username": "student2",
                "first_name": "سارة",
                "last_name": "الطالبة",
                "full_name": "سارة الطالبة",
                "email": "student2@example.com",
                "phone": "0501111111",
                "grade": "الصف الثاني الثانوي",
                "is_registered": True,
                "is_admin": False,
                "language_code": "ar",
                "first_seen_timestamp": now - timedelta(days=10),
                "last_active_timestamp": now - timedelta(hours=5),
                "last_interaction_date": now - timedelta(hours=5)
            },
            {
                "user_id": 222222222,
                "username": "unregistered_user",
                "first_name": "خالد",
                "last_name": "غير مسجل",
                "full_name": None,
                "email": None,
                "phone": None,
                "grade": None,
                "is_registered": False,
                "is_admin": False,
                "language_code": "ar",
                "first_seen_timestamp": now - timedelta(days=5),
                "last_active_timestamp": now - timedelta(days=5),
                "last_interaction_date": now - timedelta(days=5)
            }
        ]
        
        # إدخال البيانات التجريبية في الجدول
        with engine.connect() as conn:
            for user in test_users:
                conn.execute(users_table.insert().values(**user))
            conn.commit()
        
        logger.info(f"تم إنشاء قاعدة بيانات تجريبية بنجاح مع {len(test_users)} مستخدمين")
        return engine
    
    except Exception as e:
        logger.error(f"خطأ أثناء إنشاء بيانات تجريبية: {e}")
        return None

def test_export_users_to_excel(engine):
    """
    اختبار تصدير بيانات المستخدمين إلى ملف إكسل
    
    المعلمات:
        engine: محرك قاعدة البيانات للاختبار
    
    العائد:
        str: مسار ملف الإكسل المُصدَّر
    """
    try:
        # استبدال دالة get_engine في وحدة التصدير بمحرك الاختبار
        import admin_tools.export_users_to_excel as export_module
        original_get_engine = export_module.get_engine
        export_module.get_engine = lambda: engine
        
        # تنفيذ التصدير
        logger.info("اختبار تصدير بيانات المستخدمين إلى ملف إكسل...")
        excel_path = export_users_to_excel(admin_user_id=123456789)
        
        # إعادة الدالة الأصلية
        export_module.get_engine = original_get_engine
        
        if excel_path and os.path.exists(excel_path):
            logger.info(f"تم تصدير بيانات المستخدمين بنجاح إلى: {excel_path}")
            
            # قراءة الملف المُصدَّر للتحقق من البيانات
            df = pd.read_excel(excel_path)
            logger.info(f"تم استخراج {len(df)} مستخدمين مسجلين من أصل 5 مستخدمين (4 مسجلين و1 غير مسجل)")
            
            # التحقق من أن المستخدمين غير المسجلين لم يتم تضمينهم
            if len(df) == 4:
                logger.info("✅ تم التحقق بنجاح: تم تضمين المستخدمين المسجلين فقط")
            else:
                logger.warning(f"⚠️ تحذير: عدد المستخدمين المُصدَّرين ({len(df)}) لا يتطابق مع العدد المتوقع (4)")
            
            # التحقق من وجود جميع الأعمدة المطلوبة
            expected_columns = [
                'معرف المستخدم', 'اسم المستخدم', 'الاسم الأول', 'الاسم الأخير', 'الاسم الكامل',
                'البريد الإلكتروني', 'رقم الجوال', 'الصف الدراسي', 'مسجل', 'مدير'
            ]
            
            missing_columns = [col for col in expected_columns if col not in df.columns]
            if not missing_columns:
                logger.info("✅ تم التحقق بنجاح: جميع الأعمدة المطلوبة موجودة في الملف المُصدَّر")
            else:
                logger.warning(f"⚠️ تحذير: الأعمدة التالية مفقودة في الملف المُصدَّر: {missing_columns}")
            
            return excel_path
        else:
            logger.error("❌ فشل تصدير بيانات المستخدمين")
            return None
    
    except Exception as e:
        logger.error(f"خطأ أثناء اختبار تصدير بيانات المستخدمين: {e}")
        return None

def main():
    """الدالة الرئيسية للاختبار"""
    try:
        logger.info("بدء اختبار تصدير بيانات المستخدمين إلى ملف إكسل...")
        
        # إنشاء بيانات تجريبية
        engine = create_test_data()
        if not engine:
            logger.error("فشل إنشاء بيانات تجريبية")
            return
        
        # اختبار التصدير
        excel_path = test_export_users_to_excel(engine)
        
        if excel_path:
            logger.info(f"✅ تم اختبار تصدير بيانات المستخدمين بنجاح. الملف: {excel_path}")
            print(f"تم تصدير بيانات المستخدمين بنجاح إلى: {excel_path}")
        else:
            logger.error("❌ فشل اختبار تصدير بيانات المستخدمين")
            print("فشل اختبار تصدير بيانات المستخدمين")
    
    except Exception as e:
        logger.error(f"خطأ غير متوقع أثناء الاختبار: {e}")
        print(f"حدث خطأ أثناء الاختبار: {e}")

if __name__ == "__main__":
    main()
