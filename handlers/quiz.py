"""
Conversation handler for the quiz selection and execution flow.
(MODIFIED: Uses api_client.py for questions, QuizLogic imports DB_MANAGER directly)
(MODIFIED_MANUS: Added handlers for post-quiz buttons in SHOWING_RESULTS state and answer wrapper)
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
from utils.api_client import fetch_from_api, transform_api_question 
from handlers.common import main_menu_callback, start_command 
from .quiz_logic import QuizLogic 
# MANUS_ADDITION: Import stats_menu for transitioning from quiz results
from handlers.stats import stats_menu 

ITEMS_PER_PAGE = 6

async def _cleanup_quiz_session_data(user_id: int, chat_id: int, context: CallbackContext, reason: str):
    logger.info(f"[QuizCleanup] Cleaning up quiz session data for user {user_id}, chat {chat_id}. Reason: {reason}")
    
    active_quiz_logic_instance = context.user_data.get(f"quiz_logic_instance_{user_id}")
    if isinstance(active_quiz_logic_instance, QuizLogic) and active_quiz_logic_instance.active:
        logger.info(f"[QuizCleanup] Active QuizLogic instance found for user {user_id}. Calling its cleanup.")
        try:
            await active_quiz_logic_instance.cleanup_quiz_data(context, user_id, f"cleanup_from_quiz_handler_{reason}", preserve_current_logic_in_userdata=False)
        except Exception as e_cleanup:
            logger.error(f"[QuizCleanup] Error during QuizLogic internal cleanup for user {user_id}: {e_cleanup}")

    keys_to_pop = [
        f"quiz_logic_instance_{user_id}",
        "selected_quiz_type_key", "selected_quiz_type_display_name", 
        "questions_for_quiz", 
        "selected_course_id_for_unit_quiz", "available_courses_for_unit_quiz",
        "current_course_page_for_unit_quiz", "selected_course_name_for_unit_quiz",
        "available_units_for_course", "current_unit_page_for_course",
        "selected_unit_id", "selected_unit_name", "question_count_for_quiz",
        f"quiz_setup_{QUIZ_TYPE_ALL}_all", 
    ]
    for key in keys_to_pop:
        if key in context.user_data:
            context.user_data.pop(key, None)
            logger.debug(f"[QuizCleanup] Popped key: {key}")

    for key_ud in list(context.user_data.keys()): 
        if key_ud.startswith(f"question_timer_{chat_id}") or \
           key_ud.startswith(f"last_quiz_interaction_message_id_{chat_id}") or \
           key_ud.startswith("quiz_setup_"): 
            if key_ud.startswith(f"question_timer_{chat_id}"):
                 remove_job_if_exists(key_ud, context) 
            context.user_data.pop(key_ud, None)
            logger.debug(f"[QuizCleanup] Popped dynamic key: {key_ud}")
    logger.info(f"[QuizCleanup] Finished cleaning quiz session data for user {user_id}, chat {chat_id}.")

async def start_command_fallback_for_quiz(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    logger.info(f"User {user_id} (chat {chat_id}) sent /start during quiz_conv. Ending quiz_conv, showing main menu.")
    await _cleanup_quiz_session_data(user_id, chat_id, context, "start_command_fallback")
    await start_command(update, context) 
    return ConversationHandler.END

async def go_to_main_menu_from_quiz(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    if query: await query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    logger.info(f"User {user_id} (chat {chat_id}) chose to go to main menu from quiz conversation. Ending quiz_conv.")
    await _cleanup_quiz_session_data(user_id, chat_id, context, "main_menu_request_from_quiz")
    await main_menu_callback(update, context) 
    return ConversationHandler.END

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

async def quiz_menu_entry(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    message_id_to_edit = None

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        message_id_to_edit = query.message.message_id
    
    await _cleanup_quiz_session_data(user_id, chat_id, context, "quiz_menu_entry") 
    
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
    if callback_data == "quiz_action_back_to_type_selection": 
        return await quiz_menu_entry(update, context) 

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
        
        context.user_data["questions_for_quiz"] = api_response 
        context.user_data["selected_quiz_scope_id"] = "all"
        max_q = len(api_response)
        kbd = create_question_count_keyboard(max_q, quiz_type_key, unit_id="all")
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"اختر عدد الأسئلة لاختبار 	'{quiz_type_display_name}	': (المتاح: {max_q})", kbd)
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
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"لا توجد وحدات متاحة للمقرر 	'{selected_course_name}	'.", create_course_selection_keyboard(courses, context.user_data.get("current_course_page_for_unit_quiz",0)))
        return SELECT_COURSE_FOR_UNIT_QUIZ
    
    context.user_data["available_units_for_course"] = units
    context.user_data["current_unit_page_for_course"] = 0
    kbd = create_unit_selection_keyboard(units, selected_course_id, 0)
    await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"اختر الوحدة الدراسية للمقرر 	'{selected_course_name}	':", kbd)
    return SELECT_UNIT_FOR_COURSE

async def select_unit_for_course_handler(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    callback_data = query.data
    context.user_data[f"last_quiz_interaction_message_id_{chat_id}"] = query.message.message_id

    selected_course_id = context.user_data.get("selected_course_id_for_unit_quiz")
    courses = context.user_data.get("available_courses_for_unit_quiz", [])
    current_course_page = context.user_data.get("current_course_page_for_unit_quiz", 0)

    if callback_data.startswith("quiz_action_back_to_course_selection_"):
        kbd = create_course_selection_keyboard(courses, current_course_page)
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "اختر المقرر الدراسي:", kbd)
        return SELECT_COURSE_FOR_UNIT_QUIZ

    if callback_data.startswith("quiz_unit_page_"):
        parts = callback_data.split("_")
        page = int(parts[-1])
        # course_id_from_cb = parts[-2] # Not strictly needed if selected_course_id is reliable from user_data
        context.user_data["current_unit_page_for_course"] = page
        units = context.user_data["available_units_for_course"]
        kbd = create_unit_selection_keyboard(units, selected_course_id, page)
        selected_course_name = context.user_data.get("selected_course_name_for_unit_quiz", "")
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"اختر الوحدة الدراسية للمقرر 	'{selected_course_name}	':", kbd)
        return SELECT_UNIT_FOR_COURSE

    parts = callback_data.replace("quiz_unit_select_", "", 1).split("_")
    # course_id_from_cb = parts[0]
    selected_unit_id = parts[-1] # Assuming unit_id doesn't contain underscores
    context.user_data["selected_unit_id"] = selected_unit_id
    units = context.user_data.get("available_units_for_course", [])
    selected_unit_name = next((u.get("name") for u in units if str(u.get("id")) == str(selected_unit_id)), "وحدة غير معروفة")
    context.user_data["selected_unit_name"] = selected_unit_name
    selected_course_name = context.user_data.get("selected_course_name_for_unit_quiz", "")

    api_response = fetch_from_api(f"api/v1/units/{selected_unit_id}/questions")
    api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
    current_unit_page = context.user_data.get("current_unit_page_for_course", 0)

    if api_response == "TIMEOUT":
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, api_timeout_message, create_unit_selection_keyboard(units, selected_course_id, current_unit_page))
        return SELECT_UNIT_FOR_COURSE
    if not api_response or not isinstance(api_response, list):
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"لا توجد أسئلة للوحدة 	'{selected_unit_name}	'.", create_unit_selection_keyboard(units, selected_course_id, current_unit_page))
        return SELECT_UNIT_FOR_COURSE

    context.user_data["questions_for_quiz"] = api_response
    context.user_data["selected_quiz_scope_id"] = selected_unit_id
    max_q = len(api_response)
    kbd = create_question_count_keyboard(max_q, QUIZ_TYPE_UNIT, selected_unit_id, selected_course_id)
    text = f"اختر عدد الأسئلة لاختبار 	'{selected_unit_name}	' (من مقرر 	'{selected_course_name}	'): (المتاح: {max_q})"
    await safe_edit_message_text(context.bot, chat_id, query.message.message_id, text, kbd)
    return ENTER_QUESTION_COUNT

async def enter_question_count_handler(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    callback_data = query.data
    context.user_data[f"last_quiz_interaction_message_id_{chat_id}"] = query.message.message_id

    quiz_type = context.user_data.get("selected_quiz_type_key")
    unit_id = context.user_data.get("selected_unit_id") # Might be None for QUIZ_TYPE_ALL
    course_id = context.user_data.get("selected_course_id_for_unit_quiz") # For unit quizzes

    if callback_data.startswith("quiz_action_back_to_unit_selection_"):
        # This implies it was a unit quiz, so unit_id and course_id should be set
        units = context.user_data.get("available_units_for_course", [])
        current_unit_page = context.user_data.get("current_unit_page_for_course", 0)
        selected_course_name = context.user_data.get("selected_course_name_for_unit_quiz", "")
        kbd = create_unit_selection_keyboard(units, course_id, current_unit_page)
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"اختر الوحدة الدراسية للمقرر 	'{selected_course_name}	':", kbd)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data == "quiz_action_back_to_type_selection": # Back from QUIZ_TYPE_ALL count selection
        return await quiz_menu_entry(update, context)
    
    raw_questions = context.user_data.get("questions_for_quiz", [])
    if not raw_questions:
        logger.error(f"User {user_id}: No questions found in user_data at question count selection.")
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "خطأ: لم يتم العثور على أسئلة. يرجى البدء من جديد.", create_quiz_type_keyboard())
        await _cleanup_quiz_session_data(user_id, chat_id, context, "no_questions_at_q_count")
        return SELECT_QUIZ_TYPE

    num_questions_str = callback_data.replace("num_questions_", "", 1)
    if num_questions_str == "all":
        num_questions = len(raw_questions)
    else:
        try: num_questions = int(num_questions_str)
        except ValueError:
            logger.warning(f"User {user_id}: Invalid question count callback: {callback_data}")
            # Resend the question count keyboard as an error recovery
            max_q_fallback = len(raw_questions)
            kbd_fallback = create_question_count_keyboard(max_q_fallback, quiz_type, unit_id, course_id)
            quiz_name_fallback = context.user_data.get("selected_quiz_type_display_name", "الاختبار")
            await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"عدد أسئلة غير صالح. اختر مجدداً لـ 	'{quiz_name_fallback}	': (المتاح: {max_q_fallback})", kbd_fallback)
            return ENTER_QUESTION_COUNT

    if num_questions <= 0 or num_questions > len(raw_questions):
        logger.warning(f"User {user_id}: Requested {num_questions} but available {len(raw_questions)}. Clamping to available.")
        num_questions = len(raw_questions)
    
    context.user_data["question_count_for_quiz"] = num_questions
    selected_questions_transformed = [transform_api_question(q) for q in random.sample(raw_questions, num_questions)]

    quiz_instance_id = str(uuid.uuid4())
    quiz_name_for_logic = context.user_data.get("selected_quiz_type_display_name", "اختبار")
    if quiz_type == QUIZ_TYPE_UNIT:
        unit_name = context.user_data.get("selected_unit_name", "")
        course_name = context.user_data.get("selected_course_name_for_unit_quiz", "")
        quiz_name_for_logic = f"{course_name} - {unit_name}"
    
    quiz_scope_id_for_logic = context.user_data.get("selected_quiz_scope_id", "all") # e.g., unit_id or "all"

    # Create and store the QuizLogic instance
    quiz_logic_instance = QuizLogic(
        user_id=user_id, chat_id=chat_id, questions=selected_questions_transformed,
        quiz_name=quiz_name_for_logic, quiz_type_for_db_log=quiz_type,
        quiz_scope_id=quiz_scope_id_for_logic, total_questions_for_db_log=num_questions,
        time_limit_per_question=DEFAULT_QUESTION_TIME_LIMIT, 
        quiz_instance_id_for_logging=quiz_instance_id
    )
    context.user_data[f"quiz_logic_instance_{user_id}"] = quiz_logic_instance
    logger.info(f"[QuizSetup] QuizLogic instance {quiz_instance_id} created for user {user_id}. Starting quiz.")
    
    # Start the quiz using the QuizLogic instance
    # The QuizLogic instance will send the first question and manage the flow.
    # It returns the next state (TAKING_QUIZ or SHOWING_RESULTS if no questions).
    return await quiz_logic_instance.start_quiz(context.bot, context, update)

# MANUS_MODIFICATION: Wrapper for QuizLogic's handle_answer
async def handle_quiz_answer_wrapper(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    # query.answer() is called within QuizLogic methods
    
    user_id = query.from_user.id
    quiz_logic_instance = context.user_data.get(f"quiz_logic_instance_{user_id}")
    
    if not quiz_logic_instance or not isinstance(quiz_logic_instance, QuizLogic) or not quiz_logic_instance.active:
        logger.warning(f"User {user_id}: No active QuizLogic instance for handle_quiz_answer_wrapper or instance inactive. Callback: {query.data}. Attempting to show main menu.")
        await query.answer("حدث خطأ أثناء معالجة إجابتك. يتم إعادتك للقائمة الرئيسية.", show_alert=True)
        await _cleanup_quiz_session_data(user_id, query.message.chat_id, context, "no_quiz_logic_at_answer_wrapper")
        # Ensure main_menu_callback is awaited and its result is handled if it returns a state for a *different* conversation
        # However, here we are ending quiz_conversation, so main_menu_callback should just display the menu.
        await main_menu_callback(update, context) 
        return ConversationHandler.END

    # توجيه الاستجابة إلى الدالة المناسبة حسب نوع الزر المضغوط
    if query.data.startswith("skip_"):
        return await quiz_logic_instance.handle_skip_question(update, context, query.data)
    elif query.data.startswith("end_"):
        return await quiz_logic_instance.handle_end_quiz(update, context, query.data)
    else:
        return await quiz_logic_instance.handle_answer(update, context, query.data)

# MANUS_MODIFICATION: Handler for 'View Stats' from quiz results screen
async def go_to_stats_menu_from_results(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer() 
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    logger.info(f"User {user_id} (chat {chat_id}) chose 'View Stats' from quiz results screen. Ending quiz_conversation to allow stats_conv to start.")
    
    await _cleanup_quiz_session_data(user_id, chat_id, context, "stats_from_results_ending_quiz_conv")
    
    # By returning ConversationHandler.END, the dispatcher should pick up the 'menu_stats' 
    # callback for the globally registered stats_conv_handler.
    # The stats_menu function (entry to stats_conv_handler) will then be called by the dispatcher.
    return ConversationHandler.END

quiz_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(quiz_menu_entry, pattern="^start_quiz$")],
    states={
        SELECT_QUIZ_TYPE: [
            CallbackQueryHandler(select_quiz_type_handler, pattern="^quiz_type_(all|unit)$"),
            CallbackQueryHandler(go_to_main_menu_from_quiz, pattern="^quiz_action_main_menu$"),
            CallbackQueryHandler(quiz_menu_entry, pattern="^quiz_action_back_to_type_selection$") # Generic back to type selection
        ],
        SELECT_COURSE_FOR_UNIT_QUIZ: [
            CallbackQueryHandler(select_course_for_unit_quiz_handler, pattern="^quiz_course_select_"),
            CallbackQueryHandler(select_course_for_unit_quiz_handler, pattern="^quiz_course_page_"),
            CallbackQueryHandler(quiz_menu_entry, pattern="^quiz_action_back_to_type_selection$")
        ],
        SELECT_UNIT_FOR_COURSE: [
            CallbackQueryHandler(select_unit_for_course_handler, pattern="^quiz_unit_select_"),
            CallbackQueryHandler(select_unit_for_course_handler, pattern="^quiz_unit_page_"),
            CallbackQueryHandler(select_course_for_unit_quiz_handler, pattern="^quiz_action_back_to_course_selection_")
        ],
        ENTER_QUESTION_COUNT: [
            CallbackQueryHandler(enter_question_count_handler, pattern="^num_questions_"),
            CallbackQueryHandler(select_unit_for_course_handler, pattern="^quiz_action_back_to_unit_selection_"), # Back to unit selection (unit quiz)
            CallbackQueryHandler(quiz_menu_entry, pattern="^quiz_action_back_to_type_selection$") # Back to type selection (all quiz)
        ],
        TAKING_QUIZ: [ 
            CallbackQueryHandler(handle_quiz_answer_wrapper, pattern="^answer_"),
            CallbackQueryHandler(handle_quiz_answer_wrapper, pattern="^skip_"),
            CallbackQueryHandler(handle_quiz_answer_wrapper, pattern="^end_")
        ],
        SHOWING_RESULTS: [
            CallbackQueryHandler(quiz_menu_entry, pattern="^quiz_action_restart_quiz_cb$"), 
            CallbackQueryHandler(go_to_stats_menu_from_results, pattern="^menu_stats$"), 
            CallbackQueryHandler(go_to_main_menu_from_quiz, pattern="^quiz_action_main_menu$")
        ]
    },
    fallbacks=[
        CommandHandler("start", start_command_fallback_for_quiz),
        CallbackQueryHandler(go_to_main_menu_from_quiz, pattern="^quiz_action_main_menu$"),
        CallbackQueryHandler(quiz_menu_entry, pattern="^quiz_action_restart_quiz_cb$"), 
    ],
    persistent=False,
    name="quiz_conversation",
    # Removed map_to_parent as it might conflict with explicit END returns for transitioning
)

logger.info("Quiz conversation handler (quiz.py) loaded.")

