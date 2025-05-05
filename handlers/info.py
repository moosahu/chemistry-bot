# -*- coding: utf-8 -*-
"""Conversation handler for displaying information about courses, units, and lessons."""

import logging
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler # Added missing import
)

try:
    from config import (
        logger,
        MAIN_MENU, INFO_MENU, SHOW_INFO_DETAIL, END
    )
    from utils.helpers import safe_send_message, safe_edit_message_text
    # DB_MANAGER is no longer needed for content structure
    # from database.manager import DB_MANAGER 
    from utils.api_client import fetch_from_api # Use API client
    from handlers.common import create_main_menu_keyboard, main_menu_callback # For returning to main menu
except ImportError as e:
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error(f"Error importing modules in handlers.info: {e}. Using placeholders.")
    MAIN_MENU, INFO_MENU, SHOW_INFO_DETAIL, END = 0, 1, 2, ConversationHandler.END
    async def safe_send_message(*args, **kwargs): logger.error("Placeholder safe_send_message called!")
    async def safe_edit_message_text(*args, **kwargs): logger.error("Placeholder safe_edit_message_text called!")
    # Simulate synchronous fetch_from_api
    def fetch_from_api(*args, **kwargs): logger.error("Placeholder fetch_from_api called!"); return None # Simulate API failure
    def create_main_menu_keyboard(*args, **kwargs): logger.error("Placeholder create_main_menu_keyboard called!"); return None
    async def main_menu_callback(*args, **kwargs): logger.error("Placeholder main_menu_callback called!"); return MAIN_MENU

# --- Constants for Pagination --- 
ITEMS_PER_PAGE = 6 # Number of courses/units/lessons per page

# --- Helper Functions --- 

def create_info_scope_keyboard(scope_type: str, items: list, page: int = 0, parent_id: int | None = None) -> InlineKeyboardMarkup:
    """Creates a paginated keyboard for selecting course, unit, or lesson for info."""
    keyboard = []
    start_index = page * ITEMS_PER_PAGE
    end_index = start_index + ITEMS_PER_PAGE
    current_items = items[start_index:end_index]

    # Determine prefix and ID key based on scope_type
    prefix = ""
    # Corrected: API always returns 'id'
    id_key = "id" 
    name_key = "name"
    if scope_type == "course":
        prefix = "info_scope_course_"
    elif scope_type == "unit":
        prefix = "info_scope_unit_"
    elif scope_type == "lesson":
        prefix = "info_scope_lesson_"

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
        pagination_row.append(InlineKeyboardButton("◀️ السابق", callback_data=f"info_page_{scope_type}_{page - 1}_{parent_id_str}"))
    if end_index < len(items):
        pagination_row.append(InlineKeyboardButton("▶️ التالي", callback_data=f"info_page_{scope_type}_{page + 1}_{parent_id_str}"))
    if pagination_row:
        keyboard.append(pagination_row)

    # Back button
    back_callback = "main_menu" # Default back to main menu
    if scope_type == "unit" and parent_id is not None:
        back_callback = f"info_back_to_course"
    elif scope_type == "lesson" and parent_id is not None:
        back_callback = f"info_back_to_unit_{parent_id}"
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)])

    return InlineKeyboardMarkup(keyboard)

# --- Conversation Steps --- 

async def info_menu(update: Update, context: CallbackContext) -> int:
    """Displays the course selection menu for information."""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if query:
        await query.answer()
        logger.info(f"User {user_id} entered info menu.")
    else:
        logger.warning("info_menu called without callback query.")
        await safe_send_message(context.bot, update.effective_chat.id, text="يرجى استخدام القائمة الرئيسية.")
        return MAIN_MENU
        
    context.user_data.pop("info_selection", None)
    context.user_data.pop("current_page", None)
    context.user_data.pop("parent_id", None)

    # Fetch courses from API (Synchronous)
    courses = fetch_from_api("/api/v1/courses") 
    if courses is None or not isinstance(courses, list):
        logger.error("Failed to fetch courses from API for info menu.")
        await safe_edit_message_text(query, text="⚠️ حدث خطأ أثناء جلب المقررات الدراسية. يرجى المحاولة مرة أخرى.", reply_markup=create_main_menu_keyboard())
        return MAIN_MENU
        
    if not courses:
        await safe_edit_message_text(query, text="⚠️ لم يتم العثور على مقررات دراسية.", reply_markup=create_main_menu_keyboard())
        return MAIN_MENU
    
    context.user_data["scope_items"] = courses # Store items for pagination
    text = "📚 اختر المقرر الدراسي لعرض معلوماته:"
    keyboard = create_info_scope_keyboard("course", courses, page=0)
    await safe_edit_message_text(query, text=text, reply_markup=keyboard)
    
    return INFO_MENU

async def select_info_scope(update: Update, context: CallbackContext) -> int:
    """Handles selection of course, unit, or lesson scope for info."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"User {user_id} selected info scope: {data}")

    parts = data.split("_")
    scope_level = parts[2] # course, unit, lesson
    scope_id = int(parts[3])

    context.user_data["info_selection"] = {"type": scope_level, "id": scope_id}
    context.user_data["current_page"] = 0 # Reset page for next level or detail

    next_level_items = None
    next_scope_type = ""
    prompt_text = ""
    api_endpoint = ""
    error_message = ""

    if scope_level == "course":
        # Fetch units for the selected course from API (Synchronous)
        api_endpoint = f"/api/v1/courses/{scope_id}/units"
        next_level_items = fetch_from_api(api_endpoint) 
        next_scope_type = "unit"
        prompt_text = "📖 اختر الوحدة الدراسية لعرض معلوماتها:"
        context.user_data["parent_id"] = scope_id # Store course_id for back button
    elif scope_level == "unit":
        # Fetch lessons for the selected unit from API (Synchronous)
        api_endpoint = f"/api/v1/units/{scope_id}/lessons"
        next_level_items = fetch_from_api(api_endpoint) 
        next_scope_type = "lesson"
        prompt_text = "📄 اختر الدرس لعرض معلوماته:"
        context.user_data["parent_id"] = scope_id # Store unit_id for back button
    elif scope_level == "lesson":
        # Final level selected, show lesson detail
        api_endpoint = f"/api/v1/lessons/{scope_id}"
        lesson_detail = fetch_from_api(api_endpoint) 
        if lesson_detail and isinstance(lesson_detail, dict):
            # Corrected: Use 'id' from API response
            lesson_name = lesson_detail.get("name", f"Lesson {lesson_detail.get(\"id\")}")
            lesson_content = lesson_detail.get("content", "لا يوجد محتوى متاح لهذا الدرس.")
            # Fetch questions to show count
            questions_endpoint = f"/api/v1/lessons/{scope_id}/questions"
            questions = fetch_from_api(questions_endpoint) 
            question_count = len(questions) if isinstance(questions, list) else 0
            
            text = f"📄 **{lesson_name}**\n\n{lesson_content}\n\n*عدد الأسئلة المتاحة:* {question_count}"
            # Need parent unit ID for back button
            parent_unit_id = context.user_data.get("parent_id") 
            back_button = InlineKeyboardButton("🔙 رجوع إلى قائمة الدروس", callback_data=f"info_back_to_unit_{parent_unit_id}") if parent_unit_id else InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="main_menu")
            keyboard = InlineKeyboardMarkup([[back_button]])
            await safe_edit_message_text(query, text=text, reply_markup=keyboard, parse_mode=\"Markdown\")
            return SHOW_INFO_DETAIL # Stay to allow going back
        else:
            logger.error(f"Failed to fetch lesson detail from API ({api_endpoint}) or invalid format.")
            error_message = "⚠️ حدث خطأ أثناء جلب تفاصيل الدرس."
            await safe_edit_message_text(query, text=error_message, reply_markup=create_main_menu_keyboard())
            return MAIN_MENU

    # Check API response for next level items
    if next_level_items is None or not isinstance(next_level_items, list):
        logger.error(f"Failed to fetch {next_scope_type}s from API ({api_endpoint}) or invalid format.")
        try:
            last_word = prompt_text.split(" ")[-1]
        except IndexError:
            last_word = "العناصر"
        error_message = f"⚠️ حدث خطأ أثناء جلب {last_word} من الـ API. قد تكون هناك مشكلة في الخادم ({api_endpoint}). يرجى المحاولة مرة أخرى لاحقاً."
        await safe_edit_message_text(query, text=error_message, reply_markup=create_main_menu_keyboard())
        return MAIN_MENU

    # If there are items for the next level, show them
    if next_level_items:
        context.user_data["scope_items"] = next_level_items # Store for pagination
        keyboard = create_info_scope_keyboard(next_scope_type, next_level_items, page=0, parent_id=scope_id)
        await safe_edit_message_text(query, text=prompt_text, reply_markup=keyboard)
        return INFO_MENU # Stay in this state for next level selection
    else:
        # No items found for the next level (e.g., course has no units)
        # Show info for the current level (e.g., whole course/unit)
        api_endpoint = f"/api/v1/{scope_level}s/{scope_id}" # e.g., /api/v1/courses/1
        item_detail = fetch_from_api(api_endpoint) 
        if item_detail and isinstance(item_detail, dict):
            # Corrected: Use 'id' from API response
            item_name = item_detail.get("name", f"{scope_level.capitalize()} {item_detail.get(\"id\")}")
            item_content = item_detail.get("description", f"لا يوجد وصف متاح لهذا {scope_level}.") # Assuming description field
            # Fetch questions to show count
            questions_endpoint = f"/api/v1/{scope_level}s/{scope_id}/questions"
            questions = fetch_from_api(questions_endpoint) 
            question_count = len(questions) if isinstance(questions, list) else 0
            
            text = f"📌 **{item_name}**\n\n{item_content}\n\n*عدد الأسئلة المتاحة:* {question_count}"
            # Need parent ID for back button
            parent_id = context.user_data.get("parent_id") 
            back_callback = "main_menu"
            if scope_level == "unit" and parent_id is not None:
                back_callback = f"info_back_to_course"
            # No back needed if showing course info directly
            
            back_button = InlineKeyboardButton("🔙 رجوع", callback_data=back_callback)
            keyboard = InlineKeyboardMarkup([[back_button]])
            await safe_edit_message_text(query, text=text, reply_markup=keyboard, parse_mode=\"Markdown\")
            return SHOW_INFO_DETAIL # Stay to allow going back
        else:
            logger.error(f"Failed to fetch {scope_level} detail from API ({api_endpoint}) or invalid format.")
            error_message = f"⚠️ حدث خطأ أثناء جلب تفاصيل {scope_level}."
            await safe_edit_message_text(query, text=error_message, reply_markup=create_main_menu_keyboard())
            return MAIN_MENU

async def handle_info_pagination(update: Update, context: CallbackContext) -> int:
    """Handles pagination for info scope selection."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"User {user_id} requested info pagination: {data}")
    parts = data.split("_")
    scope_type = parts[2]
    page = int(parts[3])
    parent_id = int(parts[4]) if len(parts) > 4 and parts[4] else None
    items = context.user_data.get("scope_items", [])
    if not items:
        logger.error("Info pagination requested but scope_items not found.")
        await safe_edit_message_text(query, text="حدث خطأ في التنقل بين الصفحات.", reply_markup=create_main_menu_keyboard())
        return MAIN_MENU
    context.user_data["current_page"] = page
    keyboard = create_info_scope_keyboard(scope_type, items, page=page, parent_id=parent_id)
    prompt_text = f"اختر {scope_type} لعرض معلوماته: (صفحة {page + 1})"
    if scope_type == "course": prompt_text = "📚 اختر المقرر الدراسي لعرض معلوماته:"
    elif scope_type == "unit": prompt_text = "📖 اختر الوحدة الدراسية لعرض معلوماتها:"
    elif scope_type == "lesson": prompt_text = "📄 اختر الدرس لعرض معلوماته:"
    await safe_edit_message_text(query, text=prompt_text, reply_markup=keyboard)
    return INFO_MENU

async def handle_info_back(update: Update, context: CallbackContext) -> int:
    """Handles back navigation in the info menu."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"User {user_id} requested info back navigation: {data}")
    context.user_data["current_page"] = 0 # Reset page on back

    if data == "main_menu":
        # This should be handled by the fallback in ConversationHandler
        # but we can explicitly call main_menu_callback if needed
        return await main_menu_callback(update, context)
    elif data == "info_back_to_course":
        # Fetch courses again from API
        courses = fetch_from_api("/api/v1/courses") 
        if courses is None or not isinstance(courses, list):
            logger.error("Failed to fetch courses on back navigation in info.")
            await safe_edit_message_text(query, text="⚠️ حدث خطأ أثناء جلب المقررات الدراسية. يرجى المحاولة مرة أخرى.", reply_markup=create_main_menu_keyboard())
            return MAIN_MENU
        context.user_data["scope_items"] = courses
        text = "📚 اختر المقرر الدراسي لعرض معلوماته:"
        keyboard = create_info_scope_keyboard("course", courses, page=0)
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return INFO_MENU
    elif data.startswith("info_back_to_unit_"):
        unit_id = int(data.split("_")[-1])
        # Need the course_id to fetch units again.
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
             logger.error(f"Could not determine parent course for unit {unit_id} on info back navigation.")
             await safe_edit_message_text(query, text="حدث خطأ أثناء الرجوع.", reply_markup=create_main_menu_keyboard())
             return MAIN_MENU

        units = fetch_from_api(f"/api/v1/courses/{parent_course_id}/units") 
        if units is None or not isinstance(units, list):
            logger.error(f"Failed to fetch units for course {parent_course_id} on info back navigation.")
            await safe_edit_message_text(query, text="⚠️ حدث خطأ أثناء جلب الوحدات الدراسية. يرجى المحاولة مرة أخرى.", reply_markup=create_main_menu_keyboard())
            return MAIN_MENU
        context.user_data["scope_items"] = units
        context.user_data["parent_id"] = parent_course_id # Set parent_id for unit keyboard
        text = "📖 اختر الوحدة الدراسية لعرض معلوماتها:"
        keyboard = create_info_scope_keyboard("unit", units, page=0, parent_id=parent_course_id)
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
        return INFO_MENU
    else:
        logger.warning(f"Unknown info back navigation: {data}")
        await safe_edit_message_text(query, text="حدث خطأ غير متوقع.", reply_markup=create_main_menu_keyboard())
        return MAIN_MENU

# --- Conversation Handler Setup --- 

info_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(info_menu, pattern="^show_info$")],
    states={
        INFO_MENU: [
            CallbackQueryHandler(select_info_scope, pattern="^info_scope_"),
            CallbackQueryHandler(handle_info_pagination, pattern="^info_page_"),
            CallbackQueryHandler(handle_info_back, pattern="^info_back_to_|^main_menu$"), # Handle back navigation
        ],
        SHOW_INFO_DETAIL: [
            CallbackQueryHandler(handle_info_back, pattern="^info_back_to_|^main_menu$") # Allow back from detail view
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
    # Added name and persistent=True for persistence
    name="info_conversation", 
    persistent=True 
)

