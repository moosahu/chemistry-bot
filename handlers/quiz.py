# -*- coding: utf-8 -*-
"""Conversation handler for the quiz selection and execution flow (v9 - Handler Fix)."""

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
from handlers.common import create_main_menu_keyboard, main_menu_callback 
from .quiz_logic import QuizLogic, question_timeout_callback_wrapper 

# --- ADDED IMPORT FOR STATS UPDATE ---
from handlers.stats import update_user_stats_in_json
# -------------------------------------

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
        new_page = int(parts[-1])
        context.user_data["current_unit_page_for_course"] = new_page
        keyboard = create_unit_selection_keyboard(units, selected_course_id, new_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية للمقرر \"{context.user_data.get('selected_course_name_for_unit_quiz', '')}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data.startswith("quiz_unit_select_"):
        parts = callback_data.split("_")
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
            "quiz_name": f"{context.user_data.get('selected_course_name_for_unit_quiz', '')}: {selected_unit_name}"
        }
        max_questions = len(questions)
        keyboard = create_question_count_keyboard(max_questions, context.user_data["selected_quiz_type_key"], selected_unit_id, selected_course_id)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار \n\"{context.user_data.get('selected_course_name_for_unit_quiz', '')}: {selected_unit_name}\":", reply_markup=keyboard)
        return ENTER_QUESTION_COUNT
    return SELECT_UNIT_FOR_COURSE 

async def select_question_count(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data
    quiz_type = context.user_data.get("selected_quiz_type_key")
    unit_id = context.user_data.get("selected_unit_id") 
    course_id_for_unit = context.user_data.get("selected_course_id_for_unit_quiz") 
    quiz_setup_key = f"quiz_setup_{quiz_type}_{unit_id}"
    quiz_data = context.user_data.get(quiz_setup_key, {})
    all_questions = quiz_data.get("questions", [])
    max_questions = len(all_questions)
    if callback_data.startswith("quiz_count_back_to_unit_selection_"):
        course_id_from_cb = callback_data.split("_")[-1]
        units = context.user_data.get("available_units_for_course", [])
        unit_page = context.user_data.get("current_unit_page_for_course", 0)
        keyboard = create_unit_selection_keyboard(units, course_id_from_cb, unit_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية للمقرر \"{context.user_data.get('selected_course_name_for_unit_quiz', '')}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data == "quiz_type_back_to_type_selection": 
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE
    if not all_questions:
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذرًا، لا توجد أسئلة متاحة لهذا الاختبار. يرجى إعادة المحاولة من البداية.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE
    if callback_data == "num_questions_all":
        question_count = max_questions
    elif callback_data.startswith("num_questions_"):
        try:
            question_count = int(callback_data.split("_")[-1])
            if not (0 < question_count <= max_questions):
                raise ValueError("Invalid question count selected")
        except ValueError:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عدد أسئلة غير صالح. يرجى الاختيار من القائمة.", reply_markup=create_question_count_keyboard(max_questions, quiz_type, unit_id, course_id_for_unit))
            return ENTER_QUESTION_COUNT
    else:
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="يرجى اختيار عدد الأسئلة.", reply_markup=create_question_count_keyboard(max_questions, quiz_type, unit_id, course_id_for_unit))
        return ENTER_QUESTION_COUNT
    context.user_data["question_count_for_quiz"] = question_count
    selected_questions = random.sample(all_questions, min(question_count, len(all_questions)))
    context.user_data["questions_for_quiz"] = selected_questions
    quiz_name_for_logic = quiz_data.get("quiz_name", "اختبار مخصص")
    quiz_id_timestamp = int(datetime.utcnow().timestamp())
    quiz_id_str = f"{user_id}_{quiz_type}_{unit_id if unit_id else 'na'}_{quiz_id_timestamp}"
    if "quiz_sessions" not in context.user_data:
        context.user_data["quiz_sessions"] = {}
    quiz_instance = QuizLogic(
        user_id=user_id,
        chat_id=query.message.chat_id,
        questions_data=selected_questions,
        quiz_id=quiz_id_str,
        quiz_name=quiz_name_for_logic,
        question_time_limit=DEFAULT_QUESTION_TIME_LIMIT
    )
    context.user_data["quiz_sessions"][quiz_id_str] = quiz_instance
    logger.info(f"User {user_id} starting quiz {quiz_id_str} ({quiz_name_for_logic}) with {len(selected_questions)} questions.")
    await quiz_instance.send_question(bot=context.bot, context=context, user_id=user_id)
    return TAKING_QUIZ

async def process_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    logger.info(f"[quiz.py] process_answer called for user {user_id} with callback_data: {query.data}")
    await query.answer()
    quiz_id, answer_data = query.data.split(":", 1)
    quiz_instance = context.user_data.get("quiz_sessions", {}).get(quiz_id)
    if not quiz_instance or not isinstance(quiz_instance, QuizLogic) or quiz_instance.user_id != user_id:
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عفواً، هذا الاختبار لم يعد صالحاً أو لا يخصك. يرجى بدء اختبار جديد.", reply_markup=create_main_menu_keyboard())
        return MAIN_MENU 
    timer_job_name = f"qtimer_{user_id}_{query.message.chat_id}_{quiz_id}_{quiz_instance.current_question_index}"
    remove_job_if_exists(timer_job_name, context)
    await quiz_instance.process_answer(context.bot, context, query.message, answer_data)
    if quiz_instance.is_finished():
        logger.info(f"Quiz {quiz_id} finished for user {user_id}. Preparing to update stats.")
        try:
            final_score_percentage = getattr(quiz_instance, "score_percentage", 0.0)
            total_questions_in_quiz = getattr(quiz_instance, "total_questions", len(quiz_instance.questions))
            correct_answers_count = getattr(quiz_instance, "correct_answers_count", 0)
            incorrect_answers_count = getattr(quiz_instance, "incorrect_answers_count", 0)
            quiz_name_for_stats = getattr(quiz_instance, "quiz_name", "unknown_quiz") 

            update_user_stats_in_json(
                user_id=str(user_id),
                score=final_score_percentage,
                total_questions_in_quiz=total_questions_in_quiz,
                correct_answers_count=correct_answers_count,
                incorrect_answers_count=incorrect_answers_count,
                quiz_id=quiz_name_for_stats 
            )
            logger.info(f"Successfully called update_user_stats_in_json for user {user_id} for quiz {quiz_name_for_stats}.")
        except Exception as e_stats:
            logger.error(f"Failed to update JSON stats for user {user_id} for quiz {quiz_name_for_stats}: {e_stats}", exc_info=True)
        
        if "quiz_sessions" in context.user_data and quiz_id in context.user_data["quiz_sessions"]:
            del context.user_data["quiz_sessions"][quiz_id]
            if not context.user_data["quiz_sessions"]:
                del context.user_data["quiz_sessions"]
        logger.info(f"Cleaned up quiz session {quiz_id} for user {user_id} after normal completion.")
        return MAIN_MENU 
    else:
        await quiz_instance.send_current_question(context.bot, context, query.message)
        return TAKING_QUIZ

async def handle_quiz_timeout_in_conv_handler(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    quiz_id = context.user_data.get("current_quiz_id_for_timeout") 
    question_index_from_job = context.user_data.get("timed_out_question_index")
    logger.warning(f"handle_quiz_timeout_in_conv_handler called for user {user_id}, quiz {quiz_id}, q_idx {question_index_from_job}")
    quiz_instance = context.user_data.get("quiz_sessions", {}).get(quiz_id)
    if not quiz_instance or quiz_instance.user_id != user_id or quiz_instance.is_finished():
        logger.warning(f"Timeout for an invalid/finished quiz session {quiz_id} or different user. Ignoring.")
        return TAKING_QUIZ 
    if quiz_instance.current_question_index != question_index_from_job:
        logger.info(f"Timeout for q_idx {question_index_from_job} but quiz {quiz_id} is on q_idx {quiz_instance.current_question_index}. Likely already answered. Ignoring.")
        return TAKING_QUIZ
    logger.info(f"Processing timeout for user {user_id}, quiz {quiz_id}, question {quiz_instance.current_question_index} via conv handler.")
    await quiz_instance.handle_timeout(context.bot, context, original_message_to_edit=None) 
    if quiz_instance.is_finished():
        logger.info(f"Quiz {quiz_id} finished for user {user_id} after timeout. Preparing to update stats.")
        try:
            final_score_percentage = getattr(quiz_instance, "score_percentage", 0.0)
            total_questions_in_quiz = getattr(quiz_instance, "total_questions", len(quiz_instance.questions))
            correct_answers_count = getattr(quiz_instance, "correct_answers_count", 0)
            incorrect_answers_count = getattr(quiz_instance, "incorrect_answers_count", 0)
            quiz_name_for_stats = getattr(quiz_instance, "quiz_name", "unknown_quiz")
            update_user_stats_in_json(
                user_id=str(user_id),
                score=final_score_percentage,
                total_questions_in_quiz=total_questions_in_quiz,
                correct_answers_count=correct_answers_count,
                incorrect_answers_count=incorrect_answers_count,
                quiz_id=quiz_name_for_stats
            )
            logger.info(f"Successfully called update_user_stats_in_json for user {user_id} for quiz {quiz_name_for_stats} (after timeout path).")
        except Exception as e_stats:
            logger.error(f"Failed to update JSON stats for user {user_id} for quiz {quiz_name_for_stats} (after timeout path): {e_stats}", exc_info=True)
        if "quiz_sessions" in context.user_data and quiz_id in context.user_data["quiz_sessions"]:
            del context.user_data["quiz_sessions"][quiz_id]
            if not context.user_data["quiz_sessions"]: del context.user_data["quiz_sessions"]
        logger.info(f"Cleaned up quiz session {quiz_id} for user {user_id} after timeout completion.")
        return MAIN_MENU 
    else:
        await quiz_instance.send_current_question(context.bot, context, message_to_edit_or_reply_to=None) 
        return TAKING_QUIZ

quiz_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(quiz_menu_entry, pattern="^start_quiz$")], # CORRECTED PATTERN
    states={
        SELECT_QUIZ_TYPE: [CallbackQueryHandler(select_quiz_type)],
        SELECT_COURSE_FOR_UNIT_QUIZ: [CallbackQueryHandler(select_course_for_unit_quiz)],
        SELECT_UNIT_FOR_COURSE: [CallbackQueryHandler(select_unit_for_course)],
        ENTER_QUESTION_COUNT: [CallbackQueryHandler(select_question_count)],
        TAKING_QUIZ: [
            CallbackQueryHandler(process_answer, pattern=r"^quiz_.+:.+$"),
        ],
    },
    fallbacks=[
        CommandHandler("start", start_command_fallback_for_quiz),
        CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"),
    ],
    map_to_parent={
        MAIN_MENU: MAIN_MENU,
        ConversationHandler.END : ConversationHandler.END
    },
    persistent=True, 
    name="quiz_conversation"
)


