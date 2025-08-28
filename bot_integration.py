#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
دمج نظام التقارير الأسبوعية مع البوت
يستخدم نظام الإيميل الموجود في handlers.admin_tools.email_notification
"""

import os
import logging
import glob
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from weekly_report import WeeklyReportGenerator, WeeklyReportScheduler

logger = logging.getLogger(__name__)

def find_database_file():
    """البحث عن ملف قاعدة البيانات تلقائياً"""
    possible_paths = [
        "database/bot_stats.db",
        "bot_stats.db", 
        "database/*.db",
        "*.db"
    ]
    
    for pattern in possible_paths:
        files = glob.glob(pattern)
        if files:
            return files[0]
    
    logger.warning("لم يتم العثور على ملف قاعدة البيانات")
    return None

def setup_reporting_system():
    """إعداد نظام التقارير الأسبوعية"""
    try:
        # البحث عن قاعدة البيانات
        db_path = find_database_file()
        if not db_path:
            logger.error("لم يتم العثور على ملف قاعدة البيانات")
            return None
        
        logger.info(f"تم العثور على قاعدة البيانات: {db_path}")
        
        # إنشاء مولد التقارير (بدون email_config)
        report_generator = WeeklyReportGenerator(db_path)
        
        # إنشاء جدولة التقارير
        scheduler = WeeklyReportScheduler(report_generator)
        
        logger.info("تم إعداد نظام التقارير الأسبوعية بنجاح")
        return scheduler
        
    except Exception as e:
        logger.error(f"خطأ في إعداد نظام التقارير: {e}")
        return None

async def generate_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر إنشاء تقرير فوري"""
    try:
        # التحقق من صلاحيات المدير بطرق متعددة
        user_id = update.effective_user.id
        is_admin = False
        
        # الطريقة الأولى: متغير البيئة
        admin_id = os.getenv("ADMIN_USER_ID")
        if admin_id and str(user_id) == admin_id:
            is_admin = True
        
        # الطريقة الثانية: قاعدة البيانات
        if not is_admin:
            try:
                db_manager = context.bot_data.get("DB_MANAGER")
                if db_manager and hasattr(db_manager, 'is_user_admin'):
                    is_admin = db_manager.is_user_admin(user_id)
            except:
                pass
        
        # الطريقة الثالثة: قائمة المدراء المحددة مسبقاً (أضف معرفك هنا)
        admin_list = [7640355263]  # أضف معرف المستخدم الخاص بك هنا
        if user_id in admin_list:
            is_admin = True
        
        if not is_admin:
            await update.message.reply_text(f"❌ هذا الأمر متاح للمدير فقط\nمعرف المستخدم الخاص بك: {user_id}")
            return
        
        await update.message.reply_text("⏳ جاري إنشاء التقرير...")
        
        # إنشاء التقرير
        db_path = find_database_file()
        if not db_path:
            await update.message.reply_text("❌ لم يتم العثور على قاعدة البيانات")
            return
        
        report_generator = WeeklyReportGenerator(db_path)
        success = report_generator.generate_and_send_weekly_report()
        
        if success:
            await update.message.reply_text("✅ تم إنشاء وإرسال التقرير بنجاح")
        else:
            await update.message.reply_text("❌ فشل في إنشاء التقرير")
            
    except Exception as e:
        logger.error(f"خطأ في أمر إنشاء التقرير: {e}")
        await update.message.reply_text(f"❌ حدث خطأ في إنشاء التقرير: {str(e)}")

async def report_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر عرض حالة نظام التقارير"""
    try:
        # التحقق من صلاحيات المدير بطرق متعددة
        user_id = update.effective_user.id
        is_admin = False
        
        # الطريقة الأولى: متغير البيئة
        admin_id = os.getenv("ADMIN_USER_ID")
        if admin_id and str(user_id) == admin_id:
            is_admin = True
        
        # الطريقة الثانية: قاعدة البيانات
        if not is_admin:
            try:
                db_manager = context.bot_data.get("DB_MANAGER")
                if db_manager and hasattr(db_manager, 'is_user_admin'):
                    is_admin = db_manager.is_user_admin(user_id)
            except:
                pass
        
        # الطريقة الثالثة: قائمة المدراء المحددة مسبقاً (أضف معرفك هنا)
        admin_list = [7640355263]  # أضف معرف المستخدم الخاص بك هنا
        if user_id in admin_list:
            is_admin = True
        
        if not is_admin:
            await update.message.reply_text(f"❌ هذا الأمر متاح للمدير فقط\nمعرف المستخدم الخاص بك: {user_id}")
            return
        
        # فحص حالة النظام
        from weekly_report import is_email_configured
        
        status_msg = "📊 حالة نظام التقارير الأسبوعية\n\n"
        
        # فحص قاعدة البيانات
        db_path = find_database_file()
        if db_path:
            status_msg += f"✅ قاعدة البيانات: {db_path}\n"
        else:
            status_msg += "❌ قاعدة البيانات: غير موجودة\n"
        
        # فحص إعدادات الإيميل
        if is_email_configured():
            status_msg += "✅ إعدادات الإيميل: مكونة بشكل صحيح\n"
        else:
            status_msg += "❌ إعدادات الإيميل: غير مكونة\n"
        
        # معلومات المدير
        status_msg += f"\n👤 معلومات المدير:\n"
        status_msg += f"• معرف المستخدم: {user_id}\n"
        status_msg += f"• حالة الصلاحية: {'✅ مدير' if is_admin else '❌ غير مدير'}\n"
        
        # معلومات الجدولة
        status_msg += "\n📅 جدولة التقارير:\n"
        status_msg += "• التوقيت: كل يوم أحد الساعة 9:00 صباحاً\n"
        status_msg += "• المحتوى: إحصائيات الأسبوع الماضي\n"
        
        # الأوامر المتاحة
        status_msg += "\n🔧 الأوامر المتاحة:\n"
        status_msg += "• /generate_report - إنشاء تقرير فوري\n"
        status_msg += "• /report_status - عرض هذه الحالة\n"
        
        await update.message.reply_text(status_msg)
        
    except Exception as e:
        logger.error(f"خطأ في أمر حالة التقارير: {e}")
        await update.message.reply_text(f"❌ حدث خطأ في عرض حالة النظام: {str(e)}")

def add_admin_report_commands(application, reporting_system):
    """إضافة أوامر التقارير للبوت"""
    try:
        # إضافة أوامر المدير
        application.add_handler(CommandHandler("generate_report", generate_report_command))
        application.add_handler(CommandHandler("report_status", report_status_command))
        
        logger.info("تم إضافة أوامر التقارير الإدارية بنجاح")
        
    except Exception as e:
        logger.error(f"خطأ في إضافة أوامر التقارير: {e}")

