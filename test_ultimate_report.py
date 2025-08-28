#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
اختبار نظام التقارير الأسبوعية المتكامل والذكي
"""

import os
import sys
import logging
from datetime import datetime, timedelta

# إعداد المسار
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# إعداد السجلات
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_ultimate_report_system():
    """اختبار النظام المتكامل"""
    try:
        logger.info("🧪 بدء اختبار نظام التقارير المتكامل...")
        
        # اختبار الاستيراد
        try:
            from ultimate_weekly_report import UltimateWeeklyReportGenerator, is_ultimate_email_configured
            logger.info("✅ تم استيراد النظام المتكامل بنجاح")
        except ImportError as e:
            logger.error(f"❌ فشل في استيراد النظام المتكامل: {e}")
            return False
        
        # اختبار إعدادات الإيميل
        email_configured = is_ultimate_email_configured()
        logger.info(f"📧 إعدادات الإيميل: {'✅ مُعدة' if email_configured else '❌ غير مُعدة'}")
        
        # اختبار إنشاء مولد التقارير
        try:
            report_generator = UltimateWeeklyReportGenerator()
            logger.info("✅ تم إنشاء مولد التقارير المتكامل بنجاح")
        except Exception as e:
            logger.error(f"❌ فشل في إنشاء مولد التقارير: {e}")
            return False
        
        # اختبار الاتصال بقاعدة البيانات
        try:
            # تحديد فترة اختبار
            today = datetime.now()
            week_start = today - timedelta(days=7)
            week_end = today
            
            # اختبار الإحصائيات العامة
            general_stats = report_generator.get_comprehensive_stats(week_start, week_end)
            logger.info(f"✅ تم الحصول على الإحصائيات العامة: {len(general_stats)} عنصر")
            
            # اختبار تحليل المستخدمين
            user_progress = report_generator.get_user_progress_analysis(week_start, week_end)
            logger.info(f"✅ تم تحليل {len(user_progress)} مستخدم")
            
            # اختبار تحليل الصفوف
            grade_analysis = report_generator.get_grade_performance_analysis(week_start, week_end)
            logger.info(f"✅ تم تحليل {len(grade_analysis)} صف دراسي")
            
            # اختبار تحليل الأسئلة الصعبة
            difficult_questions = report_generator.get_difficult_questions_analysis(week_start, week_end)
            logger.info(f"✅ تم تحليل {len(difficult_questions)} سؤال صعب")
            
            # اختبار أنماط الوقت
            time_patterns = report_generator.get_time_patterns_analysis(week_start, week_end)
            daily_count = len(time_patterns.get('daily_activity', []))
            hourly_count = len(time_patterns.get('peak_hours', []))
            logger.info(f"✅ تم تحليل أنماط الوقت: {daily_count} يوم، {hourly_count} ساعة ذروة")
            
        except Exception as e:
            logger.error(f"❌ خطأ في اختبار قاعدة البيانات: {e}")
            return False
        
        # اختبار إنشاء التقرير (بدون إرسال)
        try:
            report_path = report_generator.create_ultimate_excel_report(week_start, week_end)
            if report_path and os.path.exists(report_path):
                file_size = os.path.getsize(report_path) / 1024  # KB
                logger.info(f"✅ تم إنشاء التقرير بنجاح: {report_path} ({file_size:.1f} KB)")
                
                # عرض محتويات التقرير
                try:
                    import pandas as pd
                    excel_file = pd.ExcelFile(report_path)
                    sheet_names = excel_file.sheet_names
                    logger.info(f"📊 أوراق التقرير: {', '.join(sheet_names)}")
                except:
                    logger.info("📊 تم إنشاء ملف Excel بنجاح")
                
            else:
                logger.error("❌ فشل في إنشاء التقرير")
                return False
        except Exception as e:
            logger.error(f"❌ خطأ في إنشاء التقرير: {e}")
            return False
        
        # اختبار إنشاء الرسوم البيانية
        try:
            chart_paths = report_generator.create_performance_charts(
                user_progress, grade_analysis, time_patterns
            )
            logger.info(f"✅ تم إنشاء {len(chart_paths)} رسم بياني")
            
            for chart_name, chart_path in chart_paths.items():
                if os.path.exists(chart_path):
                    file_size = os.path.getsize(chart_path) / 1024  # KB
                    logger.info(f"  📈 {chart_name}: {file_size:.1f} KB")
                
        except Exception as e:
            logger.error(f"❌ خطأ في إنشاء الرسوم البيانية: {e}")
            return False
        
        # اختبار التوصيات الذكية
        try:
            smart_recommendations = report_generator.generate_smart_recommendations(
                general_stats, user_progress, grade_analysis, difficult_questions, time_patterns
            )
            total_recommendations = sum(len(recs) for recs in smart_recommendations.values())
            logger.info(f"✅ تم إنشاء {total_recommendations} توصية ذكية")
            
            for category, recs in smart_recommendations.items():
                logger.info(f"  💡 {category}: {len(recs)} توصية")
                
        except Exception as e:
            logger.error(f"❌ خطأ في إنشاء التوصيات الذكية: {e}")
            return False
        
        logger.info("🎉 تم اختبار جميع مكونات النظام المتكامل بنجاح!")
        
        # ملخص النتائج
        logger.info("\n📋 ملخص الاختبار:")
        logger.info(f"  👥 المستخدمين المحللين: {len(user_progress)}")
        logger.info(f"  🎓 الصفوف المحللة: {len(grade_analysis)}")
        logger.info(f"  ❓ الأسئلة الصعبة: {len(difficult_questions)}")
        logger.info(f"  📊 الرسوم البيانية: {len(chart_paths)}")
        logger.info(f"  💡 التوصيات: {total_recommendations}")
        logger.info(f"  📧 إعدادات الإيميل: {'✅' if email_configured else '❌'}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ خطأ عام في اختبار النظام: {e}")
        return False

def test_integration():
    """اختبار التكامل مع البوت"""
    try:
        logger.info("🔗 اختبار التكامل مع البوت...")
        
        from ultimate_bot_integration import setup_ultimate_reporting_system, is_admin_user
        
        # اختبار إعداد النظام
        reporting_system = setup_ultimate_reporting_system()
        if reporting_system:
            logger.info("✅ تم إعداد نظام التقارير للتكامل بنجاح")
        else:
            logger.error("❌ فشل في إعداد نظام التقارير للتكامل")
            return False
        
        # اختبار صلاحيات المدير
        test_user_id = 7640355263
        is_admin = is_admin_user(test_user_id)
        logger.info(f"🔐 اختبار صلاحيات المدير ({test_user_id}): {'✅ مدير' if is_admin else '❌ ليس مدير'}")
        
        logger.info("✅ تم اختبار التكامل بنجاح")
        return True
        
    except Exception as e:
        logger.error(f"❌ خطأ في اختبار التكامل: {e}")
        return False

if __name__ == "__main__":
    print("🧪 اختبار نظام التقارير الأسبوعية المتكامل والذكي")
    print("=" * 60)
    
    # اختبار النظام الأساسي
    success1 = test_ultimate_report_system()
    
    print("\n" + "=" * 60)
    
    # اختبار التكامل
    success2 = test_integration()
    
    print("\n" + "=" * 60)
    
    if success1 and success2:
        print("🎉 جميع الاختبارات نجحت! النظام جاهز للاستخدام")
        exit(0)
    else:
        print("❌ بعض الاختبارات فشلت. راجع السجلات أعلاه")
        exit(1)

