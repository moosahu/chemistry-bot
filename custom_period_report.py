# custom_report_admin.py
# إضافة أمر للأدمن لإصدار تقرير حسب مدة محددة

import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

# States للـ ConversationHandler
REPORT_SELECT_PERIOD, REPORT_CUSTOM_DAYS = range(2)

logger = logging.getLogger(__name__)

async def admin_custom_report_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """بدء عملية إصدار تقرير مخصص"""
    query = update.callback_query
    await query.answer()
    
    # التحقق من صلاحيات الأدمن
    user_id = update.effective_user.id
    db_manager = context.bot_data.get("DB_MANAGER")
    
    if not db_manager.is_user_admin(user_id):
        await query.edit_message_text("هذه الأوامر مخصصة للأدمن فقط.")
        return ConversationHandler.END
    
    keyboard = [
        [InlineKeyboardButton("📅 آخر 3 أيام", callback_data="report_period_3")],
        [InlineKeyboardButton("📅 آخر 7 أيام (أسبوع)", callback_data="report_period_7")],
        [InlineKeyboardButton("📅 آخر 14 يوم (أسبوعين)", callback_data="report_period_14")],
        [InlineKeyboardButton("📅 آخر 30 يوم (شهر)", callback_data="report_period_30")],
        [InlineKeyboardButton("✏️ إدخال مدة مخصصة", callback_data="report_period_custom")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="admin_show_tools_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📊 *إصدار تقرير مخصص*\n\n"
        "اختر المدة الزمنية التي تريد إصدار التقرير عنها:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return REPORT_SELECT_PERIOD


async def admin_report_period_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة اختيار المدة المحددة مسبقاً"""
    query = update.callback_query
    await query.answer()
    
    # استخراج عدد الأيام من callback_data
    period_days = int(query.data.replace("report_period_", ""))
    
    # حفظ المدة في context
    context.user_data['report_days'] = period_days
    
    # إرسال رسالة انتظار
    await query.edit_message_text(
        f"⏳ جاري إعداد التقرير لآخر {period_days} يوم...\n"
        "الرجاء الانتظار..."
    )
    
    # إصدار التقرير
    await generate_and_send_custom_report(query, context, period_days)
    
    return ConversationHandler.END


async def admin_report_custom_days_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """طلب إدخال عدد أيام مخصص"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "✏️ *إدخال مدة مخصصة*\n\n"
        "الرجاء إدخال عدد الأيام التي تريد التقرير عنها:\n"
        "(مثال: 5 أو 15 أو 45)\n\n"
        "أرسل /cancel للإلغاء",
        parse_mode='Markdown'
    )
    
    return REPORT_CUSTOM_DAYS


async def admin_report_custom_days_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة عدد الأيام المخصص المدخل"""
    user_text = update.message.text.strip()
    
    # التحقق من أن المدخل رقم
    try:
        days = int(user_text)
        if days <= 0:
            await update.message.reply_text(
                "❌ الرجاء إدخال رقم موجب (أكبر من 0).\n"
                "حاول مرة أخرى أو أرسل /cancel للإلغاء"
            )
            return REPORT_CUSTOM_DAYS
        
        if days > 365:
            await update.message.reply_text(
                "⚠️ المدة المدخلة كبيرة جداً (أكثر من سنة).\n"
                "الرجاء إدخال مدة أقل من 365 يوم.\n"
                "حاول مرة أخرى أو أرسل /cancel للإلغاء"
            )
            return REPORT_CUSTOM_DAYS
            
    except ValueError:
        await update.message.reply_text(
            "❌ المدخل غير صحيح. الرجاء إدخال رقم فقط.\n"
            "مثال: 5 أو 10 أو 30\n\n"
            "حاول مرة أخرى أو أرسل /cancel للإلغاء"
        )
        return REPORT_CUSTOM_DAYS
    
    # حفظ المدة
    context.user_data['report_days'] = days
    
    # إرسال رسالة انتظار
    wait_msg = await update.message.reply_text(
        f"⏳ جاري إعداد التقرير لآخر {days} يوم...\n"
        "الرجاء الانتظار..."
    )
    
    # إصدار التقرير
    await generate_and_send_custom_report(update, context, days, wait_msg)
    
    return ConversationHandler.END


async def generate_and_send_custom_report(update_or_query, context: ContextTypes.DEFAULT_TYPE, days: int, wait_msg=None):
    """توليد وإرسال التقرير المخصص"""
    
    db_manager = context.bot_data.get("DB_MANAGER")
    
    # حساب التواريخ
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    try:
        # الاتصال بقاعدة البيانات مباشرة
        from database.connection import connect_db
        conn = connect_db()
        cursor = conn.cursor()
        
        # جلب إحصائيات الفترة المحددة
        cursor.execute("""
            SELECT 
                u.user_id,
                u.username,
                u.first_name,
                COUNT(qa.id) as total_quizzes,
                ROUND(AVG(qa.score)::numeric, 2) as avg_score,
                MAX(qa.score) as max_score,
                MIN(qa.score) as min_score,
                ROUND(AVG(qa.time_taken)::numeric, 2) as avg_time,
                SUM(CASE WHEN qa.score >= 80 THEN 1 ELSE 0 END) as excellent_count,
                SUM(CASE WHEN qa.score >= 60 AND qa.score < 80 THEN 1 ELSE 0 END) as good_count,
                SUM(CASE WHEN qa.score < 60 THEN 1 ELSE 0 END) as weak_count
            FROM users u
            LEFT JOIN quiz_attempts qa ON u.user_id = qa.user_id 
                AND qa.completed_at >= %s 
                AND qa.completed_at <= %s
                AND qa.status = 'completed'
            GROUP BY u.user_id, u.username, u.first_name
            HAVING COUNT(qa.id) > 0
            ORDER BY total_quizzes DESC, avg_score DESC
        """, (start_date, end_date))
        
        results = cursor.fetchall()
        
        if not results:
            message = (
                f"📊 *تقرير الفترة: آخر {days} يوم*\n"
                f"من {start_date.strftime('%Y-%m-%d')} إلى {end_date.strftime('%Y-%m-%d')}\n\n"
                "❌ لا توجد بيانات لهذه الفترة"
            )
            
            if wait_msg:
                await wait_msg.edit_text(message, parse_mode='Markdown')
            elif isinstance(update_or_query, Update):
                await update_or_query.message.reply_text(message, parse_mode='Markdown')
            else:
                await update_or_query.edit_message_text(message, parse_mode='Markdown')
            
            cursor.close()
            conn.close()
            return
        
        # بناء رسالة التقرير
        report_lines = [
            f"📊 *تقرير الاختبارات - آخر {days} يوم*",
            f"📅 من: {start_date.strftime('%Y-%m-%d')}",
            f"📅 إلى: {end_date.strftime('%Y-%m-%d')}",
            f"👥 عدد الطلاب النشطين: {len(results)}",
            "━━━━━━━━━━━━━━━━━",
            ""
        ]
        
        # إحصائيات عامة
        total_quizzes_all = sum(r[3] for r in results)
        avg_score_all = sum(r[4] for r in results if r[4]) / len([r for r in results if r[4]])
        
        report_lines.extend([
            f"📝 إجمالي الاختبارات: {total_quizzes_all}",
            f"📊 متوسط الدرجات العام: {avg_score_all:.1f}%",
            "",
            "━━━━━━━━━━━━━━━━━",
            "*🏆 أفضل 10 طلاب:*",
            ""
        ])
        
        # عرض أفضل 10 طلاب
        for idx, row in enumerate(results[:10], 1):
            user_id, username, first_name, total_quizzes, avg_score, max_score, min_score, avg_time, excellent, good, weak = row
            
            name = first_name or username or f"User_{user_id}"
            
            # رموز الترتيب
            rank_emoji = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
            
            report_lines.append(
                f"{rank_emoji} *{name}*\n"
                f"   📝 اختبارات: {total_quizzes} | "
                f"📊 معدل: {avg_score or 0:.1f}%\n"
                f"   ⬆️ أعلى: {max_score or 0}% | "
                f"⬇️ أقل: {min_score or 0}%\n"
                f"   ⏱️ متوسط الوقت: {avg_time or 0:.0f} ثانية\n"
            )
        
        # إضافة تفاصيل إضافية
        if len(results) > 10:
            report_lines.extend([
                "",
                f"_... و {len(results) - 10} طالب آخرين_"
            ])
        
        # إحصائيات حسب مستوى الأداء
        total_excellent = sum(r[8] for r in results)
        total_good = sum(r[9] for r in results)
        total_weak = sum(r[10] for r in results)
        
        report_lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━",
            "*📈 توزيع مستويات الأداء:*",
            f"🟢 ممتاز (80%+): {total_excellent} اختبار",
            f"🟡 جيد (60-79%): {total_good} اختبار",
            f"🔴 يحتاج تحسين (<60%): {total_weak} اختبار"
        ])
        
        cursor.close()
        conn.close()
        
        # إرسال التقرير
        report_text = "\n".join(report_lines)
        
        # تقسيم الرسالة إذا كانت طويلة
        if len(report_text) > 4000:
            # إرسال على دفعات
            parts = [report_text[i:i+4000] for i in range(0, len(report_text), 4000)]
            
            if wait_msg:
                await wait_msg.edit_text(parts[0], parse_mode='Markdown')
                for part in parts[1:]:
                    if isinstance(update_or_query, Update):
                        await update_or_query.message.reply_text(part, parse_mode='Markdown')
                    else:
                        await context.bot.send_message(
                            chat_id=update_or_query.message.chat_id,
                            text=part,
                            parse_mode='Markdown'
                        )
            else:
                if isinstance(update_or_query, Update):
                    await update_or_query.message.reply_text(parts[0], parse_mode='Markdown')
                    for part in parts[1:]:
                        await update_or_query.message.reply_text(part, parse_mode='Markdown')
                else:
                    await update_or_query.edit_message_text(parts[0], parse_mode='Markdown')
                    for part in parts[1:]:
                        await context.bot.send_message(
                            chat_id=update_or_query.message.chat_id,
                            text=part,
                            parse_mode='Markdown'
                        )
        else:
            if wait_msg:
                await wait_msg.edit_text(report_text, parse_mode='Markdown')
            elif isinstance(update_or_query, Update):
                await update_or_query.message.reply_text(report_text, parse_mode='Markdown')
            else:
                await update_or_query.edit_message_text(report_text, parse_mode='Markdown')
        
        # إرسال زر العودة لقائمة الأدمن
        keyboard = [[InlineKeyboardButton("⬅️ العودة لأدوات الأدمن", callback_data="admin_show_tools_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if isinstance(update_or_query, Update):
            await update_or_query.message.reply_text(
                "✅ تم إنشاء التقرير بنجاح!",
                reply_markup=reply_markup
            )
        else:
            await context.bot.send_message(
                chat_id=update_or_query.message.chat_id if hasattr(update_or_query, 'message') else update_or_query.from_user.id,
                text="✅ تم إنشاء التقرير بنجاح!",
                reply_markup=reply_markup
            )
            
    except Exception as e:
        logger.error(f"Error generating custom report: {e}", exc_info=True)
        error_msg = f"❌ حدث خطأ أثناء إنشاء التقرير:\n{str(e)}"
        
        if wait_msg:
            await wait_msg.edit_text(error_msg)
        elif isinstance(update_or_query, Update):
            await update_or_query.message.reply_text(error_msg)
        else:
            await update_or_query.edit_message_text(error_msg)


async def cancel_custom_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """إلغاء عملية إصدار التقرير"""
    await update.message.reply_text("تم إلغاء إصدار التقرير.")
    
    # العودة لقائمة أدوات الأدمن
    keyboard = [
        [InlineKeyboardButton("✏️ تعديل رسالة حول البوت", callback_data="admin_edit_specific_msg_about_bot_message")],
        [InlineKeyboardButton("📝 تعديل رسائل أخرى للبوت", callback_data="admin_edit_other_messages_menu")],
        [InlineKeyboardButton("📣 إرسال إشعار عام للمستخدمين", callback_data="admin_broadcast_start")],
        [InlineKeyboardButton("📊 عرض لوحة الإحصائيات", callback_data="stats_admin_panel_v4")],
        [InlineKeyboardButton("📊 إصدار تقرير مخصص", callback_data="admin_custom_report_start")],
        [InlineKeyboardButton("⬅️ عودة إلى القائمة الرئيسية", callback_data="admin_back_to_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text="🛠️ أدوات إدارة البوت:", reply_markup=reply_markup)
    
    return ConversationHandler.END
