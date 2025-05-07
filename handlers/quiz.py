# -*- coding: utf-8 -*-
"""Conversation handler for the quiz selection and execution flow (v9 - Handler Fix)."""

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
# Assuming common.py is in a directory named 'handlers' relative to quiz.py, or adjust path as needed.
# If handlers.common is a module in the same directory as quiz.py, then it should be: from .common import ...
# For now, keeping it as it was, assuming it's resolved in user's environment.
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
                    await quiz_instance.end_quiz(context.bot, context, update, manual_end=True, reason_suffix="start_fallback")
                    logger.info(f"Cleaned up quiz session {quiz_id} for user {user_id} during /start fallback via QuizLogic.end_quiz.")
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
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")] # This button will now be handled by a global handler
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
    if not counts or (counts and max_questions > counts[-1]):
         if max_questions > 0:
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
    # If main_menu is pressed here, it should be handled by a global handler now, 
    # but we keep a check in case it's still caught by the conversation for some reason before ending.
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
        selected_course_name = selected_course.get("name", f"مقرر {selected_course_id}")
        context.user_data["selected_course_name_for_unit_quiz"] = selected_course_name
        units = fetch_from_api(f"api/v1/courses/{selected_course_id}/units")
        api_timeout_message = "انتهت مهلة الاتصال بخادم الوحدات. يرجى المحاولة مرة أخرى لاحقاً."
        error_message_to_user = "عذراً، لا توجد وحدات متاحة لهذا المقرر حالياً أو حدث خطأ في جلبها."
        if units == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
        if not units or not isinstance(units, list) or not units:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=error_message_to_user, reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
        context.user_data["available_units_for_course"] = units
        context.user_data["current_unit_page_for_course"] = 0
        keyboard = create_unit_selection_keyboard(units, selected_course_id, 0)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية للمقرر \"{selected_course_name}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE

async def select_unit_for_course(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data
    selected_course_id = context.user_data.get("selected_course_id_for_unit_quiz")
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
        # course_id_from_cb = parts[-2] # Not strictly needed if selected_course_id is reliable from context
        new_page = int(parts[-1])
        context.user_data["current_unit_page_for_course"] = new_page
        keyboard = create_unit_selection_keyboard(units, selected_course_id, new_page)
        selected_course_name = context.user_data.get("selected_course_name_for_unit_quiz", "المقرر المحدد")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية للمقرر \"{selected_course_name}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data.startswith("quiz_unit_select_"):
        parts = callback_data.split("_")
        # selected_course_id_from_cb = parts[-2] # Not strictly needed
        selected_unit_id = parts[-1]
        selected_unit = next((u for u in units if str(u.get("id")) == selected_unit_id), None)
        if not selected_unit:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ في اختيار الوحدة. يرجى المحاولة مرة أخرى.", reply_markup=create_unit_selection_keyboard(units, selected_course_id, current_page))
            return SELECT_UNIT_FOR_COURSE
        context.user_data["selected_unit_id"] = selected_unit_id
        selected_unit_name = selected_unit.get("name", f"وحدة {selected_unit_id}")
        context.user_data["selected_unit_name"] = selected_unit_name
        questions = fetch_from_api(f"api/v1/units/{selected_unit_id}/questions")
        api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
        error_message_to_user = "عذراً، لا توجد أسئلة متاحة لهذه الوحدة حالياً أو حدث خطأ في جلبها."
        if questions == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_unit_selection_keyboard(units, selected_course_id, current_page))
            return SELECT_UNIT_FOR_COURSE
        if not questions or not isinstance(questions, list) or not questions:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=error_message_to_user, reply_markup=create_unit_selection_keyboard(units, selected_course_id, current_page))
            return SELECT_UNIT_FOR_COURSE
        context.user_data[f"quiz_setup_{context.user_data['selected_quiz_type_key']}_{selected_unit_id}"] = {
            "questions": questions,
            "quiz_name": selected_unit_name 
        }
        max_questions = len(questions)
        keyboard = create_question_count_keyboard(max_questions, context.user_data["selected_quiz_type_key"], unit_id=selected_unit_id, course_id_for_unit=selected_course_id)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار وحدة \"{selected_unit_name}\" من مقرر \"{context.user_data.get('selected_course_name_for_unit_quiz', '')}\":", reply_markup=keyboard)
        return ENTER_QUESTION_COUNT

async def select_question_count(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data
    quiz_type_key = context.user_data.get("selected_quiz_type_key")
    selected_unit_id = context.user_data.get("selected_unit_id") # Can be "all" for QUIZ_TYPE_ALL
    # Determine the correct key for quiz_setup data
    if quiz_type_key == QUIZ_TYPE_ALL:
        quiz_setup_key = f"quiz_setup_{quiz_type_key}_all"
    elif quiz_type_key == QUIZ_TYPE_UNIT and selected_unit_id:
        quiz_setup_key = f"quiz_setup_{quiz_type_key}_{selected_unit_id}"
    else:
        logger.error(f"[select_question_count] Invalid state: quiz_type_key={quiz_type_key}, selected_unit_id={selected_unit_id} for user {user_id}")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ في تحديد نوع الاختبار. الرجاء البدء من جديد.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    quiz_setup_data = context.user_data.get(quiz_setup_key)
    if not quiz_setup_data or "questions" not in quiz_setup_data:
        logger.error(f"[select_question_count] No questions found in quiz_setup_data for key {quiz_setup_key}, user {user_id}")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="لم يتم العثور على أسئلة مهيأة. الرجاء البدء من جديد.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE
    
    all_questions_for_scope = quiz_setup_data["questions"]
    max_questions = len(all_questions_for_scope)

    if callback_data.startswith("quiz_count_back_to_unit_selection_"):
        course_id_from_cb = callback_data.split("_")[-1]
        units_for_course = context.user_data.get("available_units_for_course", [])
        unit_page = context.user_data.get("current_unit_page_for_course", 0)
        keyboard = create_unit_selection_keyboard(units_for_course, course_id_from_cb, unit_page)
        selected_course_name = context.user_data.get("selected_course_name_for_unit_quiz", "المقرر المحدد")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية للمقرر \"{selected_course_name}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data == "quiz_type_back_to_type_selection":
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    num_questions_str = callback_data.replace("num_questions_", "", 1)
    if num_questions_str == "all":
        num_questions = max_questions
    else:
        try:
            num_questions = int(num_questions_str)
            if not (0 < num_questions <= max_questions):
                raise ValueError("Invalid number of questions")
        except ValueError:
            logger.warning(f"Invalid num_questions_str: {num_questions_str} for user {user_id}")
            keyboard = create_question_count_keyboard(max_questions, quiz_type_key, selected_unit_id, context.user_data.get("selected_course_id_for_unit_quiz"))
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عدد أسئلة غير صالح. يرجى الاختيار من القائمة.", reply_markup=keyboard)
            return ENTER_QUESTION_COUNT

    context.user_data["question_count_for_quiz"] = num_questions
    # Shuffle and select questions
    random.shuffle(all_questions_for_scope)
    questions_for_quiz = all_questions_for_scope[:num_questions]
    context.user_data["questions_for_quiz"] = questions_for_quiz

    quiz_logic = QuizLogic(
        user_id=user_id,
        quiz_type=quiz_type_key,
        questions_data=questions_for_quiz,
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
    logger.info(f"User {user_id} sent unhandled text: '{update.message.text}' during a quiz state.")
    await safe_send_message(context.bot, chat_id=update.effective_chat.id, text="أنت حالياً في وضع الاختبار. يرجى استخدام الأزرار للإجابة على الأسئلة أو انتظر انتهاء الاختبار للعودة للقائمة.")
    return TAKING_QUIZ 

async def unhandled_quiz_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    logger.warning(f"User {user_id} sent unhandled callback_query: {query.data} during a quiz state.")
    await query.answer("أمر غير معروف أو زر قديم.")
    return context.user_data.get("_current_quiz_state_", TAKING_QUIZ) 


quiz_conv_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(quiz_menu_entry, pattern="^start_quiz$"),
        CallbackQueryHandler(quiz_menu_entry, pattern="^start_quiz_new$") # MODIFIED: Added for re-entry
    ],
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
        # MODIFIED: Removed CallbackQueryHandler(main_menu_callback, pattern="^main_menu$") from here
    ],
    map_to_parent={
        END: MAIN_MENU, 
        ConversationHandler.END : ConversationHandler.END 
    },
    persistent=True, 
    name="quiz_conversation", 
    allow_reentry=True, # Ensured this is True
)

# IMPORTANT: User needs to add this to their main bot setup (e.g., in main() function):
# application.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))

