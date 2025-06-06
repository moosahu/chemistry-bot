# -*- coding: utf-8 -*-
"""Conversation handler for browsing chemical information."""

import logging
import os # Added for path joining for laws.md
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler
)

# Import necessary components from other modules
try:
    from config import logger, MAIN_MENU, INFO_MENU, SHOW_INFO_DETAIL
    from utils.helpers import safe_send_message, safe_edit_message_text, process_text_with_chemical_notation
    from handlers.common import main_menu_callback # For returning to main menu (ensure it"s async)
    # Import content data
    from content.data import ELEMENTS, COMPOUNDS, CONCEPTS, PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO
except ImportError as e:
    # Fallback for potential import issues
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error(f"Error importing modules in handlers.info: {e}. Using placeholders.")
    # Define placeholders
    MAIN_MENU, INFO_MENU, SHOW_INFO_DETAIL = 0, 7, 9 # Match config.py
    async def safe_send_message(*args, **kwargs): logger.error("Placeholder safe_send_message called!")
    async def safe_edit_message_text(*args, **kwargs): logger.error("Placeholder safe_edit_message_text called!")
    def process_text_with_chemical_notation(text): logger.warning("Placeholder process_text_with_chemical_notation called!"); return text
    async def main_menu_callback(*args, **kwargs): logger.error("Placeholder main_menu_callback called!"); return MAIN_MENU
    ELEMENTS, COMPOUNDS, CONCEPTS = {}, {}, {}
    PERIODIC_TABLE_INFO, CHEMICAL_CALCULATIONS_INFO, CHEMICAL_BONDS_INFO = "", "", ""

# --- Constants --- 
INFO_CATEGORIES = {
    "elements": "عناصر كيميائية",
    "compounds": "مركبات شائعة",
    "concepts": "مفاهيم أساسية",
    "laws": "قوانين كيميائية",
    "periodic_table": "الجدول الدوري",
    "calculations": "حسابات كيميائية",
    "bonds": "روابط كيميائية"
}

# --- Helper Functions --- 

def create_info_menu_keyboard() -> InlineKeyboardMarkup:
    """Creates the main keyboard for the information section."""
    keyboard = [
        [InlineKeyboardButton(INFO_CATEGORIES["elements"], callback_data="info_cat_elements")],
        [InlineKeyboardButton(INFO_CATEGORIES["compounds"], callback_data="info_cat_compounds")],
        [InlineKeyboardButton(INFO_CATEGORIES["concepts"], callback_data="info_cat_concepts")],
        [InlineKeyboardButton(INFO_CATEGORIES["laws"], callback_data="info_cat_laws")],
        [InlineKeyboardButton(INFO_CATEGORIES["periodic_table"], callback_data="info_cat_periodic_table")],
        [InlineKeyboardButton(INFO_CATEGORIES["calculations"], callback_data="info_cat_calculations")],
        [InlineKeyboardButton(INFO_CATEGORIES["bonds"], callback_data="info_cat_bonds")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_info_detail_keyboard(category: str) -> InlineKeyboardMarkup:
    """Creates a keyboard with items for a specific category (e.g., list of elements)."""
    keyboard = []
    items = []
    callback_prefix = f"info_detail_{category}_"

    if category == "elements":
        items = list(ELEMENTS.keys())
    elif category == "compounds":
        items = list(COMPOUNDS.keys())
    elif category == "concepts":
        items = list(CONCEPTS.keys())
    
    for item_name in items:
        keyboard.append([InlineKeyboardButton(item_name, callback_data=f"{callback_prefix}{item_name}")])

    keyboard.append([InlineKeyboardButton("🔙 رجوع لقائمة المعلومات", callback_data="info_menu")])
    return InlineKeyboardMarkup(keyboard)

# --- Conversation Steps (Converted to async) --- 

async def info_menu(update: Update, context: CallbackContext) -> int:
    """Displays the main information categories menu."""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if query:
        await query.answer()
        logger.info(f"User {user_id} entered info menu.")
        text = "📚 اختر فئة المعلومات التي تريد استعراضها:"
        keyboard = create_info_menu_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=text, reply_markup=keyboard)
    else:
        logger.warning("info_menu called without callback query.")
        text = "📚 اختر فئة المعلومات التي تريد استعراضها:"
        keyboard = create_info_menu_keyboard()
        await safe_send_message(context.bot, update.effective_chat.id, text=text, reply_markup=keyboard)
        
    return INFO_MENU

async def select_info_category(update: Update, context: CallbackContext) -> int:
    """Handles selection of an information category."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"User {user_id} selected info category: {data}")

    category = data.split("_")[-1]
    context.user_data["current_info_category"] = category

    if category in ["elements", "compounds", "concepts"]:
        text = f"اختر {INFO_CATEGORIES.get(category, category)}:"
        keyboard = create_info_detail_keyboard(category)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=text, reply_markup=keyboard)
        return SHOW_INFO_DETAIL
    else:
        content = ""
        if category == "periodic_table":
            content = PERIODIC_TABLE_INFO
        elif category == "calculations":
            content = CHEMICAL_CALCULATIONS_INFO
        elif category == "bonds":
            content = CHEMICAL_BONDS_INFO
        elif category == "laws":
            try:
                laws_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "content", "laws.md")
                with open(laws_file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except FileNotFoundError:
                logger.error(f"laws.md file not found at {laws_file_path}")
                content = "عذراً، لم يتم العثور على ملف قوانين الكيمياء."
            except Exception as e:
                logger.exception(f"Error reading laws.md: {e}")
                content = "عذراً، حدث خطأ أثناء قراءة ملف القوانين."
        else:
            content = "محتوى غير متوفر لهذه الفئة."
            logger.warning(f"No direct content defined for info category: {category}")

        formatted_content = process_text_with_chemical_notation(content)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لقائمة المعلومات", callback_data="info_menu")]])
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=formatted_content, reply_markup=keyboard, parse_mode="Markdown")
        return INFO_MENU

async def show_info_detail(update: Update, context: CallbackContext) -> int:
    """Handles selection of a specific item (element, compound, concept)."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"User {user_id} selected info detail: {data}")

    try:
        parts = data.split("_")
        category = parts[2]
        item_name = "_".join(parts[3:]) # Handles item names with underscores
    except (IndexError, ValueError):
        logger.error(f"Invalid info detail callback data format: {data}")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ في البيانات. الرجاء المحاولة مرة أخرى.", reply_markup=create_info_menu_keyboard())
        return INFO_MENU

    content = ""
    if category == "elements" and item_name in ELEMENTS:
        details = ELEMENTS[item_name]
        symbol = details.get("رمز", "N/A")
        atomic_number = details.get("رقم_ذري", "N/A")
        atomic_weight = details.get("وزن_ذري", "N/A")
        content = f"*{item_name} ({symbol})*\n\n- الرقم الذري: {atomic_number}\n- الوزن الذري: {atomic_weight}"
    elif category == "compounds" and item_name in COMPOUNDS:
        details = COMPOUNDS[item_name]
        formula_raw = details.get("صيغة", "N/A")
        formula = process_text_with_chemical_notation(formula_raw)
        compound_type = details.get("نوع", "N/A")
        state_stp = details.get("حالة", "N/A")
        content = f"*{item_name} ({formula})*\n\n- النوع: {compound_type}\n- الحالة (STP): {state_stp}"
    elif category == "concepts" and item_name in CONCEPTS:
        concept_detail = CONCEPTS.get(item_name, "المعلومات غير متوفرة لهذا المفهوم.")
        content = f"*{item_name}*\n\n{concept_detail}"
    else:
        # Line 185 area: Safely construct the string to avoid "unterminated string literal"
        part1 = "عذراً، لم يتم العثور على تفاصيل لـ \n`"
        part2 = str(item_name) # Ensure item_name is string
        part3 = "`\n في فئة \n`"
        part4 = str(category)  # Ensure category is string
        part5 = "`\n."
        content = part1 + part2 + part3 + part4 + part5
        # Original logger line, should be fine as it's a separate f-string.
        logger.warning(f"Details not found for item \n{item_name}\n in category \n{category}\n.")

    formatted_content = process_text_with_chemical_notation(content)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(f"🔙 رجوع إلى {INFO_CATEGORIES.get(category, category)}", callback_data=f"info_cat_{category}")]])
    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=formatted_content, reply_markup=keyboard, parse_mode="Markdown")
    
    return SHOW_INFO_DETAIL

# --- Conversation Handler Definition --- 

info_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(info_menu, pattern="^menu_info$")],
    states={
        INFO_MENU: [
            CallbackQueryHandler(select_info_category, pattern="^info_cat_"),
            CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")
        ],
        SHOW_INFO_DETAIL: [
            CallbackQueryHandler(show_info_detail, pattern="^info_detail_"),
            CallbackQueryHandler(select_info_category, pattern="^info_cat_"), # Allow going back to category list
            CallbackQueryHandler(info_menu, pattern="^info_menu$") # Allow going back to main info menu
        ],
    },
    fallbacks=[
        CommandHandler("start", main_menu_callback),
        CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"),
        CallbackQueryHandler(info_menu, pattern=".*") # Default to info_menu if no other match
    ],
    map_to_parent={
        MAIN_MENU: ConversationHandler.END,
    },
    persistent=True,
    name="info_conversation"
)


