"""Handles displaying user statistics and leaderboards (MODIFIED TO IMPORT DB_MANAGER DIRECTLY).
(PERSISTENCE_FIX: Set stats_conv_handler to persistent=False)
(FSTRING_DEBUG: Changed one f-string to .format() in show_my_stats)
(ADMIN_STATS_FIX_V2: Correctly call and display question difficulty stats from DB_MANAGER)
(IMPORT_FIX_V3: Ensuring clean file structure for handler exports)
(FSTRING_FIX_V4: Corrected unmatched parenthesis in an f-string)
(FSTRING_FIX_V5: Simplified complex f-string by using intermediate variables to avoid parsing issues)
(FSTRING_FIX_V6: Replaced specific problematic f-string with .format() to rule out parsing issues for completion rate line)
(FSTRING_FIX_V7: Proactively converted all f-strings in the admin question stats section to .format() to prevent further parsing errors)
(FSTRING_FIX_V8: Comprehensive conversion of nearly ALL f-strings in the file to .format() or string concatenation to eliminate f-string parsing errors entirely.)
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
plt.rcParams["font.family"] = ["DejaVu Sans", "Amiri", "Arial"] # Add fallbacks
plt.rcParams["axes.unicode_minus"] = False # Ensure minus sign is displayed correctly

# +++ MODIFICATION: Import DB_MANAGER directly +++
from database.manager import DB_MANAGER 
# +++++++++++++++++++++++++++++++++++++++++++++++

# Import necessary components from other modules
try:
    from config import logger, MAIN_MENU, STATS_MENU, ADMIN_STATS_MENU, LEADERBOARD_LIMIT
    from utils.helpers import safe_send_message, safe_edit_message_text, format_duration
    from handlers.common import main_menu_callback # For returning to main menu
except ImportError as e:
    # Fallback logger configuration if config import fails
    logging.basicConfig(level=logging.INFO) # Basic config for fallback
    logger = logging.getLogger(__name__) # Use module's name for logger
    # Using .format() for error logging
    logger.error("[stats.py] CRITICAL Error importing core modules (config, helpers, common): {}. Using placeholders. Bot functionality will be SEVERELY AFFECTED.".format(e))
    MAIN_MENU, STATS_MENU, ADMIN_STATS_MENU = 0, 8, 9
    LEADERBOARD_LIMIT = 10
    async def safe_send_message(*args, **kwargs): logger.error("Placeholder safe_send_message called!")
    async def safe_edit_message_text(*args, **kwargs): logger.error("Placeholder safe_edit_message_text called!")
    def format_duration(seconds): logger.warning("Placeholder format_duration called!"); return "{}s".format(seconds)
    async def main_menu_callback(*args, **kwargs): logger.error("Placeholder main_menu_callback called!"); return MAIN_MENU

import arabic_reshaper
from bidi.algorithm import get_display

# Helper function for processing Arabic text for Matplotlib
def process_arabic_text(text_to_process):
    text_str = str(text_to_process)
    is_arabic = False
    for char_val in text_str:
        if (
            "\u0600" <= char_val <= "\u06FF" or # Arabic
            "\u0750" <= char_val <= "\u077F" or # Arabic Supplement
            "\u08A0" <= char_val <= "\u08FF" or # Arabic Extended-A
            "\uFB50" <= char_val <= "\uFDFF" or # Arabic Presentation Forms-A
            "\uFE70" <= char_val <= "\uFEFF"    # Arabic Presentation Forms-B
        ):
            is_arabic = True
            break
    if not is_arabic:
        return text_str
    try:
        reshaped_text = arabic_reshaper.reshape(text_str)
        bidi_text = get_display(reshaped_text)
        return bidi_text
    except Exception as ex_arabic:
        # Using .format() for error logging
        logger.error("Error processing Arabic text with reshaper/bidi: {}. Text was: {}".format(ex_arabic, text_to_process))
        return text_str # Fallback


# --- Directory for charts ---
CHARTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_data", "charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

# --- Chart Generation Functions ---
def generate_bar_chart_correct_incorrect(user_id: int, correct: int, incorrect: int) -> str | None:
    if correct == 0 and incorrect == 0:
        return None
    fig, ax = plt.subplots(figsize=(8, 6))
    categories = [process_arabic_text("إجابات صحيحة"), process_arabic_text("إجابات خاطئة")]
    counts = [correct, incorrect]
    colors = ["#4CAF50", "#F44336"]
    bars = ax.bar(categories, counts, color=colors)
    ax.set_ylabel(process_arabic_text("العدد"))
    # Using .format() for title
    ax.set_title(process_arabic_text("مقارنة الإجابات للمستخدم {}".format(user_id)), pad=20)
    ax.tick_params(axis="x", labelsize=12)
    ax.tick_params(axis="y", labelsize=12)
    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 0.05 * max(counts) if max(counts)>0 else 0.5, int(yval), ha="center", va="bottom", fontsize=11)
    
    # Using .format() for chart path
    chart_path = os.path.join(CHARTS_DIR, "{}_correct_incorrect_chart.png".format(user_id))
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        return chart_path
    except Exception as e:
        # Using .format() for error logging
        logger.error("Error generating correct/incorrect chart for user {}: {}".format(user_id, e))
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
            # Using .format() for warning
            logger.warning("[Stats Chart] Quiz entry for user {} has None score_percentage. Skipping for grade distribution.".format(user_id))
    
    if all(v == 0 for v in grades.values()): return None

    fig, ax = plt.subplots(figsize=(10, 7))
    categories = list(grades.keys())
    counts = list(grades.values())
    colors = ["#4CAF50", "#8BC34A", "#CDDC39", "#FFEB3B", "#FFC107", "#F44336"][::-1]
    bars = ax.barh(categories, counts, color=colors[:len(categories)])
    ax.set_xlabel(process_arabic_text("عدد الاختبارات"))
    # Using .format() for title
    ax.set_title(process_arabic_text("توزيع تقديرات الاختبارات للمستخدم {}".format(user_id)), pad=20)
    ax.tick_params(axis="x", labelsize=12)
    ax.tick_params(axis="y", labelsize=12)
    for i, bar in enumerate(bars):
        xval = bar.get_width()
        ax.text(xval + 0.02 * max(counts) if max(counts)>0 else 0.2, i, int(xval), ha="left", va="center", fontsize=11)

    # Using .format() for chart path
    chart_path = os.path.join(CHARTS_DIR, "{}_grades_dist_chart.png".format(user_id))
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        return chart_path
    except Exception as e:
        # Using .format() for error logging
        logger.error("Error generating grades distribution chart for user {}: {}".format(user_id, e))
        return None

def generate_line_chart_performance_trend(user_id: int, quiz_history: list) -> str | None:
    valid_quiz_history = [quiz for quiz in quiz_history if quiz.get("score_percentage") is not None]
    if not valid_quiz_history or len(valid_quiz_history) < 2:
        # Using .format() for info logging
        logger.info("[Stats Chart] Not enough valid data points to generate performance trend for user {} after filtering None scores.".format(user_id))
        return None
    
    scores = [quiz.get("score_percentage") for quiz in valid_quiz_history] 
    test_numbers = list(range(1, len(valid_quiz_history) + 1))

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(test_numbers, scores, marker="o", linestyle="-", color="#007BFF", linewidth=2, markersize=8)
    ax.set_xlabel(process_arabic_text("رقم الاختبار (الأحدث على اليمين)"))
    ax.set_ylabel(process_arabic_text("النتيجة (%)"))
    # Using .format() for title
    ax.set_title(process_arabic_text("تطور الأداء للمستخدم {} (آخر {} اختبارات صالحة)".format(user_id, len(valid_quiz_history))), pad=20)
    ax.grid(True, linestyle="--", alpha=0.7)
    ax.tick_params(axis="both", labelsize=12)
    ax.set_ylim(0, 105)
    ax.set_xticks(test_numbers)
    
    for i, score_val in enumerate(scores):
        # Using .format() for text annotation
        ax.text(test_numbers[i], score_val + 2, "{:.1f}%".format(score_val), ha="center", fontsize=10)

    # Using .format() for chart path
    chart_path = os.path.join(CHARTS_DIR, "{}_performance_trend_chart.png".format(user_id))
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        return chart_path
    except Exception as e:
        # Using .format() for error logging
        logger.error("Error generating performance trend chart for user {}: {}".format(user_id, e))
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
        # Using .format() for info logging
        logger.info("User {} entered stats menu via callback from message ID {}.".format(user_id, original_message_id))
        if query.message and query.message.text:
            try:
                await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=text, reply_markup=keyboard)
            except Exception as e:
                # Using .format() for warning
                logger.warning("stats_menu: Failed to edit message {} for user {}, sending new. Error: {}".format(original_message_id, user_id, e))
                await safe_send_message(context.bot, query.message.chat_id, text=text, reply_markup=keyboard)
        else:
            # Using .format() for info logging
            logger.info("stats_menu: Original message (ID: {}) for user {} has no text or message is missing. Sending new message.".format(original_message_id, user_id))
            target_chat_id_for_send = query.message.chat_id if query.message else chat_id
            await safe_send_message(context.bot, target_chat_id_for_send, text=text, reply_markup=keyboard)
    else:
        # Using .format() for info logging
        logger.info("User {} entered stats menu via command.".format(user_id))
        await safe_send_message(context.bot, chat_id, text=text, reply_markup=keyboard)
    return STATS_MENU

async def show_my_stats(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user_first_name = update.effective_user.first_name
    # Using .format() for info logging
    logger.info("User {} requested personal stats (DB-driven).".format(user_id))

    attachments = []
    # Using .format() for stats_text
    stats_text = "📊 *إحصائياتك المفصلة يا {}* 📊\n\n══════════════════════\n📝 ملخص الأداء العام:\n".format(user_first_name)
    db_manager = DB_MANAGER
    if not db_manager:
        stats_text += "عذراً، خدمة الإحصائيات غير متاحة حالياً بسبب مشكلة في الاتصال بقاعدة البيانات."
        # Using .format() for critical logging
        logger.critical("[Stats] CRITICAL: Imported DB_MANAGER is None or not initialized! Database operations will fail for user {}.".format(user_id))
    else:
        user_overall_stats = db_manager.get_user_overall_stats(user_id)
        user_quiz_history_raw = db_manager.get_user_recent_quiz_history(user_id, limit=LEADERBOARD_LIMIT)

        if not user_overall_stats or user_overall_stats.get("total_quizzes_taken", 0) == 0:
            stats_text += "لم تقم بإكمال أي اختبارات بعد. ابدأ اختباراً لتظهر إحصائياتك هنا!"
        else:
            # Using .format() for stats_text lines
            stats_text += "🔹 إجمالي الاختبارات المكتملة: {}\n".format(user_overall_stats.get("total_quizzes_taken", 0))
            avg_score = user_overall_stats.get("average_score_percentage", 0.0)
            stats_text += "🔸 متوسط الدقة الإجمالي: {:.1f}%\n".format(avg_score)
            stats_text += "🌟 أعلى نتيجة فردية: {:.1f}%\n\n".format(user_overall_stats.get("highest_score_percentage", 0.0))
            total_correct = user_overall_stats.get("total_correct_answers", 0)
            total_questions_attempted = user_overall_stats.get("total_questions_attempted", 0)
            total_incorrect = total_questions_attempted - total_correct
            stats_text += "✅ مجموع الإجابات الصحيحة: {}\n".format(total_correct)
            stats_text += "❌ مجموع الإجابات الخاطئة: {}\n".format(total_incorrect)

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
        # Using .format() for warning
        logger.warning("show_my_stats: No message to edit for user {}. Sending new message.".format(user_id))
        await safe_send_message(context.bot, query.message.chat_id if query and query.message else update.effective_chat.id, text=stats_text, reply_markup=keyboard, parse_mode="Markdown")

    if attachments:
        for attachment_path in attachments:
            try:
                with open(attachment_path, "rb") as photo_file:
                    await context.bot.send_photo(chat_id=query.message.chat_id, photo=photo_file)
                # Using .format() for info logging
                logger.info("Sent chart {} to user {}".format(attachment_path, user_id))
            except Exception as e:
                # Using .format() for error logging
                logger.error("Failed to send chart {} to user {}: {}".format(attachment_path, user_id, e))
    return STATS_MENU

async def show_leaderboard(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    # Using .format() for info logging
    logger.info("User {} requested leaderboard.".format(user_id))

    leaderboard_text = "🏆 *لوحة الصدارة لأفضل اللاعبين* 🏆\n\n"
    db_manager = DB_MANAGER
    if not db_manager:
        leaderboard_text += "عذراً، خدمة لوحة الصدارة غير متاحة حالياً."
        # Using .format() for critical logging
        logger.critical("[Leaderboard] CRITICAL: DB_MANAGER is None! Cannot fetch leaderboard for user {}.".format(user_id))
    else:
        leaderboard_data = db_manager.get_leaderboard(limit=LEADERBOARD_LIMIT)
        if leaderboard_data:
            for i, entry in enumerate(leaderboard_data):
                # Using .format() for user_name if needed
                user_name_val = entry.get("user_display_name")
                if not user_name_val:
                    user_name_val = "مستخدم {}".format(entry.get("user_id"))
                avg_score = entry.get("average_score_percentage", 0.0)
                quizzes_taken = entry.get("total_quizzes_taken", 0)
                # Using .format() for leaderboard line
                leaderboard_text += "{}. {} - متوسط: {:.1f}% (من {} اختبارات)\n".format(i+1, user_name_val, avg_score, quizzes_taken)
        else:
            leaderboard_text += "لا توجد بيانات كافية لعرض لوحة الصدارة بعد."
    
    leaderboard_text += "\n══════════════════════"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لقائمة الإحصائيات", callback_data="stats_menu")]])
    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=leaderboard_text, reply_markup=keyboard, parse_mode="Markdown")
    return STATS_MENU

# --- Admin Statistics --- 
ADMIN_STATS_STATE, ADMIN_STATS_FILTER_STATE = range(ADMIN_STATS_MENU, ADMIN_STATS_MENU + 2)

async def admin_stats_panel(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = update.effective_user.id
    chat_id = query.message.chat_id if query and query.message else update.effective_chat.id
    db_manager = DB_MANAGER # Use the directly imported instance

    if not db_manager:
        current_logger = logger if "logger" in globals() and logger else logging.getLogger(__name__)
        # Using .format() for critical logging
        current_logger.critical("[AdminStats] CRITICAL: DB_MANAGER is None! Cannot show admin panel for user {}.".format(user_id))
        await safe_send_message(context.bot, chat_id, "عذراً، لا يمكن الوصول إلى مدير قاعدة البيانات.")
        return ConversationHandler.END

    if not db_manager.is_user_admin(user_id):
        await safe_send_message(context.bot, chat_id, "عذراً، هذه اللوحة مخصصة للمشرفين فقط.")
        # Using .format() for warning
        logger.warning("[AdminStats] Non-admin user {} tried to access admin panel.".format(user_id))
        return ConversationHandler.END

    # Using .format() for user_data key
    time_filter = context.user_data.get("admin_stats_filter_{}".format(user_id), "today")
    # Using .format() for info logging
    logger.info("[AdminStats] Admin user {} accessing panel with filter: {}".format(user_id, time_filter))

    # Using .format() for stats_text title
    stats_text = "📊 *لوحة التحكم الإدارية* ({}) 📊\n\n".format(time_filter.replace("_", " ").capitalize())
    
    stats_text += "*نظرة عامة على الاستخدام: *\n"
    total_users = db_manager.get_total_users_count()
    active_users_general = db_manager.get_active_users_count(time_filter)
    total_quizzes_completed = db_manager.get_total_quizzes_count(time_filter)
    avg_quizzes_per_active_user = db_manager.get_average_quizzes_per_active_user(time_filter)
    # Using .format() for stats_text lines
    stats_text += "- إجمالي المستخدمين (الكلي): {}\n".format(total_users)
    stats_text += "- المستخدمون النشطون: {}\n".format(active_users_general)
    stats_text += "- إجمالي الاختبارات التي تم إجراؤها: {}\n".format(total_quizzes_completed)
    stats_text += "- متوسط الاختبارات لكل مستخدم نشط: {:.2f}\n\n".format(avg_quizzes_per_active_user)

    stats_text += "*أداء الاختبارات: *\n"
    avg_correct_rate = db_manager.get_overall_average_score(time_filter)
    # Using .format() for stats_text line
    stats_text += "- متوسط نسبة الإجابات الصحيحة: {:.2f}%\n".format(avg_correct_rate)
    unit_engagement = db_manager.get_unit_engagement_stats(time_filter=time_filter, limit=3)
    popular_units = unit_engagement.get("popular_units_or_quizzes", [])
    stats_text += "- الوحدات/الاختبارات الأكثر شعبية (أعلى 3):\n"
    if popular_units:
        for i, unit_stat in enumerate(popular_units):
            quiz_name_display = unit_stat.get("quiz_name", "غير معروف")
            times_taken = unit_stat.get("times_taken", 0)
            avg_score_unit = unit_stat.get("average_score", 0.0)
            # Using .format() for stats_text line
            stats_text += "  {}. \"{}\" (لُعِبت {} مرات, متوسط {:.1f}%)\n".format(i+1, quiz_name_display, times_taken, avg_score_unit)
    else:
        stats_text += "  لا توجد بيانات\n"
    stats_text += "\n"
    
    stats_text += "*تفاعل المستخدمين: *\n"
    avg_quiz_duration_secs = db_manager.get_average_quiz_duration(time_filter)
    # Using .format() for stats_text line
    stats_text += "- متوسط وقت إكمال الاختبار: {}\n".format(format_duration(avg_quiz_duration_secs))
    completion_stats = db_manager.get_quiz_completion_rate_stats(time_filter)
    
    completion_rate_val = completion_stats.get("completion_rate", 0.0)
    completed_quizzes_val = completion_stats.get("completed_quizzes", 0)
    started_quizzes_val = completion_stats.get("started_quizzes", 0)
    
    # This was already .format(), kept as is
    line_text_completion_rate = "- معدل إكمال الاختبارات: {:.2f}% (اكتمل {} من {} بدأ)\n\n".format(
        completion_rate_val,
        completed_quizzes_val,
        started_quizzes_val
    )
    stats_text += line_text_completion_rate

    stats_text += "*إحصائيات الأسئلة: *\n"
    question_difficulty_data = db_manager.get_question_difficulty_stats(time_filter=time_filter, limit=3)
    most_difficult_questions = question_difficulty_data.get("most_difficult", [])
    easiest_questions = question_difficulty_data.get("easiest", [])

    stats_text += "- الأسئلة الأكثر صعوبة (أقل 3 إجابة صحيحة):\n"
    if most_difficult_questions:
        for i, q_stat in enumerate(most_difficult_questions):
            q_text = q_stat.get("question_text", "نص السؤال غير متوفر")
            q_text_short = (q_text[:50] + "...") if q_text and len(q_text) > 53 else q_text
            error_perc = q_stat.get("error_percentage", 0.0)
            times_ans = q_stat.get("times_answered", 0)
            # Using .format() for this potentially complex line (already was)
            stats_text += "  {}. \"{}\" ({:.1f}% خطأ من {} إجابات)\n".format(i+1, q_text_short, error_perc, times_ans)
    else:
        stats_text += "  لا توجد بيانات\n"

    stats_text += "- الأسئلة الأسهل (أعلى 3 إجابة صحيحة):\n"
    if easiest_questions:
        for i, q_stat in enumerate(easiest_questions):
            q_text = q_stat.get("question_text", "نص السؤال غير متوفر")
            q_text_short = (q_text[:50] + "...") if q_text and len(q_text) > 53 else q_text
            correct_perc = q_stat.get("correct_percentage", 0.0)
            times_ans = q_stat.get("times_answered", 0)
            # Using .format() for this potentially complex line (already was)
            stats_text += "  {}. \"{}\" ({:.1f}% صحة من {} إجابات)\n".format(i+1, q_text_short, correct_perc, times_ans)
    else:
        stats_text += "  لا توجد بيانات\n"

    stats_text += "\n══════════════════════"

    keyboard = [
        [InlineKeyboardButton("اليوم", callback_data="admin_filter_today"), InlineKeyboardButton("آخر 7 أيام", callback_data="admin_filter_last_7_days")],
        [InlineKeyboardButton("آخر 30 يوماً", callback_data="admin_filter_last_30_days"), InlineKeyboardButton("كل الوقت", callback_data="admin_filter_all")],
        # Using .format() for callback_data
        [InlineKeyboardButton("🔄 تحديث", callback_data="admin_filter_{}".format(time_filter))],
        [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.answer()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=stats_text, reply_markup=reply_markup, parse_mode="Markdown")
    else: 
        await safe_send_message(context.bot, chat_id, text=stats_text, reply_markup=reply_markup, parse_mode="Markdown")
    
    return ADMIN_STATS_FILTER_STATE

async def admin_stats_filter_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = update.effective_user.id
    filter_choice = query.data.replace("admin_filter_", "")
    # Using .format() for user_data key
    context.user_data["admin_stats_filter_{}".format(user_id)] = filter_choice
    # Using .format() for info logging
    logger.info("[AdminStats] User {} changed filter to: {}".format(user_id, filter_choice))
    return await admin_stats_panel(update, context)


# --- Conversation Handlers ---
stats_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(stats_menu, pattern="^stats_menu$")],
    states={
        STATS_MENU: [
            CallbackQueryHandler(show_my_stats, pattern="^stats_my_stats$"),
            CallbackQueryHandler(show_leaderboard, pattern="^stats_leaderboard$"),
            CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")
        ]
    },
    fallbacks=[CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")],
    map_to_parent={
        MAIN_MENU: MAIN_MENU
    },
    name="stats_conversation",
    persistent=False
)

admin_stats_conv_handler = ConversationHandler(
    entry_points=[CommandHandler("adminstats", admin_stats_panel)],
    states={
        ADMIN_STATS_FILTER_STATE: [
            CallbackQueryHandler(admin_stats_filter_callback, pattern="^admin_filter_.+$"),
            CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")
        ]
    },
    fallbacks=[
        CommandHandler("adminstats", admin_stats_panel),
        CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")
    ],
    map_to_parent={
        MAIN_MENU: MAIN_MENU
    },
    name="admin_stats_conversation",
    persistent=False
)

