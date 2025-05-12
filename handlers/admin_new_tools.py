# admin_interface_v15_admin_tools.py
# This file will integrate with manager_v17_admin_tools.py
# and implement the admin-specific UI and command handlers.

import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler)

# Assuming DB_MANAGER is instantiated and available, similar to admin_interface_v14_caption_fix.py
# from manager_v17_admin_tools import DB_MANAGER # This would be how it's imported in a real setup

# Placeholder for DB_MANAGER if running standalone for syntax check
class DBMock:
    def is_user_admin(self, user_id): return True # Assume admin for testing UI flow
    def get_system_message(self, key): return f"نص افتراضي لـ {key}"
    def update_system_message(self, key, text, is_initial_setup=False): logging.info(f"SYSTEM MSG UPDATED: {key} = {text}")
    def get_all_editable_message_keys(self): return [{'key': 'welcome_new_user', 'description': 'رسالة الترحيب بالجدد'}, {'key': 'help_command_message', 'description': 'رسالة المساعدة (/help)'}]
    def get_all_active_user_ids(self): return [123, 456] # Dummy user IDs

# DB_MANAGER = DBMock() # Use mock for dev if manager is not directly runnable here
# In a real scenario, DB_MANAGER would be the actual instance from manager_v17_admin_tools.py

# States for ConversationHandler (for editing messages and broadcasting)
EDIT_MESSAGE_TEXT, BROADCAST_MESSAGE_TEXT, BROADCAST_CONFIRM = range(3)

# --- Helper Functions (if any, or directly in handlers) ---
async def check_admin_privileges(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    # In real use: if not DB_MANAGER.is_user_admin(user_id):
    if not context.bot_data.get("DB_MANAGER").is_user_admin(user_id):
        await update.message.reply_text("هذه الأوامر مخصصة للأدمن فقط.") if update.message else None
        if update.callback_query:
            await update.callback_query.answer("هذه الأوامر مخصصة للأدمن فقط.", show_alert=True)
        return False
    return True

# --- Command Handasync def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    logger = logging.getLogger(__name__) # Ensure logger is available

    db_manager = context.bot_data.get("DB_MANAGER")

    if db_manager is None:
        logger.error("DB_MANAGER is None in start_command. Admin tools database component might not be ready.")
        await update.message.reply_text("عذراً، يبدو أن مكون قاعدة بيانات أدوات الإدارة غير جاهز حالياً. يرجى المحاولة مرة أخرى لاحقاً أو الاتصال بمسؤول البوت إذا استمرت المشكلة.")
        return

    # In real use: db_manager.add_user_if_not_exists(user_id, user.username, user.first_name, user.last_name)
    # For now, let's assume user is added or this is handled elsewhere if needed for start_command.

    welcome_message_key = "welcome_new_user"
    try:
        welcome_text = db_manager.get_system_message(welcome_message_key) or f"مرحباً بك يا {{user.first_name}}!"
    except Exception as e:
        logger.error(f"Error getting system message 
{welcome_message_key}
 from DB_MANAGER: {e}")
        welcome_text = f"مرحباً بك يا {{user.first_name}}! (رسالة ترحيب افتراضية بسبب خطأ في النظام)"
        
    welcome_text = welcome_text.replace("{user.first_name}", user.first_name or "مستخدمنا العزيز")

    keyboard = [
        [InlineKeyboardButton("🧠 بدء اختبار جديد", callback_data=
start_quiz
)],
        [InlineKeyboardButton("📚 معلومات كيميائية", callback_data=
chemical_info
)],
        [InlineKeyboardButton("📊 إحصائياتي ولوحة الصدارة", callback_data=
my_stats_leaderboard
)],
        [InlineKeyboardButton("ℹ️ حول البوت", callback_data=
show_about_bot
)],
    ]

    try:
        if db_manager.is_user_admin(user_id):
            keyboard.append([InlineKeyboardButton("⚙️ لوحة تحكم الأدمن", callback_data=
admin_show_tools_menu
)])
    except Exception as e:
        logger.error(f"Error checking admin status for user {user_id}: {e}. Admin button may not be shown.")

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)
async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    about_text = context.bot_data.get("DB_MANAGER").get_system_message('about_bot_message') or "انا بوت كيمياء تحصيلي لمساعدتك."
    await update.message.reply_text(about_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = context.bot_data.get("DB_MANAGER").get_system_message('help_command_message') or "استخدم الأزرار للتفاعل معي."
    await update.message.reply_text(help_text)

# --- Admin Tools UI and Logic ---
async def admin_show_tools_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context): return

    keyboard = [
        [InlineKeyboardButton("✏️ تعديل رسالة حول البوت", callback_data='admin_edit_specific_msg_about_bot_message')],
        [InlineKeyboardButton("📝 تعديل رسائل أخرى للبوت", callback_data='admin_edit_other_messages_menu')],
        [InlineKeyboardButton("📣 إرسال إشعار عام للمستخدمين", callback_data='admin_broadcast_start')],
        [InlineKeyboardButton("📊 عرض لوحة الإحصائيات", callback_data='stats_admin_panel_v4')], # Assuming this exists from previous stats work
        [InlineKeyboardButton("⬅️ عودة إلى القائمة الرئيسية", callback_data='admin_back_to_start')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text="🛠️ أدوات إدارة البوت:", reply_markup=reply_markup)

async def admin_back_to_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    # Simplified start message regeneration, ideally call a function that generates start message and keyboard
    welcome_message_key = "welcome_new_user"
    welcome_text = context.bot_data.get("DB_MANAGER").get_system_message(welcome_message_key) or f"مرحباً بك يا {user.first_name}!"
    welcome_text = welcome_text.replace("{user.first_name}", user.first_name or "مستخدمنا العزيز")
    keyboard = [
        [InlineKeyboardButton("🧠 بدء اختبار جديد", callback_data='start_quiz')],
        [InlineKeyboardButton("📚 معلومات كيميائية", callback_data='chemical_info')],
        [InlineKeyboardButton("📊 إحصائياتي ولوحة الصدارة", callback_data='my_stats_leaderboard')],
        [InlineKeyboardButton("ℹ️ حول البوت", callback_data='show_about_bot')],
    ]
    if context.bot_data.get("DB_MANAGER").is_user_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ لوحة تحكم الأدمن", callback_data='admin_show_tools_menu')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await query.edit_message_text(welcome_text, reply_markup=reply_markup)
    except Exception as e:
        logging.error(f"Error editing message for back to start: {e}")
        # Fallback if edit fails (e.g. message too old)
        await context.bot.send_message(chat_id=user.id, text=welcome_text, reply_markup=reply_markup)

# --- Edit System Messages --- 
async def admin_edit_specific_message_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context): return ConversationHandler.END

    message_key = query.data.split('_')[-1] # e.g., 'admin_edit_specific_msg_about_bot_message' -> 'about_bot_message'
    context.user_data['editing_message_key'] = message_key
    
    current_text = context.bot_data.get("DB_MANAGER").get_system_message(message_key) or "لا يوجد نص حالي."
    await query.edit_message_text(f"النص الحالي لـ '{message_key}':\n\n{current_text}\n\nالرجاء إرسال النص الجديد. لإلغاء العملية، أرسل /cancel_edit.")
    return EDIT_MESSAGE_TEXT

async def admin_edit_other_messages_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context): return

    editable_messages = context.bot_data.get("DB_MANAGER").get_all_editable_message_keys()
    keyboard = []
    if not editable_messages:
        await query.edit_message_text("لا توجد رسائل أخرى قابلة للتعديل حالياً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ عودة", callback_data='admin_show_tools_menu')]]))
        return

    for msg_info in editable_messages:
        keyboard.append([InlineKeyboardButton(msg_info['description'], callback_data=f"admin_edit_specific_msg_{msg_info['key']}")])
    keyboard.append([InlineKeyboardButton("⬅️ عودة إلى أدوات الإدارة", callback_data='admin_show_tools_menu')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("اختر الرسالة التي ترغب بتعديلها:", reply_markup=reply_markup)

async def received_new_message_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_admin_privileges(update, context): return ConversationHandler.END
    
    new_text = update.message.text
    message_key = context.user_data.get('editing_message_key')

    if not message_key:
        await update.message.reply_text("حدث خطأ، لم يتم تحديد الرسالة المراد تعديلها. يرجى المحاولة مرة أخرى.")
        return ConversationHandler.END

    context.bot_data.get("DB_MANAGER").update_system_message(message_key, new_text)
    await update.message.reply_text(f"تم تحديث الرسالة '{message_key}' بنجاح!")
    
    del context.user_data['editing_message_key']
    # Show admin tools menu again
    keyboard = [
        [InlineKeyboardButton("✏️ تعديل رسالة حول البوت", callback_data='admin_edit_specific_msg_about_bot_message')],
        [InlineKeyboardButton("📝 تعديل رسائل أخرى للبوت", callback_data='admin_edit_other_messages_menu')],
        [InlineKeyboardButton("📣 إرسال إشعار عام للمستخدمين", callback_data='admin_broadcast_start')],
        [InlineKeyboardButton("📊 عرض لوحة الإحصائيات", callback_data='stats_admin_panel_v4')], 
        [InlineKeyboardButton("⬅️ عودة إلى القائمة الرئيسية", callback_data='admin_back_to_start')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text="🛠️ أدوات إدارة البوت:", reply_markup=reply_markup)
    return ConversationHandler.END

async def cancel_edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if 'editing_message_key' in context.user_data:
        del context.user_data['editing_message_key']
    await update.message.reply_text("تم إلغاء عملية تعديل الرسالة.")
    # Show admin tools menu again
    keyboard = [
        [InlineKeyboardButton("✏️ تعديل رسالة حول البوت", callback_data='admin_edit_specific_msg_about_bot_message')],
        [InlineKeyboardButton("📝 تعديل رسائل أخرى للبوت", callback_data='admin_edit_other_messages_menu')],
        [InlineKeyboardButton("📣 إرسال إشعار عام للمستخدمين", callback_data='admin_broadcast_start')],
        [InlineKeyboardButton("📊 عرض لوحة الإحصائيات", callback_data='stats_admin_panel_v4')], 
        [InlineKeyboardButton("⬅️ عودة إلى القائمة الرئيسية", callback_data='admin_back_to_start')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text="🛠️ أدوات إدارة البوت:", reply_markup=reply_markup)
    return ConversationHandler.END

# --- Broadcast Feature ---
async def admin_broadcast_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context): return ConversationHandler.END

    await query.edit_message_text("الرجاء إرسال نص الإشعار الذي تود إرساله لجميع المستخدمين. للإلغاء، أرسل /cancel_broadcast.")
    return BROADCAST_MESSAGE_TEXT

async def received_broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_admin_privileges(update, context): return ConversationHandler.END

    broadcast_text = update.message.text
    context.user_data['broadcast_text'] = broadcast_text

    keyboard = [
        [InlineKeyboardButton("نعم، إرسال", callback_data='admin_broadcast_confirm')],
        [InlineKeyboardButton("لا، إلغاء", callback_data='admin_broadcast_cancel')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"نص الإشعار:\n\n{broadcast_text}\n\nهل أنت متأكد أنك تريد إرسال هذا الإشعار؟", reply_markup=reply_markup)
    return BROADCAST_CONFIRM

async def admin_broadcast_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not await check_admin_privileges(update, context): return ConversationHandler.END

    broadcast_text = context.user_data.get('broadcast_text')
    if not broadcast_text:
        await query.edit_message_text("حدث خطأ: لم يتم العثور على نص الإشعار. يرجى المحاولة مرة أخرى.")
        return ConversationHandler.END

    await query.edit_message_text("جاري إرسال الإشعار... قد يستغرق هذا بعض الوقت.")
    
    user_ids = context.bot_data.get("DB_MANAGER").get_all_active_user_ids()
    sent_count = 0
    failed_count = 0

    for user_id in user_ids:
        try:
            await context.bot.send_message(chat_id=user_id, text=broadcast_text)
            sent_count += 1
            # Consider adding a small delay here if dealing with many users to avoid rate limits
            # await asyncio.sleep(0.1) 
        except Exception as e:
            logging.warning(f"Failed to send broadcast to {user_id}: {e}")
            failed_count += 1
    
    await query.message.reply_text(f"اكتمل الإرسال.\nتم الإرسال بنجاح إلى: {sent_count} مستخدم.\nفشل الإرسال لـ: {failed_count} مستخدم.")
    
    del context.user_data['broadcast_text']
    # Show admin tools menu again
    keyboard = [
        [InlineKeyboardButton("✏️ تعديل رسالة حول البوت", callback_data='admin_edit_specific_msg_about_bot_message')],
        [InlineKeyboardButton("📝 تعديل رسائل أخرى للبوت", callback_data='admin_edit_other_messages_menu')],
        [InlineKeyboardButton("📣 إرسال إشعار عام للمستخدمين", callback_data='admin_broadcast_start')],
        [InlineKeyboardButton("📊 عرض لوحة الإحصائيات", callback_data='stats_admin_panel_v4')], 
        [InlineKeyboardButton("⬅️ عودة إلى القائمة الرئيسية", callback_data='admin_back_to_start')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(text="🛠️ أدوات إدارة البوت:", reply_markup=reply_markup)
    return ConversationHandler.END

async def admin_broadcast_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if 'broadcast_text' in context.user_data:
        del context.user_data['broadcast_text']
    await query.edit_message_text("تم إلغاء إرسال الإشعار.")
    # Show admin tools menu again
    keyboard = [
        [InlineKeyboardButton("✏️ تعديل رسالة حول البوت", callback_data='admin_edit_specific_msg_about_bot_message')],
        [InlineKeyboardButton("📝 تعديل رسائل أخرى للبوت", callback_data='admin_edit_other_messages_menu')],
        [InlineKeyboardButton("📣 إرسال إشعار عام للمستخدمين", callback_data='admin_broadcast_start')],
        [InlineKeyboardButton("📊 عرض لوحة الإحصائيات", callback_data='stats_admin_panel_v4')], 
        [InlineKeyboardButton("⬅️ عودة إلى القائمة الرئيسية", callback_data='admin_back_to_start')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(text="🛠️ أدوات إدارة البوت:", reply_markup=reply_markup)
    return ConversationHandler.END

async def cancel_broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if 'broadcast_text' in context.user_data:
        del context.user_data['broadcast_text']
    await update.message.reply_text("تم إلغاء عملية إرسال الإشعار.")
    # Show admin tools menu again
    keyboard = [
        [InlineKeyboardButton("✏️ تعديل رسالة حول البوت", callback_data='admin_edit_specific_msg_about_bot_message')],
        [InlineKeyboardButton("📝 تعديل رسائل أخرى للبوت", callback_data='admin_edit_other_messages_menu')],
        [InlineKeyboardButton("📣 إرسال إشعار عام للمستخدمين", callback_data='admin_broadcast_start')],
        [InlineKeyboardButton("📊 عرض لوحة الإحصائيات", callback_data='stats_admin_panel_v4')], 
        [InlineKeyboardButton("⬅️ عودة إلى القائمة الرئيسية", callback_data='admin_back_to_start')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text="🛠️ أدوات إدارة البوت:", reply_markup=reply_markup)
    return ConversationHandler.END

# This is a placeholder for where the main bot application would be built
# and handlers added. For a complete bot, you'd integrate this with other handlers.
# Example of how to set up (incomplete, needs actual ApplicationBuilder):
# if __name__ == '__main__':
#     logging.basicConfig(level=logging.INFO)
#     # Replace with your actual bot token
#     # BOT_TOKEN = "YOUR_BOT_TOKEN"
#     # application = Application.builder().token(BOT_TOKEN).build()

#     # # Store DB_MANAGER in bot_data for access in handlers
#     # application.bot_data["DB_MANAGER"] = DBMock() # Or the real DB_MANAGER

#     # # Conversation handler for editing messages
#     # edit_message_conv_handler = ConversationHandler(
#     #     entry_points=[
#     #         CallbackQueryHandler(admin_edit_specific_message_callback, pattern='^admin_edit_specific_msg_'),
#     #     ],
#     #     states={
#     #         EDIT_MESSAGE_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_new_message_text)],
#     #     },
#     #     fallbacks=[
#     #         CommandHandler('cancel_edit', cancel_edit_command),
#     #         CallbackQueryHandler(admin_show_tools_menu_callback, pattern='^admin_show_tools_menu$'), # Fallback to menu
#     #     ],
#     #     map_to_parent={
#     #         ConversationHandler.END: ConversationHandler.END # Or a state to return to admin menu
#     #     }
#     # )

#     # # Conversation handler for broadcasting messages
#     # broadcast_conv_handler = ConversationHandler(
#     #     entry_points=[CallbackQueryHandler(admin_broadcast_start_callback, pattern='^admin_broadcast_start$')],
#     #     states={
#     #         BROADCAST_MESSAGE_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_broadcast_text)],
#     #         BROADCAST_CONFIRM: [
#     #             CallbackQueryHandler(admin_broadcast_confirm_callback, pattern='^admin_broadcast_confirm$'),
#     #             CallbackQueryHandler(admin_broadcast_cancel_callback, pattern='^admin_broadcast_cancel$')
#     #         ]
#     #     },
#     #     fallbacks=[
#     #         CommandHandler('cancel_broadcast', cancel_broadcast_command),
#     #         CallbackQueryHandler(admin_show_tools_menu_callback, pattern='^admin_show_tools_menu$'),
#     #     ],
#     #     map_to_parent={
#     #         ConversationHandler.END: ConversationHandler.END
#     #     }
#     # )
    
#     # # Main conversation handler for admin tools to nest others or manage flow
#     # admin_tools_conv = ConversationHandler(
#     #     entry_points=[CallbackQueryHandler(admin_show_tools_menu_callback, pattern='^admin_show_tools_menu$')],
#     #     states={
#     #         # States for the main admin menu if needed, or directly use nested handlers
#     #         # For simplicity, we might add edit_message_conv_handler and broadcast_conv_handler directly to application
#     #     },
#     #     fallbacks=[CommandHandler('start', start_command)] # Example fallback
#     # )

#     # application.add_handler(CommandHandler("start", start_command))
#     # application.add_handler(CommandHandler("about", about_command))
#     # application.add_handler(CommandHandler("help", help_command))
#     # application.add_handler(CallbackQueryHandler(admin_show_tools_menu_callback, pattern='^admin_show_tools_menu$'))
#     # application.add_handler(CallbackQueryHandler(admin_edit_other_messages_menu_callback, pattern='^admin_edit_other_messages_menu$'))
#     # application.add_handler(CallbackQueryHandler(admin_back_to_start_callback, pattern='^admin_back_to_start$'))

#     # # Add conversation handlers
#     # application.add_handler(edit_message_conv_handler)
#     # application.add_handler(broadcast_conv_handler)

#     # # Add other callback query handlers (e.g., for stats_admin_panel_v4 if it's a callback)
#     # # from admin_dashboard_display_v18_arabic_final_review import stats_admin_panel_command_handler_v4 # Assuming it's a command
#     # # application.add_handler(CommandHandler("adminstats_v4", stats_admin_panel_command_handler_v4))


#     # logging.info("Bot starting...")
#     # application.run_polling()

logging.info("admin_interface_v15_admin_tools.py loaded with admin tool UI and handlers.")

