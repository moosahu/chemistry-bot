# -*- coding: utf-8 -*-
"""Conversation handler for the quiz selection and execution flow (Corrected v10 - Fixed ConversationHandler Structure)."""

import logging
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    CommandHandler
)

# --- Corrected Imports --- 
from config import (
    logger,
    MAIN_MENU, QUIZ_MENU, SELECT_QUIZ_TYPE, SELECT_QUIZ_SCOPE, 
    ENTER_QUESTION_COUNT, TAKING_QUIZ, SHOWING_RESULTS, END
)
from utils.helpers import safe_send_message, safe_edit_message_text
from utils.api_client import fetch_from_api
from handlers.common import create_main_menu_keyboard, main_menu_callback
from handlers.quiz_logic import (
    start_quiz_logic, handle_answer as handle_quiz_answer, 
    skip_question_button_handler
)

ITEMS_PER_PAGE = 6

def create_quiz_type_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🎲 اختبار عشوائي", callback_data="quiz_type_random")],
        [InlineKeyboardButton("📚 حسب المقرر", callback_data="quiz_type_course")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_scope_keyboard(scope_type: str, items: list, page: int = 0, parent_id: int | None = None) -> InlineKeyboardMarkup:
    keyboard = []
    start_index = page * ITEMS_PER_PAGE
    end_index = start_index + ITEMS_PER_PAGE
    current_items = items[start_index:end_index]
    prefix = ""
    id_key = "id"
    name_key = "name"
    if scope_type == "course":
        prefix = "quiz_scope_course_"
    elif scope_type == "unit":
        prefix = "quiz_scope_unit_"
    elif scope_type == "lesson":
        prefix = "quiz_scope_lesson_"

    for item in current_items:
        item_id = item.get(id_key)
        item_name = item.get(name_key, f"Item {item_id}")
        if item_id is not None:
            keyboard.append([InlineKeyboardButton(item_name, callback_data=f"{prefix}{item_id}")])

    pagination_row = []
    total_pages = math.ceil(len(items) / ITEMS_PER_PAGE)
    parent_id_str = str(parent_id) if parent_id is not None else ""
    if page > 0:
        pagination_row.append(InlineKeyboardButton("◀️ السابق", callback_data=f"quiz_page_{scope_type}_{page - 1}_{parent_id_str}"))
    if end_index < len(items):
        pagination_row.append(InlineKeyboardButton("▶️ التالي", callback_data=f"quiz_page_{scope_type}_{page + 1}_{parent_id_str}"))
    if pagination_row:
        keyboard.append(pagination_row)

    back_callback = "quiz_menu"
    if scope_type == "unit" and parent_id is not None:
        back_callback = f"quiz_back_to_course"
    elif scope_type == "lesson" and parent_id is not None:
        back_callback = f"quiz_back_to_unit_{parent_id}"
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def get_question_count_from_api(endpoint: str) -> int:
    logger.debug(f"Fetching questions from {endpoint} to get count.")
    questions = fetch_from_api(endpoint)
    if questions is None or not isinstance(questions, list):
        logger.error(f"Failed to fetch questions from {endpoint} or invalid format.")
        return 0
    logger.debug(f"Found {len(questions)} questions at {endpoint}.")
    return len(questions)

async def quiz_menu_entry(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = update.effective_user.id
    if query:
        await query.answer()
        logger.info(f"User {user_id} entered quiz menu.")
        text = "🧠 اختر نوع الاختبار الذي تريده:"
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
    else:
        logger.warning("quiz_menu_entry called without callback query.")
        text = "🧠 اختر نوع الاختبار الذي تريده:"
        keyboard = create_quiz_type_keyboard()
        await safe_send_message(context.bot, update.effective_chat.id, text=text, reply_markup=keyboard)
        
    context.user_data.pop("quiz_selection", None)
    context.user_data.pop("current_page", None)
    context.user_data.pop("parent_id", None)
    context.user_data.pop("scope_items", None)
    return SELECT_QUIZ_TYPE

async def select_quiz_type(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"User {user_id} selected quiz type: {data}")
    quiz_type = data.split("_")[-1]
    context.user_data["quiz_selection"] = {"type": quiz_type}
    context.user_data["current_page"] = 0
    max_questions = 0
    error_message = ""

    if quiz_type == "random":
        await safe_edit_message_text(query, text="⏳ جارٍ حساب عدد الأسئلة العشوائية المتاحة...", reply_markup=None)
        
        random_questions_endpoint = "/api/v1/questions/random"
        all_questions = fetch_from_api(random_questions_endpoint)
        
        if all_questions is None or not isinstance(all_questions, list):
            logger.error(f"Failed to fetch random questions from {random_questions_endpoint} or invalid format.")
            error_message = "⚠️ حدث خطأ أثناء جلب الأسئلة العشوائية من الـ API."
            max_questions = 0
        else:
            max_questions = len(all_questions)
            context.user_data["all_random_questions"] = all_questions 
            logger.info(f"Fetched {max_questions} total random questions.")

        if max_questions == 0 and not error_message:
             error_message = "⚠️ لم يتم العثور على أسئلة متاحة للاختبار العشوائي."

        if error_message:
            await safe_edit_message_text(query, text=error_message, reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
            
        context.user_data["quiz_selection"]["max_questions"] = max_questions
        context.user_data["quiz_selection"]["endpoint"] = "random_local" 
        logger.info(f"Random quiz selected. Max questions: {max_questions}")
        text = f"🎲 اختبار عشوائي: أدخل عدد الأسئلة التي تريدها (1-{max_questions}):"
        await safe_edit_message_text(query, text=text, reply_markup=None)
        return ENTER_QUESTION_COUNT
        
    elif quiz_type == "course":
        courses = fetch_from_api("/api/v1/courses")
        if courses is None or not isinstance(courses, list):
            logger.error("Failed to fetch courses from API or invalid format.")
            await safe_edit_message_text(query, text="⚠️ حدث خطأ أثناء جلب قائمة المقررات من الـ API.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
            
        if not courses:
            await safe_edit_message_text(query, text="⚠️ لم يتم العثور على مقررات دراسية.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        
        context.user_data["scope_items"] = courses
        text = "📚 اختر المقرر الدراسي:"
        keyboard = create_scope_keyboard("course", courses, page=0)
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
        
    else:
        logger.warning(f"Unknown quiz type selected: {quiz_type}")
        await safe_edit_message_text(query, text="نوع اختبار غير معروف.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

async def select_quiz_scope(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"User {user_id} selected quiz scope: {data}")
    parts = data.split("_")
    scope_level = parts[2]
    scope_id = int(parts[3])
    context.user_data["quiz_selection"]["scope_id"] = scope_id
    context.user_data["current_page"] = 0
    next_level_items = None
    next_scope_type = ""
    prompt_text = ""
    api_endpoint_for_next = ""
    api_endpoint_for_questions = ""
    error_message = ""

    if scope_level == "course":
        api_endpoint_for_next = f"/api/v1/courses/{scope_id}/units"
        api_endpoint_for_questions = f"/api/v1/courses/{scope_id}/questions"
        next_level_items = fetch_from_api(api_endpoint_for_next)
        next_scope_type = "unit"
        prompt_text = "📖 اختر الوحدة الدراسية:"
        context.user_data["parent_id"] = scope_id
    elif scope_level == "unit":
        api_endpoint_for_next = f"/api/v1/units/{scope_id}/lessons"
        api_endpoint_for_questions = f"/api/v1/units/{scope_id}/questions"
        next_level_items = fetch_from_api(api_endpoint_for_next)
        next_scope_type = "lesson"
        prompt_text = "📄 اختر الدرس:"
        context.user_data["current_unit_id"] = scope_id 
    elif scope_level == "lesson":
        await safe_edit_message_text(query, text="⏳ جارٍ حساب عدد الأسئلة للدرس...", reply_markup=None)
        questions_endpoint = f"/api/v1/lessons/{scope_id}/questions"
        max_questions = get_question_count_from_api(questions_endpoint)
        if max_questions == 0:
             error_message = "⚠️ لم يتم العثور على أسئلة لهذا الدرس أو حدث خطأ."
        if error_message:
            await safe_edit_message_text(query, text=error_message, reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        context.user_data["quiz_selection"]["max_questions"] = max_questions
        context.user_data["quiz_selection"]["endpoint"] = questions_endpoint
        logger.info(f"Lesson {scope_id} selected. Max questions: {max_questions}")
        text = f"📄 درس محدد: أدخل عدد الأسئلة التي تريدها (1-{max_questions}):" # Corrected f-string
        await safe_edit_message_text(query, text=text, reply_markup=None)
        return ENTER_QUESTION_COUNT

    if next_level_items is None:
        logger.error(f"Failed to fetch {next_scope_type}s from API ({api_endpoint_for_next}) or invalid format.")
        try:
            last_word = prompt_text.split(" ")[-1]
        except IndexError:
            last_word = "العناصر"
        error_message = f"⚠️ حدث خطأ أثناء جلب {last_word} من الـ API."
        await safe_edit_message_text(query, text=error_message, reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    if next_level_items:
        context.user_data["scope_items"] = next_level_items
        parent_id_for_keyboard = context.user_data.get("current_unit_id") if next_scope_type == "lesson" else context.user_data.get("parent_id")
        keyboard = create_scope_keyboard(next_scope_type, next_level_items, page=0, parent_id=parent_id_for_keyboard)
        await safe_edit_message_text(query, text=prompt_text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
    else:
        await safe_edit_message_text(query, text=f"⏳ جارٍ حساب عدد الأسئلة لـ {scope_level}...", reply_markup=None)
        max_questions = get_question_count_from_api(api_endpoint_for_questions)
        if max_questions == 0:
             error_message = f"⚠️ لم يتم العثور على أسئلة لـ {scope_level} {scope_id} أو حدث خطأ."
        if error_message:
             await safe_edit_message_text(query, text=error_message, reply_markup=create_quiz_type_keyboard())
             return SELECT_QUIZ_TYPE
        context.user_data["quiz_selection"]["max_questions"] = max_questions
        context.user_data["quiz_selection"]["endpoint"] = api_endpoint_for_questions
        logger.info(f"{scope_level.capitalize()} {scope_id} selected (no sub-items). Max questions: {max_questions}")
        text = f"📌 {scope_level.capitalize()} محدد: أدخل عدد الأسئلة التي تريدها (1-{max_questions}):"
        await safe_edit_message_text(query, text=text, reply_markup=None)
        return ENTER_QUESTION_COUNT

async def handle_scope_pagination(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"User {user_id} requested pagination: {data}")
    parts = data.split("_")
    scope_type = parts[2]
    page = int(parts[3])
    parent_id = int(parts[4]) if len(parts) > 4 and parts[4] else None
    items = context.user_data.get("scope_items", [])
    if not items:
        logger.error("Pagination requested but scope_items not found in user_data.")
        await safe_edit_message_text(query, text="حدث خطأ في التنقل بين الصفحات.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE
    context.user_data["current_page"] = page
    keyboard = create_scope_keyboard(scope_type, items, page=page, parent_id=parent_id)
    prompt_text = f"اختر {scope_type}: (صفحة {page + 1})"
    if scope_type == "course": prompt_text = "📚 اختر المقرر الدراسي:"
    elif scope_type == "unit": prompt_text = "📖 اختر الوحدة الدراسية:"
    elif scope_type == "lesson": prompt_text = "📄 اختر الدرس:"
    await safe_edit_message_text(query, text=prompt_text, reply_markup=keyboard)
    return SELECT_QUIZ_SCOPE

async def handle_scope_back(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"User {user_id} requested back navigation: {data}")
    context.user_data["current_page"] = 0

    if data == "quiz_menu":
        text = "🧠 اختر نوع الاختبار الذي تريده:"
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_TYPE
        
    elif data == "quiz_back_to_course":
        courses = fetch_from_api("/api/v1/courses")
        if courses is None or not isinstance(courses, list):
            logger.error("Failed to fetch courses on back navigation.")
            await safe_edit_message_text(query, text="⚠️ حدث خطأ أثناء جلب المقررات الدراسية.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        context.user_data["scope_items"] = courses
        context.user_data.pop("parent_id", None)
        text = "📚 اختر المقرر الدراسي:"
        keyboard = create_scope_keyboard("course", courses, page=0)
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
        
    elif data.startswith("quiz_back_to_unit_"):
        course_id = context.user_data.get("parent_id")
        if course_id is None:
             logger.error("Course ID (parent_id) not found in user_data for back navigation to units.")
             await safe_edit_message_text(query, text="⚠️ حدث خطأ أثناء الرجوع (لم يتم العثور على المقرر الأصلي).")
             return await quiz_menu_entry(update, context)
             
        units_endpoint = f"/api/v1/courses/{course_id}/units"
        units = fetch_from_api(units_endpoint)
        if units is None or not isinstance(units, list):
            logger.error(f"Failed to fetch units from {units_endpoint} on back navigation.")
            await safe_edit_message_text(query, text="⚠️ حدث خطأ أثناء جلب الوحدات الدراسية.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
            
        context.user_data["scope_items"] = units
        context.user_data.pop("current_unit_id", None)
        text = "📖 اختر الوحدة الدراسية:"
        keyboard = create_scope_keyboard("unit", units, page=0, parent_id=course_id)
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
        
    else:
        logger.warning(f"Unknown back navigation data: {data}")
        return await quiz_menu_entry(update, context)

async def enter_question_count(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    try:
        count_text = update.message.text
        count = int(count_text)
        logger.info(f"User {user_id} entered question count: {count}")
        
        quiz_selection = context.user_data.get("quiz_selection")
        if not quiz_selection:
            logger.error("ENTER_QUESTION_COUNT state reached but quiz_selection missing.")
            await safe_send_message(context.bot, chat_id, text="حدث خطأ، يرجى البدء من جديد.")
            return await quiz_menu_entry(update, context)
            
        max_questions = quiz_selection.get("max_questions", 0)
        
        if not isinstance(max_questions, int) or max_questions <= 0:
             logger.error(f"Invalid max_questions ({max_questions}) in quiz_selection.")
             await safe_send_message(context.bot, chat_id, text="حدث خطأ في تحديد الحد الأقصى للأسئلة.")
             return await quiz_menu_entry(update, context)

        if 1 <= count <= max_questions:
            quiz_selection["count"] = count
            logger.info(f"User {user_id} confirmed {count} questions. Starting quiz logic.")
            await safe_send_message(context.bot, chat_id, text=f"👍 ممتاز! سيتم بدء اختبار بـ {count} سؤال.")
            return await start_quiz_logic(update, context)
        else:
            logger.warning(f"User {user_id} entered invalid count: {count} (max: {max_questions})")
            await safe_send_message(context.bot, chat_id, text=f"⚠️ العدد غير صالح. يرجى إدخال رقم بين 1 و {max_questions}.")
            return ENTER_QUESTION_COUNT
            
    except (ValueError, TypeError):
        logger.warning(f"User {user_id} entered non-numeric text: {update.message.text}")
        await safe_send_message(context.bot, chat_id, text="⚠️ يرجى إدخال رقم صحيح.")
        return ENTER_QUESTION_COUNT

async def cancel_quiz_selection(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    logger.info(f"User {user_id} cancelled quiz selection.")
    context.user_data.clear()
    
    text = "تم إلغاء اختيار الاختبار. العودة للقائمة الرئيسية."
    keyboard = create_main_menu_keyboard(user_id)
    
    if query:
        await query.answer()
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
    else:
        await safe_send_message(context.bot, chat_id, text=text, reply_markup=keyboard)
        
    return END

# --- Conversation Handler Definition (Corrected v10 - Fixed Brackets) --- 

quiz_conv_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(quiz_menu_entry, pattern=r"^quiz_menu$")
    ],
    states={
        SELECT_QUIZ_TYPE: [
            CallbackQueryHandler(select_quiz_type, pattern=r"^quiz_type_(random|course)$"),
            CallbackQueryHandler(main_menu_callback, pattern=r"^main_menu$") # Allow returning to main menu
        ],
        SELECT_QUIZ_SCOPE: [
            CallbackQueryHandler(select_quiz_scope, pattern=r"^quiz_scope_(course|unit|lesson)_\d+$"),
            CallbackQueryHandler(handle_scope_pagination, pattern=r"^quiz_page_(course|unit|lesson)_\d+_\d*$"),
            CallbackQueryHandler(handle_scope_back, pattern=r"^quiz_back_to_(course|unit_\d+)$|^quiz_menu$")
        ],
        ENTER_QUESTION_COUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, enter_question_count)
        ],
        TAKING_QUIZ: [
            CallbackQueryHandler(handle_quiz_answer, pattern=r"^quiz_answer_\d+$"),
            CallbackQueryHandler(skip_question_button_handler, pattern=r"^skip_question$")
        ]
        # SHOWING_RESULTS is handled by quiz_logic returning END or MAIN_MENU
    },
    fallbacks=[
        CallbackQueryHandler(cancel_quiz_selection, pattern=r"^cancel_quiz$"), # Added a specific cancel pattern
        CallbackQueryHandler(main_menu_callback, pattern=r"^main_menu$"), # Allow returning to main menu from any state
        CommandHandler("cancel", cancel_quiz_selection) # Allow cancelling via command
    ],
    map_to_parent={
        # States that ConversationHandler.END returns to
        END: MAIN_MENU,
        # States that return to the parent conversation
        MAIN_MENU: MAIN_MENU, 
        # If quiz_logic returns SHOWING_RESULTS, map it back to MAIN_MENU after showing results
        SHOWING_RESULTS: MAIN_MENU 
    },
    name="quiz_conversation",
    persistent=True,
    allow_reentry=True
)

