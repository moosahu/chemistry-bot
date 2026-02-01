#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
نظام التقارير حسب فترة مخصصة - نسخة من final_weekly_report.py
يسمح للأدمن باختيار الفترة الزمنية للتقرير
"""

import os
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, 
    ConversationHandler, 
    CommandHandler, 
    CallbackQueryHandler,
    MessageHandler,
    filters
)
from final_weekly_report import FinalWeeklyReportGenerator

logger = logging.getLogger(__name__)

# States للـ ConversationHandler
SELECT_PERIOD, ENTER_CUSTOM_DAYS = range(2)

def is_admin_user(user_id: int, context: ContextTypes.DEFAULT_TYPE = None) -> bool:
    """التحقق من صلاحيات المدير باستخدام DB_MANAGER"""
    try:
        # محاولة استخدام DB_MANAGER من context
        if context and context.bot_data.get("DB_MANAGER"):
            db_manager = context.bot_data.get("DB_MANAGER")
            if hasattr(db_manager, 'is_user_admin'):
                return db_manager.is_user_admin(user_id)
        
        # Fallback: قائمة المدراء المحددة مسبقاً
        admin_ids = [6448526509, 7640355263]
        
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


async def custom_report_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """بدء عملية إنشاء تقرير مخصص"""
    user_id = update.effective_user.id
    
    # التحقق من الصلاحيات
    if not is_admin_user(user_id, context):
        logger.warning(f"User {user_id} attempted to use custom_report without admin privileges")
        if update.callback_query:
            await update.callback_query.answer("هذا الأمر متاح للمدراء فقط")
            await update.callback_query.message.reply_text(
                f"❌ عذراً، هذا الأمر متاح للمدراء فقط.\nمعرف المستخدم: {user_id}"
            )
        else:
            await update.message.reply_text(
                f"❌ عذراً، هذا الأمر متاح للمدراء فقط.\nمعرف المستخدم: {user_id}"
            )
        return ConversationHandler.END
    
    keyboard = [
        [InlineKeyboardButton("📅 آخر 3 أيام", callback_data="period_3")],
        [InlineKeyboardButton("📅 آخر 7 أيام (أسبوع)", callback_data="period_7")],
        [InlineKeyboardButton("📅 آخر 14 يوم (أسبوعين)", callback_data="period_14")],
        [InlineKeyboardButton("📅 آخر 30 يوم (شهر)", callback_data="period_30")],
        [InlineKeyboardButton("✏️ إدخال فترة مخصصة", callback_data="period_custom")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="period_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = (
        "📊 *إنشاء تقرير مخصص*\n\n"
        "اختر الفترة الزمنية التي تريد التقرير عنها:\n\n"
        "💡 التقرير سيتضمن:\n"
        "• إحصائيات شاملة للطلاب\n"
        "• تحليل الأداء والدرجات\n"
        "• الاختبارات الأكثر صعوبة\n"
        "• رسوم بيانية تفصيلية\n"
        "• توصيات ذكية للتحسين"
    )
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text=message_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text=message_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    return SELECT_PERIOD


async def period_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة اختيار الفترة المحددة"""
    query = update.callback_query
    await query.answer()
    
    # استخراج عدد الأيام
    period_days = int(query.data.replace("period_", ""))
    
    # حفظ في context
    context.user_data['report_days'] = period_days
    
    # رسالة انتظار
    await query.edit_message_text(
        f"⏳ جاري إنشاء التقرير المخصص لآخر {period_days} يوم...\n\n"
        "هذا قد يستغرق بضع ثوانٍ، الرجاء الانتظار..."
    )
    
    # إنشاء التقرير
    await generate_custom_report(query, context, period_days)
    
    return ConversationHandler.END


async def request_custom_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """طلب إدخال عدد الأيام المخصص"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "✏️ *إدخال فترة مخصصة*\n\n"
        "الرجاء إدخال عدد الأيام التي تريد التقرير عنها:\n"
        "(مثال: 5 أو 15 أو 45 أو 90)\n\n"
        "💡 الحد الأقصى: 365 يوم\n\n"
        "أرسل /cancel للإلغاء",
        parse_mode='Markdown'
    )
    
    return ENTER_CUSTOM_DAYS


async def custom_days_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة عدد الأيام المدخل"""
    user_text = update.message.text.strip()
    
    try:
        days = int(user_text)
        
        if days <= 0:
            await update.message.reply_text(
                "❌ الرجاء إدخال رقم موجب (أكبر من 0).\n"
                "حاول مرة أخرى أو أرسل /cancel للإلغاء"
            )
            return ENTER_CUSTOM_DAYS
        
        if days > 365:
            await update.message.reply_text(
                "⚠️ المدة المدخلة كبيرة جداً (أكثر من سنة).\n"
                "الرجاء إدخال مدة أقل من 365 يوم.\n"
                "حاول مرة أخرى أو أرسل /cancel للإلغاء"
            )
            return ENTER_CUSTOM_DAYS
            
    except ValueError:
        await update.message.reply_text(
            "❌ المدخل غير صحيح. الرجاء إدخال رقم فقط.\n"
            "مثال: 5 أو 10 أو 30\n\n"
            "حاول مرة أخرى أو أرسل /cancel للإلغاء"
        )
        return ENTER_CUSTOM_DAYS
    
    # حفظ المدة
    context.user_data['report_days'] = days
    
    # رسالة انتظار
    wait_msg = await update.message.reply_text(
        f"⏳ جاري إنشاء التقرير المخصص لآخر {days} يوم...\n\n"
        "هذا قد يستغرق بضع ثوانٍ، الرجاء الانتظار..."
    )
    
    # إنشاء التقرير
    await generate_custom_report(update, context, days, wait_msg)
    
    return ConversationHandler.END


async def generate_custom_report(update_or_query, context: ContextTypes.DEFAULT_TYPE, days: int, wait_msg=None):
    """إنشاء التقرير المخصص"""
    try:
        # حساب التواريخ
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        logger.info(f"إنشاء تقرير مخصص للفترة: {start_date} إلى {end_date}")
        
        # إنشاء مولد التقارير
        report_generator = FinalWeeklyReportGenerator()
        
        # إنشاء التقرير
        report_path = report_generator.create_final_excel_report(start_date, end_date)
        
        # رسالة النجاح
        success_message = (
            f"✅ *تم إنشاء التقرير بنجاح!*\n\n"
            f"📅 الفترة: {start_date.strftime('%Y-%m-%d')} إلى {end_date.strftime('%Y-%m-%d')}\n"
            f"📊 المدة: {days} يوم\n"
            f"📁 الملف: {os.path.basename(report_path)}\n\n"
            f"جاري إرسال التقرير..."
        )
        
        if wait_msg:
            await wait_msg.edit_text(success_message, parse_mode='Markdown')
        elif isinstance(update_or_query, Update):
            await update_or_query.message.reply_text(success_message, parse_mode='Markdown')
        else:
            await update_or_query.edit_message_text(success_message, parse_mode='Markdown')
        
        # إرسال الملف
        if os.path.exists(report_path):
            chat_id = None
            if isinstance(update_or_query, Update):
                chat_id = update_or_query.effective_chat.id
            else:
                chat_id = update_or_query.message.chat_id
            
            caption = (
                f"📊 التقرير المخصص - آخر {days} يوم\n"
                f"من {start_date.strftime('%Y-%m-%d')} إلى {end_date.strftime('%Y-%m-%d')}\n\n"
                f"يحتوي التقرير على:\n"
                f"• ملخص تنفيذي\n"
                f"• تحليل تقدم الطلاب\n"
                f"• مقارنة الأداء حسب المستوى\n"
                f"• الأسئلة الصعبة\n"
                f"• أنماط النشاط\n"
                f"• رسوم بيانية تفصيلية\n"
                f"• توصيات ذكية"
            )
            
            with open(report_path, 'rb') as report_file:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=report_file,
                    filename=os.path.basename(report_path),
                    caption=caption
                )
            
            logger.info(f"تم إرسال التقرير المخصص بنجاح: {report_path}")
        else:
            error_msg = "❌ حدث خطأ: لم يتم العثور على ملف التقرير"
            if wait_msg:
                await wait_msg.edit_text(error_msg)
            elif isinstance(update_or_query, Update):
                await update_or_query.message.reply_text(error_msg)
            else:
                await update_or_query.edit_message_text(error_msg)
        
    except Exception as e:
        logger.error(f"خطأ في إنشاء التقرير المخصص: {e}", exc_info=True)
        
        error_message = f"❌ حدث خطأ أثناء إنشاء التقرير:\n{str(e)}"
        
        if wait_msg:
            await wait_msg.edit_text(error_message)
        elif isinstance(update_or_query, Update):
            await update_or_query.message.reply_text(error_message)
        else:
            await update_or_query.edit_message_text(error_message)


async def cancel_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """إلغاء عملية إنشاء التقرير"""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("تم إلغاء إنشاء التقرير.")
    else:
        await update.message.reply_text("تم إلغاء إنشاء التقرير.")
    
    return ConversationHandler.END


# ConversationHandler للتقرير المخصص
custom_report_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler("custom_report", custom_report_start),
        CallbackQueryHandler(custom_report_start, pattern="^custom_report_start$")
    ],
    states={
        SELECT_PERIOD: [
            CallbackQueryHandler(period_selected, pattern="^period_[0-9]+$"),
            CallbackQueryHandler(request_custom_days, pattern="^period_custom$"),
            CallbackQueryHandler(cancel_report, pattern="^period_cancel$")
        ],
        ENTER_CUSTOM_DAYS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, custom_days_received)
        ]
    },
    fallbacks=[
        CommandHandler("cancel", cancel_report),
        CallbackQueryHandler(cancel_report, pattern="^period_cancel$")
    ],
    per_message=False,
    name="custom_report_conversation"
)
