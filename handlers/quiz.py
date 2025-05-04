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
    from utils.api_client import fetch_from_api # To get counts
    from database.manager import DB_MANAGER # To get structure
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
    async def fetch_from_api(*args, **kwargs): logger.error("Placeholder fetch_from_api called!"); return None # Simulate API failure
    # Dummy DB_MANAGER
    class DummyDBManager:
        def get_all_courses(*args, **kwargs): logger.warning("Dummy DB_MANAGER.get_all_courses called"); return []
        def get_units_by_course(*args, **kwargs): logger.warning("Dummy DB_MANAGER.get_units_by_course called"); return []
        def get_lessons_by_unit(*args, **kwargs): logger.warning("Dummy DB_MANAGER.get_lessons_by_unit called"); return []
    DB_MANAGER = DummyDBManager()
    def create_main_menu_keyboard(*args, **kwargs): logger.error("Placeholder create_main_menu_keyboard called!"); return None
    async def main_menu_callback(*args, **kwargs): logger.error("Placeholder main_menu_callback called!"); return MAIN_MENU
    async def start_quiz_logic(*args, **kwargs): logger.error("Placeholder start_quiz_logic called!"); return SHOWING_RESULTS # End quiz immediately
    async def handle_quiz_answer(*args, **kwargs): logger.error("Placeholder handle_quiz_answer called!"); return TAKING_QUIZ
    async def skip_question_callback(*args, **kwargs): logger.error("Placeholder skip_question_callback called!"); return TAKING_QUIZ
    async def show_results(*args, **kwargs): logger.error("Placeholder show_results called!"); return MAIN_MENU

# --- Constants for Pagination --- 
ITEMS_PER_PAGE = 6 # Number of courses/units/lessons per page

# --- Helper Functions for Keyboards --- 

def create_quiz_type_keyboard() -> InlineKeyboardMarkup:
    """Creates keyboard for selecting quiz type (random, course, unit, lesson)."""
    keyboard = [
        [InlineKeyboardButton("🎲 اختبار عشوائي", callback_data="quiz_type_random")],
        [InlineKeyboardButton("📚 حسب المقرر", callback_data="quiz_type_course")],
        # Add unit/lesson later if direct selection is needed, or handle via course
        # [InlineKeyboardButton("📖 حسب الوحدة", callback_data="quiz_type_unit")],
        # [InlineKeyboardButton("📄 حسب الدرس", callback_data="quiz_type_lesson")],
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
            # Corrected: Ensure no newlines in callback_data
            keyboard.append([InlineKeyboardButton(item_name, callback_data=f"{prefix}{item_id}")])

    # Pagination controls
    pagination_row = []
    total_pages = math.ceil(len(items) / ITEMS_PER_PAGE)
    # Corrected: Prepare parent_id string before f-string
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
        # Need parent unit ID for back button from lesson list
        # This assumes parent_id passed here is the unit_id
        back_callback = f"quiz_back_to_unit_{parent_id}" 
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])

    return InlineKeyboardMarkup(keyboard)

# --- Conversation Steps (Converted to async) --- 

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
        # Should be entered via callback, handle direct entry as error?
        logger.warning("quiz_menu called without callback query.")
        await safe_send_message(context.bot, update.effective_chat.id, text="يرجى استخدام القائمة الرئيسية.")
        return MAIN_MENU
        
    # Clear previous selections if re-entering menu
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

    if quiz_type == "random":
        # Fetch total random question count from API (optional, can skip)
        # count_response = await fetch_from_api("/questions/count") # Assuming fetch_from_api is async
        # max_questions = count_response.get("count") if isinstance(count_response, dict) else 50 # Default max
        # For random, maybe just set a reasonable max or skip count check here
        max_questions = 50 # Assume a max of 50 random questions available
        context.user_data["quiz_selection"]["max_questions"] = max_questions
        logger.info(f"Random quiz selected. Max questions assumed: {max_questions}")
        text = f"🎲 اختبار عشوائي: أدخل عدد الأسئلة التي تريدها (1-{max_questions}):"
        await safe_edit_message_text(query, text=text, reply_markup=None)
        return ENTER_QUESTION_COUNT
        
    elif quiz_type == "course":
        # Fetch courses from DB (assuming synchronous)
        courses = DB_MANAGER.get_all_courses() if DB_MANAGER else []
        if not courses:
            await safe_edit_message_text(query, text="⚠️ لم يتم العثور على مقررات دراسية. لا يمكن المتابعة.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        
        context.user_data["scope_items"] = courses # Store items for pagination
        text = "📚 اختر المقرر الدراسي:"
        keyboard = create_scope_keyboard("course", courses, page=0)
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
        
    # Add elif for "unit", "lesson" if direct selection is implemented
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

    next_level_items = []
    next_scope_type = ""
    prompt_text = ""

    if scope_level == "course":
        # Fetch units for the selected course (assuming synchronous)
        next_level_items = DB_MANAGER.get_units_by_course(scope_id) if DB_MANAGER else []
        next_scope_type = "unit"
        prompt_text = "📖 اختر الوحدة الدراسية:"
        context.user_data["parent_id"] = scope_id # Store course_id for back button
    elif scope_level == "unit":
        # Fetch lessons for the selected unit (assuming synchronous)
        next_level_items = DB_MANAGER.get_lessons_by_unit(scope_id) if DB_MANAGER else []
        next_scope_type = "lesson"
        prompt_text = "📄 اختر الدرس:"
        # Need parent course ID if going back from lesson -> unit -> course
        # Assuming parent_id (course_id) is still in user_data
        # We need unit_id for back button from lesson list
        context.user_data["parent_id"] = scope_id # Store unit_id for back button
    elif scope_level == "lesson":
        # Final level selected, ask for question count
        # Fetch question count for this lesson from API (assuming async)
        count_response = await fetch_from_api(f"/lessons/{scope_id}/questions/count")
        max_questions = count_response.get("count") if isinstance(count_response, dict) else 20 # Default max
        context.user_data["quiz_selection"]["max_questions"] = max_questions
        logger.info(f"Lesson {scope_id} selected. Max questions from API: {max_questions}")
        text = f"📄 درس محدد: أدخل عدد الأسئلة التي تريدها (1-{max_questions}):"
        await safe_edit_message_text(query, text=text, reply_markup=None)
        return ENTER_QUESTION_COUNT

    # If there are items for the next level, show them
    if next_level_items:
        context.user_data["scope_items"] = next_level_items # Store for pagination
        keyboard = create_scope_keyboard(next_scope_type, next_level_items, page=0, parent_id=scope_id)
        await safe_edit_message_text(query, text=prompt_text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE # Stay in this state for next level selection
    else:
        # No items found for the next level (e.g., course has no units)
        # Ask for question count for the current level (e.g., whole course/unit)
        count_endpoint = f"/{scope_level}s/{scope_id}/questions/count" # e.g., /courses/1/questions/count
        count_response = await fetch_from_api(count_endpoint) # Assuming async
        max_questions = count_response.get("count") if isinstance(count_response, dict) else 30 # Default max
        context.user_data["quiz_selection"]["max_questions"] = max_questions
        logger.info(f"{scope_level.capitalize()} {scope_id} selected (no sub-items). Max questions from API: {max_questions}")
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
        # Go back to quiz type selection as something went wrong
        text = "حدث خطأ أثناء التنقل. يرجى المحاولة مرة أخرى."
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_TYPE
        
    # Store current page and parent_id
    context.user_data["current_page"] = page
    context.user_data["parent_id"] = parent_id

    # Create and send the keyboard for the requested page
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

    # Determine where to go back to
    if data == "quiz_menu": # Back from course list to type selection
        text = "🧠 اختر نوع الاختبار الذي تريده:"
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        # Clear scope selection data
        context.user_data.pop("scope_items", None)
        context.user_data.pop("parent_id", None)
        context.user_data.pop("current_page", None)
        context.user_data.pop("quiz_selection", None)
        return SELECT_QUIZ_TYPE
        
    elif data == "quiz_back_to_course": # Back from unit list to course list
        courses = DB_MANAGER.get_all_courses() if DB_MANAGER else []
        if not courses:
            # Fallback if courses can't be fetched
            return await quiz_menu(update, context) # Call async version
        context.user_data["scope_items"] = courses
        context.user_data["current_page"] = 0 # Reset page
        context.user_data.pop("parent_id", None) # Clear parent_id (was course_id)
        text = "📚 اختر المقرر الدراسي:"
        keyboard = create_scope_keyboard("course", courses, page=0)
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
        
    elif data.startswith("quiz_back_to_unit_"): # Back from lesson list to unit list
        try:
            unit_id = int(data.split("_")[-1])
            # Need the course_id to fetch units for that course
            # This is complex - simpler approach: go back to course list
            logger.warning("Back to unit list not fully implemented, going back to course list.")
            return await handle_scope_back(update, context) # Simulate pressing back again
            # # Proper implementation (requires fetching course_id from unit_id):
            # course_id = DB_MANAGER.get_course_id_for_unit(unit_id) # Needs this DB function
            # if course_id:
            #     units = DB_MANAGER.get_units_by_course(course_id)
            #     context.user_data["scope_items"] = units
            #     context.user_data["current_page"] = 0 # Or find the page unit_id was on
            #     context.user_data["parent_id"] = course_id
            #     text = "📖 اختر الوحدة الدراسية:"
            #     keyboard = create_scope_keyboard("unit", units, page=0, parent_id=course_id)
            #     await safe_edit_message_text(query, text=text, reply_markup=keyboard)
            #     return SELECT_QUIZ_SCOPE
            # else:
            #     return await quiz_menu(update, context) # Fallback
        except (ValueError, IndexError):
             logger.error(f"Error parsing unit_id from back callback: {data}")
             return await quiz_menu(update, context) # Fallback

    else:
        logger.warning(f"Unknown back button data: {data}")
        return await quiz_menu(update, context) # Fallback to quiz menu

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
            return await main_menu_callback(update, context) # Go to main menu

        max_questions = selection.get("max_questions", 1) # Default to 1 if missing

        if 1 <= requested_count <= max_questions:
            selection["count"] = requested_count
            logger.info(f"Starting quiz for user {user_id} with selection: {selection}")
            # Call the async version of start_quiz_logic
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
    await safe_send_message(context.bot, user_id, text="تم إلغاء إعداد الاختبار.")
    # Clear potentially stored data
    context.user_data.pop("quiz_selection", None)
    context.user_data.pop("scope_items", None)
    context.user_data.pop("parent_id", None)
    context.user_data.pop("current_page", None)
    # Call the async version of main_menu_callback to show the menu
    # Need to simulate a callback query or send a new message
    # Simplest: send a new message with the main menu
    keyboard = create_main_menu_keyboard(user_id)
    await safe_send_message(context.bot, user_id, text="القائمة الرئيسية:", reply_markup=keyboard)
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
            # Add timeout handler? End quiz handler?
        ],
        SHOWING_RESULTS: [
            # CallbackQueryHandler(quiz_menu, pattern="^quiz_new$"), # Start new quiz
            CallbackQueryHandler(main_menu_callback, pattern="^main_menu$") # Back to main menu
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_quiz_setup), # Allow cancelling setup
        CommandHandler("start", main_menu_callback), # Go to main menu on /start
        CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"), # Handle explicit main menu return
        # Fallback for unexpected input during setup?
        MessageHandler(filters.ALL, quiz_menu) # Or a more specific error handler
    ],
    map_to_parent={
        # If MAIN_MENU is returned by a handler, go back to the main conversation's MAIN_MENU state
        MAIN_MENU: MAIN_MENU,
        # If END is returned, end the conversation
        END: END
    },
    persistent=True, # Enable persistence
    name="quiz_conversation" # Unique name for persistence
)

