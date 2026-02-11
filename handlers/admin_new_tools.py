#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
لوحة تحكم الأدمن المحسنة
- قائمة أزرار موحدة لكل الأدوات
- ملخص سريع فوري (مع عدد طلابي)
- بحث عن طالب (مع زر تمييز ⭐)
- إشعار حسب الصف / طلابي فقط
- تعديل الرسائل
- wrapper لزر الإحصائيات
- نظام تمييز الطلاب (is_my_student)
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

# === States ===
EDIT_MESSAGE_TEXT = 0
BROADCAST_MESSAGE_TEXT = 1
BROADCAST_CONFIRM = 2
SEARCH_STUDENT_INPUT = 3
BROADCAST_GRADE_SELECT = 4
EXAM_SCHEDULE_INPUT = 5


# ============================================================
#  0. ضمان وجود عمود is_my_student
# ============================================================
async def ensure_my_student_column():
    """التأكد من وجود عمود is_my_student في جدول users — يُنفذ مرة واحدة"""
    conn = None
    try:
        conn = connect_db()
        if conn:
            with conn.cursor() as cur:
                cur.execute("""
                    DO $$ BEGIN
                        ALTER TABLE users ADD COLUMN is_my_student BOOLEAN DEFAULT FALSE;
                    EXCEPTION
                        WHEN duplicate_column THEN NULL;
                    END $$;
                """)
                conn.commit()
                logger.info("[TagSystem] Column is_my_student ensured")
    except Exception as e:
        logger.error(f"[TagSystem] Error ensuring column: {e}")
    finally:
        if conn:
            conn.close()


# ============================================================
#  قائمة أدوات الأدمن الموحدة
# ============================================================
def get_admin_menu_keyboard():
    """إنشاء لوحة أزرار الأدمن الموحدة"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 ملخص سريع", callback_data="admin_quick_summary")],
        [InlineKeyboardButton("🔍 بحث عن طالب", callback_data="admin_search_student"),
         InlineKeyboardButton("⭐ طلابي", callback_data="admin_my_students_list")],
        [InlineKeyboardButton("📈 لوحة الإحصائيات", callback_data="stats_admin_panel_v4")],
        [InlineKeyboardButton("📁 تصدير المسجلين Excel", callback_data="admin_export_users")],
        [InlineKeyboardButton("📋 تقرير مخصص", callback_data="custom_report_start")],
        [InlineKeyboardButton("📋 تقرير أسبوعي", callback_data="admin_report_weekly"),
         InlineKeyboardButton("📊 تقرير شهري", callback_data="admin_report_monthly")],
        [InlineKeyboardButton("🏆 شهادات تفوق", callback_data="admin_report_certificates"),
         InlineKeyboardButton("📱 إشعار الضعاف", callback_data="admin_report_notify")],
        [InlineKeyboardButton("📣 إرسال إشعار", callback_data="admin_broadcast_menu")],
        [InlineKeyboardButton("⏳ مواعيد التحصيلي", callback_data="admin_exam_schedule")],
        [InlineKeyboardButton("✏️ تعديل رسائل البوت", callback_data="admin_edit_messages_menu")],
        [InlineKeyboardButton("⚙️ إعدادات البوت", callback_data="admin_bot_settings")],
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
    # ضمان وجود العمود عند أول دخول للوحة
    await ensure_my_student_column()
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
#  2. ملخص سريع فوري (مع عدد طلابي)
# ============================================================
async def admin_quick_summary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض ملخص سريع: مسجلين، طلابي، نشطين، اختبارات"""
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

            # عدد طلابي
            cur.execute("SELECT COUNT(*) FROM users WHERE is_registered = TRUE AND COALESCE(is_my_student, FALSE) = TRUE")
            my_students = cur.fetchone()[0]

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
                SELECT u.full_name, qr.score_percentage, qr.completed_at,
                       COALESCE(u.is_my_student, FALSE) as is_my_student
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
        msg += f"⭐ طلابي: {my_students}\n"
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
                star = "⭐" if rq['is_my_student'] else ""
                name = (rq['full_name'] or "—")[:15]
                score = rq['score_percentage'] or 0
                time_str = rq['completed_at'].strftime("%H:%M") if rq['completed_at'] else "—"
                msg += f"   • {star}{name}: {score}% ({time_str})\n"

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
#  3. بحث عن طالب (مع is_my_student + زر تمييز)
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
                           COALESCE(u.is_my_student, FALSE) as is_my_student,
                           COUNT(qr.id) as quiz_count,
                           ROUND(AVG(qr.score_percentage)::numeric, 1) as avg_score,
                           MAX(qr.completed_at) as last_quiz
                    FROM users u
                    LEFT JOIN quiz_results qr ON u.user_id = qr.user_id
                    WHERE u.user_id = %s
                    GROUP BY u.user_id, u.full_name, u.email, u.phone, u.grade, u.is_registered, u.is_my_student
                """, (int(search_query),))
            else:
                cur.execute("""
                    SELECT u.user_id, u.full_name, u.email, u.phone, u.grade, u.is_registered,
                           COALESCE(u.is_my_student, FALSE) as is_my_student,
                           COUNT(qr.id) as quiz_count,
                           ROUND(AVG(qr.score_percentage)::numeric, 1) as avg_score,
                           MAX(qr.completed_at) as last_quiz
                    FROM users u
                    LEFT JOIN quiz_results qr ON u.user_id = qr.user_id
                    WHERE u.is_registered = TRUE AND u.full_name ILIKE %s
                    GROUP BY u.user_id, u.full_name, u.email, u.phone, u.grade, u.is_registered, u.is_my_student
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
            is_tagged = r['is_my_student']
            tag_btn_text = "☆ إزالة من طلابي" if is_tagged else "⭐ تمييز كطالبي"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(tag_btn_text, callback_data=f"toggle_my_student_{r['user_id']}")],
                [InlineKeyboardButton("🔍 بحث جديد", callback_data="admin_search_student")],
                [InlineKeyboardButton("⬅️ رجوع للوحة", callback_data="admin_show_tools_menu")],
            ])
            await update.message.reply_text(msg, reply_markup=keyboard)
            return ConversationHandler.END
        else:
            msg = f"🔍 نتائج البحث ({len(results)}):\n\n"
            for r in results:
                star = "⭐ " if r['is_my_student'] else ""
                name = r['full_name'] or "—"
                grade = r['grade'] or "—"
                quizzes = r['quiz_count'] or 0
                avg = r['avg_score'] or 0
                msg += f"• {star}{name} | {grade} | {quizzes} اختبار | {avg}%\n"
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
    is_my = "⭐ طالبي" if r.get('is_my_student') else ""
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

    header = f"👤 بيانات الطالب {is_my}\n\n" if is_my else "👤 بيانات الطالب\n\n"

    return (
        f"{header}"
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
#  4. تبديل تمييز الطالب (⭐ طالبي)
# ============================================================
async def admin_toggle_my_student_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تبديل تمييز طالب (طالبي / ليس طالبي)"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return

    try:
        target_user_id = int(query.data.replace("toggle_my_student_", ""))
    except ValueError:
        await query.answer("❌ خطأ في المعرف", show_alert=True)
        return

    conn = None
    try:
        conn = connect_db()
        if conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                # تبديل الحالة
                cur.execute("""
                    UPDATE users SET is_my_student = NOT COALESCE(is_my_student, FALSE)
                    WHERE user_id = %s
                    RETURNING is_my_student, full_name
                """, (target_user_id,))
                result = cur.fetchone()
                conn.commit()

                if not result:
                    await query.answer("❌ الطالب غير موجود", show_alert=True)
                    return

                new_status = result['is_my_student']
                name = result['full_name'] or str(target_user_id)
                emoji = "⭐" if new_status else "☆"
                status_text = "تم تمييزه كطالبي" if new_status else "تم إزالة التمييز"
                await query.answer(f"{emoji} {name}: {status_text}", show_alert=True)

                # إعادة عرض تفاصيل الطالب
                cur.execute("""
                    SELECT u.user_id, u.full_name, u.email, u.phone, u.grade, u.is_registered,
                           COALESCE(u.is_my_student, FALSE) as is_my_student,
                           COUNT(qr.id) as quiz_count,
                           ROUND(AVG(qr.score_percentage)::numeric, 1) as avg_score,
                           MAX(qr.completed_at) as last_quiz
                    FROM users u
                    LEFT JOIN quiz_results qr ON u.user_id = qr.user_id
                    WHERE u.user_id = %s
                    GROUP BY u.user_id, u.full_name, u.email, u.phone, u.grade, u.is_registered, u.is_my_student
                """, (target_user_id,))
                student = cur.fetchone()
                if student:
                    msg = _format_student_details(student)
                    is_tagged = student['is_my_student']
                    tag_btn_text = "☆ إزالة من طلابي" if is_tagged else "⭐ تمييز كطالبي"
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton(tag_btn_text, callback_data=f"toggle_my_student_{target_user_id}")],
                        [InlineKeyboardButton("🔍 بحث جديد", callback_data="admin_search_student")],
                        [InlineKeyboardButton("⬅️ رجوع للوحة", callback_data="admin_show_tools_menu")],
                    ])
                    await query.edit_message_text(msg, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error toggling student tag: {e}")
        await query.answer(f"❌ خطأ: {str(e)[:100]}", show_alert=True)
    finally:
        if conn:
            conn.close()


# ============================================================
#  4b. قائمة طلابي (عرض + إزالة سريعة + تمييز حسب الصف)
# ============================================================
async def admin_my_students_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض قائمة طلابي مع أزرار إزالة سريعة"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return

    # جلب الصفحة
    page = context.user_data.get('my_students_page', 0)
    # لو الضغطة فيها رقم صفحة
    if query.data.startswith("my_students_page_"):
        try:
            page = int(query.data.replace("my_students_page_", ""))
        except ValueError:
            page = 0
    context.user_data['my_students_page'] = page

    PAGE_SIZE = 10
    offset = page * PAGE_SIZE

    conn = None
    try:
        conn = connect_db()
        if not conn:
            await query.edit_message_text("❌ خطأ في الاتصال", reply_markup=get_admin_menu_keyboard())
            return

        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # العدد الكلي
            cur.execute("SELECT COUNT(*) FROM users WHERE is_registered = TRUE AND COALESCE(is_my_student, FALSE) = TRUE")
            total = cur.fetchone()[0]

            if total == 0:
                # عرض خيارات التمييز
                await _show_empty_my_students(query)
                return

            # جلب الطلاب — مرتبين حسب الصف ثم الاسم
            cur.execute("""
                SELECT u.user_id, u.full_name, u.grade,
                       COUNT(qr.id) as quiz_count,
                       ROUND(AVG(qr.score_percentage)::numeric, 1) as avg_score
                FROM users u
                LEFT JOIN quiz_results qr ON u.user_id = qr.user_id
                WHERE u.is_registered = TRUE AND COALESCE(u.is_my_student, FALSE) = TRUE
                GROUP BY u.user_id, u.full_name, u.grade
                ORDER BY u.grade, u.full_name
                LIMIT %s OFFSET %s
            """, (PAGE_SIZE, offset))
            students = cur.fetchall()

            # توزيع حسب الصف
            cur.execute("""
                SELECT grade, COUNT(*) as cnt
                FROM users
                WHERE is_registered = TRUE AND COALESCE(is_my_student, FALSE) = TRUE AND grade IS NOT NULL
                GROUP BY grade ORDER BY grade
            """)
            grade_summary = cur.fetchall()

        # بناء الرسالة
        msg = f"⭐ طلابي ({total})\n"
        if grade_summary:
            parts = [f"{g['grade']}: {g['cnt']}" for g in grade_summary]
            msg += f"({' | '.join(parts)})\n"
        msg += "\n"

        current_grade = None
        for i, s in enumerate(students, start=offset + 1):
            name = (s['full_name'] or "—")[:20]
            grade = s['grade'] or "—"
            avg = s['avg_score'] or 0
            quizzes = s['quiz_count'] or 0
            # عنوان الصف
            if grade != current_grade:
                msg += f"\n📚 {grade}:\n"
                current_grade = grade
            msg += f"  {i}. {name} | {quizzes}📝 | {avg}%\n"

        # أزرار إزالة — كل طالب له زر ❌
        keyboard = []
        row = []
        for s in students:
            short_name = (s['full_name'] or "—")[:10]
            row.append(InlineKeyboardButton(f"❌ {short_name}", callback_data=f"untag_student_{s['user_id']}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        # صفحات
        nav_row = []
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        if page > 0:
            nav_row.append(InlineKeyboardButton("◀️ السابق", callback_data=f"my_students_page_{page - 1}"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("التالي ▶️", callback_data=f"my_students_page_{page + 1}"))
        if nav_row:
            keyboard.append(nav_row)

        msg += f"\nصفحة {page + 1}/{total_pages}"

        keyboard.append([InlineKeyboardButton("➕ تمييز حسب الصف", callback_data="admin_tag_by_grade")])
        keyboard.append([InlineKeyboardButton("🗑️ إزالة الكل", callback_data="admin_untag_all_confirm")])
        keyboard.append([InlineKeyboardButton("⬅️ رجوع", callback_data="admin_show_tools_menu")])

        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logger.error(f"Error listing my students: {e}", exc_info=True)
        await query.edit_message_text(f"❌ خطأ: {str(e)[:200]}", reply_markup=get_admin_menu_keyboard())
    finally:
        if conn:
            conn.close()


async def _show_empty_my_students(query):
    """عرض رسالة لا يوجد طلاب مع خيار تمييز حسب الصف"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ تمييز حسب الصف", callback_data="admin_tag_by_grade")],
        [InlineKeyboardButton("🔍 بحث وتمييز", callback_data="admin_search_student")],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="admin_show_tools_menu")],
    ])
    await query.edit_message_text(
        "⭐ طلابي (0)\n\n"
        "لا يوجد طلاب مميزين حالياً.\n\n"
        "طرق التمييز:\n"
        "• ➕ تمييز حسب الصف — تميز كل طلاب صف معين\n"
        "• 🔍 بحث وتمييز — تبحث عن طالب وتميزه",
        reply_markup=keyboard
    )


async def admin_untag_student_from_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """إزالة تمييز طالب من القائمة وتحديثها"""
    query = update.callback_query

    try:
        target_user_id = int(query.data.replace("untag_student_", ""))
    except ValueError:
        await query.answer("❌ خطأ", show_alert=True)
        return

    conn = None
    try:
        conn = connect_db()
        if conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET is_my_student = FALSE WHERE user_id = %s RETURNING full_name", (target_user_id,))
                result = cur.fetchone()
                conn.commit()
                name = result[0] if result else str(target_user_id)
                await query.answer(f"☆ تم إزالة {name}")
    except Exception as e:
        logger.error(f"Error untagging: {e}")
        await query.answer("❌ خطأ", show_alert=True)
        return
    finally:
        if conn:
            conn.close()

    # تحديث القائمة
    await admin_my_students_list_callback(update, context)


# --- تمييز حسب الصف ---
async def admin_tag_by_grade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض الصفوف لاختيار طلاب منها"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return

    conn = None
    try:
        conn = connect_db()
        if not conn:
            await query.edit_message_text("❌ خطأ", reply_markup=get_admin_menu_keyboard())
            return

        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("""
                SELECT grade, 
                       COUNT(*) as total,
                       COUNT(*) FILTER (WHERE COALESCE(is_my_student, FALSE) = TRUE) as tagged
                FROM users 
                WHERE is_registered = TRUE AND grade IS NOT NULL
                GROUP BY grade ORDER BY grade
            """)
            grades = cur.fetchall()

        if not grades:
            await query.edit_message_text("❌ لا توجد صفوف", reply_markup=get_admin_menu_keyboard())
            return

        msg = "🎓 اختر الصف لعرض طلابه:\n\n"
        keyboard = []
        for g in grades:
            msg += f"• {g['grade']}: {g['tagged']}⭐ / {g['total']} طالب\n"
            keyboard.append([
                InlineKeyboardButton(
                    f"{g['grade']} ({g['tagged']}⭐/{g['total']})",
                    callback_data=f"grade_students_{g['grade']}"
                ),
                InlineKeyboardButton(
                    f"⭐ الكل",
                    callback_data=f"tag_grade_{g['grade']}"
                ),
            ])

        keyboard.append([InlineKeyboardButton("⬅️ رجوع", callback_data="admin_my_students_list")])
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logger.error(f"Error showing grades for tagging: {e}")
        await query.edit_message_text(f"❌ خطأ: {str(e)[:200]}", reply_markup=get_admin_menu_keyboard())
    finally:
        if conn:
            conn.close()


async def admin_grade_students_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض طلاب صف معين مع أزرار تمييز فردية ⭐/☆"""
    query = update.callback_query
    await query.answer()

    # استخراج الصف ورقم الصفحة من callback_data أو من context
    data = query.data
    if data.startswith("grade_students_page_"):
        parts = data.replace("grade_students_page_", "")
        last_underscore = parts.rfind("_")
        grade = parts[:last_underscore]
        page = int(parts[last_underscore + 1:])
    elif data.startswith("grade_students_"):
        grade = data.replace("grade_students_", "")
        page = 0
    else:
        # fallback من context (عند التبديل)
        grade = context.user_data.get('grade_browse_grade', '')
        page = context.user_data.get('grade_browse_page', 0)

    context.user_data['grade_browse_page'] = page
    context.user_data['grade_browse_grade'] = grade

    PAGE_SIZE = 8
    offset = page * PAGE_SIZE

    conn = None
    try:
        conn = connect_db()
        if not conn:
            await query.edit_message_text("❌ خطأ", reply_markup=get_admin_menu_keyboard())
            return

        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # العدد الكلي
            cur.execute(
                "SELECT COUNT(*) FROM users WHERE is_registered = TRUE AND grade = %s",
                (grade,)
            )
            total = cur.fetchone()[0]

            # الطلاب
            cur.execute("""
                SELECT user_id, full_name, COALESCE(is_my_student, FALSE) as is_my_student
                FROM users
                WHERE is_registered = TRUE AND grade = %s
                ORDER BY full_name
                LIMIT %s OFFSET %s
            """, (grade, PAGE_SIZE, offset))
            students = cur.fetchall()

            # عدد المميزين
            cur.execute(
                "SELECT COUNT(*) FROM users WHERE is_registered = TRUE AND grade = %s AND COALESCE(is_my_student, FALSE) = TRUE",
                (grade,)
            )
            tagged_count = cur.fetchone()[0]

        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        msg = f"🎓 {grade} — {tagged_count}⭐ / {total} طالب\n"
        msg += f"صفحة {page + 1}/{total_pages}\n\n"
        msg += "اضغط على الطالب لتمييزه/إزالته:\n\n"

        keyboard = []
        for s in students:
            name = s['full_name'] or str(s['user_id'])
            if s['is_my_student']:
                btn_text = f"⭐ {name}"
            else:
                btn_text = f"☆ {name}"
            keyboard.append([InlineKeyboardButton(
                btn_text,
                callback_data=f"gtoggle_{grade}_{page}_{s['user_id']}"
            )])

        # صفحات
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("◀️", callback_data=f"grade_students_page_{grade}_{page - 1}"))
        nav_row.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("▶️", callback_data=f"grade_students_page_{grade}_{page + 1}"))
        keyboard.append(nav_row)

        keyboard.append([InlineKeyboardButton("⬅️ رجوع للصفوف", callback_data="admin_tag_by_grade")])

        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logger.error(f"Error listing grade students: {e}", exc_info=True)
        await query.edit_message_text(f"❌ خطأ: {str(e)[:200]}", reply_markup=get_admin_menu_keyboard())
    finally:
        if conn:
            conn.close()


async def admin_grade_toggle_student_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تبديل تمييز طالب من داخل قائمة الصف"""
    query = update.callback_query

    # gtoggle_ثانوي 1_0_123456
    data = query.data.replace("gtoggle_", "")
    # نحتاج نستخرج: grade, page, user_id
    # user_id هو آخر جزء (رقم)
    # page هو ما قبله
    parts = data.rsplit("_", 2)  # ['ثانوي 1', '0', '123456']
    if len(parts) != 3:
        await query.answer("❌ خطأ", show_alert=True)
        return

    grade = parts[0]
    page = int(parts[1])
    target_user_id = int(parts[2])

    conn = None
    try:
        conn = connect_db()
        if conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE users SET is_my_student = NOT COALESCE(is_my_student, FALSE)
                    WHERE user_id = %s
                    RETURNING is_my_student, full_name
                """, (target_user_id,))
                result = cur.fetchone()
                conn.commit()
                if result:
                    status = "⭐" if result[0] else "☆"
                    name = result[1] or str(target_user_id)
                    await query.answer(f"{status} {name}")
    except Exception as e:
        logger.error(f"Error toggling from grade list: {e}")
        await query.answer("❌ خطأ", show_alert=True)
        return
    finally:
        if conn:
            conn.close()

    # إعادة عرض نفس الصفحة
    context.user_data['grade_browse_grade'] = grade
    context.user_data['grade_browse_page'] = page
    await admin_grade_students_list_callback(update, context)


async def admin_tag_grade_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تمييز كل طلاب صف معين دفعة واحدة"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return

    data = query.data
    if data.startswith("tag_grade_"):
        grade = data.replace("tag_grade_", "")
        tag_value = True
        action_text = "تمييز"
    elif data.startswith("untag_grade_"):
        grade = data.replace("untag_grade_", "")
        tag_value = False
        action_text = "إزالة تمييز"
    else:
        return

    conn = None
    try:
        conn = connect_db()
        if conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET is_my_student = %s WHERE is_registered = TRUE AND grade = %s",
                    (tag_value, grade)
                )
                count = cur.rowcount
                conn.commit()
                await query.answer(f"✅ تم {action_text} {count} طالب في {grade}", show_alert=True)
    except Exception as e:
        logger.error(f"Error bulk tagging: {e}")
        await query.answer(f"❌ خطأ: {str(e)[:100]}", show_alert=True)
        return
    finally:
        if conn:
            conn.close()

    # تحديث صفحة الصفوف
    await admin_tag_by_grade_callback(update, context)


# --- إزالة الكل ---
async def admin_untag_all_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تأكيد إزالة تمييز الكل"""
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم، إزالة الكل", callback_data="admin_untag_all_execute")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="admin_my_students_list")],
    ])
    await query.edit_message_text("⚠️ هل أنت متأكد من إزالة تمييز جميع الطلاب؟", reply_markup=keyboard)


async def admin_untag_all_execute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تنفيذ إزالة تمييز الكل"""
    query = update.callback_query
    await query.answer()

    conn = None
    try:
        conn = connect_db()
        if conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET is_my_student = FALSE WHERE COALESCE(is_my_student, FALSE) = TRUE")
                count = cur.rowcount
                conn.commit()
                await query.answer(f"✅ تم إزالة التمييز عن {count} طالب", show_alert=True)
    except Exception as e:
        logger.error(f"Error untagging all: {e}")
        await query.answer("❌ خطأ", show_alert=True)
    finally:
        if conn:
            conn.close()

    context.user_data['my_students_page'] = 0
    await admin_my_students_list_callback(update, context)


# ============================================================
#  5. تصدير المسجلين (زر بدل أمر)
# ============================================================
async def admin_export_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تصدير المسجلين عبر زر"""
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
#  6. قائمة الإشعارات (عام + حسب الصف + طلابي فقط)
# ============================================================
async def admin_broadcast_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """قائمة خيارات الإشعارات"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return

    # جلب عدد كل صف + طلابي
    grade_counts = {}
    my_students_count = 0
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

                cur.execute("SELECT COUNT(*) FROM users WHERE is_registered = TRUE AND COALESCE(is_my_student, FALSE) = TRUE")
                my_students_count = cur.fetchone()[0]
    except Exception:
        pass
    finally:
        if conn:
            conn.close()

    total = sum(grade_counts.values())
    msg = f"📣 إرسال إشعار\n\n👥 إجمالي المسجلين: {total}\n⭐ طلابي: {my_students_count}\n"
    for g, c in grade_counts.items():
        msg += f"   • {g}: {c}\n"
    msg += "\nاختر نوع الإشعار:"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📣 إشعار للجميع ({total})", callback_data="admin_broadcast_start")],
        [InlineKeyboardButton(f"⭐ إشعار لطلابي فقط ({my_students_count})", callback_data="admin_broadcast_my_students")],
        [InlineKeyboardButton("⭐🎓 إشعار لطلابي حسب الصف", callback_data="admin_broadcast_my_grade")],
        [InlineKeyboardButton("🎓 إشعار حسب الصف (الكل)", callback_data="admin_broadcast_grade")],
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
    context.user_data['broadcast_my_students_only'] = False
    await query.edit_message_text(
        "📣 إشعار عام لجميع المسجلين\n\n"
        "أرسل نص الإشعار:\n"
        "(/cancel_broadcast للإلغاء)"
    )
    return BROADCAST_MESSAGE_TEXT


# --- إشعار لطلابي فقط ---
async def admin_broadcast_my_students_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return ConversationHandler.END

    context.user_data['broadcast_grade_filter'] = None
    context.user_data['broadcast_my_students_only'] = True

    # عدد طلابي
    conn = None
    count = 0
    try:
        conn = connect_db()
        if conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users WHERE is_registered = TRUE AND COALESCE(is_my_student, FALSE) = TRUE")
                count = cur.fetchone()[0]
    except Exception:
        pass
    finally:
        if conn:
            conn.close()

    await query.edit_message_text(
        f"⭐ إشعار لطلابي فقط\n"
        f"👥 عدد المستهدفين: {count}\n\n"
        f"أرسل نص الإشعار:\n"
        f"(/cancel_broadcast للإلغاء)"
    )
    return BROADCAST_MESSAGE_TEXT


# --- إشعار حسب الصف ---
async def admin_broadcast_grade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """اختيار الصف للإشعار"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return ConversationHandler.END

    context.user_data['broadcast_my_students_only'] = False

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


# --- إشعار لطلابي حسب الصف ---
async def admin_broadcast_my_grade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """اختيار الصف للإشعار لطلابي فقط"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return ConversationHandler.END

    context.user_data['broadcast_my_students_only'] = True

    grades_info = []
    conn = None
    try:
        conn = connect_db()
        if conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT grade, COUNT(*) as cnt 
                    FROM users WHERE is_registered = TRUE AND grade IS NOT NULL
                        AND COALESCE(is_my_student, FALSE) = TRUE
                    GROUP BY grade ORDER BY cnt DESC
                """)
                grades_info = cur.fetchall()
    except Exception:
        pass
    finally:
        if conn:
            conn.close()

    if not grades_info:
        await query.edit_message_text("❌ لا يوجد طلاب مميزين", reply_markup=get_admin_menu_keyboard())
        return ConversationHandler.END

    keyboard = []
    for g in grades_info:
        keyboard.append([InlineKeyboardButton(
            f"⭐ {g['grade']} ({g['cnt']} طالب)",
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
    my_students_only = context.user_data.get('broadcast_my_students_only', False)

    conn = None
    count = 0
    try:
        conn = connect_db()
        if conn:
            with conn.cursor() as cur:
                if my_students_only:
                    cur.execute("SELECT COUNT(*) FROM users WHERE is_registered = TRUE AND grade = %s AND COALESCE(is_my_student, FALSE) = TRUE", (grade,))
                else:
                    cur.execute("SELECT COUNT(*) FROM users WHERE is_registered = TRUE AND grade = %s", (grade,))
                count = cur.fetchone()[0]
    except Exception:
        pass
    finally:
        if conn:
            conn.close()

    target_label = f"⭐ طلابي في {grade}" if my_students_only else f"طلاب {grade}"
    await query.edit_message_text(
        f"🎓 إشعار لـ: {target_label}\n"
        f"👥 عدد المستهدفين: {count}\n\n"
        f"أرسل نص الإشعار:\n"
        f"(/cancel_broadcast للإلغاء)"
    )
    return BROADCAST_MESSAGE_TEXT


def _get_broadcast_target_text(my_students_only, grade_filter):
    """تحديد نص الهدف للإشعار"""
    if my_students_only and grade_filter:
        return f"⭐ طلابي في {grade_filter}"
    elif my_students_only:
        return "⭐ طلابي فقط"
    elif grade_filter:
        return f"طلاب {grade_filter}"
    else:
        return "جميع المسجلين"


async def received_broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_admin_privileges(update, context):
        return ConversationHandler.END

    broadcast_text = update.message.text
    context.user_data["broadcast_text"] = broadcast_text

    grade_filter = context.user_data.get('broadcast_grade_filter')
    my_students_only = context.user_data.get('broadcast_my_students_only', False)

    target = _get_broadcast_target_text(my_students_only, grade_filter)

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
    my_students_only = context.user_data.get('broadcast_my_students_only', False)
    await query.edit_message_text("⏳ جاري الإرسال...")

    # جلب المستخدمين
    user_ids = []
    conn = None
    try:
        conn = connect_db()
        if conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                if my_students_only and grade_filter:
                    # طلابي في صف معين
                    cur.execute("SELECT user_id FROM users WHERE is_registered = TRUE AND COALESCE(is_my_student, FALSE) = TRUE AND grade = %s", (grade_filter,))
                elif my_students_only:
                    # طلابي فقط (كل الصفوف)
                    cur.execute("SELECT user_id FROM users WHERE is_registered = TRUE AND COALESCE(is_my_student, FALSE) = TRUE")
                elif grade_filter:
                    # كل طلاب صف معين
                    cur.execute("SELECT user_id FROM users WHERE is_registered = TRUE AND grade = %s", (grade_filter,))
                else:
                    # الكل
                    cur.execute("SELECT user_id FROM users WHERE is_registered = TRUE")
                rows = cur.fetchall()
                if rows:
                    user_ids = [row['user_id'] for row in rows]
                logger.info(f"Broadcast: Found {len(user_ids)} users (grade={grade_filter}, my_students={my_students_only})")
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

    # تحديد الهدف للعرض
    target = _get_broadcast_target_text(my_students_only, grade_filter)

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
    context.user_data.pop("broadcast_my_students_only", None)


# ============================================================
#  7. تعديل رسائل البوت
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


# ============================================================
#  8. wrapper لفتح لوحة الإحصائيات من الزر
# ============================================================
async def admin_stats_panel_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """wrapper لفتح إحصائيات الأدمن من الزر بدل الأمر"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return
    try:
        from handlers.admin_interface import show_main_stats_menu_v4
        await show_main_stats_menu_v4(update, context, query=query)
    except ImportError:
        await query.edit_message_text(
            "📊 لعرض الإحصائيات استخدم الأمر:\n/adminstats_v4",
            reply_markup=get_admin_menu_keyboard()
        )


# ============================================================
#  9. التقارير والشهادات والإشعارات
# ============================================================

async def admin_report_weekly_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """إنشاء تقرير أسبوعي فوري"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return
    
    await query.edit_message_text("⏳ جاري إنشاء التقرير الأسبوعي وإرساله بالإيميل...")
    
    try:
        from final_weekly_report import FinalWeeklyReportScheduler
        scheduler = FinalWeeklyReportScheduler()
        scheduler.generate_and_send_weekly_report()
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تقرير جديد", callback_data="admin_report_weekly")],
            [InlineKeyboardButton("⬅️ رجوع", callback_data="admin_show_tools_menu")]
        ])
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="✅ تم إنشاء وإرسال التقرير الأسبوعي\n📧 تحقق من إيميلك",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"خطأ في التقرير الأسبوعي: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"❌ خطأ: {str(e)[:200]}",
            reply_markup=get_admin_menu_keyboard()
        )


async def admin_report_monthly_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """إنشاء تقرير شهري (30 يوم)"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return
    
    await query.edit_message_text("⏳ جاري إنشاء التقرير الشهري (30 يوم)...")
    
    try:
        from final_weekly_report import FinalWeeklyReportScheduler
        scheduler = FinalWeeklyReportScheduler()
        scheduler.generate_and_send_monthly_report()
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ رجوع", callback_data="admin_show_tools_menu")]
        ])
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="✅ تم إنشاء وإرسال التقرير الشهري\n📧 تحقق من إيميلك",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"خطأ في التقرير الشهري: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"❌ خطأ: {str(e)[:200]}",
            reply_markup=get_admin_menu_keyboard()
        )


async def admin_report_certificates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض الطلاب المؤهلين للشهادات مع اختيار فردي"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return
    
    await query.edit_message_text("⏳ جاري إنشاء شهادات التفوق...")
    
    try:
        from final_weekly_report import FinalWeeklyReportGenerator
        from datetime import datetime, timedelta
        
        generator = FinalWeeklyReportGenerator()
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        certificates = generator.generate_certificates(start_date, end_date)
        
        if not certificates:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ رجوع", callback_data="admin_show_tools_menu")]
            ])
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="📋 لا يوجد طلاب مؤهلين للشهادات هذا الأسبوع\n\n"
                     "شروط الشهادة:\n"
                     "🥇 متفوق: معدل +80% مع +15 سؤال\n"
                     "🥈 متميز: معدل +65% مع +10 سؤال\n"
                     "📈 أكثر تحسناً: اتجاه متحسن مع +3 اختبارات",
                reply_markup=keyboard
            )
            return
        
        # حفظ الشهادات مع حالة التحديد
        context.user_data['pending_certificates'] = certificates
        context.user_data['cert_selected'] = [True] * len(certificates)
        
        await _show_cert_selection(context, query.message.chat_id)
        
    except Exception as e:
        logger.error(f"خطأ في الشهادات: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"❌ خطأ: {str(e)[:200]}",
            reply_markup=get_admin_menu_keyboard()
        )


async def _show_cert_selection(context, chat_id, message_id=None):
    """عرض قائمة الشهادات مع أزرار تحديد فردية"""
    certificates = context.user_data.get('pending_certificates', [])
    selected = context.user_data.get('cert_selected', [])
    
    cert_emoji = {'متفوق': '🥇', 'متميز': '🥈', 'أكثر تحسناً': '📈'}
    selected_count = sum(selected)
    
    text = f"🏆 شهادات التفوق — اختر اللي تبي ترسل لهم:\n"
    text += f"(محدد: {selected_count}/{len(certificates)})\n\n"
    
    keyboard = []
    for i, c in enumerate(certificates):
        check = "✅" if selected[i] else "⬜"
        emoji = cert_emoji.get(c['cert_type'], '🏅')
        btn_text = f"{check} {c['name']} — {emoji}{c['cert_type']} ({c['avg_score']}%)"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"ctoggle_{i}")])
    
    # أزرار التحكم
    keyboard.append([
        InlineKeyboardButton("☑️ تحديد الكل", callback_data="cert_select_all"),
        InlineKeyboardButton("⬜ إلغاء الكل", callback_data="cert_deselect_all"),
    ])
    
    if selected_count > 0:
        keyboard.append([InlineKeyboardButton(f"📨 إرسال الشهادات ({selected_count})", callback_data="admin_report_cert_confirm")])
    
    keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="admin_show_tools_menu")])
    
    markup = InlineKeyboardMarkup(keyboard)
    
    if message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text=text, reply_markup=markup
            )
            return
        except Exception:
            pass
    
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)


async def admin_cert_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تبديل تحديد طالب في الشهادات"""
    query = update.callback_query
    await query.answer()
    
    idx = int(query.data.replace("ctoggle_", ""))
    selected = context.user_data.get('cert_selected', [])
    
    if 0 <= idx < len(selected):
        selected[idx] = not selected[idx]
        context.user_data['cert_selected'] = selected
    
    await _show_cert_selection(context, query.message.chat_id, query.message.message_id)


async def admin_cert_select_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تحديد كل الشهادات"""
    query = update.callback_query
    await query.answer()
    n = len(context.user_data.get('pending_certificates', []))
    context.user_data['cert_selected'] = [True] * n
    await _show_cert_selection(context, query.message.chat_id, query.message.message_id)


async def admin_cert_deselect_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """إلغاء تحديد كل الشهادات"""
    query = update.callback_query
    await query.answer()
    n = len(context.user_data.get('pending_certificates', []))
    context.user_data['cert_selected'] = [False] * n
    await _show_cert_selection(context, query.message.chat_id, query.message.message_id)


async def admin_report_cert_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """إرسال الشهادات المحددة فقط"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return
    
    certificates = context.user_data.get('pending_certificates', [])
    selected = context.user_data.get('cert_selected', [])
    
    if not certificates or not any(selected):
        await query.edit_message_text("❌ لم تحدد أي طالب", reply_markup=get_admin_menu_keyboard())
        return
    
    to_send = [c for i, c in enumerate(certificates) if i < len(selected) and selected[i]]
    
    await query.edit_message_text(f"📨 جاري إرسال {len(to_send)} شهادة...")
    
    sent = 0
    failed = 0
    
    for cert in to_send:
        try:
            telegram_id = cert['telegram_id']
            
            await context.bot.send_message(chat_id=telegram_id, text=cert['message'])
            
            import os
            if os.path.exists(cert['pdf_path']):
                with open(cert['pdf_path'], 'rb') as pdf_file:
                    await context.bot.send_document(
                        chat_id=telegram_id,
                        document=pdf_file,
                        filename=f"شهادة_{cert['name']}.pdf",
                        caption=f"🏆 شهادة {cert['cert_type']}"
                    )
            sent += 1
        except Exception as se:
            failed += 1
            logger.warning(f"فشل إرسال شهادة لـ {cert.get('name', '?')}: {se}")
    
    context.user_data['pending_certificates'] = []
    context.user_data['cert_selected'] = []
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ رجوع", callback_data="admin_show_tools_menu")]
    ])
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"✅ تم إرسال الشهادات\n📨 نجح: {sent}\n❌ فشل: {failed}",
        reply_markup=keyboard
    )


async def admin_report_notify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض الطلاب الضعاف مع خيار اختيار فردي"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return
    
    await query.edit_message_text("⏳ جاري تحديد الطلاب اللي يحتاجون متابعة...")
    
    try:
        from final_weekly_report import FinalWeeklyReportGenerator
        from datetime import datetime, timedelta
        
        generator = FinalWeeklyReportGenerator()
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        notifications = generator.get_students_needing_notification(start_date, end_date)
        
        if not notifications:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ رجوع", callback_data="admin_show_tools_menu")]
            ])
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="✅ لا يوجد طلاب يحتاجون إشعارات — أداء الجميع مقبول 👏",
                reply_markup=keyboard
            )
            return
        
        # حفظ الإشعارات مع حالة التحديد (الكل محدد افتراضياً)
        context.user_data['pending_notifications'] = notifications
        context.user_data['notify_selected'] = [True] * len(notifications)
        
        await _show_notify_selection(context, query.message.chat_id)
        
    except Exception as e:
        logger.error(f"خطأ في تحديد الإشعارات: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"❌ خطأ: {str(e)[:200]}",
            reply_markup=get_admin_menu_keyboard()
        )


async def _show_notify_selection(context, chat_id, message_id=None):
    """عرض قائمة الطلاب مع أزرار تحديد فردية"""
    notifications = context.user_data.get('pending_notifications', [])
    selected = context.user_data.get('notify_selected', [])
    
    type_emoji = {'ضعيف': '🔴', 'متسرع': '⚡', 'متوسط': '🟡', 'متراجع': '📉'}
    selected_count = sum(selected)
    
    text = f"📱 إشعارات الطلاب — اختر اللي تبي ترسل لهم:\n"
    text += f"(محدد: {selected_count}/{len(notifications)})\n\n"
    
    keyboard = []
    for i, n in enumerate(notifications):
        check = "✅" if selected[i] else "⬜"
        emoji = type_emoji.get(n['type'], '📌')
        btn_text = f"{check} {n['name']} — {emoji}{n['type']} ({n['avg_score']}%)"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"ntoggle_{i}")])
    
    # أزرار التحكم
    keyboard.append([
        InlineKeyboardButton("☑️ تحديد الكل", callback_data="notify_select_all"),
        InlineKeyboardButton("⬜ إلغاء الكل", callback_data="notify_deselect_all"),
    ])
    
    if selected_count > 0:
        keyboard.append([InlineKeyboardButton(f"📨 إرسال ({selected_count})", callback_data="admin_report_notify_confirm")])
    
    keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="admin_show_tools_menu")])
    
    markup = InlineKeyboardMarkup(keyboard)
    
    if message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text=text, reply_markup=markup
            )
            return
        except Exception:
            pass
    
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)


async def admin_notify_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تبديل تحديد طالب في الإشعارات"""
    query = update.callback_query
    await query.answer()
    
    idx = int(query.data.replace("ntoggle_", ""))
    selected = context.user_data.get('notify_selected', [])
    
    if 0 <= idx < len(selected):
        selected[idx] = not selected[idx]
        context.user_data['notify_selected'] = selected
    
    await _show_notify_selection(context, query.message.chat_id, query.message.message_id)


async def admin_notify_select_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تحديد الكل"""
    query = update.callback_query
    await query.answer()
    n = len(context.user_data.get('pending_notifications', []))
    context.user_data['notify_selected'] = [True] * n
    await _show_notify_selection(context, query.message.chat_id, query.message.message_id)


async def admin_notify_deselect_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """إلغاء تحديد الكل"""
    query = update.callback_query
    await query.answer()
    n = len(context.user_data.get('pending_notifications', []))
    context.user_data['notify_selected'] = [False] * n
    await _show_notify_selection(context, query.message.chat_id, query.message.message_id)


async def admin_report_notify_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """إرسال الإشعارات المحددة فقط"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return
    
    notifications = context.user_data.get('pending_notifications', [])
    selected = context.user_data.get('notify_selected', [])
    
    if not notifications or not any(selected):
        await query.edit_message_text(
            "❌ لم تحدد أي طالب",
            reply_markup=get_admin_menu_keyboard()
        )
        return
    
    # فلترة المحددين فقط
    to_send = [n for i, n in enumerate(notifications) if i < len(selected) and selected[i]]
    
    await query.edit_message_text(f"📨 جاري إرسال {len(to_send)} إشعار...")
    
    sent = 0
    failed = 0
    
    for notif in to_send:
        try:
            await context.bot.send_message(chat_id=notif['telegram_id'], text=notif['message'])
            sent += 1
        except Exception as se:
            failed += 1
            logger.warning(f"فشل إرسال إشعار لـ {notif.get('name', '?')}: {se}")
    
    context.user_data['pending_notifications'] = []
    context.user_data['notify_selected'] = []
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ رجوع", callback_data="admin_show_tools_menu")]
    ])
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"✅ تم إرسال الإشعارات التشجيعية\n📨 نجح: {sent}\n❌ فشل: {failed}",
        reply_markup=keyboard
    )


# ============================================================
#  10. إدارة مواعيد التحصيلي
# ============================================================

def _format_date_ar(d):
    """تنسيق التاريخ بالعربي (ميلادي + هجري)"""
    if not d:
        return "—"
    months = {1:'يناير', 2:'فبراير', 3:'مارس', 4:'أبريل', 5:'مايو', 6:'يونيو',
              7:'يوليو', 8:'أغسطس', 9:'سبتمبر', 10:'أكتوبر', 11:'نوفمبر', 12:'ديسمبر'}
    if isinstance(d, str):
        d = datetime.strptime(d, '%Y-%m-%d').date()
    greg = f"{d.day} {months.get(d.month, '')} {d.year}"
    try:
        from hijri_converter import Gregorian
        h = Gregorian(d.year, d.month, d.day).to_hijri()
        h_months = {1:'محرم',2:'صفر',3:'ربيع الأول',4:'ربيع الثاني',
                   5:'جمادى الأولى',6:'جمادى الآخرة',7:'رجب',8:'شعبان',
                   9:'رمضان',10:'شوال',11:'ذو القعدة',12:'ذو الحجة'}
        hijri = f"{h.day} {h_months.get(h.month, '')} {h.year}هـ"
        return f"{greg} ({hijri})"
    except Exception:
        return greg


async def admin_exam_schedule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض مواعيد التحصيلي مع خيارات الإدارة"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return

    try:
        from database.manager import get_exam_periods
    except ImportError:
        from manager import get_exam_periods

    periods = get_exam_periods()

    status_map = {'active': '🟢 مفعّل', 'upcoming': '🔜 قريباً', 'hidden': '🔴 مخفي'}

    if not periods:
        text = "⏳ مواعيد التحصيلي\n\nلا توجد فترات مضافة بعد"
    else:
        text = "⏳ إدارة مواعيد التحصيلي:\n\n"
        for p in periods:
            pid = p['id']
            name = p['period_name']
            status = status_map.get(p.get('status', 'active'), '❓')
            text += f"📋 [{pid}] {name}\n"
            text += f"   📅 {_format_date_ar(p.get('exam_start_date'))} — {_format_date_ar(p.get('exam_end_date'))}\n"
            text += f"   الحالة: {status}\n"
            if p.get('notes'):
                text += f"   💡 {p['notes']}\n"
            text += "\n"

    keyboard = []

    for p in periods:
        pid = p['id']
        name = p['period_name'][:12]
        current = p.get('status', 'active')

        row = []
        if current != 'active':
            row.append(InlineKeyboardButton(f"🟢 تفعيل", callback_data=f"exam_status_{pid}_active"))
        if current != 'upcoming':
            row.append(InlineKeyboardButton(f"🔜 قريباً", callback_data=f"exam_status_{pid}_upcoming"))
        if current != 'hidden':
            row.append(InlineKeyboardButton(f"🔴 إخفاء", callback_data=f"exam_status_{pid}_hidden"))
        if row:
            keyboard.append(row)

        keyboard.append([InlineKeyboardButton(f"🗑 حذف: {name}", callback_data=f"exam_delete_{pid}")])

    keyboard.append([InlineKeyboardButton("➕ إضافة فترة جديدة", callback_data="admin_exam_add")])
    keyboard.append([InlineKeyboardButton("⬅️ رجوع", callback_data="admin_show_tools_menu")])

    try:
        await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await context.bot.send_message(chat_id=query.message.chat_id, text=text, reply_markup=InlineKeyboardMarkup(keyboard))


async def admin_exam_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تبديل حالة فترة اختبار"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return

    parts = query.data.split("_")  # exam_status_{id}_{status}
    period_id = int(parts[2])
    new_status = parts[3]

    try:
        from database.manager import update_exam_period_status
    except ImportError:
        from manager import update_exam_period_status

    status_names = {'active': '🟢 مفعّل', 'upcoming': '🔜 قريباً', 'hidden': '🔴 مخفي'}

    if update_exam_period_status(period_id, new_status):
        await query.answer(f"✅ تم: {status_names.get(new_status, new_status)}", show_alert=True)
    else:
        await query.answer("❌ فشل التحديث", show_alert=True)

    await admin_exam_schedule_callback(update, context)


async def admin_exam_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """حذف فترة مع تأكيد"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return

    period_id = int(query.data.replace("exam_delete_", ""))

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأكيد الحذف", callback_data=f"exam_del_yes_{period_id}")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="admin_exam_schedule")]
    ])
    await query.edit_message_text(f"⚠️ متأكد من حذف الفترة [{period_id}]؟", reply_markup=keyboard)


async def admin_exam_delete_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تأكيد الحذف"""
    query = update.callback_query
    await query.answer()

    period_id = int(query.data.replace("exam_del_yes_", ""))

    try:
        from database.manager import delete_exam_period
    except ImportError:
        from manager import delete_exam_period

    if delete_exam_period(period_id):
        await query.answer("✅ تم الحذف", show_alert=True)
    else:
        await query.answer("❌ فشل الحذف", show_alert=True)

    await admin_exam_schedule_callback(update, context)


async def admin_exam_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """بدء إضافة فترة جديدة"""
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context):
        return ConversationHandler.END

    context.user_data['exam_add_step'] = 'waiting'

    text = (
        "➕ إضافة فترة اختبار جديدة\n\n"
        "أرسل البيانات بالتنسيق التالي:\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "اسم الفترة\n"
        "تاريخ بداية الاختبار\n"
        "تاريخ نهاية الاختبار\n"
        "تسجيل البنين (أو -)\n"
        "تسجيل البنات (أو -)\n"
        "تسجيل متأخر (أو -)\n"
        "آخر تسجيل (أو -)\n"
        "ملاحظات (أو -)\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📌 مثال:\n"
        "الفترة الأولى — تخصصات علمية\n"
        "2026-05-13\n"
        "2026-05-17\n"
        "2026-02-23\n"
        "2026-03-02\n"
        "2026-04-13\n"
        "2026-05-14\n"
        "ورقي\n\n"
        "أو /cancel_exam للإلغاء"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ إلغاء", callback_data="admin_exam_schedule")]
    ])
    await query.edit_message_text(text=text, reply_markup=keyboard)
    return EXAM_SCHEDULE_INPUT


async def admin_exam_add_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة إدخال بيانات الفترة الجديدة"""
    text = update.message.text.strip()

    if text == '/cancel_exam':
        context.user_data.pop('exam_add_step', None)
        await update.message.reply_text("تم الإلغاء", reply_markup=get_admin_menu_keyboard())
        return ConversationHandler.END

    lines = text.split('\n')

    if len(lines) < 3:
        await update.message.reply_text(
            "❌ البيانات ناقصة — أحتاج على الأقل:\n"
            "1. اسم الفترة\n"
            "2. بداية الاختبار (YYYY-MM-DD)\n"
            "3. نهاية الاختبار (YYYY-MM-DD)\n\n"
            "حاول مرة ثانية أو /cancel_exam"
        )
        return EXAM_SCHEDULE_INPUT

    def parse_date(s):
        s = s.strip()
        if s == '-' or not s:
            return None
        try:
            return datetime.strptime(s, '%Y-%m-%d').date()
        except ValueError:
            return None

    period_name = lines[0].strip()
    exam_start = parse_date(lines[1])
    exam_end = parse_date(lines[2])

    if not exam_start or not exam_end:
        await update.message.reply_text(
            "❌ تنسيق التاريخ غلط\n"
            "المطلوب: YYYY-MM-DD (مثال: 2026-05-13)\n\n"
            "حاول مرة ثانية أو /cancel_exam"
        )
        return EXAM_SCHEDULE_INPUT

    reg_boys = parse_date(lines[3]) if len(lines) > 3 else None
    reg_girls = parse_date(lines[4]) if len(lines) > 4 else None
    late_reg = parse_date(lines[5]) if len(lines) > 5 else None
    last_reg = parse_date(lines[6]) if len(lines) > 6 else None
    notes = lines[7].strip() if len(lines) > 7 and lines[7].strip() != '-' else None

    try:
        from database.manager import add_exam_period
    except ImportError:
        from manager import add_exam_period

    if add_exam_period(period_name, exam_start, exam_end, reg_boys, reg_girls, late_reg, last_reg, 'active', notes):
        result = f"✅ تم إضافة الفترة!\n\n"
        result += f"📋 {period_name}\n"
        result += f"📅 {_format_date_ar(exam_start)} — {_format_date_ar(exam_end)}\n"
        if reg_boys: result += f"👦 تسجيل بنين: {_format_date_ar(reg_boys)}\n"
        if reg_girls: result += f"👧 تسجيل بنات: {_format_date_ar(reg_girls)}\n"
        if late_reg: result += f"⚠️ تسجيل متأخر: {_format_date_ar(late_reg)}\n"
        if last_reg: result += f"🔒 آخر تسجيل: {_format_date_ar(last_reg)}\n"
        if notes: result += f"💡 {notes}\n"
        result += f"\nالحالة: 🟢 مفعّل"

        await update.message.reply_text(result, reply_markup=get_admin_menu_keyboard())
    else:
        await update.message.reply_text("❌ فشل في الإضافة", reply_markup=get_admin_menu_keyboard())

    context.user_data.pop('exam_add_step', None)
    return ConversationHandler.END


async def cancel_exam_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """إلغاء إضافة فترة"""
    context.user_data.pop('exam_add_step', None)
    await update.message.reply_text("تم الإلغاء", reply_markup=get_admin_menu_keyboard())
    return ConversationHandler.END


# ============================================================
#  11. إعدادات البوت
# ============================================================

async def admin_bot_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض إعدادات البوت"""
    query = update.callback_query
    await query.answer()

    if not await check_admin_privileges(update, context):
        return

    try:
        from database.manager import get_bot_setting
    except ImportError:
        from manager import get_bot_setting

    deletion_status = get_bot_setting('allow_account_deletion', 'off')
    deletion_icon = "🟢 مفعّل" if deletion_status == 'on' else "🔴 مقفل"
    deletion_btn_text = "🔴 قفل حذف الحساب" if deletion_status == 'on' else "🟢 فتح حذف الحساب"

    text = (
        "⚙️ إعدادات البوت\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🗑 حذف الحساب: {deletion_icon}\n"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(deletion_btn_text, callback_data="admin_toggle_deletion")],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="admin_show_tools_menu")],
    ])

    await query.edit_message_text(text=text, reply_markup=keyboard)


async def admin_toggle_deletion_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تبديل حالة حذف الحساب"""
    query = update.callback_query
    await query.answer()

    if not await check_admin_privileges(update, context):
        return

    try:
        from database.manager import get_bot_setting, set_bot_setting
    except ImportError:
        from manager import get_bot_setting, set_bot_setting

    current = get_bot_setting('allow_account_deletion', 'off')
    new_value = 'off' if current == 'on' else 'on'
    set_bot_setting('allow_account_deletion', new_value)

    new_icon = "🟢 مفعّل" if new_value == 'on' else "🔴 مقفل"
    new_btn = "🔴 قفل حذف الحساب" if new_value == 'on' else "🟢 فتح حذف الحساب"

    text = (
        "⚙️ إعدادات البوت\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🗑 حذف الحساب: {new_icon}\n\n"
        f"✅ تم التحديث بنجاح"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(new_btn, callback_data="admin_toggle_deletion")],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="admin_show_tools_menu")],
    ])

    await query.edit_message_text(text=text, reply_markup=keyboard)
