"""Module for generating display content (text and charts) for the Admin Dashboard.

Version 16: Introduces a separate Arabic text processing function for Matplotlib charts
(`process_arabic_text_for_matplotlib`) which uses both arabic_reshaper and bidi.algorithm.get_display
to ensure correct rendering in charts. The existing `process_arabic_text` (for Telegram messages)
continues to use only arabic_reshaper.

Version 15: Fixes Arabic text processing by only using arabic_reshaper.reshape.
It was observed that using bidi.algorithm.get_display was causing text to reverse.
This version assumes the display environment (Telegram) handles BIDI correctly once shaped.

Version 14: Centralizes Arabic text processing to occur only once, primarily within this module
just before text is used for display or in charts. TIME_FILTERS_DISPLAY now holds raw Arabic.
Ensures Matplotlib keyword error is corrected by using 'ha' and 'va'.
"""

import logging
import os
import matplotlib
matplotlib.use("Agg")  # Use Agg backend for non-interactive plotting
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np # Added for potential numerical operations in charts
from datetime import datetime

# Attempt to import logger from config first
try:
    from config import logger
except ImportError:
    # Fallback to a basic logger if config.logger is not available
    logger = logging.getLogger(__name__)
    logger.warning("Could not import logger from config, using basic logger for this module.")

# Configure Matplotlib for Arabic text
try:
    # Rely on system's default sans-serif font or ensure a suitable one is available.
    # Noto Sans Arabic is often a good choice if available.
    # For now, let's try with the default sans-serif and ensure reshaping/bidi is done.
    plt.rcParams["font.family"] = "sans-serif"
    logger.info("Attempting to use Matplotlib default sans-serif font for charts. Ensure system has Arabic support.")
    # It might be necessary to install fonts like 'fonts-noto-core' or 'fonts-noto-arabicui' on the Render instance
    # and then potentially clear Matplotlib's font cache.
except Exception as e:
    logger.warning(f"Font setup issue: {e}. Using Matplotlib default sans-serif. Arabic text in charts might not render correctly.")
    plt.rcParams["font.family"] = "sans-serif" # Fallback again

plt.rcParams["axes.unicode_minus"] = False

import arabic_reshaper
from bidi.algorithm import get_display # Re-added for Matplotlib specific processing

from database.manager import DB_MANAGER

CHARTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_data", "charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

# For general text (e.g., Telegram messages)
def process_arabic_text(text_to_process):
    if text_to_process is None:
        return ""
    text_str = str(text_to_process) # Ensure it's a string
    is_arabic = any("\u0600" <= char_val <= "\u06FF" for char_val in text_str)
    if not is_arabic:
        return text_str 
    try:
        reshaped_text = arabic_reshaper.reshape(text_str)
        return reshaped_text
    except Exception as ex_arabic:
        logger.error(f"Error in process_arabic_text (reshape only): {ex_arabic}. Text was: {text_to_process}")
        return text_str

# For Matplotlib chart text (titles, labels, etc.)
def process_arabic_text_for_matplotlib(text_to_process):
    if text_to_process is None:
        return ""
    text_str = str(text_to_process) # Ensure it's a string
    is_arabic = any("\u0600" <= char_val <= "\u06FF" for char_val in text_str)
    if not is_arabic:
        return text_str
    try:
        reshaped_text = arabic_reshaper.reshape(text_str)
        bidi_text = get_display(reshaped_text) # Apply BIDI for Matplotlib
        return bidi_text
    except Exception as ex_arabic:
        logger.error(f"Error in process_arabic_text_for_matplotlib (reshape and bidi): {ex_arabic}. Text was: {text_to_process}")
        return text_str

TIME_FILTERS_DISPLAY_RAW = {
    "today": "اليوم",
    "last_7_days": "آخر 7 أيام",
    "last_30_days": "آخر 30 يومًا",
    "all_time": "كل الوقت"
}

def get_processed_time_filter_display(time_filter_key: str) -> str:
    raw_text = TIME_FILTERS_DISPLAY_RAW.get(time_filter_key, time_filter_key) 
    return process_arabic_text(raw_text) # Use general processing for button text

def generate_usage_overview_chart(active_users: int, total_quizzes_in_period: int, time_filter: str) -> str | None:
    if active_users == 0 and total_quizzes_in_period == 0:
        return None
    fig, ax = plt.subplots(figsize=(8, 6))
    # Use process_arabic_text_for_matplotlib for chart elements
    categories = [process_arabic_text_for_matplotlib("المستخدمون النشطون"), process_arabic_text_for_matplotlib("الاختبارات المجراة")]
    counts = [active_users, total_quizzes_in_period]
    colors = ["#1f77b4", "#ff7f0e"]
    bars = ax.bar(categories, counts, color=colors, width=0.5)
    ax.set_ylabel(process_arabic_text_for_matplotlib("العدد"))
    
    time_filter_display_val_for_chart = process_arabic_text_for_matplotlib(TIME_FILTERS_DISPLAY_RAW.get(time_filter, time_filter))
    title_chart_base = process_arabic_text_for_matplotlib("نظرة عامة على الاستخدام")
    title_chart = f"{title_chart_base} ({time_filter_display_val_for_chart})"
    ax.set_title(title_chart, pad=20)
    
    ax.tick_params(axis="x", labelsize=12)
    ax.tick_params(axis="y", labelsize=12)
    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 0.02 * max(counts) if max(counts) > 0 else 0.5, 
                process_arabic_text_for_matplotlib(str(int(yval))), ha="center", va="bottom", fontsize=11)
    chart_filename = f"usage_overview_{time_filter}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.png"
    chart_path = os.path.join(CHARTS_DIR, chart_filename)
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        logger.info(f"Generated usage overview chart: {chart_path}")
        return chart_path
    except Exception as e:
        logger.error(f"Error generating usage overview chart for time_filter {time_filter}: {e}", exc_info=True)
        plt.close(fig)
        return None

async def get_usage_overview_display(time_filter: str) -> tuple[str, str | None]:
    total_users_overall = DB_MANAGER.get_total_users_count()
    active_users_period = DB_MANAGER.get_active_users_count(time_filter=time_filter)
    total_quizzes_period = DB_MANAGER.get_total_quizzes_count(time_filter=time_filter)
    avg_quizzes_active_user_period = DB_MANAGER.get_average_quizzes_per_active_user(time_filter=time_filter)
    
    # For Telegram message text, use general processing
    time_filter_display_val = get_processed_time_filter_display(time_filter)
    str_title_overview = process_arabic_text("📊 *نظرة عامة على الاستخدام*")
    str_total_users_label = process_arabic_text("- إجمالي المستخدمين (الكلي):")
    str_active_users_label = process_arabic_text("- المستخدمون النشطون")
    str_total_quizzes_label = process_arabic_text("- إجمالي الاختبارات")
    str_avg_quizzes_label = process_arabic_text("- متوسط الاختبارات لكل مستخدم نشط")
    
    line1 = f"{str_title_overview} ({time_filter_display_val}):\n"
    line2 = f"{str_total_users_label} {process_arabic_text(str(total_users_overall))}\n"
    line3 = f"{str_active_users_label} ({time_filter_display_val}): {process_arabic_text(str(active_users_period))}\n"
    line4 = f"{str_total_quizzes_label} ({time_filter_display_val}): {process_arabic_text(str(total_quizzes_period))}\n"
    avg_display_val = "{:.2f}".format(avg_quizzes_active_user_period if avg_quizzes_active_user_period is not None else 0.0)
    line5 = f"{str_avg_quizzes_label} ({time_filter_display_val}): {process_arabic_text(avg_display_val)}"
    
    text_response = line1 + line2 + line3 + line4 + line5
    chart_path = None
    if active_users_period > 0 or total_quizzes_period > 0:
        chart_path = generate_usage_overview_chart(active_users_period, total_quizzes_period, time_filter)
    return text_response, chart_path

def generate_quiz_performance_chart(score_distribution: dict, time_filter: str) -> str | None:
    if not score_distribution or not any(score_distribution.values()):
        logger.info(f"No score distribution data to generate chart for time_filter {time_filter}.")
        return None
    
    # Use process_arabic_text_for_matplotlib for chart elements
    labels = [process_arabic_text_for_matplotlib(label) for label in score_distribution.keys()]
    values = list(score_distribution.values())
    fig, ax = plt.subplots(figsize=(10, 7))
    bars = ax.bar(labels, values, color="#2ca02c", width=0.6)
    ax.set_ylabel(process_arabic_text_for_matplotlib("عدد المستخدمين"))
    ax.set_xlabel(process_arabic_text_for_matplotlib("نطاق الدرجات"))
    
    time_filter_display_val_for_chart = process_arabic_text_for_matplotlib(TIME_FILTERS_DISPLAY_RAW.get(time_filter, time_filter))
    title_chart_base = process_arabic_text_for_matplotlib("توزيع درجات الاختبارات")
    title_chart = f"{title_chart_base} ({time_filter_display_val_for_chart})"
    ax.set_title(title_chart, pad=20)
    
    ax.tick_params(axis="x", labelsize=10, rotation=45)
    ax.tick_params(axis="y", labelsize=10)
    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 0.02 * max(values) if max(values) > 0 else 0.5, 
                process_arabic_text_for_matplotlib(str(int(yval))), ha="center", va="bottom", fontsize=9)
    chart_filename = f"quiz_performance_scores_{time_filter}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.png"
    chart_path = os.path.join(CHARTS_DIR, chart_filename)
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        logger.info(f"Generated quiz performance chart: {chart_path}")
        return chart_path
    except Exception as e:
        logger.error(f"Error generating quiz performance chart for time_filter {time_filter}: {e}", exc_info=True)
        plt.close(fig)
        return None

async def get_quiz_performance_display(time_filter: str) -> tuple[str, str | None]:
    logger.info(f"[AdminDashboardDisplayV16] get_quiz_performance_display called for {time_filter}")
    # For Telegram message text, use general processing
    time_filter_display_val = get_processed_time_filter_display(time_filter)
    avg_correct_percentage = DB_MANAGER.get_overall_average_score(time_filter=time_filter)
    score_distribution_data = DB_MANAGER.get_score_distribution(time_filter=time_filter)
    
    title_str = process_arabic_text("📈 *أداء الاختبارات*")
    dist_title_str = process_arabic_text("📊 *توزيع الدرجات:*")
    no_data_str = process_arabic_text("لا توجد بيانات كافية لعرض توزيع الدرجات.")
    users_str = process_arabic_text("مستخدمين")
    avg_correct_label = process_arabic_text("- متوسط نسبة الإجابات الصحيحة:")
    
    text_response_parts = []
    text_response_parts.append(f"{title_str} ({time_filter_display_val}):")
    avg_perc_display = "{:.2f}%".format(float(avg_correct_percentage if avg_correct_percentage is not None else 0.0))
    text_response_parts.append(f"{avg_correct_label} {process_arabic_text(avg_perc_display)}")
    
    if score_distribution_data and isinstance(score_distribution_data, dict) and any(score_distribution_data.values()):
        text_response_parts.append(f"\n{dist_title_str}")
        for score_range, count in score_distribution_data.items():
            processed_score_range = process_arabic_text(str(score_range)) 
            count_display = process_arabic_text(str(count))
            text_response_parts.append(f"  - {processed_score_range}: {count_display} {users_str}")
    else:
        text_response_parts.append(f"\n{dist_title_str} {no_data_str}")
        
    text_response = "\n".join(text_response_parts)
    chart_path = None
    if score_distribution_data and isinstance(score_distribution_data, dict) and any(score_distribution_data.values()):
        chart_path = generate_quiz_performance_chart(score_distribution_data, time_filter)
    else:
        logger.info("Skipping quiz performance chart generation due to no/empty or invalid score distribution data.")
    return text_response, chart_path

def generate_user_interaction_chart(interaction_data: dict, time_filter: str) -> str | None:
    if not interaction_data or not any(str(val) for val in interaction_data.values()):
        logger.info(f"No user interaction data to generate chart for time_filter {time_filter}.")
        return None

    # Use process_arabic_text_for_matplotlib for chart elements
    labels = [process_arabic_text_for_matplotlib(label) for label in interaction_data.keys()]
    values = []
    for value in interaction_data.values():
        try:
            values.append(float(value))
        except (ValueError, TypeError):
            values.append(0.0)
            logger.warning(f"Could not convert interaction data value to float: {value}", exc_info=True)
            
    fig, ax = plt.subplots(figsize=(8, 6))
    bars = ax.bar(labels, values, color=["#ff7f0e", "#d62728"], width=0.5)
    ax.set_ylabel(process_arabic_text_for_matplotlib("النسبة المئوية (%)"))
    
    time_filter_display_val_for_chart = process_arabic_text_for_matplotlib(TIME_FILTERS_DISPLAY_RAW.get(time_filter, time_filter))
    title_chart_base = process_arabic_text_for_matplotlib("معدلات إكمال الاختبارات")
    title_chart = f"{title_chart_base} ({time_filter_display_val_for_chart})"
    ax.set_title(title_chart, pad=20)
    
    ax.tick_params(axis="x", labelsize=12)
    ax.tick_params(axis="y", labelsize=10)
    ax.set_ylim(0, 100)
    for bar in bars:
        yval = bar.get_height()
        text_val = "{:.1f}%".format(yval)
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 2, process_arabic_text_for_matplotlib(text_val), 
                ha="center", va="bottom", fontsize=10)
    chart_filename = f"user_interaction_completion_{time_filter}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.png"
    chart_path = os.path.join(CHARTS_DIR, chart_filename)
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        logger.info(f"Generated user interaction chart: {chart_path}")
        return chart_path
    except Exception as e:
        logger.error(f"Error generating user interaction chart for time_filter {time_filter}: {e}", exc_info=True)
        plt.close(fig)
        return None

async def get_user_interaction_display(time_filter: str) -> tuple[str, str | None]:
    logger.info(f"[AdminDashboardDisplayV16] get_user_interaction_display called for {time_filter}")
    # For Telegram message text, use general processing
    time_filter_display_val = get_processed_time_filter_display(time_filter)
    avg_completion_time_seconds_data = DB_MANAGER.get_average_quiz_duration(time_filter=time_filter)
    avg_completion_time_seconds = float(avg_completion_time_seconds_data) if avg_completion_time_seconds_data is not None else 0.0
    completion_stats = DB_MANAGER.get_quiz_completion_rate_stats(time_filter=time_filter)
    completion_rate = completion_stats.get("completion_rate", 0.0)
    total_started = completion_stats.get("started_quizzes", 0)
    total_completed = completion_stats.get("completed_quizzes", 0)
    drop_off_rate = 0.0
    if total_started > 0:
        drop_off_rate = ((total_started - total_completed) / total_started) * 100
        
    title_str = process_arabic_text("👥 *تفاعل المستخدمين*")
    avg_time_label = process_arabic_text("- متوسط وقت إكمال الاختبار:")
    seconds_str = process_arabic_text("ثانية")
    total_started_label = process_arabic_text("- إجمالي الاختبارات التي بدأت:")
    total_completed_label = process_arabic_text("- إجمالي الاختبارات المكتملة:")
    completion_rate_label = process_arabic_text("- معدل إكمال الاختبارات:")
    drop_off_rate_label = process_arabic_text("- معدل التسرب من الاختبارات:")
    
    text_response_parts = []
    text_response_parts.append(f"{title_str} ({time_filter_display_val}):")
    avg_time_display = "{:.2f}".format(avg_completion_time_seconds)
    text_response_parts.append(f"{avg_time_label} {process_arabic_text(avg_time_display)} {seconds_str}")
    text_response_parts.append(f"{total_started_label} {process_arabic_text(str(total_started))}")
    text_response_parts.append(f"{total_completed_label} {process_arabic_text(str(total_completed))}")
    comp_rate_display = "{:.2f}%".format(float(completion_rate))
    text_response_parts.append(f"{completion_rate_label} {process_arabic_text(comp_rate_display)}")
    drop_rate_display = "{:.2f}%".format(float(drop_off_rate))
    text_response_parts.append(f"{drop_off_rate_label} {process_arabic_text(drop_rate_display)}")
    
    text_response = "\n".join(text_response_parts)
    chart_data = {}
    if total_started > 0: 
        chart_data = {
            # Keys for chart labels should be raw Arabic, processed by matplotlib func
            "معدل الإكمال": completion_rate,
            "معدل التسرب": drop_off_rate
        }
        
    chart_path = None
    if chart_data:
        chart_path = generate_user_interaction_chart(chart_data, time_filter)
    return text_response, chart_path

def generate_question_stats_charts(question_stats: list, time_filter: str) -> list[str]:
    if not question_stats:
        logger.info(f"No question stats data to generate charts for time_filter {time_filter}.")
        return []

    chart_paths = []
    # Correctness chart (Top N most/least correct)
    # For simplicity, let's just chart correctness for all questions if not too many, or top/bottom N
    # This example will chart all for now if less than, say, 15 questions.
    
    # Sort by correctness for a more meaningful chart if needed
    # sorted_by_correctness = sorted(question_stats, key=lambda x: x.get("correct_percentage", 0), reverse=True)
    # For this example, we'll take them as they come or a slice.
    # questions_to_chart = sorted_by_correctness[:10] # Example: Top 10

    # Chart 1: Correctness Percentage
    q_texts_correctness = []
    correct_percentages = []
    for stat in question_stats:
        q_text_short = (str(stat.get("question_text", "سؤال غير معروف"))[:30] + "...") if len(str(stat.get("question_text", "سؤال غير معروف"))) > 30 else str(stat.get("question_text", "سؤال غير معروف"))
        q_texts_correctness.append(process_arabic_text_for_matplotlib(q_text_short))
        correct_percentages.append(stat.get("correct_percentage", 0.0))

    if q_texts_correctness:
        fig1, ax1 = plt.subplots(figsize=(12, 8))
        bars1 = ax1.barh(q_texts_correctness, correct_percentages, color="#9467bd")
        ax1.set_xlabel(process_arabic_text_for_matplotlib("نسبة الإجابة الصحيحة (%)"))
        ax1.set_title(process_arabic_text_for_matplotlib(f"نسبة الإجابات الصحيحة للأسئلة ({process_arabic_text_for_matplotlib(TIME_FILTERS_DISPLAY_RAW.get(time_filter, time_filter))})"), pad=20)
        ax1.set_xlim(0, 100)
        for i, bar in enumerate(bars1):
            width = bar.get_width()
            ax1.text(width + 1, bar.get_y() + bar.get_height()/2.0, 
                     process_arabic_text_for_matplotlib(f"{correct_percentages[i]:.1f}%"), 
                     va="center", ha="left", fontsize=9)
        plt.tight_layout()
        chart1_filename = f"question_correctness_{time_filter}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.png"
        chart1_path = os.path.join(CHARTS_DIR, chart1_filename)
        try:
            plt.savefig(chart1_path)
            chart_paths.append(chart1_path)
            logger.info(f"Generated question correctness chart: {chart1_path}")
        except Exception as e:
            logger.error(f"Error generating question correctness chart: {e}", exc_info=True)
        plt.close(fig1)

    # Chart 2: Average time spent
    q_texts_time = []
    avg_times = []
    for stat in question_stats:
        q_text_short = (str(stat.get("question_text", "سؤال غير معروف"))[:30] + "...") if len(str(stat.get("question_text", "سؤال غير معروف"))) > 30 else str(stat.get("question_text", "سؤال غير معروف"))
        q_texts_time.append(process_arabic_text_for_matplotlib(q_text_short))
        avg_times.append(stat.get("avg_time_seconds", 0.0))
    
    if q_texts_time and any(t > 0 for t in avg_times): # Only plot if there's actual time data
        fig2, ax2 = plt.subplots(figsize=(12, 8))
        bars2 = ax2.barh(q_texts_time, avg_times, color="#8c564b")
        ax2.set_xlabel(process_arabic_text_for_matplotlib("متوسط الوقت المستغرق (ثواني)"))
        ax2.set_title(process_arabic_text_for_matplotlib(f"متوسط الوقت المستغرق لكل سؤال ({process_arabic_text_for_matplotlib(TIME_FILTERS_DISPLAY_RAW.get(time_filter, time_filter))})"), pad=20)
        for i, bar in enumerate(bars2):
            width = bar.get_width()
            ax2.text(width + 0.5, bar.get_y() + bar.get_height()/2.0, 
                     process_arabic_text_for_matplotlib(f"{avg_times[i]:.1f} ث"), 
                     va="center", ha="left", fontsize=9)
        plt.tight_layout()
        chart2_filename = f"question_avg_time_{time_filter}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.png"
        chart2_path = os.path.join(CHARTS_DIR, chart2_filename)
        try:
            plt.savefig(chart2_path)
            chart_paths.append(chart2_path)
            logger.info(f"Generated question average time chart: {chart2_path}")
        except Exception as e:
            logger.error(f"Error generating question average time chart: {e}", exc_info=True)
        plt.close(fig2)

    return chart_paths

async def get_question_stats_display(time_filter: str) -> tuple[str, list[str]]:
    logger.info(f"[AdminDashboardDisplayV16] get_question_stats_display called for {time_filter}")
    question_stats_data = DB_MANAGER.get_detailed_question_stats(time_filter=time_filter)
    
    # For Telegram message text, use general processing
    time_filter_display_val = get_processed_time_filter_display(time_filter)
    title_str = process_arabic_text("❓ *إحصائيات الأسئلة*")
    no_data_str = process_arabic_text("لا توجد بيانات أسئلة مفصلة لهذه الفترة.")
    question_label = process_arabic_text("السؤال:")
    appeared_label = process_arabic_text("مرات الظهور:")
    correct_perc_label = process_arabic_text("نسبة الإجابة الصحيحة:")
    avg_time_label = process_arabic_text("متوسط الوقت (ثانية):")

    text_response_parts = [f"{title_str} ({time_filter_display_val}):"]
    if not question_stats_data:
        text_response_parts.append(no_data_str)
    else:
        for i, stat in enumerate(question_stats_data[:10]): # Display top 10 in text for brevity
            q_text = process_arabic_text(str(stat.get("question_text", "غير معروف")))
            appeared = process_arabic_text(str(stat.get("appeared_count", 0)))
            correct_p = "{:.1f}%".format(stat.get("correct_percentage", 0.0))
            avg_t = "{:.1f}".format(stat.get("avg_time_seconds", 0.0))
            
            text_response_parts.append(f"\n{process_arabic_text(str(i+1))}. {question_label} {q_text}")
            text_response_parts.append(f"   {appeared_label} {appeared}")
            text_response_parts.append(f"   {correct_perc_label} {process_arabic_text(correct_p)}")
            text_response_parts.append(f"   {avg_time_label} {process_arabic_text(avg_t)}")
        if len(question_stats_data) > 10:
            text_response_parts.append(process_arabic_text("\n... وغيرهم (الرسوم البيانية قد تحتوي على المزيد)."))
            
    text_response = "\n".join(text_response_parts)
    chart_paths = []
    if question_stats_data:
        chart_paths = generate_question_stats_charts(question_stats_data, time_filter)
    return text_response, chart_paths

logger.info("[AdminDashboardDisplayV16] Module loaded with separate Matplotlib Arabic processing.")

