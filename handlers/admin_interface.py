# admin_interface.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CommandHandler, CallbackQueryHandler, CallbackContext

from utils.admin_auth import is_admin
from utils import admin_logic

# Callback data prefixes
STATS_PREFIX_MAIN_MENU = "stats_menu_"
STATS_PREFIX_FETCH = "stats_fetch_"
PREFIX_TIME_FILTER = "filter_"

# Time filter options
TIME_FILTERS = {
    "today": "اليوم",
    "last_7_days": "آخر 7 أيام",
    "last_30_days": "آخر 30 يومًا",
    "all_time": "كل الوقت"
}

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
    keyboard.append([InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data=f"{PREFIX_MAIN_MENU}main")])
    return InlineKeyboardMarkup(keyboard)

def stats_admin_panel_command_handler(update: Update, context: CallbackContext):
    if not is_admin(update):
        update.message.reply_text("عذراً، هذا الأمر مخصص للأدمن فقط.")
        return
    show_main_stats_menu(update, context)

def show_main_stats_menu(update: Update, context: CallbackContext, query=None):
    keyboard = [
        [InlineKeyboardButton("📊 نظرة عامة على الاستخدام", callback_data=f"{PREFIX_MAIN_MENU}usage_overview")],
        [InlineKeyboardButton("📈 أداء الاختبارات", callback_data=f"{PREFIX_MAIN_MENU}quiz_performance")],
        [InlineKeyboardButton("👥 تفاعل المستخدمين", callback_data=f"{PREFIX_MAIN_MENU}user_interaction")],
        [InlineKeyboardButton("❓ إحصائيات الأسئلة", callback_data=f"{PREFIX_MAIN_MENU}question_stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = " पैनल لوحة تحكم إحصائيات الأدمن: اختر فئة لعرضها"
    if query:
        query.edit_message_text(text=message_text, reply_markup=reply_markup)
    elif update.message:
        update.message.reply_text(text=message_text, reply_markup=reply_markup)

def stats_menu_callback_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if not is_admin(query):
        query.edit_message_text(text="عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط.")
        return

    callback_data = query.data

    if callback_data == f"{PREFIX_MAIN_MENU}main":
        show_main_stats_menu(update, context, query=query)
        return

    # Extract stat category, e.g., "usage_overview" from "stats_menu_usage_overview"
    stat_category_base = callback_data.replace(PREFIX_MAIN_MENU, "")
    # Now, instead of fetching, show time filter options for this category
    # The base for fetch will be PREFIX_FETCH_STAT + stat_category_base
    fetch_base_callback = f"{PREFIX_FETCH_STAT}{stat_category_base}"

    reply_markup = get_time_filter_buttons(fetch_base_callback)
    query.edit_message_text(text=f"اختر الفترة الزمنية لـ: {stat_category_base.replace('_', ' ').title()}", reply_markup=reply_markup)

def stats_fetch_stats_callback_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if not is_admin(query):
        query.edit_message_text(text="عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط.")
        return

    # callback_data will be like "stats_fetch_usage_overview_last_7_days"
    parts = query.data.split("_")
    time_filter_key = parts[-1] # e.g., "last_7_days"
    if parts[-2] in ["7", "30"]: # Handles cases like last_7_days, last_30_days
        time_filter_key = parts[-3] + "_" + parts[-2] + "_" + parts[-1]
        stat_category = parts[2:-3] # e.g. ["usage", "overview"]
    else:
        stat_category = parts[2:-1] # e.g. ["usage", "overview"]

    stat_category_str = "_".join(stat_category) # e.g., "usage_overview"
    time_filter_text = TIME_FILTERS.get(time_filter_key, "كل الوقت")

    text_response = f"⏳ جاري جلب بيانات {stat_category_str.replace('_', ' ').title()} عن فترة: {time_filter_text}..."
    query.edit_message_text(text=text_response) # Show loading message

    # Simulate a slight delay for fetching, then update with actual data
    # context.job_queue.run_once(lambda ctx: send_actual_stats(update, context, stat_category_str, time_filter_key), 0.1)
    # For now, direct call for simplicity in this environment
    send_actual_stats(update, context, stat_category_str, time_filter_key)

def send_actual_stats(update: Update, context: CallbackContext, stat_category: str, time_filter: str):
    query = update.callback_query # query is available via update
    text_response = ""
    current_filter_text = TIME_FILTERS.get(time_filter, "غير محدد")

    if stat_category == "usage_overview":
        total_users = admin_logic.get_total_users() # Total users usually isn't time-filtered
        active_users = admin_logic.get_active_users(time_filter=time_filter)
        total_quizzes = admin_logic.get_total_quizzes_taken(time_filter=time_filter)
        avg_quizzes_user = admin_logic.get_average_quizzes_per_user(time_filter=time_filter)
        text_response = (f"📊 **نظرة عامة على الاستخدام ({current_filter_text}):**\n"
                         f"- إجمالي المستخدمين (الكلي): {total_users}\n"
                         f"- المستخدمون النشطون: {active_users}\n"
                         f"- إجمالي الاختبارات التي تم إجراؤها: {total_quizzes}\n"
                         f"- متوسط الاختبارات لكل مستخدم نشط: {avg_quizzes_user}")

    elif stat_category == "quiz_performance":
        avg_correct = admin_logic.get_average_correct_answer_rate(time_filter=time_filter)
        popular_units = admin_logic.get_popular_units(time_filter=time_filter, limit=3)
        difficult_units = admin_logic.get_difficulty_units(time_filter=time_filter, limit=3, easiest=False)
        easiest_units = admin_logic.get_difficulty_units(time_filter=time_filter, limit=3, easiest=True)

        pop_units_str = "\n".join([f"  - {pu['unit_id']} ({pu['quiz_count']} مرة)" for pu in popular_units]) or "  لا توجد بيانات"
        diff_units_str = "\n".join([f"  - {du['unit_id']} ({du['average_score_percent']}٪)" for du in difficult_units]) or "  لا توجد بيانات"
        easy_units_str = "\n".join([f"  - {eu['unit_id']} ({eu['average_score_percent']}٪)" for eu in easiest_units]) or "  لا توجد بيانات"

        text_response = (f"📈 **أداء الاختبارات ({current_filter_text}):**\n"
                         f"- متوسط نسبة الإجابات الصحيحة: {avg_correct}%\n"
                         f"- الوحدات الأكثر شعبية (أعلى 3):\n{pop_units_str}\n"
                         f"- الوحدات الأكثر صعوبة (أقل 3):\n{diff_units_str}\n"
                         f"- الوحدات الأسهل (أعلى 3):\n{easy_units_str}")

    elif stat_category == "user_interaction":
        avg_completion_time = admin_logic.get_average_quiz_completion_time(time_filter=time_filter)
        completion_rate = admin_logic.get_quiz_completion_rate(time_filter=time_filter)
        text_response = (f"👥 **تفاعل المستخدمين ({current_filter_text}):**\n"
                         f"- متوسط وقت إكمال الاختبار: {avg_completion_time} ثانية\n"
                         f"- معدل إكمال الاختبارات: {completion_rate}%")

    elif stat_category == "question_stats":
        difficult_questions = admin_logic.get_question_difficulty(time_filter=time_filter, limit=3, easiest=False)
        easiest_questions = admin_logic.get_question_difficulty(time_filter=time_filter, limit=3, easiest=True)

        diff_q_str = "\n".join([f"  - {dq['question_id']} ({dq['correct_percentage']}٪ صحيحة)" for dq in difficult_questions]) or "  لا توجد بيانات"
        easy_q_str = "\n".join([f"  - {eq['question_id']} ({eq['correct_percentage']}٪ صحيحة)" for eq in easiest_questions]) or "  لا توجد بيانات"

        text_response = (f"❓ **إحصائيات الأسئلة ({current_filter_text}):**\n"
                         f"- الأسئلة الأكثر صعوبة (أقل 3):\n{diff_q_str}\n"
                         f"- الأسئلة الأسهل (أعلى 3):\n{easy_q_str}")
    else:
        text_response = f"فئة الإحصائيات '{stat_category}' غير معروفة أو لم يتم تنفيذها بعد."

    # After fetching and formatting, show the time filter buttons again for the same category
    fetch_base_callback = f"{PREFIX_FETCH_STAT}{stat_category}"
    reply_markup = get_time_filter_buttons(fetch_base_callback)
    query.edit_message_text(text=text_response, reply_markup=reply_markup, parse_mode='Markdown')

# Add handlers to your application
# app.add_handler(CommandHandler("adminstats", admin_panel_command_handler))
# app.add_handler(CallbackQueryHandler(stats_menu_callback_handler, pattern=f"^{PREFIX_MAIN_MENU}"))
# app.add_handler(CallbackQueryHandler(fetch_stats_callback_handler, pattern=f"^{PREFIX_FETCH_STAT}"))

