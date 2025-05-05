# -*- coding: utf-8 -*-
"""Conversation handler for the quiz selection and execution flow."""

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

try:
    from config import (
        logger,
        MAIN_MENU, QUIZ_MENU, SELECT_QUIZ_TYPE, SELECT_QUIZ_SCOPE, 
        ENTER_QUESTION_COUNT, TAKING_QUIZ, SHOWING_RESULTS, END
    )
    from utils.helpers import safe_send_message, safe_edit_message_text
    from utils.api_client import fetch_from_api
    from handlers.common import create_main_menu_keyboard, main_menu_callback
    from handlers.quiz_logic import (
        start_quiz_logic, handle_quiz_answer, skip_question_callback, 
        end_quiz
    )
except ImportError as e:
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error(f"Error importing modules in handlers.quiz: {e}. Using placeholders.")
    MAIN_MENU, QUIZ_MENU, SELECT_QUIZ_TYPE, SELECT_QUIZ_SCOPE, ENTER_QUESTION_COUNT, TAKING_QUIZ, SHOWING_RESULTS, END = 0, 1, 2, 3, 4, 5, 6, ConversationHandler.END
    async def safe_send_message(*args, **kwargs): logger.error("Placeholder safe_send_message called!")
    async def safe_edit_message_text(*args, **kwargs): logger.error("Placeholder safe_edit_message_text called!")
    def fetch_from_api(*args, **kwargs): logger.error("Placeholder fetch_from_api called!"); return None
    def create_main_menu_keyboard(*args, **kwargs): logger.error("Placeholder create_main_menu_keyboard called!"); return None
    async def main_menu_callback(*args, **kwargs): logger.error("Placeholder main_menu_callback called!"); return MAIN_MENU
    async def start_quiz_logic(*args, **kwargs): logger.error("Placeholder start_quiz_logic called!"); return SHOWING_RESULTS
    async def handle_quiz_answer(*args, **kwargs): logger.error("Placeholder handle_quiz_answer called!"); return TAKING_QUIZ
    async def skip_question_callback(*args, **kwargs): logger.error("Placeholder skip_question_callback called!"); return TAKING_QUIZ
    async def end_quiz(*args, **kwargs): logger.error("Placeholder end_quiz called!"); return MAIN_MENU

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

async def quiz_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = update.effective_user.id
    if query:
        await query.answer()
        logger.info(f"User {user_id} entered quiz menu.")
        text = "🧠 اختر نوع الاختبار الذي تريده:"
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
    else:
        logger.warning("quiz_menu called without callback query.")
        await safe_send_message(context.bot, update.effective_chat.id, text="يرجى استخدام القائمة الرئيسية.")
        return MAIN_MENU
    context.user_data.pop("quiz_selection", None)
    context.user_data.pop("current_page", None)
    context.user_data.pop("parent_id", None)
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
        await safe_edit_message_text(query, text="⏳ جارٍ حساب عدد الأسئلة العشوائية...", reply_markup=None)
        courses = fetch_from_api("/api/v1/courses")
        if courses is None or not isinstance(courses, list):
            logger.error("Failed to fetch courses for random count.")
            # Improved error message for course fetching failure
            error_message = "⚠️ حدث خطأ أثناء جلب قائمة المقررات من الـ API. يرجى المحاولة مرة أخرى لاحقاً أو التواصل مع المسؤول."
        else:
            total_count = 0
            for course in courses:
                course_id = course.get("id")
                if course_id:
                    count = get_question_count_from_api(f"/api/v1/courses/{course_id}/questions")
                    total_count += count
            max_questions = total_count

        if max_questions == 0 and not error_message:
             error_message = "⚠️ لم يتم العثور على أسئلة متاحة للاختبار العشوائي (قد تحتاج لإضافة أسئلة للمقررات في الـ API)."

        if error_message:
            await safe_edit_message_text(query, text=error_message, reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
            
        context.user_data["quiz_selection"]["max_questions"] = max_questions
        logger.info(f"Random quiz selected. Max questions calculated: {max_questions}")
        text = f"🎲 اختبار عشوائي: أدخل عدد الأسئلة التي تريدها (1-{max_questions}):"
        await safe_edit_message_text(query, text=text, reply_markup=None)
        return ENTER_QUESTION_COUNT
        
    elif quiz_type == "course":
        courses = fetch_from_api("/api/v1/courses")
        if courses is None or not isinstance(courses, list):
            logger.error("Failed to fetch courses from API or invalid format.")
            # Improved error message for course fetching failure
            await safe_edit_message_text(query, text="⚠️ حدث خطأ أثناء جلب قائمة المقررات من الـ API. يرجى المحاولة مرة أخرى لاحقاً أو التواصل مع المسؤول.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
            
        if not courses:
            await safe_edit_message_text(query, text="⚠️ لم يتم العثور على مقررات دراسية. لا يمكن المتابعة.", reply_markup=create_quiz_type_keyboard())
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
    api_endpoint = ""
    error_message = ""

    if scope_level == "course":
        api_endpoint = f"/api/v1/courses/{scope_id}/units"
        next_level_items = fetch_from_api(api_endpoint)
        next_scope_type = "unit"
        prompt_text = "📖 اختر الوحدة الدراسية:"
        context.user_data["parent_id"] = scope_id
    elif scope_level == "unit":
        api_endpoint = f"/api/v1/units/{scope_id}/lessons"
        next_level_items = fetch_from_api(api_endpoint)
        next_scope_type = "lesson"
        prompt_text = "📄 اختر الدرس:"
        context.user_data["parent_id"] = scope_id
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
        logger.info(f"Lesson {scope_id} selected. Max questions calculated: {max_questions}")
        text = f"📄 درس محدد: أدخل عدد الأسئلة التي تريدها (1-{max_questions}):"
        await safe_edit_message_text(query, text=text, reply_markup=None)
        return ENTER_QUESTION_COUNT

    if next_level_items is None or not isinstance(next_level_items, list):
        logger.error(f"Failed to fetch {next_scope_type}s from API ({api_endpoint}) or invalid format.")
        # Correctly handle potential IndexError if prompt_text is empty or has no spaces
        try:
            last_word = prompt_text.split(' ')[-1] # Use single quotes for split
        except IndexError:
            last_word = "العناصر"
        # More specific error for API failure
        error_message = f"⚠️ حدث خطأ أثناء جلب {last_word} من الـ API. قد تكون هناك مشكلة في الخادم ({api_endpoint}). يرجى المحاولة مرة أخرى لاحقاً."
        await safe_edit_message_text(query, text=error_message, reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    if next_level_items:
        context.user_data["scope_items"] = next_level_items
        keyboard = create_scope_keyboard(next_scope_type, next_level_items, page=0, parent_id=scope_id)
        await safe_edit_message_text(query, text=prompt_text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
    else:
        await safe_edit_message_text(query, text=f"⏳ جارٍ حساب عدد الأسئلة لـ {scope_level}...", reply_markup=None)
        questions_endpoint = f"/api/v1/{scope_level}s/{scope_id}/questions"
        max_questions = get_question_count_from_api(questions_endpoint)
        if max_questions == 0:
             error_message = f"⚠️ لم يتم العثور على أسئلة لـ {scope_level} {scope_id} أو حدث خطأ."
        if error_message:
             await safe_edit_message_text(query, text=error_message, reply_markup=create_quiz_type_keyboard())
             return SELECT_QUIZ_TYPE
        context.user_data["quiz_selection"]["max_questions"] = max_questions
        logger.info(f"{scope_level.capitalize()} {scope_id} selected (no sub-items). Max questions calculated: {max_questions}")
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
    context.user_data["current_page"] = 0 # Reset page on back

    if data == "quiz_menu":
        text = "🧠 اختر نوع الاختبار الذي تريده:"
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_TYPE
    elif data == "quiz_back_to_course":
        # Fetch courses again from API
        courses = fetch_from_api("/api/v1/courses")
        if courses is None or not isinstance(courses, list):
            logger.error("Failed to fetch courses on back navigation.")
            await safe_edit_message_text(query, text="⚠️ حدث خطأ أثناء جلب المقررات الدراسية. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        context.user_data["scope_items"] = courses
        text = "📚 اختر المقرر الدراسي:"
        keyboard = create_scope_keyboard("course", courses, page=0)
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
    elif data.startswith("quiz_back_to_unit_"):
        unit_id = int(data.split("_")[-1])
        # Need the course_id to fetch units again. This requires better state management.
        # For now, let's assume we can get the course_id from context or fetch it.
        # Simplified: Fetch all courses and find the parent course of the unit (inefficient)
        courses = fetch_from_api("/api/v1/courses")
        parent_course_id = None
        if courses:
            for course in courses:
                course_id = course.get("id")
                units = fetch_from_api(f"/api/v1/courses/{course_id}/units")
                if units and any(u.get("id") == unit_id for u in units):
                    parent_course_id = course_id
                    break
        
        if parent_course_id is None:
             logger.error(f"Could not determine parent course for unit {unit_id} on back navigation.")
             await safe_edit_message_text(query, text="حدث خطأ أثناء الرجوع.", reply_markup=create_quiz_type_keyboard())
             return SELECT_QUIZ_TYPE

        units = fetch_from_api(f"/api/v1/courses/{parent_course_id}/units")
        if units is None or not isinstance(units, list):
            logger.error(f"Failed to fetch units for course {parent_course_id} on back navigation.")
            await safe_edit_message_text(query, text="⚠️ حدث خطأ أثناء جلب الوحدات الدراسية. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        context.user_data["scope_items"] = units
        context.user_data["parent_id"] = parent_course_id # Set parent_id for unit keyboard
        text = "📖 اختر الوحدة الدراسية:"
        keyboard = create_scope_keyboard("unit", units, page=0, parent_id=parent_course_id)
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
    else:
        logger.warning(f"Unknown back navigation: {data}")
        await safe_edit_message_text(query, text="حدث خطأ غير متوقع.", reply_markup=create_main_menu_keyboard())
        return MAIN_MENU

async def enter_question_count(update: Update, context: CallbackContext) -> int:
    """Handles user input for the number of questions."""
    user_id = update.effective_user.id
    # Improved: Strip whitespace from input text
    text = update.message.text.strip()
    logger.info(f"User {user_id} entered question count: '{text}'") # Log raw input
    logger.debug(f"Received question count input: '{update.message.text}'") # Log original input for debugging

    quiz_selection = context.user_data.get("quiz_selection")
    if not quiz_selection:
        logger.error(f"User {user_id} reached ENTER_QUESTION_COUNT without quiz_selection.")
        await safe_send_message(context.bot, update.effective_chat.id, text="حدث خطأ، يرجى البدء من جديد.", reply_markup=create_main_menu_keyboard())
        return MAIN_MENU

    max_questions = quiz_selection.get("max_questions", 0)

    try:
        num_questions = int(text)
        if 1 <= num_questions <= max_questions:
            quiz_selection["num_questions"] = num_questions
            logger.info(f"User {user_id} selected {num_questions} questions. Starting quiz.")
            # Start the quiz logic
            return await start_quiz_logic(update, context)
        else:
            await safe_send_message(context.bot, update.effective_chat.id, text=f"❌ رقم غير صالح. يرجى إدخال رقم بين 1 و {max_questions}.")
            return ENTER_QUESTION_COUNT # Ask again
    except ValueError:
        await safe_send_message(context.bot, update.effective_chat.id, text="❌ إدخال غير صالح. يرجى إدخال رقم صحيح.")
        return ENTER_QUESTION_COUNT # Ask again

# --- Conversation Handler Setup --- 

quiz_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(quiz_menu, pattern="^menu_quiz$")],
    states={
        SELECT_QUIZ_TYPE: [
            CallbackQueryHandler(select_quiz_type, pattern="^quiz_type_"),
            CallbackQueryHandler(main_menu_callback, pattern="^main_menu$") # Allow returning to main menu
        ],
        SELECT_QUIZ_SCOPE: [
            CallbackQueryHandler(select_quiz_scope, pattern="^quiz_scope_"),
            CallbackQueryHandler(handle_scope_pagination, pattern="^quiz_page_"),
            CallbackQueryHandler(handle_scope_back, pattern="^quiz_back_to_|^quiz_menu$"), # Handle back navigation
        ],
        ENTER_QUESTION_COUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, enter_question_count)
        ],
        TAKING_QUIZ: [
            CallbackQueryHandler(handle_quiz_answer, pattern="^quiz_answer_"),
            CallbackQueryHandler(skip_question_callback, pattern="^quiz_skip$")
        ],
        SHOWING_RESULTS: [
             CallbackQueryHandler(main_menu_callback, pattern="^main_menu$") # Allow returning to main menu from results
        ]
    },
    fallbacks=[
        CommandHandler("start", main_menu_callback), # Go to main menu on /start
        CallbackQueryHandler(main_menu_callback, pattern="^main_menu$") # General fallback to main menu
    ],
    map_to_parent={
        # Return to main menu if conversation ends unexpectedly or finishes
        END: MAIN_MENU,
        MAIN_MENU: MAIN_MENU
    },
    name="quiz_conversation", # Added unique name for persistence
    persistent=True # Enabled persistence
)

