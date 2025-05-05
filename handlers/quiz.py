# -*- coding: utf-8 -*-
"""Conversation handler for the quiz selection and execution flow (Corrected v4 - Syntax fix)."""

import logging
import math
import random # Added for random sampling
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
    from utils.api_client import fetch_from_api, transform_api_question # Ensure transform_api_question is imported
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
    async def fetch_from_api(*args, **kwargs): logger.error("Placeholder fetch_from_api called!"); return None # Make it async
    def transform_api_question(q): logger.error("Placeholder transform_api_question called!"); return q
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

async def get_all_questions_for_random() -> list | None:
    """Fetches questions from all courses and combines them."""
    logger.info("[RANDOM] Fetching all courses...")
    courses = await fetch_from_api("/api/v1/courses")
    if courses is None or not isinstance(courses, list):
        logger.error("[RANDOM] Failed to fetch courses for random quiz.")
        return None
    
    all_questions = []
    logger.info(f"[RANDOM] Found {len(courses)} courses. Fetching questions for each...")
    for course in courses:
        course_id = course.get("id")
        if course_id:
            endpoint = f"/api/v1/courses/{course_id}/questions"
            logger.debug(f"[RANDOM] Fetching questions from {endpoint}")
            questions = await fetch_from_api(endpoint)
            if questions is None or not isinstance(questions, list):
                logger.warning(f"[RANDOM] Failed to fetch questions for course {course_id} or invalid format.")
                continue # Skip this course if questions failed
            
            # Transform questions before adding
            for q_data in questions:
                 transformed_q = transform_api_question(q_data)
                 if transformed_q:
                     all_questions.append(transformed_q)
                 else:
                     logger.warning(f"[RANDOM] Skipping invalid question data from course {course_id}: {q_data}")
            logger.debug(f"[RANDOM] Fetched {len(questions)} questions for course {course_id}. Total now: {len(all_questions)}")
        else:
            logger.warning(f"[RANDOM] Course found without ID: {course}")
            
    logger.info(f"[RANDOM] Finished fetching. Total combined questions: {len(all_questions)}")
    return all_questions

async def get_question_count_from_api(endpoint: str) -> int:
    """Fetches questions from a specific endpoint and returns the count."""
    logger.debug(f"Fetching questions from {endpoint} to get count.")
    questions = await fetch_from_api(endpoint)
    if questions is None or not isinstance(questions, list):
        logger.error(f"Failed to fetch questions from {endpoint} or invalid format.")
        return 0
    # Count only valid transformed questions
    valid_count = 0
    for q_data in questions:
        if transform_api_question(q_data):
            valid_count += 1
    logger.debug(f"Found {len(questions)} raw questions, {valid_count} valid questions at {endpoint}.")
    return valid_count

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
    # Clear previous quiz/scope selections
    context.user_data.pop("quiz_selection", None)
    context.user_data.pop("current_page", None)
    context.user_data.pop("parent_id", None)
    context.user_data.pop("scope_items", None)
    context.user_data.pop("all_random_questions", None) # Clear random questions cache
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
        await safe_edit_message_text(query, text="⏳ جارٍ جلب وتجميع الأسئلة العشوائية من جميع المقررات...", reply_markup=None)
        
        # **CORRECTION**: Fetch all questions and store them
        all_questions = await get_all_questions_for_random()
        
        if all_questions is None: # Check if fetching failed
            error_message = "⚠️ حدث خطأ أثناء جلب الأسئلة العشوائية من الـ API. يرجى المحاولة مرة أخرى لاحقاً."
        elif not all_questions: # Check if list is empty
            error_message = "⚠️ لم يتم العثور على أي أسئلة متاحة للاختبار العشوائي في جميع المقررات."
        else:
            max_questions = len(all_questions)
            context.user_data["all_random_questions"] = all_questions # Store the fetched questions
            # **CORRECTION**: Use a special marker instead of a real endpoint
            context.user_data["quiz_selection"]["endpoint"] = "random_local"

        if error_message:
            await safe_edit_message_text(query, text=error_message, reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
            
        context.user_data["quiz_selection"]["max_questions"] = max_questions
        logger.info(f"Random quiz selected. Total combined questions: {max_questions}")
        text = f"🎲 اختبار عشوائي: أدخل عدد الأسئلة التي تريدها (1-{max_questions}):"
        await safe_edit_message_text(query, text=text, reply_markup=None)
        return ENTER_QUESTION_COUNT
        
    elif quiz_type == "course":
        courses = await fetch_from_api("/api/v1/courses")
        if courses is None or not isinstance(courses, list):
            logger.error("Failed to fetch courses from API or invalid format.")
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
        next_level_items = await fetch_from_api(api_endpoint)
        next_scope_type = "unit"
        prompt_text = "📖 اختر الوحدة الدراسية:"
        context.user_data["parent_id"] = scope_id
        context.user_data["quiz_selection"]["endpoint_base"] = f"/api/v1/courses/{scope_id}"
    elif scope_level == "unit":
        api_endpoint = f"/api/v1/units/{scope_id}/lessons"
        next_level_items = await fetch_from_api(api_endpoint)
        next_scope_type = "lesson"
        prompt_text = "📄 اختر الدرس:"
        context.user_data["parent_id"] = scope_id
        context.user_data["quiz_selection"]["endpoint_base"] = f"/api/v1/units/{scope_id}"
    elif scope_level == "lesson":
        await safe_edit_message_text(query, text="⏳ جارٍ حساب عدد الأسئلة للدرس...", reply_markup=None)
        questions_endpoint = f"/api/v1/lessons/{scope_id}/questions"
        context.user_data["quiz_selection"]["endpoint"] = questions_endpoint
        max_questions = await get_question_count_from_api(questions_endpoint)
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

    # Handle API errors or empty lists after fetching next level items
    if next_level_items is None:
        logger.error(f"Failed to fetch {next_scope_type}s from API ({api_endpoint}) or invalid format.")
        try:
            last_word = prompt_text.split(" ")[-1]
        except IndexError:
            last_word = "العناصر"
        error_message = f"⚠️ حدث خطأ أثناء جلب {last_word} من الـ API. قد تكون هناك مشكلة في الخادم ({api_endpoint}). يرجى المحاولة مرة أخرى لاحقاً."
        await safe_edit_message_text(query, text=error_message, reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    if next_level_items: # If sub-items exist, show them
        context.user_data["scope_items"] = next_level_items
        keyboard = create_scope_keyboard(next_scope_type, next_level_items, page=0, parent_id=scope_id)
        await safe_edit_message_text(query, text=prompt_text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
    else: # If no sub-items, proceed to question count for the current scope
        await safe_edit_message_text(query, text=f"⏳ جارٍ حساب عدد الأسئلة لـ {scope_level}...", reply_markup=None)
        # **FIXED LINE 291**: Use single quotes inside f-string
        questions_endpoint = f"{context.user_data['quiz_selection'].get('endpoint_base', '')}/questions"
        context.user_data["quiz_selection"]["endpoint"] = questions_endpoint
        max_questions = await get_question_count_from_api(questions_endpoint)
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
    
    try:
        _, _, scope_type, page_str, parent_id_str = data.split("_")
        page = int(page_str)
        parent_id = int(parent_id_str) if parent_id_str else None
    except (ValueError, IndexError) as e:
        logger.error(f"Invalid pagination callback data: {data}. Error: {e}")
        await safe_edit_message_text(query, text="حدث خطأ في التنقل بين الصفحات.")
        return SELECT_QUIZ_SCOPE

    scope_items = context.user_data.get("scope_items")
    if not scope_items:
        logger.error("Pagination requested but scope_items not found in user_data.")
        await safe_edit_message_text(query, text="فقدت بيانات التنقل. يرجى البدء من جديد.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    prompt_text = f"اختر {scope_type}:"
    if scope_type == "course": prompt_text = "📚 اختر المقرر الدراسي:"
    elif scope_type == "unit": prompt_text = "📖 اختر الوحدة الدراسية:"
    elif scope_type == "lesson": prompt_text = "📄 اختر الدرس:"
    
    context.user_data["current_page"] = page
    keyboard = create_scope_keyboard(scope_type, scope_items, page=page, parent_id=parent_id)
    await safe_edit_message_text(query, text=prompt_text, reply_markup=keyboard)
    return SELECT_QUIZ_SCOPE

async def handle_scope_back(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"User {user_id} requested back navigation: {data}")

    if data == "quiz_back_to_course":
        # Go back to course selection
        courses = await fetch_from_api("/api/v1/courses")
        if courses is None or not isinstance(courses, list):
            logger.error("Failed to fetch courses for back navigation.")
            await safe_edit_message_text(query, text="⚠️ حدث خطأ أثناء جلب قائمة المقررات.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        context.user_data["scope_items"] = courses
        context.user_data["current_page"] = 0
        context.user_data.pop("parent_id", None)
        text = "📚 اختر المقرر الدراسي:"
        keyboard = create_scope_keyboard("course", courses, page=0)
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
        
    elif data.startswith("quiz_back_to_unit_"):
        try:
            parent_course_id = int(data.split("_")[-1])
        except (ValueError, IndexError):
             logger.error(f"Invalid back_to_unit callback data: {data}")
             await safe_edit_message_text(query, text="حدث خطأ أثناء الرجوع.", reply_markup=create_quiz_type_keyboard())
             return SELECT_QUIZ_TYPE
             
        # Go back to unit selection for the parent course
        api_endpoint = f"/api/v1/courses/{parent_course_id}/units"
        units = await fetch_from_api(api_endpoint)
        if units is None or not isinstance(units, list):
            logger.error(f"Failed to fetch units for course {parent_course_id} for back navigation.")
            await safe_edit_message_text(query, text="⚠️ حدث خطأ أثناء جلب قائمة الوحدات.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        context.user_data["scope_items"] = units
        context.user_data["current_page"] = 0
        context.user_data["parent_id"] = parent_course_id
        text = "📖 اختر الوحدة الدراسية:"
        keyboard = create_scope_keyboard("unit", units, page=0, parent_id=parent_course_id)
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
        
    else: # Default back to quiz type selection
        logger.warning(f"Unhandled back navigation: {data}. Returning to quiz menu.")
        text = "🧠 اختر نوع الاختبار الذي تريده:"
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

async def enter_question_count(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    text = update.message.text
    logger.info(f"User {user_id} entered question count: {text}")
    quiz_selection = context.user_data.get("quiz_selection")
    if not quiz_selection:
        logger.error("enter_question_count called without quiz_selection.")
        await safe_send_message(context.bot, update.effective_chat.id, text="حدث خطأ. يرجى البدء من جديد.", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU

    max_questions = quiz_selection.get("max_questions", 10) # Default max if missing

    try:
        count = int(text)
        if 1 <= count <= max_questions:
            quiz_selection["count"] = count
            logger.info(f"User {user_id} selected {count} questions.")
            await safe_send_message(context.bot, update.effective_chat.id, text=f"👍 حسناً، سيتم تحضير اختبار بـ {count} أسئلة.")
            # Now start the quiz using the logic handler
            return await start_quiz_logic(update, context)
        else:
            await safe_send_message(context.bot, update.effective_chat.id, text=f"❌ العدد غير صالح. يرجى إدخال رقم بين 1 و {max_questions}.")
            return ENTER_QUESTION_COUNT
    except ValueError:
        await safe_send_message(context.bot, update.effective_chat.id, text="❌ إدخال غير صالح. يرجى إدخال رقم.")
        return ENTER_QUESTION_COUNT

async def cancel_quiz_setup(update: Update, context: CallbackContext) -> int:
    """Handles cancellation during the quiz setup phase."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} cancelled quiz setup.")
    await safe_send_message(context.bot, update.effective_chat.id, text="تم إلغاء إعداد الاختبار.")
    # Clean up potentially stored data
    context.user_data.pop("quiz_selection", None)
    context.user_data.pop("current_page", None)
    context.user_data.pop("parent_id", None)
    context.user_data.pop("scope_items", None)
    context.user_data.pop("all_random_questions", None)
    # Send main menu
    kb = create_main_menu_keyboard(user_id)
    await safe_send_message(context.bot, update.effective_chat.id, text="القائمة الرئيسية:", reply_markup=kb)
    return MAIN_MENU

# --- Conversation Handler Definition --- 

quiz_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(quiz_menu, pattern="^quiz_menu$")],
    states={
        SELECT_QUIZ_TYPE: [
            CallbackQueryHandler(select_quiz_type, pattern="^quiz_type_(random|course)$"),
            CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"),
        ],
        SELECT_QUIZ_SCOPE: [
            CallbackQueryHandler(select_quiz_scope, pattern="^quiz_scope_(course|unit|lesson)_\d+$"),
            CallbackQueryHandler(handle_scope_pagination, pattern="^quiz_page_(course|unit|lesson)_\d+_\d*$"),
            CallbackQueryHandler(handle_scope_back, pattern="^quiz_back_to_(course|unit_\d+)$|^quiz_menu$"), # Handle back buttons
            CallbackQueryHandler(quiz_menu, pattern="^quiz_menu$"), # Allow returning to quiz type selection
        ],
        ENTER_QUESTION_COUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, enter_question_count)
        ],
        TAKING_QUIZ: [
            CallbackQueryHandler(handle_quiz_answer, pattern="^quiz_.*_ans_\d+_\d+$"),
            CallbackQueryHandler(skip_question_callback, pattern="^quiz_.*_skip_\d+$"),
            CallbackQueryHandler(end_quiz, pattern="^quiz_end$"), # Optional: Add an explicit end button
        ],
        SHOWING_RESULTS: [
            CallbackQueryHandler(quiz_menu, pattern="^quiz_menu$"),
            CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"),
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_quiz_setup), # Allow cancellation during setup
        CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"), # Global fallback to main menu
        CallbackQueryHandler(quiz_menu, pattern="^quiz_menu$"), # Fallback to quiz menu
    ],
    name="quiz_conversation",
    persistent=True,
    allow_reentry=True
)

