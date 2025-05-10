"""Handles displaying user statistics and leaderboards (MODIFIED TO IMPORT DB_MANAGER DIRECTLY).
(PERSISTENCE_FIX: Set stats_conv_handler to persistent=False)
(FSTRING_DEBUG: Changed one f-string to .format() in show_my_stats)
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler
)

import os
from datetime import datetime
import matplotlib
matplotlib.use("Agg") # Use Agg backend for non-interactive plotting
import matplotlib.pyplot as plt
from matplotlib import font_manager

# Configure Matplotlib for Arabic text
plt.rcParams['font.family'] = ['DejaVu Sans', 'Amiri', 'Arial'] # Add fallbacks
plt.rcParams['axes.unicode_minus'] = False # Ensure minus sign is displayed correctly

# +++ MODIFICATION: Import DB_MANAGER directly +++
# Make sure the new manager file is placed correctly for this import
from database.manager import DB_MANAGER 
# +++++++++++++++++++++++++++++++++++++++++++++++

# Import necessary components from other modules
try:
    from config import logger, MAIN_MENU, STATS_MENU, ADMIN_STATS_MENU, LEADERBOARD_LIMIT
    from utils.helpers import safe_send_message, safe_edit_message_text, format_duration
    from handlers.common import main_menu_callback # For returning to main menu
except ImportError as e:
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error(f"Error importing modules in handlers.stats: {e}. Using placeholders.")
    MAIN_MENU, STATS_MENU, ADMIN_STATS_MENU = 0, 8, 9 # Added ADMIN_STATS_MENU placeholder
    LEADERBOARD_LIMIT = 10
    async def safe_send_message(*args, **kwargs): logger.error("Placeholder safe_send_message called!")
    async def safe_edit_message_text(*args, **kwargs): logger.error("Placeholder safe_edit_message_text called!")
    def format_duration(seconds): logger.warning("Placeholder format_duration called!"); return f"{seconds}s"
    async def main_menu_callback(*args, **kwargs): logger.error("Placeholder main_menu_callback called!"); return MAIN_MENU

import arabic_reshaper
from bidi.algorithm import get_display

# Helper function for processing Arabic text for Matplotlib
def process_arabic_text(text_to_process):
    text_str = str(text_to_process)
    is_arabic = False
    for char_val in text_str:
        if ('\u0600' <= char_val <= '\u06FF' or # Arabic
            '\u0750' <= char_val <= '\u077F' or # Arabic Supplement
            '\u08A0' <= char_val <= '\u08FF' or # Arabic Extended-A
            '\uFB50' <= char_val <= '\uFDFF' or # Arabic Presentation Forms-A
            '\uFE70' <= char_val <= '\uFEFF'):  # Arabic Presentation Forms-B
            is_arabic = True
            break
    if not is_arabic:
        return text_str
    try:
        reshaped_text = arabic_reshaper.reshape(text_str)
        bidi_text = get_display(reshaped_text)
        return bidi_text
    except Exception:
        return text_str # Fallback


# --- Directory for charts ---
CHARTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_data", "charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

# --- Chart Generation Functions (Unchanged from previous version) ---
def generate_bar_chart_correct_incorrect(user_id: int, correct: int, incorrect: int) -> str | None:
    if correct == 0 and incorrect == 0:
        return None
    fig, ax = plt.subplots(figsize=(8, 6))
    categories = [process_arabic_text("إجابات صحيحة"), process_arabic_text("إجابات خاطئة")]
    counts = [correct, incorrect]
    colors = ["#4CAF50", "#F44336"]
    bars = ax.bar(categories, counts, color=colors)
    ax.set_ylabel(process_arabic_text("العدد"))
    ax.set_title(process_arabic_text(f"مقارنة الإجابات للمستخدم {user_id}"), pad=20)
    ax.tick_params(axis="x", labelsize=12)
    ax.tick_params(axis="y", labelsize=12)
    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 0.05 * max(counts) if max(counts)>0 else 0.5, int(yval), ha="center", va="bottom", fontsize=11)
    
    chart_path = os.path.join(CHARTS_DIR, f"{user_id}_correct_incorrect_chart.png")
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        return chart_path
    except Exception as e:
        logger.error(f"Error generating correct/incorrect chart for user {user_id}: {e}")
        return None

def generate_bar_chart_grades_distribution(user_id: int, quiz_history: list) -> str | None:
    if not quiz_history:
        return None
    grades = {process_arabic_text("ممتاز (90+)"): 0, process_arabic_text("جيد جداً (80-89)"): 0, process_arabic_text("جيد (70-79)"): 0, process_arabic_text("مقبول (60-69)"): 0, process_arabic_text("يحتاج تحسين (<60)"): 0}
    for quiz in quiz_history:
        score = quiz.get("score_percentage") 
        if score is not None:
            if score >= 90: grades[process_arabic_text("ممتاز (90+)")] += 1
            elif score >= 80: grades[process_arabic_text("جيد جداً (80-89)")] += 1
            elif score >= 70: grades[process_arabic_text("جيد (70-79)")] += 1
            elif score >= 60: grades[process_arabic_text("مقبول (60-69)")] += 1
            else: grades[process_arabic_text("يحتاج تحسين (<60)")] += 1
        else:
            logger.warning(f"[Stats Chart] Quiz entry for user {user_id} has None score_percentage. Skipping for grade distribution.")
    
    if all(v == 0 for v in grades.values()): return None

    fig, ax = plt.subplots(figsize=(10, 7))
    categories = list(grades.keys())
    counts = list(grades.values())
    colors = ["#4CAF50", "#8BC34A", "#CDDC39", "#FFEB3B", "#FFC107", "#F44336"][::-1]
    bars = ax.barh(categories, counts, color=colors[:len(categories)])
    ax.set_xlabel(process_arabic_text("عدد الاختبارات"))
    ax.set_title(process_arabic_text(f"توزيع تقديرات الاختبارات للمستخدم {user_id}"), pad=20)
    ax.tick_params(axis="x", labelsize=12)
    ax.tick_params(axis="y", labelsize=12)
    for i, bar in enumerate(bars):
        xval = bar.get_width()
        ax.text(xval + 0.02 * max(counts) if max(counts)>0 else 0.2, i, int(xval), ha="left", va="center", fontsize=11)

    chart_path = os.path.join(CHARTS_DIR, f"{user_id}_grades_dist_chart.png")
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        return chart_path
    except Exception as e:
        logger.error(f"Error generating grades distribution chart for user {user_id}: {e}")
        return None

def generate_line_chart_performance_trend(user_id: int, quiz_history: list) -> str | None:
    valid_quiz_history = [quiz for quiz in quiz_history if quiz.get("score_percentage") is not None]
    if not valid_quiz_history or len(valid_quiz_history) < 2:
        logger.info(f"[Stats Chart] Not enough valid data points to generate performance trend for user {user_id} after filtering None scores.")
        return None
    
    scores = [quiz.get("score_percentage") for quiz in valid_quiz_history] 
    test_numbers = list(range(1, len(valid_quiz_history) + 1))

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(test_numbers, scores, marker="o", linestyle="-", color="#007BFF", linewidth=2, markersize=8)
    ax.set_xlabel(process_arabic_text("رقم الاختبار (الأحدث على اليمين)"))
    ax.set_ylabel(process_arabic_text("النتيجة (%)"))
    ax.set_title(process_arabic_text(f"تطور الأداء للمستخدم {user_id} (آخر {len(valid_quiz_history)} اختبارات صالحة)"), pad=20)
    ax.grid(True, linestyle="--", alpha=0.7)
    ax.tick_params(axis="both", labelsize=12)
    ax.set_ylim(0, 105)
    ax.set_xticks(test_numbers)
    
    for i, score_val in enumerate(scores):
        ax.text(test_numbers[i], score_val + 2, f"{score_val:.1f}%", ha="center", fontsize=10)

    chart_path = os.path.join(CHARTS_DIR, f"{user_id}_performance_trend_chart.png")
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        return chart_path
    except Exception as e:
        logger.error(f"Error generating performance trend chart for user {user_id}: {e}")
        return None

# --- Helper Functions (User Stats) ---
def create_stats_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📊 إحصائياتي", callback_data="stats_my_stats")],
        [InlineKeyboardButton("🏆 لوحة الصدارة", callback_data="stats_leaderboard")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Conversation Steps (User Stats) ---
async def stats_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = update.effective_user.id
    chat_id = query.message.chat_id if query and query.message else update.effective_chat.id

    text = "🏅 اختر الإحصائيات التي تريد عرضها:"
    keyboard = create_stats_menu_keyboard()

    if query:
        await query.answer()
        original_message_id = query.message.message_id if query.message else "N/A"
        logger.info(f"User {user_id} entered stats menu via callback from message ID {original_message_id}.")
        if query.message and query.message.text:
            try:
                await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=text, reply_markup=keyboard)
            except Exception as e:
                logger.warning(f"stats_menu: Failed to edit message {original_message_id} for user {user_id}, sending new. Error: {e}")
                await safe_send_message(context.bot, query.message.chat_id, text=text, reply_markup=keyboard)
        else:
            logger.info(f"stats_menu: Original message (ID: {original_message_id}) for user {user_id} has no text or message is missing. Sending new message.")
            target_chat_id_for_send = query.message.chat_id if query.message else chat_id
            await safe_send_message(context.bot, target_chat_id_for_send, text=text, reply_markup=keyboard)
    else:
        logger.info(f"User {user_id} entered stats menu via command.")
        await safe_send_message(context.bot, chat_id, text=text, reply_markup=keyboard)
    return STATS_MENU

async def show_my_stats(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user_first_name = update.effective_user.first_name
    logger.info(f"User {user_id} requested personal stats (DB-driven).")

    attachments = []
    stats_text = f"📊 *إحصائياتك المفصلة يا {user_first_name}* 📊\n\n══════════════════════\n📝 ملخص الأداء العام:\n"
    db_manager = DB_MANAGER
    if not db_manager:
        stats_text += "عذراً، خدمة الإحصائيات غير متاحة حالياً بسبب مشكلة في الاتصال بقاعدة البيانات."
        logger.critical(f"[Stats] CRITICAL: Imported DB_MANAGER is None or not initialized! Database operations will fail for user {user_id}.")
    else:
        user_overall_stats = db_manager.get_user_overall_stats(user_id)
        user_quiz_history_raw = db_manager.get_user_recent_quiz_history(user_id, limit=LEADERBOARD_LIMIT)

        if not user_overall_stats or user_overall_stats.get("total_quizzes_taken", 0) == 0:
            stats_text += "لم تقم بإكمال أي اختبارات بعد. ابدأ اختباراً لتظهر إحصائياتك هنا!"
        else:
            stats_text += f"🔹 إجمالي الاختبارات المكتملة: {user_overall_stats.get('total_quizzes_taken', 0)}\n"
            avg_score = user_overall_stats.get("average_score_percentage", 0.0)
            stats_text += f"🔸 متوسط الدقة الإجمالي: {avg_score:.1f}%\n"
            stats_text += f"🌟 أعلى نتيجة فردية: {user_overall_stats.get('highest_score_percentage', 0.0):.1f}%\n\n"
            total_correct = user_overall_stats.get("total_correct_answers", 0)
            total_questions_attempted = user_overall_stats.get("total_questions_attempted", 0)
            total_incorrect = total_questions_attempted - total_correct
            stats_text += f"✅ مجموع الإجابات الصحيحة: {total_correct}\n"
            stats_text += f"❌ مجموع الإجابات الخاطئة: {total_incorrect}\n"

            chart1_path = generate_bar_chart_correct_incorrect(user_id, total_correct, total_incorrect)
            if chart1_path: attachments.append(chart1_path)

            quiz_history_for_charts = []
            if user_quiz_history_raw:
                for qh_entry in user_quiz_history_raw:
                    correct_count = qh_entry.get("score", 0)
                    total_q_in_quiz = qh_entry.get("total_questions", 0)
                    quiz_history_for_charts.append({
                        "score_percentage": qh_entry.get("percentage", 0.0),
                        "correct_answers": correct_count,
                        "incorrect_answers": total_q_in_quiz - correct_count,
                        "total_questions": total_q_in_quiz,
                        "date": qh_entry.get("completion_timestamp").strftime("%Y-%m-%d %H:%M:%S") if qh_entry.get("completion_timestamp") else "N/A"
                    })
            
            chart2_path = generate_bar_chart_grades_distribution(user_id, quiz_history_for_charts)
            if chart2_path: attachments.append(chart2_path)
            chart3_path = generate_line_chart_performance_trend(user_id, quiz_history_for_charts)
            if chart3_path: attachments.append(chart3_path)

            if user_quiz_history_raw:
                stats_text += "\n══════════════════════\n📜 سجل آخر اختباراتك:\n"
                for i, test_entry in enumerate(user_quiz_history_raw):
                    test_date = test_entry.get("completion_timestamp").strftime("%Y-%m-%d %H:%M:%S") if test_entry.get("completion_timestamp") else "N/A"
                    score_percent = test_entry.get("percentage", 0.0)
                    correct_ans = test_entry.get("score", 0)
                    total_q = test_entry.get("total_questions", 0)
                    incorrect_ans = total_q - correct_ans
                    details_str = "(صحيحة: {}, خاطئة: {})".format(correct_ans, incorrect_ans)
                    if score_percent is not None:
                        stats_text += "{}. بتاريخ {}: {:.1f}% {}\n".format(i + 1, test_date, score_percent, details_str)
                    else:
                        stats_text += "{}. بتاريخ {}: {} {}\n".format(i + 1, test_date, "N/A", details_str)
            stats_text += "\n══════════════════════\n💡 نصيحة: استمر في التعلم والممارسة لتحسين نتائجك!"

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لقائمة الإحصائيات", callback_data="stats_menu")]])
    message_id_to_edit = query.message.message_id if query and query.message else None
    
    if message_id_to_edit:
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=message_id_to_edit, text=stats_text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        logger.warning(f"show_my_stats: No message to edit for user {user_id}. Sending new message.")
        await safe_send_message(context.bot, query.message.chat_id if query and query.message else update.effective_chat.id, text=stats_text, reply_markup=keyboard, parse_mode="Markdown")

    if attachments:
        for attachment_path in attachments:
            try:
                with open(attachment_path, "rb") as photo_file:
                    await context.bot.send_photo(chat_id=query.message.chat_id, photo=photo_file)
                logger.info(f"Sent chart {attachment_path} to user {user_id}")
            except Exception as e:
                logger.error(f"Failed to send chart {attachment_path} to user {user_id}: {e}")
    return STATS_MENU

async def show_leaderboard(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requested leaderboard.")

    leaderboard_text = "🏆 *لوحة الصدارة لأفضل اللاعبين* 🏆\n\n"
    db_manager = DB_MANAGER
    if not db_manager:
        leaderboard_text += "عذراً، خدمة لوحة الصدارة غير متاحة حالياً بسبب مشكلة في الاتصال بقاعدة البيانات."
        logger.critical(f"[Leaderboard] CRITICAL: Imported DB_MANAGER is None! Database operations will fail for user {user_id}.")
    else:
        leaderboard_data = db_manager.get_leaderboard(limit=LEADERBOARD_LIMIT)
        if not leaderboard_data:
            leaderboard_text += "لا توجد بيانات كافية لعرض لوحة الصدارة بعد. شارك في المزيد من الاختبارات!"
        else:
            for i, entry in enumerate(leaderboard_data):
                rank = i + 1
                display_name = entry.get("user_display_name", f"مستخدم {entry.get('user_id')}")
                avg_score = entry.get("average_score_percentage", 0.0)
                quizzes_taken = entry.get("total_quizzes_taken", 0)
                medal = ""
                if rank == 1: medal = "🥇"
                elif rank == 2: medal = "🥈"
                elif rank == 3: medal = "🥉"
                leaderboard_text += f"{medal}{rank}. {display_name} - متوسط: {avg_score:.1f}% (من {quizzes_taken} اختبارات)\n"
    
    leaderboard_text += "\n══════════════════════\n💪 استمر في المنافسة لتحقيق أعلى المراكز!"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لقائمة الإحصائيات", callback_data="stats_menu")]])
    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=leaderboard_text, reply_markup=keyboard, parse_mode="Markdown")
    return STATS_MENU

# --- Admin Statistics --- 

ADMIN_STATS_STATE_CHOOSE_PERIOD = 100
ADMIN_STATS_STATE_SHOW_DATA = 101

def create_admin_stats_period_keyboard(stat_type: str) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("اليوم", callback_data=f"admin_stats_period_today_{stat_type}"),
         InlineKeyboardButton("آخر 7 أيام", callback_data=f"admin_stats_period_week_{stat_type}")],
        [InlineKeyboardButton("آخر 30 يوماً", callback_data=f"admin_stats_period_month_{stat_type}"),
         InlineKeyboardButton("كل الوقت", callback_data=f"admin_stats_period_all_{stat_type}")],
        [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="main_menu")] # Or admin menu if exists
    ]
    return InlineKeyboardMarkup(keyboard)

async def admin_stats_start(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    db_manager = DB_MANAGER
    if not db_manager or not db_manager.is_user_admin(user_id):
        await safe_send_message(context.bot, update.effective_chat.id, "عذراً، هذه الميزة متاحة للمشرفين فقط.")
        return ConversationHandler.END

    logger.info(f"Admin user {user_id} accessed admin statistics.")
    text = "📊 لوحة التحكم الإدارية 📊\nاختر نوع الإحصائيات والفترة الزمنية لعرضها:"
    # Main admin stats menu - for now, let's assume we go directly to period selection for a combined view
    # Or, we can have another layer of menu here to choose *which* admin stat to view first.
    # For simplicity, let's start by asking for a period for a general overview.
    
    # We will display multiple stats for the chosen period.
    # So, the callback data for period selection will just be the period itself.
    keyboard_layout = [
        [InlineKeyboardButton("اليوم", callback_data="admin_stats_fetch_today"),
         InlineKeyboardButton("آخر 7 أيام", callback_data="admin_stats_fetch_week")],
        [InlineKeyboardButton("آخر 30 يوماً", callback_data="admin_stats_fetch_month"),
         InlineKeyboardButton("كل الوقت", callback_data="admin_stats_fetch_all")],
        [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="main_menu")]
    ]
    keyboard = InlineKeyboardMarkup(keyboard_layout)
    
    if update.callback_query:
        await update.callback_query.answer()
        await safe_edit_message_text(context.bot, chat_id=update.callback_query.message.chat_id, 
                                   message_id=update.callback_query.message.message_id, 
                                   text=text, reply_markup=keyboard)
    else:
        await safe_send_message(context.bot, update.effective_chat.id, text=text, reply_markup=keyboard)
    
    return ADMIN_STATS_STATE_CHOOSE_PERIOD # Next state: waiting for period selection

async def admin_stats_fetch_and_display(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    time_filter_keyword = query.data.split('_')[-1] # e.g., 'today', 'week', 'month', 'all'
    logger.info(f"Admin {user_id} requested admin stats for period: {time_filter_keyword}")

    db_manager = DB_MANAGER
    if not db_manager:
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="خطأ: لا يمكن الاتصال بقاعدة البيانات.")
        return ConversationHandler.END

    # Fetch all required stats
    total_users = db_manager.get_total_users_count()
    active_users = db_manager.get_active_users_count(time_filter_keyword)
    total_quizzes = db_manager.get_total_quizzes_taken_count(time_filter_keyword)
    avg_score = db_manager.get_average_score_percentage_overall(time_filter_keyword)
    avg_completion_time_secs = db_manager.get_average_quiz_completion_time(time_filter_keyword)
    quiz_completion_rate = db_manager.get_quiz_completion_rate(time_filter_keyword)
    avg_quizzes_per_active_user = db_manager.get_average_quizzes_per_active_user(time_filter_keyword)
    popular_units = db_manager.get_most_popular_units(time_filter_keyword, limit=3)
    question_difficulty = db_manager.get_question_difficulty_stats(time_filter_keyword, limit=3)

    # Format the display text
    period_map = {"today": "اليوم", "week": "آخر 7 أيام", "month": "آخر 30 يوماً", "all": "كل الوقت"}
    display_period = period_map.get(time_filter_keyword, time_filter_keyword)

    stats_text = f"📊 *نظرة عامة على الاستخدام ({display_period}):*\n"
    stats_text += f"  - إجمالي المستخدمين (الكلي): {total_users}\n"
    stats_text += f"  - المستخدمون النشطون: {active_users}\n"
    stats_text += f"  - إجمالي الاختبارات التي تم إجراؤها: {total_quizzes}\n"
    stats_text += f"  - متوسط الاختبارات لكل مستخدم نشط: {avg_quizzes_per_active_user:.2f}\n\n"

    stats_text += f"📈 *أداء الاختبارات ({display_period}):*\n"
    stats_text += f"  - متوسط نسبة الإجابات الصحيحة: {avg_score:.2f}%\n"
    stats_text += f"  - معدل إكمال الاختبارات: {quiz_completion_rate:.2f}%\n"
    stats_text += f"  - متوسط وقت إكمال الاختبار: {format_duration(int(avg_completion_time_secs))}\n\n"
    
    stats_text += f"📚 *الوحدات الأكثر شعبية ({display_period}):*\n"
    if popular_units:
        for i, unit in enumerate(popular_units):
            stats_text += f"  {i+1}. {unit['unit_name']} (اختبرت {unit['quiz_count']} مرات)\n"
    else:
        stats_text += "  - لا توجد بيانات كافية.\n"
    stats_text += "\n"

    stats_text += f"❓ *إحصائيات الأسئلة ({display_period}):*\n"
    stats_text += "  - الأسئلة الأكثر صعوبة (أعلى 3 نسبة خطأ):
"
    if question_difficulty['most_difficult']:
        for i, q_diff in enumerate(question_difficulty['most_difficult']):
            q_text_short = q_diff['question_text'][:50] + "..." if len(q_diff['question_text']) > 50 else q_diff['question_text']
            stats_text += f"    {i+1}. \"{q_text_short}\" (ID: {q_diff['question_id']}) - نسبة الخطأ: {q_diff['incorrect_percentage']:.1f}% ({q_diff['incorrect_count']}/{q_diff['total_attempts']})\n"
    else:
        stats_text += "    - لا توجد بيانات كافية.\n"
    
    stats_text += "  - الأسئلة الأسهل (أعلى 3 نسبة صحة):
"
    if question_difficulty['easiest']:
        for i, q_easy in enumerate(question_difficulty['easiest']):
            q_text_short = q_easy['question_text'][:50] + "..." if len(q_easy['question_text']) > 50 else q_easy['question_text']
            stats_text += f"    {i+1}. \"{q_text_short}\" (ID: {q_easy['question_id']}) - نسبة الصحة: {q_easy['correct_percentage']:.1f}% ({q_easy['correct_count']}/{q_easy['total_attempts']})\n"
    else:
        stats_text += "    - لا توجد بيانات كافية.\n"

    # Re-use the same keyboard for period selection to allow changing the period
    keyboard_layout = [
        [InlineKeyboardButton("اليوم", callback_data="admin_stats_fetch_today"),
         InlineKeyboardButton("آخر 7 أيام", callback_data="admin_stats_fetch_week")],
        [InlineKeyboardButton("آخر 30 يوماً", callback_data="admin_stats_fetch_month"),
         InlineKeyboardButton("كل الوقت", callback_data="admin_stats_fetch_all")],
        [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="main_menu")]
    ]
    keyboard = InlineKeyboardMarkup(keyboard_layout)

    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, 
                               message_id=query.message.message_id, 
                               text=stats_text, reply_markup=keyboard, parse_mode="Markdown")
    
    return ADMIN_STATS_STATE_CHOOSE_PERIOD # Stay in the same state to allow period change or exit


# --- Conversation Handler Setup ---
stats_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(stats_menu, pattern='^stats_menu$'), CommandHandler('stats', stats_menu)],
    states={
        STATS_MENU: [
            CallbackQueryHandler(show_my_stats, pattern='^stats_my_stats$'),
            CallbackQueryHandler(show_leaderboard, pattern='^stats_leaderboard$'),
            CallbackQueryHandler(main_menu_callback, pattern='^main_menu$')
        ]
    },
    fallbacks=[CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'), CommandHandler('start', main_menu_callback)],
    map_to_parent={
        MAIN_MENU: MAIN_MENU # Return to main menu from stats
    },
    persistent=False, # Set to False as per previous fix
    name="stats_conversation"
)

admin_stats_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('adminstats', admin_stats_start)],
    states={
        ADMIN_STATS_STATE_CHOOSE_PERIOD: [
            CallbackQueryHandler(admin_stats_fetch_and_display, pattern='^admin_stats_fetch_(today|week|month|all)$'),
            CallbackQueryHandler(main_menu_callback, pattern='^main_menu$') # Allow returning to main menu
        ]
        # No ADMIN_STATS_STATE_SHOW_DATA needed if we always return to CHOOSE_PERIOD
    },
    fallbacks=[CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'), CommandHandler('start', main_menu_callback)],
    map_to_parent={
        MAIN_MENU: MAIN_MENU 
    },
    persistent=False, 
    name="admin_stats_conversation"
)

# Ensure DB_MANAGER is initialized (it's a singleton, so this is fine)
DB_MANAGER = DB_MANAGER

