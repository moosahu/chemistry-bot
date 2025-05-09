"""
Conversation handler for the quiz selection and execution flow (PARAM FIXES APPLIED).
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
# Ensure correct import for main_menu_callback and start_command if they are in common.py
from handlers.common import main_menu_callback, start_command 
from .quiz_logic import QuizLogic, question_timeout_callback_wrapper 

# --- POSTGRESQL DATABASE LOGGING ---
try:
    from database.data_logger import log_user_activity, log_quiz_start
except ImportError as e:
    logger.error(f"CRITICAL: Could not import from database.data_logger: {e}.")
    def log_user_activity(*args, **kwargs): logger.error("Dummy log_user_activity called."); pass
    def log_quiz_start(*args, **kwargs): logger.error("Dummy log_quiz_start called."); return None
# -----------------------------------

ITEMS_PER_PAGE = 6

async def start_command_fallback_for_quiz(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} sent /start during quiz_conv. Ending quiz_conv, showing main menu.")
    
    # Cleanup quiz instance if exists
    quiz_instance_key = f"quiz_instance_{user_id}_{update.effective_chat.id}" # Example key
    if quiz_instance_key in context.user_data:
        quiz_instance = context.user_data[quiz_instance_key]
        if isinstance(quiz_instance, QuizLogic) and quiz_instance.active:
            await quiz_instance.end_quiz(context.bot, context, update, manual_end=True, reason_suffix="start_fallback_quiz_handler", called_from_fallback=True)
        del context.user_data[quiz_instance_key]

    # Clear other quiz-related data
    keys_to_pop = [
        "selected_quiz_type_key", "selected_quiz_type_display_name", "questions_for_quiz",
        "selected_course_id_for_unit_quiz", "available_courses_for_unit_quiz",
        "current_course_page_for_unit_quiz", "selected_course_name_for_unit_quiz",
        "available_units_for_course", "current_unit_page_for_course",
        "selected_unit_id", "selected_unit_name", "question_count_for_quiz",
        "db_quiz_session_id"
    ]
    for key in keys_to_pop:
        context.user_data.pop(key, None)
    for key in list(context.user_data.keys()): # Clean up any other quiz_setup or qtimer keys
        if key.startswith("quiz_setup_") or key.startswith("qtimer_"):
            context.user_data.pop(key, None)

    await start_command(update, context) # Show main menu using the function from common.py
    return ConversationHandler.END

async def go_to_main_menu_from_quiz(update: Update, context: CallbackContext) -> int:
    logger.info(f"User {update.effective_user.id} chose to go to main menu from quiz conversation.")
    await main_menu_callback(update, context) # This should display the main menu
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
        "db_quiz_session_id"
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
        return await go_to_main_menu_from_quiz(update, context)
        
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
            # Fallback: try fetching from courses if /all fails or returns non-list
            courses = fetch_from_api("api/v1/courses")
            if courses == "TIMEOUT":
                await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_quiz_type_keyboard())
                return SELECT_QUIZ_TYPE
            if not courses or not isinstance(courses, list):
                await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=error_message_to_user, reply_markup=create_quiz_type_keyboard())
                return SELECT_QUIZ_TYPE
            all_questions_pool = []
            for course in courses:
                course_id_val = course.get("id") # Renamed to avoid conflict
                if not course_id_val: continue
                current_course_questions = fetch_from_api(f"api/v1/courses/{course_id_val}/questions")
                if current_course_questions == "TIMEOUT": continue 
                if isinstance(current_course_questions, list):
                    all_questions_pool.extend(current_course_questions)
        
        if not all_questions_pool: # Check after attempting all fetches
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لم يتم العثور على أسئلة للاختبار الشامل.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
            
        context.user_data[f"quiz_setup_{quiz_type_key}_all"] = {
            "questions": all_questions_pool,
            "quiz_name": quiz_type_display_name,
            "scope_id": "all" # Explicitly set scope_id for QUIZ_TYPE_ALL
        }
        context.user_data["selected_unit_id"] = "all" 
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
        selected_course_id = callback_data.replace("quiz_course_select_", "", 1)
        context.user_data["selected_course_id_for_unit_quiz"] = selected_course_id
        selected_course = next((c for c in courses if str(c.get("id")) == str(selected_course_id)), None)
        context.user_data["selected_course_name_for_unit_quiz"] = selected_course.get("name", "المقرر المحدد") if selected_course else "مقرر غير معروف"
        
        units = fetch_from_api(f"api/v1/courses/{selected_course_id}/units")
        api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
        if units == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
        if not units or not isinstance(units, list) or not units:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"عذراً، لا توجد وحدات متاحة حالياً للمقرر \"{context.user_data['selected_course_name_for_unit_quiz']}\" أو حدث خطأ في جلبها.", reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
        context.user_data["available_units_for_course"] = units
        context.user_data["current_unit_page_for_course"] = 0
        keyboard = create_unit_selection_keyboard(units, selected_course_id, 0)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية من مقرر \"{context.user_data['selected_course_name_for_unit_quiz']}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    return SELECT_COURSE_FOR_UNIT_QUIZ # Fallback

async def select_unit_for_course(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data
    units = context.user_data.get("available_units_for_course", [])
    current_page = context.user_data.get("current_unit_page_for_course", 0)
    selected_course_id = context.user_data.get("selected_course_id_for_unit_quiz")
    selected_course_name = context.user_data.get("selected_course_name_for_unit_quiz", "المقرر المحدد")

    if callback_data == "quiz_unit_back_to_course_selection":
        all_courses = context.user_data.get("available_courses_for_unit_quiz", [])
        course_page = context.user_data.get("current_course_page_for_unit_quiz", 0)
        keyboard = create_course_selection_keyboard(all_courses, course_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="اختر المقرر الدراسي:", reply_markup=keyboard)
        return SELECT_COURSE_FOR_UNIT_QUIZ

    if callback_data.startswith("quiz_unit_page_"):
        parts = callback_data.split("_")
        new_page = int(parts[-1])
        # course_id_from_cb = parts[-2] # Not strictly needed if selected_course_id is reliable from user_data
        context.user_data["current_unit_page_for_course"] = new_page
        keyboard = create_unit_selection_keyboard(units, selected_course_id, new_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية من مقرر \"{selected_course_name}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data.startswith("quiz_unit_select_"):
        parts = callback_data.split("_")
        selected_unit_id = parts[-1]
        # course_id_from_cb = parts[-2] # Could verify against selected_course_id
        context.user_data["selected_unit_id"] = selected_unit_id
        selected_unit = next((u for u in units if str(u.get("id")) == str(selected_unit_id)), None)
        selected_unit_name = selected_unit.get("name", f"وحدة {selected_unit_id}") if selected_unit else f"وحدة {selected_unit_id}"
        context.user_data["selected_unit_name"] = selected_unit_name

        questions_for_unit = fetch_from_api(f"api/v1/units/{selected_unit_id}/questions")
        api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
        if questions_for_unit == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_unit_selection_keyboard(units, selected_course_id, current_page))
            return SELECT_UNIT_FOR_COURSE
        if not questions_for_unit or not isinstance(questions_for_unit, list) or not questions_for_unit:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"عذراً، لا توجد أسئلة متاحة حالياً للوحدة \"{selected_unit_name}\" أو حدث خطأ في جلبها.", reply_markup=create_unit_selection_keyboard(units, selected_course_id, current_page))
            return SELECT_UNIT_FOR_COURSE
        
        quiz_type_key = context.user_data.get("selected_quiz_type_key", QUIZ_TYPE_UNIT)
        quiz_name = f"{selected_course_name} - {selected_unit_name}"
        context.user_data[f"quiz_setup_{quiz_type_key}_{selected_unit_id}"] = {
            "questions": questions_for_unit,
            "quiz_name": quiz_name,
            "scope_id": selected_unit_id # Store the unit_id as scope_id
        }
        max_questions = len(questions_for_unit)
        keyboard = create_question_count_keyboard(max_questions, quiz_type_key, unit_id=selected_unit_id, course_id_for_unit=selected_course_id)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار وحدة \n\"{selected_unit_name}\" من مقرر \"{selected_course_name}\":", reply_markup=keyboard)
        return ENTER_QUESTION_COUNT
    return SELECT_UNIT_FOR_COURSE # Fallback

async def select_question_count(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    callback_data = query.data

    quiz_type_key = context.user_data.get("selected_quiz_type_key")
    selected_unit_id = context.user_data.get("selected_unit_id") # This will be 'all' for QUIZ_TYPE_ALL
    selected_course_id_for_unit = context.user_data.get("selected_course_id_for_unit_quiz") # For back button context

    # Determine the key for quiz_setup_data based on quiz_type and scope (unit_id or 'all')
    quiz_setup_data_key = f"quiz_setup_{quiz_type_key}_{selected_unit_id}"
    quiz_setup_data = context.user_data.get(quiz_setup_data_key, {})
    questions_to_use_pool = quiz_setup_data.get("questions", [])
    quiz_name = quiz_setup_data.get("quiz_name", "اختبار")
    # Scope ID for logging: unit_id if unit quiz, None if 'all' (or handle 'all' as a special case if DB needs it)
    quiz_scope_id_for_log = selected_unit_id if selected_unit_id != "all" else None 
    # If your DB expects an integer or NULL, ensure conversion if selected_unit_id can be non-integer string other than 'all'
    if isinstance(quiz_scope_id_for_log, str) and quiz_scope_id_for_log.isdigit():
        quiz_scope_id_for_log = int(quiz_scope_id_for_log)
    elif quiz_scope_id_for_log is not None: # If it's a non-digit string (and not 'all' which became None)
        logger.warning(f"quiz_scope_id_for_log is a non-digit string: {quiz_scope_id_for_log}. Setting to None for DB logging.")
        quiz_scope_id_for_log = None # Or handle as error

    if callback_data.startswith("quiz_count_back_to_unit_selection_"):
        course_id_from_cb = callback_data.replace("quiz_count_back_to_unit_selection_", "", 1)
        units_for_course = context.user_data.get("available_units_for_course", [])
        unit_page = context.user_data.get("current_unit_page_for_course", 0)
        course_name = context.user_data.get("selected_course_name_for_unit_quiz", "المقرر المحدد")
        keyboard = create_unit_selection_keyboard(units_for_course, course_id_from_cb, unit_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية من مقرر \"{course_name}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data == "quiz_type_back_to_type_selection":
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    if not questions_to_use_pool:
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذرًا، لا توجد أسئلة متاحة لهذا الاختيار. يرجى الرجوع واختيار نوع آخر.", reply_markup=create_quiz_type_keyboard())
        log_user_activity(user_id, action="quiz_start_failed_no_questions", details={"quiz_type": quiz_type_key, "unit_id": selected_unit_id})
        return SELECT_QUIZ_TYPE

    actual_question_count = 0
    if callback_data == "num_questions_all":
        actual_question_count = len(questions_to_use_pool)
    elif callback_data.startswith("num_questions_"):
        try:
            actual_question_count = int(callback_data.replace("num_questions_", "", 1))
        except ValueError:
            await query.message.reply_text("عدد أسئلة غير صالح. يرجى المحاولة مرة أخرى.")
            return ENTER_QUESTION_COUNT
    
    if actual_question_count <= 0 or actual_question_count > len(questions_to_use_pool):
        await query.message.reply_text(f"الرجاء اختيار عدد أسئلة صالح (حتى {len(questions_to_use_pool)}).")
        # Re-show question count keyboard
        keyboard = create_question_count_keyboard(len(questions_to_use_pool), quiz_type_key, unit_id=selected_unit_id, course_id_for_unit=selected_course_id_for_unit)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="اختر عدد الأسئلة:", reply_markup=keyboard)
        return ENTER_QUESTION_COUNT

    context.user_data["question_count_for_quiz"] = actual_question_count
    questions_for_this_quiz = random.sample(questions_to_use_pool, actual_question_count)

    # Log quiz start to database and get DB session ID
    # CORRECTED log_quiz_start call
    db_session_id = await log_quiz_start(
        user_id=user_id,
        quiz_type=quiz_type_key,
        quiz_name=quiz_name,
        quiz_scope_id=quiz_scope_id_for_log, # Pass the processed scope_id
        total_questions=actual_question_count
    )
    if db_session_id:
        context.user_data["db_quiz_session_id"] = db_session_id
        logger.info(f"Quiz started for user {user_id} with DB session ID: {db_session_id}")
    else:
        logger.error(f"Failed to get DB session ID for quiz start for user {user_id}. Quiz will proceed without DB session tracking.")
        context.user_data.pop("db_quiz_session_id", None) # Ensure it's not set if logging failed

    # CORRECTED QuizLogic instantiation
    quiz_instance_id = f"quiz_{user_id}_{chat_id}_{datetime.now().timestamp()}" # Unique ID for the quiz instance
    quiz_logic = QuizLogic(
        user_id=user_id,
        chat_id=chat_id,
        questions_data=questions_for_this_quiz, # CORRECTED parameter name
        quiz_type=quiz_type_key,
        quiz_name=quiz_name,
        quiz_scope_id=quiz_scope_id_for_log, # Pass the processed scope_id
        total_questions=actual_question_count,
        time_limit_per_question=DEFAULT_QUESTION_TIME_LIMIT,
        db_quiz_session_id=context.user_data.get("db_quiz_session_id") # Pass the DB session ID
    )
    context.user_data[quiz_instance_id] = quiz_logic
    context.user_data["current_quiz_instance_id"] = quiz_instance_id # Store current quiz ID

    await quiz_logic.send_question(context.bot, context, update)
    return TAKING_QUIZ

async def handle_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    quiz_instance_id = context.user_data.get("current_quiz_instance_id")

    if not quiz_instance_id or quiz_instance_id not in context.user_data:
        logger.warning(f"User {user_id} tried to answer, but no active quiz instance ID found or instance missing.")
        await query.answer("عذراً، لا يوجد اختبار نشط حالياً أو انتهت صلاحية الجلسة.")
        # Try to send them to the main menu gracefully
        await main_menu_callback(update, context)
        return ConversationHandler.END

    quiz_logic = context.user_data[quiz_instance_id]
    if not isinstance(quiz_logic, QuizLogic) or not quiz_logic.active:
        logger.warning(f"User {user_id} tried to answer, but QuizLogic instance is not valid or inactive.")
        await query.answer("الاختبار لم يعد نشطاً.")
        await main_menu_callback(update, context)
        return ConversationHandler.END

    await quiz_logic.handle_answer(update, context, query)
    if quiz_logic.active:
        return TAKING_QUIZ
    else:
        # Quiz ended, show results (handled by quiz_logic.end_quiz)
        return SHOWING_RESULTS # Or directly END if results are part of TAKING_QUIZ state actions

async def quiz_timeout_fallback(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    logger.info(f"Quiz timeout fallback triggered for user {user_id}.")
    quiz_instance_id = context.user_data.get("current_quiz_instance_id")
    if quiz_instance_id and quiz_instance_id in context.user_data:
        quiz_logic = context.user_data[quiz_instance_id]
        if isinstance(quiz_logic, QuizLogic) and quiz_logic.active:
            # This might be called if a global timeout for the conversation happens
            # or if a specific question timer didn't get handled properly by its own job.
            logger.warning(f"Quiz conversation timeout for user {user_id}. Ending quiz via fallback.")
            await quiz_logic.end_quiz(context.bot, context, update, manual_end=True, reason_suffix="conv_timeout_fallback", called_from_fallback=True)
    else:
        logger.info(f"Quiz timeout fallback for user {user_id}, but no active quiz instance found.")
    
    await safe_send_message(context.bot, update.effective_chat.id, "انتهى الوقت المخصص للاختبار أو حدث خطأ غير متوقع.")
    await main_menu_callback(update, context) # Show main menu
    return ConversationHandler.END

async def skip_question_command(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    quiz_instance_id = context.user_data.get("current_quiz_instance_id")
    if not quiz_instance_id or quiz_instance_id not in context.user_data:
        await update.message.reply_text("لا يوجد اختبار نشط لتخطي سؤال منه.")
        return TAKING_QUIZ # Stay in state or return current state if not part of conv.

    quiz_logic = context.user_data[quiz_instance_id]
    if not isinstance(quiz_logic, QuizLogic) or not quiz_logic.active:
        await update.message.reply_text("الاختبار لم يعد نشطاً.")
        return TAKING_QUIZ

    await quiz_logic.skip_question(context.bot, context, update)
    if quiz_logic.active:
        return TAKING_QUIZ
    else:
        return SHOWING_RESULTS

quiz_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(quiz_menu_entry, pattern="^start_quiz$")],
    states={
        SELECT_QUIZ_TYPE: [CallbackQueryHandler(select_quiz_type)],
        SELECT_COURSE_FOR_UNIT_QUIZ: [CallbackQueryHandler(select_course_for_unit_quiz)],
        SELECT_UNIT_FOR_COURSE: [CallbackQueryHandler(select_unit_for_course)],
        ENTER_QUESTION_COUNT: [CallbackQueryHandler(select_question_count)],
        TAKING_QUIZ: [
            CallbackQueryHandler(handle_answer, pattern="^answer_"),
            CommandHandler("skip", skip_question_command)
        ],
        SHOWING_RESULTS: [
            CallbackQueryHandler(go_to_main_menu_from_quiz, pattern="^main_menu$"), # If results have a main menu button
            CallbackQueryHandler(quiz_menu_entry, pattern="^start_quiz$") # If results have a 
