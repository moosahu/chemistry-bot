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
# from handlers.stats import update_user_stats_in_json # This line can be removed if not used elsewhere
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
    # Call main_menu_callback from common.py to display the main menu
    # This function should handle sending or editing the message to show the main menu keyboard.
    # It's important that main_menu_callback itself doesn't return a state that re-enters a conversation
    # unless that's the explicit intention (e.g., MAIN_MENU state for a top-level conversation).
    # For ending a conversation, it should ultimately lead to ConversationHandler.END for the current conv.
    await main_menu_callback(update, context) # Pass context if needed by main_menu_callback
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
        # This case should ideally not be reached if quiz_type_key is validated from button callbacks
        log_user_activity(user_id=user_id, action="unknown_quiz_type_selected", details={"quiz_type_key": quiz_type_key})
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
        selected_course_id = callback_data.replace("quiz_course_select_", "", 1)
        selected_course = next((c for c in courses if str(c.get("id")) == selected_course_id), None)
        if not selected_course:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، المقرر المختار غير صالح. حاول مرة أخرى.", reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
        
        context.user_data["selected_course_id_for_unit_quiz"] = selected_course_id
        context.user_data["selected_course_name_for_unit_quiz"] = selected_course.get("name", f"مقرر {selected_course_id}")
        
        units = fetch_from_api(f"api/v1/courses/{selected_course_id}/units")
        if units == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً.", reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
        if not units or not isinstance(units, list) or not units:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"عذراً، لا توجد وحدات متاحة حالياً للمقرر \"{selected_course.get('name')}\" أو حدث خطأ في جلبها.", reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ

        context.user_data["available_units_for_course"] = units
        context.user_data["current_unit_page_for_course"] = 0
        keyboard = create_unit_selection_keyboard(units, selected_course_id, 0)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية من مقرر \"{selected_course.get('name')}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    else:
        log_user_activity(user_id=user_id, action="unknown_course_selection_callback", details={"callback_data": callback_data})
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="أمر غير معروف. يرجى استخدام الأزرار.", reply_markup=create_course_selection_keyboard(courses, current_page))
        return SELECT_COURSE_FOR_UNIT_QUIZ

async def select_unit_for_course(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data
    
    selected_course_id = context.user_data.get("selected_course_id_for_unit_quiz")
    selected_course_name = context.user_data.get("selected_course_name_for_unit_quiz", f"مقرر {selected_course_id}")
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
        # course_id_from_cb = parts[3] # Not strictly needed if selected_course_id is reliable from context
        new_page = int(parts[-1])
        context.user_data["current_unit_page_for_course"] = new_page
        keyboard = create_unit_selection_keyboard(units, selected_course_id, new_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية من مقرر \"{selected_course_name}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data.startswith("quiz_unit_select_"):
        parts = callback_data.split("_")
        # course_id_from_cb = parts[3]
        selected_unit_id = parts[-1]
        selected_unit = next((u for u in units if str(u.get("id")) == selected_unit_id), None)
        
        if not selected_unit:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، الوحدة المختارة غير صالحة. حاول مرة أخرى.", reply_markup=create_unit_selection_keyboard(units, selected_course_id, current_page))
            return SELECT_UNIT_FOR_COURSE

        context.user_data["selected_unit_id"] = selected_unit_id
        selected_unit_name = selected_unit.get("name", f"وحدة {selected_unit_id}")
        context.user_data["selected_unit_name"] = selected_unit_name
        quiz_name = f"{selected_course_name} - {selected_unit_name}"

        questions = fetch_from_api(f"api/v1/units/{selected_unit_id}/questions")
        if questions == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً.", reply_markup=create_unit_selection_keyboard(units, selected_course_id, current_page))
            return SELECT_UNIT_FOR_COURSE
        if not questions or not isinstance(questions, list) or not questions:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"عذراً، لا توجد أسئلة متاحة حالياً للوحدة \"{selected_unit_name}\".", reply_markup=create_unit_selection_keyboard(units, selected_course_id, current_page))
            return SELECT_UNIT_FOR_COURSE
        
        context.user_data[f"quiz_setup_{context.user_data['selected_quiz_type_key']}_{selected_unit_id}"] = {
            "questions": questions,
            "quiz_name": quiz_name
        }
        max_questions = len(questions)
        keyboard = create_question_count_keyboard(max_questions, context.user_data['selected_quiz_type_key'], selected_unit_id, selected_course_id)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار \n\"{quiz_name}\":", reply_markup=keyboard)
        return ENTER_QUESTION_COUNT
    else:
        log_user_activity(user_id=user_id, action="unknown_unit_selection_callback", details={"callback_data": callback_data})
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="أمر غير معروف. يرجى استخدام الأزرار.", reply_markup=create_unit_selection_keyboard(units, selected_course_id, current_page))
        return SELECT_UNIT_FOR_COURSE

async def select_question_count(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data

    quiz_type = context.user_data.get("selected_quiz_type_key")
    unit_id = context.user_data.get("selected_unit_id") # This will be 'all' for QUIZ_TYPE_ALL
    course_id_for_unit = context.user_data.get("selected_course_id_for_unit_quiz") # Only for QUIZ_TYPE_UNIT

    if callback_data.startswith("quiz_count_back_to_unit_selection_"):
        # This callback includes the course_id: quiz_count_back_to_unit_selection_{course_id}
        # We need to re-fetch units for that course and display unit selection.
        # course_id_from_cb = callback_data.split("_")[-1] # Not strictly needed if context is reliable
        
        # Retrieve necessary context for going back to unit selection
        # selected_course_id = context.user_data.get("selected_course_id_for_unit_quiz")
        # selected_course_name = context.user_data.get("selected_course_name_for_unit_quiz", f"مقرر {selected_course_id}")
        # units_for_course = context.user_data.get("available_units_for_course", [])
        # current_unit_page = context.user_data.get("current_unit_page_for_course", 0)

        # For simplicity, let's assume context.user_data has what create_unit_selection_keyboard needs
        # or that select_unit_for_course can reconstruct it if we return SELECT_UNIT_FOR_COURSE.
        # However, the direct way is to call the function that shows the unit selection again.
        # We need to ensure that `selected_course_id_for_unit_quiz` is still in context.
        if not course_id_for_unit:
            logger.error(f"User {user_id}: Cannot go back to unit selection, course_id_for_unit is missing from context.")
            # Fallback to type selection if course context is lost
            keyboard = create_quiz_type_keyboard()
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ، فضلاً اختر نوع الاختبار مرة أخرى:", reply_markup=keyboard)
            return SELECT_QUIZ_TYPE

        units = context.user_data.get("available_units_for_course", []) # Should have been fetched before
        current_unit_page = context.user_data.get("current_unit_page_for_course", 0)
        selected_course_name = context.user_data.get("selected_course_name_for_unit_quiz", f"مقرر {course_id_for_unit}")
        
        keyboard = create_unit_selection_keyboard(units, course_id_for_unit, current_unit_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية من مقرر \"{selected_course_name}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
        
    elif callback_data == "quiz_type_back_to_type_selection":
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    quiz_setup_data_key = f"quiz_setup_{quiz_type}_{unit_id}"
    quiz_data = context.user_data.get(quiz_setup_data_key)

    if not quiz_data or "questions" not in quiz_data:
        logger.error(f"User {user_id}: Quiz data or questions not found in context for key {quiz_setup_data_key}. Returning to type selection.")
        log_user_activity(user_id=user_id, action="quiz_data_missing_at_count_selection", details={"quiz_setup_key": quiz_setup_data_key})
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، حدث خطأ في إعداد الاختبار. يرجى المحاولة مرة أخرى.", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    all_questions = quiz_data["questions"]
    quiz_name = quiz_data.get("quiz_name", "اختبار")
    max_questions = len(all_questions)

    if callback_data == "num_questions_all":
        num_questions = max_questions
    elif callback_data.startswith("num_questions_"):
        try:
            num_questions = int(callback_data.replace("num_questions_", ""))
            if not (0 < num_questions <= max_questions):
                raise ValueError("Invalid number of questions selected.")
        except ValueError:
            logger.warning(f"User {user_id} selected invalid number of questions: {callback_data}")
            log_user_activity(user_id=user_id, action="invalid_question_count_selected", details={"callback_data": callback_data, "max_questions": max_questions})
            keyboard = create_question_count_keyboard(max_questions, quiz_type, unit_id, course_id_for_unit)
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عدد أسئلة غير صالح. يرجى الاختيار من القائمة.", reply_markup=keyboard)
            return ENTER_QUESTION_COUNT
    else:
        logger.warning(f"User {user_id} sent unknown callback for question count: {callback_data}")
        # Log this unexpected callback
        log_user_activity(user_id=user_id, action="unknown_question_count_callback", details={"callback_data": callback_data})
        keyboard = create_question_count_keyboard(max_questions, quiz_type, unit_id, course_id_for_unit)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="أمر غير معروف. يرجى استخدام الأزرار.", reply_markup=keyboard)
        return ENTER_QUESTION_COUNT

    context.user_data["question_count_for_quiz"] = num_questions
    questions_for_quiz = random.sample(all_questions, min(num_questions, max_questions))
    context.user_data["questions_for_quiz"] = questions_for_quiz

    # --- POSTGRESQL DATABASE LOGGING --- 
    # Log quiz start to the database and get the quiz_session_id
    # Ensure quiz_name, quiz_type, unit_id (if applicable), course_id (if applicable) are passed
    db_quiz_session_id = None
    try:
        db_quiz_session_id = log_quiz_start(
            user_id=user_id,
            quiz_name=quiz_name,
            quiz_type=quiz_type,
            total_questions=len(questions_for_quiz),
            course_id=course_id_for_unit, # Will be None if not QUIZ_TYPE_UNIT
            unit_id=unit_id if quiz_type == QUIZ_TYPE_UNIT else None # Pass unit_id only for unit quizzes
        )
        if db_quiz_session_id:
            context.user_data["db_quiz_session_id"] = db_quiz_session_id
            logger.info(f"User {user_id} started quiz. DB Session ID: {db_quiz_session_id}")
        else:
            logger.error(f"User {user_id} started quiz, but failed to get DB Session ID from log_quiz_start.")
            log_user_activity(user_id=user_id, action="quiz_start_db_session_id_failed", details={"quiz_name": quiz_name, "quiz_type": quiz_type})
    except Exception as e_log_start:
        logger.error(f"Error logging quiz start to DB for user {user_id}: {e_log_start}")
        log_user_activity(user_id=user_id, action="quiz_start_db_logging_exception", details={"error": str(e_log_start)})
    # -----------------------------------

    # Generate a unique quiz_id for this specific quiz instance
    # This quiz_id is for the QuizLogic instance and timer jobs, distinct from db_quiz_session_id
    quiz_instance_id = f"{user_id}_{query.message.chat_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    context.user_data["quiz_instance_id"] = quiz_instance_id

    quiz_logic = QuizLogic(
        user_id=user_id,
        chat_id=query.message.chat_id,
        questions=questions_for_quiz,
        quiz_name=quiz_name,
        quiz_type=quiz_type,
        quiz_instance_id=quiz_instance_id, # Pass the unique instance ID
        db_quiz_session_id=db_quiz_session_id # Pass the DB session ID
    )
    
    # Store the QuizLogic instance in a dictionary keyed by quiz_instance_id
    if "quiz_sessions" not in context.user_data:
        context.user_data["quiz_sessions"] = {}
    context.user_data["quiz_sessions"][quiz_instance_id] = quiz_logic
    
    logger.info(f"User {user_id} starting quiz \"{quiz_name}\" (Type: {quiz_type}, Unit: {unit_id}, Course: {course_id_for_unit}) with {len(questions_for_quiz)} questions. Instance ID: {quiz_instance_id}")
    await quiz_logic.send_question(context.bot, query.message.message_id, context)
    return TAKING_QUIZ

async def process_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    quiz_instance_id = context.user_data.get("quiz_instance_id")

    if not quiz_instance_id or quiz_instance_id not in context.user_data.get("quiz_sessions", {}):
        logger.warning(f"User {user_id} tried to answer, but no active quiz instance found for ID {quiz_instance_id}. Callback: {query.data}")
        await query.answer("عذراً، يبدو أن هذا الاختبار لم يعد نشطاً أو انتهت صلاحيته.")
        # Attempt to show main menu if quiz is truly gone
        # Check if the message still exists before trying to edit
        if query.message:
             await main_menu_callback(update, context)
        return ConversationHandler.END

    quiz_logic = context.user_data["quiz_sessions"][quiz_instance_id]
    
    # Extract quiz_id_from_callback if it's part of the answer callback, e.g., "quiz_answer_QUIZID_QID_AID"
    # This is crucial if multiple quizzes could be active, though current design is one per user_data instance.
    # For now, we rely on quiz_instance_id from context.user_data.
    
    # Ensure the callback is for the current active quiz instance
    # Example: if query.data is like "quiz_answer_THIS_QUIZ_INSTANCE_ID_q1_opt0"
    # parts = query.data.split("_")
    # if len(parts) > 2 and parts[2] != quiz_instance_id:
    #     logger.warning(f"User {user_id} answered for quiz {parts[2]} but current active is {quiz_instance_id}. Ignoring.")
    #     await query.answer("إجابة لاختبار مختلف. هذا الاختبار هو النشط.")
    #     return TAKING_QUIZ # Stay in current state

    return await quiz_logic.process_user_answer(context.bot, query, context)

async def next_question_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    quiz_instance_id = context.user_data.get("quiz_instance_id")

    if not quiz_instance_id or quiz_instance_id not in context.user_data.get("quiz_sessions", {}):
        logger.warning(f"User {user_id} tried next_question, but no active quiz instance found for ID {quiz_instance_id}.")
        await query.answer("عذراً، يبدو أن هذا الاختبار لم يعد نشطاً.")
        if query.message:
            await main_menu_callback(update, context)
        return ConversationHandler.END
        
    quiz_logic = context.user_data["quiz_sessions"][quiz_instance_id]
    return await quiz_logic.send_question(context.bot, query.message.message_id, context, is_next_command=True)

async def prev_question_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    quiz_instance_id = context.user_data.get("quiz_instance_id")

    if not quiz_instance_id or quiz_instance_id not in context.user_data.get("quiz_sessions", {}):
        logger.warning(f"User {user_id} tried prev_question, but no active quiz instance found for ID {quiz_instance_id}.")
        await query.answer("عذراً، يبدو أن هذا الاختبار لم يعد نشطاً.")
        if query.message:
            await main_menu_callback(update, context)
        return ConversationHandler.END

    quiz_logic = context.user_data["quiz_sessions"][quiz_instance_id]
    return await quiz_logic.show_specific_question(context.bot, query.message.message_id, context, quiz_logic.current_question_index - 1)

async def end_quiz_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    quiz_instance_id = context.user_data.get("quiz_instance_id")

    if not quiz_instance_id or quiz_instance_id not in context.user_data.get("quiz_sessions", {}):
        logger.warning(f"User {user_id} tried end_quiz, but no active quiz instance found for ID {quiz_instance_id}.")
        await query.answer("عذراً، يبدو أن هذا الاختبار لم يعد نشطاً أو قد انتهى بالفعل.")
        if query.message:
            await main_menu_callback(update, context)
        return ConversationHandler.END

    quiz_logic = context.user_data["quiz_sessions"][quiz_instance_id]
    return await quiz_logic.end_quiz(context.bot, context, update, manual_end=True)

async def toggle_bookmark_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    quiz_instance_id = context.user_data.get("quiz_instance_id")

    if not quiz_instance_id or quiz_instance_id not in context.user_data.get("quiz_sessions", {}):
        logger.warning(f"User {user_id} tried toggle_bookmark, but no active quiz instance found for ID {quiz_instance_id}.")
        await query.answer("عذراً، لا يمكن تعديل العلامة المرجعية لاختبار غير نشط.")
        return TAKING_QUIZ # Or END if appropriate

    quiz_logic = context.user_data["quiz_sessions"][quiz_instance_id]
    return await quiz_logic.toggle_bookmark(context.bot, query, context)

async def auto_end_quiz_job(context: CallbackContext):
    """Job to automatically end a quiz after a timeout if not completed."""
    job_context = context.job.data
    user_id = job_context.get("user_id")
    chat_id = job_context.get("chat_id")
    quiz_instance_id = job_context.get("quiz_instance_id")
    quiz_message_id_to_edit = job_context.get("quiz_message_id_to_edit")

    logger.info(f"Auto-end job triggered for quiz {quiz_instance_id} for user {user_id} in chat {chat_id}.")

    # Access the specific quiz instance from the shared context.user_data["quiz_sessions"]
    # We need to pass the main bot's context.user_data to the job if it runs in a different context scope,
    # or ensure the job has access to the same context.user_data.
    # For PTB v20+, context in job is the application.bot_data or chat_data or user_data directly.
    # Let's assume context.user_data is accessible and shared.

    if quiz_instance_id and quiz_instance_id in context.user_data.get("quiz_sessions", {}):
        quiz_logic = context.user_data["quiz_sessions"][quiz_instance_id]
        if quiz_logic.active:
            logger.info(f"Quiz {quiz_instance_id} is still active. Ending it due to overall timeout.")
            # Construct a dummy Update object or pass necessary info if end_quiz expects it
            # For now, end_quiz is adapted to handle being called from a job
            await quiz_logic.end_quiz(context.bot, context, update=None, manual_end=False, reason_suffix="overall_timeout_job", quiz_message_id_override=quiz_message_id_to_edit)
        else:
            logger.info(f"Quiz {quiz_instance_id} was already inactive when auto-end job ran.")
            # Ensure cleanup if it was missed
            if quiz_instance_id in context.user_data.get("quiz_sessions", {}):
                # Minimal cleanup if instance is gone or inactive
                context.user_data["quiz_sessions"].pop(quiz_instance_id, None)
                if not context.user_data["quiz_sessions"]:
                    context.user_data.pop("quiz_sessions", None)
                logger.info(f"Performed minimal cleanup for quiz {quiz_instance_id} during timeout as it was already inactive/gone.")
    else:
        logger.warning(f"Auto-end job for quiz {quiz_instance_id} for user {user_id}: Quiz instance not found or already cleaned up.")

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
        CallbackQueryHandler(quiz_menu_entry, pattern="^start_quiz$")  # MODIFIED HERE
    ],
    states={
        SELECT_QUIZ_TYPE: [
            CallbackQueryHandler(select_quiz_type, pattern=f"^quiz_type_({QUIZ_TYPE_ALL}|{QUIZ_TYPE_UNIT})$"),
            CallbackQueryHandler(main_menu_callback, pattern="^main_menu$") 
        ],
        SELECT_COURSE_FOR_UNIT_QUIZ: [
            CallbackQueryHandler(select_course_for_unit_quiz, pattern=f"^quiz_course_select_\d+$"),
            CallbackQueryHandler(select_course_for_unit_quiz, pattern=f"^quiz_course_page_\d+$"),
            CallbackQueryHandler(select_quiz_type, pattern="^quiz_type_back_to_type_selection$") 
        ],
        SELECT_UNIT_FOR_COURSE: [
            CallbackQueryHandler(select_unit_for_course, pattern=f"^quiz_unit_select_\d+_\d+$"),
            CallbackQueryHandler(select_unit_for_course, pattern=f"^quiz_unit_page_\d+_\d+$"),
            CallbackQueryHandler(select_course_for_unit_quiz, pattern="^quiz_unit_back_to_course_selection$") 
        ],
        ENTER_QUESTION_COUNT: [
            CallbackQueryHandler(select_question_count, pattern=f"^num_questions_(\d+|all)$"),
            CallbackQueryHandler(select_unit_for_course, pattern=f"^quiz_count_back_to_unit_selection_\d+$"), 
            CallbackQueryHandler(select_quiz_type, pattern="^quiz_type_back_to_type_selection$") 
        ],
        TAKING_QUIZ: [
            CallbackQueryHandler(process_answer, pattern=f"^quiz_answer_.+$"), 
            CallbackQueryHandler(next_question_callback, pattern=f"^quiz_next_question_.+$"),
            CallbackQueryHandler(prev_question_callback, pattern=f"^quiz_prev_question_.+$"),
            CallbackQueryHandler(end_quiz_callback, pattern=f"^quiz_end_quiz_.+$"),
            CallbackQueryHandler(toggle_bookmark_callback, pattern=f"^quiz_toggle_bookmark_.+$")
        ],
    },
    fallbacks=[
        CommandHandler("start", start_command_fallback_for_quiz),
        CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"), # MODIFIED HERE
        CallbackQueryHandler(unhandled_quiz_callback) 
    ],
    map_to_parent={
        ConversationHandler.END: ConversationHandler.END 
    },
    per_message=False, 
    name="quiz_conversation_handler",
    persistent=True, 
)

