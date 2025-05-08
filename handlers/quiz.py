# -*- coding: utf-8 -*-
"""Conversation handler for the quiz selection and execution flow (v10 - Global Main Menu Fix)."""

import logging
import math
import random
import re 
from datetime import datetime # Added for quiz_id timestamp
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
# Ensure main_menu_callback is imported, it will be used by the global handler
from handlers.common import create_main_menu_keyboard, main_menu_callback 
from .quiz_logic import QuizLogic, question_timeout_callback_wrapper 

# --- ADDED IMPORT FOR STATS UPDATE ---
from handlers.stats import update_user_stats_in_json
# -------------------------------------

ITEMS_PER_PAGE = 6

async def start_command_fallback_for_quiz(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} sent /start during an active or lingering quiz conversation. Ending current quiz conversation and showing main menu.")
    
    # Cleanup logic for quiz sessions and user_data
    if "quiz_sessions" in context.user_data:
        for quiz_id, quiz_instance in list(context.user_data["quiz_sessions"].items()): 
            if isinstance(quiz_instance, QuizLogic) and quiz_instance.user_id == user_id:
                try:
                    timer_job_name = f"qtimer_{user_id}_{update.effective_chat.id}_{quiz_instance.quiz_id}_{quiz_instance.current_question_index}"
                    remove_job_if_exists(timer_job_name, context)
                    # Assuming QuizLogic has an end_quiz or similar cleanup method
                    # If not, direct cleanup here or ensure quiz_instance.active = False
                    if hasattr(quiz_instance, 'end_quiz') and callable(getattr(quiz_instance, 'end_quiz')):
                         await quiz_instance.end_quiz(context.bot, context, update, manual_end=True, reason_suffix="start_fallback_quiz_handler")
                    else:
                         quiz_instance.active = False # Fallback to mark as inactive
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
        # Ensure any quiz_instance key is also cleared if not handled by quiz_sessions loop
        f"quiz_instance_{user_id}_{update.effective_chat.id}" 
    ]
    for key in list(context.user_data.keys()):
        if key.startswith("quiz_setup_") or key.startswith("qtimer_") or key in keys_to_pop or key.startswith(f"quiz_instance_{user_id}_"):
             context.user_data.pop(key, None)

    logger.info(f"Cleared quiz-related user_data for user {user_id} due to /start fallback in quiz conversation.")
    # Call the global main_menu_callback directly
    await main_menu_callback(update, context, called_from_fallback=True) 
    return ConversationHandler.END

# ... (rest of the functions like create_quiz_type_keyboard, select_quiz_type, etc. remain the same)

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
    # No need to handle 'main_menu' here if a global handler is added, 
    # but it's good for clarity within the conversation flow.
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
    return SELECT_COURSE_FOR_UNIT_QUIZ # Fallback

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
        selected_course_name = context.user_data.get("selected_course_name_for_unit_quiz", f"مقرر {selected_course_id}")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية للمقرر \"{selected_course_name}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data.startswith("quiz_unit_select_"):
        parts = callback_data.split("_")
        # selected_course_id_from_cb = parts[-2] # Ensure it matches context if used
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
        quiz_name = f"{context.user_data.get('selected_course_name_for_unit_quiz', '')} - {selected_unit_name}"
        context.user_data[f"quiz_setup_{context.user_data['selected_quiz_type_key']}_{selected_unit_id}"] = {
            "questions": questions,
            "quiz_name": quiz_name
        }
        max_questions = len(questions)
        keyboard = create_question_count_keyboard(max_questions, context.user_data["selected_quiz_type_key"], unit_id=selected_unit_id, course_id_for_unit=selected_course_id)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار \"{selected_unit_name}\":", reply_markup=keyboard)
        return ENTER_QUESTION_COUNT
    return SELECT_UNIT_FOR_COURSE # Fallback

async def select_question_count(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data
    quiz_type = context.user_data.get("selected_quiz_type_key")
    unit_id = context.user_data.get("selected_unit_id") # This will be 'all' for QUIZ_TYPE_ALL
    course_id_for_unit = context.user_data.get("selected_course_id_for_unit_quiz") # For back button from unit quiz

    if callback_data.startswith("quiz_count_back_to_unit_selection_"):
        # This specific back button is only for unit quizzes
        course_id_from_cb = callback_data.split("_")[-1]
        units = context.user_data.get("available_units_for_course", [])
        unit_page = context.user_data.get("current_unit_page_for_course", 0)
        selected_course_name = context.user_data.get("selected_course_name_for_unit_quiz", f"مقرر {course_id_from_cb}")
        keyboard = create_unit_selection_keyboard(units, course_id_from_cb, unit_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية للمقرر \"{selected_course_name}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data == "quiz_type_back_to_type_selection": # Generic back to type selection
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    quiz_setup_key = f"quiz_setup_{quiz_type}_{unit_id}"
    quiz_data_for_type = context.user_data.get(quiz_setup_key)

    if not quiz_data_for_type or "questions" not in quiz_data_for_type:
        logger.error(f"User {user_id}: Quiz data not found for key {quiz_setup_key} at question count selection.")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ في إعداد الاختبار. يرجى البدء من جديد.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    all_questions = quiz_data_for_type["questions"]
    quiz_name_from_setup = quiz_data_for_type.get("quiz_name", "اختبار")
    max_q = len(all_questions)

    if callback_data == "num_questions_all":
        num_questions = max_q
    elif callback_data.startswith("num_questions_"):
        try:
            num_questions = int(callback_data.split("_")[-1])
            if not (0 < num_questions <= max_q):
                logger.warning(f"User {user_id} selected invalid num_questions {num_questions} (max: {max_q}). Defaulting to max.")
                num_questions = max_q
        except ValueError:
            logger.error(f"User {user_id}: ValueError converting num_questions from {callback_data}. Defaulting to max.")
            num_questions = max_q
    else:
        logger.warning(f"User {user_id}: Unknown callback {callback_data} at question count. Defaulting to max.")
        num_questions = max_q
    
    context.user_data["question_count_for_quiz"] = num_questions
    selected_questions = random.sample(all_questions, min(num_questions, max_q))
    
    # Generate a unique quiz_id for this session
    # Example: user_id_quiz_type_unit_id_timestamp
    timestamp = int(datetime.now().timestamp())
    quiz_id_str = f"{user_id}_{quiz_type}_{unit_id}_{timestamp}"

    # Store the QuizLogic instance in user_data using the unique quiz_id
    # This replaces the older method of storing one quiz_instance per user/chat
    if "quiz_sessions" not in context.user_data: context.user_data["quiz_sessions"] = {}
    
    quiz_instance = QuizLogic(
        user_id=user_id, 
        chat_id=query.message.chat_id, 
        quiz_type=quiz_type, 
        questions_data=selected_questions, 
        question_time_limit=DEFAULT_QUESTION_TIME_LIMIT, # Or from user settings
        quiz_id=quiz_id_str,
        quiz_name=quiz_name_from_setup
    )
    context.user_data["quiz_sessions"][quiz_id_str] = quiz_instance
    
    logger.info(f"User {user_id} starting quiz {quiz_id_str} ({quiz_name_from_setup}) with {len(selected_questions)} questions.")
    
    # Edit the message to show quiz is starting, or send new if edit fails
    start_message_text = f"⏳ يتم الآن بدء اختبار \"{quiz_name_from_setup}\" بـ {len(selected_questions)} أسئلة..."
    try:
        await context.bot.edit_message_text(
            text=start_message_text,
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            reply_markup=None # Remove buttons
        )
    except Exception as e_edit_start:
        logger.warning(f"Failed to edit message at quiz start for user {user_id}: {e_edit_start}. Sending new message.")
        await safe_send_message(context.bot, chat_id=query.message.chat_id, text=start_message_text)

    return await quiz_instance.start_quiz(bot=context.bot, context=context, update=update, user_id=user_id)

async def process_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer() # Acknowledge callback quickly

    logger.info(f"[quiz.py] process_answer CALLED for user {user_id} with callback_data: {query.data}")

    # Extract quiz_id from callback_data (assuming format like "ans_QUIZID_qidx_optid")
    try:
        # Simplified parsing assuming quiz_id is the second part after "ans_"
        # and before the last two numeric parts (q_idx, option_id)
        parts = query.data.split("_", 1) # Split "ans_" prefix
        if len(parts) < 2 or parts[0] != "ans":
            raise ValueError("Callback data does not start with ans_")
        
        remaining_data = parts[1]
        # quiz_id might contain underscores, so rsplit from the right for q_idx and option_id
        quiz_id_parts = remaining_data.rsplit("_", 2)
        if len(quiz_id_parts) < 3:
            raise ValueError("Callback data does not have enough parts for quiz_id, q_idx, option_id")
        
        quiz_id_str_from_callback = quiz_id_parts[0]
    except Exception as e_parse:
        logger.error(f"[quiz.py] process_answer: Error parsing quiz_id from callback_data '{query.data}': {e_parse}")
        # Attempt to find any active quiz for the user if parsing fails (less ideal)
        active_quiz_found = False
        if "quiz_sessions" in context.user_data:
            for q_id, q_instance in context.user_data["quiz_sessions"].items():
                if q_instance.user_id == user_id and q_instance.active:
                    quiz_id_str_from_callback = q_id
                    active_quiz_found = True
                    logger.warning(f"[quiz.py] process_answer: Fallback - Using active quiz_id {q_id} for user {user_id}")
                    break
        if not active_quiz_found:
            await safe_send_message(context.bot, chat_id=query.message.chat_id, text="حدث خطأ في معالجة إجابتك (معرف اختبار غير صالح). يرجى المحاولة مرة أخرى أو بدء اختبار جديد.")
            return ConversationHandler.END # Or go to main menu

    quiz_instance = context.user_data.get("quiz_sessions", {}).get(quiz_id_str_from_callback)

    if not quiz_instance or not quiz_instance.active:
        logger.warning(f"User {user_id}: No active quiz instance found for quiz_id {quiz_id_str_from_callback} or instance is inactive.")
        await safe_send_message(context.bot, chat_id=query.message.chat_id, text="لم يتم العثور على اختبار نشط. ربما انتهى وقته أو حدث خطأ.")
        # Try to send to main menu if possible
        await main_menu_callback(update, context, called_from_fallback=True)
        return ConversationHandler.END

    # Let QuizLogic handle the answer and determine the next state.
    next_state_from_logic = await quiz_instance.handle_answer(bot=context.bot, context=context, update=update)
    logger.info(f"[quiz.py] process_answer: quiz_logic.handle_answer returned {next_state_from_logic} for user {user_id}, quiz {quiz_id_str_from_callback}")

    # Check if the quiz has finished after handling the answer
    if quiz_instance.is_finished():
        logger.info(f"Quiz {quiz_id_str_from_callback} finished for user {user_id}. Preparing to update stats.")
        # --- STATS UPDATE --- 
        try:
            final_score_percentage = (quiz_instance.score / quiz_instance.total_questions) * 100 if quiz_instance.total_questions > 0 else 0
            total_questions_in_quiz = quiz_instance.total_questions
            correct_answers_count = quiz_instance.score
            incorrect_answers_count = total_questions_in_quiz - correct_answers_count
            quiz_name_for_stats = quiz_instance.quiz_name if quiz_instance.quiz_name else quiz_instance.quiz_type
            
            update_user_stats_in_json(
                user_id=user_id,
                score=final_score_percentage,
                total_questions_in_quiz=total_questions_in_quiz,
                correct_answers_count=correct_answers_count,
                incorrect_answers_count=incorrect_answers_count,
                quiz_id=quiz_name_for_stats 
            )
            logger.info(f"Successfully called update_user_stats_in_json for user {user_id} for quiz {quiz_name_for_stats}.")
        except Exception as e_stats:
            logger.error(f"Failed to update JSON stats for user {user_id} for quiz {quiz_name_for_stats}: {e_stats}", exc_info=True)
        # ---------------------
        
        # Cleanup quiz session from user_data as it's finished
        # This is now handled inside quiz_logic.show_results -> cleanup_quiz_data
        # However, double-checking or ensuring quiz_instance.active is False is good.
        # if "quiz_sessions" in context.user_data and quiz_id_str_from_callback in context.user_data["quiz_sessions"]:
        #     del context.user_data["quiz_sessions"][quiz_id_str_from_callback]
        #     if not context.user_data["quiz_sessions"]:
        #         del context.user_data["quiz_sessions"]
        # logger.info(f"Cleaned up quiz session {quiz_id_str_from_callback} for user {user_id} after normal completion.")
        return MAIN_MENU # Or whatever state quiz_logic.show_results returns (should be END or a state that leads to menu)
    else:
        # The send_question call was removed from here as it's handled by quiz_logic.handle_answer
        # next_state = await quiz_logic.send_question(context.bot, context, user_id)
        # logger.info(f"[quiz.py] process_answer: send_question returned {next_state} for user {user_id} after handle_answer.")
        # return next_state 
        return TAKING_QUIZ # Remain in TAKING_QUIZ state as determined by quiz_logic

async def handle_quiz_timeout_in_conv_handler(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id # Should be available from update or job context
    
    # Retrieve necessary data from context.job.data if this is called by a job
    # For direct calls or fallbacks, data might be in user_data
    job_data = context.job.data if context.job else {}
    quiz_id_from_job = job_data.get("quiz_id")
    question_index_from_job = job_data.get("question_index")

    logger.warning(f"[quiz.py] handle_quiz_timeout_in_conv_handler called for user {user_id}, quiz_id (from job): {quiz_id_from_job}, q_idx (from job): {question_index_from_job}")

    quiz_instance = None
    if quiz_id_from_job and "quiz_sessions" in context.user_data:
        quiz_instance = context.user_data["quiz_sessions"].get(quiz_id_from_job)

    if quiz_instance and quiz_instance.active and quiz_instance.current_question_index == question_index_from_job:
        logger.info(f"Processing timeout for user {user_id}, quiz {quiz_id_from_job}, question {question_index_from_job} via question_timeout_callback_wrapper.")
        # The actual timeout logic (sending feedback, next question/results) is in question_timeout_callback_wrapper
        # This handler's main role is to catch the timeout if it somehow bubbles up or needs explicit state transition.
        # Typically, the job itself handles the logic and state changes via QuizLogic methods.
        # We might just ensure the conversation ends or moves to an appropriate state if the job didn't.
        if quiz_instance.is_finished():
            logger.info(f"Quiz {quiz_id_from_job} is finished after timeout processing. Returning MAIN_MENU.")
            return MAIN_MENU
        else:
            logger.info(f"Quiz {quiz_id_from_job} not finished after timeout. Returning TAKING_QUIZ.")
            return TAKING_QUIZ
    else:
        logger.warning(f"User {user_id}: Timeout callback for quiz {quiz_id_from_job} (q_idx {question_index_from_job}) but quiz not active or index mismatch. Conversation may end or ignore.")
        # Fallback: try to show main menu to avoid user getting stuck
        await main_menu_callback(update, context, called_from_fallback=True)
        return ConversationHandler.END

# Conversation Handler for Quiz
quiz_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(quiz_menu_entry, pattern="^start_quiz$")],
    states={
        SELECT_QUIZ_TYPE: [CallbackQueryHandler(select_quiz_type, pattern="^quiz_type_|^main_menu$|^quiz_type_back_to_type_selection$")],
        SELECT_COURSE_FOR_UNIT_QUIZ: [CallbackQueryHandler(select_course_for_unit_quiz, pattern="^quiz_course_select_|^quiz_course_page_|^quiz_type_back_to_type_selection$")],
        SELECT_UNIT_FOR_COURSE: [CallbackQueryHandler(select_unit_for_course, pattern="^quiz_unit_select_|^quiz_unit_page_|^quiz_unit_back_to_course_selection$")],
        ENTER_QUESTION_COUNT: [CallbackQueryHandler(select_question_count, pattern="^num_questions_|^quiz_count_back_to_unit_selection_|^quiz_type_back_to_type_selection$")],
        TAKING_QUIZ: [CallbackQueryHandler(process_answer, pattern="^ans_")],
        # SHOWING_RESULTS is implicitly handled by QuizLogic.show_results which should return END or a state leading to menu.
        # If QuizLogic.show_results returns a specific state for results, it should be listed here.
        # For now, assuming it transitions to END and main_menu is handled globally or by fallbacks.
    },
    fallbacks=[
        CommandHandler("start", start_command_fallback_for_quiz), # Handles /start during quiz
        CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"), # Handles main_menu button within conversation states
        # A generic timeout handler for the conversation itself, if needed.
        # MessageHandler(filters.ALL, fallback_handler) # Example generic fallback
    ],
    map_to_parent={
        # If this conversation is part of a larger one, map END to a parent state
        END: MAIN_MENU, # Example: END from quiz returns to MAIN_MENU state of parent
        MAIN_MENU: MAIN_MENU # Explicitly map MAIN_MENU to itself or parent's MAIN_MENU
    },
    per_message=False,
    name="quiz_conversation",
    persistent=True, # Make sure persistence is configured in ApplicationBuilder
    # allow_reentry=True # Consider if users should be able to re-enter easily
)

# IMPORTANT: Instructions for the user:
# To make the "القائمة الرئيسية" (main_menu) button work globally, especially after a conversation ends,
# you need to add a global CallbackQueryHandler to your application dispatcher in your main bot script (e.g., bot.py).
# This handler should be added BEFORE other ConversationHandlers if there's a pattern conflict,
# though for a specific pattern like "^main_menu$" it's usually fine.
#
# Example of what to add in your main bot script where you set up your application:
#
# from telegram.ext import Application, CallbackQueryHandler
# from handlers.common import main_menu_callback # Ensure this path is correct
#
# # ... (your other imports and bot setup) ...
#
# async def post_init(application: Application):
#     # This is a good place to ensure commands are set, etc.
#     await application.bot.set_my_commands([
#         # ... your commands ...
#         ("start", "▶️ بدء التفاعل مع البوت"),
#         ("quiz", "🧠 بدء اختبار جديد"),
#         # ... other commands ...
#     ])
#
# if __name__ == "__main__":
#     persistence = PicklePersistence(filepath=BOT_CONVERSATION_PERSISTENCE_FILE)
#     application = Application.builder().token(TELEGRAM_BOT_TOKEN).persistence(persistence).post_init(post_init).build()
#
#     # Add your ConversationHandlers (like quiz_conv_handler, etc.)
#     application.add_handler(quiz_conv_handler)
#     # ... add other conversation handlers ...
#
#     # ADD THIS GLOBAL HANDLER FOR MAIN MENU:
#     application.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
#
#     # ... (rest of your application setup and run code) ...
#     application.run_polling()
#
# By adding this global handler, any "main_menu" callback will be caught and processed by main_menu_callback,
# effectively ending any active conversation (if main_menu_callback is designed to do so, which it is)
# and showing the main menu.

