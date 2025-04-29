import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

# Assuming these are defined/imported in the main bot file or globally
# from helper_function import safe_edit_message_text
# from bot_states import INFO_MENU # Or however states are defined

# Define logger if not already defined globally
logger = logging.getLogger(__name__)

# Placeholder handlers for info menu options
def handle_info_elements(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    safe_edit_message_text(query, text="قسم العناصر الكيميائية قيد التطوير.", reply_markup=create_info_menu_keyboard()) # Need to create this keyboard func
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
        # Read content from the markdown file
        with open("/home/ubuntu/chemistry_laws_content.md", "r", encoding="utf-8") as f:
            laws_content = f.read()
        # Display the content using Markdown formatting
        safe_edit_message_text(query, text=laws_content, reply_markup=create_info_menu_keyboard(), parse_mode='Markdown')
    except FileNotFoundError:
        logger.error("Chemistry laws content file not found.")
        safe_edit_message_text(query, text="عذراً، حدث خطأ أثناء تحميل محتوى قوانين الكيمياء.", reply_markup=create_info_menu_keyboard())
    except Exception as e:
        logger.error(f"Error loading/sending chemistry laws content: {e}")
        safe_edit_message_text(query, text="عذراً، حدث خطأ غير متوقع.", reply_markup=create_info_menu_keyboard())

    return INFO_MENU

# Function to create the info menu keyboard (similar to show_info_menu but just the keyboard part)
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

# Combined handler for info menu callbacks
def info_menu_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    logger.info(f"User {user_id} chose {data} from info menu.")

    # Need to ensure safe_edit_message_text and main_menu_callback are accessible here
    # Assuming they are imported/defined in the main script
    global safe_edit_message_text, main_menu_callback, INFO_MENU

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
        # Go back to main menu handler
        # Ensure main_menu_callback is correctly imported/defined and returns the appropriate state
        return main_menu_callback(update, context)
    else:
        query.answer("خيار غير معروف")
        return INFO_MENU # Stay in info menu

