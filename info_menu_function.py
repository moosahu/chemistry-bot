import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler

# Assuming helper_function.py is in the same directory
# If safe_edit_message_text is not found, this will raise an ImportError later
try:
    from helper_function import safe_edit_message_text
except ImportError:
    # Fallback or log error if helper_function is critical and missing
    logging.error("Failed to import safe_edit_message_text from helper_function.py")
    # Define a dummy function to avoid NameError, but log loudly
    def safe_edit_message_text(query, text, reply_markup=None, parse_mode=None):
        logging.error("safe_edit_message_text is not available!")
        if query:
            query.message.reply_text("Error: Cannot display menu correctly.")

# Get logger instance
logger = logging.getLogger(__name__)

# Define state constant locally to avoid circular import
# This value MUST match the value assigned in bot.py (range(24))
INFO_MENU = 23

def show_info_menu(update: Update, context: CallbackContext) -> int:
    """عرض قائمة المعلومات الكيميائية."""
    query = update.callback_query
    # Answer the callback query to remove the "loading" state
    if query:
        query.answer()

    logger.info("Showing info menu")
    keyboard = [
        [InlineKeyboardButton("🧪 العناصر الكيميائية", callback_data='info_elements')],
        [InlineKeyboardButton("🔬 المركبات الكيميائية", callback_data='info_compounds')],
        [InlineKeyboardButton("📘 المفاهيم الكيميائية", callback_data='info_concepts')],
        [InlineKeyboardButton("📊 الجدول الدوري", callback_data='info_periodic_table')],
        [InlineKeyboardButton("🔢 الحسابات الكيميائية", callback_data='info_calculations')],
        [InlineKeyboardButton("🔗 الروابط الكيميائية", callback_data='info_bonds')],
        # Added new button for Achievement Test Laws
        [InlineKeyboardButton("📜 أهم قوانين التحصيلي", callback_data='info_laws')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='main_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = "📚 اختر نوع المعلومات الكيميائية:"

    # Edit the message if it came from a callback query, otherwise send a new message
    if query:
        safe_edit_message_text(query, text=text, reply_markup=reply_markup)
    elif update.message:
        update.message.reply_text(text, reply_markup=reply_markup)
    else:
        logger.warning("show_info_menu called without query or message")
        # Cannot reliably return to a state without update object
        # Returning END might terminate the whole conversation unexpectedly.
        # Let the ConversationHandler handle the fallback.
        return ConversationHandler.END # Or return a default state if safer

    return INFO_MENU # Stay in the info menu state

