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
    logger.error(f"CRITICAL: Could not import from database.data_logger: {e}. Ensure it\'s in the correct path (e.g., PYTHONPATH or relative). Stats for admin panel will not work.")
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
        course = courses        keyboard.append([InlineKeyboardButton(course.get("name", f"مقرر {course.get('id')}"), callback_data=f"quiz_course_select_{course.get('id')}")])
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
        keyboard.append([InlineKeyboardButton(unit.get("name", f"وحدة {unit.get(\'id\')}"), callback_data=f"quiz_unit_select_{course_id}_{unit.get(\'id\')}")])
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
        course_id = callback_data.replace("quiz_course_select_", "", 1)
        context.user_data["selected_course_id_for_unit_quiz"] = course_id
        selected_course = next((c for c in courses if str(c.get("id")) == str(course_id)), None)
        context.user_data["selected_course_name_for_unit_quiz"] = selected_course.get("name", f"مقرر {course_id}") if selected_course else f"مقرر {course_id}"
        
        units = fetch_from_api(f"api/v1/courses/{course_id}/units")
        api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
        if units == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
        if not units or not isinstance(units, list) or not units:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"عذراً، لا توجد وحدات متاحة حالياً للمقرر \"{context.user_data['selected_course_name_for_unit_quiz']}\" أو حدث خطأ في جلبها.", reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
        
        context.user_data["available_units_for_course"] = units
        context.user_data["current_unit_page_for_course"] = 0
        keyboard = create_unit_selection_keyboard(units, course_id, 0)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية من مقرر \"{context.user_data['selected_course_name_for_unit_quiz']}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    return SELECT_COURSE_FOR_UNIT_QUIZ 

async def select_unit_for_course(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data
    course_id = context.user_data.get("selected_course_id_for_unit_quiz")
    units = context.user_data.get("available_units_for_course", [])
    current_page = context.user_data.get("current_unit_page_for_course", 0)

    if callback_data == "quiz_unit_back_to_course_selection":
        all_courses = context.user_data.get("available_courses_for_unit_quiz", [])
        course_page = context.user_data.get("current_course_page_for_unit_quiz", 0)
        keyboard = create_course_selection_keyboard(all_courses, course_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="اختر المقرر الدراسي:", reply_markup=keyboard)
        return SELECT_COURSE_FOR_UNIT_QUIZ

    if callback_data.startswith("quiz_unit_page_"):
        parts = callback_data.split("_")
        # c_id = parts[-2] # course_id from callback, ensure it matches context if needed
        new_page = int(parts[-1])
        context.user_data["current_unit_page_for_course"] = new_page
        keyboard = create_unit_selection_keyboard(units, course_id, new_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية من مقرر \"{context.user_data.get('selected_course_name_for_unit_quiz', '')}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data.startswith("quiz_unit_select_"):
        parts = callback_data.split("_")
        # c_id = parts[-2] # course_id from callback
        unit_id = parts[-1]
        context.user_data["selected_unit_id"] = unit_id
        selected_unit = next((u for u in units if str(u.get("id")) == str(unit_id)), None)
        unit_name = selected_unit.get("name", f"وحدة {unit_id}") if selected_unit else f"وحدة {unit_id}"
        context.user_data["selected_unit_name"] = unit_name
        quiz_type_key = context.user_data.get("selected_quiz_type_key", QUIZ_TYPE_UNIT) 
        quiz_type_display_name = context.user_data.get("selected_quiz_type_display_name", "اختبار الوحدة")
        
        questions_for_unit = fetch_from_api(f"api/v1/units/{unit_id}/questions")
        api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
        if questions_for_unit == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_unit_selection_keyboard(units, course_id, current_page))
            return SELECT_UNIT_FOR_COURSE
        if not questions_for_unit or not isinstance(questions_for_unit, list) or not questions_for_unit:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"عذراً، لا توجد أسئلة متاحة حالياً للوحدة \"{unit_name}\".", reply_markup=create_unit_selection_keyboard(units, course_id, current_page))
            return SELECT_UNIT_FOR_COURSE

        context.user_data[f"quiz_setup_{quiz_type_key}_{unit_id}"] = {
            "questions": questions_for_unit,
            "quiz_name": f"{quiz_type_display_name}: {unit_name}"
        }
        max_questions = len(questions_for_unit)
        keyboard = create_question_count_keyboard(max_questions, quiz_type_key, unit_id=unit_id, course_id_for_unit=course_id)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار \"{unit_name}\" من مقرر \"{context.user_data.get('selected_course_name_for_unit_quiz', '')}\":", reply_markup=keyboard)
        return ENTER_QUESTION_COUNT
    return SELECT_UNIT_FOR_COURSE

async def select_question_count(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data
    quiz_type_key = context.user_data.get("selected_quiz_type_key")
    unit_id = context.user_data.get("selected_unit_id") 
    course_id_for_unit = context.user_data.get("selected_course_id_for_unit_quiz")

    if callback_data.startswith("quiz_count_back_to_unit_selection_"):
        # c_id_from_cb = callback_data.split("_")[-1]
        all_units = context.user_data.get("available_units_for_course", [])
        unit_page = context.user_data.get("current_unit_page_for_course", 0)
        keyboard = create_unit_selection_keyboard(all_units, course_id_for_unit, unit_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية من مقرر \"{context.user_data.get('selected_course_name_for_unit_quiz', '')}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data == "quiz_type_back_to_type_selection":
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    quiz_setup_data_key = f"quiz_setup_{quiz_type_key}_{unit_id if unit_id else 'all'}"
    quiz_setup_data = context.user_data.get(quiz_setup_data_key)

    if not quiz_setup_data or "questions" not in quiz_setup_data:
        logger.error(f"User {user_id}: Quiz setup data not found or invalid for key {quiz_setup_data_key} at select_question_count.")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ في إعداد الاختبار. يرجى المحاولة من البداية.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    all_questions_for_scope = quiz_setup_data["questions"]
    max_questions = len(all_questions_for_scope)
    quiz_name = quiz_setup_data.get("quiz_name", "اختبار")
    quiz_scope_id = unit_id if quiz_type_key == QUIZ_TYPE_UNIT else None # For QUIZ_TYPE_ALL, scope_id is None

    if callback_data.startswith("num_questions_"):
        num_str = callback_data.replace("num_questions_", "", 1)
        if num_str == "all":
            num_questions = max_questions
        else:
            try:
                num_questions = int(num_str)
                if not (0 < num_questions <= max_questions):
                    logger.warning(f"User {user_id} selected invalid num_questions: {num_questions} (max: {max_questions}). Defaulting to max.")
                    num_questions = max_questions
            except ValueError:
                logger.error(f"User {user_id} provided invalid num_questions string: {num_str}. Defaulting to max.")
                num_questions = max_questions
    else:
        logger.warning(f"User {user_id} sent unexpected callback_data at select_question_count: {callback_data}. Defaulting to max questions.")
        num_questions = max_questions

    context.user_data["question_count_for_quiz"] = num_questions
    selected_questions = random.sample(all_questions_for_scope, min(num_questions, max_questions))
    context.user_data["questions_for_quiz"] = selected_questions

    # Attempt to log quiz start to DB and get a session ID
    db_quiz_session_id = None
    try:
        db_quiz_session_id = log_quiz_start(
            user_id=user_id,
            quiz_type=quiz_type_key,
            quiz_name=quiz_name,
            quiz_scope_id=quiz_scope_id, # This is filter_id in some contexts
            total_questions=len(selected_questions) # Log the actual number of questions to be asked
        )
        if db_quiz_session_id:
            context.user_data["db_quiz_session_id"] = db_quiz_session_id
            logger.info(f"User {user_id}: Quiz start logged to DB. Session ID: {db_quiz_session_id}")
        else:
            logger.warning(f"User {user_id}: log_quiz_start did not return a DB session ID. Quiz may not be fully tracked in DB.")
    except Exception as e_log_start:
        logger.error(f"User {user_id}: Error logging quiz start to DB: {e_log_start}", exc_info=True)
    
    # Fallback DB logging (if the main one failed or was skipped)
    if not context.user_data.get("db_quiz_session_id"):
        logger.warning(f"User {user_id}: db_quiz_session_id was not found in context.user_data. Attempting to log quiz start again or this might be an issue.")
        try:
            log_user_activity(
                user_id=user_id,
                action="attempt_fallback_quiz_start_logging", # CORRECTED: Added action argument
                details={
                    "quiz_type": quiz_type_key,
                    "quiz_name": quiz_name,
                    "scope_id": quiz_scope_id,
                    "total_questions_available": max_questions,
                    "selected_question_count": num_questions,
                    "reason": "db_quiz_session_id_missing_before_quiz_logic_init"
                },
                username=query.from_user.username, 
                first_name=query.from_user.first_name
            )
            # This fallback log_user_activity doesn't create a db_quiz_session_id itself.
            # The log_quiz_start above is the one intended for that.
            # This is more for general activity logging if the session creation failed.
        except Exception as e_fallback_log:
            logger.error(f"User {user_id}: Error during fallback DB logging: {e_fallback_log}", exc_info=True)

    # Initialize QuizLogic instance
    quiz_instance_key = f"quiz_instance_{user_id}_{query.message.chat_id}"
    if "quiz_sessions" not in context.user_data: context.user_data["quiz_sessions"] = {}

    current_quiz_id_timestamp = str(datetime.now().timestamp()).replace(".", "")
    quiz_unique_id_for_logic = f"quiz_{user_id}_{current_quiz_id_timestamp}"

    quiz_logic_instance = QuizLogic(
        user_id=user_id, 
        chat_id=query.message.chat_id,
        quiz_type=quiz_type_key, 
        questions_data=selected_questions, 
        total_questions=len(selected_questions),
        question_time_limit=DEFAULT_QUESTION_TIME_LIMIT,
        quiz_id=quiz_unique_id_for_logic, 
        quiz_name=quiz_name,
        db_quiz_session_id=context.user_data.get("db_quiz_session_id") # Pass the DB session ID
    )
    context.user_data["quiz_sessions"][quiz_unique_id_for_logic] = quiz_logic_instance
    context.user_data["current_quiz_id"] = quiz_unique_id_for_logic # Store current quiz ID for easy access

    logger.info(f"User {user_id} starting quiz \'{quiz_name}\' (QuizLogic ID: {quiz_unique_id_for_logic}, DB Session: {context.user_data.get('db_quiz_session_id')}) with {len(selected_questions)} questions.")
    
    # Edit the message to remove buttons before starting the quiz questions
    try:
        await query.edit_message_text(text=f"👍 تم إعداد اختبار \"{quiz_name}\" بـ {len(selected_questions)} أسئلة. الاختبار سيبدأ الآن...")
    except Exception as e_edit:
        logger.warning(f"Could not edit message before starting quiz for user {user_id}: {e_edit}. Sending new message instead.")
        await safe_send_message(context.bot, chat_id=query.message.chat_id, text=f"👍 تم إعداد اختبار \"{quiz_name}\" بـ {len(selected_questions)} أسئلة. الاختبار سيبدأ الآن...")

    return await quiz_logic_instance.start_quiz(context.bot, context, update, user_id)

async def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    current_quiz_id = context.user_data.get("current_quiz_id")
    quiz_sessions = context.user_data.get("quiz_sessions", {})
    quiz_instance = quiz_sessions.get(current_quiz_id) if current_quiz_id else None

    if not quiz_instance or not isinstance(quiz_instance, QuizLogic) or not quiz_instance.active:
        logger.warning(f"User {user_id} answer for inactive/non-existent quiz {current_quiz_id}. Callback: {query.data}")
        try:
            await query.answer(text="هذا الاختبار غير نشط أو قد انتهى. يرجى البدء من جديد.", show_alert=True)
            # Try to clean up and send main menu if message exists
            if query.message:
                main_menu_text = "القائمة الرئيسية:"
                main_menu_keyboard = create_main_menu_keyboard(user_id=user_id) # Ensure create_main_menu_keyboard accepts user_id if needed for admin
                await query.edit_message_text(text=main_menu_text, reply_markup=main_menu_keyboard)
        except Exception as e_edit_inactive:
            logger.error(f"Error editing message for inactive quiz answer: {e_edit_inactive}")
        return ConversationHandler.END # Or appropriate state if you want to redirect differently

    return await quiz_instance.handle_answer(context.bot, context, update)

async def quiz_timeout_callback_external_wrapper(context: CallbackContext):
    job_data = context.job.data
    quiz_id = job_data.get("quiz_id")
    user_id = job_data.get("user_id")
    chat_id = job_data.get("chat_id")
    question_index = job_data.get("question_index")
    message_id = job_data.get("message_id")
    question_was_image = job_data.get("question_was_image", False)

    quiz_sessions = context.chat_data.get("quiz_sessions", {}) # Use chat_data for timers as it's more persistent for jobs
    quiz_instance = quiz_sessions.get(quiz_id) if quiz_id else None

    if quiz_instance and isinstance(quiz_instance, QuizLogic) and quiz_instance.active and quiz_instance.current_question_index == question_index:
        logger.info(f"[QuizLogic Timeout {quiz_id}] Question timeout for user {user_id}, q_idx {question_index}. Calling quiz_instance.handle_timeout.")
        await quiz_instance.handle_timeout(context.bot, context, user_id, chat_id, message_id, question_was_image)
    else:
        logger.warning(f"[QuizLogic Timeout {quiz_id}] No active quiz instance found in chat_data for user {user_id}, chat {chat_id}. Timer job {context.job.name} might be orphaned.")

quiz_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(quiz_menu_entry, pattern="^start_quiz$")],
    states={
        SELECT_QUIZ_TYPE: [CallbackQueryHandler(select_quiz_type)],
        SELECT_COURSE_FOR_UNIT_QUIZ: [CallbackQueryHandler(select_course_for_unit_quiz)],
        SELECT_UNIT_FOR_COURSE: [CallbackQueryHandler(select_unit_for_course)],
        ENTER_QUESTION_COUNT: [CallbackQueryHandler(select_question_count)],
        TAKING_QUIZ: [CallbackQueryHandler(handle_quiz_answer, pattern="^ans_")],
        # SHOWING_RESULTS is handled by QuizLogic internally, then it returns END or MAIN_MENU state value
    },
    fallbacks=[
        CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"),
        CommandHandler("start", start_command_fallback_for_quiz) # Fallback for /start during quiz
    ],
    map_to_parent={
        END: MAIN_MENU, 
        MAIN_MENU: MAIN_MENU 
    },
    per_message=False,
    name="quiz_conversation",
    persistent=True,
    allow_reentry=True 
)

logger.info("Quiz conversation handler (quiz.py) loaded.")

