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
    logger.info(f"User {user_id} entered quiz menu (quiz_menu_entry) via {query.data}.") # Log which callback triggered it
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
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="نوع اختبار غير معروف. يرجى إعادة المحاولة.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

async def select_course_for_unit_quiz(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data

    if callback_data == "quiz_type_back_to_type_selection":
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    courses = context.user_data.get("available_courses_for_unit_quiz", [])
    current_page = context.user_data.get("current_course_page_for_unit_quiz", 0)

    if callback_data.startswith("quiz_course_page_"):
        new_page = int(callback_data.split('_')[-1])
        context.user_data["current_course_page_for_unit_quiz"] = new_page
        keyboard = create_course_selection_keyboard(courses, new_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="اختر المقرر الدراسي:", reply_markup=keyboard)
        return SELECT_COURSE_FOR_UNIT_QUIZ

    elif callback_data.startswith("quiz_course_select_"):
        selected_course_id = callback_data.split('_')[-1]
        selected_course = next((c for c in courses if str(c.get('id')) == selected_course_id), None)
        
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
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية للمقرر \"{selected_course.get('name', selected_course_id)}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    
    return SELECT_COURSE_FOR_UNIT_QUIZ # Fallback

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
        # Format: quiz_unit_page_<course_id>_<page_num>
        parts = callback_data.split('_')
        # course_id_from_cb = parts[-2] # Not strictly needed if selected_course_id is reliable from context
        new_page = int(parts[-1])
        context.user_data["current_unit_page_for_course"] = new_page
        keyboard = create_unit_selection_keyboard(available_units, selected_course_id, new_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية للمقرر \"{selected_course_name}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE

    elif callback_data.startswith("quiz_unit_select_"):
        # Format: quiz_unit_select_<course_id>_<unit_id>
        parts = callback_data.split('_')
        # course_id_from_cb = parts[-2] # Not strictly needed
        selected_unit_id = parts[-1]
        selected_unit = next((u for u in available_units if str(u.get("id")) == selected_unit_id), None)

        if not selected_unit:
            logger.error(f"User {user_id} selected a unit ID ({selected_unit_id}) that was not found for course {selected_course_id}.")
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ في اختيار الوحدة. يرجى المحاولة مرة أخرى.", reply_markup=create_unit_selection_keyboard(available_units, selected_course_id, current_unit_page))
            return SELECT_UNIT_FOR_COURSE

        context.user_data["selected_unit_id"] = selected_unit_id
        context.user_data["selected_unit_name"] = selected_unit.get("name", f"وحدة {selected_unit_id}")
        logger.info(f"User {user_id} selected unit: {selected_unit_id} ({selected_unit.get('name')}) for course {selected_course_id}")

        # Fetch questions for this specific unit
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
        
        # Store fetched questions and quiz name for this unit
        quiz_type_key = context.user_data.get("selected_quiz_type_key") # Should be QUIZ_TYPE_UNIT
        context.user_data[f"quiz_setup_{quiz_type_key}_{selected_unit_id}"] = {
            'questions': questions_for_unit,
            'quiz_name': f"{selected_course_name} - {selected_unit.get('name', f'وحدة {selected_unit_id}')}"
        }

        max_questions = len(questions_for_unit)
        # Pass selected_course_id for the back button logic in create_question_count_keyboard
        keyboard = create_question_count_keyboard(max_questions, quiz_type_key, unit_id=selected_unit_id, course_id_for_unit=selected_course_id)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"""اختر عدد الأسئلة لاختبار \n'{selected_course_name} - {selected_unit.get('name', '')}':""", reply_markup=keyboard)
        return ENTER_QUESTION_COUNT

    return SELECT_UNIT_FOR_COURSE # Fallback

async def select_question_count(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    callback_data = query.data # e.g., "num_questions_10" or "num_questions_all"

    # Retrieve stored quiz type and scope (unit_id or "all")
    quiz_type_key = context.user_data.get("selected_quiz_type_key")
    # For QUIZ_TYPE_UNIT, unit_id is stored in selected_unit_id. For QUIZ_TYPE_ALL, it's "all".
    scope_identifier = context.user_data.get("selected_unit_id") # This will be 'all' for QUIZ_TYPE_ALL or actual unit_id

    if not quiz_type_key or not scope_identifier:
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، يبدو أن معلومات إعداد الاختبار غير كاملة. يرجى المحاولة من البداية.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE # Or END if more appropriate

    num_questions_str = callback_data.replace("num_questions_", "", 1)
    
    quiz_setup_data_key = f"quiz_setup_{quiz_type_key}_{scope_identifier}"
    quiz_setup_data = context.user_data.get(quiz_setup_data_key)

    if not quiz_setup_data:
        logger.error(f"Quiz setup data not found for key: {quiz_setup_data_key}")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، بيانات إعداد الاختبار مفقودة. يرجى إعادة المحاولة.")
        # Go back to a relevant state, e.g., type selection
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    all_questions_for_scope = quiz_setup_data.get('questions', [])
    quiz_name_from_setup = quiz_setup_data.get('quiz_name', "اختبار") # Default name

    if not all_questions_for_scope:
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لا توجد أسئلة متاحة لهذا النطاق المحدد.")
        # Go back
        keyboard = create_quiz_type_keyboard() # Or a more specific back option
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
            # Re-present question count choice
            # This needs the keyboard again, might be complex to reconstruct here, better to go back a step.
            # For simplicity, going back to type selection.
            keyboard = create_quiz_type_keyboard()
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
            return SELECT_QUIZ_TYPE
    
    if not selected_questions_final: # Should not happen if logic above is correct, but as a safeguard
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لم يتم اختيار أسئلة. يرجى المحاولة مرة أخرى.")
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    # Instantiate QuizLogic
    quiz_logic = QuizLogic(
        bot_instance=context.bot, 
        user_id=user_id, 
        quiz_type=quiz_type_key, # Pass the key
        questions_data=selected_questions_final, 
        total_questions=num_questions, 
        question_time_limit=DEFAULT_QUESTION_TIME_LIMIT, # Assuming this is defined in config
        # Removed quiz_name, scope_identifier as QuizLogic might not need them or gets them differently
        # Ensure QuizLogic's __init__ matches these parameters
        context_for_job_queue=context # Pass the whole context for job_queue access
    )

    context.user_data["current_quiz_logic"] = quiz_logic
    
    # Display name for the quiz type and scope
    quiz_type_display_name = context.user_data.get("selected_quiz_type_display_name", quiz_type_key)
    scope_display_name = ""
    if quiz_type_key == QUIZ_TYPE_UNIT:
        selected_course_name = context.user_data.get("selected_course_name_for_unit_quiz", "")
        selected_unit_name = context.user_data.get("selected_unit_name", "")
        if selected_course_name and selected_unit_name:
            scope_display_name = f" ({selected_course_name} - {selected_unit_name})"
        elif selected_course_name: # Should not happen if flow is correct
             scope_display_name = f" ({selected_course_name})"
    elif quiz_type_key == QUIZ_TYPE_ALL:
        scope_display_name = " (شامل)"


    logger.info(f"QuizLogic instance created for user {user_id}. Starting quiz '{quiz_name_from_setup}'{scope_display_name} with {num_questions} questions.")

    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"⏳ يتم الآن إعداد اختبارك{scope_display_name} بـ {num_questions} سؤال. لحظات قليلة...")
    
    # Call start_quiz from the QuizLogic instance
    # This will send the first question and return TAKING_QUIZ (or END if no questions)
    return await quiz_logic.start_quiz(update, query.message.chat_id, user_id) # Pass chat_id and user_id explicitly

async def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    quiz_logic = context.user_data.get("current_quiz_logic")
    if not quiz_logic:
        logger.warning(f"User {user_id} tried to answer, but no active quiz logic found.")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لا يوجد اختبار نشط. يرجى البدء من جديد.")
        await main_menu_callback(update, context)
        return ConversationHandler.END

    return await quiz_logic.handle_answer(update, query.data)

async def quiz_timeout(context: CallbackContext) -> None:
    job_data = context.job.data
    user_id = job_data["user_id"]
    quiz_logic = context.user_data.get("current_quiz_logic") # Get the specific user's quiz_logic

    if not quiz_logic or quiz_logic.user_id != user_id or quiz_logic.quiz_id != job_data.get("quiz_id") or quiz_logic.current_question_index != job_data.get("question_idx"):
        logger.info(f"Quiz timeout job executed for user {user_id}, quiz {job_data.get('quiz_id', 'N/A')}, q_idx {job_data.get('question_idx', 'N/A')}, but current quiz state does not match or quiz_logic missing. Ignoring.")
        return

    logger.info(f"Timeout for user {user_id}, quiz {quiz_logic.quiz_id}, question {quiz_logic.current_question_index + 1}")
    await quiz_logic.handle_timeout(job_data["chat_id"], job_data["message_id_to_edit"])

async def quiz_results(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    quiz_logic = context.user_data.get("current_quiz_logic")
    if not quiz_logic:
        logger.warning(f"User {user_id} tried to see results, but no active quiz logic found.")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لا توجد نتائج لعرضها. ربما انتهى الاختبار بالفعل أو لم يبدأ.")
        await main_menu_callback(update, context)
        return ConversationHandler.END
    
    # This state is usually reached via QuizLogic returning SHOWING_RESULTS
    # The actual result display is handled by QuizLogic.end_quiz or a similar method.
    # This handler might be redundant if QuizLogic handles the final message edit.
    # However, if it's a callback from a "Show Results" button after quiz ends:
    if hasattr(quiz_logic, 'get_final_results_text_and_markup'):
        results_text, results_markup = quiz_logic.get_final_results_text_and_markup()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=results_text, reply_markup=results_markup)
    else:
        logger.warning(f"QuizLogic for user {user_id} does not have get_final_results_text_and_markup method.")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="النتائج غير متوفرة حالياً.")

    # Clean up quiz logic from user_data after showing results
    # del context.user_data["current_quiz_logic"] # QuizLogic should handle its own cleanup or signal for it
    await main_menu_callback(update, context) # Go to main menu
    return ConversationHandler.END

async def end_quiz_conversation(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    logger.info(f"User {user_id} chose to end quiz conversation explicitly or quiz ended.")
    
    if query: # If called from a callback query (e.g., a button)
        await query.answer()
        chat_id = query.message.chat_id
        message_id = query.message.message_id
    else: # If called directly (e.g. after timeout and no more questions)
        chat_id = update.effective_chat.id
        # We might not have a specific message_id to edit if called directly without a query
        # In this case, QuizLogic should have handled the last message, or we send a new one.
        message_id = None 

    if 'current_quiz_logic' in context.user_data:
        quiz_logic = context.user_data['current_quiz_logic']
        # Ensure timer is stopped if quiz_logic is being removed
        if hasattr(quiz_logic, 'quiz_id') and hasattr(quiz_logic, 'current_question_index'):
            timer_job_name = f"qtimer_{user_id}_{chat_id}_{quiz_logic.quiz_id}_{quiz_logic.current_question_index}"
            remove_job_if_exists(timer_job_name, context)
        del context.user_data['current_quiz_logic']
        logger.info(f"Quiz logic removed for user {user_id}.")

    # Clear all quiz-related data more comprehensively
    keys_to_pop = [
        'selected_quiz_type_key', 'selected_quiz_type_display_name', 'questions_for_quiz',
        'selected_course_id_for_unit_quiz', 'available_courses_for_unit_quiz',
        'current_course_page_for_unit_quiz', 'selected_course_name_for_unit_quiz',
        'available_units_for_course', 'current_unit_page_for_course',
        'selected_unit_id', 'selected_unit_name', 'question_count_for_quiz'
    ]
    for key in list(context.user_data.keys()): # Iterate over a copy of keys for safe popping
        if key.startswith("quiz_setup_") or key.startswith("qtimer_") or key in keys_to_pop:
             context.user_data.pop(key, None)
    logger.info(f"All quiz-related user_data cleared for user {user_id} at end_quiz_conversation.")

    if message_id: # If we have a message to edit (likely from a button press)
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=message_id, text="تم إنهاء جلسة الاختبار. شكراً لك!", reply_markup=create_main_menu_keyboard(user_id))
    else: # If no specific message to edit, send a new one
        await safe_send_message(context.bot, chat_id=chat_id, text="تم إنهاء جلسة الاختبار. شكراً لك!", reply_markup=create_main_menu_keyboard(user_id))
    
    return ConversationHandler.END

# --- Conversation Handler Definition ---
quiz_conv_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(quiz_menu_entry, pattern='^quiz_menu$'),
        CallbackQueryHandler(quiz_menu_entry, pattern='^start_quiz$') # Added to handle start_quiz from common.py
    ],
    states={
        SELECT_QUIZ_TYPE: [
            CallbackQueryHandler(select_quiz_type, pattern='^quiz_type_.*$'),
            CallbackQueryHandler(main_menu_callback, pattern='^main_menu$') # From quiz type selection
        ],
        SELECT_COURSE_FOR_UNIT_QUIZ: [
            CallbackQueryHandler(select_course_for_unit_quiz, pattern='^quiz_course_.*$'),
            CallbackQueryHandler(select_quiz_type, pattern='^quiz_type_back_to_type_selection$') # Back to type selection
        ],
        SELECT_UNIT_FOR_COURSE: [
            CallbackQueryHandler(select_unit_for_course, pattern='^quiz_unit_.*$'),
            CallbackQueryHandler(select_course_for_unit_quiz, pattern='^quiz_unit_back_to_course_selection$') # Back to course selection
        ],
        ENTER_QUESTION_COUNT: [
            CallbackQueryHandler(select_question_count, pattern='^num_questions_.*$'),
            # Back buttons from question count:
            CallbackQueryHandler(select_unit_for_course, pattern='^quiz_count_back_to_unit_selection_.*$'), # Back to unit selection
            CallbackQueryHandler(select_quiz_type, pattern='^quiz_type_back_to_type_selection$') # Back to type selection (for QUIZ_TYPE_ALL)
        ],
        TAKING_QUIZ: [
            CallbackQueryHandler(handle_quiz_answer, pattern='^answer_.*$'),
            CallbackQueryHandler(end_quiz_conversation, pattern='^end_quiz_early$') # Optional: Button to end quiz early
        ],
        SHOWING_RESULTS: [ # This state might be mostly managed by QuizLogic's final message
            CallbackQueryHandler(quiz_results, pattern='^view_quiz_results_again$'), # If there's a button to view again
            CallbackQueryHandler(main_menu_callback, pattern='^main_menu$') # Back to main menu from results
        ]
    },
    fallbacks=[
        CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'), # Global fallback to main menu
        CallbackQueryHandler(end_quiz_conversation, pattern='^end_quiz_final$'), # A generic end quiz button
        CommandHandler('start', start_command_fallback_for_quiz), # Handle /start during quiz
        MessageHandler(filters.COMMAND, start_command_fallback_for_quiz) # Handle any other command as /start
    ],
    map_to_parent={
        # If ConversationHandler.END is returned, control goes back to parent conversation if one exists
        ConversationHandler.END: MAIN_MENU # Or whatever state should be next after quiz ends
    },
    per_message=False, # Allow multiple interactions with the same message (e.g. paginations)
    name="quiz_conversation",
    persistent=True # Uses PicklePersistence if configured
)

