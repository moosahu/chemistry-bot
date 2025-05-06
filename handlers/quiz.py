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

from config import (
    logger,
    MAIN_MENU, QUIZ_MENU, SELECT_QUIZ_TYPE, SELECT_QUIZ_SCOPE, 
    ENTER_QUESTION_COUNT, TAKING_QUIZ, SHOWING_RESULTS, END
)
from utils.helpers import safe_send_message, safe_edit_message_text # Ensure get_quiz_type_string is here if used
from utils.api_client import fetch_from_api
from handlers.common import create_main_menu_keyboard, main_menu_callback
# quiz_logic.py now uses a class QuizLogic, so we import that
from .quiz_logic import QuizLogic # Corrected to import the class

ITEMS_PER_PAGE = 6

# --- Quiz State Definitions (used as keys in ConversationHandler) ---
# These are already defined in config.py, so no need to redefine here
# SELECT_QUIZ_TYPE, SELECT_QUIZ_SCOPE, ENTER_QUESTION_COUNT, TAKING_QUIZ, SHOWING_RESULTS

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
    id_key = "id" # Default for courses
    name_key = "name"

    if scope_type == "course":
        prefix = "quiz_scope_course_"
    elif scope_type == "unit":
        prefix = "quiz_scope_unit_"
        id_key = "unit_id" # API uses unit_id for units
        name_key = "name"
    elif scope_type == "lesson":
        prefix = "quiz_scope_lesson_"
        id_key = "lesson_id" # API uses lesson_id for lessons
        name_key = "name"

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

    back_callback = "quiz_menu" # Default back to quiz type selection
    if scope_type == "unit":
        back_callback = f"quiz_back_to_course" # No parent_id needed as it's one level up
    elif scope_type == "lesson":
        # For lessons, parent_id should be the unit_id to go back to units of the current course
        back_callback = f"quiz_back_to_unit_{parent_id if parent_id else ''}" 
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)

def get_question_count_from_api(endpoint: str, params: dict | None = None) -> int:
    logger.debug(f"Fetching questions from {endpoint} with params {params} to get count.")
    # The API for questions usually returns a list of questions directly
    questions = fetch_from_api(endpoint, params=params)
    if questions is None or not isinstance(questions, list):
        logger.error(f"Failed to fetch questions from {endpoint} or invalid format. Response: {questions}")
        return 0
    logger.debug(f"Found {len(questions)} questions at {endpoint}.")
    return len(questions)

async def quiz_menu_entry(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = update.effective_user.id
    if query:
        await query.answer()
        logger.info(f"User {user_id} entered quiz menu via callback.")
        text = "🧠 اختر نوع الاختبار الذي تريده:"
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=text, reply_markup=keyboard)
    else:
        # Entry via command /quiz
        logger.info(f"User {user_id} entered quiz menu via command.")
        text = "🧠 اختر نوع الاختبار الذي تريده:"
        keyboard = create_quiz_type_keyboard()
        await safe_send_message(context.bot, update.effective_chat.id, text=text, reply_markup=keyboard)
        
    context.user_data.pop("quiz_selection", None)
    context.user_data.pop("current_page", None)
    context.user_data.pop("parent_id", None) # For course_id when selecting units
    context.user_data.pop("current_unit_id", None) # For unit_id when selecting lessons
    context.user_data.pop("scope_items", None)
    return SELECT_QUIZ_TYPE

async def select_quiz_type_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"User {user_id} selected quiz type: {data}")
    quiz_type = data.split("_")[-1]
    context.user_data["quiz_selection"] = {"type": quiz_type, "type_display_name": query.message.reply_markup.inline_keyboard[0][0].text if quiz_type=="random" else query.message.reply_markup.inline_keyboard[1][0].text}
    context.user_data["current_page"] = 0
    max_questions = 0
    error_message = ""

    if quiz_type == "random":
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="⏳ جارٍ جلب الأسئلة العشوائية...", reply_markup=None)
        random_questions_endpoint = "/api/v1/questions/random?limit=200" # Fetch a good number for sampling
        all_questions = fetch_from_api(random_questions_endpoint)
        
        if all_questions is None or not isinstance(all_questions, list):
            logger.error(f"Failed to fetch random questions from {random_questions_endpoint} or invalid format.")
            error_message = "⚠️ حدث خطأ أثناء جلب الأسئلة العشوائية."
            max_questions = 0
        else:
            max_questions = len(all_questions)
            context.user_data["quiz_selection"]["fetched_questions"] = all_questions
            logger.info(f"Fetched {max_questions} total random questions.")

        if max_questions == 0 and not error_message:
             error_message = "⚠️ لم يتم العثور على أسئلة متاحة للاختبار العشوائي."

        if error_message:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=error_message, reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
            
        context.user_data["quiz_selection"]["max_questions"] = max_questions
        context.user_data["quiz_selection"]["endpoint"] = "random_api" 
        logger.info(f"Random quiz selected. Max available questions: {max_questions}")
        text = f"🎲 اختبار عشوائي: أدخل عدد الأسئلة التي تريدها (1-{max_questions}):"
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=text, reply_markup=None)
        return ENTER_QUESTION_COUNT
        
    elif quiz_type == "course":
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="⏳ جارٍ جلب المقررات الدراسية...", reply_markup=None)
        courses = fetch_from_api("/api/v1/courses")
        if courses is None or not isinstance(courses, list):
            logger.error("Failed to fetch courses from API or invalid format.")
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="⚠️ حدث خطأ أثناء جلب قائمة المقررات.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
            
        if not courses:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="⚠️ لم يتم العثور على مقررات دراسية.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        
        context.user_data["scope_items"] = courses
        text = "📚 اختر المقرر الدراسي:"
        keyboard = create_scope_keyboard("course", courses, page=0)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
        
    else:
        logger.warning(f"Unknown quiz type selected: {quiz_type}")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="نوع اختبار غير معروف.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

async def select_quiz_scope_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"User {user_id} selected quiz scope: {data}")
    parts = data.split("_") # e.g., quiz_scope_course_1 or quiz_scope_unit_5
    scope_level = parts[2]
    scope_id = int(parts[3])
    
    # Store the display name of the selected scope
    selected_item_name = ""
    for row in query.message.reply_markup.inline_keyboard:
        for button in row:
            if button.callback_data == data:
                selected_item_name = button.text
                break
        if selected_item_name: break
    
    context.user_data["quiz_selection"]["scope_id"] = scope_id
    context.user_data["quiz_selection"][f"{scope_level}_scope_display_name"] = selected_item_name
    context.user_data["current_page"] = 0 # Reset page for next level
    
    next_level_items = None
    next_scope_type = ""
    prompt_text = ""
    api_endpoint_for_next_level = ""
    api_endpoint_for_questions_at_this_level = ""
    error_message = ""

    if scope_level == "course":
        context.user_data["parent_id"] = scope_id # Save course_id for back navigation from units
        api_endpoint_for_next_level = f"/api/v1/courses/{scope_id}/units"
        api_endpoint_for_questions_at_this_level = f"/api/v1/courses/{scope_id}/questions"
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"⏳ جارٍ جلب وحدات المقرر: {selected_item_name}...", reply_markup=None)
        next_level_items = fetch_from_api(api_endpoint_for_next_level)
        next_scope_type = "unit"
        prompt_text = f"📖 اختر الوحدة الدراسية للمقرر \"{selected_item_name}\":"
    elif scope_level == "unit":
        context.user_data["current_unit_id"] = scope_id # Save unit_id for back navigation from lessons
        api_endpoint_for_next_level = f"/api/v1/units/{scope_id}/lessons"
        api_endpoint_for_questions_at_this_level = f"/api/v1/units/{scope_id}/questions"
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"⏳ جارٍ جلب دروس الوحدة: {selected_item_name}...", reply_markup=None)
        next_level_items = fetch_from_api(api_endpoint_for_next_level)
        next_scope_type = "lesson"
        prompt_text = f"📄 اختر الدرس للوحدة \"{selected_item_name}\":"
    elif scope_level == "lesson":
        # This is the final level for selection, proceed to question count
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"⏳ جارٍ حساب عدد أسئلة الدرس: {selected_item_name}...", reply_markup=None)
        questions_endpoint = f"/api/v1/lessons/{scope_id}/questions"
        max_questions = get_question_count_from_api(questions_endpoint)
        if max_questions == 0:
             error_message = f"⚠️ لم يتم العثور على أسئلة لهذا الدرس ({selected_item_name}) أو حدث خطأ."
        if error_message:
            # Go back to selecting lessons of the parent unit
            parent_unit_id = context.user_data.get("current_unit_id")
            # It's complex to rebuild the previous state perfectly here, simpler to go to quiz menu or course selection
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=error_message, reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE # Or a more specific back state if possible
        context.user_data["quiz_selection"]["max_questions"] = max_questions
        context.user_data["quiz_selection"]["endpoint"] = questions_endpoint
        context.user_data["quiz_selection"]["scope_display_name"] = selected_item_name
        logger.info(f"Lesson {scope_id} ({selected_item_name}) selected. Max questions: {max_questions}")
        text = f"📄 درس \"{selected_item_name}\": أدخل عدد الأسئلة التي تريدها (1-{max_questions}):"
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=text, reply_markup=None)
        return ENTER_QUESTION_COUNT

    # If there are items in the next level (e.g., units for a course, lessons for a unit)
    if next_level_items is not None and next_level_items: # Check if list is not empty
        context.user_data["scope_items"] = next_level_items
        # parent_id for unit keyboard is course_id, for lesson keyboard is unit_id
        parent_id_for_keyboard = scope_id 
        keyboard = create_scope_keyboard(next_scope_type, next_level_items, page=0, parent_id=parent_id_for_keyboard)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=prompt_text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
    # If no items in the next level (e.g., a course has no units, or a unit has no lessons)
    # OR if fetching next level items failed (next_level_items is None or empty list after fetch attempt)
    else:
        if next_level_items is None: # API fetch failed
            error_message = f"⚠️ حدث خطأ أثناء جلب {next_scope_type} لـ {scope_level} \"{selected_item_name}\"."
        else: # API returned empty list
            error_message = f"⚠️ لم يتم العثور على {next_scope_type} لـ {scope_level} \"{selected_item_name}\"."
        
        logger.warning(f"{error_message} Trying to get questions directly for {scope_level} {scope_id}.")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"{error_message} جاري محاولة تحميل أسئلة {scope_level} \"{selected_item_name}\" مباشرة...", reply_markup=None)
        
        max_questions = get_question_count_from_api(api_endpoint_for_questions_at_this_level)
        if max_questions == 0:
            final_error_msg = f"⚠️ لم يتم العثور على أسئلة لـ {scope_level} \"{selected_item_name}\" حتى بشكل مباشر."
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=final_error_msg, reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
            
        context.user_data["quiz_selection"]["max_questions"] = max_questions
        context.user_data["quiz_selection"]["endpoint"] = api_endpoint_for_questions_at_this_level
        context.user_data["quiz_selection"]["scope_display_name"] = selected_item_name
        logger.info(f"{scope_level.capitalize()} {scope_id} ({selected_item_name}) selected (no sub-items or sub-items failed). Max questions: {max_questions}")
        text = f"📌 {scope_level.capitalize()} \"{selected_item_name}\": أدخل عدد الأسئلة التي تريدها (1-{max_questions}):"
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=text, reply_markup=None)
        return ENTER_QUESTION_COUNT

async def handle_scope_pagination_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data # e.g., quiz_page_unit_1_5 (page 1 of units for course_id 5)
    logger.info(f"User {user_id} requested pagination: {data}")
    parts = data.split("_")
    scope_type = parts[2]
    page = int(parts[3])
    # Parent ID is crucial for knowing which course's units or which unit's lessons to paginate
    parent_id = int(parts[4]) if len(parts) > 4 and parts[4] else None 

    items = context.user_data.get("scope_items", [])
    if not items:
        logger.error("Pagination requested but scope_items not found in user_data.")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ في التنقل بين الصفحات.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE
        
    context.user_data["current_page"] = page
    keyboard = create_scope_keyboard(scope_type, items, page=page, parent_id=parent_id)
    
    prompt_text = f"اختر (صفحة {page + 1}):"
    if scope_type == "course": 
        prompt_text = "📚 اختر المقرر الدراسي:"
    elif scope_type == "unit": 
        course_name = context.user_data.get("quiz_selection", {}).get("course_scope_display_name", "المقرر المحدد")
        prompt_text = f"📖 اختر الوحدة الدراسية للمقرر \"{course_name}\":"
    elif scope_type == "lesson": 
        unit_name = context.user_data.get("quiz_selection", {}).get("unit_scope_display_name", "الوحدة المحددة")
        prompt_text = f"📄 اختر الدرس للوحدة \"{unit_name}\":"
        
    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=prompt_text, reply_markup=keyboard)
    return SELECT_QUIZ_SCOPE

async def handle_scope_back_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"User {user_id} requested back navigation: {data}")
    context.user_data["current_page"] = 0 # Reset page on back

    if data == "quiz_menu": # Back from course selection to quiz type
        return await quiz_menu_entry(update, context)
        
    elif data == "quiz_back_to_course": # Back from unit selection to course selection
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="⏳ جارٍ جلب المقررات الدراسية...", reply_markup=None)
        courses = fetch_from_api("/api/v1/courses")
        if courses is None or not isinstance(courses, list):
            logger.error("Failed to fetch courses on back navigation.")
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="⚠️ حدث خطأ أثناء جلب المقررات الدراسية.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        context.user_data["scope_items"] = courses
        context.user_data.pop("parent_id", None)
        context.user_data["quiz_selection"].pop("course_scope_display_name", None)
        context.user_data["quiz_selection"].pop("scope_id", None) # Clear previous scope ID
        text = "📚 اختر المقرر الدراسي:"
        keyboard = create_scope_keyboard("course", courses, page=0)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
        
    elif data.startswith("quiz_back_to_unit_"): # Back from lesson selection to unit selection
        # The parent_id for units is the course_id, which should be in user_data["parent_id"]
        course_id = context.user_data.get("parent_id")
        if course_id is None:
             logger.error("Course ID (parent_id) not found in user_data for back navigation to units.")
             await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="⚠️ حدث خطأ أثناء الرجوع (لم يتم العثور على المقرر الأصلي).")
             return await quiz_menu_entry(update, context) # Fallback to main quiz menu
        
        course_name = context.user_data.get("quiz_selection", {}).get("course_scope_display_name", "المقرر المحدد")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"⏳ جارٍ جلب وحدات المقرر: {course_name}...", reply_markup=None)
        units_endpoint = f"/api/v1/courses/{course_id}/units"
        units = fetch_from_api(units_endpoint)
        if units is None or not isinstance(units, list):
            logger.error(f"Failed to fetch units from {units_endpoint} on back navigation.")
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="⚠️ حدث خطأ أثناء جلب الوحدات الدراسية.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
            
        context.user_data["scope_items"] = units
        context.user_data.pop("current_unit_id", None)
        context.user_data["quiz_selection"].pop("unit_scope_display_name", None)
        context.user_data["quiz_selection"].pop("scope_id", None) # Clear previous scope ID
        text = f"📖 اختر الوحدة الدراسية للمقرر \"{course_name}\":"
        keyboard = create_scope_keyboard("unit", units, page=0, parent_id=course_id)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
    
    logger.warning(f"Unhandled back navigation data: {data}")
    return await quiz_menu_entry(update, context) # Fallback

async def enter_question_count(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text_input = update.message.text
    logger.info(f"User {user_id} entered question count: {text_input}")
    quiz_selection = context.user_data.get("quiz_selection")

    if not quiz_selection or "max_questions" not in quiz_selection:
        logger.error(f"User {user_id} in ENTER_QUESTION_COUNT but quiz_selection or max_questions is missing.")
        await safe_send_message(context.bot, chat_id, "حدث خطأ، يرجى البدء من جديد.", reply_markup=create_main_menu_keyboard(user_id))
        return MAIN_MENU

    max_q = quiz_selection["max_questions"]
    try:
        num_questions = int(text_input)
        if not (1 <= num_questions <= max_q):
            await safe_send_message(context.bot, chat_id, f"⚠️ يرجى إدخال رقم بين 1 و {max_q}.")
            # Re-prompt for question count
            scope_display = quiz_selection.get("scope_display_name", quiz_selection.get("type_display_name", "الاختبار المحدد"))
            prompt = f"📌 {scope_display}: أدخل عدد الأسئلة التي تريدها (1-{max_q}):"
            if quiz_selection["type"] == "random":
                 prompt = f"🎲 اختبار عشوائي: أدخل عدد الأسئلة التي تريدها (1-{max_q}):"
            await safe_send_message(context.bot, chat_id, prompt)
            return ENTER_QUESTION_COUNT
    except ValueError:
        await safe_send_message(context.bot, chat_id, "⚠️ إدخال غير صالح. يرجى إدخال رقم.")
        scope_display = quiz_selection.get("scope_display_name", quiz_selection.get("type_display_name", "الاختبار المحدد"))
        prompt = f"📌 {scope_display}: أدخل عدد الأسئلة التي تريدها (1-{max_q}):"
        if quiz_selection["type"] == "random":
                prompt = f"🎲 اختبار عشوائي: أدخل عدد الأسئلة التي تريدها (1-{max_q}):"
        await safe_send_message(context.bot, chat_id, prompt)
        return ENTER_QUESTION_COUNT

    quiz_selection["count"] = num_questions
    # Initialize QuizLogic instance here, as we now have all necessary info
    # This instance will be stored in user_data to be used by quiz answer/skip handlers
    context.user_data["quiz_logic_instance"] = QuizLogic(context) 
    
    # Call the start_quiz method from the QuizLogic instance
    return await context.user_data["quiz_logic_instance"].start_quiz(update)

async def handle_quiz_answer_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data # Format: quiz_{quiz_id}_ans_{q_idx}_{option_idx}
    logger.info(f"User {user_id} answered: {data}")
    
    quiz_logic_instance = context.user_data.get("quiz_logic_instance")
    if not quiz_logic_instance:
        logger.error(f"User {user_id} answered but no quiz_logic_instance found.")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ أثناء معالجة إجابتك. يرجى محاولة بدء اختبار جديد.")
        return await quiz_menu_entry(update, context)

    try:
        parts = data.split("_")
        # quiz_id = parts[1] # Not strictly needed by handler if it uses user_data internal quiz_id
        # question_index = int(parts[3]) # Also managed internally by QuizLogic
        chosen_option_index = int(parts[4])
    except (IndexError, ValueError) as e:
        # Corrected line below
        logger.error(f"Error parsing quiz answer callback data. Data: '{data}', Error: {e}")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ في بيانات الإجابة.")
        return TAKING_QUIZ # Stay in quiz, or end it if unrecoverable

    return await quiz_logic_instance.handle_answer(update, chosen_option_index)

async def handle_skip_question_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data # Format: quiz_{quiz_id}_skip_{q_idx}
    logger.info(f"User {user_id} skipped question: {data}")

    quiz_logic_instance = context.user_data.get("quiz_logic_instance")
    if not quiz_logic_instance:
        logger.error(f"User {user_id} skipped question but no quiz_logic_instance found.")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ أثناء معالجة التخطي. يرجى محاولة بدء اختبار جديد.")
        return await quiz_menu_entry(update, context)
    
    # The skip logic in QuizLogic needs the update object to potentially edit the message
    return await quiz_logic_instance.handle_skip_question(update)

async def cancel_quiz_selection(update: Update, context: CallbackContext) -> int:
    """Cancels the quiz selection process and returns to the main menu."""
    query = update.callback_query
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    message_id = query.message.message_id if query else None

    logger.info(f"User {user_id} cancelled quiz selection.")
    context.user_data.pop("quiz_selection", None)
    context.user_data.pop("current_page", None)
    context.user_data.pop("parent_id", None)
    context.user_data.pop("current_unit_id", None)
    context.user_data.pop("scope_items", None)
    context.user_data.pop("quiz_logic_instance", None)
    
    text = "تم إلغاء اختيار الاختبار."
    if query:
        await query.answer()
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=message_id, text=text, reply_markup=None)
    else: # Should not happen if cancel is only via button
        await safe_send_message(context.bot, chat_id=chat_id, text=text, reply_markup=None)

    # Send main menu again
    return await main_menu_callback(update, context, from_quiz_cancel=True)

async def handle_text_during_quiz(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    logger.warning(f"User {user_id} sent text during quiz: {update.message.text}")
    
    quiz_logic_instance = context.user_data.get("quiz_logic_instance")
    if quiz_logic_instance and quiz_logic_instance.user_data.get("current_quiz") and not quiz_logic_instance.user_data["current_quiz"].get("finished"):
        await safe_send_message(context.bot, chat_id, text="⚠️ يرجى استخدام الأزرار لاختيار الإجابة أو تخطي السؤال.")
        return TAKING_QUIZ # Stay in the quiz state
    else:
        # If not actively in a quiz, or quiz_logic_instance is missing, this text might be intended for something else.
        # Or it's a sign of a stuck state. For now, just log and don't change state.
        logger.info(f"User {user_id} sent text but not actively in a quiz or quiz_logic_instance missing. Text: {update.message.text}")
        # To prevent getting stuck, perhaps redirect to main menu if no quiz is active
        if not (quiz_logic_instance and quiz_logic_instance.user_data.get("current_quiz") and not quiz_logic_instance.user_data["current_quiz"].get("finished")):
            await safe_send_message(context.bot, chat_id, text="أمر غير متوقع. يتم إعادتك للقائمة الرئيسية.")
            return await main_menu_callback(update, context)
        return TAKING_QUIZ # Default to staying if unsure

# Conversation handler for the quiz
quiz_conv_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(quiz_menu_entry, pattern="^quiz_start$"),
        CommandHandler("quiz", quiz_menu_entry) # Allow starting with /quiz command
    ],
    states={
        SELECT_QUIZ_TYPE: [
            CallbackQueryHandler(select_quiz_type_callback, pattern="^quiz_type_"),
            CallbackQueryHandler(main_menu_callback, pattern="^main_menu$") # Back to main menu
        ],
        SELECT_QUIZ_SCOPE: [
            CallbackQueryHandler(select_quiz_scope_callback, pattern="^quiz_scope_"),
            CallbackQueryHandler(handle_scope_pagination_callback, pattern="^quiz_page_"),
            CallbackQueryHandler(handle_scope_back_callback, pattern="^quiz_back_to_"), # Handles specific back like to units
            CallbackQueryHandler(quiz_menu_entry, pattern="^quiz_menu$") # General back to quiz type selection
        ],
        ENTER_QUESTION_COUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, enter_question_count)
        ],
        TAKING_QUIZ: [
            CallbackQueryHandler(handle_quiz_answer_callback, pattern="^quiz_.*_ans_"),
            CallbackQueryHandler(handle_skip_question_callback, pattern="^quiz_.*_skip_"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_during_quiz) # Handle unexpected text
        ],
        # SHOWING_RESULTS is handled by QuizLogic ending the conversation or returning to MAIN_MENU
    },
    fallbacks=[
        CallbackQueryHandler(cancel_quiz_selection, pattern="^cancel_quiz$"), # A general cancel button if added
        CommandHandler("cancel", cancel_quiz_selection), # Command to cancel
        CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"), # Fallback to main menu
        CommandHandler("start", main_menu_callback) # Fallback to main menu on /start
    ],
    map_to_parent={
        # If the quiz finishes and returns MAIN_MENU, it goes to the parent conversation's MAIN_MENU state
        MAIN_MENU: MAIN_MENU,
        END: END
    },
    per_message=False,
    name="quiz_conversation",
    # persistent=True # Consider if persistence is needed and how to manage it
)

logger.info("handlers/quiz.py V1 Final (Syntax Corrected) loaded successfully with quiz_conv_handler.")

