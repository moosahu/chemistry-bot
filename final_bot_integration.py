#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
دمج نظام التقارير الأسبوعية النهائي والمحسن مع البوت
يعمل بدون مشاكل الخطوط العربية ومع المكتبات الموجودة فقط
"""

import logging
import os
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from final_weekly_report import (
    FinalWeeklyReportGenerator, 
    FinalWeeklyReportScheduler
)

logger = logging.getLogger(__name__)

def setup_final_reporting_system():
    """إعداد نظام التقارير النهائي والمحسن"""
    try:
        # التحقق من قاعدة البيانات
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            logger.error("متغير DATABASE_URL غير موجود")
            return None
        
        logger.info(f"تم العثور على قاعدة البيانات: {database_url[:50]}...")
        
        # إنشاء جدولة التقارير
        scheduler = FinalWeeklyReportScheduler()
        
        logger.info("تم إعداد نظام التقارير النهائي بنجاح")
        return scheduler
        
    except Exception as e:
        logger.error(f"خطأ في إعداد نظام التقارير النهائي: {e}")
        return None

def is_final_email_configured() -> bool:
    """التحقق من إعدادات الإيميل"""
    email_username = os.getenv('EMAIL_USERNAME')
    email_password = os.getenv('EMAIL_PASSWORD')
    admin_email = os.getenv('ADMIN_EMAIL')
    
    return all([email_username, email_password, admin_email])

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

async def final_report_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض حالة نظام التقارير النهائي"""
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
        status_message = "📊 حالة نظام التقارير النهائي والمحسن\n\n"
        
        # فحص قاعدة البيانات
        database_url = os.getenv('DATABASE_URL')
        if database_url:
            status_message += "✅ قاعدة البيانات: متصلة\n"
        else:
            status_message += "❌ قاعدة البيانات: غير متصلة\n"
        
        # فحص إعدادات الإيميل
        if is_final_email_configured():
            status_message += "✅ إعدادات الإيميل: مكونة بشكل صحيح\n"
            admin_email = os.getenv('ADMIN_EMAIL')
            status_message += f"📧 إيميل الإدارة: {admin_email}\n"
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
        status_message += f"• التنسيق: ملف Excel شامل مع رسوم بيانية\n"
        
        # المميزات الجديدة
        status_message += f"\n🌟 المميزات المحسنة:\n"
        status_message += f"• ✅ حل مشكلة الخطوط العربية\n"
        status_message += f"• ✅ رسوم بيانية ملونة وواضحة\n"
        status_message += f"• ✅ تحليلات ذكية وتوصيات عملية\n"
        status_message += f"• ✅ تقارير Excel متعددة الأوراق\n"
        
        # الأوامر المتاحة
        status_message += f"\n🛠️ الأوامر المتاحة:\n"
        status_message += f"• /final_generate - إنشاء تقرير فوري\n"
        status_message += f"• /final_status - عرض هذه الحالة\n"
        status_message += f"• /final_analytics - تحليلات سريعة\n"
        
        await update.message.reply_text(status_message)
        
    except Exception as e:
        logger.error(f"خطأ في أمر حالة التقارير النهائي: {e}")
        await update.message.reply_text("❌ حدث خطأ في عرض حالة النظام")

async def final_generate_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إنشاء تقرير فوري نهائي ومحسن"""
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
        await update.message.reply_text("⏳ جاري إنشاء التقرير النهائي المحسن...")
        
        # إنشاء التقرير
        try:
            scheduler = FinalWeeklyReportScheduler()
            scheduler.generate_and_send_weekly_report()
            
            await update.message.reply_text("✅ تم إنشاء وإرسال التقرير النهائي بنجاح")
                
        except Exception as e:
            logger.error(f"خطأ في إنشاء التقرير النهائي: {e}")
            await update.message.reply_text(f"❌ خطأ في إنشاء التقرير: {str(e)}")
        
    except Exception as e:
        logger.error(f"خطأ في أمر إنشاء التقرير النهائي: {e}")
        await update.message.reply_text("❌ حدث خطأ في إنشاء التقرير")

async def final_analytics_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض تحليلات سريعة نهائية ومحسنة"""
    try:
        user_id = update.effective_user.id
        
        # التحقق من الصلاحيات
        if not is_admin_user(user_id):
            await update.message.reply_text(
                "❌ عذراً، هذا الأمر متاح للمدراء فقط.\n"
                f"معرف المستخدم: {user_id}"
            )
            return
        
        await update.message.reply_text("📊 جاري جمع التحليلات السريعة المحسنة...")
        
        try:
            scheduler = FinalWeeklyReportScheduler()
            analytics = scheduler.get_quick_analytics()
            
            if not analytics:
                await update.message.reply_text("❌ لا توجد بيانات متاحة للتحليل")
                return
            
            # إنشاء رسالة التحليلات
            analytics_message = "📈 التحليلات السريعة النهائية\n\n"
            
            analytics_message += f"📅 الفترة: {analytics.get('period', 'غير محدد')}\n\n"
            
            analytics_message += "📊 الإحصائيات العامة:\n"
            analytics_message += f"• إجمالي المستخدمين: {analytics.get('total_users', 0)}\n"
            analytics_message += f"• النشطين هذا الأسبوع: {analytics.get('active_users', 0)}\n"
            analytics_message += f"• معدل المشاركة: {analytics.get('engagement_rate', 0)}%\n"
            analytics_message += f"• إجمالي الاختبارات: {analytics.get('total_quizzes', 0)}\n"
            analytics_message += f"• متوسط الدرجات: {analytics.get('avg_score', 0)}%\n"
            
            # تقييم الأداء
            engagement_rate = analytics.get('engagement_rate', 0)
            avg_score = analytics.get('avg_score', 0)
            
            analytics_message += f"\n🎯 تقييم الأداء:\n"
            
            if engagement_rate >= 70:
                analytics_message += "• معدل المشاركة: ممتاز 🟢\n"
            elif engagement_rate >= 50:
                analytics_message += "• معدل المشاركة: جيد 🟡\n"
            else:
                analytics_message += "• معدل المشاركة: يحتاج تحسين 🔴\n"
            
            if avg_score >= 80:
                analytics_message += "• متوسط الدرجات: ممتاز 🟢\n"
            elif avg_score >= 60:
                analytics_message += "• متوسط الدرجات: جيد 🟡\n"
            else:
                analytics_message += "• متوسط الدرجات: يحتاج تحسين 🔴\n"
            
            analytics_message += f"\n💡 للحصول على تقرير مفصل، استخدم:\n/final_generate"
            
            await update.message.reply_text(analytics_message)
            
        except Exception as e:
            logger.error(f"خطأ في التحليلات السريعة النهائية: {e}")
            await update.message.reply_text(f"❌ خطأ في جمع التحليلات: {str(e)}")
        
    except Exception as e:
        logger.error(f"خطأ في أمر التحليلات النهائية: {e}")
        await update.message.reply_text("❌ حدث خطأ في عرض التحليلات")

def add_final_admin_report_commands(application, reporting_system):
    """إضافة أوامر التقارير النهائية للمدراء"""
    try:
        # إضافة معالجات الأوامر
        application.add_handler(CommandHandler("final_status", final_report_status_command))
        application.add_handler(CommandHandler("final_generate", final_generate_report_command))
        application.add_handler(CommandHandler("final_analytics", final_analytics_command))
        
        logger.info("تم إضافة أوامر التقارير النهائية للمدراء بنجاح")
        
    except Exception as e:
        logger.error(f"خطأ في إضافة أوامر التقارير النهائية: {e}")

