# -*- coding: utf-8 -*-
"""Conversation handler for the quiz selection and execution flow (v8 - Pickle Refactor Support - F-string fix)."""

import logging
import math
import random
import re 
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot # Added Bot
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
# Import the refactored QuizLogic and its timeout wrapper
from .quiz_logic import QuizLogic, question_timeout_callback_wrapper 

ITEMS_PER_PAGE = 6

async def start_command_fallback_for_quiz(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} sent /start during an active or lingering quiz conversation. Ending current quiz conversation and showing main menu.")
    
    if "quiz_sessions" in context.user_data:
        for quiz_id, quiz_instance in list(context.user_data["quiz_sessions"].items()): 
            if isinstance(quiz_instance, QuizLogic) and quiz_instance.user_id == user_id:
                try:
                    timer_job_name = f"qtimer_{user_id}_{update.effective_chat.id}_{quiz_instance.quiz_id}_{quiz_instance.current_question_index}"
                    remove_job_if_exists(timer_job_name, context)
                    # Pass bot and context to end_quiz if it expects them (it does in v24)
                    await quiz_instance.end_quiz(context.bot, context, update, manual_end=True, reason_suffix="start_fallback")
                    logger.info(f"Cleaned up quiz session {quiz_id} for user {user_id} during /start fallback via QuizLogic.end_quiz.")
                except Exception as e_cleanup:
                    logger.error(f"Error during quiz_logic cleanup for quiz {quiz_id} in start_command_fallback: {e_cleanup}")
                    # Fallback cleanup if QuizLogic method fails or instance is malformed
                    if quiz_id in context.user_data["quiz_sessions"]:
                        del context.user_data["quiz_sessions"][quiz_id]
        if not context.user_data["quiz_sessions"]:
            context.user_data.pop("quiz_sessions", None)

    keys_to_pop = [
        "selected_quiz_type_key", "selected_quiz_type_display_name", "questions_for_quiz",
        "selected_course_id_for_unit_quiz", "available_courses_for_unit_quiz",
        "current_course_page_for_unit_quiz", "selected_course_name_for_unit_quiz",
        "available_units_for_course", "current_unit_page_for_course",
        "selected_unit_id", "selected_unit_name", "question_count_for_quiz"
    ]
    for key in list(context.user_data.keys()):
        if key.startswith("quiz_setup_") or key.startswith("qtimer_") or key in keys_to_pop:
             context.user_data.pop(key, None)

    logger.info(f"Cleared quiz-related user_data for user {user_id} due to /start fallback in quiz conversation.")
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
        # Corrected f-string: using single quotes inside for course.get('id')
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
        # Corrected f-string: using single quotes inside for unit.get('id')
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
    if not counts or (counts and max_questions > counts[-1]):
         if max_questions > 0:
            keyboard.append([InlineKeyboardButton(f"الكل ({max_questions})", callback_data="num_questions_all")]) # Corrected f-string, no nested quotes issue here
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
        "selected_unit_id", "selected_unit_name", "question_count_for_quiz"
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
        context.user_data["selected_unit_id"] = "all"
        max_questions = len(all_questions_pool)
        keyboard = create_question_count_keyboard(max_questions, quiz_type_key, unit_id="all")
        # Corrected f-string: using single quotes for quiz_type_display_name if it contains special chars, or ensure it's clean.
        # For safety, using escaped double quotes inside the f-string's literal part.
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
        selected_course_id = callback_data.split("_")[-1]
        selected_course = next((c for c in courses if str(c.get("id")) == selected_course_id), None)
        if not selected_course:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ في اختيار المقرر. يرجى المحاولة مرة أخرى.", reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
        context.user_data["selected_course_id_for_unit_quiz"] = selected_course_id
        # Corrected f-string for selected_course.get('name')
        selected_course_name = selected_course.get("name", f"مقرر {selected_course_id}")
        context.user_data["selected_course_name_for_unit_quiz"] = selected_course_name
        units = fetch_from_api(f"api/v1/courses/{selected_course_id}/units")
        api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
        if units == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
        if not units or not isinstance(units, list) or not units:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لا توجد وحدات دراسية متاحة لهذا المقرر حالياً.", reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
        context.user_data["available_units_for_course"] = units
        context.user_data["current_unit_page_for_course"] = 0
        keyboard = create_unit_selection_keyboard(units, selected_course_id, 0)
        # Corrected f-string for selected_course_name
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية للمقرر \"{selected_course_name}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    return SELECT_COURSE_FOR_UNIT_QUIZ

async def select_unit_for_course(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data
    selected_course_id = context.user_data.get("selected_course_id_for_unit_quiz")
    # Corrected f-string for selected_course_name default value
    selected_course_name = context.user_data.get("selected_course_name_for_unit_quiz", f"مقرر {selected_course_id}")
    available_units = context.user_data.get("available_units_for_course", [])
    current_unit_page = context.user_data.get("current_unit_page_for_course", 0)
    if callback_data == "quiz_unit_back_to_course_selection":
        all_courses = context.user_data.get("available_courses_for_unit_quiz", [])
        current_course_page = context.user_data.get("current_course_page_for_unit_quiz", 0)
        keyboard = create_course_selection_keyboard(all_courses, current_course_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="اختر المقرر الدراسي:", reply_markup=keyboard)
        return SELECT_COURSE_FOR_UNIT_QUIZ
    if callback_data.startswith("quiz_unit_page_"):
        parts = callback_data.split("_")
        new_page = int(parts[-1])
        context.user_data["current_unit_page_for_course"] = new_page
        keyboard = create_unit_selection_keyboard(available_units, selected_course_id, new_page)
        # Corrected f-string for selected_course_name
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية للمقرر \"{selected_course_name}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data.startswith("quiz_unit_select_"):
        parts = callback_data.split("_")
        selected_unit_id = parts[-1]
        selected_unit = next((u for u in available_units if str(u.get("id")) == selected_unit_id), None)
        if not selected_unit:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ في اختيار الوحدة. يرجى المحاولة مرة أخرى.", reply_markup=create_unit_selection_keyboard(available_units, selected_course_id, current_unit_page))
            return SELECT_UNIT_FOR_COURSE
        # Corrected f-string for selected_unit.get('name')
        selected_unit_name = selected_unit.get("name", f"وحدة {selected_unit_id}")
        context.user_data["selected_unit_id"] = selected_unit_id
        context.user_data["selected_unit_name"] = selected_unit_name
        questions_for_unit = fetch_from_api(f"api/v1/units/{selected_unit_id}/questions")
        api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
        if questions_for_unit == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_unit_selection_keyboard(available_units, selected_course_id, current_unit_page))
            return SELECT_UNIT_FOR_COURSE
        if not questions_for_unit or not isinstance(questions_for_unit, list) or not questions_for_unit:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لا توجد أسئلة متاحة لهذه الوحدة حالياً.", reply_markup=create_unit_selection_keyboard(available_units, selected_course_id, current_unit_page))
            return SELECT_UNIT_FOR_COURSE
        quiz_type_key = context.user_data.get("selected_quiz_type_key")
        context.user_data[f"quiz_setup_{quiz_type_key}_{selected_unit_id}"] = {
            "questions": questions_for_unit,
            # Corrected f-string for selected_unit_name
            "quiz_name": f"{selected_course_name} - {selected_unit_name}"
        }
        max_questions = len(questions_for_unit)
        keyboard = create_question_count_keyboard(max_questions, quiz_type_key, unit_id=selected_unit_id, course_id_for_unit=selected_course_id)
        # Corrected f-string for selected_course_name and selected_unit_name
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار \n\"{selected_course_name} - {selected_unit_name}\":", reply_markup=keyboard)
        return ENTER_QUESTION_COUNT
    return SELECT_UNIT_FOR_COURSE

async def select_question_count(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    callback_data = query.data
    quiz_type_key = context.user_data.get("selected_quiz_type_key")
    scope_identifier = context.user_data.get("selected_unit_id") 

    if callback_data.startswith("quiz_count_back_to_unit_selection_"):
        course_id_from_cb = callback_data.split("_")[-1]
        units_for_course = context.user_data.get("available_units_for_course", []) 
        current_unit_pg = context.user_data.get("current_unit_page_for_course", 0)
        course_name_for_unit = context.user_data.get("selected_course_name_for_unit_quiz", "المقرر المحدد")
        keyboard = create_unit_selection_keyboard(units_for_course, course_id_from_cb, current_unit_pg)
        # Corrected f-string for course_name_for_unit
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر وحدة دراسية من مقرر \"{course_name_for_unit}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data == "quiz_type_back_to_type_selection": 
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    if not quiz_type_key or not scope_identifier:
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، يبدو أن معلومات إعداد الاختبار غير كاملة. يرجى المحاولة من البداية.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    num_questions_str = callback_data.replace("num_questions_", "", 1)
    quiz_setup_data_key = f"quiz_setup_{quiz_type_key}_{scope_identifier}"
    quiz_setup_data = context.user_data.get(quiz_setup_data_key)

    if not quiz_setup_data:
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، بيانات إعداد الاختبار مفقودة. يرجى إعادة المحاولة.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    all_questions_for_scope = quiz_setup_data.get("questions", [])
    quiz_name_from_setup = quiz_setup_data.get("quiz_name", "اختبار")

    if not all_questions_for_scope:
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لا توجد أسئلة متاحة لهذا النطاق المحدد.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE
        
    if num_questions_str == "all":
        num_questions = len(all_questions_for_scope)
        selected_questions_final = all_questions_for_scope
    else:
        try:
            num_questions = int(num_questions_str)
            if num_questions <= 0: raise ValueError("Number of questions must be positive.")
            if num_questions > len(all_questions_for_scope):
                num_questions = len(all_questions_for_scope)
            selected_questions_final = random.sample(all_questions_for_scope, num_questions)
        except ValueError:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عدد الأسئلة المحدد غير صالح. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
    
    if not selected_questions_final:
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لم يتم اختيار أسئلة. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    quiz_logic = QuizLogic(
        user_id=user_id, 
        quiz_type=quiz_type_key,
        questions_data=selected_questions_final, 
        total_questions=num_questions, 
        question_time_limit=DEFAULT_QUESTION_TIME_LIMIT
    )

    if "quiz_sessions" not in context.user_data:
        context.user_data["quiz_sessions"] = {}
    context.user_data["quiz_sessions"][quiz_logic.quiz_id] = quiz_logic
    
    scope_display_name = ""
    if quiz_type_key == QUIZ_TYPE_UNIT:
        selected_course_name = context.user_data.get("selected_course_name_for_unit_quiz", "")
        selected_unit_name = context.user_data.get("selected_unit_name", "")
        if selected_course_name and selected_unit_name:
            scope_display_name = f" ({selected_course_name} - {selected_unit_name})"
        elif selected_course_name:
             scope_display_name = f" ({selected_course_name})"
    elif quiz_type_key == QUIZ_TYPE_ALL:
        scope_display_name = " (شامل)"

    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"⏳ يتم الآن إعداد اختبارك{scope_display_name} بـ {num_questions} سؤال. لحظات قليلة...")
    
    return await quiz_logic.start_quiz(context.bot, context, update, query.message.chat_id, user_id)

async def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    callback_data = query.data 

    quiz_id_from_callback = None
    if callback_data.startswith("ans_"):
        try:
            parts = callback_data.split("_")
            quiz_id_from_callback = parts[1]
        except IndexError:
            await query.answer("خطأ في بيانات الإجابة.", show_alert=True)
            return TAKING_QUIZ 

    quiz_logic = None
    if quiz_id_from_callback and "quiz_sessions" in context.user_data:
        quiz_logic = context.user_data["quiz_sessions"].get(quiz_id_from_callback)
    
    if not quiz_logic or not isinstance(quiz_logic, QuizLogic):
        await query.answer("الاختبار غير موجود أو انتهت صلاحيته.", show_alert=True)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass 
        return TAKING_QUIZ 

    if quiz_logic.user_id != user_id:
        await query.answer("هذا الاختبار ليس لك.", show_alert=True)
        return TAKING_QUIZ

    return await quiz_logic.handle_answer(context.bot, context, update)

async def unhandled_quiz_text(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} sent unhandled text: '{update.message.text}' during a quiz state.") # Corrected f-string quotes
    await safe_send_message(context.bot, chat_id=update.effective_chat.id, text="أنت حالياً في وضع الاختبار. يرجى استخدام الأزرار للإجابة على الأسئلة أو انتظر انتهاء الاختبار للعودة للقائمة.")
    return TAKING_QUIZ 

async def unhandled_quiz_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    logger.warning(f"User {user_id} sent unhandled callback_query: {query.data} during a quiz state.")
    await query.answer("أمر غير معروف أو زر قديم.")
    return context.user_data.get("_current_quiz_state_", TAKING_QUIZ) 


quiz_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(quiz_menu_entry, pattern="^start_quiz$")],
    states={
        SELECT_QUIZ_TYPE: [CallbackQueryHandler(select_quiz_type, pattern="^(quiz_type_|main_menu|quiz_type_back_to_type_selection)")],
        SELECT_COURSE_FOR_UNIT_QUIZ: [CallbackQueryHandler(select_course_for_unit_quiz, pattern="^(quiz_course_select_|quiz_course_page_|quiz_type_back_to_type_selection)")],
        SELECT_UNIT_FOR_COURSE: [CallbackQueryHandler(select_unit_for_course, pattern="^(quiz_unit_select_|quiz_unit_page_|quiz_unit_back_to_course_selection)")],
        ENTER_QUESTION_COUNT: [CallbackQueryHandler(select_question_count, pattern="^(num_questions_|quiz_count_back_to_unit_selection_|quiz_type_back_to_type_selection)")],
        TAKING_QUIZ: [
            CallbackQueryHandler(handle_quiz_answer, pattern="^ans_"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, unhandled_quiz_text), 
            CallbackQueryHandler(unhandled_quiz_callback) 
        ],
    },
    fallbacks=[
        CommandHandler("start", start_command_fallback_for_quiz), 
        CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"), 
    ],
    map_to_parent={
        END: MAIN_MENU, 
        ConversationHandler.END : ConversationHandler.END 
    },
    persistent=True, 
    name="quiz_conversation", 
)

