# -*- coding: utf-8 -*-
"""Handles displaying user statistics and leaderboards."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler
)

# --- New imports for advanced stats ---
import json
import os
from datetime import datetime
import matplotlib
matplotlib.use("Agg") # Use Agg backend for non-interactive plotting
import matplotlib.pyplot as plt
# --- End of new imports ---

# Import necessary components from other modules
try:
    from config import logger, MAIN_MENU, STATS_MENU, LEADERBOARD_LIMIT
    from database.manager import DB_MANAGER 
    from utils.helpers import safe_send_message, safe_edit_message_text, format_duration
    from handlers.common import main_menu_callback # For returning to main menu
except ImportError as e:
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error(f"Error importing modules in handlers.stats: {e}. Using placeholders.")
    MAIN_MENU, STATS_MENU = 0, 8
    LEADERBOARD_LIMIT = 10
    DB_MANAGER = None
    async def safe_send_message(*args, **kwargs): logger.error("Placeholder safe_send_message called!")
    async def safe_edit_message_text(*args, **kwargs): logger.error("Placeholder safe_edit_message_text called!")
    def format_duration(seconds): logger.warning("Placeholder format_duration called!"); return f"{seconds}s"
    async def main_menu_callback(*args, **kwargs): logger.error("Placeholder main_menu_callback called!"); return MAIN_MENU

# --- Directory for user stats (JSON files and charts) ---
USER_STATS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_data", "stats")
os.makedirs(USER_STATS_DIR, exist_ok=True)

# --- Helper Functions for Advanced Stats (JSON based) ---
def load_user_stats_from_json(user_id: int) -> dict:
    stats_file = os.path.join(USER_STATS_DIR, f"{user_id}.json")
    if os.path.exists(stats_file):
        try:
            with open(stats_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading stats for user {user_id} from JSON: {e}")
            return {}
    return {}

def save_user_stats_to_json(user_id: int, stats_data: dict) -> None:
    stats_file = os.path.join(USER_STATS_DIR, f"{user_id}.json")
    try:
        with open(stats_file, "w", encoding="utf-8") as f:
            json.dump(stats_data, f, ensure_ascii=False, indent=4)
    except IOError as e:
        logger.error(f"Error saving stats for user {user_id} to JSON: {e}")

def update_user_stats_in_json(user_id: int, score: float, total_questions_in_quiz: int, correct_answers_count: int, incorrect_answers_count: int, quiz_id: str = None):
    stats = load_user_stats_from_json(user_id)
    
    stats["total_quizzes_taken"] = stats.get("total_quizzes_taken", 0) + 1
    stats["total_correct_answers"] = stats.get("total_correct_answers", 0) + correct_answers_count
    stats["total_incorrect_answers"] = stats.get("total_incorrect_answers", 0) + incorrect_answers_count
    
    stats["sum_of_scores_achieved"] = stats.get("sum_of_scores_achieved", 0) + (score / 100 * total_questions_in_quiz)
    stats["sum_of_total_possible_scores"] = stats.get("sum_of_total_possible_scores", 0) + total_questions_in_quiz
    
    if stats["sum_of_total_possible_scores"] > 0:
        stats["average_score_percentage"] = (stats["sum_of_scores_achieved"] / stats["sum_of_total_possible_scores"]) * 100
    else:
        stats["average_score_percentage"] = 0
        
    stats["highest_score_percentage"] = max(stats.get("highest_score_percentage", 0), score)
    
    quiz_history = stats.get("quiz_history", [])
    # *** Line 83 Fix: Changed f-string to concatenation for quiz_id generation ***
    generated_quiz_id = "quiz_" + datetime.now().strftime('%Y%m%d%H%M%S')
    quiz_record = {
        "quiz_id": quiz_id if quiz_id else generated_quiz_id,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "score_percentage": score,
        "correct_answers": correct_answers_count,
        "incorrect_answers": incorrect_answers_count,
        "total_questions": total_questions_in_quiz
    }
    quiz_history.append(quiz_record)
    stats["quiz_history"] = quiz_history[-5:]
        
    save_user_stats_to_json(user_id, stats)
    logger.info(f"JSON stats updated for user {user_id} after quiz {quiz_id if quiz_id else 'N/A'}.") # This f-string is usually fine.

# --- Chart Generation Functions ---
def generate_bar_chart_correct_incorrect(user_id: int, correct: int, incorrect: int) -> str | None:
    if correct == 0 and incorrect == 0:
        return None
    fig, ax = plt.subplots(figsize=(8, 6))
    categories = ["إجابات صحيحة", "إجابات خاطئة"]
    counts = [correct, incorrect]
    colors = ["#4CAF50", "#F44336"]
    bars = ax.bar(categories, counts, color=colors)
    ax.set_ylabel("العدد")
    ax.set_title(f"مقارنة الإجابات للمستخدم {user_id}", pad=20)
    ax.tick_params(axis="x", labelsize=12)
    ax.tick_params(axis="y", labelsize=12)
    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 0.05 * max(counts) if max(counts)>0 else 0.5, int(yval), ha="center", va="bottom", fontsize=11)
    
    chart_path = os.path.join(USER_STATS_DIR, f"{user_id}_correct_incorrect_chart.png")
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
    grades = {"ممتاز (90+)": 0, "جيد جداً (80-89)": 0, "جيد (70-79)": 0, "مقبول (60-69)": 0, "يحتاج تحسين (<60)": 0}
    for quiz in quiz_history:
        score = quiz.get("score_percentage", 0)
        if score >= 90: grades["ممتاز (90+)"] += 1
        elif score >= 80: grades["جيد جداً (80-89)"] += 1
        elif score >= 70: grades["جيد (70-79)"] += 1
        elif score >= 60: grades["مقبول (60-69)"] += 1
        else: grades["يحتاج تحسين (<60)"] += 1
    
    if all(v == 0 for v in grades.values()): return None

    fig, ax = plt.subplots(figsize=(10, 7))
    categories = list(grades.keys())
    counts = list(grades.values())
    colors = ["#4CAF50", "#8BC34A", "#CDDC39", "#FFEB3B", "#FFC107", "#F44336"][::-1]
    bars = ax.barh(categories, counts, color=colors[:len(categories)])
    ax.set_xlabel("عدد الاختبارات")
    ax.set_title(f"توزيع تقديرات الاختبارات للمستخدم {user_id}", pad=20)
    ax.tick_params(axis="x", labelsize=12)
    ax.tick_params(axis="y", labelsize=12)
    for i, bar in enumerate(bars):
        xval = bar.get_width()
        ax.text(xval + 0.02 * max(counts) if max(counts)>0 else 0.2, i, int(xval), ha="left", va="center", fontsize=11)

    chart_path = os.path.join(USER_STATS_DIR, f"{user_id}_grades_dist_chart.png")
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        return chart_path
    except Exception as e:
        logger.error(f"Error generating grades distribution chart for user {user_id}: {e}")
        return None

def generate_line_chart_performance_trend(user_id: int, quiz_history: list) -> str | None:
    if not quiz_history or len(quiz_history) < 2:
        return None
    
    scores = [quiz.get("score_percentage", 0) for quiz in quiz_history]
    test_numbers = list(range(1, len(quiz_history) + 1))

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(test_numbers, scores, marker="o", linestyle="-", color="#007BFF", linewidth=2, markersize=8)
    ax.set_xlabel("رقم الاختبار (الأحدث على اليمين)")
    ax.set_ylabel("النتيجة (%)")
    ax.set_title(f"تطور الأداء للمستخدم {user_id} (آخر {len(quiz_history)} اختبارات)", pad=20)
    ax.grid(True, linestyle="--", alpha=0.7)
    ax.tick_params(axis="both", labelsize=12)
    ax.set_ylim(0, 105)
    ax.set_xticks(test_numbers)
    
    for i, score_val in enumerate(scores):
        ax.text(test_numbers[i], score_val + 2, f"{score_val:.1f}%", ha="center", fontsize=10)

    chart_path = os.path.join(USER_STATS_DIR, f"{user_id}_performance_trend_chart.png")
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        return chart_path
    except Exception as e:
        logger.error(f"Error generating performance trend chart for user {user_id}: {e}")
        return None

# --- Original Helper Functions from user"s stats.py --- 
def create_stats_menu_keyboard() -> InlineKeyboardMarkup:
    """Creates the main keyboard for the statistics section."""
    keyboard = [
        [InlineKeyboardButton("📊 إحصائياتي", callback_data="stats_my_stats")],
        [InlineKeyboardButton("🏆 لوحة الصدارة", callback_data="stats_leaderboard")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Conversation Steps --- 
async def stats_menu(update: Update, context: CallbackContext) -> int:
    """Displays the main statistics menu."""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if query:
        await query.answer()
        logger.info(f"User {user_id} entered stats menu.")
        text = "🏅 اختر الإحصائيات التي تريد عرضها:"
        keyboard = create_stats_menu_keyboard()
        # *** safe_edit_message_text fix: Added context.bot ***
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=text, reply_markup=keyboard)
    else:
        logger.warning("stats_menu called without callback query.")
        text = "🏅 اختر الإحصائيات التي تريد عرضها:"
        keyboard = create_stats_menu_keyboard()
        await safe_send_message(context.bot, update.effective_chat.id, text=text, reply_markup=keyboard)
        
    return STATS_MENU

# --- MODIFIED show_my_stats function with advanced logic and charts ---
async def show_my_stats(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requested personal stats (advanced).")

    stats_data = load_user_stats_from_json(user_id)
    attachments = []
    stats_text = f"📊 *إحصائياتك المفصلة يا {update.effective_user.first_name}* 📊\n\n══════════════════════\n📝 ملخص الأداء العام:\n"

    if not stats_data or stats_data.get("total_quizzes_taken", 0) == 0:
        stats_text += "لم تقم بإكمال أي اختبارات بعد. ابدأ اختباراً لتظهر إحصائياتك هنا!"
    else:
        stats_text += f"🔹 إجمالي الاختبارات المكتملة: {stats_data.get('total_quizzes_taken', 0)}\n"
        avg_score = stats_data.get("average_score_percentage", 0.0)
        stats_text += f"🔸 متوسط الدقة الإجمالي: {avg_score:.1f}%\n"
        stats_text += f"🌟 أعلى نتيجة فردية: {stats_data.get('highest_score_percentage', 0.0):.1f}%\n\n"
        total_correct = stats_data.get("total_correct_answers", 0)
        total_incorrect = stats_data.get("total_incorrect_answers", 0)
        stats_text += f"✅ مجموع الإجابات الصحيحة: {total_correct}\n"
        stats_text += f"❌ مجموع الإجابات الخاطئة: {total_incorrect}\n"

        chart1_path = generate_bar_chart_correct_incorrect(user_id, total_correct, total_incorrect)
        if chart1_path: attachments.append(chart1_path)

        quiz_history = stats_data.get("quiz_history", [])
        chart2_path = generate_bar_chart_grades_distribution(user_id, quiz_history)
        if chart2_path: attachments.append(chart2_path)
        
        chart3_path = generate_line_chart_performance_trend(user_id, quiz_history)
        if chart3_path: attachments.append(chart3_path)

        if quiz_history:
            stats_text += "\n══════════════════════\n📜 سجل آخر اختباراتك:\n"
            for i, test in enumerate(quiz_history):
                stats_text += f"{i+1}. بتاريخ {test.get('date', 'N/A')}: {test.get('score_percentage', 0):.1f}% (صحيحة: {test.get('correct_answers',0)}، خاطئة: {test.get('incorrect_answers',0)})\n"
        stats_text += "\n══════════════════════\n💡 نصيحة: استمر في التعلم والممارسة لتحسين نتائجك!"

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لقائمة الإحصائيات", callback_data="stats_menu")]])
    # *** safe_edit_message_text fix: Added context.bot ***
    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=stats_text, reply_markup=keyboard, parse_mode="Markdown")
    
    if attachments:
        for attachment_path in attachments:
            try:
                await context.bot.send_photo(chat_id=query.message.chat_id, photo=open(attachment_path, "rb"))
            except Exception as e:
                logger.error(f"Failed to send chart {attachment_path} for user {user_id}: {e}")    
        
    return STATS_MENU

async def show_leaderboard(update: Update, context: CallbackContext) -> int:
    """Fetches and displays the leaderboard."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requested leaderboard.")

    leaderboard_text = f"🏆 *لوحة الصدارة (أفضل {LEADERBOARD_LIMIT} لاعبين)*\n\n"
    rank_emojis = ["🥇", "🥈", "🥉"] + ["🏅"] * (LEADERBOARD_LIMIT - 3)

    if DB_MANAGER:
        leaderboard_data = DB_MANAGER.get_leaderboard(limit=LEADERBOARD_LIMIT)
        if leaderboard_data:
            for i, entry in enumerate(leaderboard_data):
                rank = rank_emojis[i] if i < len(rank_emojis) else f"{i+1}."
                user_id_entry = entry.get('user_id', 'Unknown')
                display_name = entry.get('user_display_name', f"User {user_id_entry}")
                safe_display_name = display_name.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`")
                avg_score = entry.get('average_score', 0.0)
                quizzes_taken = entry.get('quizzes_taken', 0)
                leaderboard_text += f"{rank} {safe_display_name} - متوسط: {avg_score:.1f}% ({quizzes_taken} اختبار)\n"
        else:
            leaderboard_text += "لا توجد بيانات كافية لعرض لوحة الصدارة بعد."
    else:
        leaderboard_text += "عذراً، لا يمكن استرجاع لوحة الصدارة حالياً (مشكلة في قاعدة البيانات)."

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لقائمة الإحصائيات", callback_data="stats_menu")]])
    # *** safe_edit_message_text fix: Added context.bot ***
    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=leaderboard_text, reply_markup=keyboard, parse_mode="Markdown")
    
    return STATS_MENU

# --- Conversation Handler Definition (Original) --- 
stats_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(stats_menu, pattern="^menu_stats$")], 
    states={
        STATS_MENU: [
            CallbackQueryHandler(show_my_stats, pattern="^stats_my_stats$"),
            CallbackQueryHandler(show_leaderboard, pattern="^stats_leaderboard$"),
            CallbackQueryHandler(stats_menu, pattern="^stats_menu$"),
            CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")
        ],
    },
    fallbacks=[
        CommandHandler("start", main_menu_callback),
        CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"),
        CallbackQueryHandler(stats_menu, pattern=".*")
    ],
    map_to_parent={
        MAIN_MENU: MAIN_MENU,
    },
    persistent=True,
    name="stats_conversation"
)


