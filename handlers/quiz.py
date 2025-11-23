"""
Conversation handler for the quiz selection and execution flow.
(MODIFIED: Uses api_client.py for questions, QuizLogic imports DB_MANAGER directly)
"""

import logging
import random
import uuid # For quiz_instance_id
import asyncio # For async sleep in resume_saved_quiz
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
    DEFAULT_QUESTION_TIME_LIMIT,
    STATS_MENU # MANUS_MODIFIED_V6: Added STATS_MENU for returning state
)

# إضافة حالة جديدة لاختيار المقرر للاختبار العشوائي
SELECT_COURSE_FOR_RANDOM_QUIZ = 100
from utils.helpers import safe_send_message, safe_edit_message_text, get_quiz_type_string, remove_job_if_exists
from utils.api_client import fetch_from_api, transform_api_question 
# MANUS_MODIFIED_V6: Removed problematic import of stats_menu_callback
from handlers.common import main_menu_callback, start_command 
from .quiz_logic import QuizLogic 

ITEMS_PER_PAGE = 6

async def _cleanup_quiz_session_data(user_id: int, chat_id: int, context: CallbackContext, reason: str):
    logger.info(f"[QuizCleanup] Cleaning up quiz session data for user {user_id}, chat {chat_id}. Reason: {reason}")
    
    active_quiz_logic_instance = context.user_data.get(f"quiz_logic_instance_{user_id}")
    if isinstance(active_quiz_logic_instance, QuizLogic):
        logger.info(f"[QuizCleanup] QuizLogic instance found for user {user_id} (active: {active_quiz_logic_instance.active}). Ensuring its cleanup.")
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
        "available_courses_for_random_quiz", "current_course_page_for_random_quiz",
        "selected_course_id_for_random_quiz", "selected_course_name_for_random_quiz",
        "selected_quiz_scope_id",
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
    logger.info(f"User {user_id} (chat {chat_id}) chose to go to main menu from quiz conversation (general). Ending quiz_conv.")
    await _cleanup_quiz_session_data(user_id, chat_id, context, "main_menu_request_from_quiz_stages")
    await main_menu_callback(update, context) 
    return ConversationHandler.END

def create_quiz_type_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🎲 اختبار عشوائي شامل (كل المقررات)", callback_data=f"quiz_type_{QUIZ_TYPE_ALL}")],
        [InlineKeyboardButton("📖 اختبار عشوائي حسب المقرر", callback_data="quiz_type_random_course")],
        [InlineKeyboardButton("📚 حسب الوحدة الدراسية (اختر المقرر ثم الوحدة)", callback_data=f"quiz_type_{QUIZ_TYPE_UNIT}")],
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="quiz_action_main_menu")] 
    ]
    return InlineKeyboardMarkup(keyboard)

def create_course_selection_keyboard(courses: list, current_page: int = 0, for_random_quiz: bool = False) -> InlineKeyboardMarkup:
    keyboard = []
    start_index = current_page * ITEMS_PER_PAGE
    end_index = start_index + ITEMS_PER_PAGE
    for i in range(start_index, min(end_index, len(courses))):
        course = courses[i]
        if for_random_quiz:
            keyboard.append([InlineKeyboardButton(course.get("name", f"مقرر {course.get('id')}"), callback_data=f"quiz_random_course_select_{course.get('id')}")])  
        else:
            keyboard.append([InlineKeyboardButton(course.get("name", f"مقرر {course.get('id')}"), callback_data=f"quiz_course_select_{course.get('id')}")])
    pagination_buttons = []
    if current_page > 0:
        page_callback = f"quiz_random_course_page_{current_page - 1}" if for_random_quiz else f"quiz_course_page_{current_page - 1}"
        pagination_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=page_callback))
    if end_index < len(courses):
        page_callback = f"quiz_random_course_page_{current_page + 1}" if for_random_quiz else f"quiz_course_page_{current_page + 1}"
        pagination_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=page_callback))
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
        logger.info(f"[QuizMenuEntry] Entered via callback: {query.data} for user {user_id}")
    else:
        logger.info(f"[QuizMenuEntry] Entered (likely not via callback) for user {user_id}")

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

    if callback_data == "main_menu" or callback_data == "quiz_action_main_menu":
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
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"اختر عدد الأسئلة لاختبار '{quiz_type_display_name}': (المتاح: {max_q})", kbd)
        return ENTER_QUESTION_COUNT

    elif quiz_type_key == "random_course":
        # اختبار عشوائي حسب المقرر
        courses = fetch_from_api("api/v1/courses")
        if courses == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id, query.message.message_id, api_timeout_message, create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        if not courses or not isinstance(courses, list) or not courses:
            await safe_edit_message_text(context.bot, chat_id, query.message.message_id, error_text_no_data("مقررات دراسية"), create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        context.user_data["available_courses_for_random_quiz"] = courses
        context.user_data["current_course_page_for_random_quiz"] = 0
        kbd = create_course_selection_keyboard(courses, 0, for_random_quiz=True)
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "اختر المقرر للاختبار العشوائي:", kbd)
        return SELECT_COURSE_FOR_RANDOM_QUIZ
        
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

async def select_course_for_random_quiz_handler(update: Update, context: CallbackContext) -> int:
    """معالج اختيار المقرر للاختبار العشوائي"""
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    callback_data = query.data
    context.user_data[f"last_quiz_interaction_message_id_{chat_id}"] = query.message.message_id

    # العودة لاختيار نوع الاختبار
    if callback_data == "quiz_action_back_to_type_selection":
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "🧠 اختر نوع الاختبار:", keyboard)
        return SELECT_QUIZ_TYPE

    # التنقل بين صفحات المقررات
    if callback_data.startswith("quiz_random_course_page_"):
        page = int(callback_data.split("_")[-1])
        context.user_data["current_course_page_for_random_quiz"] = page
        courses = context.user_data["available_courses_for_random_quiz"]
        kbd = create_course_selection_keyboard(courses, page, for_random_quiz=True)
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "اختر المقرر للاختبار العشوائي:", kbd)
        return SELECT_COURSE_FOR_RANDOM_QUIZ

    # اختيار المقرر
    selected_course_id = callback_data.replace("quiz_random_course_select_", "", 1)
    context.user_data["selected_course_id_for_random_quiz"] = selected_course_id
    courses = context.user_data.get("available_courses_for_random_quiz", [])
    selected_course_name = next((c.get("name") for c in courses if str(c.get("id")) == str(selected_course_id)), "مقرر غير معروف")
    context.user_data["selected_course_name_for_random_quiz"] = selected_course_name

    # جلب جميع الأسئلة للمقرر
    api_response = fetch_from_api(f"api/v1/courses/{selected_course_id}/questions")
    api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
    
    if api_response == "TIMEOUT":
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, api_timeout_message, 
                                     create_course_selection_keyboard(courses, context.user_data.get("current_course_page_for_random_quiz", 0), for_random_quiz=True))
        return SELECT_COURSE_FOR_RANDOM_QUIZ
    
    if not api_response or not isinstance(api_response, list):
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, 
                                     f"لا توجد أسئلة متاحة للمقرر '{selected_course_name}'.", 
                                     create_course_selection_keyboard(courses, context.user_data.get("current_course_page_for_random_quiz", 0), for_random_quiz=True))
        return SELECT_COURSE_FOR_RANDOM_QUIZ

    # حفظ الأسئلة
    context.user_data["questions_for_quiz"] = api_response
    context.user_data["selected_quiz_scope_id"] = selected_course_id
    context.user_data["selected_quiz_type_key"] = "random_course"
    context.user_data["selected_quiz_type_display_name"] = f"اختبار عشوائي - {selected_course_name}"
    
    max_q = len(api_response)
    kbd = create_question_count_keyboard(max_q, "random_course", unit_id=selected_course_id, course_id_for_unit=selected_course_id)
    await safe_edit_message_text(context.bot, chat_id, query.message.message_id, 
                                 f"اختر عدد الأسئلة لاختبار '{selected_course_name}': (المتاح: {max_q})", kbd)
    return ENTER_QUESTION_COUNT

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

    selected_course_id = context.user_data.get("selected_course_id_for_unit_quiz")
    courses = context.user_data.get("available_courses_for_unit_quiz", [])
    current_course_page = context.user_data.get("current_course_page_for_unit_quiz", 0)
    selected_course_name = context.user_data.get("selected_course_name_for_unit_quiz", "المقرر المحدد")

    if callback_data.startswith("quiz_action_back_to_course_selection_"):
        kbd = create_course_selection_keyboard(courses, current_course_page)
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "اختر المقرر الدراسي:", kbd)
        return SELECT_COURSE_FOR_UNIT_QUIZ

    if callback_data.startswith("quiz_unit_page_"):
        page = int(callback_data.split("_")[-1])
        context.user_data["current_unit_page_for_course"] = page
        units = context.user_data["available_units_for_course"]
        kbd = create_unit_selection_keyboard(units, selected_course_id, page)
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"اختر الوحدة الدراسية للمقرر '{selected_course_name}':", kbd)
        return SELECT_UNIT_FOR_COURSE

    parts = callback_data.split("_")
    selected_unit_id = parts[-1]
    context.user_data["selected_unit_id"] = selected_unit_id
    units = context.user_data.get("available_units_for_course", [])
    selected_unit_name = next((u.get("name") for u in units if str(u.get("id")) == str(selected_unit_id)), "وحدة غير معروفة")
    context.user_data["selected_unit_name"] = selected_unit_name

    api_response = fetch_from_api(f"api/v1/units/{selected_unit_id}/questions")
    api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
    current_unit_page = context.user_data.get("current_unit_page_for_course", 0)

    if api_response == "TIMEOUT":
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, api_timeout_message, create_unit_selection_keyboard(units, selected_course_id, current_unit_page))
        return SELECT_UNIT_FOR_COURSE
    if not api_response or not isinstance(api_response, list) or not api_response:
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"لا توجد أسئلة متاحة للوحدة '{selected_unit_name}'.", create_unit_selection_keyboard(units, selected_course_id, current_unit_page))
        return SELECT_UNIT_FOR_COURSE

    context.user_data["questions_for_quiz"] = api_response
    context.user_data["selected_quiz_scope_id"] = selected_unit_id
    max_q = len(api_response)
    kbd = create_question_count_keyboard(max_q, QUIZ_TYPE_UNIT, selected_unit_id, selected_course_id)
    await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"اختر عدد الأسئلة لاختبار الوحدة '{selected_unit_name}' (المتاح: {max_q}):", kbd)
    return ENTER_QUESTION_COUNT

async def enter_question_count_handler(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    callback_data = query.data
    context.user_data[f"last_quiz_interaction_message_id_{chat_id}"] = query.message.message_id

    quiz_type = context.user_data.get("selected_quiz_type_key")
    unit_id = context.user_data.get("selected_unit_id")
    course_id_for_unit = context.user_data.get("selected_course_id_for_unit_quiz")

    if callback_data.startswith("quiz_action_back_to_unit_selection_"):
        units = context.user_data.get("available_units_for_course", [])
        current_unit_page = context.user_data.get("current_unit_page_for_course", 0)
        selected_course_name = context.user_data.get("selected_course_name_for_unit_quiz", "المقرر المحدد")
        kbd = create_unit_selection_keyboard(units, course_id_for_unit, current_unit_page)
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, f"اختر الوحدة الدراسية للمقرر '{selected_course_name}':", kbd)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data == "quiz_action_back_to_type_selection":
        return await quiz_menu_entry(update, context)
    elif callback_data.startswith("quiz_action_back_to_course_selection_"):
        courses = context.user_data.get("available_courses_for_unit_quiz", [])
        current_course_page = context.user_data.get("current_course_page_for_unit_quiz", 0)
        kbd = create_course_selection_keyboard(courses, current_course_page)
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "اختر المقرر الدراسي:", kbd)
        return SELECT_COURSE_FOR_UNIT_QUIZ

    raw_questions = context.user_data.get("questions_for_quiz", [])
    if not raw_questions:
        logger.error(f"User {user_id} in ENTER_QUESTION_COUNT but no questions_for_quiz in user_data. Returning to type selection.")
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "حدث خطأ في إعداد الاختبار، لا توجد أسئلة. يرجى المحاولة مجدداً.", create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    num_questions_str = callback_data.replace("num_questions_", "", 1)
    if num_questions_str == "all":
        num_questions = len(raw_questions)
    else:
        try:
            num_questions = int(num_questions_str)
            if not (0 < num_questions <= len(raw_questions)):
                logger.warning(f"User {user_id} selected invalid number of questions: {num_questions}. Max: {len(raw_questions)}. Defaulting to max.")
                num_questions = len(raw_questions)
        except ValueError:
            logger.error(f"User {user_id} selected invalid (non-int) number of questions: {num_questions_str}. Defaulting to max.")
            num_questions = len(raw_questions)
    
    context.user_data["question_count_for_quiz"] = num_questions
    selected_questions = random.sample(raw_questions, k=min(num_questions, len(raw_questions)))
    
    transformed_questions = []
    for q_data in selected_questions:
        transformed_q = transform_api_question(q_data) 
        if transformed_q:
            transformed_questions.append(transformed_q)
    
    if not transformed_questions:
        logger.error(f"User {user_id} - No questions available after transformation for quiz type {quiz_type}. Raw count: {len(raw_questions)}")
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "عذراً، لم نتمكن من إعداد الأسئلة. يرجى المحاولة مرة أخرى.", create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    quiz_instance_id = str(uuid.uuid4())
    quiz_name_parts = [context.user_data.get("selected_quiz_type_display_name", "اختبار")]
    if quiz_type == QUIZ_TYPE_UNIT:
        quiz_name_parts.append(context.user_data.get("selected_course_name_for_unit_quiz", ""))
        quiz_name_parts.append(context.user_data.get("selected_unit_name", ""))
    elif quiz_type == "random_course":
        # اسم المقرر موجود بالفعل في selected_quiz_type_display_name
        pass
    quiz_display_name = " - ".join(filter(None, quiz_name_parts))
    
    # تحديد إذا كان الاختبار قابل للحفظ والاستكمال
    # يكون قابل للحفظ فقط عندما يختار "الكل" في الاختبارات العشوائية
    is_resumable = False
    if quiz_type in [QUIZ_TYPE_ALL, "random_course"] and num_questions_str == "all":
        is_resumable = True

    quiz_logic_instance = QuizLogic(
        user_id=user_id, chat_id=chat_id,
        questions=transformed_questions, quiz_name=quiz_display_name,
        quiz_type_for_db_log=quiz_type,
        quiz_scope_id=context.user_data.get("selected_quiz_scope_id", "unknown"),
        total_questions_for_db_log=len(transformed_questions),
        time_limit_per_question=DEFAULT_QUESTION_TIME_LIMIT,
        quiz_instance_id_for_logging=quiz_instance_id,
        is_resumable=is_resumable
    )
    context.user_data[f"quiz_logic_instance_{user_id}"] = quiz_logic_instance
    
    return await quiz_logic_instance.start_quiz(context.bot, context, update) 

async def handle_quiz_answer_wrapper(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    quiz_logic_instance = context.user_data.get(f"quiz_logic_instance_{user_id}")

    if not isinstance(quiz_logic_instance, QuizLogic):
        logger.warning(f"User {user_id} sent a callback in TAKING_QUIZ/SHOWING_RESULTS, but no QuizLogic instance found. Cleaning up.")
        await query.answer("جلسة الاختبار غير موجودة أو انتهت. يتم إعادتك للقائمة.")
        await _cleanup_quiz_session_data(user_id, chat_id, context, "no_quiz_logic_instance_in_wrapper")
        await main_menu_callback(update, context)
        return ConversationHandler.END

    if quiz_logic_instance.active:
        # توجيه الاستجابة إلى الدالة المناسبة حسب نوع الزر المضغوط
        if query.data.startswith("skip_"):
            return await quiz_logic_instance.handle_skip_question(update, context, query.data)
        elif query.data.startswith("end_"):
            return await quiz_logic_instance.handle_end_quiz(update, context, query.data)
        elif query.data.startswith("save_exit_"):
            return await quiz_logic_instance.handle_save_and_exit(update, context, query.data)
        else:
            return await quiz_logic_instance.handle_answer(update, context, query.data)
    else: 
        logger.info(f"User {user_id} (chat {chat_id}) interacted with an inactive QuizLogic instance. Callback: {query.data}. Cleaning up and going to main menu.")
        await query.answer("هذا الاختبار قد انتهى بالفعل. يتم نقلك للقائمة الرئيسية.")
        await _cleanup_quiz_session_data(user_id, chat_id, context, "interaction_with_inactive_quiz_logic_wrapper")
        await main_menu_callback(update, context)
        return ConversationHandler.END

async def handle_restart_quiz_from_results_cb(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    logger.info(f"User {user_id} chose to restart quiz from results. Calling quiz_menu_entry.")
    # Cleanup is handled by quiz_menu_entry
    return await quiz_menu_entry(update, context) 

# MANUS_MODIFIED_V6: Corrected stats button to return STATS_MENU state
async def handle_show_stats_from_results_cb(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    logger.info(f"User {user_id} (chat {chat_id}) chose to show stats from results. Cleaning up quiz session and returning STATS_MENU state.")
    await _cleanup_quiz_session_data(user_id, chat_id, context, "show_stats_from_results")
    # The main ConversationHandler (in bot.py or application setup) should handle STATS_MENU state.
    return STATS_MENU

async def handle_main_menu_from_results_cb(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    logger.info(f"User {user_id} chose to go to main menu from results. Cleaning up.")
    await _cleanup_quiz_session_data(user_id, chat_id, context, "main_menu_from_results")
    await main_menu_callback(update, context)
    return ConversationHandler.END

quiz_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(quiz_menu_entry, pattern="^start_quiz$")],
    states={
        SELECT_QUIZ_TYPE: [
            CallbackQueryHandler(select_quiz_type_handler, pattern="^quiz_type_|^quiz_action_main_menu$|^quiz_action_back_to_type_selection$")
        ],
        SELECT_COURSE_FOR_RANDOM_QUIZ: [
            CallbackQueryHandler(select_course_for_random_quiz_handler, pattern="^quiz_random_course_select_|^quiz_random_course_page_|^quiz_action_back_to_type_selection$")
        ],
        SELECT_COURSE_FOR_UNIT_QUIZ: [
            CallbackQueryHandler(select_course_for_unit_quiz_handler, pattern="^quiz_course_select_|^quiz_course_page_|^quiz_action_back_to_type_selection$")
        ],
        SELECT_UNIT_FOR_COURSE: [
            CallbackQueryHandler(select_unit_for_course_handler, pattern="^quiz_unit_select_|^quiz_unit_page_|^quiz_action_back_to_course_selection_")
        ],
        ENTER_QUESTION_COUNT: [
            CallbackQueryHandler(enter_question_count_handler, pattern="^num_questions_|^quiz_action_back_to_unit_selection_|^quiz_action_back_to_type_selection$|^quiz_action_back_to_course_selection_")
        ],
        TAKING_QUIZ: [
            CallbackQueryHandler(handle_quiz_answer_wrapper) 
        ],
        SHOWING_RESULTS: [
            CallbackQueryHandler(handle_restart_quiz_from_results_cb, pattern="^quiz_action_restart_quiz_cb$"),
            CallbackQueryHandler(handle_show_stats_from_results_cb, pattern="^quiz_action_show_stats_cb$"),
            CallbackQueryHandler(handle_main_menu_from_results_cb, pattern="^quiz_action_main_menu$"),
            # Fallback for any other callback in SHOWING_RESULTS, likely an old answer button if message not edited properly
            CallbackQueryHandler(handle_quiz_answer_wrapper) 
        ],
    },
    fallbacks=[
        CommandHandler("start", start_command_fallback_for_quiz),
        # General main menu fallback if user clicks a generic main menu button during quiz setup stages
        CallbackQueryHandler(go_to_main_menu_from_quiz, pattern="^quiz_action_main_menu$"), 
    ],
    persistent=False, # Recommended to be False for in-memory ConversationHandlers
    name="quiz_conversation",
    allow_reentry=True # Important for restarting quiz from results
)

# واجهة استكمال الاختبارات المحفوظة

async def show_saved_quizzes_menu(update: Update, context: CallbackContext) -> int:
    """عرض قائمة الاختبارات المحفوظة"""
    query = update.callback_query if update.callback_query else None
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    saved_quizzes = context.user_data.get("saved_quizzes", {})
    
    if not saved_quizzes:
        text = "📭 لا توجد اختبارات محفوظة حالياً.\n\nيمكنك حفظ اختبار عند اختيار 'جميع الأسئلة' في الاختبارات العشوائية."
        keyboard = [[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if query:
            await safe_edit_message_text(context.bot, chat_id, query.message.message_id, text, reply_markup)
        else:
            await safe_send_message(context.bot, chat_id, text, reply_markup)
        return MAIN_MENU
    
    # إنشاء قائمة بالاختبارات المحفوظة
    keyboard = []
    for quiz_id, quiz_data in saved_quizzes.items():
        quiz_name = quiz_data.get("quiz_name", "اختبار غير مسمى")
        current_q = quiz_data.get("current_question_index", 0)
        total_q = quiz_data.get("total_questions", 0)
        progress = f"({current_q}/{total_q})"
        
        button_text = f"📝 {quiz_name} {progress}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"resume_quiz_{quiz_id}")])
    
    keyboard.append([InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "📚 الاختبارات المحفوظة:\n\nاختر اختباراً لاستكماله:"
    
    if query:
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, text, reply_markup)
    else:
        await safe_send_message(context.bot, chat_id, text, reply_markup)
    
    return MAIN_MENU


async def resume_saved_quiz(update: Update, context: CallbackContext) -> int:
    """استكمال اختبار محفوظ"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    
    # استخراج معرف الاختبار من callback_data
    quiz_id = query.data.replace("resume_quiz_", "")
    
    saved_quizzes = context.user_data.get("saved_quizzes", {})
    
    if quiz_id not in saved_quizzes:
        await safe_edit_message_text(context.bot, chat_id, query.message.message_id, 
                                     "❌ الاختبار المحفوظ غير موجود أو تم حذفه.",
                                     InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="show_saved_quizzes")]]))
        return MAIN_MENU
    
    saved_quiz_data = saved_quizzes[quiz_id]
    
    # إعادة بناء QuizLogic من البيانات المحفوظة
    from datetime import datetime, timezone
    
    quiz_logic_instance = QuizLogic(
        user_id=user_id,
        chat_id=chat_id,
        questions=saved_quiz_data["questions_data"],
        quiz_name=saved_quiz_data["quiz_name"],
        quiz_type_for_db_log=saved_quiz_data["quiz_type"],
        quiz_scope_id=saved_quiz_data["quiz_scope_id"],
        total_questions_for_db_log=saved_quiz_data["total_questions"],
        time_limit_per_question=DEFAULT_QUESTION_TIME_LIMIT,
        quiz_instance_id_for_logging=quiz_id,
        is_resumable=True
    )
    
    # استعادة الحالة
    quiz_logic_instance.current_question_index = saved_quiz_data["current_question_index"]
    quiz_logic_instance.score = saved_quiz_data["score"]
    quiz_logic_instance.answers = saved_quiz_data["answers"]
    quiz_logic_instance.active = True
    quiz_logic_instance.db_quiz_session_id = saved_quiz_data.get("db_quiz_session_id")
    
    if saved_quiz_data.get("quiz_start_time"):
        quiz_logic_instance.quiz_actual_start_time_dt = datetime.fromisoformat(saved_quiz_data["quiz_start_time"])
    
    # حفظ instance في context
    context.user_data[f"quiz_logic_instance_{user_id}"] = quiz_logic_instance
    
    # حذف الاختبار من القائمة المحفوظة (سيتم حفظه مرة أخرى إذا اختار الحفظ)
    del saved_quizzes[quiz_id]
    
    # إرسال رسالة ترحيب
    await safe_edit_message_text(context.bot, chat_id, query.message.message_id,
                                 f"✅ تم استعادة الاختبار!\n\n📝 {saved_quiz_data['quiz_name']}\n📊 التقدم: {saved_quiz_data['current_question_index']}/{saved_quiz_data['total_questions']}\n\nسيتم عرض السؤال التالي...")
    
    await asyncio.sleep(1)
    
    # بدء الاختبار من السؤال الحالي
    await quiz_logic_instance.send_question(context.bot, context)
    
    # إرجاع حالة TAKING_QUIZ لتفعيل معالجات الإجابات
    return TAKING_QUIZ
