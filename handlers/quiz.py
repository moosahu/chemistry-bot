"""
Conversation handler for the quiz selection and execution flow.
(DB_MANAGER_PASS_FIX: Passes db_manager instance directly to QuizLogic)
(SHOW_RESULTS_FIX: Ensures last_quiz_interaction_message_id is updated)
"""

import logging
import math # Not used, consider removing
import random
import re # Not used, consider removing
import uuid # For quiz_instance_id
from datetime import datetime
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
from handlers.common import main_menu_callback, start_command 
# Assuming quiz_logic.py will be updated with the content of quiz_logic_DBMANAGER_PASS_FIX.py
from .quiz_logic import QuizLogic, question_timeout_callback_wrapper 

ITEMS_PER_PAGE = 6

async def start_command_fallback_for_quiz(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} sent /start during quiz_conv. Ending quiz_conv, showing main menu.")
    
    current_quiz_instance_id = context.user_data.get("current_quiz_instance_id")
    if current_quiz_instance_id and current_quiz_instance_id in context.user_data:
        quiz_instance = context.user_data.get(current_quiz_instance_id)
        if isinstance(quiz_instance, QuizLogic) and quiz_instance.active:
            await quiz_instance.end_quiz(context.bot, context, update, manual_end=True, reason_suffix="start_fallback_quiz_handler", called_from_fallback=True)
        context.user_data.pop(current_quiz_instance_id, None)
    context.user_data.pop("current_quiz_instance_id", None)

    keys_to_pop = [
        "selected_quiz_type_key", "selected_quiz_type_display_name", "questions_for_quiz",
        "selected_course_id_for_unit_quiz", "available_courses_for_unit_quiz",
        "current_course_page_for_unit_quiz", "selected_course_name_for_unit_quiz",
        "available_units_for_course", "current_unit_page_for_course",
        "selected_unit_id", "selected_unit_name", "question_count_for_quiz"
    ]
    for key in keys_to_pop:
        context.user_data.pop(key, None)
    for key_ud in list(context.user_data.keys()):
        if key_ud.startswith("quiz_setup_") or key_ud.startswith("qtimer_") or key_ud.startswith("last_quiz_interaction_message_id_"):
            context.user_data.pop(key_ud, None)

    await start_command(update, context)
    return ConversationHandler.END

async def go_to_main_menu_from_quiz(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} chose to go to main menu from quiz conversation ({update.callback_query.data if update.callback_query else 'N/A'}). Ending quiz_conv.")
    
    current_quiz_instance_id = context.user_data.get("current_quiz_instance_id")
    if current_quiz_instance_id and current_quiz_instance_id in context.user_data:
        quiz_instance = context.user_data.get(current_quiz_instance_id)
        if isinstance(quiz_instance, QuizLogic) and quiz_instance.active:
            await quiz_instance.end_quiz(context.bot, context, update, manual_end=True, reason_suffix="main_menu_fallback_quiz_handler", called_from_fallback=True)
        context.user_data.pop(current_quiz_instance_id, None)
    context.user_data.pop("current_quiz_instance_id", None)
    
    keys_to_pop = [
        "selected_quiz_type_key", "selected_quiz_type_display_name", "questions_for_quiz",
        "selected_course_id_for_unit_quiz", "available_courses_for_unit_quiz",
        "current_course_page_for_unit_quiz", "selected_course_name_for_unit_quiz",
        "available_units_for_course", "current_unit_page_for_course",
        "selected_unit_id", "selected_unit_name", "question_count_for_quiz"
    ]
    for key in keys_to_pop:
        context.user_data.pop(key, None)
    for key_ud in list(context.user_data.keys()): 
        if key_ud.startswith("quiz_setup_") or key_ud.startswith("qtimer_") or key_ud.startswith("last_quiz_interaction_message_id_"):
            context.user_data.pop(key_ud, None)
            
    await main_menu_callback(update, context)
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
    
    back_callback_data = "quiz_type_back_to_type_selection"
    if quiz_type == QUIZ_TYPE_UNIT:
        if course_id_for_unit and unit_id:
             back_callback_data = f"quiz_count_back_to_unit_selection_{course_id_for_unit}"
        # If only course_id_for_unit is present (e.g. back from unit selection to course selection, then back again)
        # This case is handled by select_unit_for_course setting the correct back target.
        # For question count, if unit_id is not set, it means we are likely in QUIZ_TYPE_ALL or similar.

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
        "current_quiz_instance_id"
    ]
    for key in keys_to_clear_on_entry:
        context.user_data.pop(key, None)
    # Also clear any lingering interaction message ID for this chat
    if query.message:
        context.user_data.pop(f"last_quiz_interaction_message_id_{query.message.chat_id}", None)

    logger.debug(f"Cleared preliminary quiz setup data for user {user_id} at quiz_menu_entry.")
    keyboard = create_quiz_type_keyboard()
    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
    return SELECT_QUIZ_TYPE

async def select_quiz_type(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    callback_data = query.data

    # Store message_id for potential edits
    context.user_data[f"last_quiz_interaction_message_id_{chat_id}"] = query.message.message_id

    if callback_data == "main_menu":
        return await go_to_main_menu_from_quiz(update, context)
        
    if callback_data == "quiz_type_back_to_type_selection": 
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
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
            await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        if not all_questions_pool or not isinstance(all_questions_pool, list):
            courses = fetch_from_api("api/v1/courses")
            if courses == "TIMEOUT":
                await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_quiz_type_keyboard())
                return SELECT_QUIZ_TYPE
            if not courses or not isinstance(courses, list):
                await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text=error_message_to_user, reply_markup=create_quiz_type_keyboard())
                return SELECT_QUIZ_TYPE
            all_questions_pool = []
            for course in courses:
                course_id_val = course.get("id")
                if not course_id_val: continue
                current_course_questions = fetch_from_api(f"api/v1/courses/{course_id_val}/questions")
                if current_course_questions == "TIMEOUT": continue 
                if isinstance(current_course_questions, list):
                    all_questions_pool.extend(current_course_questions)
        
        if not all_questions_pool: 
            await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="عذراً، لم يتم العثور على أسئلة للاختبار الشامل.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
            
        context.user_data[f"quiz_setup_{quiz_type_key}_all"] = {
            "questions": all_questions_pool,
            "quiz_name": quiz_type_display_name,
            "scope_id": "all"
        }
        context.user_data["selected_unit_id"] = "all" 
        max_questions = len(all_questions_pool)
        keyboard = create_question_count_keyboard(max_questions, quiz_type_key, unit_id="all")
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار \n\"{quiz_type_display_name}\":", reply_markup=keyboard)
        return ENTER_QUESTION_COUNT

    elif quiz_type_key == QUIZ_TYPE_UNIT:
        courses = fetch_from_api("api/v1/courses")
        if courses == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        if not courses or not isinstance(courses, list) or not courses:
            await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="عذراً، لا توجد مقررات متاحة حالياً أو حدث خطأ في جلبها.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        context.user_data["available_courses_for_unit_quiz"] = courses
        context.user_data["current_course_page_for_unit_quiz"] = 0
        keyboard = create_course_selection_keyboard(courses, 0)
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="اختر المقرر الدراسي أولاً:", reply_markup=keyboard)
        return SELECT_COURSE_FOR_UNIT_QUIZ
    else:
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="نوع اختبار غير معروف. يرجى الاختيار من القائمة.", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

async def select_course_for_unit_quiz(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    callback_data = query.data
    courses = context.user_data.get("available_courses_for_unit_quiz", [])
    current_page = context.user_data.get("current_course_page_for_unit_quiz", 0)

    # Store message_id for potential edits
    context.user_data[f"last_quiz_interaction_message_id_{chat_id}"] = query.message.message_id

    if callback_data == "quiz_type_back_to_type_selection":
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE
    
    if callback_data.startswith("quiz_course_page_"):
        new_page = int(callback_data.split("_")[-1])
        context.user_data["current_course_page_for_unit_quiz"] = new_page
        keyboard = create_course_selection_keyboard(courses, new_page)
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="اختر المقرر الدراسي:", reply_markup=keyboard)
        return SELECT_COURSE_FOR_UNIT_QUIZ

    if callback_data.startswith("quiz_course_select_"):
        course_id = callback_data.split("_")[-1]
        selected_course = next((c for c in courses if str(c.get("id")) == course_id), None)
        if not selected_course:
            await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="خطأ: لم يتم العثور على المقرر المختار. يرجى المحاولة مرة أخرى.", reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
        
        context.user_data["selected_course_id_for_unit_quiz"] = course_id
        context.user_data["selected_course_name_for_unit_quiz"] = selected_course.get("name", f"مقرر {course_id}")
        
        units = fetch_from_api(f"api/v1/courses/{course_id}/units")
        api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
        if units == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
        if not units or not isinstance(units, list) or not units:
            await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text=f"عذراً، لا توجد وحدات متاحة حالياً للمقرر \"{selected_course.get('name')}\" أو حدث خطأ في جلبها.", reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ

        context.user_data["available_units_for_course"] = units
        context.user_data["current_unit_page_for_course"] = 0
        keyboard = create_unit_selection_keyboard(units, course_id, 0)
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية للمقرر \"{selected_course.get('name')}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    
    return SELECT_COURSE_FOR_UNIT_QUIZ # Fallback

async def select_unit_for_course(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    callback_data = query.data
    
    course_id = context.user_data.get("selected_course_id_for_unit_quiz")
    units = context.user_data.get("available_units_for_course", [])
    current_page = context.user_data.get("current_unit_page_for_course", 0)
    course_name = context.user_data.get("selected_course_name_for_unit_quiz", "المقرر المختار")

    # Store message_id for potential edits
    context.user_data[f"last_quiz_interaction_message_id_{chat_id}"] = query.message.message_id

    if callback_data == "quiz_unit_back_to_course_selection":
        all_courses = context.user_data.get("available_courses_for_unit_quiz", [])
        course_page = context.user_data.get("current_course_page_for_unit_quiz", 0)
        keyboard = create_course_selection_keyboard(all_courses, course_page)
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="اختر المقرر الدراسي:", reply_markup=keyboard)
        return SELECT_COURSE_FOR_UNIT_QUIZ

    if callback_data.startswith("quiz_unit_page_"):
        parts = callback_data.split("_")
        # course_id_from_cb = parts[-2] # Not strictly needed if we rely on context
        new_page = int(parts[-1])
        context.user_data["current_unit_page_for_course"] = new_page
        keyboard = create_unit_selection_keyboard(units, course_id, new_page)
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية للمقرر \"{course_name}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE

    if callback_data.startswith("quiz_unit_select_"):
        parts = callback_data.split("_")
        # course_id_from_cb = parts[-2]
        unit_id = parts[-1]
        selected_unit = next((u for u in units if str(u.get("id")) == unit_id), None)
        if not selected_unit:
            await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="خطأ: لم يتم العثور على الوحدة المختارة. يرجى المحاولة مرة أخرى.", reply_markup=create_unit_selection_keyboard(units, course_id, current_page))
            return SELECT_UNIT_FOR_COURSE

        context.user_data["selected_unit_id"] = unit_id
        context.user_data["selected_unit_name"] = selected_unit.get("name", f"وحدة {unit_id}")
        quiz_type_key = context.user_data.get("selected_quiz_type_key")
        quiz_name_for_display = f"{context.user_data['selected_quiz_type_display_name']}: {course_name} - {selected_unit.get('name')}"

        questions_for_unit = fetch_from_api(f"api/v1/units/{unit_id}/questions")
        api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
        if questions_for_unit == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_unit_selection_keyboard(units, course_id, current_page))
            return SELECT_UNIT_FOR_COURSE
        if not questions_for_unit or not isinstance(questions_for_unit, list) or not questions_for_unit:
            await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text=f"عذراً، لا توجد أسئلة متاحة حالياً للوحدة \"{selected_unit.get('name')}\".", reply_markup=create_unit_selection_keyboard(units, course_id, current_page))
            return SELECT_UNIT_FOR_COURSE

        context.user_data[f"quiz_setup_{quiz_type_key}_{unit_id}"] = {
            "questions": questions_for_unit,
            "quiz_name": quiz_name_for_display,
            "scope_id": unit_id
        }
        max_questions = len(questions_for_unit)
        keyboard = create_question_count_keyboard(max_questions, quiz_type_key, unit_id=unit_id, course_id_for_unit=course_id)
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار \n\"{quiz_name_for_display}\":", reply_markup=keyboard)
        return ENTER_QUESTION_COUNT

    return SELECT_UNIT_FOR_COURSE # Fallback

async def select_question_count(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    callback_data = query.data

    # Store message_id for potential edits
    context.user_data[f"last_quiz_interaction_message_id_{chat_id}"] = query.message.message_id

    quiz_type = context.user_data.get("selected_quiz_type_key")
    unit_id = context.user_data.get("selected_unit_id") # This will be 'all' for QUIZ_TYPE_ALL
    course_id_for_unit = context.user_data.get("selected_course_id_for_unit_quiz")

    if callback_data.startswith("quiz_count_back_to_unit_selection_"):
        # This callback includes course_id, e.g., quiz_count_back_to_unit_selection_COURSEID
        # We need to re-fetch units for that course and display unit selection
        course_id_from_cb = callback_data.split("_")[-1]
        units_for_course = context.user_data.get("available_units_for_course", []) # Should be already fetched
        current_unit_page = context.user_data.get("current_unit_page_for_course", 0)
        course_name = context.user_data.get("selected_course_name_for_unit_quiz", "المقرر المختار")
        keyboard = create_unit_selection_keyboard(units_for_course, course_id_from_cb, current_unit_page)
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية للمقرر \"{course_name}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data == "quiz_type_back_to_type_selection": # General back for QUIZ_TYPE_ALL
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    if not callback_data.startswith("num_questions_"):
        logger.warning(f"User {user_id} sent invalid callback for question count: {callback_data}")
        # Resend the question count keyboard as a fallback
        quiz_setup_key = f"quiz_setup_{quiz_type}_{unit_id}"
        quiz_data = context.user_data.get(quiz_setup_key, {})
        max_q = len(quiz_data.get("questions", []))
        kbd = create_question_count_keyboard(max_q, quiz_type, unit_id, course_id_for_unit)
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "يرجى اختيار عدد الأسئلة من الأزرار.", reply_markup=kbd)
        return ENTER_QUESTION_COUNT

    num_questions_str = callback_data.replace("num_questions_", "", 1)
    quiz_setup_key = f"quiz_setup_{quiz_type}_{unit_id}"
    quiz_data_for_scope = context.user_data.get(quiz_setup_key)

    if not quiz_data_for_scope or not quiz_data_for_scope.get("questions"):
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="عذراً، حدث خطأ في إعداد الأسئلة. يرجى المحاولة من البداية.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    all_questions_for_scope = quiz_data_for_scope["questions"]
    max_questions_available = len(all_questions_for_scope)

    if num_questions_str == "all":
        num_questions_to_ask = max_questions_available
    else:
        try:
            num_questions_to_ask = int(num_questions_str)
            if not (0 < num_questions_to_ask <= max_questions_available):
                num_questions_to_ask = max_questions_available # Default to max if invalid number chosen
        except ValueError:
            logger.error(f"Invalid number for questions: {num_questions_str}")
            num_questions_to_ask = max_questions_available # Default to max

    context.user_data["question_count_for_quiz"] = num_questions_to_ask
    
    # Shuffle and select questions
    random.shuffle(all_questions_for_scope)
    questions_for_this_quiz = all_questions_for_scope[:num_questions_to_ask]
    context.user_data["questions_for_quiz"] = questions_for_this_quiz

    quiz_name_for_display = quiz_data_for_scope.get("quiz_name", context.user_data.get("selected_quiz_type_display_name", "اختبار"))
    quiz_scope_id_for_db = quiz_data_for_scope.get("scope_id", unit_id if unit_id else quiz_type)

    await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text=f"جاري بدء اختبار \"{quiz_name_for_display}\" بـ {num_questions_to_ask} سؤالاً. استعد!", reply_markup=None)
    
    return await start_actual_quiz(update, context, questions_for_this_quiz, num_questions_to_ask, quiz_name_for_display, quiz_type, quiz_scope_id_for_db)

async def start_actual_quiz(update: Update, context: CallbackContext, questions_for_this_quiz: list, num_questions_to_ask: int, quiz_name_for_display: str, quiz_type: str, quiz_scope_id_for_db: str) -> int:
    query = update.callback_query # This comes from select_question_count
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    # Generate a unique ID for this quiz instance
    quiz_instance_id = str(uuid.uuid4())
    logger.info(f"Starting actual quiz. User: {user_id}, QuizName: '{quiz_name_for_display}', Type: {quiz_type}, ScopeID: {quiz_scope_id_for_db}, NumQs: {num_questions_to_ask}, InstanceID: {quiz_instance_id}")

    # Get db_manager instance with fallback and error handling
    db_m_instance = context.bot_data.get("db_manager")
    if not db_m_instance:
        logger.warning(f"db_manager not found in context.bot_data for user {user_id} at start_actual_quiz. Trying context.application.bot_data.")
        db_m_instance = context.application.bot_data.get("db_manager")

    if not db_m_instance:
        logger.critical(f"CRITICAL: db_manager STILL NOT FOUND in context.bot_data or context.application.bot_data at start_actual_quiz for user {user_id}. Quiz stats will NOT be saved.")
        logger.debug(f"Context bot_data keys at failure: {list(context.bot_data.keys()) if context.bot_data else 'None'}")
        logger.debug(f"Context application bot_data keys at failure: {list(context.application.bot_data.keys()) if hasattr(context, 'application') and context.application.bot_data else 'None'}")
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="عذرًا، حدث خطأ في تهيئة الاختبار (DB_INIT_FAIL). يرجى المحاولة لاحقًا أو إبلاغ المشرف.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE
    else:
        logger.info(f"Successfully retrieved db_manager for user {user_id} in start_actual_quiz.")

    # Create QuizLogic instance
    quiz_logic_instance = QuizLogic(
        user_id=user_id,
        chat_id=chat_id,
        questions=questions_for_this_quiz,
        quiz_name=quiz_name_for_display,
        quiz_type_for_db_log=quiz_type,
        quiz_scope_id=quiz_scope_id_for_db,
        total_questions_for_db_log=num_questions_to_ask,
        time_limit_per_question=DEFAULT_QUESTION_TIME_LIMIT,
        quiz_instance_id_for_logging=quiz_instance_id,
        db_manager_instance=db_m_instance  # Use the fetched instance
    )
    context.user_data[quiz_instance_id] = quiz_logic_instance
    context.user_data["current_quiz_instance_id"] = quiz_instance_id
    logger.info(f"QuizLogic instance {quiz_instance_id} created and stored for user {user_id}.")

    # Store the message_id of the interaction that led to starting the quiz (the "جاري بدء اختبار" message)
    if query and query.message:
        context.user_data[f"last_quiz_interaction_message_id_{chat_id}"] = query.message.message_id
        logger.debug(f"Stored last_quiz_interaction_message_id_{chat_id} = {query.message.message_id} in start_actual_quiz from select_question_count confirmation.")

    # Start the quiz via QuizLogic
    # The start_quiz method in QuizLogic will send the first question
    # It needs the `update` object to potentially edit the message if no questions are found.
    next_state = await quiz_logic_instance.start_quiz(context.bot, context, update)
    return next_state

async def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    quiz_instance_id = context.user_data.get("current_quiz_instance_id")

    if not quiz_instance_id or quiz_instance_id not in context.user_data:
        logger.warning(f"User {user_id} (chat {chat_id}) sent an answer but no active quiz instance ID found or instance missing. Callback: {query.data}")
        await query.answer(text="لم يتم العثور على اختبار نشط. قد يكون الاختبار قد انتهى أو حدث خطأ.")
        # Try to clean up the message if possible, or send a new one with main menu
        try:
            await query.edit_message_text("انتهى هذا الاختبار أو لم يعد صالحاً.", reply_markup=create_quiz_type_keyboard())
        except Exception:
            await safe_send_message(context.bot, chat_id, "انتهى هذا الاختبار أو لم يعد صالحاً.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE # Or END, but SELECT_QUIZ_TYPE allows re-entry

    quiz_logic_instance = context.user_data[quiz_instance_id]
    if not isinstance(quiz_logic_instance, QuizLogic):
        logger.error(f"User {user_id} (chat {chat_id}) - object for quiz_instance_id {quiz_instance_id} is not QuizLogic. Type: {type(quiz_logic_instance)}. CB: {query.data}")
        await query.answer(text="خطأ في بيانات الاختبار.")
        await query.edit_message_text("حدث خطأ داخلي في بيانات الاختبار.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    # Store the message_id of the callback query message (the question message with buttons)
    # This is crucial for show_results to correctly identify the message to edit.
    if query and query.message:
        context.user_data[f"last_quiz_interaction_message_id_{chat_id}"] = query.message.message_id
        logger.debug(f"Stored last_quiz_interaction_message_id_{chat_id} = {query.message.message_id} in handle_quiz_answer.")

    next_state = await quiz_logic_instance.handle_answer(update, context)
    return next_state

async def quiz_timeout_handler_entry(update: Update, context: CallbackContext):
    """Handles timeout if a user doesn't answer a question in time. This is called by the JobQueue job created in QuizLogic.
       This function itself is not a ConversationHandler state, but is called by question_timeout_callback_wrapper.
       The wrapper should be imported from quiz_logic and used by JobQueue in bot.py or quiz_logic.py.
       This specific handler in quiz.py might be redundant if question_timeout_callback_wrapper is directly used by QuizLogic's job.
       However, if it's intended as an entry point for a timeout *event* that then finds the QuizLogic instance, it needs careful implementation.
       The current QuizLogic schedules `question_timeout_callback_wrapper` from `quiz_logic.py`.
    """
    # This function seems to be a placeholder or a misunderstanding of how timeouts are handled.
    # The actual timeout logic is now primarily within QuizLogic and its scheduled job `question_timeout_callback_wrapper`.
    # If this function `quiz_timeout_handler_entry` is still registered somewhere, it might conflict or be unused.
    # For now, logging its call if it ever happens.
    logger.warning("quiz_timeout_handler_entry in quiz.py was called. This might be unexpected as QuizLogic handles its own timeouts.")
    
    # Attempt to find the quiz instance if possible, though this is better handled by the job's context data
    user_id = update.effective_user.id if update.effective_user else "UnknownUserFromTimeout"
    chat_id = update.effective_chat.id if update.effective_chat else "UnknownChatFromTimeout"
    quiz_instance_id = context.user_data.get("current_quiz_instance_id")

    if quiz_instance_id and quiz_instance_id in context.user_data:
        quiz_logic_instance = context.user_data.get(quiz_instance_id)
        if isinstance(quiz_logic_instance, QuizLogic) and quiz_logic_instance.active:
            logger.info(f"Timeout detected by quiz_timeout_handler_entry for user {user_id}, quiz {quiz_instance_id}. Delegating to instance.")
            # This call is problematic as handle_timeout in QuizLogic expects to be called by the job wrapper
            # and might not have the correct `update` object if this is a generic timeout event.
            # The job wrapper in quiz_logic.py is the correct entry point.
            # await quiz_logic_instance.handle_timeout(context.bot, context) # This would be incorrect here.
            pass # Avoid calling directly, rely on the job queue's call to the wrapper in quiz_logic.py
        else:
            logger.info(f"Timeout detected by quiz_timeout_handler_entry for user {user_id}, but quiz {quiz_instance_id} not active or not QuizLogic.")
    else:
        logger.info(f"Timeout detected by quiz_timeout_handler_entry for user {user_id}, but no current quiz instance found.")
    
    # This function should not return a state for ConversationHandler unless it's part of its states.
    # Given the current setup, this function is likely unused or misconfigured if called.

# Conversation Handler Setup
quiz_conv_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(quiz_menu_entry, pattern="^quiz_menu_entry$"),
        # Fallback for /quiz command if user is in no particular state or to re-enter quiz selection
        CommandHandler("quiz", quiz_menu_entry) # Assuming quiz_menu_entry can handle direct command if query is None
    ],
    states={
        SELECT_QUIZ_TYPE: [
            CallbackQueryHandler(select_quiz_type, pattern="^quiz_type_.+$"),
            CallbackQueryHandler(go_to_main_menu_from_quiz, pattern="^main_menu$")
        ],
        SELECT_COURSE_FOR_UNIT_QUIZ: [
            CallbackQueryHandler(select_course_for_unit_quiz, pattern="^quiz_course_select_.+$"),
            CallbackQueryHandler(select_course_for_unit_quiz, pattern="^quiz_course_page_.+$"),
            CallbackQueryHandler(select_quiz_type, pattern="^quiz_type_back_to_type_selection$") # Back to type selection
        ],
        SELECT_UNIT_FOR_COURSE: [
            CallbackQueryHandler(select_unit_for_course, pattern="^quiz_unit_select_.+_.+$"),
            CallbackQueryHandler(select_unit_for_course, pattern="^quiz_unit_page_.+_.+$"),
            CallbackQueryHandler(select_course_for_unit_quiz, pattern="^quiz_unit_back_to_course_selection$") # Back to course selection
        ],
        ENTER_QUESTION_COUNT: [
            CallbackQueryHandler(select_question_count, pattern="^num_questions_.+$"),
            CallbackQueryHandler(select_question_count, pattern="^quiz_count_back_to_unit_selection_.+$"), # Back to unit selection (for unit quizzes)
            CallbackQueryHandler(select_question_count, pattern="^quiz_type_back_to_type_selection$") # Back to type selection (for 'all' quizzes)
        ],
        TAKING_QUIZ: [
            CallbackQueryHandler(handle_quiz_answer, pattern="^ans_.+_.+_.+$")
            # Timeouts are handled by JobQueue calling question_timeout_callback_wrapper from quiz_logic.py
            # That wrapper then calls quiz_logic_instance.handle_timeout()
        ],
        SHOWING_RESULTS: [ # After results are shown, user can go to main menu or start new quiz
            CallbackQueryHandler(quiz_menu_entry, pattern="^quiz_menu_entry$"), # Start new quiz
            CallbackQueryHandler(go_to_main_menu_from_quiz, pattern="^main_menu$"),
            # CallbackQueryHandler(show_my_stats_entry_from_quiz_results, pattern="^quiz_show_my_stats$") # If stats is part of this conv
        ]
    },
    fallbacks=[
        CommandHandler("start", start_command_fallback_for_quiz),
        CallbackQueryHandler(go_to_main_menu_from_quiz, pattern="^main_menu$"), # Global main menu fallback
        CallbackQueryHandler(quiz_menu_entry, pattern="^quiz_menu_entry$") # If user clicks 'start new quiz' from results
    ],
    map_to_parent={
        END: MAIN_MENU # Or whatever state main_menu_callback returns if it's a conv handler itself
    },
    per_message=False,
    name="quiz_conversation",
    persistent=True
)

