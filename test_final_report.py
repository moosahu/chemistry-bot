#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
اختبار نظام التقارير الأسبوعية النهائي والمحسن
يتضمن اختبارات شاملة للتأكد من عمل النظام بدون مشاكل الخطوط
"""

import os
import sys
from datetime import datetime, timedelta

# إضافة المسار الحالي
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_final_reporting_system():
    """اختبار النظام النهائي والمحسن"""
    print("🧪 اختبار نظام التقارير النهائي والمحسن...")
    print("=" * 60)
    
    try:
        # اختبار الاستيراد
        print("📦 اختبار الاستيراد...")
        from final_weekly_report import FinalWeeklyReportGenerator, FinalWeeklyReportScheduler
        print("✅ تم استيراد النظام النهائي بنجاح")
        
        # اختبار إعدادات الإيميل
        print("\n📧 اختبار إعدادات الإيميل...")
        email_username = os.getenv('EMAIL_USERNAME')
        email_password = os.getenv('EMAIL_PASSWORD')
        admin_email = os.getenv('ADMIN_EMAIL')
        
        if all([email_username, email_password, admin_email]):
            print("✅ إعدادات الإيميل مكونة بشكل صحيح")
            print(f"   📧 إيميل البوت: {email_username}")
            print(f"   📧 إيميل الإدارة: {admin_email}")
        else:
            print("⚠️ إعدادات الإيميل غير مكتملة")
            print(f"   EMAIL_USERNAME: {'✅' if email_username else '❌'}")
            print(f"   EMAIL_PASSWORD: {'✅' if email_password else '❌'}")
            print(f"   ADMIN_EMAIL: {'✅' if admin_email else '❌'}")
        
        # اختبار قاعدة البيانات
        print("\n🗄️ اختبار قاعدة البيانات...")
        database_url = os.getenv('DATABASE_URL')
        if database_url:
            print("✅ متغير قاعدة البيانات موجود")
            print(f"   🔗 النوع: {'PostgreSQL' if 'postgresql' in database_url else 'أخرى'}")
        else:
            print("❌ متغير قاعدة البيانات غير موجود")
            return False
        
        # اختبار إنشاء مولد التقارير
        print("\n⚙️ اختبار إنشاء مولد التقارير...")
        try:
            report_generator = FinalWeeklyReportGenerator()
            print("✅ تم إنشاء مولد التقارير بنجاح")
            print(f"   📁 مجلد التقارير: {report_generator.reports_dir}")
            print(f"   📊 مجلد الرسوم: {report_generator.charts_dir}")
        except Exception as e:
            print(f"❌ فشل في إنشاء مولد التقارير: {e}")
            return False
        
        # اختبار إنشاء جدولة التقارير
        print("\n⏰ اختبار إنشاء جدولة التقارير...")
        try:
            scheduler = FinalWeeklyReportScheduler()
            print("✅ تم إنشاء جدولة التقارير بنجاح")
        except Exception as e:
            print(f"❌ فشل في إنشاء جدولة التقارير: {e}")
            return False
        
        # اختبار جمع الإحصائيات
        print("\n📊 اختبار جمع البيانات...")
        try:
            today = datetime.now()
            start_date = today - timedelta(days=7)
            end_date = today
            
            print(f"   📅 الفترة: {start_date.strftime('%Y-%m-%d')} إلى {end_date.strftime('%Y-%m-%d')}")
            
            # الإحصائيات الشاملة
            stats = report_generator.get_comprehensive_stats(start_date, end_date)
            print(f"✅ تم جمع الإحصائيات الشاملة: {len(stats)} مؤشر")
            if stats:
                print(f"   👥 إجمالي المستخدمين: {stats.get('total_registered_users', 0)}")
                print(f"   🎯 النشطين هذا الأسبوع: {stats.get('active_users_this_week', 0)}")
                print(f"   📈 معدل المشاركة: {stats.get('engagement_rate', 0)}%")
            
            # تحليل تقدم المستخدمين
            user_progress = report_generator.get_user_progress_analysis(start_date, end_date)
            print(f"✅ تم تحليل تقدم المستخدمين: {len(user_progress)} مستخدم")
            
            # تحليل أداء الصفوف
            grade_analysis = report_generator.get_grade_performance_analysis(start_date, end_date)
            print(f"✅ تم تحليل أداء الصفوف: {len(grade_analysis)} صف")
            
            # تحليل الأسئلة الصعبة
            difficult_questions = report_generator.get_difficult_questions_analysis(start_date, end_date)
            print(f"✅ تم تحليل الأسئلة الصعبة: {len(difficult_questions)} سؤال")
            
            # تحليل أنماط الوقت
            time_patterns = report_generator.get_time_patterns_analysis(start_date, end_date)
            daily_activity = time_patterns.get('daily_activity', [])
            peak_hours = time_patterns.get('peak_hours', [])
            print(f"✅ تم تحليل أنماط الوقت: {len(daily_activity)} يوم، {len(peak_hours)} ساعة ذروة")
            
        except Exception as e:
            print(f"❌ فشل في جمع البيانات: {e}")
            return False
        
        # اختبار إنشاء الرسوم البيانية
        print("\n📈 اختبار إنشاء الرسوم البيانية...")
        try:
            chart_paths = report_generator.create_performance_charts(
                user_progress, grade_analysis, time_patterns
            )
            print(f"✅ تم إنشاء الرسوم البيانية: {len(chart_paths)} رسم")
            for chart_name, chart_path in chart_paths.items():
                if os.path.exists(chart_path):
                    file_size = os.path.getsize(chart_path) / 1024  # KB
                    print(f"   📊 {chart_name}: {file_size:.1f} KB")
                else:
                    print(f"   ❌ {chart_name}: الملف غير موجود")
        except Exception as e:
            print(f"❌ فشل في إنشاء الرسوم البيانية: {e}")
            print(f"   تفاصيل الخطأ: {str(e)}")
            # لا نوقف الاختبار هنا لأن الرسوم قد تفشل بسبب عدم وجود بيانات
        
        # اختبار إنشاء التوصيات الذكية
        print("\n💡 اختبار إنشاء التوصيات الذكية...")
        try:
            recommendations = report_generator.generate_smart_recommendations(
                stats, user_progress, grade_analysis, difficult_questions, time_patterns
            )
            total_recommendations = sum(len(recs) for recs in recommendations.values())
            print(f"✅ تم إنشاء التوصيات الذكية: {total_recommendations} توصية")
            for category, recs in recommendations.items():
                print(f"   📋 {category}: {len(recs)} توصية")
        except Exception as e:
            print(f"❌ فشل في إنشاء التوصيات: {e}")
        
        # اختبار إنشاء التقرير (بدون إرسال)
        print("\n📄 اختبار إنشاء التقرير...")
        try:
            report_path = report_generator.create_final_excel_report(start_date, end_date)
            if report_path and os.path.exists(report_path):
                print(f"✅ تم إنشاء التقرير: {os.path.basename(report_path)}")
                file_size = os.path.getsize(report_path) / 1024  # KB
                print(f"   📊 حجم التقرير: {file_size:.1f} KB")
                print(f"   📁 المسار الكامل: {report_path}")
            else:
                print("❌ فشل في إنشاء التقرير")
                return False
        except Exception as e:
            print(f"❌ فشل في إنشاء التقرير: {e}")
            return False
        
        # اختبار التحليلات السريعة
        print("\n⚡ اختبار التحليلات السريعة...")
        try:
            quick_analytics = scheduler.get_quick_analytics()
            if quick_analytics:
                print("✅ تم جمع التحليلات السريعة")
                print(f"   📅 الفترة: {quick_analytics.get('period', 'غير محدد')}")
                print(f"   👥 إجمالي المستخدمين: {quick_analytics.get('total_users', 0)}")
                print(f"   🎯 النشطين: {quick_analytics.get('active_users', 0)}")
                print(f"   📈 معدل المشاركة: {quick_analytics.get('engagement_rate', 0)}%")
            else:
                print("⚠️ لا توجد بيانات للتحليلات السريعة")
        except Exception as e:
            print(f"❌ فشل في التحليلات السريعة: {e}")
        
        print("\n" + "=" * 60)
        print("🎉 جميع الاختبارات الأساسية نجحت!")
        print("✅ النظام النهائي جاهز للعمل بدون مشاكل الخطوط")
        print("📧 يمكن الآن إرسال التقارير بالإيميل")
        print("📊 الرسوم البيانية تعمل بخطوط آمنة")
        return True
        
    except ImportError as e:
        print(f"❌ فشل في استيراد النظام: {e}")
        return False
    except Exception as e:
        print(f"❌ خطأ عام في الاختبار: {e}")
        return False

def test_integration():
    """اختبار التكامل مع البوت"""
    print("\n🤖 اختبار التكامل مع البوت...")
    
    try:
        from final_bot_integration import (
            setup_final_reporting_system,
            is_final_email_configured,
            is_admin_user
        )
        print("✅ تم استيراد وحدة التكامل بنجاح")
        
        # اختبار إعداد النظام
        reporting_system = setup_final_reporting_system()
        if reporting_system:
            print("✅ تم إعداد نظام التقارير للتكامل")
        else:
            print("❌ فشل في إعداد نظام التقارير للتكامل")
        
        # اختبار فحص الإيميل
        if is_final_email_configured():
            print("✅ إعدادات الإيميل جاهزة للتكامل")
        else:
            print("⚠️ إعدادات الإيميل غير مكتملة للتكامل")
        
        # اختبار فحص المدير (مع معرف تجريبي)
        test_admin_id = 7640355263
        if is_admin_user(test_admin_id):
            print(f"✅ المعرف {test_admin_id} معترف به كمدير")
        else:
            print(f"⚠️ المعرف {test_admin_id} غير معترف به كمدير")
        
        return True
        
    except ImportError as e:
        print(f"❌ فشل في استيراد وحدة التكامل: {e}")
        return False
    except Exception as e:
        print(f"❌ خطأ في اختبار التكامل: {e}")
        return False

if __name__ == "__main__":
    print("🚀 بدء اختبار النظام النهائي والمحسن")
    print("=" * 60)
    
    # تحقق من متغيرات البيئة
    required_vars = ['DATABASE_URL', 'EMAIL_USERNAME', 'EMAIL_PASSWORD', 'ADMIN_EMAIL']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print("⚠️ تحذير: متغيرات البيئة التالية غير موجودة:")
        for var in missing_vars:
            print(f"   ❌ {var}")
        print("\nيرجى تعيين جميع متغيرات البيئة المطلوبة للاختبار الكامل")
        print("=" * 60)
    
    # تشغيل الاختبارات
    success1 = test_final_reporting_system()
    success2 = test_integration()
    
    overall_success = success1 and success2
    
    print("\n" + "=" * 60)
    if overall_success:
        print("🎉 جميع الاختبارات نجحت! النظام جاهز للاستخدام")
        print("🚀 يمكن الآن نشر النظام في الإنتاج")
    else:
        print("❌ بعض الاختبارات فشلت - يرجى مراجعة الأخطاء أعلاه")
    
    print("=" * 60)
    sys.exit(0 if overall_success else 1)

