#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
دمج نظام التقارير الأسبوعية المتكامل والذكي مع البوت
يوفر أوامر إدارية متقدمة وتقارير ذكية
"""

import os
import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from ultimate_weekly_report import UltimateWeeklyReportGenerator, UltimateWeeklyReportScheduler, is_ultimate_email_configured

logger = logging.getLogger(__name__)

# قائمة معرفات المدراء (يمكن إضافة المزيد)
ADMIN_USER_IDS = [
    7640355263,  # معرف المدير الأساسي
    # يمكن إضافة معرفات أخرى هنا
]

def is_admin_user(user_id: int) -> bool:
    """التحقق من صلاحيات المدير المحسنة"""
    try:
        # التحقق من متغير البيئة
        admin_id_env = os.getenv('ADMIN_USER_ID')
        if admin_id_env and str(user_id) == str(admin_id_env):
            return True
        
        # التحقق من القائمة المحددة
        if user_id in ADMIN_USER_IDS:
            return True
        
        # التحقق من قاعدة البيانات (إذا كان هناك نظام مدراء)
        try:
            # يمكن إضافة التحقق من قاعدة البيانات هنا
            pass
        except:
            pass
        
        return False
        
    except Exception as e:
        logger.error(f"خطأ في التحقق من صلاحيات المدير: {e}")
        return False

async def ultimate_report_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض حالة نظام التقارير المتكامل"""
    try:
        user_id = update.effective_user.id
        
        # التحقق من الصلاحيات
        if not is_admin_user(user_id):
            await update.message.reply_text(
                "❌ عذراً، هذا الأمر متاح للمدراء فقط.\n"
                f"معرف المستخدم: {user_id}"
            )
            return
        
        # فحص إعدادات الإيميل
        email_configured = is_ultimate_email_configured()
        
        # فحص قاعدة البيانات
        try:
            report_generator = UltimateWeeklyReportGenerator()
            db_status = "✅ متصل"
        except Exception as e:
            db_status = f"❌ خطأ: {str(e)[:50]}..."
        
        # إعداد الرسالة
        status_message = f"""
🔍 حالة نظام التقارير المتكامل والذكي

👤 معرف المستخدم: {user_id}
🔐 صلاحية المدير: ✅ مؤكدة

📧 إعدادات الإيميل: {'✅ مُعدة' if email_configured else '❌ غير مُعدة'}
🗄️ قاعدة البيانات: {db_status}

📊 المميزات المتاحة:
• تحليل تقدم المستخدمين مع الاتجاهات
• إحصائيات الصفوف الدراسية
• تحليل الأسئلة الصعبة
• أنماط النشاط والأوقات المثلى
• توصيات ذكية مخصصة
• رسوم بيانية تفاعلية

⏰ الجدولة: كل يوم أحد الساعة 9:00 صباحاً

🎯 الأوامر المتاحة:
/ultimate_report_status - حالة النظام
/generate_ultimate_report - تقرير فوري متكامل
        """
        
        await update.message.reply_text(status_message)
        logger.info(f"تم عرض حالة النظام المتكامل للمدير {user_id}")
        
    except Exception as e:
        logger.error(f"خطأ في عرض حالة النظام المتكامل: {e}")
        await update.message.reply_text(
            "❌ حدث خطأ في عرض حالة النظام المتكامل"
        )

async def generate_ultimate_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إنشاء تقرير فوري متكامل"""
    try:
        user_id = update.effective_user.id
        
        # التحقق من الصلاحيات
        if not is_admin_user(user_id):
            await update.message.reply_text(
                "❌ عذراً، هذا الأمر متاح للمدراء فقط.\n"
                f"معرف المستخدم: {user_id}"
            )
            return
        
        # التحقق من إعدادات الإيميل
        if not is_ultimate_email_configured():
            await update.message.reply_text(
                "❌ إعدادات الإيميل غير مُعدة بشكل صحيح.\n"
                "تأكد من وجود المتغيرات: EMAIL_USERNAME, EMAIL_PASSWORD, ADMIN_EMAIL"
            )
            return
        
        # إرسال رسالة البداية
        status_message = await update.message.reply_text("🔄 جاري إنشاء التقرير المتكامل والذكي...")
        
        try:
            # إنشاء مولد التقارير
            report_generator = UltimateWeeklyReportGenerator()
            
            # إنشاء وإرسال التقرير
            success = report_generator.generate_and_send_ultimate_report()
            
            if success:
                await status_message.edit_text(
                    "✅ تم إنشاء وإرسال التقرير المتكامل بنجاح!\n\n"
                    "📊 التقرير يشمل:\n"
                    "• الملخص التنفيذي\n"
                    "• تحليل تقدم المستخدمين\n"
                    "• أداء الصفوف الدراسية\n"
                    "• الأسئلة الصعبة\n"
                    "• أنماط النشاط\n"
                    "• توصيات ذكية\n"
                    "• رسوم بيانية ملونة\n\n"
                    "📧 تحقق من إيميلك للحصول على التقرير الكامل"
                )
                logger.info(f"تم إنشاء التقرير المتكامل بنجاح بواسطة المدير {user_id}")
            else:
                await status_message.edit_text(
                    "❌ فشل في إنشاء التقرير المتكامل.\n"
                    "تحقق من السجلات للمزيد من التفاصيل."
                )
                logger.error(f"فشل في إنشاء التقرير المتكامل بواسطة المدير {user_id}")
                
        except Exception as e:
            await status_message.edit_text(
                f"❌ خطأ في إنشاء التقرير المتكامل:\n{str(e)[:100]}..."
            )
            logger.error(f"خطأ في إنشاء التقرير المتكامل: {e}")
            
    except Exception as e:
        logger.error(f"خطأ في أمر إنشاء التقرير المتكامل: {e}")
        await update.message.reply_text(
            "❌ حدث خطأ في معالجة الأمر"
        )

async def ultimate_analytics_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض تحليلات سريعة متقدمة"""
    try:
        user_id = update.effective_user.id
        
        # التحقق من الصلاحيات
        if not is_admin_user(user_id):
            await update.message.reply_text(
                "❌ عذراً، هذا الأمر متاح للمدراء فقط."
            )
            return
        
        # إرسال رسالة البداية
        status_message = await update.message.reply_text("📊 جاري تحليل البيانات...")
        
        try:
            # إنشاء مولد التقارير
            report_generator = UltimateWeeklyReportGenerator()
            
            # تحديد فترة الأسبوع الحالي
            today = datetime.now()
            week_start = today - timedelta(days=today.weekday())
            week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
            week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
            
            # الحصول على الإحصائيات السريعة
            general_stats = report_generator.get_comprehensive_stats(week_start, week_end)
            user_progress = report_generator.get_user_progress_analysis(week_start, week_end)
            
            # إعداد الرسالة
            analytics_message = f"""
📈 التحليلات السريعة - الأسبوع الحالي

👥 المستخدمين:
• إجمالي المسجلين: {general_stats.get('total_registered_users', 0)}
• النشطين هذا الأسبوع: {general_stats.get('active_users_this_week', 0)}
• معدل المشاركة: {general_stats.get('engagement_rate', 0)}%

📊 الأداء:
• متوسط الدرجات: {general_stats.get('avg_percentage_this_week', 0)}%
• إجمالي الاختبارات: {general_stats.get('total_quizzes_this_week', 0)}
• إجمالي الأسئلة: {general_stats.get('total_questions_this_week', 0)}

🎯 تصنيف المستخدمين:
            """
            
            if user_progress:
                # تحليل مستويات الأداء
                performance_counts = {}
                for user in user_progress:
                    level = user['performance_level']
                    performance_counts[level] = performance_counts.get(level, 0) + 1
                
                for level, count in performance_counts.items():
                    analytics_message += f"• {level}: {count} مستخدم\n"
                
                # أفضل 3 مستخدمين
                top_users = sorted(user_progress, key=lambda x: x['overall_avg_percentage'], reverse=True)[:3]
                analytics_message += f"\n🏆 أفضل 3 مستخدمين:\n"
                for i, user in enumerate(top_users, 1):
                    analytics_message += f"{i}. {user['full_name']}: {user['overall_avg_percentage']}%\n"
            
            analytics_message += f"\n📅 الفترة: {week_start.strftime('%Y-%m-%d')} - {week_end.strftime('%Y-%m-%d')}"
            
            await status_message.edit_text(analytics_message)
            logger.info(f"تم عرض التحليلات السريعة للمدير {user_id}")
            
        except Exception as e:
            await status_message.edit_text(
                f"❌ خطأ في تحليل البيانات:\n{str(e)[:100]}..."
            )
            logger.error(f"خطأ في التحليلات السريعة: {e}")
            
    except Exception as e:
        logger.error(f"خطأ في أمر التحليلات السريعة: {e}")
        await update.message.reply_text(
            "❌ حدث خطأ في معالجة الأمر"
        )

def setup_ultimate_reporting_system():
    """إعداد نظام التقارير المتكامل"""
    try:
        logger.info("بدء إعداد نظام التقارير المتكامل والذكي...")
        
        # التحقق من إعدادات قاعدة البيانات
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            logger.error("متغير DATABASE_URL غير موجود")
            return None
        
        # إنشاء مولد التقارير
        report_generator = UltimateWeeklyReportGenerator()
        logger.info("تم إنشاء مولد التقارير المتكامل بنجاح")
        
        # إنشاء جدولة التقارير
        scheduler = UltimateWeeklyReportScheduler(report_generator)
        logger.info("تم إعداد جدولة التقارير المتكاملة بنجاح")
        
        return scheduler
        
    except Exception as e:
        logger.error(f"خطأ في إعداد نظام التقارير المتكامل: {e}")
        return None

def add_ultimate_admin_commands(application, reporting_system):
    """إضافة الأوامر الإدارية المتكاملة للبوت"""
    try:
        from telegram.ext import CommandHandler
        
        # إضافة أوامر التقارير المتكاملة
        application.add_handler(CommandHandler("ultimate_report_status", ultimate_report_status_command))
        application.add_handler(CommandHandler("generate_ultimate_report", generate_ultimate_report_command))
        application.add_handler(CommandHandler("ultimate_analytics", ultimate_analytics_command))
        
        # أوامر مختصرة
        application.add_handler(CommandHandler("ur_status", ultimate_report_status_command))
        application.add_handler(CommandHandler("ur_generate", generate_ultimate_report_command))
        application.add_handler(CommandHandler("ur_analytics", ultimate_analytics_command))
        
        logger.info("تم إضافة الأوامر الإدارية المتكاملة بنجاح")
        
    except Exception as e:
        logger.error(f"خطأ في إضافة الأوامر الإدارية المتكاملة: {e}")

# مثال على الاستخدام في الملف الرئيسي للبوت
"""
# في ملف bot.py، أضف هذا الكود:

from ultimate_bot_integration import setup_ultimate_reporting_system, add_ultimate_admin_commands

# في دالة main()
def main():
    # ... الكود الموجود ...
    
    # إعداد نظام التقارير المتكامل
    ultimate_reporting_system = setup_ultimate_reporting_system()
    if ultimate_reporting_system:
        ultimate_reporting_system.start_scheduler()
        add_ultimate_admin_commands(application, ultimate_reporting_system)
        logger.info("✅ Ultimate Weekly Reports System activated successfully")
    else:
        logger.error("❌ Failed to initialize Ultimate Weekly Reports System")
    
    # ... باقي الكود ...
"""

