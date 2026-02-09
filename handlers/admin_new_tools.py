#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
لوحة تحكم الأدمن المحسنة
- قائمة أزرار موحدة لكل الأدوات
- ملخص سريع فوري
- بحث عن طالب
- إشعار حسب الصف
- تعديل الرسائل
- إشعار عام (مع فلتر المسجلين فقط)
"""

import logging
import asyncio
import os
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

try:
    from database.connection import connect_db
except ImportError:
    def connect_db():
        logging.error("CRITICAL: connect_db could not be imported")
        return None

logger = logging.getLogger(__name__)

# === States (الأرقام القديمة محفوظة + الجديدة) ===
EDIT_MESSAGE_TEXT = 0
BROADCAST_MESSAGE_TEXT = 1
BROADCAST_CONFIRM = 2
SEARCH_STUDENT_INPUT = 3
BROADCAST_GRADE_SELECT = 4


# ============================================================
#  قائمة أدوات الأدمن الموحدة
# ============================================================
def get_admin_menu_keyboard():
    """إنشاء لوحة أزرار الأدمن الموحدة"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 ملخص سريع", callback_data="admin_quick_summary")],
        [InlineKeyboardButton("🔍 بحث عن طالب", callback_data="admin_search_student")],
        [InlineKeyboardButton("📈 لوحة الإحصائيات", callback_data="stats_admin_panel_v4")],
        [InlineKeyboardButton("📁 تصدير المسجلين Excel", callback_data="admin_export_users")],
        [InlineKeyboardButton("📋 تقرير مخصص", callback_data="custom_report_start")],
        [InlineKeyboardButton("📣 إرسال إشعار", callback_data="admin_broadcast_menu")],
        [InlineKeyboardButton("✏️ تعديل رسائل البوت", callback_data="admin_edit_messages_menu")],
        [InlineKeyboardButton("⬅️ القائمة الرئيسية", callback_data="admin_back_to_start")],
    ])


# ============================================================
#  فحص صلاحيات الأدمن
# ============================================================
async def check_admin_privileges(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager or not db_manager.is_user_admin(user_id):
        if update.message:
            await update.message.reply_text("هذه الأوامر مخصصة للأدمن فقط.")
        if update.callback_query:
            await update.callback_query.answer("هذه الأوامر مخصصة للأدمن فقط.", show_alert=True)
        return False
    return True


# ============================================================
#  أوامر أساسية (start, about, help)
# ============================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    db_manager = context.bot_data.get("DB_MANAGER")

    if db_manager is None:
        await update.message.reply_text("عذراً، مكون قاعدة البيانات غير جاهز حالياً.")
        return

    welcome_message_key = "welcome_new_user"
    try:
        welcome_text = db_manager.get_system_message(welcome_message_key) or f"مرحباً بك يا {user.first_name}!"
    except Exception:
        welcome_text = f"مرحباً بك يا {user.first_name}!"

    welcome_text = welcome_text.replace("{user.first_name}", user.first_name or "مستخدمنا العزيز")

    keyboard = [
        [InlineKeyboardButton("🧠 بدء اختبار جديد", callback_data="start_quiz")],
        [InlineKeyboardButton("📚 معلومات كيميائية", callback_data="chemical_info")],
        [InlineKeyboardButton("📊 إحصائياتي ولوحة الصدارة", callback_data="my_stats_leaderboard")],
        [InlineKeyboardButton("ℹ️ حول البوت", callback_data="about_bot")],
    ]

    try:
        if db_manager.is_user_admin(user_id):
            keyboard.append([InlineKeyboardButton("⚙️ لوحة تحكم الأدمن", callback_data="admin_show_tools_menu")])
    except Exception:
        pass

    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard))


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    about_text = context.bot_data.get("DB_MANAGER").get_system_message("about_bot_message") or "انا بوت كيمياء تحصيلي لمساعدتك."
    await update.message.reply_text(about_text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = context.bot_data.get("DB_MANAGER").get_system_message("help_command_message") or "استخدم الأزرار للتفاعل معي."
    await update.message.reply_text(help_text)


# ============================================================
#  1. لوحة تحكم الأدمن الموحدة
# ============================================================
async def admin_show_tools_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return
    await query.edit_message_text(text="🛠️ لوحة تحكم الأدمن:", reply_markup=get_admin_menu_keyboard())


async def admin_back_to_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    db_manager = context.bot_data.get("DB_MANAGER")

    welcome_text = "مرحباً بك!"
    try:
        welcome_text = db_manager.get_system_message("welcome_new_user") or f"مرحباً بك يا {user.first_name}!"
        welcome_text = welcome_text.replace("{user.first_name}", user.first_name or "مستخدمنا العزيز")
    except Exception:
        pass

    keyboard = [
        [InlineKeyboardButton("🧠 بدء اختبار جديد", callback_data="start_quiz")],
        [InlineKeyboardButton("📚 معلومات كيميائية", callback_data="chemical_info")],
        [InlineKeyboardButton("📊 إحصائياتي ولوحة الصدارة", callback_data="my_stats_leaderboard")],
        [InlineKeyboardButton("ℹ️ حول البوت", callback_data="about_bot")],
    ]
    try:
        if db_manager.is_user_admin(user.id):
            keyboard.append([InlineKeyboardButton("⚙️ لوحة تحكم الأدمن", callback_data="admin_show_tools_menu")])
    except Exception:
        pass

    try:
        await query.edit_message_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await context.bot.send_message(chat_id=user.id, text=welcome_text, reply_markup=InlineKeyboardMarkup(keyboard))


# ============================================================
#  2. ملخص سريع فوري
# ============================================================
async def admin_quick_summary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض ملخص سريع: مسجلين، نشطين، اختبارات"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return

    await query.edit_message_text("⏳ جاري جمع الإحصائيات...")

    conn = None
    try:
        conn = connect_db()
        if not conn:
            await query.edit_message_text("❌ خطأ في الاتصال بقاعدة البيانات", reply_markup=get_admin_menu_keyboard())
            return

        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # عدد المسجلين
            cur.execute("SELECT COUNT(*) FROM users WHERE is_registered = TRUE")
            total_registered = cur.fetchone()[0]

            # توزيع حسب الصف
            cur.execute("""
                SELECT grade, COUNT(*) as cnt 
                FROM users WHERE is_registered = TRUE AND grade IS NOT NULL
                GROUP BY grade ORDER BY cnt DESC
            """)
            grade_dist = cur.fetchall()

            # نشطين اليوم
            cur.execute("""
                SELECT COUNT(DISTINCT user_id) FROM quiz_results 
                WHERE completed_at >= CURRENT_DATE
            """)
            active_today = cur.fetchone()[0]

            # نشطين آخر 7 أيام
            cur.execute("""
                SELECT COUNT(DISTINCT user_id) FROM quiz_results 
                WHERE completed_at >= CURRENT_DATE - INTERVAL '7 days'
            """)
            active_week = cur.fetchone()[0]

            # اختبارات اليوم
            cur.execute("""
                SELECT COUNT(*) FROM quiz_results 
                WHERE completed_at >= CURRENT_DATE
            """)
            quizzes_today = cur.fetchone()[0]

            # اختبارات الأسبوع
            cur.execute("""
                SELECT COUNT(*) FROM quiz_results 
                WHERE completed_at >= CURRENT_DATE - INTERVAL '7 days'
            """)
            quizzes_week = cur.fetchone()[0]

            # متوسط الدرجات هذا الأسبوع
            cur.execute("""
                SELECT ROUND(AVG(score_percentage)::numeric, 1) FROM quiz_results 
                WHERE completed_at >= CURRENT_DATE - INTERVAL '7 days'
                AND score_percentage IS NOT NULL
            """)
            avg_score = cur.fetchone()[0] or 0

            # آخر 5 اختبارات
            cur.execute("""
                SELECT u.full_name, qr.score_percentage, qr.completed_at
                FROM quiz_results qr
                JOIN users u ON qr.user_id = u.user_id
                WHERE qr.completed_at IS NOT NULL
                ORDER BY qr.completed_at DESC LIMIT 5
            """)
            recent_quizzes = cur.fetchall()

        # بناء الرسالة
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        msg = f"📊 ملخص سريع — {now}\n\n"

        msg += f"👥 المسجلين: {total_registered}\n"
        if grade_dist:
            for g in grade_dist:
                msg += f"   • {g['grade']}: {g['cnt']}\n"

        msg += f"\n🟢 نشطين اليوم: {active_today}\n"
        msg += f"🟡 نشطين (7 أيام): {active_week}\n"

        msg += f"\n📝 اختبارات اليوم: {quizzes_today}\n"
        msg += f"📝 اختبارات (7 أيام): {quizzes_week}\n"
        msg += f"📈 متوسط الدرجات (7 أيام): {avg_score}%\n"

        if recent_quizzes:
            msg += "\n🕐 آخر الاختبارات:\n"
            for rq in recent_quizzes:
                name = (rq['full_name'] or "—")[:15]
                score = rq['score_percentage'] or 0
                time_str = rq['completed_at'].strftime("%H:%M") if rq['completed_at'] else "—"
                msg += f"   • {name}: {score}% ({time_str})\n"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تحديث", callback_data="admin_quick_summary")],
            [InlineKeyboardButton("⬅️ رجوع", callback_data="admin_show_tools_menu")],
        ])
        await query.edit_message_text(msg, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Error in quick summary: {e}", exc_info=True)
        await query.edit_message_text(f"❌ خطأ: {str(e)[:200]}", reply_markup=get_admin_menu_keyboard())
    finally:
        if conn:
            conn.close()


# ============================================================
#  3. بحث عن طالب
# ============================================================
async def admin_search_student_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """بدء البحث عن طالب"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return ConversationHandler.END

    await query.edit_message_text(
        "🔍 بحث عن طالب\n\n"
        "أدخل اسم الطالب أو جزء منه أو رقم الـ ID:\n\n"
        "أرسل /cancel_search للإلغاء"
    )
    return SEARCH_STUDENT_INPUT


async def search_student_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة البحث عن طالب"""
    search_query = update.message.text.strip()

    conn = None
    try:
        conn = connect_db()
        if not conn:
            await update.message.reply_text("❌ خطأ في الاتصال بقاعدة البيانات")
            return ConversationHandler.END

        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            if search_query.isdigit():
                cur.execute("""
                    SELECT u.user_id, u.full_name, u.email, u.phone, u.grade, u.is_registered,
                           COUNT(qr.id) as quiz_count,
                           ROUND(AVG(qr.score_percentage)::numeric, 1) as avg_score,
                           MAX(qr.completed_at) as last_quiz
                    FROM users u
                    LEFT JOIN quiz_results qr ON u.user_id = qr.user_id
                    WHERE u.user_id = %s
                    GROUP BY u.user_id, u.full_name, u.email, u.phone, u.grade, u.is_registered
                """, (int(search_query),))
            else:
                cur.execute("""
                    SELECT u.user_id, u.full_name, u.email, u.phone, u.grade, u.is_registered,
                           COUNT(qr.id) as quiz_count,
                           ROUND(AVG(qr.score_percentage)::numeric, 1) as avg_score,
                           MAX(qr.completed_at) as last_quiz
                    FROM users u
                    LEFT JOIN quiz_results qr ON u.user_id = qr.user_id
                    WHERE u.is_registered = TRUE AND u.full_name ILIKE %s
                    GROUP BY u.user_id, u.full_name, u.email, u.phone, u.grade, u.is_registered
                    ORDER BY u.full_name
                    LIMIT 10
                """, (f"%{search_query}%",))

            results = cur.fetchall()

        if not results:
            await update.message.reply_text(
                f"❌ لا توجد نتائج لـ: {search_query}\n\n"
                "جرب بحث ثاني أو أرسل /cancel_search للإلغاء"
            )
            return SEARCH_STUDENT_INPUT

        if len(results) == 1:
            r = results[0]
            msg = _format_student_details(r)
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 بحث جديد", callback_data="admin_search_student")],
                [InlineKeyboardButton("⬅️ رجوع للوحة", callback_data="admin_show_tools_menu")],
            ])
            await update.message.reply_text(msg, reply_markup=keyboard)
            return ConversationHandler.END
        else:
            msg = f"🔍 نتائج البحث ({len(results)}):\n\n"
            for r in results:
                name = r['full_name'] or "—"
                grade = r['grade'] or "—"
                quizzes = r['quiz_count'] or 0
                avg = r['avg_score'] or 0
                msg += f"• {name} | {grade} | {quizzes} اختبار | {avg}%\n"
                msg += f"  ID: {r['user_id']}\n\n"

            msg += "📌 أرسل رقم ID للتفاصيل أو اسم للبحث مرة ثانية\n/cancel_search للإلغاء"
            await update.message.reply_text(msg)
            return SEARCH_STUDENT_INPUT

    except Exception as e:
        logger.error(f"Error searching student: {e}", exc_info=True)
        await update.message.reply_text(f"❌ خطأ: {str(e)[:200]}")
        return ConversationHandler.END
    finally:
        if conn:
            conn.close()


def _format_student_details(r) -> str:
    """تنسيق تفاصيل الطالب"""
    name = r['full_name'] or "—"
    email = r['email'] or "—"
    phone = r['phone'] or "—"
    grade = r['grade'] or "—"
    registered = "✅ مسجل" if r['is_registered'] else "❌ غير مسجل"
    quizzes = r['quiz_count'] or 0
    avg_score = r['avg_score'] or 0
    last_quiz = r['last_quiz'].strftime("%Y-%m-%d %H:%M") if r['last_quiz'] else "—"

    if avg_score >= 80:
        performance = "🟢 ممتاز"
    elif avg_score >= 60:
        performance = "🟡 جيد"
    elif avg_score > 0:
        performance = "🔴 يحتاج تحسين"
    else:
        performance = "⚪ لم يختبر"

    return (
        f"👤 بيانات الطالب\n\n"
        f"📛 الاسم: {name}\n"
        f"🆔 ID: {r['user_id']}\n"
        f"📧 الإيميل: {email}\n"
        f"📱 الجوال: {phone}\n"
        f"🎓 الصف: {grade}\n"
        f"📌 الحالة: {registered}\n\n"
        f"📊 الإحصائيات:\n"
        f"• عدد الاختبارات: {quizzes}\n"
        f"• متوسط الدرجات: {avg_score}%\n"
        f"• آخر اختبار: {last_quiz}\n"
        f"• التقييم: {performance}"
    )


async def cancel_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """إلغاء البحث"""
    await update.message.reply_text("تم إلغاء البحث.", reply_markup=get_admin_menu_keyboard())
    return ConversationHandler.END


# ============================================================
#  4. تصدير المسجلين (زر بدل أمر)
# ============================================================
async def admin_export_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تصدير المسجلين عبر زر — يستدعي نفس الأمر الموجود"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return

    await query.edit_message_text("⏳ جاري تصدير بيانات المسجلين...")

    try:
        from handlers.admin_tools.admin_commands import export_users_to_excel
        db_manager = context.bot_data.get("DB_MANAGER")
        user_id = update.effective_user.id

        if not db_manager:
            await query.edit_message_text("❌ قاعدة البيانات غير متاحة", reply_markup=get_admin_menu_keyboard())
            return

        result = await export_users_to_excel(db_manager, user_id)

        if result and isinstance(result, tuple):
            excel_path, stats = result
            caption = (
                f"📊 تم التصدير بنجاح\n\n"
                f"• إجمالي المستخدمين: {stats.get('total', 0)}\n"
                f"• النشطون: {stats.get('active', 0)}\n"
                f"• المحظورون: {stats.get('blocked', 0)}"
            )
            with open(excel_path, 'rb') as f:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f,
                    filename=os.path.basename(excel_path),
                    caption=caption
                )
            await query.message.reply_text("🛠️ لوحة تحكم الأدمن:", reply_markup=get_admin_menu_keyboard())
        else:
            await query.edit_message_text("❌ فشل التصدير", reply_markup=get_admin_menu_keyboard())

    except ImportError:
        await query.edit_message_text(
            "📁 لتصدير المسجلين استخدم الأمر:\n/export_users",
            reply_markup=get_admin_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"Error exporting users: {e}")
        await query.edit_message_text(f"❌ خطأ: {str(e)[:200]}", reply_markup=get_admin_menu_keyboard())


# ============================================================
#  5. قائمة الإشعارات (عام + حسب الصف)
# ============================================================
async def admin_broadcast_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """قائمة خيارات الإشعارات"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return

    # جلب عدد كل صف
    grade_counts = {}
    conn = None
    try:
        conn = connect_db()
        if conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT grade, COUNT(*) as cnt 
                    FROM users WHERE is_registered = TRUE AND grade IS NOT NULL
                    GROUP BY grade ORDER BY cnt DESC
                """)
                for row in cur.fetchall():
                    grade_counts[row['grade']] = row['cnt']
    except Exception:
        pass
    finally:
        if conn:
            conn.close()

    total = sum(grade_counts.values())
    msg = f"📣 إرسال إشعار\n\n👥 إجمالي المسجلين: {total}\n"
    for g, c in grade_counts.items():
        msg += f"   • {g}: {c}\n"
    msg += "\nاختر نوع الإشعار:"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📣 إشعار للجميع ({total})", callback_data="admin_broadcast_start")],
        [InlineKeyboardButton("🎓 إشعار حسب الصف", callback_data="admin_broadcast_grade")],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="admin_show_tools_menu")],
    ])
    await query.edit_message_text(msg, reply_markup=keyboard)


# --- إشعار عام ---
async def admin_broadcast_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return ConversationHandler.END

    context.user_data['broadcast_grade_filter'] = None
    await query.edit_message_text(
        "📣 إشعار عام لجميع المسجلين\n\n"
        "أرسل نص الإشعار:\n"
        "(/cancel_broadcast للإلغاء)"
    )
    return BROADCAST_MESSAGE_TEXT


# --- إشعار حسب الصف ---
async def admin_broadcast_grade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """اختيار الصف للإشعار"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return ConversationHandler.END

    # جلب الصفوف المتاحة مع أعدادها
    grades_info = []
    conn = None
    try:
        conn = connect_db()
        if conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT grade, COUNT(*) as cnt 
                    FROM users WHERE is_registered = TRUE AND grade IS NOT NULL
                    GROUP BY grade ORDER BY cnt DESC
                """)
                grades_info = cur.fetchall()
    except Exception:
        pass
    finally:
        if conn:
            conn.close()

    if not grades_info:
        await query.edit_message_text("❌ لا توجد صفوف مسجلة", reply_markup=get_admin_menu_keyboard())
        return ConversationHandler.END

    keyboard = []
    for g in grades_info:
        keyboard.append([InlineKeyboardButton(
            f"{g['grade']} ({g['cnt']} طالب)",
            callback_data=f"bcast_grade_{g['grade']}"
        )])
    keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="bcast_grade_cancel")])

    await query.edit_message_text("🎓 اختر الصف الدراسي:", reply_markup=InlineKeyboardMarkup(keyboard))
    return BROADCAST_GRADE_SELECT


async def broadcast_grade_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """بعد اختيار الصف"""
    query = update.callback_query
    await query.answer()

    if query.data == "bcast_grade_cancel":
        await query.edit_message_text("تم الإلغاء.", reply_markup=get_admin_menu_keyboard())
        return ConversationHandler.END

    grade = query.data.replace("bcast_grade_", "")
    context.user_data['broadcast_grade_filter'] = grade

    # عدد الطلاب في هذا الصف
    conn = None
    count = 0
    try:
        conn = connect_db()
        if conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users WHERE is_registered = TRUE AND grade = %s", (grade,))
                count = cur.fetchone()[0]
    except Exception:
        pass
    finally:
        if conn:
            conn.close()

    await query.edit_message_text(
        f"🎓 إشعار لطلاب: {grade}\n"
        f"👥 عدد المستهدفين: {count}\n\n"
        f"أرسل نص الإشعار:\n"
        f"(/cancel_broadcast للإلغاء)"
    )
    return BROADCAST_MESSAGE_TEXT


async def received_broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_admin_privileges(update, context):
        return ConversationHandler.END

    broadcast_text = update.message.text
    context.user_data["broadcast_text"] = broadcast_text

    grade_filter = context.user_data.get('broadcast_grade_filter')
    target = f"طلاب {grade_filter}" if grade_filter else "جميع المسجلين"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم، إرسال", callback_data="admin_broadcast_confirm")],
        [InlineKeyboardButton("❌ لا، إلغاء", callback_data="admin_broadcast_cancel")]
    ])
    await update.message.reply_text(
        f"📣 تأكيد الإشعار\n\n"
        f"🎯 الهدف: {target}\n\n"
        f"📝 النص:\n{broadcast_text}\n\n"
        f"هل أنت متأكد؟",
        reply_markup=keyboard
    )
    return BROADCAST_CONFIRM


async def admin_broadcast_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return ConversationHandler.END

    broadcast_text = context.user_data.get("broadcast_text")
    if not broadcast_text:
        await query.edit_message_text("❌ لم يتم العثور على نص الإشعار.")
        return ConversationHandler.END

    grade_filter = context.user_data.get('broadcast_grade_filter')
    await query.edit_message_text("⏳ جاري الإرسال...")

    # جلب المستخدمين المسجلين فقط
    user_ids = []
    conn = None
    try:
        conn = connect_db()
        if conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                if grade_filter:
                    cur.execute("SELECT user_id FROM users WHERE is_registered = TRUE AND grade = %s", (grade_filter,))
                else:
                    cur.execute("SELECT user_id FROM users WHERE is_registered = TRUE")
                rows = cur.fetchall()
                if rows:
                    user_ids = [row['user_id'] for row in rows]
                logger.info(f"Broadcast: Found {len(user_ids)} users (grade_filter={grade_filter})")
    except Exception as e:
        logger.error(f"Error fetching users for broadcast: {e}")
        await query.edit_message_text("❌ خطأ في جلب المستخدمين", reply_markup=get_admin_menu_keyboard())
        _cleanup_broadcast_data(context)
        return ConversationHandler.END
    finally:
        if conn:
            conn.close()

    if not user_ids:
        await query.edit_message_text("❌ لا يوجد مستخدمين للإرسال", reply_markup=get_admin_menu_keyboard())
        _cleanup_broadcast_data(context)
        return ConversationHandler.END

    # إرسال
    sent_count = 0
    failed_count = 0
    failed_users = []

    for user_id in user_ids:
        try:
            await context.bot.send_message(chat_id=user_id, text=broadcast_text)
            sent_count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            failed_count += 1
            failed_users.append({"user_id": user_id, "error": str(e)[:80]})

    # النتيجة
    target = f"طلاب {grade_filter}" if grade_filter else "جميع المسجلين"
    result = (
        f"اكتمل الإرسال.\n"
        f"🎯 الهدف: {target}\n"
        f"تم الإرسال بنجاح إلى: {sent_count} مستخدم.\n"
        f"فشل الإرسال لـ: {failed_count} مستخدم."
    )

    if failed_users:
        result += "\n\n📋 قائمة المستخدمين الذين فشل الإرسال لهم:\n"
        for idx, fu in enumerate(failed_users[:15], 1):
            result += f"{idx}. User ID: {fu['user_id']}\n   الخطأ: {fu['error']}...\n"
        if len(failed_users) > 15:
            result += f"... و {len(failed_users) - 15} آخرين"

    await query.message.reply_text(result)
    _cleanup_broadcast_data(context)

    await query.message.reply_text("🛠️ لوحة تحكم الأدمن:", reply_markup=get_admin_menu_keyboard())
    return ConversationHandler.END


async def admin_broadcast_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _cleanup_broadcast_data(context)
    await query.edit_message_text("تم إلغاء الإشعار.")
    await query.message.reply_text("🛠️ لوحة تحكم الأدمن:", reply_markup=get_admin_menu_keyboard())
    return ConversationHandler.END


async def cancel_broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _cleanup_broadcast_data(context)
    await update.message.reply_text("تم إلغاء الإشعار.", reply_markup=get_admin_menu_keyboard())
    return ConversationHandler.END


def _cleanup_broadcast_data(context):
    """تنظيف بيانات الإشعار من السياق"""
    context.user_data.pop("broadcast_text", None)
    context.user_data.pop("broadcast_grade_filter", None)


# ============================================================
#  6. تعديل رسائل البوت
# ============================================================
async def admin_edit_messages_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """قائمة تعديل الرسائل"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ تعديل رسالة حول البوت", callback_data="admin_edit_specific_msg_about_bot_message")],
        [InlineKeyboardButton("📝 تعديل رسائل أخرى", callback_data="admin_edit_other_messages_menu")],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="admin_show_tools_menu")],
    ])
    await query.edit_message_text("✏️ تعديل رسائل البوت:", reply_markup=keyboard)


async def admin_edit_specific_message_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return ConversationHandler.END

    message_key_parts = query.data.split("_")
    message_key = "_".join(message_key_parts[4:])
    context.user_data["editing_message_key"] = message_key

    current_text = context.bot_data.get("DB_MANAGER").get_system_message(message_key) or "لا يوجد نص حالي."
    await query.edit_message_text(
        f"📝 النص الحالي لـ '{message_key}':\n\n{current_text}\n\n"
        "أرسل النص الجديد:\n(/cancel_edit للإلغاء)"
    )
    return EDIT_MESSAGE_TEXT


async def admin_edit_other_messages_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return

    editable_messages = context.bot_data.get("DB_MANAGER").get_all_editable_message_keys()
    keyboard = []
    if not editable_messages:
        await query.edit_message_text(
            "لا توجد رسائل قابلة للتعديل.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="admin_edit_messages_menu")]])
        )
        return

    for msg_info in editable_messages:
        keyboard.append([InlineKeyboardButton(msg_info["description"], callback_data=f"admin_edit_specific_msg_{msg_info['key']}")])
    keyboard.append([InlineKeyboardButton("⬅️ رجوع", callback_data="admin_edit_messages_menu")])
    await query.edit_message_text("اختر الرسالة:", reply_markup=InlineKeyboardMarkup(keyboard))


async def received_new_message_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_admin_privileges(update, context):
        return ConversationHandler.END

    new_text = update.message.text
    message_key = context.user_data.get("editing_message_key")

    if not message_key:
        await update.message.reply_text("❌ خطأ، لم يتم تحديد الرسالة.")
        return ConversationHandler.END

    context.bot_data.get("DB_MANAGER").update_system_message(message_key, new_text)
    await update.message.reply_text(f"✅ تم تحديث '{message_key}' بنجاح!")
    del context.user_data["editing_message_key"]

    await update.message.reply_text("🛠️ لوحة تحكم الأدمن:", reply_markup=get_admin_menu_keyboard())
    return ConversationHandler.END


async def cancel_edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("editing_message_key", None)
    await update.message.reply_text("تم إلغاء التعديل.", reply_markup=get_admin_menu_keyboard())
    return ConversationHandler.END
