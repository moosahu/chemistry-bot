#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
نظام جدول المذاكرة — مدمج
النظام القديم (تتبع + أيام راحة + عرض أسبوعي) + الجديد (مواد متعددة + صفحات + بطاقات PDF)
التدفق: اختيار المواد → الصفحات → المدة → أيام الراحة → تأكيد (DB + PDF)
"""

import logging
import io
import json
import random
from datetime import datetime, date, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

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
DAY_NAMES = {
    0: 'الاثنين', 1: 'الثلاثاء', 2: 'الأربعاء',
    3: 'الخميس', 4: 'الجمعة', 5: 'السبت', 6: 'الأحد'
}

WEEK_NAMES = {
    1:'الأول', 2:'الثاني', 3:'الثالث', 4:'الرابع', 5:'الخامس',
    6:'السادس', 7:'السابع', 8:'الثامن', 9:'التاسع', 10:'العاشر',
    11:'الحادي عشر', 12:'الثاني عشر'
}

SUBJECTS_POOL = [
    {'name': 'فيزياء', 'icon': '⚡', 'bg': '#E3F2FD', 'header': '#1565C0'},
    {'name': 'رياضيات', 'icon': '📐', 'bg': '#FFEBEE', 'header': '#C62828'},
    {'name': 'كيمياء', 'icon': '⚗', 'bg': '#E8F5E9', 'header': '#2E7D32'},
    {'name': 'أحياء', 'icon': '🌿', 'bg': '#FFF3E0', 'header': '#E65100'},
]

DEFAULT_PAGES = {
    'فيزياء': (6, 88),
    'رياضيات': (80, 175),
    'كيمياء': (178, 261),
    'أحياء': (264, 351),
}

TEMPLATE_PHRASES = [
    'ابدأ بقوة', 'أنت قادر', 'استمر', 'تقدم رائع', 'رائع',
    'ممتاز', 'واصل', 'ركز', 'أكمل', 'تمرن',
    'نصف الطريق', 'متميز', 'متقدم', 'حل وتدرب', 'واصل التميز',
    'قريب', 'شارفت', 'أيام قليلة', 'تقريباً', 'أنت مبدع',
]

MOTIVATIONAL_QUOTES = [
    "كل يوم تقترب من هدفك | النجاح بانتظارك | أنت قادر على التميز",
    "إن أعظم مجد تصنعه لنفسك هو أن تعمل بصمت حتى تحصل عليه",
    "لا تستلم، ستشكر نفسك على تعبك لاحقاً",
    "افرح بالأمل، ثابر بالعمل، قاوم الملل، فقريباً سوف تصل",
    "النجاح العظيم يستغرق وقتاً، لا تتراجع أبداً",
    "لا يهم كم مرة تعثرت، المهم أن تنهض من جديد",
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
    except Exception:
        try:
            await context.bot.send_message(
                chat_id=chat_id, text=text,
                reply_markup=reply_markup, parse_mode="HTML"
            )
        except Exception:
            pass


def _reshape_arabic(text):
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(str(text)))
    except ImportError:
        return str(text)
    except Exception:
        return str(text)


def _progress_bar(pct):
    filled = int(pct / 10)
    return "▓" * filled + "░" * (10 - filled)


def _clean_user_data(context):
    for k in ['sched_selected', 'sched_subjects', 'sched_pages_idx',
              'sched_pages_state', 'sched_total_days', 'sched_rest_days']:
        context.user_data.pop(k, None)


def _parse_subjects_json(subject_field):
    """يحلل حقل المادة — JSON (قديم) أو أسماء مفصولة بفاصلة (جديد) أو نص عادي"""
    if not subject_field:
        return None
    # محاولة JSON أولاً
    try:
        data = json.loads(subject_field)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    # أسماء مفصولة بفاصلة
    if ',' in subject_field:
        names = [n.strip() for n in subject_field.split(',')]
        return _reconstruct_subjects(names)
    return None


def _reconstruct_subjects(names):
    """يسترجع تفاصيل المواد الكاملة من الأسماء"""
    pool_map = {s['name']: s for s in SUBJECTS_POOL}
    result = []
    for name in names:
        if name in pool_map:
            s = pool_map[name]
            default = DEFAULT_PAGES.get(name, (1, 100))
            result.append({
                'name': s['name'], 'icon': s['icon'],
                'start': default[0], 'end': default[1],
                'bg': s['bg'], 'header': s['header'],
            })
    return result if result else None


def _display_subjects(plan):
    """يعرض اسم المادة/المواد من الخطة"""
    subject = plan.get('subject', '')
    data = _parse_subjects_json(subject)
    if data:
        return '، '.join(s.get('name', '') for s in data)
    return subject or 'كيمياء'


# ============================================================
#  1. القائمة الرئيسية — تعرض الخطة النشطة أو إنشاء جديد
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

        subj_display = _display_subjects(plan)

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
            f"📖 المواد: <b>{subj_display}</b>\n"
            f"📆 البداية: {plan['start_date'].strftime('%Y-%m-%d')}\n"
            f"⏱ المدة: {plan['num_weeks']} أسابيع\n"
            f"🛋 أيام الراحة: {rest_display}\n\n"
            f"📊 التقدم: {_progress_bar(pct)} {pct}%\n"
            f"✅ {completed}/{study_days} يوم مذاكرة\n"
        )
        keyboard = [
            [InlineKeyboardButton("📋 عرض الجدول", callback_data="study_view_week_1")],
            [InlineKeyboardButton("📝 تسجيل إنجاز اليوم", callback_data="study_record_today")],
            [InlineKeyboardButton("📄 تصدير PDF", callback_data="study_export_pdf"),
             InlineKeyboardButton("🖨 طباعة بطاقات", callback_data="study_print_cards")],
            [InlineKeyboardButton("🆕 جدول جديد", callback_data="sched_start"),
             InlineKeyboardButton("🗑 حذف الجدول", callback_data="study_delete_plan")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")],
        ]
    else:
        text = (
            "📅 <b>جدول المذاكرة</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "صمم جدول مذاكرتك وحمّله PDF جاهز للطباعة 🖨\n\n"
            "⚡ فيزياء  📐 رياضيات  ⚗ كيمياء  🌿 أحياء\n\n"
            "اختر المواد → حدد الصفحات → اختر المدة → أيام الراحة → جاهز! 💪"
        )
        keyboard = [
            [InlineKeyboardButton("🆕 إنشاء جدول مذاكرة", callback_data="sched_start")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")],
        ]

    msg_id = query.message.message_id if query else None
    if msg_id:
        await _safe_edit(context, chat_id, msg_id, text, InlineKeyboardMarkup(keyboard))
    else:
        await context.bot.send_message(
            chat_id=chat_id, text=text,
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
        )


# ============================================================
#  2. الخطوة 1 من 4: اختيار المواد
# ============================================================
async def sched_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data['sched_selected'] = [0, 1, 2, 3]  # الكل مختار
    context.user_data['sched_subjects'] = []
    context.user_data.pop('sched_pages_state', None)
    context.user_data.pop('sched_rest_days', None)

    await _show_subjects(context, query.message.chat_id, query.message.message_id)


async def _show_subjects(context, chat_id, message_id):
    selected = context.user_data.get('sched_selected', [])

    text = (
        "📅 <b>إنشاء جدول مذاكرة</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "<b>الخطوة 1 من 4:</b> اختر المواد\n"
        "(اضغط لتفعيل/تعطيل)\n\n"
    )
    for i, subj in enumerate(SUBJECTS_POOL):
        icon = "✅" if i in selected else "⬜"
        text += f"{icon} {subj['icon']} {subj['name']}\n"

    if selected:
        text += f"\n📚 المواد المختارة: <b>{len(selected)}</b>"

    rows = []
    for i in range(0, len(SUBJECTS_POOL), 2):
        row = []
        for j in range(i, min(i + 2, len(SUBJECTS_POOL))):
            subj = SUBJECTS_POOL[j]
            icon = "✅" if j in selected else "⬜"
            row.append(InlineKeyboardButton(
                f"{icon} {subj['icon']} {subj['name']}",
                callback_data=f"sched_subj_{j}"
            ))
        rows.append(row)

    if selected:
        rows.append([InlineKeyboardButton(
            f"▶ التالي: تحديد الصفحات ({len(selected)} مواد)",
            callback_data="sched_next_pages"
        )])
    rows.append([InlineKeyboardButton("❌ إلغاء", callback_data="study_menu")])

    await _safe_edit(context, chat_id, message_id, text, InlineKeyboardMarkup(rows))


async def sched_subj_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    idx = int(query.data.replace("sched_subj_", ""))
    selected = context.user_data.get('sched_selected', [])

    if idx in selected:
        if len(selected) <= 1:
            await query.answer("⚠️ لازم مادة واحدة على الأقل", show_alert=True)
            return
        selected.remove(idx)
    else:
        selected.append(idx)
        selected.sort()

    await query.answer()
    context.user_data['sched_selected'] = selected
    await _show_subjects(context, query.message.chat_id, query.message.message_id)


# ============================================================
#  3. الخطوة 2 من 4: إدخال الصفحات
# ============================================================
async def sched_next_pages_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data['sched_subjects'] = []
    context.user_data['sched_pages_idx'] = 0
    context.user_data['sched_pages_state'] = True

    await _show_pages_input(context, query.message.chat_id, query.message.message_id)


async def _show_pages_input(context, chat_id, message_id):
    selected = context.user_data.get('sched_selected', [])
    idx = context.user_data.get('sched_pages_idx', 0)
    done = context.user_data.get('sched_subjects', [])

    if idx >= len(selected):
        # انتهينا → اختيار المدة
        context.user_data['sched_pages_state'] = False
        await _show_duration(context, chat_id, message_id)
        return

    subj = SUBJECTS_POOL[selected[idx]]
    current = idx + 1
    total = len(selected)
    default = DEFAULT_PAGES.get(subj['name'], (1, 100))

    text = (
        f"📅 <b>إنشاء جدول مذاكرة</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>الخطوة 2 من 4:</b> حدد الصفحات ({current}/{total})\n\n"
    )

    for ds in done:
        text += f"✅ {ds['icon']} {ds['name']}: ص{ds['start']}-{ds['end']}\n"

    text += (
        f"\n{subj['icon']} <b>{subj['name']}</b>\n"
        f"أرسل رقم صفحة البداية والنهاية:\n"
        f"مثال: <code>{default[0]}-{default[1]}</code>\n"
    )

    keyboard = [
        [InlineKeyboardButton(
            f"📖 الافتراضي: ص{default[0]}-{default[1]}",
            callback_data=f"sched_def_{idx}"
        )],
        [InlineKeyboardButton("⏭ تخطي", callback_data="sched_skip_subj")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="sched_cancel")],
    ]
    await _safe_edit(context, chat_id, message_id, text, InlineKeyboardMarkup(keyboard))


async def sched_default_pages_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected = context.user_data.get('sched_selected', [])
    idx = context.user_data.get('sched_pages_idx', 0)
    if idx >= len(selected):
        return

    subj = SUBJECTS_POOL[selected[idx]]
    default = DEFAULT_PAGES.get(subj['name'], (1, 100))

    done = context.user_data.get('sched_subjects', [])
    done.append({
        'name': subj['name'], 'icon': subj['icon'],
        'start': default[0], 'end': default[1],
        'bg': subj['bg'], 'header': subj['header'],
    })
    context.user_data['sched_subjects'] = done
    context.user_data['sched_pages_idx'] = idx + 1

    await _show_pages_input(context, query.message.chat_id, query.message.message_id)


async def sched_pages_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('sched_pages_state'):
        return

    text = update.message.text.strip()
    selected = context.user_data.get('sched_selected', [])
    idx = context.user_data.get('sched_pages_idx', 0)

    if idx >= len(selected):
        context.user_data['sched_pages_state'] = False
        return

    parts = None
    for sep in ['-', ' ', '،', ',']:
        if sep in text:
            parts = text.split(sep, 1)
            break

    if not parts or len(parts) != 2:
        await update.message.reply_text(
            "⚠️ أدخل البداية والنهاية بـ -\nمثال: <code>6-88</code>",
            parse_mode="HTML"
        )
        return

    try:
        start = int(parts[0].strip().replace('ص', ''))
        end = int(parts[1].strip().replace('ص', ''))
        if start < 1 or end < start or end > 9999:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("⚠️ أرقام غير صحيحة", parse_mode="HTML")
        return

    subj = SUBJECTS_POOL[selected[idx]]
    done = context.user_data.get('sched_subjects', [])
    done.append({
        'name': subj['name'], 'icon': subj['icon'],
        'start': start, 'end': end,
        'bg': subj['bg'], 'header': subj['header'],
    })
    context.user_data['sched_subjects'] = done
    context.user_data['sched_pages_idx'] = idx + 1

    msg = await update.message.reply_text("⏳")
    await _show_pages_input(context, update.effective_chat.id, msg.message_id)


async def sched_skip_subj_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    idx = context.user_data.get('sched_pages_idx', 0)
    context.user_data['sched_pages_idx'] = idx + 1

    selected = context.user_data.get('sched_selected', [])
    done = context.user_data.get('sched_subjects', [])

    if idx + 1 >= len(selected) and not done:
        await _safe_edit(context, query.message.chat_id, query.message.message_id,
                         "⚠️ لازم مادة واحدة على الأقل",
                         InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="sched_start")]]))
        return

    await _show_pages_input(context, query.message.chat_id, query.message.message_id)


# ============================================================
#  4. الخطوة 3 من 4: اختيار المدة
# ============================================================
async def _show_duration(context, chat_id, message_id):
    done = context.user_data.get('sched_subjects', [])
    total_pages = sum(s['end'] - s['start'] + 1 for s in done)

    text = (
        "📅 <b>إنشاء جدول مذاكرة</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "<b>الخطوة 3 من 4:</b> اختر المدة\n\n"
    )
    for s in done:
        pages = s['end'] - s['start'] + 1
        text += f"{s['icon']} {s['name']}: ص{s['start']}-{s['end']} ({pages} صفحة)\n"

    text += f"\n📄 إجمالي: <b>{total_pages}</b> صفحة\n\n"

    for d in [15, 30, 60]:
        ppd = round(total_pages / d, 1)
        icon = '⚡' if d == 15 else '📋' if d == 30 else '📚'
        text += f"{icon} {d} يوم ≈ {ppd} ص/يوم\n"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ 15 يوم", callback_data="sched_dur_15"),
         InlineKeyboardButton("📋 30 يوم", callback_data="sched_dur_30")],
        [InlineKeyboardButton("📖 45 يوم", callback_data="sched_dur_45"),
         InlineKeyboardButton("📚 60 يوم", callback_data="sched_dur_60")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="sched_cancel")],
    ])
    await _safe_edit(context, chat_id, message_id, text, keyboard)


# ============================================================
#  5. الخطوة 4 من 4: أيام الراحة
# ============================================================
async def sched_dur_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اختيار المدة → الانتقال لأيام الراحة"""
    query = update.callback_query
    await query.answer()

    total_days = int(query.data.replace("sched_dur_", ""))
    context.user_data['sched_total_days'] = total_days

    if 'sched_rest_days' not in context.user_data:
        context.user_data['sched_rest_days'] = [4]  # الجمعة افتراضي

    await _show_rest_days(context, query.message.chat_id, query.message.message_id)


async def _show_rest_days(context, chat_id, message_id):
    done = context.user_data.get('sched_subjects', [])
    total_days = context.user_data.get('sched_total_days', 30)
    selected = context.user_data.get('sched_rest_days', [4])
    total_pages = sum(s['end'] - s['start'] + 1 for s in done)

    weeks = -(-total_days // 7)  # ceiling
    rest_total = weeks * len(selected)
    if rest_total > total_days:
        rest_total = total_days
    study_total = total_days - rest_total

    ppd = round(total_pages / study_total, 1) if study_total > 0 else 0
    subj_names = ' '.join(s['icon'] + s['name'] for s in done)

    text = (
        f"📅 <b>إنشاء جدول مذاكرة</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>الخطوة 4 من 4:</b> أيام الراحة\n"
        f"(اضغط لتفعيل/تعطيل)\n\n"
        f"📚 {subj_names}\n"
        f"📅 المدة: {total_days} يوم | 📄 {total_pages} صفحة\n\n"
        f"📚 أيام مذاكرة: <b>{study_total}</b> يوم (~{ppd} ص/يوم)\n"
        f"🛋 أيام راحة: <b>{rest_total}</b> يوم\n"
    )

    day_order = [6, 0, 1, 2, 3, 4, 5]  # Sun..Sat
    row1, row2 = [], []
    for i, d in enumerate(day_order):
        icon = "🛋" if d in selected else "📚"
        btn = InlineKeyboardButton(f"{icon} {DAY_NAMES[d]}", callback_data=f"sched_rest_{d}")
        if i < 4:
            row1.append(btn)
        else:
            row2.append(btn)

    keyboard = [
        row1, row2,
        [InlineKeyboardButton(f"✅ تأكيد وإنشاء ({study_total} يوم مذاكرة)", callback_data="sched_confirm")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="sched_cancel")],
    ]
    await _safe_edit(context, chat_id, message_id, text, InlineKeyboardMarkup(keyboard))


async def sched_rest_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    day_num = int(query.data.replace("sched_rest_", ""))
    selected = context.user_data.get('sched_rest_days', [4])

    if day_num in selected:
        selected.remove(day_num)
        await query.answer()
    else:
        if len(selected) >= 3:
            await query.answer("⚠️ أقصى 3 أيام راحة", show_alert=True)
            return
        selected.append(day_num)
        await query.answer()

    context.user_data['sched_rest_days'] = selected
    await _show_rest_days(context, query.message.chat_id, query.message.message_id)


# ============================================================
#  6. تأكيد — حفظ في قاعدة البيانات + إنشاء PDF بطاقات
# ============================================================
async def sched_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⏳ جاري إنشاء الجدول...")

    user_id = query.from_user.id
    chat_id = query.message.chat_id
    done = context.user_data.get('sched_subjects', [])
    total_days = context.user_data.get('sched_total_days', 30)
    rest_days = context.user_data.get('sched_rest_days', [4])

    if not done:
        await _safe_edit(context, chat_id, query.message.message_id,
                         "⚠️ لا توجد مواد",
                         InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="study_menu")]]))
        return

    # --- حفظ في قاعدة البيانات ---
    # نحفظ أسماء المواد فقط (VARCHAR قصير) — التفاصيل نسترجعها من SUBJECTS_POOL
    subj_names_csv = ','.join(s['name'] for s in done)

    weeks = -(-total_days // 7)  # ceiling division

    today = date.today()
    if today.weekday() == 6:
        start = today
    else:
        days_until_sunday = (6 - today.weekday()) % 7
        start = today + timedelta(days=days_until_sunday if days_until_sunday > 0 else 7)

    plan_id = None
    try:
        plan_id = create_study_plan(user_id, subj_names_csv, weeks, start, rest_days)
        logger.info(f"[Schedule] Plan created: plan_id={plan_id}, user={user_id}, weeks={weeks}, subjects={subj_names_csv}")
    except Exception as e:
        logger.error(f"[Schedule] DB create_study_plan failed: {e}", exc_info=True)

    # --- إنشاء PDF بطاقات ---
    bot_username = (await context.bot.get_me()).username
    exam_info = _fetch_exam_info()

    try:
        pdf_bytes = _generate_card_pdf(total_days, done, rest_days, bot_username, exam_info)
        subj_names = ' '.join(s['icon'] + s['name'] for s in done)
        await context.bot.send_document(
            chat_id=chat_id,
            document=io.BytesIO(pdf_bytes),
            filename=f"جدول_مذاكرة_{total_days}_يوم.pdf",
            caption=f"📅 جدول مذاكرة — {total_days} يوم\n{subj_names}"
        )
    except Exception as e:
        logger.error(f"[Schedule] PDF error: {e}", exc_info=True)

    # --- رسالة النجاح ---
    subj_names = '، '.join(s['name'] for s in done)
    rest_names = [DAY_NAMES.get(d, '') for d in rest_days]
    rest_display = '، '.join(rest_names) if rest_names else 'لا يوجد'

    if plan_id:
        text = (
            f"✅ <b>تم إنشاء جدول المذاكرة!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"📖 المواد: <b>{subj_names}</b>\n"
            f"📅 المدة: {total_days} يوم ({weeks} أسابيع)\n"
            f"📆 البداية: {start.strftime('%Y-%m-%d')}\n"
            f"🛋 أيام الراحة: {rest_display}\n\n"
            f"🖨 PDF جاهز للطباعة!\n"
            f"📝 تقدر تتابع إنجازك اليومي من البوت\n\n"
            f"ابدأ رحلتك الآن! 💪🔥"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 عرض الجدول", callback_data="study_view_week_1")],
            [InlineKeyboardButton("📝 تسجيل إنجاز اليوم", callback_data="study_record_today")],
            [InlineKeyboardButton("🔙 قائمة المذاكرة", callback_data="study_menu")],
        ])
    else:
        text = (
            f"⚠️ <b>PDF جاهز لكن فشل حفظ الجدول!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"📖 المواد: <b>{subj_names}</b>\n"
            f"📅 المدة: {total_days} يوم\n\n"
            f"🖨 PDF تم إرساله\n"
            f"⚠️ التتبع اليومي غير متاح — حاول إنشاء الجدول مرة ثانية"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 حاول مرة ثانية", callback_data="sched_start")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")],
        ])

    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML",
                                   reply_markup=keyboard)

    _clean_user_data(context)


# ============================================================
#  إلغاء
# ============================================================
async def sched_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _clean_user_data(context)
    await study_menu_callback(update, context)


# ============================================================
#  7. عرض الجدول الأسبوعي (نظام التتبع)
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
                         InlineKeyboardMarkup([[InlineKeyboardButton("🆕 إنشاء جدول", callback_data="sched_start")]]))
        return

    days = get_study_plan_days(plan['id'], week_num)
    if not days:
        await _safe_edit(context, chat_id, query.message.message_id,
                         "⚠️ لا توجد بيانات لهذا الأسبوع",
                         InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="study_menu")]]))
        return

    stats = get_study_plan_stats(plan['id'])
    total_weeks = plan['num_weeks']
    subj_display = _display_subjects(plan)

    text = f"📅 <b>{subj_display} — الأسبوع {WEEK_NAMES.get(week_num, str(week_num))}</b>\n"
    text += "━━━━━━━━━━━━━━━━━━\n\n"

    day_buttons = []
    for day in days:
        date_str = day['day_date'].strftime('%m/%d')
        is_rest = day.get('is_rest_day', False)

        if is_rest:
            text += f"🛋 {day['day_name']} {date_str} — راحة\n"
        elif day['is_completed']:
            line = f"✅ {day['day_name']} {date_str}"
            if day.get('pages'):
                line += f" — ص {day['pages']}"
            text += line + "\n"
        else:
            text += f"⬜ {day['day_name']} {date_str}\n"

        if not is_rest:
            toggle_icon = "⬜" if day['is_completed'] else "✅"
            day_buttons.append([InlineKeyboardButton(
                f"{toggle_icon} {day['day_name']} {date_str}",
                callback_data=f"study_toggle_{day['id']}_w{week_num}"
            )])

    pct = stats.get('progress_pct', 0)
    completed = stats.get('completed_days', 0)
    study_days = stats.get('study_days', 0)
    text += f"\n📊 {_progress_bar(pct)} {pct}% ({completed}/{study_days})"

    nav_row = []
    if week_num > 1:
        nav_row.append(InlineKeyboardButton("◀ السابق", callback_data=f"study_view_week_{week_num - 1}"))
    if week_num < total_weeks:
        nav_row.append(InlineKeyboardButton("التالي ▶", callback_data=f"study_view_week_{week_num + 1}"))

    keyboard = day_buttons
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton("🔙 قائمة المذاكرة", callback_data="study_menu")])

    await _safe_edit(context, chat_id, query.message.message_id, text, InlineKeyboardMarkup(keyboard))


# ============================================================
#  8. تبديل حالة يوم
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
#  9. تسجيل إنجاز اليوم
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
    today_date = date.today()
    today_day = None
    for d in all_days:
        if d['day_date'] == today_date:
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

    was_completed = today_day['is_completed']
    toggle_study_day(today_day['id'])

    week = today_day['week_number']
    if was_completed:
        text = f"⬜ تم إلغاء إنجاز اليوم ({today_day['day_name']})"
    else:
        text = f"✅ <b>تم تسجيل إنجاز اليوم!</b>\n\n📅 {today_day['day_name']} — {today_date.strftime('%Y-%m-%d')}\n\nاستمر! 💪🔥"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 عرض الجدول", callback_data=f"study_view_week_{week}")],
        [InlineKeyboardButton("🔙 قائمة المذاكرة", callback_data="study_menu")],
    ])
    await _safe_edit(context, chat_id, query.message.message_id, text, keyboard)


# ============================================================
#  10. حذف الجدول
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
#  11. تصدير PDF (جدول أسبوعي مع التقدم)
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
        pdf_bytes = _generate_weekly_pdf(plan, all_days, stats, student_name, bot_username)
        subj_display = _display_subjects(plan)
        await context.bot.send_document(
            chat_id=chat_id,
            document=io.BytesIO(pdf_bytes),
            filename=f"جدول_مذاكرة_تقدم.pdf",
            caption=f"📅 جدول مذاكرة {subj_display} — {plan['num_weeks']} أسابيع"
        )
    except Exception as e:
        logger.error(f"[StudySchedule] PDF error: {e}", exc_info=True)
        await context.bot.send_message(chat_id=chat_id, text=f"❌ خطأ: {str(e)[:150]}")


# ============================================================
#  12. طباعة بطاقات من الخطة النشطة
# ============================================================
async def study_print_cards_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⏳ جاري إنشاء البطاقات...")
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    plan = get_active_study_plan(user_id)
    if not plan:
        await _safe_edit(context, chat_id, query.message.message_id,
                         "📅 لا يوجد جدول نشط",
                         InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="study_menu")]]))
        return

    subjects_data = _parse_subjects_json(plan.get('subject', ''))
    if not subjects_data:
        await context.bot.send_message(chat_id=chat_id, text="⚠️ هذا الجدول بالنظام القديم، أنشئ جدول جديد للبطاقات")
        return

    rest_str = plan.get('rest_days', '')
    rest_list = []
    if rest_str:
        for d in rest_str.split(','):
            if d.strip().isdigit():
                rest_list.append(int(d.strip()))

    total_days = plan['num_weeks'] * 7
    bot_username = (await context.bot.get_me()).username
    exam_info = _fetch_exam_info()

    try:
        pdf_bytes = _generate_card_pdf(total_days, subjects_data, rest_list, bot_username, exam_info)
        await context.bot.send_document(
            chat_id=chat_id,
            document=io.BytesIO(pdf_bytes),
            filename=f"بطاقات_مذاكرة_{total_days}_يوم.pdf",
            caption=f"🖨 بطاقات مذاكرة — {total_days} يوم"
        )
    except Exception as e:
        logger.error(f"[Schedule] Card PDF error: {e}", exc_info=True)
        await context.bot.send_message(chat_id=chat_id, text=f"❌ خطأ: {str(e)[:150]}")


# ============================================================
#  مساعدات — جلب مواعيد التحصيلي
# ============================================================
def _fetch_exam_info():
    try:
        try:
            from database.manager import connect_db
        except ImportError:
            from manager import connect_db
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT period_name, exam_start_date, exam_end_date 
            FROM exam_schedule 
            WHERE status IN ('active','upcoming') 
            ORDER BY exam_start_date LIMIT 2
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows if rows else None
    except Exception:
        return None


# ============================================================
#  توزيع الصفحات مع أيام الراحة
# ============================================================
def _distribute_pages(total_days, subjects, rest_weekdays=None):
    if rest_weekdays is None:
        rest_weekdays = []

    # تحديد أيام الراحة
    start_weekday = 6  # الأحد
    rest_day_nums = set()
    for i in range(total_days):
        if (start_weekday + i) % 7 in rest_weekdays:
            rest_day_nums.add(i + 1)

    study_day_count = total_days - len(rest_day_nums)
    if study_day_count <= 0:
        study_day_count = total_days
        rest_day_nums = set()

    # توزيع الأيام بالتناسب
    subj_pages = [s['end'] - s['start'] + 1 for s in subjects]
    total_pages = sum(subj_pages)

    subj_day_counts = []
    remaining = study_day_count
    for i, pages in enumerate(subj_pages):
        if i == len(subj_pages) - 1:
            subj_day_counts.append(remaining)
        else:
            d = max(1, round(study_day_count * pages / total_pages))
            subj_day_counts.append(d)
            remaining -= d

    # بناء أيام الدراسة
    study_days = []
    for si, subj in enumerate(subjects):
        n_days = subj_day_counts[si]
        pages = subj_pages[si]
        ppd = pages / n_days if n_days > 0 else pages

        for di in range(n_days):
            sp = subj['start'] + round(di * ppd)
            ep = subj['start'] + round((di + 1) * ppd) - 1
            if di == n_days - 1:
                ep = subj['end']

            study_days.append({
                'subject': subj['name'],
                'bg': subj['bg'],
                'header_color': subj['header'],
                'pages_start': sp,
                'pages_end': ep,
            })

    # دمج أيام الراحة والدراسة
    days = []
    study_idx = 0
    for day_num in range(1, total_days + 1):
        if day_num in rest_day_nums:
            days.append({
                'day': day_num,
                'is_rest': True,
                'subject': 'راحة',
                'bg': '#FFF3E0',
                'header_color': '#E65100',
                'pages_start': 0,
                'pages_end': 0,
                'phrase': '🛋 استرح',
            })
        else:
            sd = study_days[study_idx] if study_idx < len(study_days) else study_days[-1]
            study_idx += 1

            if day_num == total_days:
                phrase = '🎉 مبروك أتممت!'
            elif study_idx >= len(study_days):
                phrase = f"أنهيت الكل!"
            elif day_num == 1:
                phrase = 'ابدأ بقوة'
            else:
                phrase = TEMPLATE_PHRASES[day_num % len(TEMPLATE_PHRASES)]

            days.append({
                'day': day_num,
                'is_rest': False,
                'subject': sd['subject'],
                'bg': sd['bg'],
                'header_color': sd['header_color'],
                'pages_start': sd['pages_start'],
                'pages_end': sd['pages_end'],
                'phrase': phrase,
            })

    return days


# ============================================================
#  تحميل الخط العربي
# ============================================================
def _ensure_arabic_font():
    import os
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    try:
        pdfmetrics.getFont('ArabicFont')
        return True
    except KeyError:
        pass

    search_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts', 'Amiri-Regular.ttf'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts', 'DejaVuSans.ttf'),
        '/home/ubuntu/fonts/Amiri-Regular.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
        '/usr/share/fonts/TTF/DejaVuSans.ttf',
        '/opt/render/project/src/fonts/Amiri-Regular.ttf',
        '/opt/render/project/src/fonts/DejaVuSans.ttf',
        '/opt/render/project/src/DejaVuSans.ttf',
    ]
    
    search_paths_bold = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts', 'Amiri-Bold.ttf'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts', 'DejaVuSans.ttf'),
        '/home/ubuntu/fonts/Amiri-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/opt/render/project/src/fonts/Amiri-Bold.ttf',
        '/opt/render/project/src/fonts/DejaVuSans.ttf',
    ]

    font_path = None
    for fp in search_paths:
        if os.path.exists(fp):
            font_path = fp
            break

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
        except Exception:
            pass

    if not font_path:
        download_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
        os.makedirs(download_dir, exist_ok=True)
        font_path = os.path.join(download_dir, 'DejaVuSans.ttf')
        if not os.path.exists(font_path):
            try:
                import urllib.request
                urllib.request.urlretrieve(
                    "https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans.ttf",
                    font_path
                )
            except Exception:
                return False

    if not os.path.exists(font_path):
        return False

    try:
        pdfmetrics.registerFont(TTFont('ArabicFont', font_path))
    except Exception:
        return False

    # تسجيل الخط Bold
    bold_path = None
    for fp in search_paths_bold:
        if os.path.exists(fp):
            bold_path = fp
            break
    
    if not bold_path:
        bold_path = font_path.replace('Regular.ttf', 'Bold.ttf')
        if not os.path.exists(bold_path):
            bold_path = font_path.replace('Sans.ttf', 'Sans-Bold.ttf')
    
    try:
        if os.path.exists(bold_path):
            pdfmetrics.registerFont(TTFont('ArabicFontBold', bold_path))
        else:
            pdfmetrics.registerFont(TTFont('ArabicFontBold', font_path))
    except Exception:
        pdfmetrics.registerFont(TTFont('ArabicFontBold', font_path))

    return True


# ============================================================
#  PDF بطاقات — Card Layout
# ============================================================
def _generate_card_pdf(total_days, subjects, rest_weekdays, bot_username, exam_info=None):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader

    if not _ensure_arabic_font():
        raise RuntimeError("خط عربي غير متوفر")

    ar = _reshape_arabic
    days = _distribute_pages(total_days, subjects, rest_weekdays)

    buf = io.BytesIO()
    width, height = A4
    c = canvas.Canvas(buf, pagesize=A4)

    cols = 6
    rows_per_page = 8  # زيادة عدد الصفوف لتصغير المربعات أكثر
    margin_x = 35  # زيادة الهامش الجانبي
    gap = 8  # زيادة المسافة بين المربعات
    top_area = 75
    bottom_area = 120  # زيادة المساحة السفلية لضمان ظهور QR code

    usable_w = width - 2 * margin_x
    usable_h = height - top_area - bottom_area
    card_w = (usable_w - gap * (cols - 1)) / cols
    card_h = (usable_h - gap * (rows_per_page - 1)) / rows_per_page
    cards_per_page = cols * rows_per_page

    for page_start in range(0, len(days), cards_per_page):
        if page_start > 0:
            c.showPage()

        page_days = days[page_start:page_start + cards_per_page]
        _draw_card_header(c, width, height, total_days, exam_info, ar)

        for idx, day in enumerate(page_days):
            row = idx // cols
            col_ltr = idx % cols
            col_idx = cols - 1 - col_ltr  # RTL

            x = margin_x + col_idx * (card_w + gap)
            y = height - top_area - (row + 1) * (card_h + gap) + gap
            _draw_card(c, x, y, card_w, card_h, day, ar)

        _draw_card_footer(c, width, bot_username, ar)
        
        # إضافة رقم الصفحة في الأسفل
        page_num = (page_start // cards_per_page) + 1
        c.setFillColor(colors.HexColor('#888888'))
        c.setFont('ArabicFont', 9)
        c.drawCentredString(width / 2, 20, ar(f"ص {page_num}"))

    c.save()
    return buf.getvalue()


def _draw_card_header(c, width, height, total_days, exam_info, ar):
    from reportlab.lib import colors

    c.setFillColor(colors.HexColor('#f8f9fa'))
    c.rect(0, height - 75, width, 75, fill=1)

    c.setFillColor(colors.HexColor('#2c3e50'))
    c.setFont('ArabicFontBold', 20)
    c.drawCentredString(width / 2, height - 28, ar(f"خطتك للتميز - {total_days} يوم"))

    if exam_info:
        c.setFillColor(colors.HexColor('#555555'))
        c.setFont('ArabicFont', 8)
        y = height - 45
        for row in exam_info[:2]:
            period = row[0] or ''
            start_d = row[1].strftime('%Y/%m/%d') if row[1] else ''
            end_d = row[2].strftime('%Y/%m/%d') if row[2] else ''
            c.drawCentredString(width / 2, y, ar(f"{period}: {start_d} - {end_d}"))
            y -= 13
    else:
        c.setFillColor(colors.HexColor('#888888'))
        c.setFont('ArabicFont', 9)
        c.drawCentredString(width / 2, height - 50, ar("⚡فيزياء  📐رياضيات  ⚗كيمياء  🌿أحياء"))


def _draw_card(c, x, y, w, h, day, ar):
    from reportlab.lib import colors

    is_rest = day.get('is_rest', False)

    c.setFillColor(colors.HexColor(day['bg']))
    c.roundRect(x, y, w, h, 4, fill=1)

    c.setStrokeColor(colors.HexColor('#dee2e6'))
    c.setLineWidth(0.4)
    c.roundRect(x, y, w, h, 4)

    header_h = 16
    c.setFillColor(colors.HexColor(day['header_color']))
    c.rect(x + 1, y + h - header_h, w - 2, header_h - 1, fill=1)

    c.setFillColor(colors.white)
    c.setFont('ArabicFontBold', 9)
    c.drawCentredString(x + w / 2, y + h - header_h + 4, ar(f"يوم {day['day']}"))

    cx = x + w / 2
    ct = y + h - header_h

    if is_rest:
        c.setFillColor(colors.HexColor('#E65100'))
        c.setFont('ArabicFontBold', 12)
        c.drawCentredString(cx, ct - 25, ar("🛋 راحة"))
        c.setFillColor(colors.HexColor('#666666'))
        c.setFont('ArabicFont', 8)
        c.drawCentredString(cx, ct - 42, ar("استرح وجدد نشاطك"))
    else:
        c.setFillColor(colors.HexColor(day['header_color']))
        c.setFont('ArabicFontBold', 11)
        c.drawCentredString(cx, ct - 18, ar(day['subject']))

        c.setFillColor(colors.HexColor('#333333'))
        c.setFont('ArabicFont', 9)
        # أرقام الصفحات مع حرف ص
        c.drawCentredString(cx, ct - 34, ar(f"ص {day['pages_start']}-{day['pages_end']}"))

        c.setFillColor(colors.HexColor('#666666'))
        c.setFont('ArabicFont', 7)
        c.drawCentredString(cx, ct - 48, ar(day['phrase']))

        cb_size = 8
        c.setStrokeColor(colors.HexColor('#999999'))
        c.setLineWidth(0.6)
        c.setFillColor(colors.white)
        c.rect(cx - cb_size / 2, y + 12, cb_size, cb_size, fill=1)  # رفع المربع لتجنب التداخل


def _draw_card_footer(c, width, bot_username, ar):
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader

    c.setFillColor(colors.HexColor('#2c3e50'))
    c.setFont('ArabicFontBold', 10)
    c.drawCentredString(width / 2, 88, ar("إعداد الأستاذ حسين الموسى"))

    c.setFillColor(colors.HexColor('#555555'))
    c.setFont('ArabicFont', 9)
    c.drawCentredString(width / 2, 74, ar(random.choice(MOTIVATIONAL_QUOTES)))

    c.setFont('ArabicFont', 8)
    c.drawCentredString(width / 2, 60, ar("سجل في بوت الكيمياء للاختبارات والتدريبات"))

    c.setFillColor(colors.HexColor('#2c3e50'))
    c.setFont('ArabicFontBold', 10)
    c.drawCentredString(width / 2, 46, f"@{bot_username.upper()}")

    try:
        import qrcode
        qr = qrcode.QRCode(version=1, box_size=3, border=1)
        qr.add_data(f"https://t.me/{bot_username}")
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_buf = io.BytesIO()
        qr_img.save(qr_buf, format='PNG')
        qr_buf.seek(0)
        c.drawImage(ImageReader(qr_buf), width / 2 - 20, 2, 40, 40)
    except Exception:
        pass


# ============================================================
#  PDF أسبوعي — Weekly Table Layout (مع التقدم)
# ============================================================
def _generate_weekly_pdf(plan, all_days, stats, student_name, bot_username):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas as canv
    from reportlab.lib.utils import ImageReader

    if not _ensure_arabic_font():
        raise RuntimeError("خط عربي غير متوفر")

    buf = io.BytesIO()
    width, height = landscape(A4)
    c = canv.Canvas(buf, pagesize=landscape(A4))

    subj_display = _display_subjects(plan)
    rest_str = plan.get('rest_days', '')
    rest_names = []
    if rest_str:
        for d in rest_str.split(','):
            if d.strip().isdigit():
                rest_names.append(DAY_NAMES.get(int(d.strip()), ''))
    rest_display = '، '.join(rest_names) if rest_names else 'لا يوجد'
    study_days_count = stats.get('study_days', 0)

    _draw_weekly_cover(c, width, height, plan, subj_display, student_name, bot_username, rest_display, study_days_count)
    # إضافة رقم الصفحة للغلاف
    c.setFillColor(colors.HexColor('#888888'))
    c.setFont('ArabicFont', 9)
    c.drawCentredString(width / 2, 15, _reshape_arabic("ص 1"))
    c.showPage()

    # استخراج بيانات التوزيع من الخطة وإضافتها للأيام
    subjects_data = _parse_subjects_json(plan.get('subject', ''))
    rest_days_str = plan.get('rest_days', '')
    rest_days_list = []
    if rest_days_str:
        for d in rest_days_str.split(','):
            if d.strip().isdigit():
                rest_days_list.append(int(d.strip()))

    # توزيع الصفحات على الأيام مرة ثانية لربطها
    if subjects_data:
        total_days = plan.get('num_weeks', 1) * 7
        distributed_days = _distribute_pages(total_days, subjects_data, rest_days_list)

        # إنشاء dictionary للربط السريع بين رقم اليوم وبياناته
        day_info_map = {}
        for dist_day in distributed_days:
            day_num = dist_day.get('day', 0)
            day_info_map[day_num] = {
                'subject': dist_day.get('subject', ''),
                'pages_start': dist_day.get('pages_start', 0),
                'pages_end': dist_day.get('pages_end', 0),
                'is_rest': dist_day.get('is_rest', False)
            }

        # إضافة المعلومات لكل يوم في all_days
        for day in all_days:
            day_num = day.get('day_number', 0)
            if day_num in day_info_map:
                info = day_info_map[day_num]
                if not day.get('pages') and not day.get('is_rest_day', False):
                    day['subject'] = info['subject']
                    day['pages_start'] = info['pages_start']
                    day['pages_end'] = info['pages_end']

    weeks_data = {}
    for day in all_days:
        weeks_data.setdefault(day['week_number'], []).append(day)
    week_nums = sorted(weeks_data.keys())
    page_num = 2
    for i in range(0, len(week_nums), 4):
        batch = week_nums[i:i + 4]
        _draw_weeks_page(c, width, height, subj_display, weeks_data, batch)
        # إضافة رقم الصفحة
        c.setFillColor(colors.HexColor('#888888'))
        c.setFont('ArabicFont', 9)
        c.drawCentredString(width / 2, 15, _reshape_arabic(f"ص {page_num}"))
        page_num += 1
        c.showPage()

    c.save()
    return buf.getvalue()


def _draw_weekly_cover(c, width, height, plan, subj_display, student_name, bot_username, rest_display, study_days):
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader

    c.setFillColor(colors.HexColor('#f8f9fa'))
    c.rect(0, 0, width, height, fill=1)

    c.setFillColor(colors.HexColor('#2c3e50'))
    c.rect(0, height - 80, width, 80, fill=1)
    c.setFillColor(colors.white)
    c.setFont('ArabicFontBold', 22)
    c.drawCentredString(width / 2, height - 35, _reshape_arabic("بوت كيم تحصيلي"))
    c.setFont('ArabicFont', 14)
    c.drawCentredString(width / 2, height - 60, _reshape_arabic("إعداد: أ. حسين الموسى"))

    c.setFillColor(colors.HexColor('#2c3e50'))
    c.setFont('ArabicFontBold', 36)
    c.drawCentredString(width / 2, height - 170, _reshape_arabic("جدول مذاكرة"))
    c.setFillColor(colors.HexColor('#e74c3c'))
    c.setFont('ArabicFontBold', 42)
    c.drawCentredString(width / 2, height - 230, _reshape_arabic(subj_display[:30]))

    c.setFillColor(colors.HexColor('#555555'))
    c.setFont('ArabicFont', 15)
    y = height - 300
    c.drawCentredString(width / 2, y, _reshape_arabic(f"المدة: {plan['num_weeks']} أسابيع — أيام المذاكرة: {study_days} يوم"))
    y -= 28
    c.drawCentredString(width / 2, y, _reshape_arabic(f"أيام الراحة: {rest_display}"))
    y -= 28
    c.drawCentredString(width / 2, y, _reshape_arabic(f"البداية: {plan['start_date'].strftime('%Y-%m-%d')}"))
    if student_name:
        y -= 28
        c.drawCentredString(width / 2, y, _reshape_arabic(f"الطالب/ة: {student_name}"))

    try:
        import qrcode
        qr = qrcode.QRCode(version=1, box_size=4, border=1)
        qr.add_data(f"https://t.me/{bot_username}")
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_buf = io.BytesIO()
        qr_img.save(qr_buf, format='PNG')
        qr_buf.seek(0)
        c.drawImage(ImageReader(qr_buf), width - 120, 20, 90, 90)
        c.setFillColor(colors.HexColor('#555555'))
        c.setFont('ArabicFont', 8)
        c.drawCentredString(width - 75, 12, f"@{bot_username}")
    except Exception:
        pass

    c.setFillColor(colors.HexColor('#2c3e50'))
    c.rect(0, 0, width, 8, fill=1)


def _draw_weeks_page(c, width, height, subj_display, weeks_data, week_nums):
    from reportlab.lib import colors
    margin = 30
    usable_w = width - 2 * margin

    c.setFillColor(colors.HexColor('#2c3e50'))
    c.rect(0, height - 40, width, 40, fill=1)
    c.setFillColor(colors.white)
    c.setFont('ArabicFontBold', 12)
    c.drawCentredString(width / 2, height - 27,
                        _reshape_arabic(f"جدول مذاكرة {subj_display[:20]} — أ. حسين الموسى — بوت كيم تحصيلي"))

    usable_h = height - 100
    table_w = (usable_w - 20) / 2
    table_h = (usable_h - 30) / 2

    # ترتيب الجداول من اليمين لليسار (عربي)
    positions = [
        (margin + table_w + 20, height - 60 - table_h),      # اليمين فوق
        (margin, height - 60 - table_h),                      # اليسار فوق
        (margin + table_w + 20, height - 80 - 2 * table_h),  # اليمين تحت
        (margin, height - 80 - 2 * table_h),                  # اليسار تحت
    ]

    for idx, wn in enumerate(week_nums[:4]):
        days = weeks_data.get(wn, [])
        px, py = positions[idx]
        _draw_week_table(c, px, py, table_w, table_h, wn, days)

    c.setFillColor(colors.HexColor('#888888'))
    c.setFont('ArabicFont', 9)
    c.drawCentredString(width / 2, 12, _reshape_arabic(random.choice(MOTIVATIONAL_QUOTES)))


def _draw_week_table(c, x, y, w, h, week_num, days):
    from reportlab.lib import colors

    title = f"الأسبوع {WEEK_NAMES.get(week_num, str(week_num))}"
    c.setFillColor(colors.HexColor('#2c3e50'))
    c.roundRect(x, y + h - 25, w, 25, 5, fill=1)
    c.setFillColor(colors.white)
    c.setFont('ArabicFontBold', 11)
    c.drawCentredString(x + w / 2, y + h - 18, _reshape_arabic(title))

    header_y = y + h - 50
    col_labels = ['اليوم', 'التاريخ', 'الصفحة', 'ملاحظات', 'الإنجاز']
    cw = [w * 0.15, w * 0.18, w * 0.18, w * 0.34, w * 0.15]

    c.setFillColor(colors.HexColor('#ecf0f1'))
    c.rect(x, header_y, w, 20, fill=1)
    c.setFillColor(colors.HexColor('#2c3e50'))
    c.setFont('ArabicFontBold', 8)
    cx = x
    for i, col in enumerate(col_labels):
        c.drawCentredString(cx + cw[i] / 2, header_y + 6, _reshape_arabic(col))
        cx += cw[i]

    row_h = (h - 55) / 7
    c.setFont('ArabicFont', 8)

    for idx, day in enumerate(days[:7]):
        ry = header_y - (idx + 1) * row_h
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
        ty = ry + row_h / 2 - 3
        cx = x

        # الترتيب: اليوم، التاريخ، الصفحة، ملاحظات، الإنجاز
        # عمود اليوم
        c.drawCentredString(cx + cw[0] / 2, ty, _reshape_arabic(day['day_name'][:8]))
        cx += cw[0]
        
        # عمود التاريخ
        c.drawCentredString(cx + cw[1] / 2, ty, day['day_date'].strftime('%m/%d'))
        cx += cw[1]

        if is_rest:
            # عمود الصفحة + ملاحظات + الإنجاز = راحة
            c.setFillColor(colors.HexColor('#e67e22'))
            c.setFont('ArabicFontBold', 9)
            c.drawCentredString(cx + (cw[2] + cw[3] + cw[4]) / 2, ty, _reshape_arabic("راحة"))
            c.setFont('ArabicFont', 8)
            c.setFillColor(colors.HexColor('#333333'))
        else:
            # عمود الصفحة
            pages_text = day.get('pages', '') or ''
            if not pages_text and day.get('pages_start') and day.get('pages_end'):
                pages_text = f"{day['pages_start']}-{day['pages_end']}"
            c.drawCentredString(cx + cw[2] / 2, ty, str(pages_text)[:12])
            cx += cw[2]
            
            # عمود ملاحظات
            notes_text = day.get('notes', '') or ''
            if notes_text:
                c.drawCentredString(cx + cw[3] / 2, ty, _reshape_arabic(str(notes_text)[:25]))
            else:
                c.drawCentredString(cx + cw[3] / 2, ty, notes_text)
            cx += cw[3]
            
            # عمود الإنجاز
            if day['is_completed']:
                c.setFillColor(colors.HexColor('#27ae60'))
                st = "✓"
            else:
                c.setFillColor(colors.HexColor('#bdc3c7'))
                st = "☐"
            c.setFont('ArabicFontBold', 12)
            c.drawCentredString(cx + cw[4] / 2, ty, st)
            c.setFont('ArabicFont', 8)
            c.setFillColor(colors.HexColor('#333333'))

    c.setStrokeColor(colors.HexColor('#2c3e50'))
    c.setLineWidth(1)
    c.rect(x, y, w, h - 25)
