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

# --- Keyboard Creation Helper Functions ---

def create_quiz_type_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🎲 اختبار عشوائي شامل (كل المقررات)", callback_data=f"quiz_type_{QUIZ_TYPE_ALL}")],
        [InlineKeyboardButton("📚 حسب الوحدة الدراسية (اختر المقرر ثم الوحدة)", callback_data=f"quiz_type_{QUIZ_TYPE_UNIT}")],
        # Add other quiz types here if needed, e.g., by specific course directly
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
    elif quiz_type != QUIZ_TYPE_ALL: # For other specific scope types if any
        # This part might need adjustment if other scoped quizzes are added
        # For now, default to type selection if not unit or all
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
        # Ensure main_menu_callback is adapted to be called with from_quiz=True if needed
        # or handle the state transition to MAIN_MENU directly if it's simpler.
        # For now, assuming main_menu_callback can handle it or it's a direct state transition.
        await main_menu_callback(update, context) # Removed from_quiz, ensure it works or adjust
        return ConversationHandler.END
    if callback_data == "quiz_type_back_to_type_selection": # Handles back button from course/unit selection
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
        # course_id_from_cb = parts[3] # Already have selected_course_id from context
        page = int(parts[-1])
        units = context.user_data.get("available_units_for_course", [])
        context.user_data["current_unit_page_for_course"] = page
        keyboard = create_unit_selection_keyboard(units, selected_course_id, page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر وحدة دراسية من مقرر '{course_name}' (صفحة {page + 1}):", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE

    # Format: quiz_unit_select_{course_id}_{unit_id}
    parts = callback_data.split('_')
    selected_unit_id = parts[-1]
    # selected_course_id_from_cb = parts[-2] # Already have from context

    context.user_data["selected_scope_id"] = selected_unit_id # scope_id is unit_id here
    
    units_list = context.user_data.get("available_units_for_course", [])
    selected_unit_obj = next((u for u in units_list if str(u.get('id')) == str(selected_unit_id)), None)
    unit_name = selected_unit_obj.get('name') if selected_unit_obj else f"وحدة {selected_unit_id}"
    context.user_data["selected_scope_name"] = unit_name # scope_name is unit_name

    logger.info(f"User {user_id} selected unit {selected_unit_id} ({unit_name}) from course {selected_course_id} ({course_name}).")
    logger.debug(f"[API] Fetching questions for unit ID: {selected_unit_id}.")
    questions_data = fetch_from_api(f"api/v1/units/{selected_unit_id}/questions")

    if questions_data == "TIMEOUT":
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"انتهت مهلة الاتصال بخادم الأسئلة أثناء جلب أسئلة الوحدة '{unit_name}'.", reply_markup=create_unit_selection_keyboard(units_list, selected_course_id, context.user_data.get("current_unit_page_for_course",0)))
        return SELECT_UNIT_FOR_COURSE
    if not questions_data or not isinstance(questions_data, list) or not questions_data:
        logger.error(f"[API] Failed to fetch questions for unit {selected_unit_id} or no questions returned. Data: {questions_data}")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"عذراً، لا توجد أسئلة متاحة للوحدة '{unit_name}' حالياً أو حدث خطأ.", reply_markup=create_unit_selection_keyboard(units_list, selected_course_id, context.user_data.get("current_unit_page_for_course",0)))
        return SELECT_UNIT_FOR_COURSE

    context.user_data["questions_for_quiz"] = questions_data
    max_questions = len(questions_data)
    quiz_type_key = context.user_data.get("selected_quiz_type_key") # Should be QUIZ_TYPE_UNIT
    keyboard = create_question_count_keyboard(max_questions, quiz_type_key, selected_unit_id, selected_course_id)
    display_name_for_count = f"{context.user_data.get('selected_quiz_type_display_name', quiz_type_key)} - {course_name} - {unit_name}"
    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار '{display_name_for_count}':", reply_markup=keyboard)
    return ENTER_QUESTION_COUNT

async def enter_question_count(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data

    quiz_type_key = context.user_data.get("selected_quiz_type_key")
    scope_id = context.user_data.get("selected_scope_id") # This is unit_id if quiz_type is UNIT
    course_id_for_unit = context.user_data.get("selected_course_id_for_unit_quiz")

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

    num_questions_str = callback_data.split('_')[-1]
    questions_for_quiz_pool = context.user_data.get("questions_for_quiz", [])
    max_available_questions = len(questions_for_quiz_pool)
    
    num_questions = 0
    if num_questions_str == "all":
        num_questions = max_available_questions
    else:
        try:
            num_questions = int(num_questions_str)
            if not (0 < num_questions <= max_available_questions):
                logger.warning(f"User {user_id} selected invalid number of questions: {num_questions}. Max: {max_available_questions}")
                keyboard = create_question_count_keyboard(max_available_questions, quiz_type_key, scope_id, course_id_for_unit)
                await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"عدد أسئلة غير صالح. يرجى اختيار عدد بين 1 و {max_available_questions}.", reply_markup=keyboard)
                return ENTER_QUESTION_COUNT
        except ValueError:
            logger.error(f"Invalid num_questions_str: {num_questions_str}")
            keyboard = create_question_count_keyboard(max_available_questions, quiz_type_key, scope_id, course_id_for_unit)
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ في اختيار عدد الأسئلة. حاول مرة أخرى.", reply_markup=keyboard)
            return ENTER_QUESTION_COUNT

    logger.info(f"User {user_id} selected {num_questions} questions for quiz type {quiz_type_key} (Course: {course_id_for_unit if course_id_for_unit else 'N/A'}, Unit/Scope: {scope_id if scope_id else 'N/A'}).")
    
    if num_questions == 0 and max_available_questions > 0: # Should not happen if validation above is correct
        logger.warning("Number of questions is 0 but pool is not empty. Defaulting to 1.")
        num_questions = 1 # Safety net
    elif num_questions == 0 and max_available_questions == 0:
        logger.error("No questions available to start quiz.")
        # This case should have been caught earlier when fetching questions
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لا توجد أسئلة لبدء الاختبار. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    if num_questions < max_available_questions:
        selected_questions = random.sample(questions_for_quiz_pool, num_questions)
    else:
        selected_questions = questions_for_quiz_pool
    
    quiz_display_name = context.user_data.get("selected_quiz_type_display_name", quiz_type_key)
    if quiz_type_key == QUIZ_TYPE_UNIT:
        scope_name = context.user_data.get("selected_scope_name", f"وحدة {scope_id}")
        course_name = context.user_data.get("selected_course_name_for_unit_quiz", f"مقرر {course_id_for_unit}")
        quiz_display_name = f"{quiz_display_name} - {course_name} - {scope_name}"

    quiz_logic_instance = QuizLogic(
        context=context,
        bot_instance=context.bot,
        user_id=user_id,
        quiz_type=quiz_display_name,
        questions_data=selected_questions,
        total_questions=num_questions,
        question_time_limit=context.bot_data.get("default_question_time_limit", DEFAULT_QUESTION_TIME_LIMIT)
    )
    context.user_data['current_quiz_instance'] = quiz_logic_instance

    logger.info(f"Quiz instance created for user {user_id}. Starting quiz with {num_questions} questions.")
    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"جاري بدء الاختبار بـ {num_questions} أسئلة...", reply_markup=None)
    return await quiz_logic_instance.start_quiz(update)

async def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    quiz_logic_instance = context.user_data.get('current_quiz_instance')

    if not quiz_logic_instance:
        logger.error(f"No quiz instance found for user {user_id} on callback: {query.data}")
        await query.answer("عذراً، لا يوجد اختبار نشط حالياً أو انتهت صلاحية الجلسة.", show_alert=True)
        keyboard = create_quiz_type_keyboard()
        # Attempt to edit the message if possible, otherwise send a new one
        try:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="يبدو أنه لا يوجد اختبار نشط. يرجى اختيار نوع اختبار جديد:", reply_markup=keyboard)
        except Exception as e:
            logger.warning(f"Failed to edit message for no active quiz, sending new: {e}")
            await safe_send_message(context.bot, chat_id=query.message.chat_id, text="يبدو أنه لا يوجد اختبار نشط. يرجى اختيار نوع اختبار جديد:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    logger.debug(f"Passing answer callback {query.data} to QuizLogic instance for user {user_id}")
    return await quiz_logic_instance.handle_answer(update, context)

async def end_quiz_command(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    quiz_logic_instance = context.user_data.get('current_quiz_instance')

    if quiz_logic_instance:
        logger.info(f"User {user_id} manually ended quiz {quiz_logic_instance.quiz_id}.")
        # Attempt to remove timer job
        timer_job_name = f"qtimer_{user_id}_{chat_id}_{quiz_logic_instance.quiz_id}_{quiz_logic_instance.current_question_index}"
        # Ensure remove_job_if_exists is available and correctly imported/defined in helpers.py
        # This might need to be context.job_queue.scheduler.remove_job(timer_job_name) or similar depending on PTB version
        # For now, assuming a helper function `remove_job_if_exists` is defined and works with context.job_queue
        from utils.helpers import remove_job_if_exists # Ensure this is correctly defined and available
        remove_job_if_exists(timer_job_name, context) 

        await quiz_logic_instance.show_results(chat_id, user_id)
        context.user_data.pop('current_quiz_instance', None)
        await safe_send_message(context.bot, chat_id, "تم إنهاء الاختبار بناءً على طلبك.", reply_markup=create_main_menu_keyboard(user_id))
    else:
        await safe_send_message(context.bot, chat_id, "لا يوجد اختبار نشط لإنهاءه.", reply_markup=create_main_menu_keyboard(user_id))
    
    return ConversationHandler.END

quiz_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(quiz_menu_entry, pattern=r'^start_quiz$')],
    states={
        SELECT_QUIZ_TYPE: [
            CallbackQueryHandler(select_quiz_type, pattern=r'^quiz_type_(?!back_to_type_selection).+$'), # Matches quiz_type_KEY
            CallbackQueryHandler(main_menu_callback, pattern=r'^main_menu$') 
        ],
        SELECT_COURSE_FOR_UNIT_QUIZ: [
            CallbackQueryHandler(handle_course_selection_for_unit_quiz, pattern=r'^quiz_course_select_.+$'),
            CallbackQueryHandler(handle_course_selection_for_unit_quiz, pattern=r'^quiz_course_page_.+$'),
            CallbackQueryHandler(select_quiz_type, pattern=r'^quiz_type_back_to_type_selection$') # Back to type selection
        ],
        SELECT_UNIT_FOR_COURSE: [
            CallbackQueryHandler(handle_unit_selection_for_course, pattern=r'^quiz_unit_select_.+_.+$'),
            CallbackQueryHandler(handle_unit_selection_for_course, pattern=r'^quiz_unit_page_.+_.+$'),
            CallbackQueryHandler(handle_course_selection_for_unit_quiz, pattern=r'^quiz_unit_back_to_course_selection$') # Back to course selection
        ],
        # SELECT_QUIZ_SCOPE: [ # This state might be deprecated or used for other quiz types
            # CallbackQueryHandler(handle_scope_pagination, pattern=r'^quiz_scope_page_.+$'),
            # CallbackQueryHandler(select_quiz_scope_specific, pattern=r'^quiz_scope_specific_.+$'),
            # CallbackQueryHandler(select_quiz_type, pattern=r'^quiz_type_back$') 
        # ],
        ENTER_QUESTION_COUNT: [
            CallbackQueryHandler(enter_question_count, pattern=r'^num_questions_.+$'),
            CallbackQueryHandler(enter_question_count, pattern=r'^quiz_count_back_to_.+$') 
        ],
        TAKING_QUIZ: [
            CallbackQueryHandler(handle_quiz_answer, pattern=r'^ans_.+$')
        ],
    },
    fallbacks=[
        CommandHandler('cancelquiz', end_quiz_command),
        CallbackQueryHandler(main_menu_callback, pattern=r'^main_menu$') 
    ],
    map_to_parent={
        END: MAIN_MENU
    },
    per_message=False,
    name="quiz_conversation_v4",
    persistent=True
)

logger.info("Quiz conversation handler (v4 - Course/Unit Flow) created.")

