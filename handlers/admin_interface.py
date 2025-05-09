# admin_interface.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CommandHandler, CallbackQueryHandler, CallbackContext

from utils.admin_auth import is_admin
from utils import admin_logic

# Callback data prefixes
STATS_PREFIX_MAIN_MENU = "stats_menu_"
STATS_PREFIX_FETCH = "stats_fetch_"
PREFIX_TIME_FILTER = "filter_" # This one seems unused by admin stats, but kept for now

# Time filter options
TIME_FILTERS = {
    "today": "اليوم",
    "last_7_days": "آخر 7 أيام",
    "last_30_days": "آخر 30 يومًا",
    "all_time": "كل الوقت"
}

# This function itself doesn't need to be async as it doesn't call awaitable operations
def get_time_filter_buttons(stat_category_base_callback: str):
    keyboard = []
    row = []
    for key, text in TIME_FILTERS.items():
        row.append(InlineKeyboardButton(text, callback_data=f"{stat_category_base_callback}_{key}"))
        if len(row) == 2: # Max 2 buttons per row for time filters
            keyboard.append(row)
            row = []
    if row: # Add remaining buttons if any
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data=f"{STATS_PREFIX_MAIN_MENU}main")])
    return InlineKeyboardMarkup(keyboard)

async def stats_admin_panel_command_handler(update: Update, context: CallbackContext):
    if not is_admin(update):
        await update.message.reply_text("عذراً، هذا الأمر مخصص للأدمن فقط.")
        return
    await show_main_stats_menu(update, context)

async def show_main_stats_menu(update: Update, context: CallbackContext, query=None):
    keyboard = [
        [InlineKeyboardButton("📊 نظرة عامة على الاستخدام", callback_data=f"{STATS_PREFIX_MAIN_MENU}usage_overview")],
        [InlineKeyboardButton("📈 أداء الاختبارات", callback_data=f"{STATS_PREFIX_MAIN_MENU}quiz_performance")],
        [InlineKeyboardButton("👥 تفاعل المستخدمين", callback_data=f"{STATS_PREFIX_MAIN_MENU}user_interaction")],
        [InlineKeyboardButton("❓ إحصائيات الأسئلة", callback_data=f"{STATS_PREFIX_MAIN_MENU}question_stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = "لوحة تحكم إحصائيات الأدمن: اختر فئة لعرضها"
    if query:
        await query.edit_message_text(text=message_text, reply_markup=reply_markup)
    elif update.message:
        await update.message.reply_text(text=message_text, reply_markup=reply_markup)

async def stats_menu_callback_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    if not is_admin(query):
        await query.edit_message_text(text="عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط.")
        return

    callback_data = query.data

    if callback_data == f"{STATS_PREFIX_MAIN_MENU}main":
        await show_main_stats_menu(update, context, query=query)
        return

    stat_category_base = callback_data.replace(STATS_PREFIX_MAIN_MENU, "")
    fetch_base_callback = f"{STATS_PREFIX_FETCH}{stat_category_base}"

    reply_markup = get_time_filter_buttons(fetch_base_callback)
    stat_category_title = stat_category_base.replace("_", " ").title()
    message_text_for_edit = f"اختر الفترة الزمنية لـ: {stat_category_title}"
    await query.edit_message_text(text=message_text_for_edit, reply_markup=reply_markup)

async def stats_fetch_stats_callback_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    if not is_admin(query):
        await query.edit_message_text(text="عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط.")
        return

    parts = query.data.split("_")
    time_filter_key = parts[-1]
    if parts[-2] in ["7", "30"]: # Handle cases like "last_7_days"
        time_filter_key = parts[-3] + "_" + parts[-2] + "_" + parts[-1]
        stat_category = parts[2:-3]
    else:
        stat_category = parts[2:-1]

    stat_category_str = "_".join(stat_category)
    time_filter_text = TIME_FILTERS.get(time_filter_key, "كل الوقت")

    stat_category_display_title = stat_category_str.replace("_", " ").title()
    loading_message_text = f"⏳ جاري جلب بيانات {stat_category_display_title} عن فترة: {time_filter_text}..."
    await query.edit_message_text(text=loading_message_text)

    await send_actual_stats(update, context, stat_category_str, time_filter_key)

async def send_actual_stats(update: Update, context: CallbackContext, stat_category: str, time_filter: str):
    query = update.callback_query
    text_response = ""
    current_filter_text = TIME_FILTERS.get(time_filter, "غير محدد")

    if stat_category == "usage_overview":
        total_users = admin_logic.get_total_users()
        active_users = admin_logic.get_active_users(time_filter=time_filter)
        total_quizzes = admin_logic.get_total_quizzes_taken(time_filter=time_filter)
        avg_quizzes_user = admin_logic.get_average_quizzes_per_user(time_filter=time_filter)
        text_response = (
            f"📊 *نظرة عامة على الاستخدام ({current_filter_text}):*\n"
            f"- إجمالي المستخدمين (الكلي): {total_users}\n"
            f"- المستخدمون النشطون: {active_users}\n"
            f"- إجمالي الاختبارات التي تم إجراؤها: {total_quizzes}\n"
            f"- متوسط الاختبارات لكل مستخدم نشط: {avg_quizzes_user:.2f}"
        )

    elif stat_category == "quiz_performance":
        avg_correct = admin_logic.get_average_correct_answer_rate(time_filter=time_filter)
        popular_units = admin_logic.get_popular_units(time_filter=time_filter, limit=3)
        difficult_units = admin_logic.get_difficulty_units(time_filter=time_filter, limit=3, easiest=False)
        easiest_units = admin_logic.get_difficulty_units(time_filter=time_filter, limit=3, easiest=True)

        pop_items = []
        for pu in popular_units:
            unit_id_val = pu.get("unit_id", "غير متوفر")
            quiz_count_val = pu.get("quiz_count", "0")
            pop_items.append(f"  - {unit_id_val} ({quiz_count_val} مرة)")
        pop_units_str = "\n".join(pop_items) or "  لا توجد بيانات"

        diff_items = []
        for du in difficult_units:
            unit_id_val = du.get("unit_id", "غير متوفر")
            avg_score_val = float(du.get("average_score_percent", 0))
            diff_items.append(f"  - {unit_id_val} ({avg_score_val:.0f}٪)")
        diff_units_str = "\n".join(diff_items) or "  لا توجد بيانات"

        easy_items = []
        for eu in easiest_units:
            unit_id_val = eu.get("unit_id", "غير متوفر")
            avg_score_val = float(eu.get("average_score_percent", 0))
            easy_items.append(f"  - {unit_id_val} ({avg_score_val:.0f}٪)")
        easy_units_str = "\n".join(easy_items) or "  لا توجد بيانات"

        text_response = (
            f"📈 *أداء الاختبارات ({current_filter_text}):*\n"
            f"- متوسط نسبة الإجابات الصحيحة: {float(avg_correct):.2f}%\n"
            f"- الوحدات الأكثر شعبية (أعلى 3):\n{pop_units_str}\n"
            f"- الوحدات الأكثر صعوبة (أقل 3):\n{diff_units_str}\n"
            f"- الوحدات الأسهل (أعلى 3):\n{easy_units_str}"
        )

    elif stat_category == "user_interaction":
        avg_completion_time = admin_logic.get_average_quiz_completion_time(time_filter=time_filter)
        completion_rate = admin_logic.get_quiz_completion_rate(time_filter=time_filter)
        text_response = (
            f"👥 *تفاعل المستخدمين ({current_filter_text}):*\n"
            f"- متوسط وقت إكمال الاختبار: {float(avg_completion_time):.2f} ثانية\n"
            f"- معدل إكمال الاختبارات: {float(completion_rate):.2f}%"
        )

    elif stat_category == "question_stats":
        difficult_questions = admin_logic.get_question_difficulty(time_filter=time_filter, limit=3, easiest=False)
        easiest_questions = admin_logic.get_question_difficulty(time_filter=time_filter, limit=3, easiest=True)
        
        diff_q_items = []
        for dq in difficult_questions:
            question_id_val = dq.get("question_id", "غير متوفر")
            correct_perc_val = float(dq.get("correct_percentage", 0))
            diff_q_items.append(f"  - {question_id_val} ({correct_perc_val:.0f}٪ صحيحة)")
        diff_q_str = "\n".join(diff_q_items) or "  لا توجد بيانات"

        easy_q_items = []
        for eq in easiest_questions:
            question_id_val = eq.get("question_id", "غير متوفر")
            correct_perc_val = float(eq.get("correct_percentage", 0))
            easy_q_items.append(f"  - {question_id_val} ({correct_perc_val:.0f}٪ صحيحة)")
        easy_q_str = "\n".join(easy_q_items) or "  لا توجد بيانات"

        text_response = (
            f"❓ *إحصائيات الأسئلة ({current_filter_text}):*\n"
            f"- الأسئلة الأكثر صعوبة (أقل 3):\n{diff_q_str}\n"
            f"- الأسئلة الأسهل (أعلى 3):\n{easy_q_str}"
        )
    else:
        text_response = f"فئة الإحصائيات \'{stat_category}\' غير معروفة أو لم يتم تنفيذها بعد."

    fetch_base_callback = f"{STATS_PREFIX_FETCH}{stat_category}"
    reply_markup = get_time_filter_buttons(fetch_base_callback)
    await query.edit_message_text(text=text_response, reply_markup=reply_markup, parse_mode='Markdown')

# Add handlers to your application (examples, actual registration in bot.py)
# app.add_handler(CommandHandler("adminstats", stats_admin_panel_command_handler))
# app.add_handler(CallbackQueryHandler(stats_menu_callback_handler, pattern=f"^{STATS_PREFIX_MAIN_MENU}"))
# app.add_handler(CallbackQueryHandler(stats_fetch_stats_callback_handler, pattern=f"^{STATS_PREFIX_FETCH}"))

