# -*- coding: utf-8 -*-
"""Conversation handler for the quiz selection and execution flow."""

import logging
import math
# asyncio is no longer needed here as fetch_from_api is synchronous
# import asyncio 
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters, # Import filters (lowercase) instead of Filters
    CommandHandler # Added missing import
)

# Import necessary components from other modules
try:
    from config import (
        logger,
        MAIN_MENU, QUIZ_MENU, SELECT_QUIZ_TYPE, SELECT_QUIZ_SCOPE, 
        ENTER_QUESTION_COUNT, TAKING_QUIZ, SHOWING_RESULTS, END
    )
    from utils.helpers import safe_send_message, safe_edit_message_text
    # Ensure fetch_from_api is imported correctly
    from utils.api_client import fetch_from_api 
    # DB_MANAGER is no longer needed for content structure
    from handlers.common import create_main_menu_keyboard, main_menu_callback # For returning to main menu
    from handlers.quiz_logic import (
        start_quiz_logic, handle_quiz_answer, skip_question_callback, 
        end_quiz # Core logic functions
    )
except ImportError as e:
    # Fallback for potential import issues
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error(f"Error importing modules in handlers.quiz: {e}. Using placeholders.")
    # Define placeholders
    MAIN_MENU, QUIZ_MENU, SELECT_QUIZ_TYPE, SELECT_QUIZ_SCOPE, ENTER_QUESTION_COUNT, TAKING_QUIZ, SHOWING_RESULTS, END = 0, 1, 2, 3, 4, 5, 6, ConversationHandler.END
    async def safe_send_message(*args, **kwargs): logger.error("Placeholder safe_send_message called!")
    async def safe_edit_message_text(*args, **kwargs): logger.error("Placeholder safe_edit_message_text called!")
    # Simulate synchronous fetch_from_api
    def fetch_from_api(*args, **kwargs): logger.error("Placeholder fetch_from_api called!"); return None # Simulate API failure
    def create_main_menu_keyboard(*args, **kwargs): logger.error("Placeholder create_main_menu_keyboard called!"); return None
    async def main_menu_callback(*args, **kwargs): logger.error("Placeholder main_menu_callback called!"); return MAIN_MENU
    async def start_quiz_logic(*args, **kwargs): logger.error("Placeholder start_quiz_logic called!"); return SHOWING_RESULTS # End quiz immediately
    async def handle_quiz_answer(*args, **kwargs): logger.error("Placeholder handle_quiz_answer called!"); return TAKING_QUIZ
    async def skip_question_callback(*args, **kwargs): logger.error("Placeholder skip_question_callback called!"); return TAKING_QUIZ
    async def end_quiz(*args, **kwargs): logger.error("Placeholder end_quiz called!"); return MAIN_MENU

# --- Constants for Pagination --- 
ITEMS_PER_PAGE = 6 # Number of courses/units/lessons per page

# --- Helper Functions for Keyboards --- 

def create_quiz_type_keyboard() -> InlineKeyboardMarkup:
    """Creates keyboard for selecting quiz type (random, course, unit, lesson)."""
    keyboard = [
        [InlineKeyboardButton("🎲 اختبار عشوائي", callback_data="quiz_type_random")],
        [InlineKeyboardButton("📚 حسب المقرر", callback_data="quiz_type_course")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_scope_keyboard(scope_type: str, items: list, page: int = 0, parent_id: int | None = None) -> InlineKeyboardMarkup:
    """Creates a paginated keyboard for selecting course, unit, or lesson."""
    keyboard = []
    start_index = page * ITEMS_PER_PAGE
    end_index = start_index + ITEMS_PER_PAGE
    current_items = items[start_index:end_index]

    # Determine prefix and ID key based on scope_type
    prefix = ""
    id_key = ""
    name_key = "name"
    if scope_type == "course":
        prefix = "quiz_scope_course_"
        id_key = "course_id"
    elif scope_type == "unit":
        prefix = "quiz_scope_unit_"
        id_key = "unit_id"
    elif scope_type == "lesson":
        prefix = "quiz_scope_lesson_"
        id_key = "lesson_id"

    # Create buttons for items on the current page
    for item in current_items:
        item_id = item.get(id_key)
        item_name = item.get(name_key, f"Item {item_id}")
        if item_id is not None:
            keyboard.append([InlineKeyboardButton(item_name, callback_data=f"{prefix}{item_id}")])

    # Pagination controls
    pagination_row = []
    total_pages = math.ceil(len(items) / ITEMS_PER_PAGE)
    parent_id_str = str(parent_id) if parent_id is not None else ""
    if page > 0:
        pagination_row.append(InlineKeyboardButton("◀️ السابق", callback_data=f"quiz_page_{scope_type}_{page - 1}_{parent_id_str}"))
    if end_index < len(items):
        pagination_row.append(InlineKeyboardButton("▶️ التالي", callback_data=f"quiz_page_{scope_type}_{page + 1}_{parent_id_str}"))
    if pagination_row:
        keyboard.append(pagination_row)

    # Back button
    back_callback = "quiz_menu" # Default back to quiz type selection
    if scope_type == "unit" and parent_id is not None:
        back_callback = f"quiz_back_to_course"
    elif scope_type == "lesson" and parent_id is not None:
        back_callback = f"quiz_back_to_unit_{parent_id}" 
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])

    return InlineKeyboardMarkup(keyboard)

# --- Helper function to get question count by fetching list (Synchronous) --- 
def get_question_count_from_api(endpoint: str) -> int:
    """Fetches questions from an endpoint and returns the count."""
    logger.debug(f"Fetching questions from {endpoint} to get count.")
    # Removed await as fetch_from_api is assumed synchronous
    questions = fetch_from_api(endpoint) 
    if questions is None or not isinstance(questions, list):
        logger.error(f"Failed to fetch questions from {endpoint} or invalid format.")
        return 0 # Return 0 if fetch fails or format is wrong
    logger.debug(f"Found {len(questions)} questions at {endpoint}.")
    return len(questions)

# --- Conversation Steps (Modified for Synchronous API Calls) --- 

async def quiz_menu(update: Update, context: CallbackContext) -> int:
    """Displays the quiz type selection menu."""
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
    """Handles the selection of the quiz type."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"User {user_id} selected quiz type: {data}")

    quiz_type = data.split("_")[-1] # e.g., "random", "course"
    context.user_data["quiz_selection"] = {"type": quiz_type}
    context.user_data["current_page"] = 0 # Reset page for scope selection

    max_questions = 0
    error_message = ""

    if quiz_type == "random":
        # Fetch total random question count from API (Synchronous iteration)
        await safe_edit_message_text(query, text="⏳ جارٍ حساب عدد الأسئلة العشوائية...", reply_markup=None)
        # Removed await
        courses = fetch_from_api("/api/v1/courses") 
        if courses is None or not isinstance(courses, list):
            logger.error("Failed to fetch courses for random count.")
            error_message = "⚠️ حدث خطأ أثناء جلب المقررات لحساب الأسئلة العشوائية." 
        else:
            total_count = 0
            for course in courses:
                course_id = course.get("course_id")
                if course_id:
                    # Call synchronous helper function
                    count = get_question_count_from_api(f"/api/v1/courses/{course_id}/questions")
                    total_count += count
            max_questions = total_count

        if max_questions == 0 and not error_message:
             error_message = "⚠️ لم يتم العثور على أسئلة متاحة للاختبار العشوائي."

        if error_message:
            await safe_edit_message_text(query, text=error_message, reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
            
        context.user_data["quiz_selection"]["max_questions"] = max_questions
        logger.info(f"Random quiz selected. Max questions calculated: {max_questions}")
        text = f"🎲 اختبار عشوائي: أدخل عدد الأسئلة التي تريدها (1-{max_questions}):"
        await safe_edit_message_text(query, text=text, reply_markup=None)
        return ENTER_QUESTION_COUNT
        
    elif quiz_type == "course":
        # Fetch courses from API (Synchronous)
        # Removed await
        courses = fetch_from_api("/api/v1/courses") 
        if courses is None or not isinstance(courses, list):
            logger.error("Failed to fetch courses from API or invalid format.")
            await safe_edit_message_text(query, text="⚠️ حدث خطأ أثناء جلب المقررات الدراسية. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
            
        if not courses:
            await safe_edit_message_text(query, text="⚠️ لم يتم العثور على مقررات دراسية. لا يمكن المتابعة.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        
        context.user_data["scope_items"] = courses # Store items for pagination
        text = "📚 اختر المقرر الدراسي:"
        keyboard = create_scope_keyboard("course", courses, page=0)
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
        
    else:
        logger.warning(f"Unknown quiz type selected: {quiz_type}")
        await safe_edit_message_text(query, text="نوع اختبار غير معروف.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

async def select_quiz_scope(update: Update, context: CallbackContext) -> int:
    """Handles selection of course, unit, or lesson scope."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"User {user_id} selected quiz scope: {data}")

    parts = data.split("_")
    scope_level = parts[2] # course, unit, lesson
    scope_id = int(parts[3])

    context.user_data["quiz_selection"]["scope_id"] = scope_id
    context.user_data["current_page"] = 0 # Reset page for next level or count

    next_level_items = None # Use None to indicate API call needed/failed
    next_scope_type = ""
    prompt_text = ""
    api_endpoint = ""
    error_message = ""

    if scope_level == "course":
        # Fetch units for the selected course from API (Synchronous)
        api_endpoint = f"/api/v1/courses/{scope_id}/units"
        # Removed await
        next_level_items = fetch_from_api(api_endpoint) 
        next_scope_type = "unit"
        prompt_text = "📖 اختر الوحدة الدراسية:"
        context.user_data["parent_id"] = scope_id # Store course_id for back button
    elif scope_level == "unit":
        # Fetch lessons for the selected unit from API (Synchronous)
        api_endpoint = f"/api/v1/units/{scope_id}/lessons"
        # Removed await
        next_level_items = fetch_from_api(api_endpoint) 
        next_scope_type = "lesson"
        prompt_text = "📄 اختر الدرس:"
        context.user_data["parent_id"] = scope_id # Store unit_id for back button
    elif scope_level == "lesson":
        # Final level selected, ask for question count
        # Fetch question count for this lesson from API by getting the list (Synchronous)
        await safe_edit_message_text(query, text="⏳ جارٍ حساب عدد الأسئلة للدرس...", reply_markup=None)
        questions_endpoint = f"/api/v1/lessons/{scope_id}/questions"
        # Removed await
        max_questions = get_question_count_from_api(questions_endpoint) 
             
        if max_questions == 0:
             error_message = "⚠️ لم يتم العثور على أسئلة لهذا الدرس أو حدث خطأ." 

        if error_message:
            await safe_edit_message_text(query, text=error_message, reply_markup=create_quiz_type_keyboard()) # Go back to type selection
            return SELECT_QUIZ_TYPE
             
        context.user_data["quiz_selection"]["max_questions"] = max_questions
        logger.info(f"Lesson {scope_id} selected. Max questions calculated: {max_questions}")
        text = f"📄 درس محدد: أدخل عدد الأسئلة التي تريدها (1-{max_questions}):"
        await safe_edit_message_text(query, text=text, reply_markup=None)
        return ENTER_QUESTION_COUNT

    # Check API response for next level items
    if next_level_items is None or not isinstance(next_level_items, list):
        logger.error(f"Failed to fetch {next_scope_type}s from API ({api_endpoint}) or invalid format.")
        # Decide whether to ask for count for current level or show error
        # Let's show an error and go back for now
        error_message = f"⚠️ حدث خطأ أثناء جلب {prompt_text.split(" ")[-1]}. يرجى المحاولة مرة أخرى."
        await safe_edit_message_text(query, text=error_message, reply_markup=create_quiz_type_keyboard()) # Go back to type selection
        return SELECT_QUIZ_TYPE

    # If there are items for the next level, show them
    if next_level_items:
        context.user_data["scope_items"] = next_level_items # Store for pagination
        keyboard = create_scope_keyboard(next_scope_type, next_level_items, page=0, parent_id=scope_id)
        await safe_edit_message_text(query, text=prompt_text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE # Stay in this state for next level selection
    else:
        # No items found for the next level (e.g., course has no units)
        # Ask for question count for the current level (e.g., whole course/unit) (Synchronous)
        await safe_edit_message_text(query, text=f"⏳ جارٍ حساب عدد الأسئلة لـ {scope_level}...", reply_markup=None)
        questions_endpoint = f"/api/v1/{scope_level}s/{scope_id}/questions" # e.g., /api/v1/courses/1/questions
        # Removed await
        max_questions = get_question_count_from_api(questions_endpoint) 

        if max_questions == 0:
             error_message = f"⚠️ لم يتم العثور على أسئلة لـ {scope_level} {scope_id} أو حدث خطأ." 

        if error_message:
             await safe_edit_message_text(query, text=error_message, reply_markup=create_quiz_type_keyboard()) # Go back to type selection
             return SELECT_QUIZ_TYPE
             
        context.user_data["quiz_selection"]["max_questions"] = max_questions
        logger.info(f"{scope_level.capitalize()} {scope_id} selected (no sub-items). Max questions calculated: {max_questions}")
        text = f"📌 {scope_level.capitalize()} محدد: أدخل عدد الأسئلة التي تريدها (1-{max_questions}):"
        await safe_edit_message_text(query, text=text, reply_markup=None)
        return ENTER_QUESTION_COUNT

async def handle_scope_pagination(update: Update, context: CallbackContext) -> int:
    """Handles pagination for course/unit/lesson selection."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.debug(f"User {user_id} requested scope pagination: {data}")

    parts = data.split("_")
    scope_type = parts[2]
    page = int(parts[3])
    parent_id = int(parts[4]) if len(parts) > 4 and parts[4] else None

    items = context.user_data.get("scope_items", [])
    if not items:
        logger.warning("Pagination requested but no items found in user_data.")
        text = "حدث خطأ أثناء التنقل. يرجى المحاولة مرة أخرى."
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_TYPE
        
    context.user_data["current_page"] = page
    context.user_data["parent_id"] = parent_id

    prompt_map = {"course": "📚 اختر المقرر الدراسي:", "unit": "📖 اختر الوحدة الدراسية:", "lesson": "📄 اختر الدرس:"}
    text = prompt_map.get(scope_type, "اختر:")
    keyboard = create_scope_keyboard(scope_type, items, page=page, parent_id=parent_id)
    await safe_edit_message_text(query, text=text, reply_markup=keyboard)
    
    return SELECT_QUIZ_SCOPE # Remain in the scope selection state

async def handle_scope_back(update: Update, context: CallbackContext) -> int:
    """Handles the back button during scope selection."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.debug(f"User {user_id} pressed back button: {data}")

    if data == "quiz_menu": # Back from course list to type selection
        text = "🧠 اختر نوع الاختبار الذي تريده:"
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        context.user_data.pop("scope_items", None)
        context.user_data.pop("parent_id", None)
        context.user_data.pop("current_page", None)
        context.user_data.pop("quiz_selection", None)
        return SELECT_QUIZ_TYPE
        
    elif data == "quiz_back_to_course": # Back from unit list to course list
        # Removed await
        courses = fetch_from_api("/api/v1/courses") 
        if courses is None or not isinstance(courses, list):
            logger.error("Failed to fetch courses from API on back button.")
            await safe_edit_message_text(query, text="⚠️ حدث خطأ أثناء الرجوع. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
            
        if not courses:
            # If no courses, go back to quiz menu
            text = "🧠 اختر نوع الاختبار الذي تريده:"
            keyboard = create_quiz_type_keyboard()
            await safe_edit_message_text(query, text=text, reply_markup=keyboard)
            return SELECT_QUIZ_TYPE
            
        context.user_data["scope_items"] = courses
        context.user_data["current_page"] = 0
        context.user_data.pop("parent_id", None)
        text = "📚 اختر المقرر الدراسي:"
        keyboard = create_scope_keyboard("course", courses, page=0)
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
        
    elif data.startswith("quiz_back_to_unit_"): # Back from lesson list to unit list
        try:
            unit_id = int(data.split("_")[-1])
            # We need the course_id. It should be stored as parent_id when units were listed.
            course_id = context.user_data.get("parent_id") # This should be the course_id
            
            if course_id is None:
                 logger.error(f"Cannot go back to unit list: course_id not found for unit {unit_id}.")
                 # Fallback: Go back to course list instead
                 query.data = "quiz_back_to_course" # Modify query data to trigger course list fallback
                 return await handle_scope_back(update, context)

            units_endpoint = f"/api/v1/courses/{course_id}/units"
            # Removed await
            units = fetch_from_api(units_endpoint) 
            if units is None or not isinstance(units, list):
                logger.error(f"Failed to fetch units from API ({units_endpoint}) on back button.")
                await safe_edit_message_text(query, text="⚠️ حدث خطأ أثناء الرجوع. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_type_keyboard())
                return SELECT_QUIZ_TYPE

            if not units:
                 logger.warning(f"No units found for course {course_id} on back button.")
                 # Fallback: Go back to course list instead
                 query.data = "quiz_back_to_course" # Modify query data to trigger course list fallback
                 return await handle_scope_back(update, context)

            context.user_data["scope_items"] = units
            context.user_data["current_page"] = 0 # Reset page
            context.user_data["parent_id"] = course_id # Parent is now course
            text = "📖 اختر الوحدة الدراسية:"
            keyboard = create_scope_keyboard("unit", units, page=0, parent_id=course_id)
            await safe_edit_message_text(query, text=text, reply_markup=keyboard)
            return SELECT_QUIZ_SCOPE

        except (ValueError, IndexError, TypeError) as e:
             logger.error(f"Error parsing unit_id or getting course_id from back callback: {data}, Error: {e}")
             # Fallback to quiz menu
             text = "🧠 اختر نوع الاختبار الذي تريده:"
             keyboard = create_quiz_type_keyboard()
             await safe_edit_message_text(query, text=text, reply_markup=keyboard)
             return SELECT_QUIZ_TYPE

    else:
        logger.warning(f"Unknown back button data: {data}")
        # Fallback to quiz menu
        text = "🧠 اختر نوع الاختبار الذي تريده:"
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

async def enter_question_count(update: Update, context: CallbackContext) -> int:
    """Handles the user entering the desired number of questions."""
    user_id = update.effective_user.id
    try:
        count_text = update.message.text
        requested_count = int(count_text)
        logger.info(f"User {user_id} entered question count: {requested_count}")

        selection = context.user_data.get("quiz_selection")
        if not selection:
            logger.error("ENTER_QUESTION_COUNT state reached without quiz_selection.")
            await safe_send_message(context.bot, user_id, text="حدث خطأ، يرجى البدء من جديد.")
            keyboard = create_main_menu_keyboard(user_id)
            await safe_send_message(context.bot, user_id, text="القائمة الرئيسية:", reply_markup=keyboard)
            return MAIN_MENU

        max_questions = selection.get("max_questions", 0) # Default to 0 if missing

        if max_questions == 0:
             await safe_send_message(context.bot, user_id, text="⚠️ لا توجد أسئلة متاحة لهذا الاختيار. يرجى اختيار نطاق آخر.")
             text = "🧠 اختر نوع الاختبار الذي تريده:"
             keyboard = create_quiz_type_keyboard()
             await safe_send_message(context.bot, user_id, text=text, reply_markup=keyboard)
             return SELECT_QUIZ_TYPE

        if 1 <= requested_count <= max_questions:
            selection["count"] = requested_count
            logger.info(f"Starting quiz for user {user_id} with selection: {selection}")
            # start_quiz_logic is async, so await is needed here
            return await start_quiz_logic(update, context) 
        else:
            await safe_send_message(context.bot, user_id, text=f"❌ عدد غير صالح. يرجى إدخال رقم بين 1 و {max_questions}.")
            return ENTER_QUESTION_COUNT # Stay in this state

    except (ValueError, TypeError):
        await safe_send_message(context.bot, user_id, text="❌ إدخال غير صالح. يرجى إدخال رقم صحيح.")
        return ENTER_QUESTION_COUNT # Stay in this state
    except Exception as e:
        logger.error(f"Error processing question count for user {user_id}: {e}", exc_info=True)
        await safe_send_message(context.bot, user_id, text="حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى.")
        return ENTER_QUESTION_COUNT # Stay in this state

async def cancel_quiz_setup(update: Update, context: CallbackContext) -> int:
    """Cancels the quiz setup process and returns to the main menu."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} cancelled quiz setup.")
    query = update.callback_query
    message_func = safe_edit_message_text if query else safe_send_message
    target = query if query else context.bot
    chat_id = update.effective_chat.id
    
    if query:
        await query.answer()
        await message_func(target, text="تم إلغاء إعداد الاختبار.", reply_markup=None)
    else:
        await message_func(target, chat_id, text="تم إلغاء إعداد الاختبار.")
        
    context.user_data.pop("quiz_selection", None)
    context.user_data.pop("scope_items", None)
    context.user_data.pop("parent_id", None)
    context.user_data.pop("current_page", None)
    
    keyboard = create_main_menu_keyboard(user_id)
    await safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=keyboard)
    return MAIN_MENU

# --- Conversation Handler Definition --- 

quiz_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(quiz_menu, pattern="^menu_quiz$")],
    states={
        SELECT_QUIZ_TYPE: [
            CallbackQueryHandler(select_quiz_type, pattern="^quiz_type_"),
            CallbackQueryHandler(main_menu_callback, pattern="^main_menu$") # Back to main menu
        ],
        SELECT_QUIZ_SCOPE: [
            CallbackQueryHandler(select_quiz_scope, pattern="^quiz_scope_"),
            CallbackQueryHandler(handle_scope_pagination, pattern="^quiz_page_"),
            CallbackQueryHandler(handle_scope_back, pattern="^quiz_back_"), # Handle various back buttons
            CallbackQueryHandler(quiz_menu, pattern="^quiz_menu$") # Back to type selection
        ],
        ENTER_QUESTION_COUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, enter_question_count)
        ],
        TAKING_QUIZ: [
            CallbackQueryHandler(handle_quiz_answer, pattern="^quiz_answer_"),
            CallbackQueryHandler(skip_question_callback, pattern="^quiz_skip_")
        ],
        SHOWING_RESULTS: [
            CallbackQueryHandler(main_menu_callback, pattern="^main_menu$") # Back to main menu
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_quiz_setup), 
        CommandHandler("start", main_menu_callback), 
        CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"), 
        CallbackQueryHandler(cancel_quiz_setup, pattern="^cancel_setup$")
    ],
    map_to_parent={
        MAIN_MENU: MAIN_MENU,
        END: END
    },
    persistent=True, 
    name="quiz_conversation" 
)

