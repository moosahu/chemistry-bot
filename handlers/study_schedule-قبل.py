#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
نظام جدول المذاكرة — جدول مرن مع أيام راحة ومتابعة التقدم وتصدير PDF
"""

import logging
import io
import random
from datetime import datetime, date, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CallbackQueryHandler, MessageHandler,
    ConversationHandler, CommandHandler, filters
)

logger = logging.getLogger(__name__)

# ============================================================
#  Conversation States
# ============================================================
STUDY_SUBJECT_INPUT = 60
STUDY_WEEKS_INPUT = 61
STUDY_REST_DAYS_INPUT = 62
STUDY_PAGES_INPUT = 63
STUDY_NOTES_INPUT = 64
STUDY_CUSTOM_WEEKS = 65

# ============================================================
#  DB imports
# ============================================================
try:
    from database.manager import (
        create_study_plan, get_active_study_plan, get_study_plan_days,
        update_study_day, toggle_study_day, get_study_plan_stats,
        delete_study_plan
    )
except ImportError:
    from manager import (
        create_study_plan, get_active_study_plan, get_study_plan_days,
        update_study_day, toggle_study_day, get_study_plan_stats,
        delete_study_plan
    )

# ============================================================
#  ثوابت
# ============================================================
# weekday(): 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
DAY_NAMES = {
    0: 'الاثنين', 1: 'الثلاثاء', 2: 'الأربعاء',
    3: 'الخميس', 4: 'الجمعة', 5: 'السبت', 6: 'الأحد'
}

WEEK_NAMES = {
    1:'الأول', 2:'الثاني', 3:'الثالث', 4:'الرابع', 5:'الخامس',
    6:'السادس', 7:'السابع', 8:'الثامن', 9:'التاسع', 10:'العاشر',
    11:'الحادي عشر', 12:'الثاني عشر'
}

MOTIVATIONAL_QUOTES = [
    "إن أعظم مجد تصنعه لنفسك هو أن تعمل بصمت حتى تحصل عليه",
    "لا يهم كم مرة تعثرت، المهم أن تنهض من جديد",
    "لا تستلم، ستشكر نفسك على تعبك لاحقاً",
    "كل شيء يستحق الحصول عليه يستحق العمل من أجله",
    "افرح بالأمل، ثابر بالعمل، قاوم الملل، فقريباً سوف تصل",
    "النجاح العظيم يستغرق وقتاً، لا تتراجع أبداً",
]

# ============================================================
#  Helpers
# ============================================================
async def _safe_edit(context, chat_id, message_id, text, reply_markup=None):
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text=text, reply_markup=reply_markup, parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"[StudySchedule] Edit error: {e}")
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception:
            pass


async def _safe_send(context, chat_id, text, reply_markup=None):
    try:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"[StudySchedule] Send error: {e}")


def _progress_bar(pct):
    filled = int(pct / 10)
    return "▓" * filled + "░" * (10 - filled)


# ============================================================
#  1. القائمة الرئيسية لجدول المذاكرة
# ============================================================
async def study_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة جدول المذاكرة"""
    query = update.callback_query
    if query:
        await query.answer()

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    plan = get_active_study_plan(user_id)

    if plan:
        stats = get_study_plan_stats(plan['id'])
        pct = stats.get('progress_pct', 0)
        completed = stats.get('completed_days', 0)
        study_days = stats.get('study_days', 0)

        # أسماء أيام الراحة
        rest_str = plan.get('rest_days', '')
        rest_names = []
        if rest_str:
            for d in rest_str.split(','):
                if d.strip().isdigit():
                    rest_names.append(DAY_NAMES.get(int(d.strip()), ''))
        rest_display = '، '.join(rest_names) if rest_names else 'لا يوجد'

        text = (
            f"📅 <b>جدول المذاكرة</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"📖 المادة: <b>{plan['subject']}</b>\n"
            f"📆 البداية: {plan['start_date'].strftime('%Y-%m-%d')}\n"
            f"⏱ المدة: {plan['num_weeks']} أسابيع\n"
            f"🛋 أيام الراحة: {rest_display}\n\n"
            f"📊 التقدم: {_progress_bar(pct)} {pct}%\n"
            f"✅ {completed}/{study_days} يوم مذاكرة\n"
        )
        keyboard = [
            [InlineKeyboardButton("📋 عرض الجدول", callback_data="study_view_week_1")],
            [InlineKeyboardButton("📝 تسجيل إنجاز اليوم", callback_data="study_record_today")],
            [InlineKeyboardButton("📄 تصدير PDF", callback_data="study_export_pdf")],
            [InlineKeyboardButton("🆕 جدول جديد", callback_data="study_new_plan"),
             InlineKeyboardButton("🗑 حذف الجدول", callback_data="study_delete_plan")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")],
        ]
    else:
        text = (
            "📅 <b>جدول المذاكرة</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "لا يوجد جدول مذاكرة حالياً\n"
            "أنشئ جدولك الآن وابدأ رحلتك! 💪"
        )
        keyboard = [
            [InlineKeyboardButton("🆕 إنشاء جدول جديد", callback_data="study_new_plan")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")],
        ]

    msg_id = query.message.message_id if query else None
    if msg_id:
        await _safe_edit(context, chat_id, msg_id, text, InlineKeyboardMarkup(keyboard))
    else:
        await _safe_send(context, chat_id, text, InlineKeyboardMarkup(keyboard))


# ============================================================
#  2. إنشاء جدول — الخطوة 1: المادة
# ============================================================
async def study_new_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = (
        "📖 <b>إنشاء جدول مذاكرة جديد</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "<b>الخطوة 1 من 3:</b> اختر المادة\n"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 كيمياء", callback_data="study_subject_كيمياء")],
        [InlineKeyboardButton("✏️ اسم آخر (أرسل رسالة)", callback_data="study_subject_custom")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="study_menu")],
    ])
    await _safe_edit(context, query.message.chat_id, query.message.message_id, text, keyboard)
    return STUDY_SUBJECT_INPUT


async def study_subject_quick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    subject = query.data.replace("study_subject_", "")

    if subject == "custom":
        await _safe_edit(
            context, query.message.chat_id, query.message.message_id,
            "✏️ أرسل اسم المادة أو الكتاب:",
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="study_menu")]])
        )
        return STUDY_SUBJECT_INPUT

    context.user_data['study_subject'] = subject
    return await _show_duration_step(context, query.message.chat_id, query.message.message_id)


async def study_subject_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subject = update.message.text.strip()
    if len(subject) > 50:
        await _safe_send(context, update.effective_chat.id, "⚠️ الاسم طويل (أقصى 50 حرف). جرّب مرة ثانية:")
        return STUDY_SUBJECT_INPUT
    context.user_data['study_subject'] = subject
    msg = await update.message.reply_text("⏳")
    return await _show_duration_step(context, update.effective_chat.id, msg.message_id)


# ============================================================
#  3. الخطوة 2: مدة الجدول
# ============================================================
async def _show_duration_step(context, chat_id, message_id):
    subject = context.user_data.get('study_subject', 'كيمياء')
    text = (
        f"📖 المادة: <b>{subject}</b>\n\n"
        f"📆 <b>الخطوة 2 من 3:</b> اختر مدة الجدول\n"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 شهر (4 أسابيع)", callback_data="study_dur_4")],
        [InlineKeyboardButton("📋 شهرين (8 أسابيع)", callback_data="study_dur_8")],
        [InlineKeyboardButton("📋 3 أشهر (12 أسبوع)", callback_data="study_dur_12")],
        [InlineKeyboardButton("✏️ مخصص (أرسل رقم)", callback_data="study_dur_custom")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="study_menu")],
    ])
    await _safe_edit(context, chat_id, message_id, text, keyboard)
    return STUDY_WEEKS_INPUT


async def study_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    dur = query.data.replace("study_dur_", "")

    if dur == "custom":
        await _safe_edit(
            context, query.message.chat_id, query.message.message_id,
            "✏️ أرسل عدد الأسابيع (1-12):",
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="study_menu")]])
        )
        return STUDY_CUSTOM_WEEKS

    context.user_data['study_weeks'] = int(dur)
    return await _show_rest_days_step(context, query.message.chat_id, query.message.message_id)


async def study_custom_weeks_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        weeks = int(update.message.text.strip())
        if weeks < 1 or weeks > 12:
            raise ValueError()
    except ValueError:
        await _safe_send(context, update.effective_chat.id, "⚠️ أدخل رقم بين 1 و 12:")
        return STUDY_CUSTOM_WEEKS

    context.user_data['study_weeks'] = weeks
    msg = await update.message.reply_text("⏳")
    return await _show_rest_days_step(context, update.effective_chat.id, msg.message_id)


# ============================================================
#  4. الخطوة 3: أيام الراحة
# ============================================================
async def _show_rest_days_step(context, chat_id, message_id):
    subject = context.user_data.get('study_subject', 'كيمياء')
    weeks = context.user_data.get('study_weeks', 4)

    # الافتراضي: الجمعة راحة
    if 'study_rest_days' not in context.user_data:
        context.user_data['study_rest_days'] = [4]  # 4=Friday

    selected = context.user_data['study_rest_days']
    total_days = weeks * 7
    rest_total = weeks * len(selected)
    study_total = total_days - rest_total

    text = (
        f"📖 المادة: <b>{subject}</b> | ⏱ {weeks} أسابيع\n\n"
        f"🛋 <b>الخطوة 3 من 3:</b> اختر أيام الراحة\n"
        f"(اضغط على اليوم لتفعيله/تعطيله)\n\n"
        f"📚 أيام المذاكرة: <b>{study_total}</b> يوم\n"
        f"🛋 أيام الراحة: <b>{rest_total}</b> يوم\n"
    )

    # أزرار الأيام — ترتيب: أحد، اثنين، ... ، سبت
    day_order = [6, 0, 1, 2, 3, 4, 5]
    days_row1 = []
    days_row2 = []
    for i, d in enumerate(day_order):
        icon = "🛋" if d in selected else "📚"
        btn = InlineKeyboardButton(f"{icon} {DAY_NAMES[d]}", callback_data=f"study_rest_toggle_{d}")
        if i < 4:
            days_row1.append(btn)
        else:
            days_row2.append(btn)

    keyboard = [
        days_row1, days_row2,
        [InlineKeyboardButton(f"✅ تأكيد ({study_total} يوم مذاكرة)", callback_data="study_confirm_create")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="study_menu")],
    ]
    await _safe_edit(context, chat_id, message_id, text, InlineKeyboardMarkup(keyboard))
    return STUDY_REST_DAYS_INPUT


async def study_rest_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    day_num = int(query.data.replace("study_rest_toggle_", ""))
    selected = context.user_data.get('study_rest_days', [4])

    if day_num in selected:
        selected.remove(day_num)
        await query.answer()
    else:
        if len(selected) >= 3:
            await query.answer("⚠️ أقصى 3 أيام راحة", show_alert=True)
            return STUDY_REST_DAYS_INPUT
        selected.append(day_num)
        await query.answer()

    context.user_data['study_rest_days'] = selected
    return await _show_rest_days_step(context, query.message.chat_id, query.message.message_id)


async def study_confirm_create_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    subject = context.user_data.get('study_subject', 'كيمياء')
    weeks = context.user_data.get('study_weeks', 4)
    rest_days = context.user_data.get('study_rest_days', [4])

    # بدء من الأحد القادم (أو اليوم لو أحد)
    today = date.today()
    if today.weekday() == 6:  # Sunday
        start = today
    else:
        days_until_sunday = (6 - today.weekday()) % 7
        start = today + timedelta(days=days_until_sunday if days_until_sunday > 0 else 7)

    plan_id = create_study_plan(user_id, subject, weeks, start, rest_days)

    if plan_id:
        total_days = weeks * 7
        rest_total = weeks * len(rest_days)
        study_total = total_days - rest_total
        rest_names = [DAY_NAMES.get(d, '') for d in rest_days]

        text = (
            "✅ <b>تم إنشاء جدول المذاكرة!</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"📖 المادة: <b>{subject}</b>\n"
            f"📆 البداية: {start.strftime('%Y-%m-%d')}\n"
            f"⏱ المدة: {weeks} أسابيع\n"
            f"📚 أيام المذاكرة: <b>{study_total}</b> يوم\n"
            f"🛋 أيام الراحة: {'، '.join(rest_names) if rest_names else 'لا يوجد'}\n\n"
            "ابدأ رحلتك الآن! 💪🔥"
        )
    else:
        text = "❌ حدث خطأ في إنشاء الجدول. حاول مرة ثانية."

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 عرض الجدول", callback_data="study_view_week_1")],
        [InlineKeyboardButton("🔙 قائمة المذاكرة", callback_data="study_menu")],
    ])
    await _safe_edit(context, query.message.chat_id, query.message.message_id, text, keyboard)

    for k in ['study_subject', 'study_weeks', 'study_rest_days']:
        context.user_data.pop(k, None)
    return ConversationHandler.END


# ============================================================
#  5. عرض الجدول الأسبوعي
# ============================================================
async def study_view_week_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    chat_id = query.message.chat_id
    week_num = int(query.data.replace("study_view_week_", ""))

    plan = get_active_study_plan(user_id)
    if not plan:
        await _safe_edit(context, chat_id, query.message.message_id,
                         "📅 لا يوجد جدول نشط",
                         InlineKeyboardMarkup([[InlineKeyboardButton("🆕 إنشاء جدول", callback_data="study_new_plan")]]))
        return

    days = get_study_plan_days(plan['id'], week_num)
    if not days:
        await _safe_edit(context, chat_id, query.message.message_id,
                         "⚠️ لا توجد بيانات لهذا الأسبوع",
                         InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="study_menu")]]))
        return

    stats = get_study_plan_stats(plan['id'])
    total_weeks = plan['num_weeks']

    text = f"📅 <b>{plan['subject']} — الأسبوع {WEEK_NAMES.get(week_num, str(week_num))}</b>\n"
    text += "━━━━━━━━━━━━━━━━━━\n\n"

    day_buttons = []
    for day in days:
        date_str = day['day_date'].strftime('%m/%d')
        is_rest = day.get('is_rest_day', False)

        if is_rest:
            text += f"🛋 {day['day_name']} {date_str} — راحة\n"
        elif day['is_completed']:
            line = f"✅ {day['day_name']} {date_str}"
            if day['pages']:
                line += f" — ص {day['pages']}"
            if day['notes']:
                line += f" 📝"
            text += line + "\n"
        else:
            text += f"⬜ {day['day_name']} {date_str}\n"

        # زر تبديل فقط لأيام المذاكرة
        if not is_rest:
            toggle_icon = "⬜" if day['is_completed'] else "✅"
            day_buttons.append([InlineKeyboardButton(
                f"{toggle_icon} {day['day_name']} {date_str}",
                callback_data=f"study_toggle_{day['id']}_w{week_num}"
            )])

    # شريط التقدم
    pct = stats.get('progress_pct', 0)
    completed = stats.get('completed_days', 0)
    study_days = stats.get('study_days', 0)
    text += f"\n📊 {_progress_bar(pct)} {pct}% ({completed}/{study_days})"

    # أزرار التنقل
    nav_row = []
    if week_num > 1:
        nav_row.append(InlineKeyboardButton("◀ السابق", callback_data=f"study_view_week_{week_num - 1}"))
    if week_num < total_weeks:
        nav_row.append(InlineKeyboardButton("التالي ▶", callback_data=f"study_view_week_{week_num + 1}"))

    keyboard = day_buttons
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton("📝 تسجيل إنجاز اليوم", callback_data="study_record_today")])
    keyboard.append([InlineKeyboardButton("🔙 قائمة المذاكرة", callback_data="study_menu")])

    await _safe_edit(context, chat_id, query.message.message_id, text, InlineKeyboardMarkup(keyboard))


# ============================================================
#  6. تبديل حالة يوم
# ============================================================
async def study_toggle_day_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("تم التحديث ✅")
    parts = query.data.replace("study_toggle_", "").split("_w")
    day_id = int(parts[0])
    week_num = int(parts[1])
    toggle_study_day(day_id)
    query.data = f"study_view_week_{week_num}"
    await study_view_week_callback(update, context)


# ============================================================
#  7. تسجيل إنجاز اليوم
# ============================================================
async def study_record_today_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    plan = get_active_study_plan(user_id)
    if not plan:
        await _safe_edit(context, chat_id, query.message.message_id,
                         "📅 لا يوجد جدول نشط",
                         InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="study_menu")]]))
        return

    all_days = get_study_plan_days(plan['id'])
    today = date.today()
    today_day = None
    for d in all_days:
        if d['day_date'] == today:
            today_day = d
            break

    if not today_day:
        await _safe_edit(context, chat_id, query.message.message_id,
                         "📅 اليوم ليس ضمن فترة الجدول",
                         InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="study_menu")]]))
        return

    if today_day.get('is_rest_day', False):
        await _safe_edit(context, chat_id, query.message.message_id,
                         "🛋 اليوم يوم راحة! استمتع بوقتك 😊",
                         InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="study_menu")]]))
        return

    context.user_data['study_recording_day_id'] = today_day['id']
    context.user_data['study_recording_week'] = today_day['week_number']

    status = "✅ مكتمل" if today_day['is_completed'] else "⬜ لم يتم بعد"
    text = (
        f"📝 <b>تسجيل إنجاز اليوم</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 {today_day['day_name']} — {today.strftime('%Y-%m-%d')}\n"
        f"الحالة: {status}\n\n"
        f"أدخل أرقام الصفحات (اختياري):\n"
        f"💡 مثال: 1-20 أو ص15"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ تخطي الصفحات", callback_data="study_skip_pages")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="study_menu")],
    ])
    await _safe_edit(context, chat_id, query.message.message_id, text, keyboard)
    return STUDY_PAGES_INPUT


async def study_pages_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pages = update.message.text.strip()[:100]
    context.user_data['study_pages'] = pages
    msg = await update.message.reply_text(
        "📝 أدخل ملاحظاتك (اختياري):\n\n💡 مثال: باب الذرة - صعب شوي",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭ تخطي", callback_data="study_skip_notes")],
        ])
    )
    return STUDY_NOTES_INPUT


async def study_skip_pages_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['study_pages'] = None
    await _safe_edit(
        context, query.message.chat_id, query.message.message_id,
        "📝 أدخل ملاحظاتك (اختياري):\n\n💡 مثال: باب الذرة - صعب شوي",
        InlineKeyboardMarkup([[InlineKeyboardButton("⏭ تخطي", callback_data="study_skip_notes")]])
    )
    return STUDY_NOTES_INPUT


async def study_notes_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notes = update.message.text.strip()[:200]
    context.user_data['study_notes'] = notes
    return await _save_record(update, context, is_callback=False)


async def study_skip_notes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['study_notes'] = None
    return await _save_record(update, context, is_callback=True)


async def _save_record(update, context, is_callback=False):
    day_id = context.user_data.get('study_recording_day_id')
    pages = context.user_data.get('study_pages')
    notes = context.user_data.get('study_notes')
    week = context.user_data.get('study_recording_week', 1)

    if day_id:
        update_study_day(day_id, is_completed=True, pages=pages, notes=notes)

    text = "✅ <b>تم تسجيل إنجاز اليوم!</b>\n\n"
    if pages:
        text += f"📄 الصفحات: {pages}\n"
    if notes:
        text += f"📝 ملاحظات: {notes}\n"
    text += "\nاستمر! 💪🔥"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 عرض الجدول", callback_data=f"study_view_week_{week}")],
        [InlineKeyboardButton("🔙 قائمة المذاكرة", callback_data="study_menu")],
    ])

    if is_callback:
        query = update.callback_query
        await _safe_edit(context, query.message.chat_id, query.message.message_id, text, keyboard)
    else:
        await _safe_send(context, update.effective_chat.id, text, keyboard)

    for k in ['study_recording_day_id', 'study_pages', 'study_notes', 'study_recording_week']:
        context.user_data.pop(k, None)
    return ConversationHandler.END


# ============================================================
#  8. حذف الجدول
# ============================================================
async def study_delete_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "⚠️ هل أنت متأكد من حذف جدول المذاكرة؟\n\nسيتم حذف جميع بيانات التقدم."
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 نعم، احذف", callback_data="study_delete_confirm")],
        [InlineKeyboardButton("🔙 لا، رجوع", callback_data="study_menu")],
    ])
    await _safe_edit(context, query.message.chat_id, query.message.message_id, text, keyboard)


async def study_delete_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan = get_active_study_plan(query.from_user.id)
    if plan:
        delete_study_plan(plan['id'])
    await _safe_edit(context, query.message.chat_id, query.message.message_id,
                     "✅ تم حذف الجدول",
                     InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="study_menu")]]))


# ============================================================
#  9. تصدير PDF
# ============================================================
async def study_export_pdf_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⏳ جاري إنشاء PDF...")
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    plan = get_active_study_plan(user_id)
    if not plan:
        await _safe_edit(context, chat_id, query.message.message_id,
                         "📅 لا يوجد جدول نشط",
                         InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="study_menu")]]))
        return

    all_days = get_study_plan_days(plan['id'])
    stats = get_study_plan_stats(plan['id'])

    # جلب اسم الطالب
    student_name = ""
    db_manager = context.bot_data.get("DB_MANAGER")
    if db_manager:
        try:
            from handlers.registration import get_user_info
            info = get_user_info(db_manager, user_id)
            student_name = info.get('full_name', '') if info else ''
        except Exception:
            pass

    bot_username = (await context.bot.get_me()).username

    try:
        pdf_bytes = generate_study_pdf(plan, all_days, stats, student_name, bot_username)
        await context.bot.send_document(
            chat_id=chat_id,
            document=io.BytesIO(pdf_bytes),
            filename=f"جدول_مذاكرة_{plan['subject']}.pdf",
            caption=f"📅 جدول مذاكرة {plan['subject']} — {plan['num_weeks']} أسابيع"
        )
    except Exception as e:
        logger.error(f"[StudySchedule] PDF error: {e}")
        await _safe_send(context, chat_id, f"❌ خطأ في إنشاء PDF: {str(e)[:100]}")


# ============================================================
#  PDF Generation
# ============================================================
def generate_study_pdf(plan, all_days, stats, student_name, bot_username):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas as canv
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.utils import ImageReader

    for fp in ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
               '/usr/share/fonts/truetype/freefont/FreeSans.ttf']:
        try:
            pdfmetrics.registerFont(TTFont('ArabicFont', fp))
            bold = fp.replace('Sans.ttf', 'Sans-Bold.ttf') if 'DejaVu' in fp else fp
            pdfmetrics.registerFont(TTFont('ArabicFontBold', bold))
            break
        except Exception:
            continue

    buf = io.BytesIO()
    width, height = landscape(A4)
    c = canv.Canvas(buf, pagesize=landscape(A4))

    rest_str = plan.get('rest_days', '')
    rest_names = []
    if rest_str:
        for d in rest_str.split(','):
            if d.strip().isdigit():
                rest_names.append(DAY_NAMES.get(int(d.strip()), ''))
    rest_display = '، '.join(rest_names) if rest_names else 'لا يوجد'
    study_days_count = stats.get('study_days', 0)

    # ---- الغلاف ----
    _draw_cover(c, width, height, plan, student_name, bot_username, rest_display, study_days_count)
    c.showPage()

    # ---- الأسابيع ----
    weeks_data = {}
    for day in all_days:
        weeks_data.setdefault(day['week_number'], []).append(day)

    week_nums = sorted(weeks_data.keys())
    for i in range(0, len(week_nums), 4):
        batch = week_nums[i:i+4]
        _draw_weeks_page(c, width, height, plan, weeks_data, batch)
        c.showPage()

    c.save()
    return buf.getvalue()


def _draw_cover(c, width, height, plan, student_name, bot_username, rest_display, study_days):
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader

    c.setFillColor(colors.HexColor('#f8f9fa'))
    c.rect(0, 0, width, height, fill=1)

    # شريط علوي
    c.setFillColor(colors.HexColor('#2c3e50'))
    c.rect(0, height - 80, width, 80, fill=1)
    c.setFillColor(colors.white)
    c.setFont('ArabicFontBold', 22)
    c.drawCentredString(width/2, height-35, "بوت كيم تحصيلي")
    c.setFont('ArabicFont', 14)
    c.drawCentredString(width/2, height-60, "إعداد: أ. حسين الموسى")

    # العنوان
    c.setFillColor(colors.HexColor('#2c3e50'))
    c.setFont('ArabicFontBold', 36)
    c.drawCentredString(width/2, height-170, "جدول مذاكرة")
    c.setFillColor(colors.HexColor('#e74c3c'))
    c.setFont('ArabicFontBold', 42)
    c.drawCentredString(width/2, height-230, plan['subject'])

    # معلومات
    c.setFillColor(colors.HexColor('#555555'))
    c.setFont('ArabicFont', 15)
    y = height - 300
    c.drawCentredString(width/2, y, f"المدة: {plan['num_weeks']} أسابيع — أيام المذاكرة: {study_days} يوم")
    y -= 28
    c.drawCentredString(width/2, y, f"أيام الراحة: {rest_display}")
    y -= 28
    c.drawCentredString(width/2, y, f"البداية: {plan['start_date'].strftime('%Y-%m-%d')}")
    if student_name:
        y -= 28
        c.drawCentredString(width/2, y, f"الطالب/ة: {student_name}")

    # صندوق
    c.setFillColor(colors.HexColor('#34495e'))
    c.roundRect(width/2-200, 120, 400, 50, 10, fill=1)
    c.setFillColor(colors.white)
    c.setFont('ArabicFontBold', 16)
    c.drawCentredString(width/2, 138, "جدول مفرغ — اصنع جدولك بنفسك")

    # QR
    try:
        import qrcode
        qr = qrcode.QRCode(version=1, box_size=4, border=1)
        qr.add_data(f"https://t.me/{bot_username}")
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_buf = io.BytesIO()
        qr_img.save(qr_buf, format='PNG')
        qr_buf.seek(0)
        c.drawImage(ImageReader(qr_buf), width-120, 20, 90, 90)
        c.setFillColor(colors.HexColor('#555555'))
        c.setFont('ArabicFont', 8)
        c.drawCentredString(width-75, 12, f"@{bot_username}")
    except Exception as e:
        logger.error(f"QR error: {e}")

    c.setFillColor(colors.HexColor('#2c3e50'))
    c.rect(0, 0, width, 8, fill=1)


def _draw_weeks_page(c, width, height, plan, weeks_data, week_nums):
    from reportlab.lib import colors

    margin = 30
    usable_w = width - 2 * margin
    usable_h = height - 100

    c.setFillColor(colors.HexColor('#2c3e50'))
    c.rect(0, height-40, width, 40, fill=1)
    c.setFillColor(colors.white)
    c.setFont('ArabicFontBold', 12)
    c.drawCentredString(width/2, height-27, f"جدول مذاكرة {plan['subject']} — أ. حسين الموسى — بوت كيم تحصيلي")

    table_w = (usable_w - 20) / 2
    table_h = (usable_h - 30) / 2

    positions = [
        (margin, height - 60 - table_h),
        (margin + table_w + 20, height - 60 - table_h),
        (margin, height - 80 - 2*table_h),
        (margin + table_w + 20, height - 80 - 2*table_h),
    ]

    for idx, wn in enumerate(week_nums[:4]):
        days = weeks_data.get(wn, [])
        px, py = positions[idx]
        _draw_week_table(c, px, py, table_w, table_h, wn, days)

    c.setFillColor(colors.HexColor('#888888'))
    c.setFont('ArabicFont', 9)
    c.drawCentredString(width/2, 12, random.choice(MOTIVATIONAL_QUOTES))


def _draw_week_table(c, x, y, w, h, week_num, days):
    from reportlab.lib import colors

    title = f"الأسبوع {WEEK_NAMES.get(week_num, str(week_num))}"

    c.setFillColor(colors.HexColor('#2c3e50'))
    c.roundRect(x, y+h-25, w, 25, 5, fill=1)
    c.setFillColor(colors.white)
    c.setFont('ArabicFontBold', 11)
    c.drawCentredString(x+w/2, y+h-18, title)

    header_y = y + h - 50
    cols = ['اليوم', 'التاريخ', 'الصفحة', 'ملاحظات', 'الإنجاز']
    cw = [w*0.15, w*0.18, w*0.18, w*0.34, w*0.15]

    c.setFillColor(colors.HexColor('#ecf0f1'))
    c.rect(x, header_y, w, 20, fill=1)
    c.setFillColor(colors.HexColor('#2c3e50'))
    c.setFont('ArabicFontBold', 8)
    cx = x
    for i, col in enumerate(cols):
        c.drawCentredString(cx + cw[i]/2, header_y+6, col)
        cx += cw[i]

    row_h = (h - 55) / 7
    c.setFont('ArabicFont', 8)

    for idx, day in enumerate(days[:7]):
        ry = header_y - (idx+1) * row_h
        is_rest = day.get('is_rest_day', False)

        if is_rest:
            c.setFillColor(colors.HexColor('#fff3e0'))
        elif idx % 2 == 0:
            c.setFillColor(colors.HexColor('#ffffff'))
        else:
            c.setFillColor(colors.HexColor('#f8f9fa'))
        c.rect(x, ry, w, row_h, fill=1)

        c.setStrokeColor(colors.HexColor('#dee2e6'))
        c.setLineWidth(0.3)
        c.rect(x, ry, w, row_h)

        c.setFillColor(colors.HexColor('#333333'))
        ty = ry + row_h/2 - 3
        cx = x

        c.drawCentredString(cx+cw[0]/2, ty, day['day_name'][:8])
        cx += cw[0]
        c.drawCentredString(cx+cw[1]/2, ty, day['day_date'].strftime('%m/%d'))
        cx += cw[1]

        if is_rest:
            c.setFillColor(colors.HexColor('#e67e22'))
            c.setFont('ArabicFontBold', 9)
            rest_x = cx + (cw[2]+cw[3]+cw[4])/2
            c.drawCentredString(rest_x, ty, "راحة")
            c.setFont('ArabicFont', 8)
            c.setFillColor(colors.HexColor('#333333'))
        else:
            pages_text = day.get('pages', '') or ''
            c.drawCentredString(cx+cw[2]/2, ty, pages_text[:12])
            cx += cw[2]
            notes_text = day.get('notes', '') or ''
            c.drawCentredString(cx+cw[3]/2, ty, notes_text[:25])
            cx += cw[3]

            if day['is_completed']:
                c.setFillColor(colors.HexColor('#27ae60'))
                st = "✓"
            else:
                c.setFillColor(colors.HexColor('#bdc3c7'))
                st = "☐"
            c.setFont('ArabicFontBold', 12)
            c.drawCentredString(cx+cw[4]/2, ty, st)
            c.setFont('ArabicFont', 8)
            c.setFillColor(colors.HexColor('#333333'))

    c.setStrokeColor(colors.HexColor('#2c3e50'))
    c.setLineWidth(1)
    c.rect(x, y, w, h-25)


# ============================================================
#  10. Conversation Handler
# ============================================================
def get_study_schedule_conv_handler():
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(study_new_plan_callback, pattern=r"^study_new_plan$"),
            CallbackQueryHandler(study_record_today_callback, pattern=r"^study_record_today$"),
        ],
        states={
            STUDY_SUBJECT_INPUT: [
                CallbackQueryHandler(study_subject_quick_callback, pattern=r"^study_subject_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, study_subject_text_handler),
            ],
            STUDY_WEEKS_INPUT: [
                CallbackQueryHandler(study_duration_callback, pattern=r"^study_dur_"),
            ],
            STUDY_CUSTOM_WEEKS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, study_custom_weeks_handler),
            ],
            STUDY_REST_DAYS_INPUT: [
                CallbackQueryHandler(study_rest_toggle_callback, pattern=r"^study_rest_toggle_\d$"),
                CallbackQueryHandler(study_confirm_create_callback, pattern=r"^study_confirm_create$"),
            ],
            STUDY_PAGES_INPUT: [
                CallbackQueryHandler(study_skip_pages_callback, pattern=r"^study_skip_pages$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, study_pages_text_handler),
            ],
            STUDY_NOTES_INPUT: [
                CallbackQueryHandler(study_skip_notes_callback, pattern=r"^study_skip_notes$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, study_notes_text_handler),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(study_menu_callback, pattern=r"^study_menu$"),
            CommandHandler("cancel", lambda u, c: ConversationHandler.END),
        ],
        persistent=False,
        name="study_schedule_conversation"
    )
