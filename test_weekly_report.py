#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
اختبار نظام التقارير الأسبوعية
"""

import sys
import os
from datetime import datetime, timedelta

# إضافة المسار الحالي
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

def test_database_connection():
    """اختبار الاتصال بقاعدة البيانات"""
    print("🔍 اختبار الاتصال بقاعدة البيانات...")
    
    try:
        from weekly_report import WeeklyReportGenerator
        from email_config import EMAIL_CONFIG
        
        db_path = "pasted_file_IJVgjG_bot_stats.db"
        generator = WeeklyReportGenerator(db_path, EMAIL_CONFIG)
        
        conn = generator.get_database_connection()
        cursor = conn.execute("SELECT COUNT(*) as count FROM users")
        result = cursor.fetchone()
        user_count = result['count']
        conn.close()
        
        print(f"✅ الاتصال بقاعدة البيانات نجح - عدد المستخدمين: {user_count}")
        return True
        
    except Exception as e:
        print(f"❌ فشل الاتصال بقاعدة البيانات: {e}")
        return False

def test_report_generation():
    """اختبار إنشاء التقرير (بدون إرسال)"""
    print("\n📊 اختبار إنشاء التقرير...")
    
    try:
        from weekly_report import WeeklyReportGenerator
        from email_config import EMAIL_CONFIG
        
        db_path = "pasted_file_IJVgjG_bot_stats.db"
        generator = WeeklyReportGenerator(db_path, EMAIL_CONFIG)
        
        # الحصول على نطاق الأسبوع الحالي
        today = datetime.now()
        week_start, week_end = generator.get_week_range(today)
        
        print(f"📅 فترة التقرير: {week_start.strftime('%Y-%m-%d')} إلى {week_end.strftime('%Y-%m-%d')}")
        
        # اختبار الحصول على الإحصائيات
        general_stats = generator.get_weekly_stats(week_start, week_end)
        print(f"📈 الإحصائيات العامة: {general_stats}")
        
        # اختبار الحصول على تفاصيل المستخدمين
        users_data = generator.get_user_weekly_details(week_start, week_end)
        print(f"👥 عدد المستخدمين: {len(users_data)}")
        
        if users_data:
            print("📋 عينة من بيانات المستخدمين:")
            for i, user in enumerate(users_data[:3]):  # أول 3 مستخدمين
                print(f"  {i+1}. المستخدم {user['user_id']}: {user['display_name']} - اختبارات: {user['weekly_quizzes']}")
        
        # اختبار تحليل الأخطاء
        error_analysis = generator.get_error_analysis(week_start, week_end)
        print(f"🔍 تحليل الأخطاء: {len(error_analysis.get('most_difficult_questions', []))} سؤال صعب")
        
        # اختبار إنشاء ملف Excel
        print("\n📄 اختبار إنشاء ملف Excel...")
        report_path = generator.create_excel_report(week_start, week_end)
        
        if os.path.exists(report_path):
            file_size = os.path.getsize(report_path)
            print(f"✅ تم إنشاء التقرير بنجاح: {report_path}")
            print(f"📏 حجم الملف: {file_size} بايت")
            return True
        else:
            print("❌ فشل في إنشاء ملف التقرير")
            return False
            
    except Exception as e:
        print(f"❌ فشل في إنشاء التقرير: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_email_config():
    """اختبار إعدادات البريد الإلكتروني"""
    print("\n📧 اختبار إعدادات البريد الإلكتروني...")
    
    try:
        from email_config import validate_email_config, EMAIL_CONFIG
        
        is_valid, message = validate_email_config()
        
        if is_valid:
            print("✅ إعدادات البريد الإلكتروني صحيحة")
        else:
            print(f"⚠️ إعدادات البريد الإلكتروني تحتاج تعديل: {message}")
        
        print(f"📤 إيميل المرسل: {EMAIL_CONFIG['sender_email']}")
        print(f"📥 إيميل المدير: {EMAIL_CONFIG['admin_email']}")
        
        return is_valid
        
    except Exception as e:
        print(f"❌ خطأ في فحص إعدادات البريد الإلكتروني: {e}")
        return False

def test_integration():
    """اختبار التكامل العام"""
    print("\n🔧 اختبار التكامل العام...")
    
    try:
        from bot_integration import BotReportingSystem
        
        db_path = "pasted_file_IJVgjG_bot_stats.db"
        reporting_system = BotReportingSystem(db_path)
        
        # اختبار التهيئة
        if reporting_system.initialize():
            print("✅ تم تهيئة نظام التقارير بنجاح")
            
            # اختبار الحصول على حالة النظام
            status = reporting_system.get_system_status()
            print(f"📊 حالة النظام: {status}")
            
            return True
        else:
            print("❌ فشل في تهيئة نظام التقارير")
            return False
            
    except Exception as e:
        print(f"❌ خطأ في اختبار التكامل: {e}")
        return False

def main():
    """تشغيل جميع الاختبارات"""
    print("🚀 بدء اختبار نظام التقارير الأسبوعية")
    print("=" * 50)
    
    tests = [
        ("اختبار قاعدة البيانات", test_database_connection),
        ("اختبار إعدادات الإيميل", test_email_config),
        ("اختبار إنشاء التقرير", test_report_generation),
        ("اختبار التكامل", test_integration),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\n{'='*20} {test_name} {'='*20}")
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ خطأ في {test_name}: {e}")
            results.append((test_name, False))
    
    # عرض النتائج النهائية
    print("\n" + "="*50)
    print("📋 ملخص نتائج الاختبارات:")
    print("="*50)
    
    passed = 0
    for test_name, result in results:
        status = "✅ نجح" if result else "❌ فشل"
        print(f"{status} {test_name}")
        if result:
            passed += 1
    
    print(f"\n📊 النتيجة النهائية: {passed}/{len(results)} اختبارات نجحت")
    
    if passed == len(results):
        print("🎉 جميع الاختبارات نجحت! النظام جاهز للاستخدام.")
    else:
        print("⚠️ بعض الاختبارات فشلت. يرجى مراجعة الأخطاء أعلاه.")

if __name__ == "__main__":
    main()

