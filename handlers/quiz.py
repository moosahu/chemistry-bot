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
    filters # Import filters (lowercase) instead of Filters
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
        show_results # Core logic functions
    )
except ImportError as e:
    # Fallback for potential import issues
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error(f"Error importing modules in handlers.quiz: {e}. Using placeholders.")
    # Define placeholders
    MAIN_MENU, QUIZ_MENU, SELECT_QUIZ_TYPE, SELECT_QUIZ_SCOPE, ENTER_QUESTION_COUNT, TAKING_QUIZ, SHOWING_RESULTS, END = 0, 1, 2, 3, 4, 5, 6, ConversationHandler.END
    def safe_send_message(*args, **kwargs): logger.error("Placeholder safe_send_message called!")
    def safe_edit_message_text(*args, **kwargs): logger.error("Placeholder safe_edit_message_text called!")
    def fetch_from_api(*args, **kwargs): logger.error("Placeholder fetch_from_api called!"); return None # Simulate API failure
    # Dummy DB_MANAGER
    class DummyDBManager:
        def get_all_courses(*args, **kwargs): logger.warning("Dummy DB_MANAGER.get_all_courses called"); return []
        def get_units_by_course(*args, **kwargs): logger.warning("Dummy DB_MANAGER.get_units_by_course called"); return []
        def get_lessons_by_unit(*args, **kwargs): logger.warning("Dummy DB_MANAGER.get_lessons_by_unit called"); return []
    DB_MANAGER = DummyDBManager()
    def create_main_menu_keyboard(*args, **kwargs): logger.error("Placeholder create_main_menu_keyboard called!"); return None
    def main_menu_callback(*args, **kwargs): logger.error("Placeholder main_menu_callback called!"); return MAIN_MENU
    def start_quiz_logic(*args, **kwargs): logger.error("Placeholder start_quiz_logic called!"); return SHOWING_RESULTS # End quiz immediately
    def handle_quiz_answer(*args, **kwargs): logger.error("Placeholder handle_quiz_answer called!"); return TAKING_QUIZ
    def skip_question_callback(*args, **kwargs): logger.error("Placeholder skip_question_callback called!"); return TAKING_QUIZ
    def show_results(*args, **kwargs): logger.error("Placeholder show_results called!"); return MAIN_MENU

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
            keyboard.append([InlineKeyboardButton(item_name, callback_data=f"{prefix}{item_id}")]) # Corrected f-string

    # Pagination controls
    pagination_row = []
    total_pages = math.ceil(len(items) / ITEMS_PER_PAGE)
    if page > 0:
        pagination_row.append(InlineKeyboardButton("◀️ السابق", callback_data=f"quiz_page_{scope_type}_{page - 1}_{parent_id or ''}")) # Corrected f-string
    if end_index < len(items):
        pagination_row.append(InlineKeyboardButton("▶️ التالي", callback_data=f"quiz_page_{scope_type}_{page + 1}_{parent_id or ''}")) # Corrected f-string
    if pagination_row:
        keyboard.append(pagination_row)

    # Back button
    back_callback = "quiz_menu" # Default back to quiz type selection
    if scope_type == "unit" and parent_id is not None:
        back_callback = f"quiz_back_to_course"
    elif scope_type == "lesson" and parent_id is not None:
        # Assuming parent_id here is the unit_id when displaying lessons
        back_callback = f"quiz_back_to_unit_{parent_id}" 
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])

    return InlineKeyboardMarkup(keyboard)

# --- Conversation Steps --- 

def quiz_menu(update: Update, context: CallbackContext) -> int:
    """Displays the quiz type selection menu."""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if query:
        query.answer()
        logger.info(f"User {user_id} entered quiz menu.")
        text = "🧠 اختر نوع الاختبار الذي تريده:"
        keyboard = create_quiz_type_keyboard()
        safe_edit_message_text(query, text=text, reply_markup=keyboard)
    else:
        # Should be entered via callback, handle direct entry as error?
        logger.warning("quiz_menu called without callback query.")
        safe_send_message(context.bot, update.effective_chat.id, text="يرجى استخدام القائمة الرئيسية.")
        return MAIN_MENU
        
    # Clear previous selections if re-entering menu
    context.user_data.pop("quiz_selection", None)
    context.user_data.pop("current_page", None)
    context.user_data.pop("parent_id", None)
    
    return SELECT_QUIZ_TYPE

def select_quiz_type(update: Update, context: CallbackContext) -> int:
    """Handles the selection of the quiz type."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"User {user_id} selected quiz type: {data}")

    quiz_type = data.split("_")[-1] # Corrected split
    context.user_data["quiz_selection"] = {"type": quiz_type}
    context.user_data["current_page"] = 0 # Reset page for scope selection

    if quiz_type == "random":
        # Fetch total random question count from API (optional, can skip)
        # count_response = fetch_from_api("/questions/count")
        # max_questions = count_response.get("count") if isinstance(count_response, dict) else 50 # Default max
        # For random, maybe just set a reasonable max or skip count check here
        max_questions = 50 # Assume a max of 50 random questions available
        context.user_data["quiz_selection"]["max_questions"] = max_questions
        logger.info(f"Random quiz selected. Max questions assumed: {max_questions}")
        text = f"🎲 اختبار عشوائي: أدخل عدد الأسئلة التي تريدها (1-{max_questions}):"
        safe_edit_message_text(query, text=text, reply_markup=None)
        return ENTER_QUESTION_COUNT
        
    elif quiz_type == "course":
        # Fetch courses from DB
        courses = DB_MANAGER.get_all_courses() if DB_MANAGER else []
        if not courses:
            safe_edit_message_text(query, text="⚠️ لم يتم العثور على مقررات دراسية. لا يمكن المتابعة.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        
        context.user_data["scope_items"] = courses # Store items for pagination
        text = "📚 اختر المقرر الدراسي:"
        keyboard = create_scope_keyboard("course", courses, page=0)
        safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
        
    # Add elif for "unit", "lesson" if direct selection is implemented
    else:
        logger.warning(f"Unknown quiz type selected: {quiz_type}")
        safe_edit_message_text(query, text="نوع اختبار غير معروف.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

def select_quiz_scope(update: Update, context: CallbackContext) -> int:
    """Handles selection of course, unit, or lesson scope."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"User {user_id} selected quiz scope: {data}")

    parts = data.split("_") # Corrected split
    scope_level = parts[2] # course, unit, lesson
    scope_id = int(parts[3])

    context.user_data["quiz_selection"]["scope_id"] = scope_id
    context.user_data["current_page"] = 0 # Reset page for next level or count

    next_level_items = []
    next_scope_type = ""
    prompt_text = ""
    parent_course_id = context.user_data.get("parent_id") # Get parent course id if exists (from previous level)

    if scope_level == "course":
        # Fetch units for the selected course
        next_level_items = DB_MANAGER.get_units_by_course(scope_id) if DB_MANAGER else []
        next_scope_type = "unit"
        prompt_text = "📖 اختر الوحدة الدراسية:"
        context.user_data["parent_id"] = scope_id # Store course_id for back button from unit list
    elif scope_level == "unit":
        # Fetch lessons for the selected unit
        next_level_items = DB_MANAGER.get_lessons_by_unit(scope_id) if DB_MANAGER else []
        next_scope_type = "lesson"
        prompt_text = "📄 اختر الدرس:"
        # Keep the parent_id (which is course_id) for potential back navigation
        # Store the current unit_id separately if needed for back from lesson list
        context.user_data["current_unit_id"] = scope_id 
    elif scope_level == "lesson":
        # Final level selected, ask for question count
        # Fetch question count for this lesson from API
        count_response = fetch_from_api(f"/lessons/{scope_id}/questions/count")
        max_questions = count_response.get("count") if isinstance(count_response, dict) else 20 # Default max
        context.user_data["quiz_selection"]["max_questions"] = max_questions
        logger.info(f"Lesson {scope_id} selected. Max questions from API: {max_questions}")
        text = f"📄 درس محدد: أدخل عدد الأسئلة التي تريدها (1-{max_questions}):"
        safe_edit_message_text(query, text=text, reply_markup=None)
        return ENTER_QUESTION_COUNT

    # If there are items for the next level, show them
    if next_level_items:
        context.user_data["scope_items"] = next_level_items # Store for pagination
        # Pass the correct parent ID for the next level's back button
        parent_id_for_next = scope_id if scope_level == "course" else context.user_data.get("current_unit_id")
        keyboard = create_scope_keyboard(next_scope_type, next_level_items, page=0, parent_id=parent_id_for_next)
        safe_edit_message_text(query, text=prompt_text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE # Stay in this state for next level selection
    else:
        # No items found for the next level (e.g., course has no units, unit has no lessons)
        # Ask for question count for the current level (e.g., whole course/unit)
        count_endpoint = f"/{scope_level}s/{scope_id}/questions/count" # e.g., /courses/1/questions/count
        count_response = fetch_from_api(count_endpoint)
        max_questions = count_response.get("count") if isinstance(count_response, dict) else 30 # Default max
        context.user_data["quiz_selection"]["max_questions"] = max_questions
        logger.info(f"{scope_level.capitalize()} {scope_id} selected (no sub-items). Max questions from API: {max_questions}")
        text = f"📌 {scope_level.capitalize()} محدد: أدخل عدد الأسئلة التي تريدها (1-{max_questions}):"
        safe_edit_message_text(query, text=text, reply_markup=None)
        return ENTER_QUESTION_COUNT

def handle_scope_pagination(update: Update, context: CallbackContext) -> int:
    """Handles pagination for course/unit/lesson selection."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.debug(f"User {user_id} requested scope pagination: {data}")

    parts = data.split("_") # Corrected split
    scope_type = parts[2]
    page = int(parts[3])
    parent_id = int(parts[4]) if len(parts) > 4 and parts[4] else None

    items = context.user_data.get("scope_items", [])
    if not items:
        logger.warning("Pagination requested but no items found in user_data.")
        # Go back to quiz type selection as something went wrong
        text = "حدث خطأ أثناء التنقل. يرجى المحاولة مرة أخرى."
        keyboard = create_quiz_type_keyboard()
        safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_TYPE
        
    # Store current page and parent_id
    context.user_data["current_page"] = page
    # context.user_data["parent_id"] = parent_id # Re-evaluate if parent_id needs update here

    # Create and send the keyboard for the requested page
    prompt_map = {"course": "📚 اختر المقرر الدراسي:", "unit": "📖 اختر الوحدة الدراسية:", "lesson": "📄 اختر الدرس:"}
    text = prompt_map.get(scope_type, "اختر:")
    # Get the correct parent_id for the back button based on current scope_type
    current_parent_id = context.user_data.get("parent_id") if scope_type == "unit" else context.user_data.get("current_unit_id")
    keyboard = create_scope_keyboard(scope_type, items, page=page, parent_id=current_parent_id)
    safe_edit_message_text(query, text=text, reply_markup=keyboard)
    
    return SELECT_QUIZ_SCOPE # Remain in the scope selection state

def handle_scope_back(update: Update, context: CallbackContext) -> int:
    """Handles the back button during scope selection."""
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.debug(f"User {user_id} pressed back button: {data}")

    # Determine where to go back to
    if data == "quiz_menu": # Back from course list to type selection
        text = "🧠 اختر نوع الاختبار الذي تريده:"
        keyboard = create_quiz_type_keyboard()
        safe_edit_message_text(query, text=text, reply_markup=keyboard)
        # Clear scope selection data
        context.user_data.pop("scope_items", None)
        context.user_data.pop("parent_id", None)
        context.user_data.pop("current_page", None)
        context.user_data.pop("quiz_selection", None)
        context.user_data.pop("current_unit_id", None)
        return SELECT_QUIZ_TYPE
        
    elif data == "quiz_back_to_course": # Back from unit list to course list
        courses = DB_MANAGER.get_all_courses() if DB_MANAGER else []
        if not courses:
            # Fallback if courses can't be fetched
            return quiz_menu(update, context) 
        context.user_data["scope_items"] = courses
        context.user_data["current_page"] = 0 # Reset page
        context.user_data.pop("parent_id", None) # Clear parent_id (was course_id)
        context.user_data.pop("current_unit_id", None)
        text = "📚 اختر المقرر الدراسي:"
        keyboard = create_scope_keyboard("course", courses, page=0)
        safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
        
    elif data.startswith("quiz_back_to_unit_"): # Back from lesson list to unit list
        try:
            # The parent_id passed when creating the lesson list keyboard was the unit_id
            unit_id = int(data.split("_")[-1]) # Corrected split
            # We need the course_id to fetch units for that course.
            # It should be stored in parent_id from the previous step (unit selection)
            course_id = context.user_data.get("parent_id") 
            if course_id is None:
                 logger.error("Cannot go back to unit list: parent course_id not found in user_data.")
                 return quiz_menu(update, context) # Fallback to main quiz menu
                 
            units = DB_MANAGER.get_units_by_course(course_id) if DB_MANAGER else []
            if not units:
                 return quiz_menu(update, context) # Fallback
                 
            context.user_data["scope_items"] = units
            context.user_data["current_page"] = 0
            context.user_data["current_unit_id"] = None # Clear current unit id
            # parent_id remains the course_id
            text = "📖 اختر الوحدة الدراسية:"
            keyboard = create_scope_keyboard("unit", units, page=0, parent_id=course_id)
            safe_edit_message_text(query, text=text, reply_markup=keyboard)
            return SELECT_QUIZ_SCOPE
        except (ValueError, IndexError):
             logger.error(f"Error parsing unit_id from back callback: {data}")
             return quiz_menu(update, context) # Fallback
             
    else:
        logger.warning(f"Unknown back callback: {data}")
        return quiz_menu(update, context) # Fallback to main quiz menu

def enter_question_count(update: Update, context: CallbackContext) -> int:
    """Handles the user entering the desired number of questions."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    text = update.message.text
    logger.info(f"User {user.id} entered question count: {text}")

    quiz_selection = context.user_data.get("quiz_selection")
    if not quiz_selection:
        logger.error("enter_question_count called without quiz_selection in user_data.")
        safe_send_message(context.bot, chat_id, text="حدث خطأ. يرجى البدء من القائمة الرئيسية.")
        return MAIN_MENU

    max_questions = quiz_selection.get("max_questions", 1) # Default to 1 if somehow missing

    try:
        count = int(text)
        if 1 <= count <= max_questions:
            quiz_selection["count"] = count
            logger.info(f"User {user.id} confirmed {count} questions.")
            # Proceed to start the quiz using the logic function
            # start_quiz_logic will handle API calls, state setup, and sending the first question
            return start_quiz_logic(update, context)
        else:
            safe_send_message(context.bot, chat_id, text=f"الرجاء إدخال رقم صحيح بين 1 و {max_questions}.")
            return ENTER_QUESTION_COUNT # Remain in this state
    except ValueError:
        safe_send_message(context.bot, chat_id, text=f"إدخال غير صالح. الرجاء إدخال رقم صحيح بين 1 و {max_questions}.")
        return ENTER_QUESTION_COUNT # Remain in this state

# --- Conversation Handler Definition --- 

quiz_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(quiz_menu, pattern="^menu_quiz$")], # Corrected pattern
    states={
        SELECT_QUIZ_TYPE: [
            CallbackQueryHandler(select_quiz_type, pattern="^quiz_type_"), # Corrected pattern
            CallbackQueryHandler(main_menu_callback, pattern="^main_menu$") # Corrected pattern
        ],
        SELECT_QUIZ_SCOPE: [
            CallbackQueryHandler(select_quiz_scope, pattern="^quiz_scope_"), # Corrected pattern
            CallbackQueryHandler(handle_scope_pagination, pattern="^quiz_page_"), # Corrected pattern
            CallbackQueryHandler(handle_scope_back, pattern="^quiz_back_to_|^quiz_menu$") # Corrected pattern
        ],
        ENTER_QUESTION_COUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, enter_question_count),
        ],
        TAKING_QUIZ: [
            CallbackQueryHandler(handle_quiz_answer, pattern="^quiz_.*_ans_"), # Corrected pattern
            CallbackQueryHandler(skip_question_callback, pattern="^quiz_.*_skip_") # Corrected pattern
            # No message handler here, only button presses expected
        ],
        SHOWING_RESULTS: [
            # This state is usually terminal, show_results returns MAIN_MENU
            # Add handlers here if interaction is needed after results (e.g., review answers)
            CallbackQueryHandler(main_menu_callback, pattern="^main_menu$") # Corrected pattern
        ],
    },
    fallbacks=[
        CommandHandler("start", main_menu_callback), # Corrected command name
        CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"), # Corrected pattern
        # Add a generic fallback message?
        MessageHandler(filters.ALL, lambda u, c: quiz_fallback(u, c)) # Corrected filter name
    ],
    map_to_parent={
        # If MAIN_MENU is returned, map it to the main conversation handler's MAIN_MENU state
        MAIN_MENU: MAIN_MENU,
        # If END is returned, end the conversation
        END: END
    },
    # Allow re-entry e.g. if user presses /start during quiz selection
    allow_reentry=True
)

def quiz_fallback(update: Update, context: CallbackContext):
    """Generic fallback handler within the quiz conversation."""
    logger.warning(f"Quiz fallback triggered for update: {update}")
    state = context.conversation_state
    text = "أمر غير معروف أو إجراء غير متوقع."
    keyboard = None
    next_state = state # Default to staying in the same state

    if state == ENTER_QUESTION_COUNT:
        text += " يرجى إدخال عدد الأسئلة المطلوب."
    elif state == TAKING_QUIZ:
        text += " يرجى استخدام الأزرار للإجابة على السؤال أو تخطيه."
    else:
        text += " العودة إلى قائمة اختيار الاختبار."
        keyboard = create_quiz_type_keyboard()
        next_state = SELECT_QUIZ_TYPE
        # Clear potentially inconsistent state data
        context.user_data.pop("quiz_selection", None)
        context.user_data.pop("scope_items", None)
        context.user_data.pop("parent_id", None)
        context.user_data.pop("current_page", None)
        context.user_data.pop("current_unit_id", None)

    if update.callback_query:
        safe_edit_message_text(update.callback_query, text=text, reply_markup=keyboard)
    else:
        safe_send_message(context.bot, update.effective_chat.id, text=text, reply_markup=keyboard)
        
    return next_state

