from datetime import datetime
"""Module for generating display content (text and charts) for the Admin Dashboard."""

import logging
import os
import matplotlib
matplotlib.use("Agg")  # Use Agg backend for non-interactive plotting
import matplotlib.pyplot as plt
from matplotlib import font_manager

# Configure Matplotlib for Arabic text
# Ensure you have an Arabic font like Amiri or DejaVu Sans installed in the environment
# plt.rcParams["font.family"] = ["DejaVu Sans", "Amiri", "Arial"]  # Add fallbacks
# Using a specific font path might be more reliable in some environments
try:
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf" # Common path on Linux
    if os.path.exists(font_path):
        font_manager.fontManager.addfont(font_path)
        plt.rcParams["font.family"] = "DejaVu Sans"
    else:
        # Fallback if DejaVuSans is not in the expected path, try Amiri or system default
        # This requires Amiri to be installed or relying on Matplotlib's font finding
        plt.rcParams["font.family"] = ["Amiri", "Arial", "sans-serif"]
except Exception as e:
    logging.warning(f"Font setup issue: {e}. Using Matplotlib defaults.")
    plt.rcParams["font.family"] = "sans-serif"

plt.rcParams["axes.unicode_minus"] = False  # Ensure minus sign is displayed correctly

import arabic_reshaper
from bidi.algorithm import get_display

from database.manager import DB_MANAGER
from config import logger  # Assuming logger is configured in config.py

# --- Directory for charts ---
# Assuming this script is in handlers/, so ../ to go to project root, then user_data/charts
CHARTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_data", "charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

# Helper function for processing Arabic text for Matplotlib
def process_arabic_text(text_to_process):
    text_str = str(text_to_process)
    # Basic check if text contains Arabic characters
    is_arabic = any("\u0600" <= char_val <= "\u06FF" for char_val in text_str)
    if not is_arabic:
        return text_str
    try:
        reshaped_text = arabic_reshaper.reshape(text_str)
        bidi_text = get_display(reshaped_text)
        return bidi_text
    except Exception as ex_arabic:
        logger.error(f"Error processing Arabic text with reshaper/bidi: {ex_arabic}. Text was: {text_to_process}")
        return text_str  # Fallback

TIME_FILTERS_DISPLAY = {
    "today": "اليوم",
    "last_7_days": "آخر 7 أيام",
    "last_30_days": "آخر 30 يومًا",
    "all_time": "كل الوقت"
}

def generate_usage_overview_chart(active_users: int, total_quizzes_in_period: int, time_filter: str) -> str | None:
    if active_users == 0 and total_quizzes_in_period == 0:
        return None

    fig, ax = plt.subplots(figsize=(8, 6))
    categories = [process_arabic_text("المستخدمون النشطون"), process_arabic_text("الاختبارات المجراة")]
    counts = [active_users, total_quizzes_in_period]
    colors = ["#1f77b4", "#ff7f0e"]  # Blue and Orange

    bars = ax.bar(categories, counts, color=colors, width=0.5)
    ax.set_ylabel(process_arabic_text("العدد"))
    time_filter_display = TIME_FILTERS_DISPLAY.get(time_filter, time_filter)
    ax.set_title(process_arabic_text(f"نظرة عامة على الاستخدام ({time_filter_display})"), pad=20)
    ax.tick_params(axis=	'x	', labelsize=12)
    ax.tick_params(axis=	'y	', labelsize=12)

    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 0.02 * max(counts) if max(counts) > 0 else 0.5, int(yval), ha="center", va="bottom", fontsize=11)
    
    chart_filename = f"usage_overview_{time_filter}_{datetime.now().strftime(	'%Y%m%d%H%M%S	')}.png"
    chart_path = os.path.join(CHARTS_DIR, chart_filename)
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        logger.info(f"Generated usage overview chart: {chart_path}")
        return chart_path
    except Exception as e:
        logger.error(f"Error generating usage overview chart for time_filter {time_filter}: {e}")
        plt.close(fig) # Ensure figure is closed on error
        return None

async def get_usage_overview_display(time_filter: str) -> tuple[str, str | None]:
    """Fetches data for usage overview and prepares text and chart."""
    total_users_overall = DB_MANAGER.get_total_users_count()
    active_users_period = DB_MANAGER.get_active_users_count(time_filter=time_filter)
    total_quizzes_period = DB_MANAGER.get_total_quizzes_count(time_filter=time_filter)
    avg_quizzes_active_user_period = DB_MANAGER.get_average_quizzes_per_active_user(time_filter=time_filter)

    time_filter_display = TIME_FILTERS_DISPLAY.get(time_filter, time_filter)

    text_response = (
        f"📊 *نظرة عامة على الاستخدام ({time_filter_display}):*\n"
        f"- إجمالي المستخدمين (الكلي): {total_users_overall}\n"
        f"- المستخدمون النشطون ({time_filter_display}): {active_users_period}\n"
        f"- إجمالي الاختبارات ({time_filter_display}): {total_quizzes_period}\n"
        f"- متوسط الاختبارات لكل مستخدم نشط ({time_filter_display}): {avg_quizzes_active_user_period:.2f}"
    )

    chart_path = None
    if active_users_period > 0 or total_quizzes_period > 0:
        chart_path = generate_usage_overview_chart(active_users_period, total_quizzes_period, time_filter)
    
    return text_response, chart_path

# Placeholder for other display generation functions
async def get_quiz_performance_display(time_filter: str) -> tuple[str, str | None]:
    # TODO: Implement data fetching, text summary, and chart generation
    logger.info(f"[AdminDashboardDisplay] get_quiz_performance_display called for {time_filter}")
    # Example data (replace with actual DB_MANAGER calls)
    avg_correct = DB_MANAGER.get_overall_average_score(time_filter=time_filter)
    text_response = f"📈 *أداء الاختبارات ({TIME_FILTERS_DISPLAY.get(time_filter, time_filter)}):*\n- متوسط نسبة الإجابات الصحيحة: {float(avg_correct):.2f}%\n(تفاصيل إضافية ورسوم بيانية ستضاف هنا)"
    return text_response, None # No chart yet

async def get_user_interaction_display(time_filter: str) -> tuple[str, str | None]:
    # TODO: Implement data fetching, text summary, and chart generation
    logger.info(f"[AdminDashboardDisplay] get_user_interaction_display called for {time_filter}")
    avg_completion_time = DB_MANAGER.get_average_quiz_duration(time_filter=time_filter)
    completion_stats = DB_MANAGER.get_quiz_completion_rate_stats(time_filter=time_filter)
    completion_rate = completion_stats.get("completion_rate", 0.0)
    text_response = f"👥 *تفاعل المستخدمين ({TIME_FILTERS_DISPLAY.get(time_filter, time_filter)}):*\n- متوسط وقت إكمال الاختبار: {float(avg_completion_time):.2f} ثانية\n- معدل إكمال الاختبارات: {float(completion_rate):.2f}%\n(تفاصيل إضافية ورسوم بيانية ستضاف هنا)"
    return text_response, None # No chart yet

async def get_question_stats_display(time_filter: str) -> tuple[str, str | None]:
    # TODO: Implement data fetching, text summary, and chart generation
    logger.info(f"[AdminDashboardDisplay] get_question_stats_display called for {time_filter}")
    question_difficulty_data = DB_MANAGER.get_question_difficulty_stats(time_filter=time_filter, limit=3)
    text_response = f"❓ *إحصائيات الأسئلة ({TIME_FILTERS_DISPLAY.get(time_filter, time_filter)}):*\n(تفاصيل الأسئلة الأكثر صعوبة وسهولة ورسوم بيانية ستضاف هنا)"
    return text_response, None # No chart yet


