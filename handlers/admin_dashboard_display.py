"""Module for generating display content (text and charts) for the Admin Dashboard.

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
    logger.warning(f"Font setup issue: {e}. Using Matplotlib default sans-serif. Arabic text in charts might not render correctly.")
    plt.rcParams["font.family"] = "sans-serif"

plt.rcParams["axes.unicode_minus"] = False

import arabic_reshaper
from bidi.algorithm import get_display

from database.manager import DB_MANAGER

CHARTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_data", "charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

def process_arabic_text(text_to_process):
    if text_to_process is None:
        return ""
    text_str = str(text_to_process) # Ensure it's a string
    # Check if the string contains any Arabic characters
    is_arabic = any("\u0600" <= char_val <= "\u06FF" for char_val in text_str)
    if not is_arabic:
        return text_str # Return original if no Arabic characters
    try:
        reshaped_text = arabic_reshaper.reshape(text_str)
        bidi_text = get_display(reshaped_text)
        return bidi_text
    except Exception as ex_arabic:
        logger.error(f"Error processing Arabic text with reshaper/bidi: {ex_arabic}. Text was: {text_to_process}")
        return text_str # Return original on error

# TIME_FILTERS_DISPLAY now holds RAW Arabic strings.
# Processing will happen where these are used.
TIME_FILTERS_DISPLAY_RAW = {
    "today": "اليوم",
    "last_7_days": "آخر 7 أيام",
    "last_30_days": "آخر 30 يومًا",
    "all_time": "كل الوقت"
}

def get_processed_time_filter_display(time_filter_key: str) -> str:
    raw_text = TIME_FILTERS_DISPLAY_RAW.get(time_filter_key, time_filter_key) # Fallback to key itself if not found
    return process_arabic_text(raw_text)

def generate_usage_overview_chart(active_users: int, total_quizzes_in_period: int, time_filter: str) -> str | None:
    if active_users == 0 and total_quizzes_in_period == 0:
        return None
    fig, ax = plt.subplots(figsize=(8, 6))
    categories = [process_arabic_text("المستخدمون النشطون"), process_arabic_text("الاختبارات المجراة")]
    counts = [active_users, total_quizzes_in_period]
    colors = ["#1f77b4", "#ff7f0e"]
    bars = ax.bar(categories, counts, color=colors, width=0.5)
    ax.set_ylabel(process_arabic_text("العدد"))
    
    time_filter_display_val = get_processed_time_filter_display(time_filter)
    title_chart_base = process_arabic_text("نظرة عامة على الاستخدام")
    title_chart = f"{title_chart_base} ({time_filter_display_val})"
    ax.set_title(title_chart, pad=20)
    
    ax.tick_params(axis="x", labelsize=12)
    ax.tick_params(axis="y", labelsize=12)
    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 0.02 * max(counts) if max(counts) > 0 else 0.5, 
                process_arabic_text(str(int(yval))), ha="center", va="bottom", fontsize=11)
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
    
    labels = [process_arabic_text(label) for label in score_distribution.keys()]
    values = list(score_distribution.values())
    fig, ax = plt.subplots(figsize=(10, 7))
    bars = ax.bar(labels, values, color="#2ca02c", width=0.6)
    ax.set_ylabel(process_arabic_text("عدد المستخدمين"))
    ax.set_xlabel(process_arabic_text("نطاق الدرجات"))
    
    time_filter_display_val = get_processed_time_filter_display(time_filter)
    title_chart_base = process_arabic_text("توزيع درجات الاختبارات")
    title_chart = f"{title_chart_base} ({time_filter_display_val})"
    ax.set_title(title_chart, pad=20)
    
    ax.tick_params(axis="x", labelsize=10, rotation=45, ha="right")
    ax.tick_params(axis="y", labelsize=10)
    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 0.02 * max(values) if max(values) > 0 else 0.5, 
                process_arabic_text(str(int(yval))), ha="center", va="bottom", fontsize=9)
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
    logger.info(f"[AdminDashboardDisplayV14] get_quiz_performance_display called for {time_filter}")
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
            # score_range is already processed if it comes from keys of score_ranges in manager.py and those are Arabic
            # Assuming score_range from DB_MANAGER.get_score_distribution is raw, needs processing if Arabic
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
    if not interaction_data or not any(str(val) for val in interaction_data.values()): # Check if any value is non-empty string after str conversion
        logger.info(f"No user interaction data to generate chart for time_filter {time_filter}.")
        return None

    # Keys of interaction_data are expected to be raw Arabic needing processing
    labels = [process_arabic_text(label) for label in interaction_data.keys()]
    values = []
    for value in interaction_data.values():
        try:
            values.append(float(value))
        except (ValueError, TypeError):
            values.append(0.0)
            logger.warning(f"Could not convert interaction data value to float: {value}", exc_info=True)
            
    fig, ax = plt.subplots(figsize=(8, 6))
    bars = ax.bar(labels, values, color=["#ff7f0e", "#d62728"], width=0.5)
    ax.set_ylabel(process_arabic_text("النسبة المئوية (%)"))
    
    time_filter_display_val = get_processed_time_filter_display(time_filter)
    title_chart_base = process_arabic_text("معدلات إكمال الاختبارات")
    title_chart = f"{title_chart_base} ({time_filter_display_val})"
    ax.set_title(title_chart, pad=20)
    
    ax.tick_params(axis="x", labelsize=12)
    ax.tick_params(axis="y", labelsize=10)
    ax.set_ylim(0, 100)
    for bar in bars:
        yval = bar.get_height()
        text_val = "{:.1f}%".format(yval)
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 2, process_arabic_text(text_val), 
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
    logger.info(f"[AdminDashboardDisplayV14] get_user_interaction_display called for {time_filter}")
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
        # Keys for chart_data should be raw Arabic, they will be processed in generate_user_interaction_chart
        chart_data = {
            "معدل الإكمال": completion_rate,
            "معدل التسرب": drop_off_rate
        }
        
    chart_path = None
    if chart_data:
        # Values are already float, no need for chart_data_float conversion here
        chart_path = generate_user_interaction_chart(chart_data, time_filter)
    else:
        logger.info("Skipping user interaction chart generation due to no interaction data or total_started is zero.")
    return text_response, chart_path

def generate_question_difficulty_chart(difficulty_data_list: list, time_filter: str, chart_type: str) -> str | None:
    if not difficulty_data_list:
        logger.info(f"No {chart_type} question data to generate chart for time_filter {time_filter}.")
        return None
        
    questions_to_chart = difficulty_data_list[:5]
    # q.get("question_text") is raw, needs processing for labels
    labels = [process_arabic_text(q.get("question_text", "N/A")[:30] + ("..." if len(q.get("question_text", "N/A")) > 30 else "")) for q in questions_to_chart]
    values = [q.get("correct_percentage", 0.0) for q in questions_to_chart]
    fig, ax = plt.subplots(figsize=(12, 8))
    bar_color = "#9467bd" if chart_type == "hardest" else "#8c564b"
    bars = ax.bar(labels, values, color=bar_color, width=0.5)
    ax.set_ylabel(process_arabic_text("نسبة الإجابة الصحيحة (%)"))
    
    time_filter_display_val = get_processed_time_filter_display(time_filter)
    chart_title_type_str_raw = "الأصعب" if chart_type == "hardest" else "الأسهل"
    chart_title_type_str = process_arabic_text(chart_title_type_str_raw)
    title_chart_base = process_arabic_text("الأسئلة الـ")
    title_chart = f"{title_chart_base}{process_arabic_text(str(len(questions_to_chart)))} {chart_title_type_str} ({time_filter_display_val})"
    ax.set_title(title_chart, pad=20)
    
    ax.tick_params(axis="x", labelsize=9, rotation=35, ha="right")
    ax.tick_params(axis="y", labelsize=10)
    ax.set_ylim(0, 100)
    for bar in bars:
        yval = bar.get_height()
        text_val = "{:.1f}%".format(yval)
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 1.5, process_arabic_text(text_val), 
                ha="center", va="bottom", fontsize=9)
    chart_filename = f"question_difficulty_{chart_type}_{time_filter}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.png"
    chart_path = os.path.join(CHARTS_DIR, chart_filename)
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        logger.info(f"Generated question difficulty ({chart_type}) chart: {chart_path}")
        return chart_path
    except Exception as e:
        logger.error(f"Error generating question difficulty ({chart_type}) chart for time_filter {time_filter}: {e}", exc_info=True)
        plt.close(fig)
        return None

async def get_question_stats_display(time_filter: str) -> tuple[str, list[str] | None]:
    logger.info(f"[AdminDashboardDisplayV14] get_question_stats_display called for {time_filter}")
    time_filter_display_val = get_processed_time_filter_display(time_filter)
    question_difficulty_list = DB_MANAGER.get_question_difficulty_stats(time_filter=time_filter)
    
    title_str = process_arabic_text("❓ *إحصائيات الأسئلة*")
    hardest_title_str = process_arabic_text("📉 *أصعب 5 أسئلة (حسب أقل نسبة إجابات صحيحة):*")
    easiest_title_str = process_arabic_text("📈 *أسهل 5 أسئلة (حسب أعلى نسبة إجابات صحيحة):*")
    no_data_hardest_str = process_arabic_text("📉 *أصعب الأسئلة:* لا توجد بيانات كافية.")
    no_data_easiest_str = process_arabic_text("📈 *أسهل الأسئلة:* لا توجد بيانات كافية.")
    correctness_str = process_arabic_text("صحة:")
    attempts_str = process_arabic_text("محاولات:")
    not_available_str = process_arabic_text("غير متوفر") # This is already processed if it's displayed directly
    
    text_response_parts = [f"{title_str} ({time_filter_display_val}):"]
    hardest_questions = [q for q in question_difficulty_list if q.get("correct_percentage") is not None][:5]
    easiest_questions = sorted([q for q in question_difficulty_list if q.get("correct_percentage") is not None], key=lambda x: x["correct_percentage"], reverse=True)[:5]
    
    if hardest_questions:
        text_response_parts.append(f"\n{hardest_title_str}")
        for i, q in enumerate(hardest_questions):
            q_text_original = q.get("question_text", "N/A") # Raw text
            attempts_val = q.get("total_attempts", not_available_str) # attempts_val could be a number or processed "غير متوفر"
            
            processed_q_text = process_arabic_text(q_text_original[:40] + ("..." if len(q_text_original) > 40 else ""))
            correct_perc_display = "{:.2f}%".format(q.get("correct_percentage", 0.0))
            
            # Process numbers if they are part of Arabic string, or ensure they are displayed correctly as is.
            # Here, they are concatenated, so process Arabic parts and numbers separately if needed.
            text_response_parts.append(f"  {process_arabic_text(str(i+1))}. \"{processed_q_text}\" ({correctness_str} {process_arabic_text(correct_perc_display)}, {attempts_str} {process_arabic_text(str(attempts_val))})")
    else:
        text_response_parts.append(f"\n{no_data_hardest_str}")
        
    if easiest_questions:
        text_response_parts.append(f"\n{easiest_title_str}")
        for i, q in enumerate(easiest_questions):
            q_text_original = q.get("question_text", "N/A")
            attempts_val = q.get("total_attempts", not_available_str)
            processed_q_text = process_arabic_text(q_text_original[:40] + ("..." if len(q_text_original) > 40 else ""))
            correct_perc_display = "{:.2f}%".format(q.get("correct_percentage", 0.0))
            text_response_parts.append(f"  {process_arabic_text(str(i+1))}. \"{processed_q_text}\" ({correctness_str} {process_arabic_text(correct_perc_display)}, {attempts_str} {process_arabic_text(str(attempts_val))})")
    else:
        text_response_parts.append(f"\n{no_data_easiest_str}")
        
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

logger.info("[AdminDashboardDisplayV14] Module loaded, Arabic text processing centralized.")

