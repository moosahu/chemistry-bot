"""Module for generating display content (text and charts) for the Admin Dashboard.

Version 10: Fixes 'logger not defined' error by ensuring logger is imported
from config before its first use, especially in font setup.
Completely removes f-strings and uses basic string concatenation
or .format() to prevent "unmatched parenthesis" errors. 
Ensures ALL user-facing Arabic strings, static or dynamic, in text responses
and chart elements are passed through process_arabic_text.
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
    font_path_amiri = "/usr/share/fonts/truetype/amiri/Amiri-Regular.ttf" 
    font_path_dejavu = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    
    if os.path.exists(font_path_amiri):
        font_manager.fontManager.addfont(font_path_amiri)
        plt.rcParams["font.family"] = "Amiri"
        logger.info("Using Amiri font for Matplotlib charts.")
    elif os.path.exists(font_path_dejavu):
        font_manager.fontManager.addfont(font_path_dejavu)
        plt.rcParams["font.family"] = "DejaVu Sans"
        logger.info("Using DejaVu Sans font for Matplotlib charts.")
    else:
        logger.warning("Amiri and DejaVu Sans fonts not found. Using Matplotlib default sans-serif. Arabic text in charts might not render correctly.")
        plt.rcParams["font.family"] = "sans-serif"
except Exception as e:
    logger.warning("Font setup issue: {}. Using Matplotlib default sans-serif. Arabic text in charts might not render correctly.".format(e))
    plt.rcParams["font.family"] = "sans-serif"

plt.rcParams["axes.unicode_minus"] = False

import arabic_reshaper
from bidi.algorithm import get_display

from database.manager import DB_MANAGER
# logger is already imported from config or defined above

CHARTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_data", "charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

def process_arabic_text(text_to_process):
    if text_to_process is None:
        return ""
    text_str = str(text_to_process)
    is_arabic = any("\u0600" <= char_val <= "\u06FF" for char_val in text_str)
    if not is_arabic:
        return text_str
    try:
        reshaped_text = arabic_reshaper.reshape(text_str)
        bidi_text = get_display(reshaped_text)
        return bidi_text
    except Exception as ex_arabic:
        logger.error("Error processing Arabic text with reshaper/bidi: {}. Text was: {}".format(ex_arabic, text_to_process))
        return text_str

TIME_FILTERS_DISPLAY = {
    "today": process_arabic_text("اليوم"),
    "last_7_days": process_arabic_text("آخر 7 أيام"),
    "last_30_days": process_arabic_text("آخر 30 يومًا"),
    "all_time": process_arabic_text("كل الوقت")
}

def generate_usage_overview_chart(active_users: int, total_quizzes_in_period: int, time_filter: str) -> str | None:
    if active_users == 0 and total_quizzes_in_period == 0:
        return None
    fig, ax = plt.subplots(figsize=(8, 6))
    categories = [process_arabic_text("المستخدمون النشطون"), process_arabic_text("الاختبارات المجراة")]
    counts = [active_users, total_quizzes_in_period]
    colors = ["#1f77b4", "#ff7f0e"]
    bars = ax.bar(categories, counts, color=colors, width=0.5)
    ax.set_ylabel(process_arabic_text("العدد"))
    time_filter_display_val = TIME_FILTERS_DISPLAY.get(time_filter, process_arabic_text(time_filter))
    title_chart = process_arabic_text("نظرة عامة على الاستخدام ({})".format(time_filter_display_val))
    ax.set_title(title_chart, pad=20)
    ax.tick_params(axis="x", labelsize=12)
    ax.tick_params(axis="y", labelsize=12)
    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 0.02 * max(counts) if max(counts) > 0 else 0.5, int(yval), ha="center", va="bottom", fontsize=11)
    chart_filename = "usage_overview_{}_{}.png".format(time_filter, datetime.now().strftime("%Y%m%d%H%M%S%f"))
    chart_path = os.path.join(CHARTS_DIR, chart_filename)
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        logger.info("Generated usage overview chart: {}".format(chart_path))
        return chart_path
    except Exception as e:
        logger.error("Error generating usage overview chart for time_filter {}: {}".format(time_filter, e), exc_info=True)
        plt.close(fig)
        return None

async def get_usage_overview_display(time_filter: str) -> tuple[str, str | None]:
    total_users_overall = DB_MANAGER.get_total_users_count()
    active_users_period = DB_MANAGER.get_active_users_count(time_filter=time_filter)
    total_quizzes_period = DB_MANAGER.get_total_quizzes_count(time_filter=time_filter)
    avg_quizzes_active_user_period = DB_MANAGER.get_average_quizzes_per_active_user(time_filter=time_filter)
    time_filter_display_val = TIME_FILTERS_DISPLAY.get(time_filter, process_arabic_text(time_filter))
    
    str_title_overview = process_arabic_text("📊 *نظرة عامة على الاستخدام*")
    str_total_users_label = process_arabic_text("- إجمالي المستخدمين (الكلي):")
    str_active_users_label = process_arabic_text("- المستخدمون النشطون")
    str_total_quizzes_label = process_arabic_text("- إجمالي الاختبارات")
    str_avg_quizzes_label = process_arabic_text("- متوسط الاختبارات لكل مستخدم نشط")

    line1 = str_title_overview + " (" + time_filter_display_val + "):\n"
    line2 = str_total_users_label + " " + str(total_users_overall) + "\n"
    line3 = str_active_users_label + " (" + time_filter_display_val + "): " + str(active_users_period) + "\n"
    line4 = str_total_quizzes_label + " (" + time_filter_display_val + "): " + str(total_quizzes_period) + "\n"
    line5 = str_avg_quizzes_label + " (" + time_filter_display_val + "): {:.2f}".format(avg_quizzes_active_user_period if avg_quizzes_active_user_period is not None else 0.0)
    text_response = line1 + line2 + line3 + line4 + line5

    chart_path = None
    if active_users_period > 0 or total_quizzes_period > 0:
        chart_path = generate_usage_overview_chart(active_users_period, total_quizzes_period, time_filter)
    return text_response, chart_path

def generate_quiz_performance_chart(score_distribution: dict, time_filter: str) -> str | None:
    if not score_distribution or not any(score_distribution.values()):
        logger.info("No score distribution data to generate chart for time_filter {}.".format(time_filter))
        return None
    labels = [process_arabic_text(label) for label in score_distribution.keys()]
    values = list(score_distribution.values())
    fig, ax = plt.subplots(figsize=(10, 7))
    bars = ax.bar(labels, values, color="#2ca02c", width=0.6)
    ax.set_ylabel(process_arabic_text("عدد المستخدمين"))
    ax.set_xlabel(process_arabic_text("نطاق الدرجات"))
    time_filter_display_val = TIME_FILTERS_DISPLAY.get(time_filter, process_arabic_text(time_filter))
    title_chart = process_arabic_text("توزيع درجات الاختبارات ({})".format(time_filter_display_val))
    ax.set_title(title_chart, pad=20)
    ax.tick_params(axis="x", labelsize=10, rotation=45, ha="right")
    ax.tick_params(axis="y", labelsize=10)
    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 0.02 * max(values) if max(values) > 0 else 0.5, int(yval), ha="center", va="bottom", fontsize=9)
    chart_filename = "quiz_performance_scores_{}_{}.png".format(time_filter, datetime.now().strftime("%Y%m%d%H%M%S%f"))
    chart_path = os.path.join(CHARTS_DIR, chart_filename)
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        logger.info("Generated quiz performance chart: {}".format(chart_path))
        return chart_path
    except Exception as e:
        logger.error("Error generating quiz performance chart for time_filter {}: {}".format(time_filter, e), exc_info=True)
        plt.close(fig)
        return None

async def get_quiz_performance_display(time_filter: str) -> tuple[str, str | None]:
    logger.info("[AdminDashboardDisplayV10] get_quiz_performance_display called for {}".format(time_filter))
    time_filter_display_val = TIME_FILTERS_DISPLAY.get(time_filter, process_arabic_text(time_filter))
    avg_correct_percentage = DB_MANAGER.get_overall_average_score(time_filter=time_filter)
    score_distribution_data = DB_MANAGER.get_score_distribution(time_filter=time_filter)
    
    title_str = process_arabic_text("📈 *أداء الاختبارات*")
    dist_title_str = process_arabic_text("📊 *توزيع الدرجات:*")
    no_data_str = process_arabic_text("لا توجد بيانات كافية لعرض توزيع الدرجات.")
    users_str = process_arabic_text("مستخدمين")
    avg_correct_label = process_arabic_text("- متوسط نسبة الإجابات الصحيحة:")

    text_response_parts = []
    text_response_parts.append(title_str + " (" + time_filter_display_val + "):")
    text_response_parts.append(avg_correct_label + " {:.2f}%".format(float(avg_correct_percentage if avg_correct_percentage is not None else 0.0)))
    if score_distribution_data and isinstance(score_distribution_data, dict) and any(score_distribution_data.values()):
        text_response_parts.append("\n" + dist_title_str)
        for score_range, count in score_distribution_data.items():
            processed_score_range = process_arabic_text(str(score_range))
            text_response_parts.append("  - " + processed_score_range + ": " + str(count) + " " + users_str)
    else:
        text_response_parts.append("\n" + dist_title_str + " " + no_data_str)
    text_response = "\n".join(text_response_parts)
    chart_path = None
    if score_distribution_data and isinstance(score_distribution_data, dict) and any(score_distribution_data.values()):
        chart_path = generate_quiz_performance_chart(score_distribution_data, time_filter)
    else:
        logger.info("Skipping quiz performance chart generation due to no/empty or invalid score distribution data.")
    return text_response, chart_path

def generate_user_interaction_chart(interaction_data: dict, time_filter: str) -> str | None:
    if not interaction_data or not any(str(val) for val in interaction_data.values()):
        logger.info("No user interaction data to generate chart for time_filter {}.".format(time_filter))
        return None

    labels = [process_arabic_text(label) for label in interaction_data.keys()]
    values = []
    for value in interaction_data.values():
        try:
            values.append(float(value))
        except (ValueError, TypeError):
            values.append(0.0)
            logger.warning("Could not convert interaction data value: {}".format(value), exc_info=True)

    fig, ax = plt.subplots(figsize=(8, 6))
    bars = ax.bar(labels, values, color=["#ff7f0e", "#d62728"], width=0.5)

    ax.set_ylabel(process_arabic_text("النسبة المئوية (%)"))
    time_filter_display_val = TIME_FILTERS_DISPLAY.get(time_filter, process_arabic_text(time_filter))
    title_chart = process_arabic_text("معدلات إكمال الاختبارات ({})".format(time_filter_display_val))
    ax.set_title(title_chart, pad=20)
    ax.tick_params(axis="x", labelsize=12)
    ax.tick_params(axis="y", labelsize=10)
    ax.set_ylim(0, 100)

    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 2, "{:.1f}%".format(yval), ha="center", va="bottom", fontsize=10)

    chart_filename = "user_interaction_completion_{}_{}.png".format(time_filter, datetime.now().strftime("%Y%m%d%H%M%S%f"))
    chart_path = os.path.join(CHARTS_DIR, chart_filename)
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        logger.info("Generated user interaction chart: {}".format(chart_path))
        return chart_path
    except Exception as e:
        logger.error("Error generating user interaction chart for time_filter {}: {}".format(time_filter, e), exc_info=True)
        plt.close(fig)
        return None

async def get_user_interaction_display(time_filter: str) -> tuple[str, str | None]:
    logger.info("[AdminDashboardDisplayV10] get_user_interaction_display called for {}".format(time_filter))
    time_filter_display_val = TIME_FILTERS_DISPLAY.get(time_filter, process_arabic_text(time_filter))

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
    text_response_parts.append(title_str + " (" + time_filter_display_val + "):")
    text_response_parts.append(avg_time_label + " {:.2f} ".format(avg_completion_time_seconds) + seconds_str)
    text_response_parts.append(total_started_label + " " + str(total_started))
    text_response_parts.append(total_completed_label + " " + str(total_completed))
    text_response_parts.append(completion_rate_label + " {:.2f}%".format(float(completion_rate)))
    text_response_parts.append(drop_off_rate_label + " {:.2f}%".format(float(drop_off_rate)))
    text_response = "\n".join(text_response_parts)

    chart_data = {}
    if total_started > 0: 
        chart_data = {
            process_arabic_text("معدل الإكمال"): completion_rate,
            process_arabic_text("معدل التسرب"): drop_off_rate
        }
    
    chart_path = None
    if chart_data:
        chart_path = generate_user_interaction_chart(chart_data, time_filter)
    else:
        logger.info("Skipping user interaction chart generation due to no interaction data.")

    return text_response, chart_path

def generate_question_difficulty_chart(difficulty_data_list: list, time_filter: str, chart_type: str) -> str | None:
    if not difficulty_data_list:
        logger.info("No {} question data to generate chart for time_filter {}.".format(chart_type, time_filter))
        return None

    questions_to_chart = difficulty_data_list[:5]
    
    labels = [process_arabic_text(q.get("question_text", "N/A")[:30] + ("..." if len(q.get("question_text", "N/A")) > 30 else "")) for q in questions_to_chart]
    values = [q.get("correct_percentage", 0.0) for q in questions_to_chart]
    
    fig, ax = plt.subplots(figsize=(12, 8))
    bar_color = "#9467bd" if chart_type == "hardest" else "#8c564b"
    bars = ax.bar(labels, values, color=bar_color, width=0.5)

    ax.set_ylabel(process_arabic_text("نسبة الإجابة الصحيحة (%)"))
    time_filter_display_val = TIME_FILTERS_DISPLAY.get(time_filter, process_arabic_text(time_filter))
    chart_title_type_str = process_arabic_text("الأصعب") if chart_type == "hardest" else process_arabic_text("الأسهل")
    title_chart = process_arabic_text("الأسئلة الـ{} {} ({})".format(len(questions_to_chart), chart_title_type_str, time_filter_display_val))
    ax.set_title(title_chart, pad=20)
    ax.tick_params(axis="x", labelsize=9, rotation=35, ha="right")
    ax.tick_params(axis="y", labelsize=10)
    ax.set_ylim(0, 100)

    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 1.5, "{:.1f}%".format(yval), ha="center", va="bottom", fontsize=9)

    chart_filename = "question_difficulty_{}_{}_{}.png".format(chart_type, time_filter, datetime.now().strftime("%Y%m%d%H%M%S%f"))
    chart_path = os.path.join(CHARTS_DIR, chart_filename)
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        logger.info("Generated question difficulty ({}) chart: {}".format(chart_type, chart_path))
        return chart_path
    except Exception as e:
        logger.error("Error generating question difficulty ({}) chart for time_filter {}: {}".format(chart_type, time_filter, e), exc_info=True)
        plt.close(fig)
        return None

async def get_question_stats_display(time_filter: str) -> tuple[str, list[str] | None]:
    logger.info("[AdminDashboardDisplayV10] get_question_stats_display called for {}".format(time_filter))
    time_filter_display_val = TIME_FILTERS_DISPLAY.get(time_filter, process_arabic_text(time_filter))
    
    question_difficulty_list = DB_MANAGER.get_question_difficulty_stats(time_filter=time_filter) 

    title_str = process_arabic_text("❓ *إحصائيات الأسئلة*")
    hardest_title_str = process_arabic_text("📉 *أصعب 5 أسئلة (حسب أقل نسبة إجابات صحيحة):*")
    easiest_title_str = process_arabic_text("📈 *أسهل 5 أسئلة (حسب أعلى نسبة إجابات صحيحة):*")
    no_data_hardest_str = process_arabic_text("📉 *أصعب الأسئلة:* لا توجد بيانات كافية.")
    no_data_easiest_str = process_arabic_text("📈 *أسهل الأسئلة:* لا توجد بيانات كافية.")
    correctness_str = process_arabic_text("صحة:")
    attempts_str = process_arabic_text("محاولات:")
    not_available_str = process_arabic_text("غير متوفر")

    text_response_parts = [title_str + " (" + time_filter_display_val + "):"]

    hardest_questions = sorted([q for q in question_difficulty_list if q.get("correct_percentage") is not None], key=lambda x: x["correct_percentage"])[:5]
    easiest_questions = sorted([q for q in question_difficulty_list if q.get("correct_percentage") is not None], key=lambda x: x["correct_percentage"], reverse=True)[:5]

    if hardest_questions:
        text_response_parts.append("\n" + hardest_title_str)
        for i, q in enumerate(hardest_questions):
            q_text = q.get("question_text", "N/A")
            attempts_val = q.get("total_attempts", not_available_str)
            processed_q_text = process_arabic_text(q_text[:40] + ("..." if len(q_text) > 40 else ""))
            text_response_parts.append("  {}. \"{}\" ({} {:.2f}%, {} {})".format(i+1, processed_q_text, correctness_str, q.get("correct_percentage", 0.0), attempts_str, attempts_val))
    else:
        text_response_parts.append("\n" + no_data_hardest_str)

    if easiest_questions:
        text_response_parts.append("\n" + easiest_title_str)
        for i, q in enumerate(easiest_questions):
            q_text = q.get("question_text", "N/A")
            attempts_val = q.get("total_attempts", not_available_str)
            processed_q_text = process_arabic_text(q_text[:40] + ("..." if len(q_text) > 40 else ""))
            text_response_parts.append("  {}. \"{}\" ({} {:.2f}%, {} {})".format(i+1, processed_q_text, correctness_str, q.get("correct_percentage", 0.0), attempts_str, attempts_val))
    else:
        text_response_parts.append("\n" + no_data_easiest_str)

    text_response = "\n".join(text_response_parts)
    
    chart_paths = []
    hardest_chart_path = None
    easiest_chart_path = None

    if hardest_questions:
        hardest_chart_path = generate_question_difficulty_chart(hardest_questions, time_filter, "hardest")
        if hardest_chart_path:
            chart_paths.append(hardest_chart_path)
    
    if easiest_questions:
        easiest_chart_path = generate_question_difficulty_chart(easiest_questions, time_filter, "easiest")
        if easiest_chart_path:
            chart_paths.append(easiest_chart_path)
            
    if not chart_paths:
        logger.info("Skipping question stats chart generation due to no sufficient data.")
        return text_response, None

    return text_response, chart_paths

logger.info("[AdminDashboardDisplayV10] Module loaded, logger defined, all f-strings replaced.")

