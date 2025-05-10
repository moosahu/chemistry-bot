"""
Conversation handler for the quiz selection and execution flow.
(MODIFIED: Uses api_client.py for questions, QuizLogic imports DB_MANAGER directly)
"""

import logging
import random
import uuid # For quiz_instance_id
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters
)

from config import (
    logger,
    MAIN_MENU, QUIZ_MENU, SELECT_QUIZ_TYPE, 
    SELECT_COURSE_FOR_UNIT_QUIZ, SELECT_UNIT_FOR_COURSE, 
    ENTER_QUESTION_COUNT, TAKING_QUIZ, SHOWING_RESULTS, END,
    QUIZ_TYPE_ALL, QUIZ_TYPE_UNIT, 
    DEFAULT_QUESTION_TIME_LIMIT
)
from utils.helpers import safe_send_message, safe_edit_message_text, get_quiz_type_string, remove_job_if_exists
# Assuming api_client.py is in utils and has fetch_from_api and transform_api_question
from utils.api_client import fetch_from_api, transform_api_question 
from handlers.common import main_menu_callback, start_command 
# Assuming quiz_logic_modified_v1.py is now handlers.quiz_logic.py
from .quiz_logic import QuizLogic 

ITEMS_PER_PAGE = 6

# --- Utility function to clean up quiz-related user_data and jobs ---
async def _cleanup_quiz_session_data(user_id: int, chat_id: int, context: CallbackContext, reason: str):
    logger.info(f"[QuizCleanup] Cleaning up quiz session data for user {user_id}, chat {chat_id}. Reason: {reason}")
    
    active_quiz_logic_instance = context.user_data.get(f"quiz_logic_instance_{user_id}")
    if isinstance(active_quiz_logic_instance, QuizLogic) and active_quiz_logic_instance.active:
        logger.info(f"[QuizCleanup] Active QuizLogic instance found for user {user_id}. Calling its cleanup.")
        try:
            # The QuizLogic's own cleanup should handle its internal state and timers.
            await active_quiz_logic_instance.cleanup_quiz_data(context, user_id, f"cleanup_from_quiz_handler_{reason}")
        except Exception as e_cleanup:
            logger.error(f"[QuizCleanup] Error during QuizLogic internal cleanup for user {user_id}: {e_cleanup}")

    keys_to_pop = [
        f"quiz_logic_instance_{user_id}",
        "selected_quiz_type_key", "selected_quiz_type_display_name", 
        "questions_for_quiz", # This might hold raw questions before QuizLogic instance is created
        "selected_course_id_for_unit_quiz", "available_courses_for_unit_quiz",
        "current_course_page_for_unit_quiz", "selected_course_name_for_unit_quiz",
        "available_units_for_course", "current_unit_page_for_course",
        "selected_unit_id", "selected_unit_name", "question_count_for_quiz",
        f"quiz_setup_{QUIZ_TYPE_ALL}_all", # Specific setup data
        # Add other quiz_setup_{type}_{id} keys if used
    ]
    for key in keys_to_pop:
        if key in context.user_data:
            context.user_data.pop(key, None)
            logger.debug(f"[QuizCleanup] Popped key: {key}")

    # Robust cleanup for dynamic keys like timers and last interaction message ID
    # Note: QuizLogic's cleanup should ideally handle its own timers.
    # This is a secondary safeguard or for timers set outside QuizLogic.
    for key_ud in list(context.user_data.keys()): 
        if key_ud.startswith(f"question_timer_{chat_id}") or \
           key_ud.startswith(f"last_quiz_interaction_message_id_{chat_id}") or \
           key_ud.startswith("quiz_setup_"): # General catch-all for other setup data
            if key_ud.startswith(f"question_timer_{chat_id}"):
                 remove_job_if_exists(key_ud, context) # Also remove job from queue
            context.user_data.pop(key_ud, None)
            logger.debug(f"[QuizCleanup] Popped dynamic key: {key_ud}")
    logger.info(f"[QuizCleanup] Finished cleaning quiz session data for user {user_id}, chat {chat_id}.")

async def start_command_fallback_for_quiz(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    logger.info(f"User {user_id} (chat {chat_id}) sent /start during quiz_conv. Ending quiz_conv, showing main menu.")
    await _cleanup_quiz_session_data(user_id, chat_id, context, "start_command_fallback")
    await start_command(update, context) # Call the main start command handler
    return ConversationHandler.END

async def go_to_main_menu_from_quiz(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    logger.info(f"User {user_id} (chat {chat_id}) chose to go to main menu from quiz conversation. Ending quiz_conv.")
    await _cleanup_quiz_session_data(user_id, chat_id, context, "main_menu_request")
    await main_menu_callback(update, context) # Call the common main menu callback
    return ConversationHandler.END

# --- Keyboards --- 
def create_quiz_type_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🎲 اختبار عشوائي شامل (كل المقررات)", callback_data=f"quiz_type_{QUIZ_TYPE_ALL}")],
        [InlineKeyboardButton("📚 حسب الوحدة الدراسية (اختر المقرر ثم الوحدة)", callback_data=f"quiz_type_{QUIZ_TYPE_UNIT}")],
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="quiz_action_main_menu")] 
    ]
    return InlineKeyboardMarkup(keyboard)

def create_course_selection_keyboard(courses: list, current_page: int = 0) -> InlineKeyboardMarkup:
    keyboard = []
    start_index = current_page * ITEMS_PER_PAGE
    end_index = start_index + ITEMS_PER_PAGE
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
    keyboard.append([InlineKeyboardButton("🔙 اختيار نوع الاختبار", callback_data="quiz_action_back_to_type_selection")])
    return InlineKeyboardMarkup(keyboard)

def create_unit_selection_keyboard(units: list, course_id: str, current_page: int = 0) -> InlineKeyboardMarkup:
    keyboard = []
    start_index = current_page * ITEMS_PER_PAGE
    end_index = start_index + ITEMS_PER_PAGE
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
    keyboard.append([InlineKeyboardButton("🔙 اختيار المقرر", callback_data=f"quiz_action_back_to_course_selection_{course_id}")])
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
        if len(row) == 3: keyboard.append(row); row = []
    if row: keyboard.append(row)
    if not counts or (counts and max_questions > 0 and (max_questions > counts[-1] if counts else True)):
         keyboard.append([InlineKeyboardButton(f"الكل ({max_questions})", callback_data="num_questions_all")])
    
    back_callback_data = "quiz_action_back_to_type_selection"
    if quiz_type == QUIZ_TYPE_UNIT:
        if course_id_for_unit and unit_id: 
             back_callback_data = f"quiz_action_back_to_unit_selection_{course_id_for_unit}_{unit_id}"
        elif course_id_for_unit: 
             back_callback_data = f"quiz_action_back_to_course_selection_{course_id_for_unit}"
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback_data)])
    return InlineKeyboardMarkup(keyboard)

# --- Quiz Setup States --- 
async def quiz_menu_entry(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    message_id_to_edit = None

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        message_id_to_edit = query.message.message_id
    
    await _cleanup_quiz_session_data(user_id, chat_id, context, "quiz_menu_entry") # Fresh start
    
    keyboard = create_quiz_type_keyboard()
    text_to_send = "🧠 اختر نوع الاختبار:"
    if message_id_to_edit:
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=message_id_to_edit, text=text_to_send, reply_markup=keyboard)
    else:
        sent_msg = await safe_send_message(context.bot, chat_id=chat_id, text=text_to_send, reply_markup=keyboard)
        if sent_msg: context.user_data[f"last_quiz_interaction_message_id_{chat_id}"] = sent_msg.message_id
    return SELECT_QUIZ_TYPE

async def select_quiz_type_handler(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    callback_data = query.data
    context.user_data[f"last_quiz_interaction_message_id_{chat_id}"] = query.message.message_id

    if callback_data == "quiz_action_main_menu":
        return await go_to_main_menu_from_quiz(update, context)
    if callback_data == "quiz_action_back_to_type_selection": # User wants to go back to type selection
        return await quiz_menu_entry(update, context) # Re-enter the first step

    quiz_type_key = callback_data.replace("quiz_type_", "", 1)
    context.user_data["selected_quiz_type_key"] = quiz_type_key
    quiz_type_display_name = get_quiz_type_string(quiz_type_key)
    context.user_data["selected_quiz_type_display_name"] = quiz_type_display_name
    
    error_text_general = "عذراً، حدث خطأ أثناء جلب البيانات. يرجى المحاولة لاحقاً."
    error_text_no_data = lambda item: f"عذراً، لا توجد {item} متاحة حالياً."
    api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."

    if quiz_type_key == QUIZ_TYPE_ALL:
        api_response = await fetch_from_api("api/v1/questions/all")
        if api_response == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id, query.message.message_id, api_timeout_message, create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE 
        if not api_response or not isinstance(api_response, list):
            await safe_edit_message_text(context.bot, chat_id, query.message.message_id, error_text_no_data("أسئلة شاملة"), create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        
        context.user_data["questions_for_quiz"] = api_response # Store raw questions
        context.user_data["selected_quiz_scope_id"] = "all"
        max_q = len(api_response)
        kbd = create_question_count_keyboard(max_q, quiz_type_key, unit_id="all")
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"اختر عدد الأسئلة لاختبار '{quiz_type_display_name}': (المتاح: {max_q})", kbd)
        return ENTER_QUESTION_COUNT

    elif quiz_type_key == QUIZ_TYPE_UNIT:
        courses = await fetch_from_api("api/v1/courses")
        if courses == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id, query.message.message_id, api_timeout_message, create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        if not courses or not isinstance(courses, list) or not courses:
            await safe_edit_message_text(context.bot, chat_id, query.message.message_id, error_text_no_data("مقررات دراسية"), create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        context.user_data["available_courses_for_unit_quiz"] = courses
        context.user_data["current_course_page_for_unit_quiz"] = 0
        kbd = create_course_selection_keyboard(courses, 0)
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "اختر المقرر الدراسي:", kbd)
        return SELECT_COURSE_FOR_UNIT_QUIZ
    else:
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "نوع اختبار غير صالح.", create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

async def select_course_for_unit_quiz_handler(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    callback_data = query.data
    context.user_data[f"last_quiz_interaction_message_id_{chat_id}"] = query.message.message_id

    if callback_data == "quiz_action_back_to_type_selection":
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "🧠 اختر نوع الاختبار:", keyboard)
        return SELECT_QUIZ_TYPE

    if callback_data.startswith("quiz_course_page_"):
        page = int(callback_data.split('_')[-1])
        context.user_data["current_course_page_for_unit_quiz"] = page
        courses = context.user_data["available_courses_for_unit_quiz"]
        kbd = create_course_selection_keyboard(courses, page)
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "اختر المقرر الدراسي:", kbd)
        return SELECT_COURSE_FOR_UNIT_QUIZ

    selected_course_id = callback_data.replace("quiz_course_select_", "", 1)
    context.user_data["selected_course_id_for_unit_quiz"] = selected_course_id
    courses = context.user_data.get("available_courses_for_unit_quiz", [])
    selected_course_name = next((c.get("name") for c in courses if str(c.get("id")) == str(selected_course_id)), "مقرر غير معروف")
    context.user_data["selected_course_name_for_unit_quiz"] = selected_course_name

    units = await fetch_from_api(f"api/v1/courses/{selected_course_id}/units")
    api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
    if units == "TIMEOUT":
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, api_timeout_message, create_course_selection_keyboard(courses, context.user_data.get("current_course_page_for_unit_quiz",0)))
        return SELECT_COURSE_FOR_UNIT_QUIZ
    if not units or not isinstance(units, list) or not units:
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"لا توجد وحدات متاحة للمقرر '{selected_course_name}'.", create_course_selection_keyboard(courses, context.user_data.get("current_course_page_for_unit_quiz",0)))
        return SELECT_COURSE_FOR_UNIT_QUIZ
    
    context.user_data["available_units_for_course"] = units
    context.user_data["current_unit_page_for_course"] = 0
    kbd = create_unit_selection_keyboard(units, selected_course_id, 0)
    await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"اختر الوحدة الدراسية للمقرر '{selected_course_name}':", kbd)
    return SELECT_UNIT_FOR_COURSE

async def select_unit_for_course_handler(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    callback_data = query.data
    context.user_data[f"last_quiz_interaction_message_id_{chat_id}"] = query.message.message_id
    selected_course_id = context.user_data["selected_course_id_for_unit_quiz"]
    courses = context.user_data["available_courses_for_unit_quiz"]
    current_course_page = context.user_data.get("current_course_page_for_unit_quiz", 0)

    if callback_data.startswith(f"quiz_action_back_to_course_selection_{selected_course_id}"):
        kbd = create_course_selection_keyboard(courses, current_course_page)
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "اختر المقرر الدراسي:", kbd)
        return SELECT_COURSE_FOR_UNIT_QUIZ

    if callback_data.startswith("quiz_unit_page_"):
        parts = callback_data.split('_')
        page = int(parts[-1])
        # course_id_from_cb = parts[-2] # Already have selected_course_id
        context.user_data["current_unit_page_for_course"] = page
        units = context.user_data["available_units_for_course"]
        kbd = create_unit_selection_keyboard(units, selected_course_id, page)
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"اختر الوحدة الدراسية للمقرر '{context.user_data['selected_course_name_for_unit_quiz']}':", kbd)
        return SELECT_UNIT_FOR_COURSE

    # Format: quiz_unit_select_{course_id}_{unit_id}
    parts = callback_data.replace("quiz_unit_select_", "", 1).split('_', 1)
    # selected_course_id_from_cb = parts[0] # Already have selected_course_id
    selected_unit_id = parts[1]
    context.user_data["selected_unit_id"] = selected_unit_id
    units = context.user_data.get("available_units_for_course", [])
    selected_unit_name = next((u.get("name") for u in units if str(u.get("id")) == str(selected_unit_id)), "وحدة غير معروفة")
    context.user_data["selected_unit_name"] = selected_unit_name

    questions = await fetch_from_api(f"api/v1/units/{selected_unit_id}/questions")
    api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
    current_unit_page = context.user_data.get("current_unit_page_for_course", 0)

    if questions == "TIMEOUT":
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, api_timeout_message, create_unit_selection_keyboard(units, selected_course_id, current_unit_page))
        return SELECT_UNIT_FOR_COURSE
    if not questions or not isinstance(questions, list) or not questions:
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"لا توجد أسئلة متاحة للوحدة '{selected_unit_name}'.", create_unit_selection_keyboard(units, selected_course_id, current_unit_page))
        return SELECT_UNIT_FOR_COURSE

    context.user_data["questions_for_quiz"] = questions # Store raw questions
    context.user_data["selected_quiz_scope_id"] = selected_unit_id
    max_q = len(questions)
    kbd = create_question_count_keyboard(max_q, QUIZ_TYPE_UNIT, unit_id=selected_unit_id, course_id_for_unit=selected_course_id)
    await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"اختر عدد الأسئلة لاختبار الوحدة '{selected_unit_name}' (المقرر: '{context.user_data['selected_course_name_for_unit_quiz']}'): (المتاح: {max_q})", kbd)
    return ENTER_QUESTION_COUNT

async def enter_question_count_handler(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    callback_data = query.data
    context.user_data[f"last_quiz_interaction_message_id_{chat_id}"] = query.message.message_id

    quiz_type = context.user_data["selected_quiz_type_key"]
    unit_id = context.user_data.get("selected_unit_id") # Will be 'all' for QUIZ_TYPE_ALL
    course_id = context.user_data.get("selected_course_id_for_unit_quiz")

    # Handle back navigation
    if callback_data == "quiz_action_back_to_type_selection":
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "🧠 اختر نوع الاختبار:", keyboard)
        return SELECT_QUIZ_TYPE
    if callback_data.startswith("quiz_action_back_to_unit_selection_"):
        # cb: quiz_action_back_to_unit_selection_{course_id}_{unit_id} -> we need course_id
        # We should have course_id in context.user_data["selected_course_id_for_unit_quiz"]
        # And units in context.user_data["available_units_for_course"]
        units_for_course = context.user_data.get("available_units_for_course", [])
        current_unit_page = context.user_data.get("current_unit_page_for_course", 0)
        kbd = create_unit_selection_keyboard(units_for_course, course_id, current_unit_page)
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"اختر الوحدة الدراسية للمقرر '{context.user_data['selected_course_name_for_unit_quiz']}':", kbd)
        return SELECT_UNIT_FOR_COURSE
    if callback_data.startswith("quiz_action_back_to_course_selection_"):
        courses = context.user_data["available_courses_for_unit_quiz"]
        current_course_page = context.user_data.get("current_course_page_for_unit_quiz", 0)
        kbd = create_course_selection_keyboard(courses, current_course_page)
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "اختر المقرر الدراسي:", kbd)
        return SELECT_COURSE_FOR_UNIT_QUIZ

    raw_questions = context.user_data.get("questions_for_quiz", [])
    if not raw_questions:
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "خطأ: لم يتم العثور على أسئلة. يرجى البدء من جديد.", create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE # Or END

    num_questions_to_take = 0
    if callback_data == "num_questions_all":
        num_questions_to_take = len(raw_questions)
    elif callback_data.startswith("num_questions_"):
        try:
            num_questions_to_take = int(callback_data.replace("num_questions_", ""))
        except ValueError:
            await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "عدد أسئلة غير صالح. حاول مرة أخرى.")
            # Resend the question count keyboard
            max_q = len(raw_questions)
            kbd = create_question_count_keyboard(max_q, quiz_type, unit_id, course_id)
            await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "اختر عدد الأسئلة:", kbd)
            return ENTER_QUESTION_COUNT
    else:
        # Should not happen with button presses
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "اختيار غير صالح لعدد الأسئلة.")
        return ENTER_QUESTION_COUNT

    if num_questions_to_take <= 0 or num_questions_to_take > len(raw_questions):
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"عدد الأسئلة المطلوب ({num_questions_to_take}) غير صالح أو أكبر من المتاح ({len(raw_questions)}). يرجى الاختيار مرة أخرى.")
        max_q = len(raw_questions)
        kbd = create_question_count_keyboard(max_q, quiz_type, unit_id, course_id)
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "اختر عدد الأسئلة:", kbd)
        return ENTER_QUESTION_COUNT

    context.user_data["question_count_for_quiz"] = num_questions_to_take
    
    # Transform and select questions
    transformed_questions = []
    selected_raw_questions = random.sample(raw_questions, num_questions_to_take) if len(raw_questions) > num_questions_to_take else raw_questions
    
    for raw_q in selected_raw_questions:
        transformed_q = transform_api_question(raw_q) # From api_client.py
        if transformed_q:
            transformed_questions.append(transformed_q)
        else:
            logger.warning(f"[QuizSetup] Failed to transform question from API: {raw_q.get('id', 'N/A')} for user {user_id}")

    if not transformed_questions:
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "فشل في تجهيز الأسئلة. يرجى المحاولة مرة أخرى.", create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    quiz_name = context.user_data.get("selected_quiz_type_display_name", "اختبار")
    if quiz_type == QUIZ_TYPE_UNIT:
        quiz_name = f"{context.user_data.get('selected_course_name_for_unit_quiz', '')} - {context.user_data.get('selected_unit_name', quiz_name)}"
    
    quiz_instance_id = str(uuid.uuid4())
    quiz_logic = QuizLogic(
        user_id=user_id,
        chat_id=chat_id,
        questions=transformed_questions,
        quiz_name=quiz_name,
        quiz_type_for_db_log=quiz_type,
        quiz_scope_id=context.user_data.get("selected_quiz_scope_id", "unknown"),
        total_questions_for_db_log=len(transformed_questions),
        time_limit_per_question=context.user_data.get("time_limit_per_question", DEFAULT_QUESTION_TIME_LIMIT),
        quiz_instance_id_for_logging=quiz_instance_id
        # DB_MANAGER is NOT passed here; QuizLogic imports it directly
    )
    context.user_data[f"quiz_logic_instance_{user_id}"] = quiz_logic
    logger.info(f"[QuizSetup] QuizLogic instance {quiz_instance_id} created for user {user_id}. Starting quiz.")
    
    # Edit the message to indicate quiz is starting, then QuizLogic sends the first question
    await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"جاري بدء اختبار '{quiz_name}' بـ {len(transformed_questions)} أسئلة...", reply_markup=None)
    
    return await quiz_logic.start_quiz(context.bot, context, update) # This will send the first question

# --- Quiz Taking States (Handled by QuizLogic) ---
async def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    # quiz_id_from_cb = query.data.split('_')[1] # Example: ans_QUIZID_qidx_optid
    # Retrieve the QuizLogic instance
    quiz_logic_instance = context.user_data.get(f"quiz_logic_instance_{user_id}")
    if quiz_logic_instance and isinstance(quiz_logic_instance, QuizLogic) and quiz_logic_instance.active:
        return await quiz_logic_instance.handle_answer(update, context)
    else:
        logger.warning(f"[HandleAnswer] No active QuizLogic instance found for user {user_id} or callback is stale. Callback: {query.data}")
        await query.answer("هذا الاختبار لم يعد نشطاً أو أن الزر قديم.")
        # Optionally, try to guide user back to main menu or resend current question if possible (complex)
        # For now, just end or let user figure it out.
        # Check if we can show results if quiz ended abruptly but has data
        if quiz_logic_instance and isinstance(quiz_logic_instance, QuizLogic) and not quiz_logic_instance.active and quiz_logic_instance.answers:
             return await quiz_logic_instance.show_results(context.bot, context, update)
        return TAKING_QUIZ # Or END if quiz is truly gone

# --- Timeout callback (wrapper might be in QuizLogic or here) ---
# This is now primarily handled within QuizLogic. If a global wrapper is needed, it would call the instance method.
# async def question_timeout_callback_wrapper(context: CallbackContext):
#     job_data = context.job.data
#     user_id = job_data.get("user_id") # Assuming user_id is passed in job_data
#     quiz_logic_instance = context.user_data.get(f"quiz_logic_instance_{user_id}")
#     if quiz_logic_instance and isinstance(quiz_logic_instance, QuizLogic):
#         await quiz_logic_instance.question_timeout_auto_skip(context) # Call the instance method
#     else:
#         logger.warning(f"Timeout job triggered but no QuizLogic instance for user {user_id} or job data missing user_id.")

# --- Conversation Handler for Quiz ---
quiz_conv_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(quiz_menu_entry, pattern="^start_quiz$"), # From main menu button
        CommandHandler("quiz", quiz_menu_entry) # Allow starting with /quiz command
    ],
    states={
        SELECT_QUIZ_TYPE: [
            CallbackQueryHandler(select_quiz_type_handler, pattern="^quiz_type_.+$"),
            CallbackQueryHandler(go_to_main_menu_from_quiz, pattern="^quiz_action_main_menu$"),
        ],
        SELECT_COURSE_FOR_UNIT_QUIZ: [
            CallbackQueryHandler(select_course_for_unit_quiz_handler, pattern="^quiz_course_select_.+$"),
            CallbackQueryHandler(select_course_for_unit_quiz_handler, pattern="^quiz_course_page_.+$"),
            CallbackQueryHandler(select_quiz_type_handler, pattern="^quiz_action_back_to_type_selection$") # Back to type selection
        ],
        SELECT_UNIT_FOR_COURSE: [
            CallbackQueryHandler(select_unit_for_course_handler, pattern="^quiz_unit_select_.+_.+$"),
            CallbackQueryHandler(select_unit_for_course_handler, pattern="^quiz_unit_page_.+_.+$"),
            CallbackQueryHandler(select_course_for_unit_quiz_handler, pattern="^quiz_action_back_to_course_selection_.+$") # Back to course selection
        ],
        ENTER_QUESTION_COUNT: [
            CallbackQueryHandler(enter_question_count_handler, pattern="^num_questions_.+$"),
            # Back navigation handlers for question count state
            CallbackQueryHandler(select_quiz_type_handler, pattern="^quiz_action_back_to_type_selection$"),
            CallbackQueryHandler(select_unit_for_course_handler, pattern="^quiz_action_back_to_unit_selection_.+_.+$"), 
            CallbackQueryHandler(select_course_for_unit_quiz_handler, pattern="^quiz_action_back_to_course_selection_.+$")
        ],
        TAKING_QUIZ: [
            CallbackQueryHandler(handle_quiz_answer, pattern="^ans_.+_.+_.+$")
            # Timeout is handled by jobs scheduled by QuizLogic
        ],
        SHOWING_RESULTS: [
            # After results are shown, QuizLogic returns SHOWING_RESULTS.
            # From here, user can go to main menu or stats via buttons provided by QuizLogic's show_results.
            # These are handled by their respective handlers (main_menu_callback, stats_conv_handler entry)
            # We might need a fallback here if user does something unexpected.
            CallbackQueryHandler(go_to_main_menu_from_quiz, pattern="^main_menu$"), # If main_menu button from results
            # CallbackQueryHandler(stats_entry_from_results, pattern="^stats_menu_entry$") # If stats button from results (handled by stats_conv_handler)
        ]
    },
    fallbacks=[
        CommandHandler("start", start_command_fallback_for_quiz),
        CallbackQueryHandler(go_to_main_menu_from_quiz, pattern="^quiz_action_main_menu$"), # General main menu fallback
        CallbackQueryHandler(go_to_main_menu_from_quiz, pattern="^main_menu$") # General main menu fallback
    ],
    map_to_parent={
        # If any state returns MAIN_MENU, it goes to the parent conversation's MAIN_MENU state
        MAIN_MENU: MAIN_MENU,
        # If ConversationHandler.END is returned, the conversation ends.
        END: ConversationHandler.END 
    },
    per_message=False, # Allow multiple users to interact with the bot concurrently
    name="quiz_conversation",
    persistent=False # IMPORTANT: For non-picklable objects like DB_MANAGER, persistence can cause issues.
)

logger.info("Quiz conversation handler (quiz.py) loaded.")

