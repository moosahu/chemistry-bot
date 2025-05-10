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
        api_response = fetch_from_api("api/v1/questions/all")
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
        courses = fetch_from_api("api/v1/courses")
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
        page = int(callback_data.split("_")[-1])
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

    units = fetch_from_api(f"api/v1/courses/{selected_course_id}/units")
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

    courses = context.user_data.get("available_courses_for_unit_quiz", [])
    current_course_page = context.user_data.get("current_course_page_for_unit_quiz", 0)
    selected_course_id = context.user_data.get("selected_course_id_for_unit_quiz")
    selected_course_name = context.user_data.get("selected_course_name_for_unit_quiz", "المقرر المحدد")

    if callback_data.startswith("quiz_action_back_to_course_selection_"):
        kbd = create_course_selection_keyboard(courses, current_course_page)
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "اختر المقرر الدراسي:", kbd)
        return SELECT_COURSE_FOR_UNIT_QUIZ

    if callback_data.startswith("quiz_unit_page_"):
        parts = callback_data.split("_")
        page = int(parts[-1])
        # course_id_from_cb = parts[-2] # Not strictly needed if selected_course_id is reliable
        context.user_data["current_unit_page_for_course"] = page
        units = context.user_data["available_units_for_course"]
        kbd = create_unit_selection_keyboard(units, selected_course_id, page)
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"اختر الوحدة الدراسية للمقرر '{selected_course_name}':", kbd)
        return SELECT_UNIT_FOR_COURSE

    parts = callback_data.replace("quiz_unit_select_", "", 1).split("_")
    # course_id_from_cb = parts[0]
    selected_unit_id = parts[-1] # Assuming unit_id is the last part
    context.user_data["selected_unit_id"] = selected_unit_id
    context.user_data["selected_quiz_scope_id"] = selected_unit_id # For unit quizzes, scope is the unit ID
    units = context.user_data.get("available_units_for_course", [])
    selected_unit_name = next((u.get("name") for u in units if str(u.get("id")) == str(selected_unit_id)), "وحدة غير معروفة")
    context.user_data["selected_unit_name"] = selected_unit_name

    api_response = fetch_from_api(f"api/v1/units/{selected_unit_id}/questions")
    api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
    if api_response == "TIMEOUT":
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, api_timeout_message, create_unit_selection_keyboard(units, selected_course_id, context.user_data.get("current_unit_page_for_course",0)))
        return SELECT_UNIT_FOR_COURSE
    if not api_response or not isinstance(api_response, list):
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"لا توجد أسئلة متاحة للوحدة '{selected_unit_name}'.", create_unit_selection_keyboard(units, selected_course_id, context.user_data.get("current_unit_page_for_course",0)))
        return SELECT_UNIT_FOR_COURSE

    context.user_data["questions_for_quiz"] = api_response # Store raw questions
    max_q = len(api_response)
    kbd = create_question_count_keyboard(max_q, QUIZ_TYPE_UNIT, unit_id=selected_unit_id, course_id_for_unit=selected_course_id)
    await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"اختر عدد الأسئلة لاختبار الوحدة '{selected_unit_name}' من مقرر '{selected_course_name}': (المتاح: {max_q})", kbd)
    return ENTER_QUESTION_COUNT

async def enter_question_count_handler(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    callback_data = query.data
    message_id_to_edit = query.message.message_id
    context.user_data[f"last_quiz_interaction_message_id_{chat_id}"] = message_id_to_edit

    quiz_type = context.user_data.get("selected_quiz_type_key")
    unit_id = context.user_data.get("selected_unit_id") # Will be None for QUIZ_TYPE_ALL
    course_id_for_unit = context.user_data.get("selected_course_id_for_unit_quiz") # For back button

    if callback_data.startswith("quiz_action_back_to_unit_selection_"):
        # This implies it was a unit quiz, go back to unit selection for that course
        parts = callback_data.split("_")
        # course_id_from_cb = parts[-2]
        # unit_id_from_cb = parts[-1] # Not needed, we use stored selected_course_id
        units = context.user_data.get("available_units_for_course", [])
        current_unit_page = context.user_data.get("current_unit_page_for_course", 0)
        selected_course_name = context.user_data.get("selected_course_name_for_unit_quiz", "المقرر المحدد")
        kbd = create_unit_selection_keyboard(units, course_id_for_unit, current_unit_page)
        await safe_edit_message_text(context.bot, chat_id, message_id_to_edit, f"اختر الوحدة الدراسية للمقرر '{selected_course_name}':", kbd)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data == "quiz_action_back_to_type_selection": # From QUIZ_TYPE_ALL
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id, message_id_to_edit, "🧠 اختر نوع الاختبار:", keyboard)
        return SELECT_QUIZ_TYPE

    raw_questions = context.user_data.get("questions_for_quiz", [])
    if not raw_questions:
        await safe_edit_message_text(context.bot, chat_id, message_id_to_edit, "عذراً، لا توجد أسئلة متاحة لبدء الاختبار. يرجى المحاولة مرة أخرى.", create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE # Go back to type selection

    if callback_data == "num_questions_all":
        num_questions = len(raw_questions)
    elif callback_data.startswith("num_questions_"):
        try:
            num_questions = int(callback_data.replace("num_questions_", "", 1))
        except ValueError:
            logger.error(f"Invalid num_questions callback: {callback_data}")
            await safe_edit_message_text(context.bot, chat_id, message_id_to_edit, "عدد أسئلة غير صالح.")
            # Re-show the question count keyboard
            max_q = len(raw_questions)
            kbd = create_question_count_keyboard(max_q, quiz_type, unit_id, course_id_for_unit)
            quiz_type_display_name = context.user_data.get("selected_quiz_type_display_name", "الاختبار")
            scope_name = context.user_data.get("selected_unit_name", quiz_type_display_name)
            await safe_edit_message_text(context.bot, chat_id, message_id_to_edit, f"اختر عدد الأسئلة لاختبار '{scope_name}': (المتاح: {max_q})", kbd)
            return ENTER_QUESTION_COUNT
    else:
        logger.warning(f"Unhandled callback in enter_question_count_handler: {callback_data}")
        return ENTER_QUESTION_COUNT # Stay in the same state

    context.user_data["question_count_for_quiz"] = num_questions
    
    # Transform questions using api_client.transform_api_question
    transformed_questions = []
    for q_data in raw_questions:
        transformed_q = transform_api_question(q_data)
        if transformed_q:
            transformed_questions.append(transformed_q)
        else:
            logger.warning(f"Failed to transform question from API: {q_data.get('id', 'Unknown ID')}")

    if not transformed_questions:
        await safe_edit_message_text(context.bot, chat_id, message_id_to_edit, "عذراً، لم يتم العثور على أسئلة صالحة لبدء الاختبار. يرجى المحاولة مرة أخرى.", create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    # Shuffle and select the number of questions
    random.shuffle(transformed_questions)
    final_questions_for_quiz = transformed_questions[:num_questions]

    if not final_questions_for_quiz:
        await safe_edit_message_text(context.bot, chat_id, message_id_to_edit, "عذراً، لا توجد أسئلة كافية لبدء الاختبار بالعدد المطلوب. يرجى اختيار عدد أقل أو المحاولة لاحقاً.", create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    quiz_name_parts = []
    quiz_type_display = context.user_data.get("selected_quiz_type_display_name", "اختبار")
    quiz_name_parts.append(quiz_type_display)
    if quiz_type == QUIZ_TYPE_UNIT:
        course_name = context.user_data.get("selected_course_name_for_unit_quiz", "")
        unit_name = context.user_data.get("selected_unit_name", "")
        if course_name: quiz_name_parts.append(f"مقرر: {course_name}")
        if unit_name: quiz_name_parts.append(f"وحدة: {unit_name}")
    quiz_name_full = " - ".join(quiz_name_parts)
    
    quiz_scope_id = context.user_data.get("selected_quiz_scope_id", "unknown_scope")
    quiz_instance_id = str(uuid.uuid4()) # Unique ID for this quiz attempt
    context.user_data[f"quiz_instance_id_{user_id}"] = quiz_instance_id

    # Create QuizLogic instance
    try:
        quiz_logic_instance = QuizLogic(
            user_id=user_id,
            chat_id=chat_id,
            questions_data=final_questions_for_quiz,
            quiz_name=quiz_name_full, # Descriptive name
            quiz_type=quiz_type, # e.g., QUIZ_TYPE_ALL, QUIZ_TYPE_UNIT
            filter_id=quiz_scope_id, # e.g., "all" or unit_id
            time_limit_per_question=DEFAULT_QUESTION_TIME_LIMIT,
            quiz_instance_id=quiz_instance_id
        )
        context.user_data[f"quiz_logic_instance_{user_id}"] = quiz_logic_instance
        logger.info(f"[QuizSetup] QuizLogic instance {quiz_instance_id} created for user {user_id}. Starting quiz.")
    except Exception as e_ql_init:
        logger.exception(f"[QuizSetup] Failed to initialize QuizLogic for user {user_id}: {e_ql_init}")
        await safe_edit_message_text(context.bot, chat_id, message_id_to_edit, "حدث خطأ أثناء إعداد الاختبار. يرجى المحاولة لاحقاً.", create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    # Start the quiz via QuizLogic
    initial_quiz_message, initial_keyboard, success = await quiz_logic_instance.start_quiz(update, context)
    if success:
        await safe_edit_message_text(context.bot, chat_id, message_id_to_edit, initial_quiz_message, initial_keyboard)
        return TAKING_QUIZ
    else:
        # QuizLogic.start_quiz should send its own error message if it fails internally
        logger.error(f"[QuizSetup] QuizLogic.start_quiz failed for user {user_id}, instance {quiz_instance_id}. Error message should have been sent by QuizLogic.")
        # Fallback error message if QuizLogic didn't send one
        await safe_edit_message_text(context.bot, chat_id, message_id_to_edit, "حدث خطأ ما. يرجى المحاولة مرة أخرى لاحقاً.", create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE # Go back to type selection

# --- Taking Quiz States --- 
async def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    answer_data = query.data # This is the callback_data from the button
    message_id_to_edit = query.message.message_id
    context.user_data[f"last_quiz_interaction_message_id_{chat_id}"] = message_id_to_edit

    quiz_logic_instance = context.user_data.get(f"quiz_logic_instance_{user_id}")
    if not isinstance(quiz_logic_instance, QuizLogic) or not quiz_logic_instance.active:
        logger.warning(f"User {user_id} (chat {chat_id}) tried to answer, but no active QuizLogic instance found.")
        await safe_edit_message_text(context.bot, chat_id, message_id_to_edit, "لم يتم العثور على اختبار نشط. يرجى بدء اختبار جديد.", create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    # Pass the answer_data to QuizLogic's handle_answer method
    next_state = await quiz_logic_instance.handle_answer(update, context, answer_data=answer_data)
    return next_state # TAKING_QUIZ or SHOWING_RESULTS

async def handle_quiz_timeout(context: CallbackContext):
    job = context.job
    user_id = job.data["user_id"]
    chat_id = job.data["chat_id"]
    quiz_instance_id_from_job = job.data["quiz_instance_id"]
    question_index_from_job = job.data["question_index"]
    
    logger.info(f"[QuizTimeout] Timeout for user {user_id}, quiz {quiz_instance_id_from_job}, Q{question_index_from_job}")

    quiz_logic_instance = context.user_data.get(f"quiz_logic_instance_{user_id}")
    if not isinstance(quiz_logic_instance, QuizLogic) or \
       not quiz_logic_instance.active or \
       quiz_logic_instance.quiz_instance_id != quiz_instance_id_from_job or \
       quiz_logic_instance.current_question_index != question_index_from_job:
        logger.warning(f"[QuizTimeout] Stale or mismatched timeout job for user {user_id}. QuizLogic instance: {quiz_logic_instance.quiz_instance_id if quiz_logic_instance else 'None'}, Job quiz_id: {quiz_instance_id_from_job}. Current Q_idx: {quiz_logic_instance.current_question_index if quiz_logic_instance else 'N/A'}, Job Q_idx: {question_index_from_job}. Ignoring.")
        return

    # Call QuizLogic's method to handle the timeout for the specific question
    next_state = await quiz_logic_instance.handle_question_timeout(context)
    # The QuizLogic instance should handle sending messages and updating state.
    # The return value of handle_question_timeout might not be directly usable as a ConversationHandler state here,
    # as this is called from a job, not a handler. The QuizLogic instance manages its own state.
    # We don't return a state here as it's a job callback.

# --- Showing Results State --- 
async def show_results_entry(update: Update, context: CallbackContext) -> int:
    # This state is typically entered directly from QuizLogic when the quiz ends.
    # QuizLogic's handle_answer or handle_question_timeout should have already sent the results message.
    # This handler is mainly a placeholder or for actions after results are shown (e.g., back to menu).
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    callback_data = query.data
    message_id_to_edit = query.message.message_id
    context.user_data[f"last_quiz_interaction_message_id_{chat_id}"] = message_id_to_edit

    quiz_logic_instance = context.user_data.get(f"quiz_logic_instance_{user_id}")

    if callback_data == "quiz_action_main_menu_from_results":
        logger.info(f"User {user_id} chose main menu from results.")
        await _cleanup_quiz_session_data(user_id, chat_id, context, "main_menu_from_results")
        await main_menu_callback(update, context) # Call the common main menu callback
        return ConversationHandler.END
    elif callback_data == "quiz_action_restart_quiz_selection":
        logger.info(f"User {user_id} chose to restart quiz selection from results.")
        # Cleanup is important before restarting the quiz selection flow
        await _cleanup_quiz_session_data(user_id, chat_id, context, "restart_quiz_selection_from_results")
        return await quiz_menu_entry(update, context) # Go back to the very first step
    elif callback_data == "quiz_action_show_my_stats_from_results":
        # This would ideally transition to the stats conversation handler
        # For now, let's just send a message and end this conversation.
        # Proper transition requires more complex inter-conversation handling.
        logger.info(f"User {user_id} chose to see stats from results.")
        await _cleanup_quiz_session_data(user_id, chat_id, context, "show_stats_from_results")
        await safe_edit_message_text(context.bot, chat_id, message_id_to_edit, "لعرض الإحصائيات، يرجى استخدام الأمر /stats أو الذهاب إلى القائمة الرئيسية واختيار الإحصائيات.")
        # Ideally, you'd call the entry point of your stats conversation handler here if possible
        # For simplicity, we end and let the user navigate.
        return ConversationHandler.END 
    else:
        logger.warning(f"Unhandled callback in show_results_entry: {callback_data}")
        # If QuizLogic instance is still around and active, it might have sent a message.
        # Otherwise, resend a generic results menu if possible or an error.
        if isinstance(quiz_logic_instance, QuizLogic) and not quiz_logic_instance.active:
            # Quiz is over, QuizLogic should have sent results. We can offer menu again.
            # This part is tricky as QuizLogic should manage the final message.
            # Let's assume QuizLogic already sent the final message with options.
            pass # Stay in this state, user might click another button from results message
        else:
            await safe_edit_message_text(context.bot, chat_id, message_id_to_edit, "انتهى الاختبار. اختر من الخيارات أدناه.") # Fallback
        return SHOWING_RESULTS

# --- Conversation Handler Setup --- 
quiz_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(quiz_menu_entry, pattern="^start_quiz$")],
    states={
        SELECT_QUIZ_TYPE: [
            CallbackQueryHandler(select_quiz_type_handler, pattern="^quiz_type_|^quiz_action_main_menu$|^quiz_action_back_to_type_selection$")
        ],
        SELECT_COURSE_FOR_UNIT_QUIZ: [
            CallbackQueryHandler(select_course_for_unit_quiz_handler, pattern="^quiz_course_select_|^quiz_course_page_|^quiz_action_back_to_type_selection$")
        ],
        SELECT_UNIT_FOR_COURSE: [
            CallbackQueryHandler(select_unit_for_course_handler, pattern="^quiz_unit_select_|^quiz_unit_page_|^quiz_action_back_to_course_selection_")
        ],
        ENTER_QUESTION_COUNT: [
            CallbackQueryHandler(enter_question_count_handler, pattern="^num_questions_|^quiz_action_back_to_unit_selection_|^quiz_action_back_to_type_selection$")
        ],
        TAKING_QUIZ: [
            CallbackQueryHandler(handle_quiz_answer, pattern="^answer_") # Pattern for answer callbacks
        ],
        SHOWING_RESULTS: [
            CallbackQueryHandler(show_results_entry, pattern="^quiz_action_main_menu_from_results$|^quiz_action_restart_quiz_selection$|^quiz_action_show_my_stats_from_results$")
        ],
    },
    fallbacks=[
        CommandHandler("start", start_command_fallback_for_quiz), # Handle /start if user gets stuck
        CallbackQueryHandler(go_to_main_menu_from_quiz, pattern="^quiz_action_main_menu$"), # General main menu fallback
        CallbackQueryHandler(main_menu_callback, pattern="^main_menu$") # Fallback to global main menu if other patterns fail
    ],
    name="quiz_conversation",
    persistent=False, # Important: Set to False as we are managing DB_MANAGER outside bot_data
    # per_user=True, per_chat=True, per_message=False # Default, seems fine
)

logger.info("Quiz conversation handler (quiz.py) loaded.")

