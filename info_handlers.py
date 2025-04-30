import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler, CommandHandler, CallbackQueryHandler

# Import functions/constants from other modules
try:
    from info_menu_function import show_info_menu, INFO_MENU # INFO_MENU = 23 (defined in info_menu_function)
except ImportError as e:
    logging.error(f"Failed to import from info_menu_function: {e}")
    # Define placeholder if import fails
    INFO_MENU = 23
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
                # Try editing existing message if possible
                query.edit_message_text(text="Error: Cannot display content correctly.")
            except Exception:
                 # Fallback to replying if edit fails
                 query.message.reply_text("Error: Cannot display content correctly.")
        # Cannot reply if query.message is None

# Import main_menu_callback carefully - potential circular import if bot.py imports this file
try:
    # Assuming main_menu_callback is defined in bot.py and returns MAIN_MENU state
    # Also assuming MAIN_MENU state value is defined there (e.g., 0)
    from bot import main_menu_callback, MAIN_MENU
except ImportError as e:
    logging.error(f"Could not import main_menu_callback or MAIN_MENU from bot.py: {e}. Using placeholders.")
    # Define placeholders if import fails
    MAIN_MENU = 0 # Assuming state 0 for main menu
    def main_menu_callback(update: Update, context: CallbackContext) -> int:
        logging.error("Placeholder main_menu_callback called!")
        text_to_send = "Error: Cannot return to main menu properly."
        if update.message:
            update.message.reply_text(text_to_send)
        elif update.callback_query:
            # Try to edit the message from the callback query
            safe_edit_message_text(update.callback_query, text=text_to_send)
        return ConversationHandler.END # End this conversation as a fallback

# Define logger
logger = logging.getLogger(__name__)

# Function to create the info menu keyboard
def create_info_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🧪 العناصر الكيميائية", callback_data=\'info_elements\')],
        [InlineKeyboardButton("🔬 المركبات الكيميائية", callback_data=\'info_compounds\')],
        [InlineKeyboardButton("📘 المفاهيم الكيميائية", callback_data=\'info_concepts\')],
        [InlineKeyboardButton("📊 الجدول الدوري", callback_data=\'info_periodic_table\')],
        [InlineKeyboardButton("🔢 الحسابات الكيميائية", callback_data=\'info_calculations\')],
        [InlineKeyboardButton("🔗 الروابط الكيميائية", callback_data=\'info_bonds\')],
        [InlineKeyboardButton("📜 أهم قوانين التحصيلي", callback_data=\'info_laws\')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=\'main_menu\')],
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
        # Read content from the markdown file (assuming it's in the root directory on Heroku)
        with open("chemistry_laws_content.md", "r", encoding="utf-8") as f:
            laws_content = f.read()
        # Display the content using Markdown formatting
        safe_edit_message_text(query, text=laws_content, reply_markup=create_info_menu_keyboard(), parse_mode=\'Markdown\')
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

    if data == \'info_elements\':
        return handle_info_elements(update, context)
    elif data == \'info_compounds\':
        return handle_info_compounds(update, context)
    elif data == \'info_concepts\':
        return handle_info_concepts(update, context)
    elif data == \'info_periodic_table\':
        return handle_info_periodic_table(update, context)
    elif data == \'info_calculations\':
        return handle_info_calculations(update, context)
    elif data == \'info_bonds\':
        return handle_info_bonds(update, context)
    elif data == \'info_laws\':
        return handle_info_laws(update, context)
    elif data == \'main_menu\':
        logger.info("Attempting to return to main menu from info menu.")
        try:
            # Call main_menu_callback to display the main menu and return its state
            return main_menu_callback(update, context) # Should return MAIN_MENU state (e.g., 0)
        except Exception as e:
            logger.error(f"Failed to transition back to main menu via main_menu_callback: {e}")
            # Fallback: end the current conversation
            safe_edit_message_text(query, text="Returning to start...") # Inform user
            return ConversationHandler.END
    else:
        # query.answer("خيار غير معروف") # Already answered above
        safe_edit_message_text(query, text="خيار غير معروف.", reply_markup=create_info_menu_keyboard())
        return INFO_MENU # Stay in info menu

# --- Define the ConversationHandler --- #
info_menu_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(show_info_menu, pattern=\'^info_menu$\')], # Triggered by 'info_menu' button callback
    states={
        INFO_MENU: [
            CallbackQueryHandler(info_menu_callback) # Handles buttons within the info menu
        ],
        # No other states defined within this specific handler
    },
    fallbacks=[
        CommandHandler(\'start\', main_menu_callback), # Go back to main menu on /start
        # Add other potential fallbacks like /cancel if needed
        # CallbackQueryHandler(main_menu_callback, pattern='^main_menu$') # Alternative way to handle main_menu button if needed as fallback
        ],
    # Assuming this handler is added directly to the dispatcher in bot.py,
    # returning MAIN_MENU from info_menu_callback (via main_menu_callback) should transition
    # control back to the main handler if it handles the MAIN_MENU state.
    # Returning ConversationHandler.END will terminate this conversation flow.
)

