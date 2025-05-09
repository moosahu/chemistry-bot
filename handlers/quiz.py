"""
Conversation handler for the quiz selection and execution flow (FULLY COMPATIBLE - PostgreSQL Logging & Original UI Preservation).
"""

import logging
import math
import random
import re
from datetime import datetime # Added for quiz_id timestamp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    CommandHandler
)

from config import (
    logger,
    MAIN_MENU, QUIZ_MENU, SELECT_QUIZ_TYPE, 
    SELECT_COURSE_FOR_UNIT_QUIZ, SELECT_UNIT_FOR_COURSE, 
    SELECT_QUIZ_SCOPE, 
    ENTER_QUESTION_COUNT, TAKING_QUIZ, SHOWING_RESULTS, END,
    QUIZ_TYPE_RANDOM, QUIZ_TYPE_CHAPTER, QUIZ_TYPE_UNIT, QUIZ_TYPE_ALL, 
    DEFAULT_QUESTION_TIME_LIMIT
)
from utils.helpers import safe_send_message, safe_edit_message_text, get_quiz_type_string, remove_job_if_exists
from utils.api_client import fetch_from_api
from handlers.common import create_main_menu_keyboard, main_menu_callback 
from .quiz_logic import QuizLogic, question_timeout_callback_wrapper # Assuming quiz_logic is in the same directory

# --- STATS UPDATE (ORIGINAL JSON) ---
from handlers.stats import update_user_stats_in_json
# -------------------------------------

# --- POSTGRESQL DATABASE LOGGING ---
# Ensure this path is correct for your project structure (e.g., if handlers/ and database/ are siblings)
try:
    from database.data_logger import log_user_activity, log_quiz_start
except ImportError as e:
    logger.error(f"CRITICAL: Could not import from database.data_logger: {e}. Ensure it's in the correct path (e.g., PYTHONPATH or relative). Stats for admin panel will not work.")
    # Define dummy functions to prevent crashes if import fails
    def log_user_activity(*args, **kwargs): logger.error("Dummy log_user_activity called due to import error."); pass
    def log_quiz_start(*args, **kwargs): logger.error("Dummy log_quiz_start called due to import error."); return None
# -----------------------------------

ITEMS_PER_PAGE = 6

async def start_command_fallback_for_quiz(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} sent /start during an active or lingering quiz conversation. Ending current quiz conversation and showing main menu.")
    
    if "quiz_sessions" in context.user_data:
        for quiz_id, quiz_instance in list(context.user_data["quiz_sessions"].items()): 
            if isinstance(quiz_instance, QuizLogic) and quiz_instance.user_id == user_id:
                try:
                    if hasattr(quiz_instance, 'end_quiz') and callable(getattr(quiz_instance, 'end_quiz')):
                         await quiz_instance.end_quiz(context.bot, context, update, manual_end=True, reason_suffix="start_fallback_quiz_handler", called_from_fallback=True)
                    else:
                         quiz_instance.active = False 
                         await quiz_instance.cleanup_quiz_data(context, user_id, "start_fallback_quiz_handler_direct_cleanup")
                    logger.info(f"Cleaned up quiz session {quiz_id} for user {user_id} during /start fallback.")
                except Exception as e_cleanup:
                    logger.error(f"Error during quiz_logic cleanup for quiz {quiz_id} in start_command_fallback: {e_cleanup}")
                    if quiz_id in context.user_data["quiz_sessions"]:
                        del context.user_data["quiz_sessions"][quiz_id]
        if not context.user_data["quiz_sessions"]:
            context.user_data.pop("quiz_sessions", None)

    keys_to_pop = [
        "selected_quiz_type_key", "selected_quiz_type_display_name", "questions_for_quiz",
        "selected_course_id_for_unit_quiz", "available_courses_for_unit_quiz",
        "current_course_page_for_unit_quiz", "selected_course_name_for_unit_quiz",
        "available_units_for_course", "current_unit_page_for_course",
        "selected_unit_id", "selected_unit_name", "question_count_for_quiz",
        f"quiz_instance_{user_id}_{update.effective_chat.id}", # Old key pattern
        "db_quiz_session_id" # Clear stored DB session ID
    ]
    for key in list(context.user_data.keys()):
        if key.startswith("quiz_setup_") or key.startswith("qtimer_") or key in keys_to_pop or key.startswith(f"quiz_instance_{user_id}_") or key.startswith(f"quiz_message_id_to_edit_{user_id}_"):
             context.user_data.pop(key, None)

    logger.info(f"Cleared quiz-related user_data for user {user_id} due to /start fallback in quiz conversation.")
    await main_menu_callback(update, context, called_from_fallback=True) 
    return ConversationHandler.END

def create_quiz_type_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🎲 اختبار عشوائي شامل (كل المقررات)", callback_data=f"quiz_type_{QUIZ_TYPE_ALL}")],
        [InlineKeyboardButton("📚 حسب الوحدة الدراسية (اختر المقرر ثم الوحدة)", callback_data=f"quiz_type_{QUIZ_TYPE_UNIT}")],
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")] 
    ]
    return InlineKeyboardMarkup(keyboard)

def create_course_selection_keyboard(courses: list, current_page: int = 0) -> InlineKeyboardMarkup:
    keyboard = []
    items_per_page = ITEMS_PER_PAGE
    start_index = current_page * items_per_page
    end_index = start_index + items_per_page
    for i in range(start_index, min(end_index, len(courses))):
        course = courses[i]
        keyboard.append([InlineKeyboardButton(course.get("name", f"مقرر {course.get('id')}"), callback_data=f"quiz_course_select_{course.get('id')}")])
    pagination_buttons = []
    if current_page > 0:
        pagination_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"quiz_course_page_{current_page - 1}"))
    if end_index < len(courses):
        pagination_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"quiz_course_page_{current_page + 1}"))
    if pagination_buttons:
        keyboard.append(pagination_buttons)
    keyboard.append([InlineKeyboardButton("🔙 اختيار نوع الاختبار", callback_data="quiz_type_back_to_type_selection")])
    return InlineKeyboardMarkup(keyboard)

def create_unit_selection_keyboard(units: list, course_id: str, current_page: int = 0) -> InlineKeyboardMarkup:
    keyboard = []
    items_per_page = ITEMS_PER_PAGE
    start_index = current_page * items_per_page
    end_index = start_index + items_per_page
    for i in range(start_index, min(end_index, len(units))):
        unit = units[i]
        keyboard.append([InlineKeyboardButton(unit.get("name", f"وحدة {unit.get('id')}"), callback_data=f"quiz_unit_select_{course_id}_{unit.get('id')}")])
    pagination_buttons = []
    if current_page > 0:
        pagination_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"quiz_unit_page_{course_id}_{current_page - 1}"))
    if end_index < len(units):
        pagination_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"quiz_unit_page_{course_id}_{current_page + 1}"))
    if pagination_buttons:
        keyboard.append(pagination_buttons)
    keyboard.append([InlineKeyboardButton("🔙 اختيار المقرر", callback_data="quiz_unit_back_to_course_selection")])
    return InlineKeyboardMarkup(keyboard)

def create_question_count_keyboard(max_questions: int, quiz_type: str, unit_id: str = None, course_id_for_unit: str = None) -> InlineKeyboardMarkup:
    counts = [1, 5, 10, 20, min(max_questions, 50)]
    if max_questions > 0 and max_questions not in counts and max_questions <= 50:
        counts.append(max_questions)
    counts = sorted(list(set(c for c in counts if c <= max_questions and c > 0)))
    keyboard = []
    row = []
    for count in counts:
        row.append(InlineKeyboardButton(str(count), callback_data=f"num_questions_{count}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    if not counts or (counts and max_questions > counts[-1] and max_questions > 0):
         keyboard.append([InlineKeyboardButton(f"الكل ({max_questions})", callback_data="num_questions_all")])
    
    if quiz_type == QUIZ_TYPE_UNIT and course_id_for_unit and unit_id:
        back_callback_data = f"quiz_count_back_to_unit_selection_{course_id_for_unit}" 
    else:
        back_callback_data = "quiz_type_back_to_type_selection"
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback_data)])
    return InlineKeyboardMarkup(keyboard)

async def quiz_menu_entry(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    logger.info(f"User {user_id} entered quiz menu (quiz_menu_entry) via {query.data}.")
    keys_to_clear_on_entry = [
        "selected_quiz_type_key", "selected_quiz_type_display_name", "questions_for_quiz",
        "selected_course_id_for_unit_quiz", "available_courses_for_unit_quiz",
        "current_course_page_for_unit_quiz", "selected_course_name_for_unit_quiz",
        "available_units_for_course", "current_unit_page_for_course",
        "selected_unit_id", "selected_unit_name", "question_count_for_quiz",
        "db_quiz_session_id" # Clear previous DB session ID if any
    ]
    for key in keys_to_clear_on_entry:
        context.user_data.pop(key, None)
    logger.debug(f"Cleared preliminary quiz setup data for user {user_id} at quiz_menu_entry.")
    keyboard = create_quiz_type_keyboard()
    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
    return SELECT_QUIZ_TYPE

async def select_quiz_type(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data

    if callback_data == "main_menu":
        logger.info(f"[select_quiz_type] User {user_id} selected main_menu. Ending quiz conversation.")
        await main_menu_callback(update, context) 
        return ConversationHandler.END
        
    if callback_data == "quiz_type_back_to_type_selection": 
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    quiz_type_key = callback_data.replace("quiz_type_", "", 1)
    context.user_data["selected_quiz_type_key"] = quiz_type_key
    quiz_type_display_name = get_quiz_type_string(quiz_type_key)
    context.user_data["selected_quiz_type_display_name"] = quiz_type_display_name
    error_message_to_user = "عذراً، حدث خطأ أثناء جلب البيانات. يرجى المحاولة لاحقاً أو التأكد من أن خدمة الأسئلة تعمل."
    api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."

    if quiz_type_key == QUIZ_TYPE_ALL:
        all_questions_pool = fetch_from_api("api/v1/questions/all")
        if all_questions_pool == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        if not all_questions_pool or not isinstance(all_questions_pool, list):
            courses = fetch_from_api("api/v1/courses")
            if courses == "TIMEOUT":
                await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_quiz_type_keyboard())
                return SELECT_QUIZ_TYPE
            if not courses or not isinstance(courses, list):
                await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=error_message_to_user, reply_markup=create_quiz_type_keyboard())
                return SELECT_QUIZ_TYPE
            all_questions_pool = []
            for course in courses:
                course_id = course.get("id")
                if not course_id: continue
                current_course_questions = fetch_from_api(f"api/v1/courses/{course_id}/questions")
                if current_course_questions == "TIMEOUT": continue 
                if isinstance(current_course_questions, list):
                    all_questions_pool.extend(current_course_questions)
        if not all_questions_pool:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لم يتم العثور على أسئلة للاختبار الشامل.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        context.user_data[f"quiz_setup_{quiz_type_key}_all"] = {
            "questions": all_questions_pool,
            "quiz_name": quiz_type_display_name
        }
        context.user_data["selected_unit_id"] = "all" # For consistency in quiz_setup_data_key later
        max_questions = len(all_questions_pool)
        keyboard = create_question_count_keyboard(max_questions, quiz_type_key, unit_id="all")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار \n\"{quiz_type_display_name}\":", reply_markup=keyboard)
        return ENTER_QUESTION_COUNT

    elif quiz_type_key == QUIZ_TYPE_UNIT:
        courses = fetch_from_api("api/v1/courses")
        if courses == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        if not courses or not isinstance(courses, list) or not courses:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لا توجد مقررات متاحة حالياً أو حدث خطأ في جلبها.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        context.user_data["available_courses_for_unit_quiz"] = courses
        context.user_data["current_course_page_for_unit_quiz"] = 0
        keyboard = create_course_selection_keyboard(courses, 0)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="اختر المقرر الدراسي أولاً:", reply_markup=keyboard)
        return SELECT_COURSE_FOR_UNIT_QUIZ
    else:
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="نوع اختبار غير معروف. يرجى الاختيار من القائمة.", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

async def select_course_for_unit_quiz(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data
    courses = context.user_data.get("available_courses_for_unit_quiz", [])
    current_page = context.user_data.get("current_course_page_for_unit_quiz", 0)

    if callback_data == "quiz_type_back_to_type_selection":
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    if callback_data.startswith("quiz_course_page_"):
        new_page = int(callback_data.split("_")[-1])
        context.user_data["current_course_page_for_unit_quiz"] = new_page
        keyboard = create_course_selection_keyboard(courses, new_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="اختر المقرر الدراسي:", reply_markup=keyboard)
        return SELECT_COURSE_FOR_UNIT_QUIZ
    elif callback_data.startswith("quiz_course_select_"):
        course_id = callback_data.split("_")[-1]
        selected_course = next((c for c in courses if str(c.get("id")) == course_id), None)
        if not selected_course:
            logger.error(f"User {user_id}: Selected course ID {course_id} not found in available courses.")
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، المقرر المختار غير موجود. يرجى المحاولة مرة أخرى.", reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
        context.user_data["selected_course_id_for_unit_quiz"] = course_id
        context.user_data["selected_course_name_for_unit_quiz"] = selected_course.get("name", f"مقرر {course_id}")
        units = fetch_from_api(f"api/v1/courses/{course_id}/units")
        if units == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="انتهت مهلة الاتصال بخادم الأسئلة أثناء جلب الوحدات. يرجى المحاولة مرة أخرى لاحقاً.", reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
        if not units or not isinstance(units, list) or not units:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"عذراً، لا توجد وحدات متاحة للمقرر \"{selected_course.get('name', '')}\" أو حدث خطأ في جلبها.", reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
        context.user_data["available_units_for_course"] = units
        context.user_data["current_unit_page_for_course"] = 0
        keyboard = create_unit_selection_keyboard(units, course_id, 0)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية للمقرر \"{selected_course.get('name', '')}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    else:
        logger.warning(f"User {user_id}: Unexpected callback_data in select_course_for_unit_quiz: {callback_data}")
        keyboard = create_course_selection_keyboard(courses, current_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="اختيار غير صالح. يرجى المحاولة مرة أخرى.", reply_markup=keyboard)
        return SELECT_COURSE_FOR_UNIT_QUIZ

async def select_unit_for_course(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data
    selected_course_id = context.user_data.get("selected_course_id_for_unit_quiz")
    units = context.user_data.get("available_units_for_course", [])
    current_page = context.user_data.get("current_unit_page_for_course", 0)

    if callback_data == "quiz_unit_back_to_course_selection":
        courses = context.user_data.get("available_courses_for_unit_quiz", [])
        course_page = context.user_data.get("current_course_page_for_unit_quiz", 0)
        keyboard = create_course_selection_keyboard(courses, course_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="اختر المقرر الدراسي:", reply_markup=keyboard)
        return SELECT_COURSE_FOR_UNIT_QUIZ

    if callback_data.startswith("quiz_unit_page_"):
        parts = callback_data.split("_")
        # course_id_from_cb = parts[-2] # Not strictly needed if selected_course_id is reliable
        new_page = int(parts[-1])
        context.user_data["current_unit_page_for_course"] = new_page
        keyboard = create_unit_selection_keyboard(units, selected_course_id, new_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية للمقرر \"{context.user_data.get('selected_course_name_for_unit_quiz', '')}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data.startswith("quiz_unit_select_"):
        parts = callback_data.split("_")
        unit_id = parts[-1]
        # course_id_from_cb = parts[-2] # Ensure it matches selected_course_id if used
        selected_unit = next((u for u in units if str(u.get("id")) == unit_id), None)
        if not selected_unit:
            logger.error(f"User {user_id}: Selected unit ID {unit_id} not found for course {selected_course_id}.")
            keyboard = create_unit_selection_keyboard(units, selected_course_id, current_page)
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، الوحدة المختارة غير موجودة. يرجى المحاولة مرة أخرى.", reply_markup=keyboard)
            return SELECT_UNIT_FOR_COURSE
        context.user_data["selected_unit_id"] = unit_id
        context.user_data["selected_unit_name"] = selected_unit.get("name", f"وحدة {unit_id}")
        unit_questions = fetch_from_api(f"api/v1/units/{unit_id}/questions")
        if unit_questions == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="انتهت مهلة الاتصال بخادم الأسئلة أثناء جلب أسئلة الوحدة. يرجى المحاولة مرة أخرى لاحقاً.", reply_markup=create_unit_selection_keyboard(units, selected_course_id, current_page))
            return SELECT_UNIT_FOR_COURSE
        if not unit_questions or not isinstance(unit_questions, list) or not unit_questions:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"عذراً، لا توجد أسئلة متاحة للوحدة \"{selected_unit.get('name', '')}\" أو حدث خطأ في جلبها.", reply_markup=create_unit_selection_keyboard(units, selected_course_id, current_page))
            return SELECT_UNIT_FOR_COURSE
        context.user_data[f"quiz_setup_{context.user_data['selected_quiz_type_key']}_{unit_id}"] = {
            "questions": unit_questions,
            "quiz_name": f"{context.user_data.get('selected_course_name_for_unit_quiz', '')} - {selected_unit.get('name', '')}"
        }
        max_questions = len(unit_questions)
        keyboard = create_question_count_keyboard(max_questions, context.user_data['selected_quiz_type_key'], unit_id, selected_course_id)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار وحدة \"{selected_unit.get('name', '')}\" من مقرر \"{context.user_data.get('selected_course_name_for_unit_quiz', '')}\":", reply_markup=keyboard)
        return ENTER_QUESTION_COUNT
    else:
        logger.warning(f"User {user_id}: Unexpected callback_data in select_unit_for_course: {callback_data}")
        keyboard = create_unit_selection_keyboard(units, selected_course_id, current_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="اختيار غير صالح. يرجى المحاولة مرة أخرى.", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE

async def select_question_count(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    callback_data = query.data
    selected_quiz_type_key = context.user_data.get("selected_quiz_type_key")
    selected_unit_id = context.user_data.get("selected_unit_id") # Will be 'all' for QUIZ_TYPE_ALL
    selected_course_id = context.user_data.get("selected_course_id_for_unit_quiz") # For QUIZ_TYPE_UNIT

    if callback_data.startswith("quiz_count_back_to_unit_selection_"):
        course_id_from_cb = callback_data.split("_")[-1]
        units = context.user_data.get("available_units_for_course", [])
        unit_page = context.user_data.get("current_unit_page_for_course", 0)
        keyboard = create_unit_selection_keyboard(units, course_id_from_cb, unit_page)
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية للمقرر \"{context.user_data.get('selected_course_name_for_unit_quiz', '')}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data == "quiz_type_back_to_type_selection":
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    quiz_setup_data_key = f"quiz_setup_{selected_quiz_type_key}_{selected_unit_id}"
    quiz_data_for_type = context.user_data.get(quiz_setup_data_key)
    if not quiz_data_for_type or "questions" not in quiz_data_for_type:
        logger.error(f"User {user_id}: Quiz data not found for key {quiz_setup_data_key} in select_question_count.")
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="حدث خطأ في إعداد الاختبار. يرجى المحاولة من البداية.", reply_markup=create_main_menu_keyboard())
        return MAIN_MENU 

    all_questions_for_quiz = quiz_data_for_type.get("questions", [])
    quiz_name_for_logic = quiz_data_for_type.get("quiz_name", "اختبار مخصص")
    max_questions = len(all_questions_for_quiz)

    if callback_data == "num_questions_all":
        num_questions = max_questions
    elif callback_data.startswith("num_questions_"):
        try:
            num_questions = int(callback_data.split("_")[-1])
            if not (0 < num_questions <= max_questions):
                raise ValueError("Invalid number of questions selected.")
        except ValueError:
            logger.warning(f"User {user_id} selected invalid question count: {callback_data}.")
            keyboard = create_question_count_keyboard(max_questions, selected_quiz_type_key, selected_unit_id, selected_course_id)
            await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="عدد أسئلة غير صالح. يرجى المحاولة مرة أخرى.", reply_markup=keyboard)
            return ENTER_QUESTION_COUNT
    else:
        logger.error(f"User {user_id}: Unexpected callback_data in select_question_count: {callback_data}")
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="حدث خطأ غير متوقع. الرجاء المحاولة مرة أخرى.", reply_markup=create_main_menu_keyboard())
        return MAIN_MENU

    context.user_data["question_count_for_quiz"] = num_questions
    questions_to_use = random.sample(all_questions_for_quiz, num_questions) if num_questions < max_questions and max_questions > 0 else all_questions_for_quiz
    
    telegram_user = query.from_user
    db_quiz_session_id = context.user_data.get("db_quiz_session_id") # Retrieve the stored DB session ID
    
    # Log user activity and quiz start (already done and db_quiz_session_id should be in context.user_data)
    # We ensure db_quiz_session_id is retrieved from context before QuizLogic initialization.
    if not db_quiz_session_id:
        # This block is a fallback or error handling if db_quiz_session_id wasn't set before.
        # Ideally, it should always be set by the time we reach here if log_quiz_start was successful.
        logger.warning(f"User {user_id}: db_quiz_session_id was not found in context.user_data. Attempting to log quiz start again or this might be an issue.")
        try:
            log_user_activity(
                user_id=telegram_user.id,
                username=telegram_user.username,
                first_name=telegram_user.first_name,
                last_name=telegram_user.last_name,
                language_code=telegram_user.language_code,
                action="quiz_setup_activity_fallback" # MODIFIED: Added action argument
            )
            log_quiz_name = context.user_data.get("selected_unit_name") or context.user_data.get("selected_quiz_type_display_name", "اختبار عام")
            db_quiz_session_id = log_quiz_start(
                user_id=telegram_user.id,
                quiz_name=log_quiz_name, 
                total_questions=num_questions,
                quiz_type=selected_quiz_type_key
            )
            if db_quiz_session_id:
                context.user_data["db_quiz_session_id"] = db_quiz_session_id # Store it again if newly created
                logger.info(f"User {user_id}: DB quiz session (re-)started with ID: {db_quiz_session_id} for quiz_type: {selected_quiz_type_key}")
            else:
                logger.error(f"User {user_id}: Failed to get db_quiz_session_id from log_quiz_start (fallback attempt) for quiz_type: {selected_quiz_type_key}.")
        except Exception as e_db_log_fallback:
            logger.error(f"User {user_id}: Error during fallback DB logging: {e_db_log_fallback}", exc_info=True)

    context.user_data.setdefault("quiz_sessions", {})
    
    # --- CRITICAL FIX: Pass db_quiz_session_id to QuizLogic --- 
    quiz_instance = QuizLogic(
        user_id=user_id,
        chat_id=chat_id, 
        quiz_type=selected_quiz_type_key,
        questions_data=questions_to_use,
        question_time_limit=DEFAULT_QUESTION_TIME_LIMIT, 
        quiz_name=quiz_name_for_logic,
        quiz_id=str(db_quiz_session_id) if db_quiz_session_id else f"quiz_{user_id}_{datetime.now().timestamp()}", # Use DB ID if available, else fallback
        db_quiz_session_id=db_quiz_session_id  # Ensure this is passed
    )
    context.user_data["quiz_sessions"][quiz_instance.quiz_id] = quiz_instance
    context.user_data[f"quiz_instance_{user_id}_{chat_id}"] = quiz_instance # Legacy key, consider phasing out
    logger.info(f"User {user_id} starting quiz '{quiz_name_for_logic}' (QuizLogic ID: {quiz_instance.quiz_id}, DB Session: {db_quiz_session_id}) with {num_questions} questions.")

    await quiz_instance.start_quiz(context.bot, context, update, query.message.message_id)
    return TAKING_QUIZ

async def process_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    callback_data = query.data
    
    quiz_id_from_callback = callback_data.split("_")[2] # e.g., quiz_answer_QUIZID_QINDEX_AINDEX
    active_quiz_instance = context.user_data.get("quiz_sessions", {}).get(quiz_id_from_callback)

    if not active_quiz_instance or not active_quiz_instance.active:
        logger.warning(f"User {user_id} answer for inactive/non-existent quiz {quiz_id_from_callback}. Callback: {callback_data}")
        try:
            await safe_edit_message_text(
                context.bot, 
                chat_id=chat_id, 
                message_id=query.message.message_id, 
                text="عذراً، هذا الاختبار لم يعد نشطاً أو انتهت صلاحيته. يرجى بدء اختبار جديد.",
                reply_markup=create_main_menu_keyboard(user_id=user_id) # Ensure user_id is passed if needed by common handler
            )
        except Exception as e_edit_inactive:
            logger.error(f"Error editing message for inactive quiz answer: {e_edit_inactive}")
        return ConversationHandler.END 

    return await active_quiz_instance.handle_answer(context.bot, context, update, callback_data)

async def next_question_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    quiz_id_from_callback = query.data.split("_")[-1]
    active_quiz_instance = context.user_data.get("quiz_sessions", {}).get(quiz_id_from_callback)

    if not active_quiz_instance or not active_quiz_instance.active:
        logger.warning(f"User {user_id} next_question for inactive/non-existent quiz {quiz_id_from_callback}.")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، هذا الاختبار لم يعد نشطاً.", reply_markup=create_main_menu_keyboard(user_id=user_id))
        return ConversationHandler.END
    return await active_quiz_instance.show_next_question(context.bot, context, update, query.message.message_id)

async def prev_question_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    quiz_id_from_callback = query.data.split("_")[-1]
    active_quiz_instance = context.user_data.get("quiz_sessions", {}).get(quiz_id_from_callback)

    if not active_quiz_instance or not active_quiz_instance.active:
        logger.warning(f"User {user_id} prev_question for inactive/non-existent quiz {quiz_id_from_callback}.")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، هذا الاختبار لم يعد نشطاً.", reply_markup=create_main_menu_keyboard(user_id=user_id))
        return ConversationHandler.END
    return await active_quiz_instance.show_previous_question(context.bot, context, update, query.message.message_id)

async def end_quiz_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    quiz_id_from_callback = query.data.split("_")[-1]
    active_quiz_instance = context.user_data.get("quiz_sessions", {}).get(quiz_id_from_callback)

    if not active_quiz_instance or not active_quiz_instance.active:
        logger.warning(f"User {user_id} end_quiz for inactive/non-existent quiz {quiz_id_from_callback}.")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، هذا الاختبار لم يعد نشطاً أو قد تم إنهاؤه بالفعل.", reply_markup=create_main_menu_keyboard(user_id=user_id))
        return ConversationHandler.END
    
    # The end_quiz method in QuizLogic should handle DB logging and stats update
    return await active_quiz_instance.end_quiz(context.bot, context, update, manual_end=True, reason_suffix="user_manual_end")

async def toggle_bookmark_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    parts = query.data.split("_")
    quiz_id_from_callback = parts[3]
    question_index = int(parts[4])
    active_quiz_instance = context.user_data.get("quiz_sessions", {}).get(quiz_id_from_callback)

    if not active_quiz_instance or not active_quiz_instance.active:
        logger.warning(f"User {user_id} toggle_bookmark for inactive/non-existent quiz {quiz_id_from_callback}.")
        # Optionally inform user, but might be too intrusive if message is already gone
        return
    await active_quiz_instance.toggle_bookmark(context.bot, context, update, question_index, query.message.message_id)

async def quiz_timeout_graceful_end(context: CallbackContext) -> None:
    job = context.job
    user_id = job.data["user_id"]
    chat_id = job.data["chat_id"]
    quiz_id = job.data["quiz_id"]
    original_message_id = job.data["original_message_id"]
    
    logger.info(f"Quiz timeout job triggered for user {user_id}, quiz {quiz_id}.")
    
    active_quiz_instance = context.user_data.get("quiz_sessions", {}).get(quiz_id)

    if active_quiz_instance and active_quiz_instance.active:
        logger.info(f"Quiz {quiz_id} for user {user_id} is still active. Ending due to timeout.")
        # Create a dummy Update object if needed by end_quiz, or adapt end_quiz
        # For now, we assume end_quiz can handle being called without a full Update if necessary
        # or we pass essential parts like bot, chat_id, user_id.
        # A more robust way is to have a simplified end_quiz_for_timeout in QuizLogic.
        try:
            # Construct a minimal Update-like structure if necessary, or rely on QuizLogic's adaptability
            # For this example, we'll assume QuizLogic's end_quiz can be called with bot, context, and identifiers
            await active_quiz_instance.end_quiz(context.bot, context, update=None, manual_end=False, reason_suffix="timeout", original_message_id_for_timeout_cleanup=original_message_id)
        except Exception as e_timeout_end:
            logger.error(f"Error during quiz_timeout_graceful_end for quiz {quiz_id}: {e_timeout_end}", exc_info=True)
            # Fallback cleanup if end_quiz fails catastrophically
            active_quiz_instance.active = False
            await active_quiz_instance.cleanup_quiz_data(context, user_id, "timeout_graceful_end_fallback_cleanup")
    else:
        logger.info(f"Quiz {quiz_id} for user {user_id} was already inactive or not found during timeout job.")
        # Ensure cleanup if it was missed
        if quiz_id in context.user_data.get("quiz_sessions", {}):
            # Minimal cleanup if instance is gone or inactive
            context.user_data["quiz_sessions"].pop(quiz_id, None)
            if not context.user_data["quiz_sessions"]:
                context.user_data.pop("quiz_sessions", None)
            logger.info(f"Performed minimal cleanup for quiz {quiz_id} during timeout as it was already inactive/gone.")

# Fallback handler for any unhandled callback queries within the quiz conversation
async def unhandled_quiz_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    logger.warning(f"User {user_id} sent an unhandled callback query in quiz conversation: {query.data}")
    await query.answer("أمر غير معروف أو غير صالح في هذا السياق.")
    # Optionally, resend the current state's message or main menu
    # For now, just acknowledge and do nothing further to avoid disrupting flow too much.

quiz_conv_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(quiz_menu_entry, pattern=f"^{QUIZ_MENU}$")
    ],
    states={
        SELECT_QUIZ_TYPE: [
            CallbackQueryHandler(select_quiz_type, pattern=f"^quiz_type_({QUIZ_TYPE_ALL}|{QUIZ_TYPE_UNIT})$"),
            CallbackQueryHandler(main_menu_callback, pattern=f"^{MAIN_MENU}$") # Allow exit to main menu
        ],
        SELECT_COURSE_FOR_UNIT_QUIZ: [
            CallbackQueryHandler(select_course_for_unit_quiz, pattern=f"^quiz_course_select_\d+$"),
            CallbackQueryHandler(select_course_for_unit_quiz, pattern=f"^quiz_course_page_\d+$"),
            CallbackQueryHandler(select_quiz_type, pattern="^quiz_type_back_to_type_selection$") # Back to type selection
        ],
        SELECT_UNIT_FOR_COURSE: [
            CallbackQueryHandler(select_unit_for_course, pattern=f"^quiz_unit_select_\d+_\d+$"),
            CallbackQueryHandler(select_unit_for_course, pattern=f"^quiz_unit_page_\d+_\d+$"),
            CallbackQueryHandler(select_course_for_unit_quiz, pattern="^quiz_unit_back_to_course_selection$") # Back to course selection
        ],
        ENTER_QUESTION_COUNT: [
            CallbackQueryHandler(select_question_count, pattern=f"^num_questions_(\d+|all)$"),
            CallbackQueryHandler(select_unit_for_course, pattern=f"^quiz_count_back_to_unit_selection_\d+$"), # Back to unit selection
            CallbackQueryHandler(select_quiz_type, pattern="^quiz_type_back_to_type_selection$") # Back to type selection (if from QUIZ_TYPE_ALL)
        ],
        TAKING_QUIZ: [
            CallbackQueryHandler(process_answer, pattern=f"^quiz_answer_.+$"), # More generic to catch QUIZID
            CallbackQueryHandler(next_question_callback, pattern=f"^quiz_next_question_.+$"),
            CallbackQueryHandler(prev_question_callback, pattern=f"^quiz_prev_question_.+$"),
            CallbackQueryHandler(end_quiz_callback, pattern=f"^quiz_end_quiz_.+$"),
            CallbackQueryHandler(toggle_bookmark_callback, pattern=f"^quiz_toggle_bookmark_.+$")
        ],
        # SHOWING_RESULTS is handled by QuizLogic and then returns ConversationHandler.END or redirects
    },
    fallbacks=[
        CommandHandler("start", start_command_fallback_for_quiz), # Handle /start during quiz
        CallbackQueryHandler(main_menu_callback, pattern=f"^{MAIN_MENU}$"), # Global exit
        CallbackQueryHandler(unhandled_quiz_callback) # Catch-all for unhandled callbacks in this conversation
    ],
    map_to_parent={
        # If ConversationHandler.END is returned, it will end here.
        # If you want to return to a main conversation, map END to that state.
        END: ConversationHandler.END 
    },
    per_message=False, # Important for callback query handlers in conversations
    name="quiz_conversation_handler",
    persistent=True, # Optional: Store conversation state across bot restarts
    # conversation_timeout=timedelta(minutes=30) # Optional: Auto-end conversation after inactivity
)

