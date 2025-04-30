# -*- coding: utf-8 -*-
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler, CommandHandler, CallbackQueryHandler

# Import functions/constants from other modules
try:
    # INFO_MENU state constant is needed
    from info_menu_function import show_info_menu, INFO_MENU
except ImportError as e:
    logging.error(f"Failed to import from info_menu_function: {e}")
    # Define placeholder if import fails
    INFO_MENU = 23 # Assuming state 23 from previous context
    def show_info_menu(update: Update, context: CallbackContext) -> int:
        logging.error("Placeholder show_info_menu called!")
        if update.callback_query:
            update.callback_query.answer("Error: Info menu unavailable.")
            if update.callback_query.message:
                update.callback_query.message.reply_text("Error: Info menu unavailable.")
        return ConversationHandler.END

try:
    from helper_function import safe_edit_message_text
except ImportError as e:
    logging.error(f"Failed to import safe_edit_message_text from helper_function: {e}")
    # Define a dummy function to avoid NameError
    def safe_edit_message_text(query, text, reply_markup=None, parse_mode=None):
        logging.error("safe_edit_message_text is not available!")
        if query and query.message:
            try:
                query.edit_message_text(text="Error: Cannot display content correctly.")
            except Exception:
                 query.message.reply_text("Error: Cannot display content correctly.")

# --- Define MAIN_MENU state locally to break circular import ---
# This value MUST match the MAIN_MENU state value defined in bot.py
MAIN_MENU = 0

# Define logger
logger = logging.getLogger(__name__)

# Function to create the info menu keyboard
def create_info_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🧪 العناصر الكيميائية", callback_data='info_elements')],
        [InlineKeyboardButton("🔬 المركبات الكيميائية", callback_data='info_compounds')],
        [InlineKeyboardButton("📘 المفاهيم الكيميائية", callback_data='info_concepts')],
        [InlineKeyboardButton("📊 الجدول الدوري", callback_data='info_periodic_table')],
        [InlineKeyboardButton("🔢 الحسابات الكيميائية", callback_data='info_calculations')],
        [InlineKeyboardButton("🔗 الروابط الكيميائية", callback_data='info_bonds')],
        [InlineKeyboardButton("📜 أهم قوانين التحصيلي", callback_data='info_laws')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')],
    ]
    return InlineKeyboardMarkup(keyboard)

# Placeholder handlers for info menu options
def handle_info_elements(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    safe_edit_message_text(query, text="قسم العناصر الكيميائية قيد التطوير.", reply_markup=create_info_menu_keyboard())
    return INFO_MENU

def handle_info_compounds(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    safe_edit_message_text(query, text="قسم المركبات الكيميائية قيد التطوير.", reply_markup=create_info_menu_keyboard())
    return INFO_MENU

def handle_info_concepts(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    safe_edit_message_text(query, text="قسم المفاهيم الكيميائية قيد التطوير.", reply_markup=create_info_menu_keyboard())
    return INFO_MENU

def handle_info_periodic_table(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    safe_edit_message_text(query, text="قسم الجدول الدوري قيد التطوير.", reply_markup=create_info_menu_keyboard())
    return INFO_MENU

def handle_info_calculations(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    safe_edit_message_text(query, text="قسم الحسابات الكيميائية قيد التطوير.", reply_markup=create_info_menu_keyboard())
    return INFO_MENU

def handle_info_bonds(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    safe_edit_message_text(query, text="قسم الروابط الكيميائية قيد التطوير.", reply_markup=create_info_menu_keyboard())
    return INFO_MENU

def handle_info_laws(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    try:
        with open("chemistry_laws_content.md", "r", encoding="utf-8") as f:
            laws_content = f.read()
        safe_edit_message_text(query, text=laws_content, reply_markup=create_info_menu_keyboard(), parse_mode='Markdown')
    except FileNotFoundError:
        logger.error("Chemistry laws content file (chemistry_laws_content.md) not found.")
        safe_edit_message_text(query, text="عذراً، حدث خطأ أثناء تحميل محتوى قوانين الكيمياء.", reply_markup=create_info_menu_keyboard())
    except Exception as e:
        logger.error(f"Error loading/sending chemistry laws content: {e}")
        safe_edit_message_text(query, text="عذراً، حدث خطأ غير متوقع.", reply_markup=create_info_menu_keyboard())

    return INFO_MENU

# Combined handler for info menu callbacks
def info_menu_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer() # Answer callback query first
    data = query.data
    user_id = query.from_user.id
    logger.info(f"User {user_id} chose {data} from info menu.")

    if data == 'info_elements':
        return handle_info_elements(update, context)
    elif data == 'info_compounds':
        return handle_info_compounds(update, context)
    elif data == 'info_concepts':
        return handle_info_concepts(update, context)
    elif data == 'info_periodic_table':
        return handle_info_periodic_table(update, context)
    elif data == 'info_calculations':
        return handle_info_calculations(update, context)
    elif data == 'info_bonds':
        return handle_info_bonds(update, context)
    elif data == 'info_laws':
        return handle_info_laws(update, context)
    elif data == 'main_menu':
        logger.info("Returning state MAIN_MENU from info menu.")
        # Simply return the MAIN_MENU state. The main handler in bot.py will catch this.
        # We need to ensure the message is updated *before* returning the state
        # Let the main_menu_callback in bot.py handle the message editing.
        return MAIN_MENU
    else:
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_info_menu_keyboard())
        return INFO_MENU # Stay in info menu

# --- Define the ConversationHandler --- #
# Note: The entry point pattern should match the callback_data in bot.py's main menu
info_menu_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(show_info_menu, pattern='^menu_info$')], # Matches 'menu_info' from main menu keyboard
    states={
        INFO_MENU: [
            CallbackQueryHandler(info_menu_callback) # Handles buttons within the info menu
        ],
    },
    fallbacks=[
        # Removed CommandHandler('start', main_menu_callback) as the main dispatcher should handle /start
        # Returning MAIN_MENU state should be handled by the main application structure
    ],
    # Allow re-entry into this conversation if needed
    allow_reentry=True
)

