from datetime import datetime
"""Module for generating display content (text and charts) for the Admin Dashboard."""

import logging
import os
import matplotlib
matplotlib.use("Agg")  # Use Agg backend for non-interactive plotting
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np # Added for potential numerical operations in charts

# Configure Matplotlib for Arabic text
try:
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf" 
    if os.path.exists(font_path):
        font_manager.fontManager.addfont(font_path)
        plt.rcParams["font.family"] = "DejaVu Sans"
    else:
        plt.rcParams["font.family"] = ["Amiri", "Arial", "sans-serif"]
except Exception as e:
    logging.warning(f"Font setup issue: {e}. Using Matplotlib defaults.")
    plt.rcParams["font.family"] = "sans-serif"

plt.rcParams["axes.unicode_minus"] = False

import arabic_reshaper
from bidi.algorithm import get_display

from database.manager import DB_MANAGER
from config import logger

CHARTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_data", "charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

def process_arabic_text(text_to_process):
    text_str = str(text_to_process)
    is_arabic = any("\u0600" <= char_val <= "\u06FF" for char_val in text_str)
    if not is_arabic:
        return text_str
    try:
        reshaped_text = arabic_reshaper.reshape(text_str)
        bidi_text = get_display(reshaped_text)
        return bidi_text
    except Exception as ex_arabic:
        logger.error(f"Error processing Arabic text with reshaper/bidi: {ex_arabic}. Text was: {text_to_process}")
        return text_str

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
    colors = ["#1f77b4", "#ff7f0e"]
    bars = ax.bar(categories, counts, color=colors, width=0.5)
    ax.set_ylabel(process_arabic_text("العدد"))
    time_filter_display = TIME_FILTERS_DISPLAY.get(time_filter, time_filter)
    ax.set_title(process_arabic_text(f"نظرة عامة على الاستخدام ({time_filter_display})"), pad=20)
    ax.tick_params(axis="x", labelsize=12)
    ax.tick_params(axis="y", labelsize=12)
    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 0.02 * max(counts) if max(counts) > 0 else 0.5, int(yval), ha="center", va="bottom", fontsize=11)
    chart_filename = f"usage_overview_{time_filter}_{datetime.now().strftime("%Y%m%d%H%M%S")}.png"
    chart_path = os.path.join(CHARTS_DIR, chart_filename)
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        logger.info(f"Generated usage overview chart: {chart_path}")
        return chart_path
    except Exception as e:
        logger.error(f"Error generating usage overview chart for time_filter {time_filter}: {e}")
        plt.close(fig)
        return None

async def get_usage_overview_display(time_filter: str) -> tuple[str, str | None]:
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

def generate_quiz_performance_chart(score_distribution: dict, time_filter: str) -> str | None:
    if not score_distribution or not any(score_distribution.values()):
        logger.info(f"No score distribution data to generate chart for time_filter {time_filter}.")
        return None
    labels = [process_arabic_text(label) for label in score_distribution.keys()]
    values = list(score_distribution.values())
    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(labels, values, color="#2ca02c", width=0.6)
    ax.set_ylabel(process_arabic_text("عدد المستخدمين"))
    ax.set_xlabel(process_arabic_text("نطاق الدرجات"))
    time_filter_display = TIME_FILTERS_DISPLAY.get(time_filter, time_filter)
    ax.set_title(process_arabic_text(f"توزيع درجات الاختبارات ({time_filter_display})"), pad=20)
    ax.tick_params(axis="x", labelsize=10, rotation=45, ha="right")
    ax.tick_params(axis="y", labelsize=10)
    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 0.02 * max(values) if max(values) > 0 else 0.5, int(yval), ha="center", va="bottom", fontsize=9)
    chart_filename = f"quiz_performance_scores_{time_filter}_{datetime.now().strftime("%Y%m%d%H%M%S")}.png"
    chart_path = os.path.join(CHARTS_DIR, chart_filename)
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        logger.info(f"Generated quiz performance chart: {chart_path}")
        return chart_path
    except Exception as e:
        logger.error(f"Error generating quiz performance chart for time_filter {time_filter}: {e}")
        plt.close(fig)
        return None

async def get_quiz_performance_display(time_filter: str) -> tuple[str, str | None]:
    logger.info(f"[AdminDashboardDisplay] get_quiz_performance_display called for {time_filter}")
    time_filter_display = TIME_FILTERS_DISPLAY.get(time_filter, time_filter)
    avg_correct_percentage = DB_MANAGER.get_overall_average_score(time_filter=time_filter)
    score_distribution_data = DB_MANAGER.get_score_distribution(time_filter=time_filter)
    text_response_parts = [f"📈 *أداء الاختبارات ({time_filter_display}):*"]
    text_response_parts.append(f"- متوسط نسبة الإجابات الصحيحة: {float(avg_correct_percentage):.2f}%")
    if score_distribution_data and any(score_distribution_data.values()):
        text_response_parts.append("\n📊 *توزيع الدرجات:*")
        for score_range, count in score_distribution_data.items():
            text_response_parts.append(f"  - {process_arabic_text(score_range)}: {count} مستخدمين")
    else:
        text_response_parts.append("\n📊 *توزيع الدرجات:* لا توجد بيانات كافية لعرض توزيع الدرجات.")
    text_response = "\n".join(text_response_parts)
    chart_path = None
    if score_distribution_data and any(score_distribution_data.values()):
        chart_path = generate_quiz_performance_chart(score_distribution_data, time_filter)
    else:
        logger.info("Skipping quiz performance chart generation due to no/empty score distribution data.")
    return text_response, chart_path

def generate_user_interaction_chart(interaction_data: dict, time_filter: str) -> str | None:
    """Generates a chart for user interaction metrics (e.g., completion rate vs. drop-off rate)."""
    if not interaction_data or not any(interaction_data.values()):
        logger.info(f"No user interaction data to generate chart for time_filter {time_filter}.")
        return None

    labels = [process_arabic_text(label) for label in interaction_data.keys()]
    values = [float(value) for value in interaction_data.values()] # Ensure values are numeric for plotting

    fig, ax = plt.subplots(figsize=(8, 6))
    bars = ax.bar(labels, values, color=["#ff7f0e", "#d62728"], width=0.5) # Orange and Red

    ax.set_ylabel(process_arabic_text("النسبة المئوية (%)"))
    time_filter_display = TIME_FILTERS_DISPLAY.get(time_filter, time_filter)
    ax.set_title(process_arabic_text(f"معدلات إكمال الاختبارات ({time_filter_display})"), pad=20)
    ax.tick_params(axis="x", labelsize=12)
    ax.tick_params(axis="y", labelsize=10)
    ax.set_ylim(0, 100) # Percentages are 0-100

    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 2, f"{yval:.1f}%", ha="center", va="bottom", fontsize=10)

    chart_filename = f"user_interaction_completion_{time_filter}_{datetime.now().strftime("%Y%m%d%H%M%S")}.png"
    chart_path = os.path.join(CHARTS_DIR, chart_filename)
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        logger.info(f"Generated user interaction chart: {chart_path}")
        return chart_path
    except Exception as e:
        logger.error(f"Error generating user interaction chart for time_filter {time_filter}: {e}")
        plt.close(fig)
        return None

async def get_user_interaction_display(time_filter: str) -> tuple[str, str | None]:
    logger.info(f"[AdminDashboardDisplay] get_user_interaction_display called for {time_filter}")
    time_filter_display = TIME_FILTERS_DISPLAY.get(time_filter, time_filter)

    avg_completion_time_seconds = DB_MANAGER.get_average_quiz_duration(time_filter=time_filter)
    completion_stats = DB_MANAGER.get_quiz_completion_rate_stats(time_filter=time_filter)
    
    completion_rate = completion_stats.get("completion_rate", 0.0)
    # Calculate drop-off rate if total_started is available and > 0
    total_started = completion_stats.get("total_started", 0)
    total_completed = completion_stats.get("total_completed", 0)
    drop_off_rate = 0.0
    if total_started > 0:
        drop_off_rate = ((total_started - total_completed) / total_started) * 100
        
    text_response_parts = [f"👥 *تفاعل المستخدمين ({time_filter_display}):*"]
    text_response_parts.append(f"- متوسط وقت إكمال الاختبار: {float(avg_completion_time_seconds):.2f} ثانية")
    text_response_parts.append(f"- إجمالي الاختبارات التي بدأت: {total_started}")
    text_response_parts.append(f"- إجمالي الاختبارات المكتملة: {total_completed}")
    text_response_parts.append(f"- معدل إكمال الاختبارات: {float(completion_rate):.2f}%")
    text_response_parts.append(f"- معدل التسرب من الاختبارات: {float(drop_off_rate):.2f}%")
    
    # Placeholder for most active times/days - requires new DB functions
    # most_active_day = DB_MANAGER.get_most_active_day(time_filter=time_filter) # e.g., "Monday"
    # most_active_hour = DB_MANAGER.get_most_active_hour(time_filter=time_filter) # e.g., "17:00-18:00"
    # if most_active_day:
    #     text_response_parts.append(f"- اليوم الأكثر نشاطاً: {process_arabic_text(most_active_day)}")
    # if most_active_hour:
    #     text_response_parts.append(f"- الساعة الأكثر نشاطاً: {process_arabic_text(most_active_hour)}")

    text_response = "\n".join(text_response_parts)

    chart_data = {}
    if total_started > 0: # Only generate chart if there are interactions
        chart_data = {
            "معدل الإكمال": completion_rate,
            "معدل التسرب": drop_off_rate
        }
    
    chart_path = None
    if chart_data:
        chart_path = generate_user_interaction_chart(chart_data, time_filter)
    else:
        logger.info("Skipping user interaction chart generation due to no interaction data.")

    return text_response, chart_path

def generate_question_difficulty_chart(difficulty_data: dict, time_filter: str, chart_type: str) -> str | None:
    """Generates a bar chart for hardest or easiest questions showing correct percentage."""
    questions = difficulty_data.get(f"{chart_type}_questions", [])
    if not questions:
        logger.info(f"No {chart_type} question data to generate chart for time_filter {time_filter}.")
        return None

    # Take top N questions for the chart, e.g., top 5
    questions_to_chart = questions[:5]
    
    labels = [process_arabic_text(q["text"][:30] + "...") for q in questions_to_chart]
    values = [q["correct_percentage"] for q in questions_to_chart]
    
    fig, ax = plt.subplots(figsize=(12, 7)) # Wider for question text
    bars = ax.bar(labels, values, color="#9467bd" if chart_type == "hardest" else "#8c564b", width=0.5) # Purple for hardest, Brown for easiest

    ax.set_ylabel(process_arabic_text("نسبة الإجابة الصحيحة (%)"))
    time_filter_display = TIME_FILTERS_DISPLAY.get(time_filter, time_filter)
    chart_title_type = "الأصعب" if chart_type == "hardest" else "الأسهل"
    ax.set_title(process_arabic_text(f"الأسئلة الـ{len(questions_to_chart)} {chart_title_type} ({time_filter_display})"), pad=20)
    ax.tick_params(axis="x", labelsize=9, rotation=30, ha="right")
    ax.tick_params(axis="y", labelsize=10)
    ax.set_ylim(0, 100)

    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 2, f"{yval:.1f}%", ha="center", va="bottom", fontsize=9)

    chart_filename = f"question_difficulty_{chart_type}_{time_filter}_{datetime.now().strftime("%Y%m%d%H%M%S")}.png"
    chart_path = os.path.join(CHARTS_DIR, chart_filename)
    try:
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close(fig)
        logger.info(f"Generated question difficulty ({chart_type}) chart: {chart_path}")
        return chart_path
    except Exception as e:
        logger.error(f"Error generating question difficulty ({chart_type}) chart for time_filter {time_filter}: {e}")
        plt.close(fig)
        return None

async def get_question_stats_display(time_filter: str) -> tuple[str, list[str] | None]: # Return list of chart paths
    logger.info(f"[AdminDashboardDisplay] get_question_stats_display called for {time_filter}")
    time_filter_display = TIME_FILTERS_DISPLAY.get(time_filter, time_filter)
    
    # Fetch up to 5 hardest and easiest questions
    question_difficulty_data = DB_MANAGER.get_question_difficulty_stats(time_filter=time_filter, limit=5) 
    # Fetch most attempted questions (assuming a new DB function)
    # most_attempted_questions = DB_MANAGER.get_most_attempted_questions(time_filter=time_filter, limit=5)

    text_response_parts = [f"❓ *إحصائيات الأسئلة ({time_filter_display}):*"]

    hardest_questions = question_difficulty_data.get("hardest_questions", [])
    if hardest_questions:
        text_response_parts.append("\n📉 *أصعب الأسئلة (حسب أقل نسبة إجابات صحيحة):*")
        for i, q in enumerate(hardest_questions):
            text_response_parts.append(f"  {i+1}. \"{process_arabic_text(q["text"][:40])}...\" (صحة: {q["correct_percentage"]:.2f}%, محاولات: {q.get("attempts", "غير متوفر")})")
    else:
        text_response_parts.append("\n📉 *أصعب الأسئلة:* لا توجد بيانات كافية.")

    easiest_questions = question_difficulty_data.get("easiest_questions", [])
    if easiest_questions:
        text_response_parts.append("\n📈 *أسهل الأسئلة (حسب أعلى نسبة إجابات صحيحة):*")
        for i, q in enumerate(easiest_questions):
            text_response_parts.append(f"  {i+1}. \"{process_arabic_text(q["text"][:40])}...\" (صحة: {q["correct_percentage"]:.2f}%, محاولات: {q.get("attempts", "غير متوفر")})")
    else:
        text_response_parts.append("\n📈 *أسهل الأسئلة:* لا توجد بيانات كافية.")

    # Placeholder for most attempted questions
    # if most_attempted_questions:
    #     text_response_parts.append("\n🔥 *الأسئلة الأكثر محاولة:*")
    #     for i, q in enumerate(most_attempted_questions):
    #         text_response_parts.append(f"  {i+1}. \"{process_arabic_text(q["text"][:40])}...\" (محاولات: {q.get("attempts", "N/A")}, صحة: {q.get("correct_percentage", "N/A"):.2f}%)")

    text_response = "\n".join(text_response_parts)
    
    chart_paths = []
    hardest_chart_path = None
    easiest_chart_path = None

    if hardest_questions:
        hardest_chart_path = generate_question_difficulty_chart(question_difficulty_data, time_filter, "hardest")
        if hardest_chart_path:
            chart_paths.append(hardest_chart_path)
    
    if easiest_questions:
        easiest_chart_path = generate_question_difficulty_chart(question_difficulty_data, time_filter, "easiest")
        if easiest_chart_path:
            chart_paths.append(easiest_chart_path)
            
    if not chart_paths:
        logger.info("Skipping question stats chart generation due to no sufficient data.")
        return text_response, None

    return text_response, chart_paths

