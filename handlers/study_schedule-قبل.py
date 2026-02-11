#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
نظام جدول المذاكرة — كل شي أزرار بدون ConversationHandler
"""

import logging
import io
import random
from datetime import datetime, date, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

logger = logging.getLogger(__name__)

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

DAY_NAMES = {
    0: 'الاثنين', 1: 'الثلاثاء', 2: 'الأربعاء',
    3: 'الخميس', 4: 'الجمعة', 5: 'السبت', 6: 'الأحد'
}

WEEK_NAMES = {
    1:'الأول', 2:'الثاني', 3:'الثالث', 4:'الرابع', 5:'الخامس',
    6:'السادس', 7:'السابع', 8:'الثامن', 9:'التاسع', 10:'العاشر',
    11:'الحادي عشر', 12:'الثاني عشر'
}

SUBJECTS = ['كيمياء', 'كيمياء 1', 'كيمياء 2', 'كيمياء 3', 'أحياء', 'فيزياء', 'رياضيات']

MOTIVATIONAL_QUOTES = [
    "إن أعظم مجد تصنعه لنفسك هو أن تعمل بصمت حتى تحصل عليه",
    "لا يهم كم مرة تعثرت، المهم أن تنهض من جديد",
    "لا تستلم، ستشكر نفسك على تعبك لاحقاً",
    "كل شيء يستحق الحصول عليه يستحق العمل من أجله",
    "افرح بالأمل، ثابر بالعمل، قاوم الملل، فقريباً سوف تصل",
    "النجاح العظيم يستغرق وقتاً، لا تتراجع أبداً",
]


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


def _progress_bar(pct):
    filled = int(pct / 10)
    return "▓" * filled + "░" * (10 - filled)


def _reshape_arabic(text):
    """تحويل النص العربي للعرض الصحيح في PDF"""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        reshaped = arabic_reshaper.reshape(str(text))
        return get_display(reshaped)
    except ImportError:
        return str(text)
    except Exception:
        return str(text)


# ============================================================
#  1. القائمة الرئيسية
# ============================================================
async def study_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


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
    row1 = [InlineKeyboardButton(s, callback_data=f"study_subj_{s}") for s in SUBJECTS[:4]]
    row2 = [InlineKeyboardButton(s, callback_data=f"study_subj_{s}") for s in SUBJECTS[4:]]
    keyboard = [row1, row2, [InlineKeyboardButton("❌ إلغاء", callback_data="study_menu")]]
    await _safe_edit(context, query.message.chat_id, query.message.message_id, text, InlineKeyboardMarkup(keyboard))


# ============================================================
#  3. الخطوة 2: المدة
# ============================================================
async def study_subject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    subject = query.data.replace("study_subj_", "")
    context.user_data['study_subject'] = subject
    text = (
        f"📖 المادة: <b>{subject}</b>\n\n"
        f"📆 <b>الخطوة 2 من 3:</b> اختر مدة الجدول\n"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("أسبوعين", callback_data="study_dur_2"),
         InlineKeyboardButton("شهر (4 أسابيع)", callback_data="study_dur_4")],
        [InlineKeyboardButton("شهرين (8 أسابيع)", callback_data="study_dur_8"),
         InlineKeyboardButton("3 أشهر (12 أسبوع)", callback_data="study_dur_12")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="study_menu")],
    ])
    await _safe_edit(context, query.message.chat_id, query.message.message_id, text, keyboard)


# ============================================================
#  4. الخطوة 3: أيام الراحة
# ============================================================
async def study_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    weeks = int(query.data.replace("study_dur_", ""))
    context.user_data['study_weeks'] = weeks
    if 'study_rest_days' not in context.user_data:
        context.user_data['study_rest_days'] = [4]
    await _show_rest_days(context, query.message.chat_id, query.message.message_id)


async def _show_rest_days(context, chat_id, message_id):
    subject = context.user_data.get('study_subject', 'كيمياء')
    weeks = context.user_data.get('study_weeks', 4)
    selected = context.user_data.get('study_rest_days', [4])

    total_days = weeks * 7
    rest_total = weeks * len(selected)
    study_total = total_days - rest_total

    day_order = [6, 0, 1, 2, 3, 4, 5]
    status_lines = ""
    for d in day_order:
        if d in selected:
            status_lines += f"   🛋 {DAY_NAMES[d]}: <b>راحة</b>\n"
        else:
            status_lines += f"   📚 {DAY_NAMES[d]}: مذاكرة\n"

    text = (
        f"📖 المادة: <b>{subject}</b> | ⏱ {weeks} أسابيع\n\n"
        f"🛋 <b>الخطوة 3 من 3:</b> اختر أيام الراحة\n"
        f"(اضغط على اليوم لتحويله راحة/مذاكرة)\n\n"
        f"{status_lines}\n"
        f"📚 أيام المذاكرة: <b>{study_total}</b> يوم\n"
        f"🛋 أيام الراحة: <b>{rest_total}</b> يوم\n"
    )

    row1, row2 = [], []
    for i, d in enumerate(day_order):
        label = f"🛋 {DAY_NAMES[d]}" if d in selected else f"📚 {DAY_NAMES[d]}"
        btn = InlineKeyboardButton(label, callback_data=f"study_rest_{d}")
        if i < 4:
            row1.append(btn)
        else:
            row2.append(btn)

    keyboard = [
        row1, row2,
        [InlineKeyboardButton(f"✅ تأكيد ({study_total} يوم مذاكرة)", callback_data="study_confirm_create")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="study_menu")],
    ]
    await _safe_edit(context, chat_id, message_id, text, InlineKeyboardMarkup(keyboard))


async def study_rest_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    day_num = int(query.data.replace("study_rest_", ""))
    selected = context.user_data.get('study_rest_days', [4])

    if day_num in selected:
        selected.remove(day_num)
        await query.answer(f"📚 {DAY_NAMES[day_num]}: مذاكرة")
    else:
        if len(selected) >= 3:
            await query.answer("⚠️ أقصى 3 أيام راحة", show_alert=True)
            return
        selected.append(day_num)
        await query.answer(f"🛋 {DAY_NAMES[day_num]}: راحة")

    context.user_data['study_rest_days'] = selected
    await _show_rest_days(context, query.message.chat_id, query.message.message_id)


# ============================================================
#  5. تأكيد الإنشاء
# ============================================================
async def study_confirm_create_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    subject = context.user_data.get('study_subject', 'كيمياء')
    weeks = context.user_data.get('study_weeks', 4)
    rest_days = context.user_data.get('study_rest_days', [4])

    today = date.today()
    if today.weekday() == 6:
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


# ============================================================
#  6. عرض الأسبوع
# ============================================================
async def study_view_week_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    week_num = int(query.data.replace("study_view_week_", ""))
    await _show_week(context, user_id, chat_id, query.message.message_id, week_num)


async def _show_week(context, user_id, chat_id, message_id, week_num):
    plan = get_active_study_plan(user_id)
    if not plan:
        await _safe_edit(context, chat_id, message_id, "📅 لا يوجد جدول نشط",
            InlineKeyboardMarkup([[InlineKeyboardButton("🆕 إنشاء جدول", callback_data="study_new_plan")]]))
        return

    days = get_study_plan_days(plan['id'], week_num)
    if not days:
        await _safe_edit(context, chat_id, message_id, "⚠️ لا توجد بيانات لهذا الأسبوع",
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
            text += f"🛋 {day['day_name']} {date_str} — <b>راحة</b>\n"
        elif day['is_completed']:
            line = f"✅ {day['day_name']} {date_str}"
            if day['pages']:
                line += f" — ص {day['pages']}"
            if day['notes']:
                line += f" 📝"
            text += line + "\n"
        else:
            text += f"⬜ {day['day_name']} {date_str}\n"

        if not is_rest:
            if day['is_completed']:
                btn_label = f"↩️ إلغاء {day['day_name']} {date_str}"
            else:
                btn_label = f"✅ إنجاز {day['day_name']} {date_str}"
            day_buttons.append([InlineKeyboardButton(
                btn_label, callback_data=f"study_toggle_{day['id']}_w{week_num}"
            )])

    pct = stats.get('progress_pct', 0)
    completed = stats.get('completed_days', 0)
    study_days_count = stats.get('study_days', 0)
    text += f"\n📊 {_progress_bar(pct)} {pct}% ({completed}/{study_days_count})"

    nav_row = []
    if week_num > 1:
        nav_row.append(InlineKeyboardButton("◀ السابق", callback_data=f"study_view_week_{week_num - 1}"))
    if week_num < total_weeks:
        nav_row.append(InlineKeyboardButton("التالي ▶", callback_data=f"study_view_week_{week_num + 1}"))

    keyboard = day_buttons
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton("🔙 قائمة المذاكرة", callback_data="study_menu")])

    await _safe_edit(context, chat_id, message_id, text, InlineKeyboardMarkup(keyboard))


# ============================================================
#  7. تبديل يوم
# ============================================================
async def study_toggle_day_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.replace("study_toggle_", "").split("_w")
    day_id = int(parts[0])
    week_num = int(parts[1])
    toggle_study_day(day_id)
    await query.answer("تم التحديث ✅")
    await _show_week(context, query.from_user.id, query.message.chat_id, query.message.message_id, week_num)


# ============================================================
#  8. تسجيل إنجاز اليوم
# ============================================================
async def study_record_today_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    plan = get_active_study_plan(user_id)
    if not plan:
        await _safe_edit(context, chat_id, query.message.message_id, "📅 لا يوجد جدول نشط",
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
        await _safe_edit(context, chat_id, query.message.message_id, "📅 اليوم ليس ضمن فترة الجدول",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="study_menu")]]))
        return

    if today_day.get('is_rest_day', False):
        await _safe_edit(context, chat_id, query.message.message_id, "🛋 اليوم يوم راحة! استمتع بوقتك 😊",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="study_menu")]]))
        return

    was_completed = today_day['is_completed']
    toggle_study_day(today_day['id'])
    week = today_day['week_number']

    if was_completed:
        text = f"⬜ تم إلغاء إنجاز اليوم ({today_day['day_name']})"
    else:
        text = f"✅ <b>تم تسجيل إنجاز اليوم!</b>\n\n📅 {today_day['day_name']} — {today.strftime('%Y-%m-%d')}\n\nاستمر! 💪🔥"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 عرض الجدول", callback_data=f"study_view_week_{week}")],
        [InlineKeyboardButton("🔙 قائمة المذاكرة", callback_data="study_menu")],
    ])
    await _safe_edit(context, chat_id, query.message.message_id, text, keyboard)


# ============================================================
#  9. حذف الجدول
# ============================================================
async def study_delete_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _safe_edit(context, query.message.chat_id, query.message.message_id,
        "⚠️ هل أنت متأكد من حذف جدول المذاكرة؟\n\nسيتم حذف جميع بيانات التقدم.",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 نعم، احذف", callback_data="study_delete_confirm")],
            [InlineKeyboardButton("🔙 لا، رجوع", callback_data="study_menu")],
        ]))


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
#  10. تصدير PDF
# ============================================================
async def study_export_pdf_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⏳ جاري إنشاء PDF...")
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    plan = get_active_study_plan(user_id)
    if not plan:
        await _safe_edit(context, chat_id, query.message.message_id, "📅 لا يوجد جدول نشط",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="study_menu")]]))
        return

    all_days = get_study_plan_days(plan['id'])
    stats = get_study_plan_stats(plan['id'])

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
            filename=f"study_plan_{plan['subject']}.pdf",
            caption=f"📅 جدول مذاكرة {plan['subject']} — {plan['num_weeks']} أسابيع"
        )
    except Exception as e:
        logger.error(f"[StudySchedule] PDF error: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"❌ خطأ في إنشاء PDF: {str(e)[:200]}")


# ============================================================
#  PDF — مع RTL عربي
# ============================================================
def _ensure_arabic_font():
    """تحميل وتسجيل خط عربي — يحمّل الخط لو مو موجود"""
    import os
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # تحقق لو مسجل مسبقاً
    try:
        pdfmetrics.getFont('ArabicFont')
        return True
    except KeyError:
        pass

    # مسارات محتملة
    search_paths = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
        '/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf',
        '/usr/share/fonts/TTF/DejaVuSans.ttf',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'DejaVuSans.ttf'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts', 'DejaVuSans.ttf'),
        '/opt/render/project/src/DejaVuSans.ttf',
        '/opt/render/project/src/fonts/DejaVuSans.ttf',
        'DejaVuSans.ttf',
        'fonts/DejaVuSans.ttf',
    ]

    font_path = None
    for fp in search_paths:
        if os.path.exists(fp):
            font_path = fp
            logger.info(f"[StudySchedule] Found font: {fp}")
            break

    # لو ما لقينا — نبحث بالنظام
    if not font_path:
        try:
            import subprocess
            result = subprocess.run(
                ['find', '/usr', '-name', '*.ttf', '-path', '*ejavu*'],
                capture_output=True, text=True, timeout=10
            )
            lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
            if lines:
                font_path = lines[0]
                logger.info(f"[StudySchedule] Found font via search: {font_path}")
        except Exception:
            pass

    # لو بعد ما لقينا — نحمّل
    if not font_path:
        download_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
        os.makedirs(download_dir, exist_ok=True)
        font_path = os.path.join(download_dir, 'DejaVuSans.ttf')

        if not os.path.exists(font_path):
            try:
                import urllib.request
                url = "https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans.ttf"
                logger.info(f"[StudySchedule] Downloading font from GitHub...")
                urllib.request.urlretrieve(url, font_path)
                logger.info(f"[StudySchedule] Font downloaded: {font_path} ({os.path.getsize(font_path)} bytes)")
            except Exception as e:
                logger.error(f"[StudySchedule] Font download failed: {e}")
                return False

    if not os.path.exists(font_path):
        logger.error(f"[StudySchedule] Font not found: {font_path}")
        return False

    try:
        pdfmetrics.registerFont(TTFont('ArabicFont', font_path))
        logger.info(f"[StudySchedule] Registered ArabicFont: {font_path}")
    except Exception as e:
        logger.error(f"[StudySchedule] Register failed: {e}")
        return False

    # Bold
    bold_path = font_path.replace('Sans.ttf', 'Sans-Bold.ttf')
    try:
        if os.path.exists(bold_path):
            pdfmetrics.registerFont(TTFont('ArabicFontBold', bold_path))
        else:
            # نحمّل Bold بعد
            bold_dl = font_path.replace('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf')
            if not os.path.exists(bold_dl):
                try:
                    import urllib.request
                    url = "https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans-Bold.ttf"
                    urllib.request.urlretrieve(url, bold_dl)
                    pdfmetrics.registerFont(TTFont('ArabicFontBold', bold_dl))
                except Exception:
                    pdfmetrics.registerFont(TTFont('ArabicFontBold', font_path))
            else:
                pdfmetrics.registerFont(TTFont('ArabicFontBold', bold_dl))
    except Exception:
        pdfmetrics.registerFont(TTFont('ArabicFontBold', font_path))

    return True


def generate_study_pdf(plan, all_days, stats, student_name, bot_username):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas as canv
    from reportlab.lib.utils import ImageReader

    # تحميل الخط العربي
    if not _ensure_arabic_font():
        raise RuntimeError("لم يتم العثور على خط عربي")

    buf = io.BytesIO()
    width, height = landscape(A4)
    c = canv.Canvas(buf, pagesize=landscape(A4))
    ar = _reshape_arabic

    rest_str = plan.get('rest_days', '')
    rest_names = []
    if rest_str:
        for d in rest_str.split(','):
            if d.strip().isdigit():
                rest_names.append(DAY_NAMES.get(int(d.strip()), ''))
    rest_display = ar('، '.join(rest_names)) if rest_names else ar('لا يوجد')
    study_days_count = stats.get('study_days', 0)

    _draw_cover(c, width, height, plan, student_name, bot_username, rest_display, study_days_count, ar)
    c.showPage()

    weeks_data = {}
    for day in all_days:
        weeks_data.setdefault(day['week_number'], []).append(day)

    week_nums = sorted(weeks_data.keys())
    for i in range(0, len(week_nums), 4):
        batch = week_nums[i:i+4]
        _draw_weeks_page(c, width, height, plan, weeks_data, batch, ar)
        c.showPage()

    c.save()
    return buf.getvalue()


def _draw_cover(c, width, height, plan, student_name, bot_username, rest_display, study_days, ar):
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader

    c.setFillColor(colors.HexColor('#f8f9fa'))
    c.rect(0, 0, width, height, fill=1)

    c.setFillColor(colors.HexColor('#2c3e50'))
    c.rect(0, height - 80, width, 80, fill=1)
    c.setFillColor(colors.white)
    c.setFont('ArabicFontBold', 22)
    c.drawCentredString(width/2, height-35, ar("بوت كيم تحصيلي"))
    c.setFont('ArabicFont', 14)
    c.drawCentredString(width/2, height-60, ar("إعداد: أ. حسين الموسى"))

    c.setFillColor(colors.HexColor('#2c3e50'))
    c.setFont('ArabicFontBold', 36)
    c.drawCentredString(width/2, height-170, ar("جدول مذاكرة"))
    c.setFillColor(colors.HexColor('#e74c3c'))
    c.setFont('ArabicFontBold', 42)
    c.drawCentredString(width/2, height-230, ar(plan['subject']))

    c.setFillColor(colors.HexColor('#555555'))
    c.setFont('ArabicFont', 15)
    y = height - 300
    c.drawCentredString(width/2, y, ar(f"المدة: {plan['num_weeks']} أسابيع — أيام المذاكرة: {study_days} يوم"))
    y -= 28
    c.drawCentredString(width/2, y, ar("أيام الراحة: ") + rest_display)
    y -= 28
    c.drawCentredString(width/2, y, ar(f"البداية: {plan['start_date'].strftime('%Y-%m-%d')}"))
    if student_name:
        y -= 28
        c.drawCentredString(width/2, y, ar(f"الطالب/ة: {student_name}"))

    c.setFillColor(colors.HexColor('#34495e'))
    c.roundRect(width/2-200, 120, 400, 50, 10, fill=1)
    c.setFillColor(colors.white)
    c.setFont('ArabicFontBold', 16)
    c.drawCentredString(width/2, 138, ar("جدول مفرغ — اصنع جدولك بنفسك"))

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
    except ImportError:
        pass
    except Exception as e:
        logger.error(f"QR error: {e}")

    c.setFillColor(colors.HexColor('#555555'))
    c.setFont('ArabicFont', 10)
    c.drawCentredString(width-75, 12, f"@{bot_username}")
    c.setFillColor(colors.HexColor('#2c3e50'))
    c.rect(0, 0, width, 8, fill=1)


def _draw_weeks_page(c, width, height, plan, weeks_data, week_nums, ar):
    from reportlab.lib import colors
    margin = 30
    usable_w = width - 2 * margin
    usable_h = height - 100

    c.setFillColor(colors.HexColor('#2c3e50'))
    c.rect(0, height-40, width, 40, fill=1)
    c.setFillColor(colors.white)
    c.setFont('ArabicFontBold', 12)
    c.drawCentredString(width/2, height-27, ar(f"جدول مذاكرة {plan['subject']} — أ. حسين الموسى — بوت كيم تحصيلي"))

    table_w = (usable_w - 20) / 2
    table_h = (usable_h - 30) / 2

    # RTL: يمين أول
    positions = [
        (margin + table_w + 20, height - 60 - table_h),
        (margin, height - 60 - table_h),
        (margin + table_w + 20, height - 80 - 2*table_h),
        (margin, height - 80 - 2*table_h),
    ]

    for idx, wn in enumerate(week_nums[:4]):
        days = weeks_data.get(wn, [])
        px, py = positions[idx]
        _draw_week_table(c, px, py, table_w, table_h, wn, days, ar)

    c.setFillColor(colors.HexColor('#888888'))
    c.setFont('ArabicFont', 9)
    c.drawCentredString(width/2, 12, ar(random.choice(MOTIVATIONAL_QUOTES)))


def _draw_week_table(c, x, y, w, h, week_num, days, ar):
    from reportlab.lib import colors

    title = ar(f"الأسبوع {WEEK_NAMES.get(week_num, str(week_num))}")
    c.setFillColor(colors.HexColor('#2c3e50'))
    c.roundRect(x, y+h-25, w, 25, 5, fill=1)
    c.setFillColor(colors.white)
    c.setFont('ArabicFontBold', 11)
    c.drawCentredString(x+w/2, y+h-18, title)

    header_y = y + h - 50

    # أعمدة RTL: من اليمين لليسار
    cols_ar = [ar('الإنجاز'), ar('ملاحظات'), ar('الصفحة'), ar('التاريخ'), ar('اليوم')]
    cw = [w*0.12, w*0.34, w*0.16, w*0.18, w*0.20]

    c.setFillColor(colors.HexColor('#ecf0f1'))
    c.rect(x, header_y, w, 20, fill=1)
    c.setFillColor(colors.HexColor('#2c3e50'))
    c.setFont('ArabicFontBold', 8)

    cx = x
    for i, col in enumerate(cols_ar):
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

        if is_rest:
            cx += cw[0]
            rest_w = cw[1] + cw[2]
            c.setFillColor(colors.HexColor('#e67e22'))
            c.setFont('ArabicFontBold', 10)
            c.drawCentredString(cx + rest_w/2, ty, ar("راحة"))
            cx += rest_w
            c.setFillColor(colors.HexColor('#333333'))
            c.setFont('ArabicFont', 8)
            c.drawCentredString(cx + cw[3]/2, ty, day['day_date'].strftime('%m/%d'))
            cx += cw[3]
            c.drawCentredString(cx + cw[4]/2, ty, ar(day['day_name']))
        else:
            # الإنجاز
            if day['is_completed']:
                c.setFillColor(colors.HexColor('#27ae60'))
                c.setFont('ArabicFontBold', 14)
                c.drawCentredString(cx + cw[0]/2, ty - 1, "✓")
            else:
                c.setStrokeColor(colors.HexColor('#bdc3c7'))
                c.setLineWidth(0.8)
                bsz = 8
                bx = cx + cw[0]/2 - bsz/2
                c.rect(bx, ty - 1, bsz, bsz)
            cx += cw[0]

            # ملاحظات
            c.setFillColor(colors.HexColor('#333333'))
            c.setFont('ArabicFont', 7)
            notes_text = day.get('notes', '') or ''
            if notes_text:
                c.drawCentredString(cx + cw[1]/2, ty, ar(notes_text[:20]))
            cx += cw[1]

            # الصفحة
            c.setFont('ArabicFont', 8)
            pages_text = day.get('pages', '') or ''
            if pages_text:
                c.drawCentredString(cx + cw[2]/2, ty, ar(pages_text[:10]))
            cx += cw[2]

            # التاريخ
            c.drawCentredString(cx + cw[3]/2, ty, day['day_date'].strftime('%m/%d'))
            cx += cw[3]

            # اليوم
            c.drawCentredString(cx + cw[4]/2, ty, ar(day['day_name']))

    c.setStrokeColor(colors.HexColor('#2c3e50'))
    c.setLineWidth(1)
    c.rect(x, y, w, h-25)
