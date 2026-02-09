#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
نظام التقارير حسب فترة مخصصة مع دعم فلتر طلابي
يسمح للأدمن باختيار:
1. لمن التقرير (الكل / طلابي / طلابي في صف)
2. الفترة الزمنية
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
SELECT_TARGET, SELECT_MY_GRADE, SELECT_PERIOD, ENTER_CUSTOM_DAYS = range(4)


def is_admin_user(user_id: int, context: ContextTypes.DEFAULT_TYPE = None) -> bool:
    """التحقق من صلاحيات المدير باستخدام DB_MANAGER"""
    try:
        if context and context.bot_data.get("DB_MANAGER"):
            db_manager = context.bot_data.get("DB_MANAGER")
            if hasattr(db_manager, 'is_user_admin'):
                return db_manager.is_user_admin(user_id)
        
        admin_ids = [6448526509, 7640355263]
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


# ============================================================
#  الخطوة 1: لمن التقرير؟
# ============================================================
async def custom_report_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """بدء عملية إنشاء تقرير مخصص — اختيار الهدف"""
    user_id = update.effective_user.id
    
    if not is_admin_user(user_id, context):
        logger.warning(f"User {user_id} attempted to use custom_report without admin privileges")
        msg = f"❌ عذراً، هذا الأمر متاح للمدراء فقط.\nمعرف المستخدم: {user_id}"
        if update.callback_query:
            await update.callback_query.answer("هذا الأمر متاح للمدراء فقط")
            await update.callback_query.message.reply_text(msg)
        else:
            await update.message.reply_text(msg)
        return ConversationHandler.END
    
    # تنظيف بيانات سابقة
    context.user_data.pop('report_user_filter', None)
    context.user_data.pop('report_days', None)
    context.user_data.pop('report_target_label', None)
    
    # جلب عدد طلابي
    my_students_count = 0
    try:
        gen = FinalWeeklyReportGenerator()
        with gen.engine.connect() as conn:
            from sqlalchemy import text
            r = conn.execute(text("SELECT COUNT(*) FROM users WHERE COALESCE(is_my_student, FALSE) = TRUE")).fetchone()
            my_students_count = r[0] if r else 0
    except Exception:
        pass
    
    keyboard = [
        [InlineKeyboardButton("👥 تقرير لجميع الطلاب", callback_data="rpt_target_all")],
        [InlineKeyboardButton(f"⭐ تقرير لطلابي فقط ({my_students_count})", callback_data="rpt_target_my")],
        [InlineKeyboardButton("⭐🎓 تقرير لطلابي حسب الصف", callback_data="rpt_target_my_grade")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="period_cancel")]
    ]
    
    message_text = (
        "📊 إنشاء تقرير مخصص\n\n"
        "الخطوة 1/2: لمن التقرير؟\n\n"
        "اختر نطاق التقرير:"
    )
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text=message_text, reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            text=message_text, reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    return SELECT_TARGET


async def target_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة اختيار الهدف"""
    query = update.callback_query
    await query.answer()
    
    target = query.data
    
    if target == "rpt_target_all":
        context.user_data['report_user_filter'] = None
        return await _show_period_selection(query, context, "جميع الطلاب")
    
    elif target == "rpt_target_my":
        context.user_data['report_user_filter'] = {'my_students': True}
        return await _show_period_selection(query, context, "⭐ طلابي فقط")
    
    elif target == "rpt_target_my_grade":
        return await _show_grade_selection(query, context)
    
    return ConversationHandler.END


async def _show_grade_selection(query, context) -> int:
    """عرض الصفوف لاختيار صف طلابي"""
    grades_info = []
    try:
        gen = FinalWeeklyReportGenerator()
        with gen.engine.connect() as conn:
            from sqlalchemy import text
            rows = conn.execute(text("""
                SELECT grade, COUNT(*) as cnt 
                FROM users 
                WHERE COALESCE(is_my_student, FALSE) = TRUE AND grade IS NOT NULL
                GROUP BY grade ORDER BY grade
            """)).fetchall()
            grades_info = [(r[0], r[1]) for r in rows]
    except Exception as e:
        logger.error(f"Error fetching grades: {e}")
    
    if not grades_info:
        await query.edit_message_text(
            "❌ لا يوجد طلاب مميزين في أي صف.\n"
            "استخدم ⭐ طلابي في لوحة الأدمن لتمييز طلابك أولاً."
        )
        return ConversationHandler.END
    
    keyboard = []
    for grade, count in grades_info:
        keyboard.append([InlineKeyboardButton(
            f"⭐ {grade} ({count} طالب)",
            callback_data=f"rpt_grade_{grade}"
        )])
    keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="period_cancel")])
    
    await query.edit_message_text(
        "📊 إنشاء تقرير مخصص\n\n"
        "اختر الصف:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SELECT_MY_GRADE


async def grade_for_report_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """بعد اختيار الصف"""
    query = update.callback_query
    await query.answer()
    
    grade = query.data.replace("rpt_grade_", "")
    context.user_data['report_user_filter'] = {'my_students': True, 'grade': grade}
    
    return await _show_period_selection(query, context, f"⭐ طلابي في {grade}")


# ============================================================
#  الخطوة 2: اختيار الفترة
# ============================================================
async def _show_period_selection(query, context, target_label) -> int:
    """عرض خيارات الفترة الزمنية"""
    context.user_data['report_target_label'] = target_label
    
    keyboard = [
        [InlineKeyboardButton("📅 آخر 3 أيام", callback_data="period_3")],
        [InlineKeyboardButton("📅 آخر 7 أيام (أسبوع)", callback_data="period_7")],
        [InlineKeyboardButton("📅 آخر 14 يوم (أسبوعين)", callback_data="period_14")],
        [InlineKeyboardButton("📅 آخر 30 يوم (شهر)", callback_data="period_30")],
        [InlineKeyboardButton("✏️ إدخال فترة مخصصة", callback_data="period_custom")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="period_cancel")]
    ]
    
    await query.edit_message_text(
        f"📊 إنشاء تقرير مخصص\n\n"
        f"🎯 النطاق: {target_label}\n\n"
        f"الخطوة 2/2: اختر الفترة الزمنية:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SELECT_PERIOD


async def period_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة اختيار الفترة المحددة"""
    query = update.callback_query
    await query.answer()
    
    period_days = int(query.data.replace("period_", ""))
    context.user_data['report_days'] = period_days
    
    target_label = context.user_data.get('report_target_label', 'جميع الطلاب')
    await query.edit_message_text(
        f"⏳ جاري إنشاء التقرير...\n\n"
        f"🎯 النطاق: {target_label}\n"
        f"📅 الفترة: آخر {period_days} يوم\n\n"
        f"هذا قد يستغرق بضع ثوانٍ..."
    )
    
    await generate_custom_report(query, context, period_days)
    return ConversationHandler.END


async def request_custom_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """طلب إدخال عدد الأيام المخصص"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "✏️ إدخال فترة مخصصة\n\n"
        "الرجاء إدخال عدد الأيام:\n"
        "(مثال: 5 أو 15 أو 45 أو 90)\n\n"
        "💡 الحد الأقصى: 365 يوم\n\n"
        "أرسل /cancel للإلغاء"
    )
    return ENTER_CUSTOM_DAYS


async def custom_days_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة عدد الأيام المدخل"""
    user_text = update.message.text.strip()
    
    try:
        days = int(user_text)
        
        if days <= 0:
            await update.message.reply_text(
                "❌ الرجاء إدخال رقم موجب.\n"
                "حاول مرة أخرى أو أرسل /cancel للإلغاء"
            )
            return ENTER_CUSTOM_DAYS
        
        if days > 365:
            await update.message.reply_text(
                "⚠️ المدة كبيرة جداً.\n"
                "الرجاء إدخال مدة أقل من 365 يوم.\n"
                "حاول مرة أخرى أو أرسل /cancel للإلغاء"
            )
            return ENTER_CUSTOM_DAYS
            
    except ValueError:
        await update.message.reply_text(
            "❌ الرجاء إدخال رقم فقط.\n"
            "مثال: 5 أو 10 أو 30\n\n"
            "حاول مرة أخرى أو أرسل /cancel للإلغاء"
        )
        return ENTER_CUSTOM_DAYS
    
    context.user_data['report_days'] = days
    target_label = context.user_data.get('report_target_label', 'جميع الطلاب')
    
    wait_msg = await update.message.reply_text(
        f"⏳ جاري إنشاء التقرير...\n\n"
        f"🎯 النطاق: {target_label}\n"
        f"📅 الفترة: آخر {days} يوم\n\n"
        f"هذا قد يستغرق بضع ثوانٍ..."
    )
    
    await generate_custom_report(update, context, days, wait_msg)
    return ConversationHandler.END


# ============================================================
#  إنشاء التقرير
# ============================================================
async def generate_custom_report(update_or_query, context: ContextTypes.DEFAULT_TYPE, days: int, wait_msg=None):
    """إنشاء التقرير المخصص (مع أو بدون فلتر)"""
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        user_filter = context.user_data.get('report_user_filter')
        target_label = context.user_data.get('report_target_label', 'جميع الطلاب')
        
        logger.info(f"إنشاء تقرير: {target_label} | الفترة: {start_date.date()} إلى {end_date.date()}")
        
        report_generator = FinalWeeklyReportGenerator()
        
        # اختيار نوع التقرير
        if user_filter and user_filter.get('my_students'):
            report_path = report_generator.create_filtered_excel_report(start_date, end_date, user_filter)
        else:
            report_path = report_generator.create_final_excel_report(start_date, end_date)
        
        success_message = (
            f"✅ تم إنشاء التقرير بنجاح\n\n"
            f"🎯 النطاق: {target_label}\n"
            f"📅 الفترة: {start_date.strftime('%Y-%m-%d')} إلى {end_date.strftime('%Y-%m-%d')}\n"
            f"📊 المدة: {days} يوم\n\n"
            f"جاري إرسال التقرير..."
        )
        
        if wait_msg:
            await wait_msg.edit_text(success_message)
        elif isinstance(update_or_query, Update):
            await update_or_query.message.reply_text(success_message)
        else:
            await update_or_query.edit_message_text(success_message)
        
        # إرسال الملف
        if os.path.exists(report_path):
            chat_id = None
            if isinstance(update_or_query, Update):
                chat_id = update_or_query.effective_chat.id
            else:
                chat_id = update_or_query.message.chat_id
            
            caption = (
                f"📊 تقرير: {target_label} — آخر {days} يوم\n"
                f"من {start_date.strftime('%Y-%m-%d')} إلى {end_date.strftime('%Y-%m-%d')}\n\n"
                f"يحتوي على: ملخص تنفيذي، تحليل الطلاب، مقارنة الأداء، توصيات"
            )
            
            with open(report_path, 'rb') as report_file:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=report_file,
                    filename=os.path.basename(report_path),
                    caption=caption
                )
            
            logger.info(f"تم إرسال التقرير بنجاح: {report_path}")
        else:
            error_msg = "❌ لم يتم العثور على ملف التقرير"
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
    context.user_data.pop('report_user_filter', None)
    context.user_data.pop('report_days', None)
    context.user_data.pop('report_target_label', None)
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("تم إلغاء إنشاء التقرير.")
    else:
        await update.message.reply_text("تم إلغاء إنشاء التقرير.")
    
    return ConversationHandler.END


# ============================================================
#  ConversationHandler
# ============================================================
custom_report_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler("custom_report", custom_report_start),
        CallbackQueryHandler(custom_report_start, pattern="^custom_report_start$")
    ],
    states={
        SELECT_TARGET: [
            CallbackQueryHandler(target_selected, pattern="^rpt_target_"),
            CallbackQueryHandler(cancel_report, pattern="^period_cancel$")
        ],
        SELECT_MY_GRADE: [
            CallbackQueryHandler(grade_for_report_selected, pattern="^rpt_grade_"),
            CallbackQueryHandler(cancel_report, pattern="^period_cancel$")
        ],
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
