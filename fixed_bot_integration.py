#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
دمج نظام التقارير الأسبوعية المحسن مع البوت
يعمل مع المكتبات الموجودة فقط
"""

import logging
import os
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from fixed_weekly_report import (
    FixedWeeklyReportGenerator, 
    FixedWeeklyReportScheduler, 
    is_fixed_email_configured
)

logger = logging.getLogger(__name__)

def setup_fixed_reporting_system():
    """إعداد نظام التقارير المحسن"""
    try:
        # التحقق من قاعدة البيانات
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            logger.error("متغير DATABASE_URL غير موجود")
            return None
        
        logger.info(f"تم العثور على قاعدة البيانات: {database_url[:50]}...")
        
        # إنشاء مولد التقارير
        report_generator = FixedWeeklyReportGenerator()
        
        # إنشاء جدولة التقارير
        scheduler = FixedWeeklyReportScheduler(report_generator)
        
        logger.info("تم إعداد نظام التقارير المحسن بنجاح")
        return scheduler
        
    except Exception as e:
        logger.error(f"خطأ في إعداد نظام التقارير المحسن: {e}")
        return None

def is_admin_user(user_id: int) -> bool:
    """التحقق من صلاحيات المدير"""
    try:
        # قائمة المدراء المحددة مسبقاً
        admin_ids = [6448526509, 7640355263]  # أضف معرفات المدراء هنا
        
        # التحقق من متغير البيئة
        admin_user_id = os.getenv('ADMIN_USER_ID')
        if admin_user_id:
            try:
                admin_ids.append(int(admin_user_id))
            except ValueError:
                pass
        
        return user_id in admin_ids
        
    except Exception as e:
        logger.error(f"خطأ في التحقق من صلاحيات المدير: {e}")
        return False

async def fixed_report_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض حالة نظام التقارير المحسن"""
    try:
        user_id = update.effective_user.id
        
        # التحقق من الصلاحيات
        if not is_admin_user(user_id):
            await update.message.reply_text(
                "❌ عذراً، هذا الأمر متاح للمدراء فقط.\n"
                f"معرف المستخدم: {user_id}"
            )
            return
        
        # فحص حالة النظام
        status_message = "📊 حالة نظام التقارير المحسن\n\n"
        
        # فحص قاعدة البيانات
        database_url = os.getenv('DATABASE_URL')
        if database_url:
            status_message += "✅ قاعدة البيانات: متصلة\n"
        else:
            status_message += "❌ قاعدة البيانات: غير متصلة\n"
        
        # فحص إعدادات الإيميل
        if is_fixed_email_configured():
            status_message += "✅ إعدادات الإيميل: مكونة بشكل صحيح\n"
        else:
            status_message += "❌ إعدادات الإيميل: غير مكتملة\n"
        
        # معلومات المدير
        status_message += f"\n👤 معلومات المدير:\n"
        status_message += f"• معرف المستخدم: {user_id}\n"
        status_message += f"• حالة الصلاحية: مدير ✅\n"
        
        # جدولة التقارير
        status_message += f"\n📅 جدولة التقارير:\n"
        status_message += f"• التوقيت: كل يوم أحد الساعة 9:00 صباحاً\n"
        status_message += f"• المحتوى: إحصائيات الأسبوع الماضي\n"
        
        # الأوامر المتاحة
        status_message += f"\n🛠️ الأوامر المتاحة:\n"
        status_message += f"• /fixed_generate - إنشاء تقرير فوري\n"
        status_message += f"• /fixed_status - عرض هذه الحالة\n"
        status_message += f"• /fixed_analytics - تحليلات سريعة\n"
        
        await update.message.reply_text(status_message)
        
    except Exception as e:
        logger.error(f"خطأ في أمر حالة التقارير المحسن: {e}")
        await update.message.reply_text("❌ حدث خطأ في عرض حالة النظام")

async def fixed_generate_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إنشاء تقرير فوري محسن"""
    try:
        user_id = update.effective_user.id
        
        # التحقق من الصلاحيات
        if not is_admin_user(user_id):
            await update.message.reply_text(
                "❌ عذراً، هذا الأمر متاح للمدراء فقط.\n"
                f"معرف المستخدم: {user_id}"
            )
            return
        
        # رسالة البداية
        await update.message.reply_text("⏳ جاري إنشاء التقرير المحسن...")
        
        # إنشاء التقرير
        try:
            report_generator = FixedWeeklyReportGenerator()
            success = report_generator.generate_and_send_fixed_report()
            
            if success:
                await update.message.reply_text("✅ تم إنشاء وإرسال التقرير المحسن بنجاح")
            else:
                await update.message.reply_text("❌ فشل في إنشاء التقرير المحسن")
                
        except Exception as e:
            logger.error(f"خطأ في إنشاء التقرير المحسن: {e}")
            await update.message.reply_text(f"❌ خطأ في إنشاء التقرير: {str(e)}")
        
    except Exception as e:
        logger.error(f"خطأ في أمر إنشاء التقرير المحسن: {e}")
        await update.message.reply_text("❌ حدث خطأ في إنشاء التقرير")

async def fixed_analytics_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض تحليلات سريعة محسنة"""
    try:
        user_id = update.effective_user.id
        
        # التحقق من الصلاحيات
        if not is_admin_user(user_id):
            await update.message.reply_text(
                "❌ عذراً، هذا الأمر متاح للمدراء فقط.\n"
                f"معرف المستخدم: {user_id}"
            )
            return
        
        await update.message.reply_text("📊 جاري جمع التحليلات السريعة...")
        
        try:
            report_generator = FixedWeeklyReportGenerator()
            
            # تحديد فترة الأسبوع الحالي
            today = datetime.now()
            start_of_week = today - timedelta(days=today.weekday())
            start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_week = today.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            # جمع الإحصائيات
            stats = report_generator.get_comprehensive_stats(start_of_week, end_of_week)
            user_progress = report_generator.get_user_progress_analysis(start_of_week, end_of_week)
            
            # إنشاء رسالة التحليلات
            analytics_message = "📈 التحليلات السريعة (الأسبوع الحالي)\n\n"
            
            analytics_message += "📊 الإحصائيات العامة:\n"
            analytics_message += f"• إجمالي المستخدمين: {stats.get('total_registered_users', 0)}\n"
            analytics_message += f"• النشطين هذا الأسبوع: {stats.get('active_users_this_week', 0)}\n"
            analytics_message += f"• معدل المشاركة: {stats.get('engagement_rate', 0)}%\n"
            analytics_message += f"• إجمالي الاختبارات: {stats.get('total_quizzes_this_week', 0)}\n"
            analytics_message += f"• متوسط الدرجات: {stats.get('avg_percentage_this_week', 0)}%\n"
            
            # تحليل مستويات الأداء
            if user_progress:
                performance_counts = {}
                for user in user_progress:
                    level = user['performance_level']
                    performance_counts[level] = performance_counts.get(level, 0) + 1
                
                analytics_message += f"\n🎯 توزيع مستويات الأداء:\n"
                for level, count in performance_counts.items():
                    analytics_message += f"• {level}: {count} مستخدم\n"
            
            # أفضل المؤدين
            top_performers = [u for u in user_progress if u['performance_level'] == 'ممتاز'][:3]
            if top_performers:
                analytics_message += f"\n🏆 أفضل المؤدين:\n"
                for i, user in enumerate(top_performers, 1):
                    analytics_message += f"{i}. {user['full_name']} ({user['overall_avg_percentage']}%)\n"
            
            await update.message.reply_text(analytics_message)
            
        except Exception as e:
            logger.error(f"خطأ في التحليلات السريعة المحسنة: {e}")
            await update.message.reply_text(f"❌ خطأ في جمع التحليلات: {str(e)}")
        
    except Exception as e:
        logger.error(f"خطأ في أمر التحليلات المحسنة: {e}")
        await update.message.reply_text("❌ حدث خطأ في عرض التحليلات")

def add_fixed_admin_report_commands(application, reporting_system):
    """إضافة أوامر التقارير المحسنة للمدراء"""
    try:
        # إضافة معالجات الأوامر
        application.add_handler(CommandHandler("fixed_status", fixed_report_status_command))
        application.add_handler(CommandHandler("fixed_generate", fixed_generate_report_command))
        application.add_handler(CommandHandler("fixed_analytics", fixed_analytics_command))
        
        logger.info("تم إضافة أوامر التقارير المحسنة للمدراء بنجاح")
        
    except Exception as e:
        logger.error(f"خطأ في إضافة أوامر التقارير المحسنة: {e}")

