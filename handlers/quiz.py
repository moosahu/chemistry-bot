# -*- coding: utf-8 -*-
"""Conversation handler for the quiz selection and execution flow (Corrected v6 - QuizLogic ID and callback_data fix)."""

import logging
import math
import random
import re # Added for parsing callback_data
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
from .quiz_logic import QuizLogic

ITEMS_PER_PAGE = 6

# --- Helper Function for /start fallback ---
async def start_command_fallback_for_quiz(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} sent /start during an active or lingering quiz conversation. Ending current quiz conversation and showing main menu.")
    
    # Clean up quiz sessions more robustly
    if "quiz_sessions" in context.user_data:
        for quiz_id, quiz_instance in list(context.user_data["quiz_sessions"].items()): # Iterate over a copy
            if hasattr(quiz_instance, 'user_id') and quiz_instance.user_id == user_id:
                try:
                    if hasattr(quiz_instance, 'quiz_id') and hasattr(quiz_instance, 'current_question_index'):
                        timer_job_name = f"qtimer_{user_id}_{update.effective_chat.id}_{quiz_instance.quiz_id}_{quiz_instance.current_question_index}"
                        remove_job_if_exists(timer_job_name, context)
                    if hasattr(quiz_instance, 'cleanup_quiz_data'): # Call cleanup if exists
                         quiz_instance.cleanup_quiz_data(context, quiz_instance.quiz_id)
                    logger.info(f"Cleaned up quiz session {quiz_id} for user {user_id} during /start fallback.")
                except Exception as e_cleanup:
                    logger.error(f"Error during quiz_logic cleanup for quiz {quiz_id} in start_command_fallback: {e_cleanup}")
                context.user_data["quiz_sessions"].pop(quiz_id, None)
        if not context.user_data["quiz_sessions"]:
            context.user_data.pop("quiz_sessions", None)

    # Also remove the old single quiz logic key if it exists
    if 'current_quiz_logic' in context.user_data:
        del context.user_data['current_quiz_logic']

    keys_to_pop = [
        'selected_quiz_type_key', 'selected_quiz_type_display_name', 'questions_for_quiz',
        'selected_course_id_for_unit_quiz', 'available_courses_for_unit_quiz',
        'current_course_page_for_unit_quiz', 'selected_course_name_for_unit_quiz',
        'available_units_for_course', 'current_unit_page_for_course',
        'selected_unit_id', 'selected_unit_name', 'question_count_for_quiz'
    ]
    for key in list(context.user_data.keys()):
        if key.startswith("quiz_setup_") or key.startswith("qtimer_") or key in keys_to_pop:
             context.user_data.pop(key, None)

    logger.info(f"Cleared quiz-related user_data for user {user_id} due to /start fallback in quiz conversation.")

    await main_menu_callback(update, context) 
    return ConversationHandler.END

# --- Keyboard Creation Helper Functions (Assumed unchanged, keeping original) ---
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
        keyboard.append([InlineKeyboardButton(course.get('name', f"مقرر {course.get('id')}"), callback_data=f"quiz_course_select_{course.get('id')}")])

    pagination_buttons = []
    if current_page > 0:
        pagination_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"quiz_course_page_{current_page - 1}"))
    if end_index < len(courses):
        pagination_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"quiz_course_page_{current_page + 1}"))
    
    if pagination_buttons:
        keyboard.append(pagination_buttons)

    keyboard.append([InlineKeyboardButton("🔙 اختيار نوع الاختبار", callback_data=f"quiz_type_back_to_type_selection")])
    return InlineKeyboardMarkup(keyboard)

def create_unit_selection_keyboard(units: list, course_id: str, current_page: int = 0) -> InlineKeyboardMarkup:
    keyboard = []
    items_per_page = ITEMS_PER_PAGE
    start_index = current_page * items_per_page
    end_index = start_index + items_per_page

    for i in range(start_index, min(end_index, len(units))):
        unit = units[i]
        keyboard.append([InlineKeyboardButton(unit.get('name', f"وحدة {unit.get('id')}"), callback_data=f"quiz_unit_select_{course_id}_{unit.get('id')}")])

    pagination_buttons = []
    if current_page > 0:
        pagination_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"quiz_unit_page_{course_id}_{current_page - 1}"))
    if end_index < len(units):
        pagination_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"quiz_unit_page_{course_id}_{current_page + 1}"))

    if pagination_buttons:
        keyboard.append(pagination_buttons)
    
    keyboard.append([InlineKeyboardButton("🔙 اختيار المقرر", callback_data=f"quiz_unit_back_to_course_selection")])
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
            keyboard.append([InlineKeyboardButton(f"الكل ({max_questions})", callback_data=f"num_questions_all")])

    if quiz_type == QUIZ_TYPE_UNIT and course_id_for_unit and unit_id:
        back_callback_data = f"quiz_count_back_to_unit_selection_{course_id_for_unit}" 
    else:
        back_callback_data = f"quiz_type_back_to_type_selection"

    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback_data)])
    return InlineKeyboardMarkup(keyboard)

# --- Conversation Handler States and Functions ---

async def quiz_menu_entry(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    logger.info(f"User {user_id} entered quiz menu (quiz_menu_entry) via {query.data}.")
    keys_to_clear_on_entry = [
        'selected_quiz_type_key', 'selected_quiz_type_display_name', 'questions_for_quiz',
        'selected_course_id_for_unit_quiz', 'available_courses_for_unit_quiz',
        'current_course_page_for_unit_quiz', 'selected_course_name_for_unit_quiz',
        'available_units_for_course', 'current_unit_page_for_course',
        'selected_unit_id', 'selected_unit_name', 'question_count_for_quiz',
        'current_quiz_logic' # Also clear the old single quiz logic key
    ]
    for key in keys_to_clear_on_entry:
        context.user_data.pop(key, None)
    # Ensure quiz_sessions for the user is also cleared or handled if needed at this stage
    # For now, assuming quiz_sessions are managed primarily by quiz_id and cleaned up on end/error
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
    logger.info(f"User {user_id} selected quiz type: {quiz_type_key} ({quiz_type_display_name})")

    error_message_to_user = "عذراً، حدث خطأ أثناء جلب البيانات. يرجى المحاولة لاحقاً أو التأكد من أن خدمة الأسئلة تعمل."
    api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."

    if quiz_type_key == QUIZ_TYPE_ALL:
        logger.debug("[API] QUIZ_TYPE_ALL: Fetching all questions directly.")
        all_questions_pool = fetch_from_api("api/v1/questions/all")
        
        if all_questions_pool == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        if not all_questions_pool or not isinstance(all_questions_pool, list):
            logger.error(f"[API] Failed to fetch or parse questions for QUIZ_TYPE_ALL. Received: {all_questions_pool}")
            logger.info("[API] QUIZ_TYPE_ALL: Fallback - Fetching all courses then questions per course.")
            courses = fetch_from_api("api/v1/courses")
            if courses == "TIMEOUT":
                await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_quiz_type_keyboard())
                return SELECT_QUIZ_TYPE
            if not courses or not isinstance(courses, list):
                logger.error(f"[API] Fallback failed: Could not fetch courses for QUIZ_TYPE_ALL. Received: {courses}")
                await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=error_message_to_user, reply_markup=create_quiz_type_keyboard())
                return SELECT_QUIZ_TYPE

            all_questions_pool = []
            for course in courses:
                course_id = course.get('id')
                if not course_id: continue
                current_course_questions = fetch_from_api(f"api/v1/courses/{course_id}/questions")
                if current_course_questions == "TIMEOUT": 
                    logger.warning(f"[API] Timeout fetching questions for course {course_id} in QUIZ_TYPE_ALL fallback. Skipping.")
                    continue 
                if isinstance(current_course_questions, list):
                    all_questions_pool.extend(current_course_questions)
                else:
                    logger.warning(f"[API] No questions or invalid data for course {course_id} in QUIZ_TYPE_ALL fallback. Received: {current_course_questions}")
            
        if not all_questions_pool:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لم يتم العثور على أسئلة للاختبار الشامل.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        
        context.user_data[f"quiz_setup_{quiz_type_key}_all"] = {
            'questions': all_questions_pool,
            'quiz_name': quiz_type_display_name
        }
        context.user_data["selected_unit_id"] = "all"

        max_questions = len(all_questions_pool)
        keyboard = create_question_count_keyboard(max_questions, quiz_type_key, unit_id="all")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"""اختر عدد الأسئلة لاختبار \n'{quiz_type_display_name}':""", reply_markup=keyboard)
        return ENTER_QUESTION_COUNT

    elif quiz_type_key == QUIZ_TYPE_UNIT:
        logger.debug("[API] QUIZ_TYPE_UNIT: Fetching all courses to select from.")
        courses = fetch_from_api("api/v1/courses")
        if courses == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        if not courses or not isinstance(courses, list) or not courses:
            logger.error(f"[API] Failed to fetch or parse courses for unit selection. Received: {courses}")
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لا توجد مقررات متاحة حالياً أو حدث خطأ في جلبها.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        
        context.user_data["available_courses_for_unit_quiz"] = courses
        context.user_data["current_course_page_for_unit_quiz"] = 0
        keyboard = create_course_selection_keyboard(courses, 0)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="اختر المقرر الدراسي أولاً:", reply_markup=keyboard)
        return SELECT_COURSE_FOR_UNIT_QUIZ

    else:
        logger.warning(f"Unknown quiz type key: {quiz_type_key}. Returning to type selection.")
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
            logger.error(f"User {user_id} selected a course ID ({selected_course_id}) that was not found in the available list.")
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ في اختيار المقرر. يرجى المحاولة مرة أخرى.", reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ

        context.user_data["selected_course_id_for_unit_quiz"] = selected_course_id
        context.user_data["selected_course_name_for_unit_quiz"] = selected_course.get("name", f"مقرر {selected_course_id}")
        logger.info(f"User {user_id} selected course: {selected_course_id} ({selected_course.get('name')})")

        units = fetch_from_api(f"api/v1/courses/{selected_course_id}/units")
        api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
        error_message_to_user = "عذراً، حدث خطأ أثناء جلب الوحدات الدراسية لهذا المقرر."

        if units == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
        if not units or not isinstance(units, list) or not units:
            logger.error(f"[API] Failed to fetch or parse units for course {selected_course_id}. Received: {units}")
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لا توجد وحدات دراسية متاحة لهذا المقرر حالياً.", reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ

        context.user_data["available_units_for_course"] = units
        context.user_data["current_unit_page_for_course"] = 0
        keyboard = create_unit_selection_keyboard(units, selected_course_id, 0)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"""اختر الوحدة الدراسية للمقرر \"{selected_course.get('name', selected_course_id)}\":""", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    
    return SELECT_COURSE_FOR_UNIT_QUIZ

async def select_unit_for_course(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data

    selected_course_id = context.user_data.get("selected_course_id_for_unit_quiz")
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
        parts = callback_data.split('_')
        new_page = int(parts[-1])
        context.user_data["current_unit_page_for_course"] = new_page
        keyboard = create_unit_selection_keyboard(available_units, selected_course_id, new_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"""اختر الوحدة الدراسية للمقرر \"{selected_course_name}\":""", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE

    elif callback_data.startswith("quiz_unit_select_"):
        parts = callback_data.split('_')
        selected_unit_id = parts[-1]
        selected_unit = next((u for u in available_units if str(u.get("id")) == selected_unit_id), None)

        if not selected_unit:
            logger.error(f"User {user_id} selected a unit ID ({selected_unit_id}) that was not found for course {selected_course_id}.")
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ في اختيار الوحدة. يرجى المحاولة مرة أخرى.", reply_markup=create_unit_selection_keyboard(available_units, selected_course_id, current_unit_page))
            return SELECT_UNIT_FOR_COURSE

        context.user_data["selected_unit_id"] = selected_unit_id
        context.user_data["selected_unit_name"] = selected_unit.get("name", f"وحدة {selected_unit_id}")
        logger.info(f"User {user_id} selected unit: {selected_unit_id} ({selected_unit.get('name')}) for course {selected_course_id}")

        questions_for_unit = fetch_from_api(f"api/v1/units/{selected_unit_id}/questions")
        api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
        error_message_to_user = "عذراً، حدث خطأ أثناء جلب أسئلة هذه الوحدة."

        if questions_for_unit == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_unit_selection_keyboard(available_units, selected_course_id, current_unit_page))
            return SELECT_UNIT_FOR_COURSE
        if not questions_for_unit or not isinstance(questions_for_unit, list) or not questions_for_unit:
            logger.error(f"[API] Failed to fetch or parse questions for unit {selected_unit_id}. Received: {questions_for_unit}")
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لا توجد أسئلة متاحة لهذه الوحدة حالياً.", reply_markup=create_unit_selection_keyboard(available_units, selected_course_id, current_unit_page))
            return SELECT_UNIT_FOR_COURSE
        
        quiz_type_key = context.user_data.get("selected_quiz_type_key")
        context.user_data[f"quiz_setup_{quiz_type_key}_{selected_unit_id}"] = {
            'questions': questions_for_unit,
            'quiz_name': f"{selected_course_name} - {selected_unit.get('name', f'وحدة {selected_unit_id}')}"
        }

        max_questions = len(questions_for_unit)
        keyboard = create_question_count_keyboard(max_questions, quiz_type_key, unit_id=selected_unit_id, course_id_for_unit=selected_course_id)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"""اختر عدد الأسئلة لاختبار \n'{selected_course_name} - {selected_unit.get('name', '')}':""", reply_markup=keyboard)
        return ENTER_QUESTION_COUNT

    return SELECT_UNIT_FOR_COURSE

async def select_question_count(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    callback_data = query.data

    quiz_type_key = context.user_data.get("selected_quiz_type_key")
    scope_identifier = context.user_data.get("selected_unit_id")

    if not quiz_type_key or not scope_identifier:
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، يبدو أن معلومات إعداد الاختبار غير كاملة. يرجى المحاولة من البداية.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    num_questions_str = callback_data.replace("num_questions_", "", 1)
    quiz_setup_data_key = f"quiz_setup_{quiz_type_key}_{scope_identifier}"
    quiz_setup_data = context.user_data.get(quiz_setup_data_key)

    if not quiz_setup_data:
        logger.error(f"Quiz setup data not found for key: {quiz_setup_data_key}")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، بيانات إعداد الاختبار مفقودة. يرجى إعادة المحاولة.")
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    all_questions_for_scope = quiz_setup_data.get('questions', [])
    quiz_name_from_setup = quiz_setup_data.get('quiz_name', "اختبار")

    if not all_questions_for_scope:
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لا توجد أسئلة متاحة لهذا النطاق المحدد.")
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE
        
    if num_questions_str == "all":
        num_questions = len(all_questions_for_scope)
        selected_questions_final = all_questions_for_scope
    else:
        try:
            num_questions = int(num_questions_str)
            if num_questions <= 0: raise ValueError("Number of questions must be positive.")
            if num_questions > len(all_questions_for_scope):
                logger.warning(f"Requested {num_questions} but only {len(all_questions_for_scope)} available. Using all available.")
                num_questions = len(all_questions_for_scope)
                selected_questions_final = all_questions_for_scope
            else:
                selected_questions_final = random.sample(all_questions_for_scope, num_questions)
        except ValueError:
            logger.error(f"Invalid number of questions string: {num_questions_str}")
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عدد الأسئلة المحدد غير صالح. يرجى المحاولة مرة أخرى.")
            keyboard = create_quiz_type_keyboard()
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
            return SELECT_QUIZ_TYPE
    
    if not selected_questions_final:
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لم يتم اختيار أسئلة. يرجى المحاولة مرة أخرى.")
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    quiz_logic = QuizLogic(
        bot_instance=context.bot, 
        user_id=user_id, 
        quiz_type=quiz_type_key,
        questions_data=selected_questions_final, 
        total_questions=num_questions, 
        question_time_limit=DEFAULT_QUESTION_TIME_LIMIT,
        context=context
    )

    # Store QuizLogic instance using its unique quiz_id
    if "quiz_sessions" not in context.user_data:
        context.user_data["quiz_sessions"] = {}
    context.user_data["quiz_sessions"][quiz_logic.quiz_id] = quiz_logic
    # Remove the old single instance key if it exists
    context.user_data.pop('current_quiz_logic', None)
    
    quiz_type_display_name = context.user_data.get("selected_quiz_type_display_name", quiz_type_key)
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

    logger.info(f"QuizLogic instance {quiz_logic.quiz_id} created for user {user_id}. Starting quiz '{quiz_name_from_setup}'{scope_display_name} with {num_questions} questions.")
    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"⏳ يتم الآن إعداد اختبارك{scope_display_name} بـ {num_questions} سؤال. لحظات قليلة...")
    
    return await quiz_logic.start_quiz(update, query.message.chat_id, user_id)

async def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data # e.g., ans_quizid_qindex_optionid

    quiz_id_from_callback = None
    if callback_data.startswith("ans_"):
        try:
            # ans_{quiz_id}_{question_index}_{option_id}
            parts = callback_data.split("_")
            quiz_id_from_callback = parts[1]
        except IndexError:
            logger.error(f"User {user_id} sent answer with malformed callback_data: {callback_data}")
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، حدث خطأ في معالجة إجابتك. يرجى المحاولة مرة أخرى أو بدء اختبار جديد.")
            # Optionally, try to end the conversation or go to main menu
            # await main_menu_callback(update, context)
            # return ConversationHandler.END 
            # For now, let's assume the quiz might still be recoverable or the user can navigate
            return TAKING_QUIZ # Stay in quiz, user might try again or timer will advance

    quiz_logic = None
    if quiz_id_from_callback and "quiz_sessions" in context.user_data:
        quiz_logic = context.user_data["quiz_sessions"].get(quiz_id_from_callback)
    
    if not quiz_logic:
        logger.warning(f"User {user_id} (chat {query.message.chat_id}) tried to answer (data: {callback_data}), but no active quiz logic found for quiz_id '{quiz_id_from_callback}'. Active sessions: {list(context.user_data.get('quiz_sessions', {}).keys())}")
        # Check if there's ANY quiz active for this user, even if ID doesn't match (e.g. old message)
        active_user_quizzes = []
        if "quiz_sessions" in context.user_data:
            for q_id, q_instance in context.user_data["quiz_sessions"].items():
                if hasattr(q_instance, 'user_id') and q_instance.user_id == user_id and hasattr(q_instance, 'is_active') and q_instance.is_active:
                    active_user_quizzes.append(q_id)
        
        if active_user_quizzes:
            logger.warning(f"User {user_id} has other active quiz sessions: {active_user_quizzes}. The callback might be for an old message from a different quiz instance.")
            # Try to inform the user that this specific button might be from an old quiz
            try:
                await query.edit_message_text(text="لا يمكن التفاعل مع هذا السؤال الآن. قد يكون من اختبار سابق أو تم إرسال سؤال أحدث. يرجى التفاعل مع أحدث رسالة اختبار.")
            except Exception as e_edit_old_ans_msg:
                logger.error(f"Failed to edit old answer message for user {user_id}: {e_edit_old_ans_msg}")
            return TAKING_QUIZ # Stay in the current state of the conversation
        else:
            logger.info(f"No active quiz sessions found for user {user_id} when trying to answer. Sending to main menu.")
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لا يوجد اختبار نشط حالياً أو انتهت صلاحية هذا الاختبار. يرجى البدء من جديد.")
            await main_menu_callback(update, context)
            return ConversationHandler.END

    # Ensure the quiz instance belongs to the user who clicked the button
    if quiz_logic.user_id != user_id:
        logger.warning(f"User {user_id} tried to answer for a quiz belonging to user {quiz_logic.user_id}. Ignoring.")
        return TAKING_QUIZ

    return await quiz_logic.handle_answer(update, callback_data) # Pass the full callback_data

async def quiz_timeout(context: CallbackContext) -> None:
    job_data = context.job.data
    user_id = job_data["user_id"]
    chat_id = job_data["chat_id"]
    quiz_id_from_job = job_data.get("quiz_id")
    question_idx_from_job = job_data.get("question_idx")
    message_id_to_edit = job_data.get("message_id_to_edit")

    quiz_logic = None
    if quiz_id_from_job and "quiz_sessions" in context.user_data:
        quiz_logic = context.user_data["quiz_sessions"].get(quiz_id_from_job)

    if not quiz_logic or quiz_logic.user_id != user_id or quiz_logic.current_question_index != question_idx_from_job:
        logger.info(f"Quiz timeout job executed for user {user_id}, quiz {quiz_id_from_job}, q_idx {question_idx_from_job}, but current quiz state does not match or quiz_logic missing. Ignoring.")
        return

    logger.info(f"Timeout for user {user_id}, quiz {quiz_logic.quiz_id}, question index {quiz_logic.current_question_index}")
    # The handle_timeout in QuizLogic should now manage its own state and potentially call end_quiz
    next_state = await quiz_logic.handle_timeout(chat_id, message_id_to_edit)
    
    # If handle_timeout signals the quiz has ended (e.g., by returning END or SHOWING_RESULTS)
    # and QuizLogic itself doesn't clean up its instance from quiz_sessions, we might need to do it here.
    # However, it's better if QuizLogic's end_quiz method handles its own removal from context.user_data['quiz_sessions']
    # This is now handled by QuizLogic.end_quiz calling self.cleanup_quiz_data(self.quiz_id)

async def quiz_results(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    # This state is typically entered via a callback from QuizLogic (e.g., after last question or explicit end)
    # The quiz_id should be part of the callback_data if this is triggered by a button after quiz ends.
    # For now, assuming QuizLogic has placed its instance or results in a known place or the callback_data contains quiz_id.

    quiz_id_from_callback = None # Placeholder, needs to be determined if this is a direct callback
    # Example: if callback_data is "show_results_quizid123"
    # if query.data and query.data.startswith("show_results_"):
    #    quiz_id_from_callback = query.data.replace("show_results_", "", 1)

    quiz_logic = None
    # Attempt to find the relevant quiz_logic instance
    # This part is tricky if quiz_results is a generic state. 
    # Ideally, the QuizLogic instance that just finished would trigger this and pass its data or ID.
    
    # Let's assume for now that QuizLogic.end_quiz or handle_answer (for last q) transitions here
    # AND that the quiz_logic instance is still findable, or its results are stored.
    # The `quiz_logic_v23_state_fixes.py` has `end_quiz` which calls `show_results` internally.
    # So, this state might be less used if QuizLogic handles showing results directly before ending.

    # Fallback: Try to find the *last* quiz session for the user if no specific ID is given
    # This is not robust if multiple quizzes were run and not cleaned properly.
    if "quiz_sessions" in context.user_data:
        user_quiz_ids = [qid for qid, q_inst in context.user_data["quiz_sessions"].items() if hasattr(q_inst, 'user_id') and q_inst.user_id == user_id]
        if user_quiz_ids: # Get the one most likely to be the one we need results for (e.g. last one if not cleaned)
            # This is a guess. A more robust way is needed if this state is entered independently.
            # For now, we assume QuizLogic.show_results is called directly by the instance.
            # This function might be redundant if QuizLogic.end_quiz handles showing results and then cleans up.
            pass # quiz_logic = context.user_data["quiz_sessions"].get(user_quiz_ids[-1]) 

    # The QuizLogic.show_results is now called internally by QuizLogic.end_quiz.
    # This handler might not be strictly necessary in the ConversationHandler if QuizLogic manages its full lifecycle display.
    # However, if it's a fallback or an explicit button to re-show results for a *specific* quiz, it needs quiz_id.

    # For now, let's assume this state is primarily for the ConversationHandler structure
    # and the actual display is handled by QuizLogic instance methods called before reaching here.
    # If a quiz_logic instance *was* passed or found, its show_results would have been called.
    
    # If this state is reached and no quiz_logic is active or found, it's likely an old state or error.
    # The common.py main_menu_callback handles the 
