#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
اختبار نظام التقارير الأسبوعية المحسن
"""

import os
import sys
from datetime import datetime, timedelta

# إضافة المسار الحالي
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_fixed_reporting_system():
    """اختبار النظام المحسن"""
    print("🧪 اختبار نظام التقارير المحسن...")
    
    try:
        # اختبار الاستيراد
        from fixed_weekly_report import FixedWeeklyReportGenerator, is_fixed_email_configured
        print("✅ تم استيراد النظام المحسن بنجاح")
        
        # اختبار إعدادات الإيميل
        if is_fixed_email_configured():
            print("✅ إعدادات الإيميل مكونة بشكل صحيح")
        else:
            print("⚠️ إعدادات الإيميل غير مكتملة")
        
        # اختبار قاعدة البيانات
        database_url = os.getenv('DATABASE_URL')
        if database_url:
            print("✅ متغير قاعدة البيانات موجود")
        else:
            print("❌ متغير قاعدة البيانات غير موجود")
            return False
        
        # اختبار إنشاء مولد التقارير
        try:
            report_generator = FixedWeeklyReportGenerator()
            print("✅ تم إنشاء مولد التقارير بنجاح")
        except Exception as e:
            print(f"❌ فشل في إنشاء مولد التقارير: {e}")
            return False
        
        # اختبار جمع الإحصائيات
        try:
            today = datetime.now()
            start_date = today - timedelta(days=7)
            end_date = today
            
            stats = report_generator.get_comprehensive_stats(start_date, end_date)
            print(f"✅ تم جمع الإحصائيات: {len(stats)} مؤشر")
            
            user_progress = report_generator.get_user_progress_analysis(start_date, end_date)
            print(f"✅ تم تحليل تقدم المستخدمين: {len(user_progress)} مستخدم")
            
            grade_analysis = report_generator.get_grade_performance_analysis(start_date, end_date)
            print(f"✅ تم تحليل أداء الصفوف: {len(grade_analysis)} صف")
            
        except Exception as e:
            print(f"❌ فشل في جمع البيانات: {e}")
            return False
        
        # اختبار إنشاء التقرير (بدون إرسال)
        try:
            report_path = report_generator.create_fixed_excel_report(start_date, end_date)
            if report_path and os.path.exists(report_path):
                print(f"✅ تم إنشاء التقرير: {report_path}")
                file_size = os.path.getsize(report_path) / 1024  # KB
                print(f"📊 حجم التقرير: {file_size:.1f} KB")
            else:
                print("❌ فشل في إنشاء التقرير")
                return False
        except Exception as e:
            print(f"❌ فشل في إنشاء التقرير: {e}")
            return False
        
        print("\n🎉 جميع الاختبارات نجحت! النظام المحسن جاهز للعمل")
        return True
        
    except ImportError as e:
        print(f"❌ فشل في استيراد النظام: {e}")
        return False
    except Exception as e:
        print(f"❌ خطأ عام في الاختبار: {e}")
        return False

if __name__ == "__main__":
    # تعيين متغيرات البيئة للاختبار (إذا لم تكن موجودة)
    if not os.getenv('DATABASE_URL'):
        print("⚠️ تحذير: متغير DATABASE_URL غير موجود")
        print("يرجى تعيين متغيرات البيئة المطلوبة:")
        print("- DATABASE_URL")
        print("- EMAIL_USERNAME")
        print("- EMAIL_PASSWORD") 
        print("- ADMIN_EMAIL")
    
    success = test_fixed_reporting_system()
    sys.exit(0 if success else 1)

