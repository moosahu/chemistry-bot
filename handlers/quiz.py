# -*- coding: utf-8 -*-
"""Conversation handler for the quiz selection and execution flow (Corrected v4 - Full Course/Unit selection flow and API fixes)."""

import logging
import math
import random
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
    SELECT_COURSE_FOR_UNIT_QUIZ, SELECT_UNIT_FOR_COURSE, # New states for unit quiz flow
    SELECT_QUIZ_SCOPE, # Kept for other potential scoped quizzes, but unit quiz uses new states
    ENTER_QUESTION_COUNT, TAKING_QUIZ, SHOWING_RESULTS, END,
    QUIZ_TYPE_RANDOM, QUIZ_TYPE_CHAPTER, QUIZ_TYPE_UNIT, QUIZ_TYPE_ALL, 
    DEFAULT_QUESTION_TIME_LIMIT
)
from utils.helpers import safe_send_message, safe_edit_message_text, get_quiz_type_string
from utils.api_client import fetch_from_api # Synchronous API fetch function
from handlers.common import create_main_menu_keyboard, main_menu_callback # Assuming main_menu_callback can handle being called from quiz
from .quiz_logic import QuizLogic

ITEMS_PER_PAGE = 6

# --- Helper Function for /start fallback ---
async def start_command_fallback_for_quiz(update: Update, context: CallbackContext) -> int:
    """Handles /start command if received during an active or lingering quiz conversation."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} sent /start during an active or lingering quiz conversation. Ending current quiz conversation and showing main menu.")
    
    # Precautionary cleanup of quiz-related user_data
    if 'current_quiz_logic' in context.user_data:
        del context.user_data['current_quiz_logic']
    
    keys_to_pop = [
        'selected_quiz_type_key', 'selected_quiz_type_display_name', 'questions_for_quiz',
        'selected_course_id_for_unit_quiz', 'available_courses_for_unit_quiz',
        'current_course_page_for_unit_quiz', 'selected_course_name_for_unit_quiz',
        'available_units_for_course', 'current_unit_page_for_course',
        'selected_unit_id', 'selected_unit_name', 'question_count_for_quiz'
    ]
    for key in keys_to_pop:
        context.user_data.pop(key, None)
    logger.info(f"Cleared quiz-related user_data for user {user_id} due to /start fallback in quiz conversation.")

    # Call the main menu function to display the main menu
    # This assumes 'main_menu_callback' is your function that shows the main menu with the 'بدء اختبار جديد' button
    await main_menu_callback(update, context) 

    return ConversationHandler.END # Crucial: This terminates the quiz conversation

# --- Keyboard Creation Helper Functions ---

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

def create_unit_selection_keyboard(units: list, course_id: int, current_page: int = 0) -> InlineKeyboardMarkup:
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

def create_question_count_keyboard(max_questions: int, quiz_type: str, scope_id: str = None, course_id_for_unit: str = None) -> InlineKeyboardMarkup:
    counts = [1, 5, 10, 20, min(max_questions, 50)]
    if max_questions > 0 and max_questions not in counts:
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
    
    if counts and max_questions > counts[-1] if counts else max_questions > 0:
         keyboard.append([InlineKeyboardButton(f"الكل ({max_questions})", callback_data=f"num_questions_all")])

    back_callback_data = f"quiz_count_back_to_type_selection"
    if quiz_type == QUIZ_TYPE_UNIT and course_id_for_unit and scope_id: # scope_id here is unit_id
        back_callback_data = f"quiz_count_back_to_unit_selection_{course_id_for_unit}" 
    elif quiz_type != QUIZ_TYPE_ALL: 
        pass 

    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback_data)])
    return InlineKeyboardMarkup(keyboard)

# --- Conversation Handler States and Functions ---

async def quiz_menu_entry(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    logger.info(f"User {user_id} entered quiz menu (quiz_menu_entry).")
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

    if quiz_type_key == QUIZ_TYPE_ALL:
        logger.debug("[API] QUIZ_TYPE_ALL: Fetching all courses.")
        courses = fetch_from_api("api/v1/courses")
        if courses == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="انتهت مهلة الاتصال بخادم الأسئلة أثناء جلب قائمة المقررات.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        if not courses or not isinstance(courses, list):
            logger.error(f"[API] Failed to fetch or parse courses for QUIZ_TYPE_ALL. Received: {courses}")
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=error_message_to_user, reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE

        all_questions_pool = []
        logger.info(f"[API] Fetched {len(courses)} courses. Now fetching questions for each.")
        for course in courses:
            course_id = course.get('id')
            if not course_id: continue
            current_course_questions = fetch_from_api(f"api/v1/courses/{course_id}/questions")
            if current_course_questions == "TIMEOUT": 
                logger.warning(f"[API] Timeout fetching questions for course {course_id} in QUIZ_TYPE_ALL. Skipping.")
                continue 
            if isinstance(current_course_questions, list):
                all_questions_pool.extend(current_course_questions)
            else:
                logger.warning(f"[API] No questions or invalid data for course {course_id} in QUIZ_TYPE_ALL. Received: {current_course_questions}")
        
        if not all_questions_pool:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لم يتم العثور على أسئلة للاختبار الشامل.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        
        context.user_data["questions_for_quiz"] = all_questions_pool
        max_questions = len(all_questions_pool)
        keyboard = create_question_count_keyboard(max_questions, quiz_type_key)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار '{quiz_type_display_name}':", reply_markup=keyboard)
        return ENTER_QUESTION_COUNT

    elif quiz_type_key == QUIZ_TYPE_UNIT:
        logger.debug("[API] QUIZ_TYPE_UNIT: Fetching all courses to select from.")
        courses = fetch_from_api("api/v1/courses")
        if courses == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="انتهت مهلة الاتصال بخادم الأسئلة أثناء جلب قائمة المقررات.", reply_markup=create_quiz_type_keyboard())
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
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="نوع اختبار غير معروف. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

async def handle_course_selection_for_unit_quiz(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data

    if callback_data == "quiz_type_back_to_type_selection":
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE
    
    if callback_data.startswith("quiz_course_page_"):
        page = int(callback_data.split('_')[-1])
        courses = context.user_data.get("available_courses_for_unit_quiz", [])
        context.user_data["current_course_page_for_unit_quiz"] = page
        keyboard = create_course_selection_keyboard(courses, page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر المقرر الدراسي (صفحة {page + 1}):", reply_markup=keyboard)
        return SELECT_COURSE_FOR_UNIT_QUIZ

    selected_course_id = callback_data.replace("quiz_course_select_", "", 1)
    context.user_data["selected_course_id_for_unit_quiz"] = selected_course_id
    
    courses_list = context.user_data.get("available_courses_for_unit_quiz", [])
    selected_course_obj = next((c for c in courses_list if str(c.get('id')) == str(selected_course_id)), None)
    course_name = selected_course_obj.get('name') if selected_course_obj else f"مقرر {selected_course_id}"
    context.user_data["selected_course_name_for_unit_quiz"] = course_name

    logger.info(f"User {user_id} selected course {selected_course_id} ({course_name}) for unit quiz.")
    logger.debug(f"[API] Fetching units for course ID: {selected_course_id}.")
    units = fetch_from_api(f"api/v1/courses/{selected_course_id}/units")

    if units == "TIMEOUT":
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"انتهت مهلة الاتصال بخادم الأسئلة أثناء جلب وحدات المقرر '{course_name}'.", reply_markup=create_course_selection_keyboard(courses_list, context.user_data.get("current_course_page_for_unit_quiz",0)))
        return SELECT_COURSE_FOR_UNIT_QUIZ
    if not units or not isinstance(units, list) or not units:
        logger.error(f"[API] Failed to fetch or parse units for course {selected_course_id}. Received: {units}")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"عذراً، لا توجد وحدات متاحة للمقرر '{course_name}' حالياً أو حدث خطأ.", reply_markup=create_course_selection_keyboard(courses_list, context.user_data.get("current_course_page_for_unit_quiz",0)))
        return SELECT_COURSE_FOR_UNIT_QUIZ

    context.user_data["available_units_for_course"] = units
    context.user_data["current_unit_page_for_course"] = 0
    keyboard = create_unit_selection_keyboard(units, selected_course_id, 0)
    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر وحدة دراسية من مقرر '{course_name}':", reply_markup=keyboard)
    return SELECT_UNIT_FOR_COURSE

async def handle_unit_selection_for_course(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data
    
    selected_course_id = context.user_data.get("selected_course_id_for_unit_quiz")
    course_name = context.user_data.get("selected_course_name_for_unit_quiz", f"مقرر {selected_course_id}")

    if callback_data == "quiz_unit_back_to_course_selection":
        courses = context.user_data.get("available_courses_for_unit_quiz", [])
        current_page = context.user_data.get("current_course_page_for_unit_quiz", 0)
        keyboard = create_course_selection_keyboard(courses, current_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="اختر المقرر الدراسي أولاً:", reply_markup=keyboard)
        return SELECT_COURSE_FOR_UNIT_QUIZ

    if callback_data.startswith("quiz_unit_page_"):
        parts = callback_data.split('_')
        page = int(parts[-1])
        units = context.user_data.get("available_units_for_course", [])
        context.user_data["current_unit_page_for_course"] = page
        keyboard = create_unit_selection_keyboard(units, selected_course_id, page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر وحدة دراسية من مقرر '{course_name}' (صفحة {page + 1}):", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE

    selected_unit_id = callback_data.replace(f"quiz_unit_select_{selected_course_id}_", "", 1)
    context.user_data["selected_unit_id"] = selected_unit_id
    
    units_list = context.user_data.get("available_units_for_course", [])
    selected_unit_obj = next((u for u in units_list if str(u.get('id')) == str(selected_unit_id)), None)
    unit_name = selected_unit_obj.get('name') if selected_unit_obj else f"وحدة {selected_unit_id}"
    context.user_data["selected_unit_name"] = unit_name

    logger.info(f"User {user_id} selected unit {selected_unit_id} ({unit_name}) from course {selected_course_id} ({course_name}).")
    logger.debug(f"[API] Fetching questions for course {selected_course_id}, unit {selected_unit_id}.")
    
    questions = fetch_from_api(f"api/v1/courses/{selected_course_id}/units/{selected_unit_id}/questions")

    if questions == "TIMEOUT":
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"انتهت مهلة الاتصال بخادم الأسئلة أثناء جلب أسئلة الوحدة '{unit_name}'.", reply_markup=create_unit_selection_keyboard(units_list, selected_course_id, context.user_data.get("current_unit_page_for_course",0)))
        return SELECT_UNIT_FOR_COURSE
    if not questions or not isinstance(questions, list) or not questions:
        logger.error(f"[API] Failed to fetch or parse questions for unit {selected_unit_id}. Received: {questions}")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"عذراً، لا توجد أسئلة متاحة للوحدة '{unit_name}' حالياً أو حدث خطأ.", reply_markup=create_unit_selection_keyboard(units_list, selected_course_id, context.user_data.get("current_unit_page_for_course",0)))
        return SELECT_UNIT_FOR_COURSE

    context.user_data["questions_for_quiz"] = questions
    max_questions = len(questions)
    quiz_type_key = context.user_data.get("selected_quiz_type_key")
    keyboard = create_question_count_keyboard(max_questions, quiz_type_key, scope_id=selected_unit_id, course_id_for_unit=selected_course_id)
    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار الوحدة '{unit_name}' من مقرر '{course_name}':", reply_markup=keyboard)
    return ENTER_QUESTION_COUNT

async def select_question_count(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data

    quiz_type_key = context.user_data.get("selected_quiz_type_key")
    course_id_for_unit = context.user_data.get("selected_course_id_for_unit_quiz")
    unit_id_for_course = context.user_data.get("selected_unit_id")

    if callback_data == "quiz_count_back_to_type_selection":
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE
    elif callback_data.startswith("quiz_count_back_to_unit_selection_"):
        course_id_from_cb = callback_data.split('_')[-1]
        units = context.user_data.get("available_units_for_course", [])
        current_page = context.user_data.get("current_unit_page_for_course", 0)
        course_name = context.user_data.get("selected_course_name_for_unit_quiz", f"مقرر {course_id_from_cb}")
        keyboard = create_unit_selection_keyboard(units, course_id_from_cb, current_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر وحدة دراسية من مقرر '{course_name}':", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE

    all_questions_pool = context.user_data.get("questions_for_quiz", [])
    max_questions = len(all_questions_pool)
    
    if callback_data == "num_questions_all":
        num_questions = max_questions
    else:
        num_questions = int(callback_data.replace("num_questions_", "", 1))

    if num_questions <= 0 or num_questions > max_questions:
        logger.warning(f"User {user_id} selected invalid number of questions: {num_questions}. Max was {max_questions}. Defaulting to max.")
        num_questions = max_questions

    context.user_data["question_count_for_quiz"] = num_questions
    
    # Shuffle and select questions
    random.shuffle(all_questions_pool)
    questions_to_ask = all_questions_pool[:num_questions]

    quiz_type_display = context.user_data.get("selected_quiz_type_display_name", "غير محدد")
    scope_display = ""
    if quiz_type_key == QUIZ_TYPE_UNIT:
        course_name = context.user_data.get("selected_course_name_for_unit_quiz", "N/A")
        unit_name = context.user_data.get("selected_unit_name", "N/A")
        scope_display = f" (المقرر: {course_name}, الوحدة: {unit_name})"
    
    logger.info(f"User {user_id} selected {num_questions} questions for quiz type {quiz_type_key}{scope_display}.")

    # Initialize QuizLogic instance
    quiz_logic = QuizLogic(
        context=context,
        user_id=user_id,
        quiz_type=quiz_type_key,
        questions_data=questions_to_ask,
        total_questions=num_questions,
        question_time_limit=DEFAULT_QUESTION_TIME_LIMIT
    )
    context.user_data["current_quiz_logic"] = quiz_logic
    logger.info(f"Quiz instance created for user {user_id}. Starting quiz with {num_questions} questions.")

    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"⏳ يتم الآن إعداد اختبارك ({quiz_type_display}{scope_display}) بـ {num_questions} سؤال. لحظات قليلة...")
    return await quiz_logic.start_quiz(update) # This will send the first question and return TAKING_QUIZ

async def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    quiz_logic = context.user_data.get("current_quiz_logic")

    if not quiz_logic:
        logger.warning(f"User {user_id} sent an answer, but no active quiz logic found. Ignoring.")
        await query.answer("لا يوجد اختبار نشط حالياً. يرجى بدء اختبار جديد.")
        # Consider ending conversation or redirecting to main menu if this happens unexpectedly
        await main_menu_callback(update, context)
        return ConversationHandler.END 

    logger.debug(f"Passing answer callback {query.data} to QuizLogic instance for user {user_id}")
    next_state = await quiz_logic.handle_answer(update, context)
    
    if next_state == END: # QuizLogic determined the quiz is over
        logger.info(f"Quiz ended by QuizLogic for user {user_id}. Transitioning to END state for ConversationHandler.")
        # QuizLogic's show_results should have cleared its own user_data keys.
        # No need to call main_menu_callback here as QuizLogic handles the final message.
        return ConversationHandler.END
    return next_state # Should be TAKING_QUIZ if quiz continues

async def quiz_timeout_global_fallback(update: Update, context: CallbackContext) -> int:
    """Handles a global timeout for the quiz if user is inactive for too long across states."""
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    chat_id = update.effective_chat.id if update.effective_chat else "UnknownChat"
    logger.warning(f"Quiz conversation timed out globally for user {user_id} in chat {chat_id}.")
    
    quiz_logic = context.user_data.get("current_quiz_logic")
    if quiz_logic and quiz_logic.last_question_message_id:
        try:
            await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=quiz_logic.last_question_message_id, text="انتهى الوقت المخصص للاختبار بسبب عدم النشاط.", reply_markup=None)
        except Exception as e_edit:
            logger.error(f"Error editing last quiz message on global timeout: {e_edit}")
    else:
        await safe_send_message(context.bot, chat_id, "انتهى الوقت المخصص للاختبار بسبب عدم النشاط.")

    # Clean up user_data related to the quiz
    if 'current_quiz_logic' in context.user_data:
        del context.user_data['current_quiz_logic']
    keys_to_pop = [
        'selected_quiz_type_key', 'selected_quiz_type_display_name', 'questions_for_quiz',
        'selected_course_id_for_unit_quiz', 'available_courses_for_unit_quiz',
        'current_course_page_for_unit_quiz', 'selected_course_name_for_unit_quiz',
        'available_units_for_course', 'current_unit_page_for_course',
        'selected_unit_id', 'selected_unit_name', 'question_count_for_quiz'
    ]
    for key in keys_to_pop:
        context.user_data.pop(key, None)
    logger.info(f"Cleared quiz-related user_data for user {user_id} due to global quiz timeout.")

    await main_menu_callback(update, context) # Show main menu
    return ConversationHandler.END

async def cancel_quiz_and_return_to_main_menu(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    logger.info(f"User {user_id} cancelled the quiz or an operation within quiz flow.")

    quiz_logic = context.user_data.get("current_quiz_logic")
    if quiz_logic and quiz_logic.last_question_message_id:
        try:
            # Try to remove keyboard from last question message if quiz was active
            if quiz_logic.last_question_is_image:
                 await context.bot.edit_message_caption(chat_id=chat_id, message_id=quiz_logic.last_question_message_id, caption="تم إلغاء الاختبار.", reply_markup=None)
            else:
                await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=quiz_logic.last_question_message_id, text="تم إلغاء الاختبار.", reply_markup=None)
        except Exception as e_edit_cancel:
            logger.warning(f"Could not edit last quiz message on cancel for user {user_id}: {e_edit_cancel}")
            # If editing fails, send a new message
            await safe_send_message(context.bot, chat_id, "تم إلغاء الاختبار بنجاح.")
    else:
         # If no quiz_logic or last_question_message_id, it means quiz hadn't started or was in selection phase
         # We might be editing a menu message
        if update.callback_query and update.callback_query.message:
            await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=update.callback_query.message.message_id, text="تم إلغاء العملية.", reply_markup=None)
            await asyncio.sleep(0.1) # Brief pause before showing main menu to ensure message edit is seen
        else:
            await safe_send_message(context.bot, chat_id, "تم إلغاء العملية.")

    # Clean up user_data related to the quiz
    if 'current_quiz_logic' in context.user_data:
        del context.user_data['current_quiz_logic']
    keys_to_pop = [
        'selected_quiz_type_key', 'selected_quiz_type_display_name', 'questions_for_quiz',
        'selected_course_id_for_unit_quiz', 'available_courses_for_unit_quiz',
        'current_course_page_for_unit_quiz', 'selected_course_name_for_unit_quiz',
        'available_units_for_course', 'current_unit_page_for_course',
        'selected_unit_id', 'selected_unit_name', 'question_count_for_quiz'
    ]
    for key in keys_to_pop:
        context.user_data.pop(key, None)
    logger.info(f"Cleared quiz-related user_data for user {user_id} due to cancellation.")

    await main_menu_callback(update, context) # Show main menu
    return ConversationHandler.END

# --- Conversation Handler Definition ---
quiz_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(quiz_menu_entry, pattern='^start_quiz$')],
    states={
        SELECT_QUIZ_TYPE: [CallbackQueryHandler(select_quiz_type)],
        SELECT_COURSE_FOR_UNIT_QUIZ: [CallbackQueryHandler(handle_course_selection_for_unit_quiz)],
        SELECT_UNIT_FOR_COURSE: [CallbackQueryHandler(handle_unit_selection_for_course)],
        ENTER_QUESTION_COUNT: [CallbackQueryHandler(select_question_count)],
        TAKING_QUIZ: [CallbackQueryHandler(handle_quiz_answer, pattern='^ans_')],
        # SHOWING_RESULTS is handled by QuizLogic returning END, which maps to ConversationHandler.END
    },
    fallbacks=[
        CommandHandler('start', start_command_fallback_for_quiz), # MODIFIED: Added /start fallback
        CommandHandler('cancel', cancel_quiz_and_return_to_main_menu),
        CallbackQueryHandler(cancel_quiz_and_return_to_main_menu, pattern='^quiz_cancel$'), # Generic cancel button
        # Fallback for unexpected callback data during quiz selection/setup
        CallbackQueryHandler(cancel_quiz_and_return_to_main_menu, pattern='^quiz_') 
    ],
    map_to_parent={
        END: MAIN_MENU, # Transition to main menu state if quiz ends and returns END
        ConversationHandler.END: MAIN_MENU # Also map explicit ConversationHandler.END to MAIN_MENU
    },
    name="quiz_conversation",
    persistent=True, # Consider if persistence is causing issues with stale states
    allow_reentry=True,
    conversation_timeout=1800 # 30 minutes global timeout for the entire conversation
)

# Add a handler for global timeout if not using map_to_parent for timeout
# This is an alternative way if conversation_timeout directly leads to a function
# quiz_conv_handler.fallbacks.append(MessageHandler(filters.TIMEOUT, quiz_timeout_global_fallback))
# However, the conversation_timeout parameter in ConversationHandler usually just ends the conversation.
# If specific action on timeout is needed, a job or a more complex state might be required.
# For now, relying on ConversationHandler.END from fallbacks or state returns.

logger.info("Quiz conversation handler (v4 - Course/Unit Flow with /start fallback) created.")

