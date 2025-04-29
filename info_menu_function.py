
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
        return ConversationHandler.END # Or handle appropriately
        
    return INFO_MENU # Stay in the info menu state


