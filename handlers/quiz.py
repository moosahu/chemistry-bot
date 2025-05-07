# -*- coding: utf-8 -*-
"""Conversation handler for the quiz selection and execution flow (Corrected v5 - QuizLogic instantiation fix)."""

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
    SELECT_COURSE_FOR_UNIT_QUIZ, SELECT_UNIT_FOR_COURSE, 
    SELECT_QUIZ_SCOPE, 
    ENTER_QUESTION_COUNT, TAKING_QUIZ, SHOWING_RESULTS, END,
    QUIZ_TYPE_RANDOM, QUIZ_TYPE_CHAPTER, QUIZ_TYPE_UNIT, QUIZ_TYPE_ALL, 
    DEFAULT_QUESTION_TIME_LIMIT # Assuming this is defined in config
)
from utils.helpers import safe_send_message, safe_edit_message_text, get_quiz_type_string, remove_job_if_exists # Added remove_job_if_exists if QuizLogic uses it through context
from utils.api_client import fetch_from_api # Synchronous API fetch function
from handlers.common import create_main_menu_keyboard, main_menu_callback 
# Ensure the path to QuizLogic is correct, assuming it's in the same directory or accessible via .quiz_logic
from .quiz_logic import QuizLogic # This was handlers.quiz_logic in original task, now .quiz_logic as per structure

ITEMS_PER_PAGE = 6

# --- Helper Function for /start fallback ---
async def start_command_fallback_for_quiz(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} sent /start during an active or lingering quiz conversation. Ending current quiz conversation and showing main menu.")
    
    if 'current_quiz_logic' in context.user_data:
        # Attempt to gracefully end the quiz if an instance exists
        try:
            quiz_instance = context.user_data['current_quiz_logic']
            if hasattr(quiz_instance, 'quiz_id') and hasattr(quiz_instance, 'current_question_index'): # Check if it's a valid quiz instance
                timer_job_name = f"qtimer_{user_id}_{update.effective_chat.id}_{quiz_instance.quiz_id}_{quiz_instance.current_question_index}"
                remove_job_if_exists(timer_job_name, context) # Ensure timer is stopped
        except Exception as e_cleanup:
            logger.error(f"Error during quiz_logic cleanup in start_command_fallback: {e_cleanup}")
        del context.user_data['current_quiz_logic']
    
    keys_to_pop = [
        'selected_quiz_type_key', 'selected_quiz_type_display_name', 'questions_for_quiz',
        'selected_course_id_for_unit_quiz', 'available_courses_for_unit_quiz',
        'current_course_page_for_unit_quiz', 'selected_course_name_for_unit_quiz',
        'available_units_for_course', 'current_unit_page_for_course',
        'selected_unit_id', 'selected_unit_name', 'question_count_for_quiz',
        # Add any other quiz-specific keys that might be set before QuizLogic instantiation
        f"quiz_setup_{context.user_data.get('selected_quiz_type_key')}_{context.user_data.get('selected_unit_id')}" # Example of a dynamic key
    ]
    for key in list(context.user_data.keys()): # Iterate over a copy of keys for safe popping
        if key.startswith("quiz_setup_") or key.startswith("qtimer_") or key in keys_to_pop:
             context.user_data.pop(key, None)

    logger.info(f"Cleared quiz-related user_data for user {user_id} due to /start fallback in quiz conversation.")

    await main_menu_callback(update, context) 
    return ConversationHandler.END

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

def create_unit_selection_keyboard(units: list, course_id: str, current_page: int = 0) -> InlineKeyboardMarkup: # course_id is string from callback
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
    counts = [1, 5, 10, 20, min(max_questions, 50)] # Ensure 50 is a reasonable upper limit or adjust
    if max_questions > 0 and max_questions not in counts and max_questions <= 50: # Only add if not present and reasonable
        counts.append(max_questions)
    counts = sorted(list(set(c for c in counts if c <= max_questions and c > 0)))

    keyboard = []
    row = []
    # Create a unique callback prefix for this specific quiz setup to avoid clashes if user navigates back and forth
    # For num_questions, the callback will be `num_questions:<count>:<quiz_type>:<unit_id_or_None>:<course_id_or_None>`
    # This is handled by select_question_count directly from query.data, so no need to pass all these in callback_data for buttons
    
    for count in counts:
        row.append(InlineKeyboardButton(str(count), callback_data=f"num_questions_{count}")) # Kept simple, full context in select_question_count
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    if not counts or (counts and max_questions > counts[-1]): # Show 'All' if no counts or max_questions is greater than largest count option
         if max_questions > 0:
            keyboard.append([InlineKeyboardButton(f"الكل ({max_questions})", callback_data=f"num_questions_all")])

    # Determine the correct back button behavior
    if quiz_type == QUIZ_TYPE_UNIT and course_id_for_unit and unit_id:
        back_callback_data = f"quiz_count_back_to_unit_selection_{course_id_for_unit}" 
    else: # QUIZ_TYPE_ALL or other types that go back to type selection
        back_callback_data = f"quiz_type_back_to_type_selection"

    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback_data)])
    return InlineKeyboardMarkup(keyboard)

# --- Conversation Handler States and Functions ---

async def quiz_menu_entry(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    logger.info(f"User {user_id} entered quiz menu (quiz_menu_entry).")
    # Clear any lingering quiz setup data before starting a new selection process
    keys_to_clear_on_entry = [
        'selected_quiz_type_key', 'selected_quiz_type_display_name', 'questions_for_quiz',
        'selected_course_id_for_unit_quiz', 'available_courses_for_unit_quiz',
        'current_course_page_for_unit_quiz', 'selected_course_name_for_unit_quiz',
        'available_units_for_course', 'current_unit_page_for_course',
        'selected_unit_id', 'selected_unit_name', 'question_count_for_quiz'
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
    
    # This handles 'back' from question count selection for QUIZ_TYPE_ALL
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
        # For QUIZ_TYPE_ALL, we fetch all questions from a dedicated endpoint if available, or aggregate.
        # Assuming an endpoint like /api/v1/questions/all exists or similar logic.
        # If not, the original logic of fetching per course and aggregating is fine.
        all_questions_pool = fetch_from_api("api/v1/questions/all") # Hypothetical endpoint for all questions
        
        if all_questions_pool == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        if not all_questions_pool or not isinstance(all_questions_pool, list):
            logger.error(f"[API] Failed to fetch or parse questions for QUIZ_TYPE_ALL. Received: {all_questions_pool}")
            # Fallback to fetching course by course if /questions/all fails or is not implemented
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
        
        # Store the fetched questions and quiz name for QUIZ_TYPE_ALL
        context.user_data[f"quiz_setup_{quiz_type_key}_all"] = {
            'questions': all_questions_pool,
            'quiz_name': quiz_type_display_name # Or a more specific name like "اختبار شامل"
        }
        context.user_data["selected_unit_id"] = "all" # Special scope for all questions

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
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="نوع اختبار غير معروف. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

async def handle_course_selection_for_unit_quiz(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data
    api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."

    if callback_data == "quiz_type_back_to_type_selection": # Back from course selection to quiz type
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
        # Go back to course selection on timeout
        current_page = context.user_data.get("current_course_page_for_unit_quiz", 0)
        keyboard = create_course_selection_keyboard(courses_list, current_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"{api_timeout_message}\n\nاختر المقرر الدراسي مجدداً:", reply_markup=keyboard)
        return SELECT_COURSE_FOR_UNIT_QUIZ
        
    if not units or not isinstance(units, list) or not units:
        logger.error(f"[API] Failed to fetch or parse units for course {selected_course_id} ('{course_name}'). Received: {units}")
        current_page = context.user_data.get("current_course_page_for_unit_quiz", 0)
        keyboard = create_course_selection_keyboard(courses_list, current_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"عذراً، لا توجد وحدات متاحة للمقرر '{course_name}' حالياً أو حدث خطأ.\n\nاختر مقرراً آخر:", reply_markup=keyboard)
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
    selected_course_id = context.user_data.get("selected_course_id_for_unit_quiz") # Should be string
    course_name = context.user_data.get("selected_course_name_for_unit_quiz", "المقرر المحدد")
    api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."

    if callback_data == "quiz_unit_back_to_course_selection":
        courses = context.user_data.get("available_courses_for_unit_quiz", [])
        current_page = context.user_data.get("current_course_page_for_unit_quiz", 0)
        keyboard = create_course_selection_keyboard(courses, current_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="اختر المقرر الدراسي:", reply_markup=keyboard)
        return SELECT_COURSE_FOR_UNIT_QUIZ

    if callback_data.startswith("quiz_unit_page_"):
        parts = callback_data.split('_')
        # course_id_from_cb = parts[-2] # Not strictly needed if selected_course_id is reliable from user_data
        page = int(parts[-1])
        units = context.user_data.get("available_units_for_course", [])
        context.user_data["current_unit_page_for_course"] = page
        keyboard = create_unit_selection_keyboard(units, selected_course_id, page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر وحدة دراسية من مقرر '{course_name}' (صفحة {page + 1}):", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE

    # Format: quiz_unit_select_{course_id}_{unit_id}
    parts = callback_data.replace("quiz_unit_select_", "", 1).split('_')
    # selected_course_id_from_cb = parts[0]
    selected_unit_id = parts[-1] # Use the last part as unit_id
    context.user_data["selected_unit_id"] = selected_unit_id

    units_list = context.user_data.get("available_units_for_course", [])
    selected_unit_obj = next((u for u in units_list if str(u.get('id')) == str(selected_unit_id)), None)
    unit_name = selected_unit_obj.get('name') if selected_unit_obj else f"وحدة {selected_unit_id}"
    context.user_data["selected_unit_name"] = unit_name

    logger.info(f"User {user_id} selected unit {selected_unit_id} ('{unit_name}') from course {selected_course_id} ('{course_name}').")
    logger.debug(f"[API] Fetching questions for course ID: {selected_course_id}, unit ID: {selected_unit_id}.")
    
    # API endpoint for questions from a specific unit of a course
    questions_data = fetch_from_api(f"api/v1/courses/{selected_course_id}/units/{selected_unit_id}/questions")

    if questions_data == "TIMEOUT":
        current_page = context.user_data.get("current_unit_page_for_course", 0)
        keyboard = create_unit_selection_keyboard(units_list, selected_course_id, current_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"{api_timeout_message}\n\nاختر وحدة دراسية أخرى من مقرر '{course_name}':", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE

    if not questions_data or not isinstance(questions_data, list) or not questions_data:
        logger.error(f"[API] Failed to fetch or parse questions for unit {selected_unit_id} ('{unit_name}') of course {selected_course_id}. Received: {questions_data}")
        current_page = context.user_data.get("current_unit_page_for_course", 0)
        keyboard = create_unit_selection_keyboard(units_list, selected_course_id, current_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"عذراً، لا توجد أسئلة متاحة للوحدة '{unit_name}' من مقرر '{course_name}'.\n\nاختر وحدة أخرى:", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    
    # Store fetched questions and quiz name for this specific unit quiz
    quiz_type = context.user_data.get("selected_quiz_type_key")
    context.user_data[f"quiz_setup_{quiz_type}_{selected_unit_id}"] = {
        'questions': questions_data,
        'quiz_name': f"{course_name} - {unit_name}"
    }

    max_questions = len(questions_data)
    keyboard = create_question_count_keyboard(max_questions, quiz_type, unit_id=selected_unit_id, course_id_for_unit=selected_course_id)
    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار وحدة '{unit_name}' من مقرر '{course_name}':", reply_markup=keyboard)
    return ENTER_QUESTION_COUNT

async def select_question_count(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    callback_data = query.data # e.g., "num_questions_10" or "num_questions_all"

    quiz_type = context.user_data.get("selected_quiz_type_key")
    # For QUIZ_TYPE_UNIT, unit_id is stored in selected_unit_id. For QUIZ_TYPE_ALL, it's "all".
    scope_identifier = context.user_data.get("selected_unit_id") 
    course_id_for_unit = context.user_data.get("selected_course_id_for_unit_quiz") # Relevant for unit quizzes for back button

    # Handle back button from question count selection
    if callback_data.startswith("quiz_count_back_to_unit_selection_"):
        # This implies it was a unit quiz, go back to unit selection
        # course_id_from_cb = callback_data.split('_')[-1]
        units = context.user_data.get("available_units_for_course", [])
        current_page = context.user_data.get("current_unit_page_for_course", 0)
        course_name = context.user_data.get("selected_course_name_for_unit_quiz", "المقرر المحدد")
        keyboard = create_unit_selection_keyboard(units, course_id_for_unit, current_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر وحدة دراسية من مقرر '{course_name}':", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data == "quiz_type_back_to_type_selection": # Back from QUIZ_TYPE_ALL count selection
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    # Retrieve the stored questions and quiz name based on type and scope
    quiz_setup_data_key = f"quiz_setup_{quiz_type}_{scope_identifier}"
    quiz_setup_data = context.user_data.get(quiz_setup_data_key)

    if not quiz_setup_data or 'questions' not in quiz_setup_data:
        logger.error(f"Quiz setup data or questions missing for key {quiz_setup_data_key} for user {user_id}. Cannot start quiz.")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، حدث خطأ في استرجاع بيانات الاختبار. يرجى المحاولة من البداية.")
        # Go back to a safe state, e.g., quiz type selection
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار مجدداً:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE 

    questions_for_quiz = quiz_setup_data['questions']
    quiz_name_from_setup = quiz_setup_data.get('quiz_name', context.user_data.get("selected_quiz_type_display_name"))
    max_questions = len(questions_for_quiz)

    num_questions_str = callback_data.replace("num_questions_", "", 1)
    if num_questions_str == "all":
        num_questions = max_questions
    else:
        try:
            num_questions = int(num_questions_str)
            if not (0 < num_questions <= max_questions):
                logger.warning(f"User {user_id} selected invalid number of questions: {num_questions}. Max is {max_questions}. Defaulting to max.")
                num_questions = max_questions
        except ValueError:
            logger.error(f"User {user_id} callback for num_questions was invalid: {callback_data}. Defaulting to max questions.")
            num_questions = max_questions
    
    context.user_data["question_count_for_quiz"] = num_questions
    logger.info(f"User {user_id} selected {num_questions} questions for quiz type '{quiz_type}', scope '{scope_identifier}'.")

    # Prepare for QuizLogic instantiation
    selected_questions_final = random.sample(questions_for_quiz, num_questions) if len(questions_for_quiz) > num_questions else questions_for_quiz
    
    # Get display names for the message
    quiz_type_display = context.user_data.get("selected_quiz_type_display_name", quiz_type)
    scope_display_name = ""
    if quiz_type == QUIZ_TYPE_UNIT:
        course_disp_name = context.user_data.get("selected_course_name_for_unit_quiz", "")
        unit_disp_name = context.user_data.get("selected_unit_name", "")
        scope_display_name = f" ({course_disp_name} - {unit_disp_name})"
    elif quiz_type == QUIZ_TYPE_ALL:
        scope_display_name = " (شامل)"
    
    # Instantiate QuizLogic with all necessary parameters
    # ** THIS IS THE CORRECTED INSTANTIATION **
    quiz_logic = QuizLogic(
        context=context, 
        bot_instance=context.bot, 
        user_id=user_id, 
        quiz_type=quiz_type, 
        questions_data=selected_questions_final, 
        total_questions=num_questions, 
        question_time_limit=DEFAULT_QUESTION_TIME_LIMIT # Assuming DEFAULT_QUESTION_TIME_LIMIT is defined in config
    )

    context.user_data["current_quiz_logic"] = quiz_logic
    logger.info(f"QuizLogic instance created for user {user_id}. Starting quiz '{quiz_name_from_setup}' with {num_questions} questions.")

    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"⏳ يتم الآن إعداد اختبارك{scope_display_name} بـ {num_questions} سؤال. لحظات قليلة...")
    
    # Call start_quiz from the QuizLogic instance
    # This will send the first question and return TAKING_QUIZ (or END if no questions)
    return await quiz_logic.start_quiz(update, query.message.chat_id, user_id) # Pass chat_id and user_id explicitly


async def handle_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    quiz_logic_instance = context.user_data.get("current_quiz_logic")
    if not quiz_logic_instance or not isinstance(quiz_logic_instance, QuizLogic):
        logger.warning(f"User {user_id} (chat {chat_id}) sent an answer, but no QuizLogic instance found or invalid. Message: {query.message.text}")
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="عذراً، يبدو أن جلسة الاختبار هذه غير صالحة أو قد انتهت. يرجى بدء اختبار جديد.")
        return ConversationHandler.END # Or return to main menu

    # Delegate to QuizLogic's handle_answer method
    # It will handle editing the message, scoring, and sending the next question or results
    # It should return the next state (TAKING_QUIZ or END)
    next_state = await quiz_logic_instance.handle_answer(update, query)
    return next_state

async def quiz_timeout_external_trigger(context: CallbackContext):
    """Called by JobQueue when a question times out. Delegates to QuizLogic instance."""
    job_data = context.job.data
    user_id = job_data.get("user_id")
    chat_id = job_data.get("chat_id")
    quiz_id_from_job = job_data.get("quiz_id")
    question_index_from_job = job_data.get("question_index")
    message_id = job_data.get("message_id")
    question_was_image = job_data.get("question_was_image", False)

    logger.info(f"External timeout trigger for user {user_id}, quiz {quiz_id_from_job}, q_idx {question_index_from_job}")

    quiz_logic_instance = context.user_data.get("current_quiz_logic")

    if not quiz_logic_instance or not isinstance(quiz_logic_instance, QuizLogic):
        logger.warning(f"Timeout for user {user_id}, but no valid QuizLogic instance found. Quiz ID from job: {quiz_id_from_job}. Aborting timeout processing.")
        # Optionally send a message if the message_id is available and seems valid
        # await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=message_id, text="انتهى وقت السؤال، ولكن حدث خطأ في متابعة الاختبار.")
        return

    # Validate that the timeout corresponds to the current quiz and question in QuizLogic
    if quiz_logic_instance.quiz_id != quiz_id_from_job or quiz_logic_instance.current_question_index != question_index_from_job:
        logger.info(f"Timeout for user {user_id} is for an old question/quiz (Job: q_idx {question_index_from_job}, quiz {quiz_id_from_job}; Current: q_idx {quiz_logic_instance.current_question_index}, quiz {quiz_logic_instance.quiz_id}). Ignoring.")
        # Edit the old message to indicate timeout if it's still relevant
        # This check helps prevent editing messages if the user has already moved on.
        if quiz_logic_instance.last_question_message_id == message_id: # Check if the message is the one we expect
            pass # QuizLogic's own timeout handler should manage this if the job is current
        else: # If it's a truly old message not managed by current quiz logic, maybe just remove keyboard
            try:
                await context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
                logger.info(f"Removed keyboard from old timed-out question (msg_id: {message_id}) for user {user_id}.")
            except Exception as e_edit_old:
                logger.warning(f"Could not remove keyboard from old timed-out msg_id {message_id} for user {user_id}: {e_edit_old}")
        return

    # Delegate to QuizLogic's question_timeout_callback method
    # This method is now part of QuizLogic and is called by the job queue
    # The QuizLogic instance will handle the timeout logic (sending feedback, next question, or results)
    await quiz_logic_instance.question_timeout_callback_from_job(job_data)
    # The state transition (TAKING_QUIZ or END) is handled within QuizLogic methods


async def end_quiz_command(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    logger.info(f"User {user_id} (chat {chat_id}) initiated /endquiz command.")

    quiz_logic_instance = context.user_data.get("current_quiz_logic")
    if quiz_logic_instance and isinstance(quiz_logic_instance, QuizLogic):
        logger.info(f"Ending active quiz {quiz_logic_instance.quiz_id} for user {user_id} due to /endquiz command.")
        # Stop any active question timer for this quiz
        timer_job_name = f"qtimer_{user_id}_{chat_id}_{quiz_logic_instance.quiz_id}_{quiz_logic_instance.current_question_index}"
        remove_job_if_exists(timer_job_name, context)
        
        # Show results if any questions were answered, or a simple end message
        if quiz_logic_instance.current_question_index > 0 or quiz_logic_instance.answers:
            await quiz_logic_instance.show_results(chat_id, user_id, ended_by_command=True)
        else:
            await safe_send_message(context.bot, chat_id, "تم إنهاء الاختبار بناءً على طلبك.")
        
        # Clean up QuizLogic instance
        del context.user_data["current_quiz_logic"]
    else:
        await safe_send_message(context.bot, chat_id, "لا يوجد اختبار نشط لإنهاءه.")
    
    # Clear other potential quiz-related data as a precaution
    keys_to_pop_on_end = [
        'selected_quiz_type_key', 'selected_quiz_type_display_name', 'questions_for_quiz',
        'selected_course_id_for_unit_quiz', 'available_courses_for_unit_quiz',
        'current_course_page_for_unit_quiz', 'selected_course_name_for_unit_quiz',
        'available_units_for_course', 'current_unit_page_for_course',
        'selected_unit_id', 'selected_unit_name', 'question_count_for_quiz'
    ]
    for key in list(context.user_data.keys()): 
        if key.startswith("quiz_setup_") or key in keys_to_pop_on_end:
            context.user_data.pop(key, None)
    logger.info(f"Cleaned up user_data for user {user_id} after /endquiz or quiz completion.")

    # Optionally, show the main menu again
    await main_menu_callback(update, context) 
    return ConversationHandler.END

# --- Conversation Handler Definition ---

# Fallback for /start command during the quiz conversation
start_fallback_handler_for_quiz = CommandHandler('start', start_command_fallback_for_quiz)

quiz_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(quiz_menu_entry, pattern='^start_quiz$')],
    states={
        SELECT_QUIZ_TYPE: [
            CallbackQueryHandler(select_quiz_type, pattern='^quiz_type_.*$'),
            CallbackQueryHandler(select_quiz_type, pattern='^main_menu$') # Allow going back to main menu
        ],
        SELECT_COURSE_FOR_UNIT_QUIZ: [
            CallbackQueryHandler(handle_course_selection_for_unit_quiz, pattern='^quiz_course_select_.*$'),
            CallbackQueryHandler(handle_course_selection_for_unit_quiz, pattern='^quiz_course_page_.*$'),
            CallbackQueryHandler(handle_course_selection_for_unit_quiz, pattern='^quiz_type_back_to_type_selection$') # Back to type selection
        ],
        SELECT_UNIT_FOR_COURSE: [
            CallbackQueryHandler(handle_unit_selection_for_course, pattern='^quiz_unit_select_.*$'),
            CallbackQueryHandler(handle_unit_selection_for_course, pattern='^quiz_unit_page_.*$'),
            CallbackQueryHandler(handle_unit_selection_for_course, pattern='^quiz_unit_back_to_course_selection$') # Back to course selection
        ],
        ENTER_QUESTION_COUNT: [
            CallbackQueryHandler(select_question_count, pattern='^num_questions_.*$'),
            CallbackQueryHandler(select_question_count, pattern='^quiz_count_back_to_unit_selection_.*$'), # Back to unit selection
            CallbackQueryHandler(select_question_count, pattern='^quiz_type_back_to_type_selection$') # Back to type selection (for QUIZ_TYPE_ALL)
        ],
        TAKING_QUIZ: [
            CallbackQueryHandler(handle_answer, pattern='^ans_.*$'),
            CommandHandler('endquiz', end_quiz_command) # Allow ending quiz with a command
        ],
        # SHOWING_RESULTS is not a state here, results are shown then END is returned by QuizLogic or end_quiz_command
    },
    fallbacks=[
        CommandHandler('endquiz', end_quiz_command),
        start_fallback_handler_for_quiz, # Handles /start during quiz
        CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'), # General fallback to main menu if other patterns fail
         # A more generic fallback if user clicks an old button or something unexpected
        CallbackQueryHandler(lambda u, c: quiz_menu_entry(u,c) if u.callback_query and u.callback_query.message else main_menu_callback(u,c), pattern='^.*$') 
    ],
    map_to_parent={
        END: MAIN_MENU # Assuming MAIN_MENU is a state in a parent ConversationHandler or similar
    },
    per_message=False, # Allow multiple interactions with the same message (e.g. question message)
    name="quiz_conversation",
    persistent=False # User data will be used for persistence if needed, but states are not session-persistent by default
)

# Note: The quiz_timeout_external_trigger is not part of the ConversationHandler states directly.
# It's triggered by the JobQueue. The QuizLogic instance then handles the logic and might return END 
# or transition internally, which is fine as ConversationHandler is mainly for user-driven state changes.

