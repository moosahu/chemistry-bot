"""Module for generating display content (text and charts) for the Admin Dashboard.

Version 5: Ensures ALL user-facing Arabic strings, static or dynamic, in text responses
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

# Configure Matplotlib for Arabic text
try:
    # Prioritize Amiri font if available, as it's a good open-source Arabic font
    font_path_amiri = "/usr/share/fonts/truetype/amiri/Amiri-Regular.ttf" # Common path for Amiri
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
        # Fallback if specific fonts are not found
        logger.warning("Amiri and DejaVu Sans fonts not found. Using Matplotlib default sans-serif. Arabic text in charts might not render correctly.")
        plt.rcParams["font.family"] = "sans-serif"
except Exception as e:
    logger.warning(f"Font setup issue: {e}. Using Matplotlib default sans-serif. Arabic text in charts might not render correctly.")
    plt.rcParams["font.family"] = "sans-serif"

plt.rcParams["axes.unicode_minus"] = False # Ensure minus sign is displayed correctly

import arabic_reshaper
from bidi.algorithm import get_display

from database.manager import DB_MANAGER
from config import logger

CHARTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_data", "charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

def process_arabic_text(text_to_process):
    if text_to_process is None:
        return ""
    text_str = str(text_to_process)
    # Check if the string contains any Arabic characters
    is_arabic = any("\u0600" <= char_val <= "\u06FF" for char_val in text_str)
    if not is_arabic:
        return text_str # Return as is if no Arabic characters
    try:
        reshaped_text = arabic_reshaper.reshape(text_str)
        bidi_text = get_display(reshaped_text)
        return bidi_text
    except Exception as ex_arabic:
        logger.error(f"Error processing Arabic text with reshaper/bidi: {ex_arabic}. Text was: {text_to_process}")
        return text_str # Return original string in case of error

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
    time_filter_display = TIME_FILTERS_DISPLAY.get(time_filter, process_arabic_text(time_filter))
    ax.set_title(process_arabic_text(f"نظرة عامة على الاستخدام ({time_filter_display})"), pad=20)
    ax.tick_params(axis="x", labelsize=12)
    ax.tick_params(axis="y", labelsize=12)
    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 0.02 * max(counts) if max(counts) > 0 else 0.5, int(yval), ha="center", va="bottom", fontsize=11)
    chart_filename = f"usage_overview_{time_filter}_{datetime.now().strftime("%Y%m%d%H%M%S%f")}.png"
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
    time_filter_display = TIME_FILTERS_DISPLAY.get(time_filter, process_arabic_text(time_filter))
    
    text_response = (
        f"{process_arabic_text('📊 *نظرة عامة على الاستخدام*')} ({time_filter_display}):\n"
        f"{process_arabic_text('- إجمالي المستخدمين (الكلي):')} {total_users_overall}\n"
        f"{process_arabic_text('- المستخدمون النشطون')} ({time_filter_display}): {active_users_period}\n"
        f"{process_arabic_text('- إجمالي الاختبارات')} ({time_filter_display}): {total_quizzes_period}\n"
        f"{process_arabic_text('- متوسط الاختبارات لكل مستخدم نشط')} ({time_filter_display}): {avg_quizzes_active_user_period:.2f}"
    )
    chart_path = None
    if active_users_period > 0 or total_quizzes_period > 0:
        chart_path = generate_usage_overview_chart(active_users_period, total_quizzes_period, time_filter)
    return text_response, chart_path # text_response is already processed internally

def generate_quiz_performance_chart(score_distribution: dict, time_filter: str) -> str | None:
    if not score_distribution or not any(score_distribution.values()):
        logger.info(f"No score distribution data to generate chart for time_filter {time_filter}.")
        return None
    labels = [process_arabic_text(label) for label in score_distribution.keys()]
    values = list(score_distribution.values())
    fig, ax = plt.subplots(figsize=(10, 7)) # Increased height for rotated labels
    bars = ax.bar(labels, values, color="#2ca02c", width=0.6)
    ax.set_ylabel(process_arabic_text("عدد المستخدمين"))
    ax.set_xlabel(process_arabic_text("نطاق الدرجات"))
    time_filter_display = TIME_FILTERS_DISPLAY.get(time_filter, process_arabic_text(time_filter))
    ax.set_title(process_arabic_text(f"توزيع درجات الاختبارات ({time_filter_display})"), pad=20)
    ax.tick_params(axis="x", labelsize=10, rotation=45, ha="right")
    ax.tick_params(axis="y", labelsize=10)
    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 0.02 * max(values) if max(values) > 0 else 0.5, int(yval), ha="center", va="bottom", fontsize=9)
    chart_filename = f"quiz_performance_scores_{time_filter}_{datetime.now().strftime("%Y%m%d%H%M%S%f")}.png"
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
    logger.info(f"[AdminDashboardDisplayV5] get_quiz_performance_display called for {time_filter}")
    time_filter_display = TIME_FILTERS_DISPLAY.get(time_filter, process_arabic_text(time_filter))
    avg_correct_percentage = DB_MANAGER.get_overall_average_score(time_filter=time_filter)
    score_distribution_data = DB_MANAGER.get_score_distribution(time_filter=time_filter)
    text_response_parts = [f"{process_arabic_text('📈 *أداء الاختبارات*')} ({time_filter_display}):"]
    text_response_parts.append(f"{process_arabic_text('- متوسط نسبة الإجابات الصحيحة:')} {float(avg_correct_percentage):.2f}%")
    if score_distribution_data and isinstance(score_distribution_data, dict) and any(score_distribution_data.values()):
        text_response_parts.append(f"\n{process_arabic_text('📊 *توزيع الدرجات:*')}")
        for score_range, count in score_distribution_data.items():
            text_response_parts.append(f"  - {process_arabic_text(score_range)}: {count} {process_arabic_text('مستخدمين')}")
    else:
        text_response_parts.append(f"\n{process_arabic_text('📊 *توزيع الدرجات:*')} {process_arabic_text('لا توجد بيانات كافية لعرض توزيع الدرجات.')}")
    text_response = "\n".join(text_response_parts)
    chart_path = None
    if score_distribution_data and isinstance(score_distribution_data, dict) and any(score_distribution_data.values()):
        chart_path = generate_quiz_performance_chart(score_distribution_data, time_filter)
    else:
        logger.info("Skipping quiz performance chart generation due to no/empty or invalid score distribution data.")
    return text_response, chart_path # text_response is already processed

def generate_user_interaction_chart(interaction_data: dict, time_filter: str) -> str | None:
    if not interaction_data or not any(str(val) for val in interaction_data.values()): # Check if any value is non-empty string after conversion
        logger.info(f"No user interaction data to generate chart for time_filter {time_filter}.")
        return None

    labels = [process_arabic_text(label) for label in interaction_data.keys()]
    # Ensure values are numeric, default to 0 if conversion fails
    values = []
    for value in interaction_data.values():
        try:
            values.append(float(value))
        except (ValueError, TypeError):
            values.append(0.0)
            logger.warning(f"Could not convert interaction data value ", exc_info=True)

    fig, ax = plt.subplots(figsize=(8, 6))
    bars = ax.bar(labels, values, color=["#ff7f0e", "#d62728"], width=0.5) # Orange and Red

    ax.set_ylabel(process_arabic_text("النسبة المئوية (%)"))
    time_filter_display = TIME_FILTERS_DISPLAY.get(time_filter, process_arabic_text(time_filter))
    ax.set_title(process_arabic_text(f"معدلات إكمال الاختبارات ({time_filter_display})"), pad=20)
    ax.tick_params(axis="x", labelsize=12)
    ax.tick_params(axis="y", labelsize=10)
    ax.set_ylim(0, 100) # Percentages are 0-100

    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 2, f"{yval:.1f}%", ha="center", va="bottom", fontsize=10)

    chart_filename = f"user_interaction_completion_{time_filter}_{datetime.now().strftime("%Y%m%d%H%M%S%f")}.png"
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
    logger.info(f"[AdminDashboardDisplayV5] get_user_interaction_display called for {time_filter}")
    time_filter_display = TIME_FILTERS_DISPLAY.get(time_filter, process_arabic_text(time_filter))

    avg_completion_time_seconds_data = DB_MANAGER.get_average_quiz_duration(time_filter=time_filter)
    avg_completion_time_seconds = float(avg_completion_time_seconds_data) if avg_completion_time_seconds_data is not None else 0.0
    completion_stats = DB_MANAGER.get_quiz_completion_rate_stats(time_filter=time_filter)
    
    completion_rate = completion_stats.get("completion_rate", 0.0)
    total_started = completion_stats.get("started_quizzes", 0)
    total_completed = completion_stats.get("completed_quizzes", 0)
    drop_off_rate = 0.0
    if total_started > 0:
        drop_off_rate = ((total_started - total_completed) / total_started) * 100
        
    text_response_parts = [f"{process_arabic_text('👥 *تفاعل المستخدمين*')} ({time_filter_display}):"]
    text_response_parts.append(f"{process_arabic_text('- متوسط وقت إكمال الاختبار:')} {avg_completion_time_seconds:.2f} {process_arabic_text('ثانية')}")
    text_response_parts.append(f"{process_arabic_text('- إجمالي الاختبارات التي بدأت:')} {total_started}")
    text_response_parts.append(f"{process_arabic_text('- إجمالي الاختبارات المكتملة:')} {total_completed}")
    text_response_parts.append(f"{process_arabic_text('- معدل إكمال الاختبارات:')} {float(completion_rate):.2f}%")
    text_response_parts.append(f"{process_arabic_text('- معدل التسرب من الاختبارات:')} {float(drop_off_rate):.2f}%")
    
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

    return text_response, chart_path # text_response is already processed

def generate_question_difficulty_chart(difficulty_data_list: list, time_filter: str, chart_type: str) -> str | None:
    if not difficulty_data_list:
        logger.info(f"No {chart_type} question data to generate chart for time_filter {time_filter}.")
        return None

    questions_to_chart = difficulty_data_list[:5] # Already limited to 5 by DB query in this version
    
    labels = [process_arabic_text(q.get("question_text", "N/A")[:30] + ("..." if len(q.get("question_text", "N/A")) > 30 else "")) for q in questions_to_chart]
    values = [q.get("correct_percentage", 0.0) for q in questions_to_chart]
    
    fig, ax = plt.subplots(figsize=(12, 8)) # Increased height for rotated labels 
    bar_color = "#9467bd" if chart_type == "hardest" else "#8c564b" # Purple for hardest, Brown for easiest
    bars = ax.bar(labels, values, color=bar_color, width=0.5)

    ax.set_ylabel(process_arabic_text("نسبة الإجابة الصحيحة (%)"))
    time_filter_display = TIME_FILTERS_DISPLAY.get(time_filter, process_arabic_text(time_filter))
    chart_title_type = process_arabic_text("الأصعب") if chart_type == "hardest" else process_arabic_text("الأسهل")
    ax.set_title(process_arabic_text(f"الأسئلة الـ{len(questions_to_chart)} {chart_title_type} ({time_filter_display})"), pad=20)
    ax.tick_params(axis="x", labelsize=9, rotation=35, ha="right") # Adjusted rotation
    ax.tick_params(axis="y", labelsize=10)
    ax.set_ylim(0, 100)

    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 1.5, f"{yval:.1f}%", ha="center", va="bottom", fontsize=9)

    chart_filename = f"question_difficulty_{chart_type}_{time_filter}_{datetime.now().strftime("%Y%m%d%H%M%S%f")}.png"
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
    logger.info(f"[AdminDashboardDisplayV5] get_question_stats_display called for {time_filter}")
    time_filter_display = TIME_FILTERS_DISPLAY.get(time_filter, process_arabic_text(time_filter))
    
    # get_question_difficulty_stats now returns a list of dicts directly
    question_difficulty_list = DB_MANAGER.get_question_difficulty_stats(time_filter=time_filter) 

    text_response_parts = [f"{process_arabic_text('❓ *إحصائيات الأسئلة*')} ({time_filter_display}):"]

    # Sort by correct_percentage ascending for hardest, descending for easiest
    # The DB query already sorts by correct_percentage ASC, total_attempts DESC, and limits.
    # We can just take the first 5 for hardest, and if we want easiest, we'd need another query or sort differently.
    # For now, assuming the DB query gives a general list, and we pick hardest/easiest from it.
    # The DB query in manager_v3_fixes.py is already ordered by ASC (hardest first) and limited.

    hardest_questions = sorted([q for q in question_difficulty_list if q.get("correct_percentage") is not None], key=lambda x: x["correct_percentage"])[:5]
    easiest_questions = sorted([q for q in question_difficulty_list if q.get("correct_percentage") is not None], key=lambda x: x["correct_percentage"], reverse=True)[:5]

    if hardest_questions:
        text_response_parts.append(f"\n{process_arabic_text('📉 *أصعب 5 أسئلة (حسب أقل نسبة إجابات صحيحة):*')}")
        for i, q in enumerate(hardest_questions):
            q_text = q.get("question_text", "N/A")
            text_response_parts.append(f"  {i+1}. \"{process_arabic_text(q_text[:40] + ('...' if len(q_text) > 40 else ''))}\" ({process_arabic_text('صحة:')} {q.get('correct_percentage', 0.0):.2f}%, {process_arabic_text('محاولات:')} {q.get('total_attempts', process_arabic_text('غير متوفر'))})")
    else:
        text_response_parts.append(f"\n{process_arabic_text('📉 *أصعب الأسئلة:*')} {process_arabic_text('لا توجد بيانات كافية.')}")

    if easiest_questions:
        text_response_parts.append(f"\n{process_arabic_text('📈 *أسهل 5 أسئلة (حسب أعلى نسبة إجابات صحيحة):*')}")
        for i, q in enumerate(easiest_questions):
            q_text = q.get("question_text", "N/A")
            text_response_parts.append(f"  {i+1}. \"{process_arabic_text(q_text[:40] + ('...' if len(q_text) > 40 else ''))}\" ({process_arabic_text('صحة:')} {q.get('correct_percentage', 0.0):.2f}%, {process_arabic_text('محاولات:')} {q.get('total_attempts', process_arabic_text('غير متوفر'))})")
    else:
        text_response_parts.append(f"\n{process_arabic_text('📈 *أسهل الأسئلة:*')} {process_arabic_text('لا توجد بيانات كافية.')}")

    text_response = "\n".join(text_response_parts)
    
    chart_paths = []
    hardest_chart_path = None
    easiest_chart_path = None

    if hardest_questions:
        # Pass the list of question dicts directly
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

    return text_response, chart_paths # text_response is already processed

logger.info("[AdminDashboardDisplayV5] Module loaded and all Arabic text processing enhanced.")

