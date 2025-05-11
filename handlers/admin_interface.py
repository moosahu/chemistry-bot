# admin_interface.py (v4 - Integrated with admin_dashboard_display)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputMediaPhoto
from telegram.ext import CommandHandler, CallbackQueryHandler, CallbackContext
import os # Added for file operations

from utils.admin_auth import is_admin
from database.manager import DB_MANAGER
from config import logger # Assuming logger is configured in config.py

# Import new display functions
from .admin_dashboard_display import (
    get_usage_overview_display,
    get_quiz_performance_display,
    get_user_interaction_display,
    get_question_stats_display,
    TIME_FILTERS_DISPLAY
)

# Callback data prefixes
STATS_PREFIX_MAIN_MENU = "stats_menu_v4_"
STATS_PREFIX_FETCH = "stats_fetch_v4_"
# PREFIX_TIME_FILTER = "filter_" # This one seems unused by admin stats, but kept for now

# Time filter options (using TIME_FILTERS_DISPLAY from admin_dashboard_display for consistency)
# TIME_FILTERS = {
# "today": "اليوم",
# "last_7_days": "آخر 7 أيام",
# "last_30_days": "آخر 30 يومًا",
# "all_time": "كل الوقت"
# }

def get_time_filter_buttons_v4(stat_category_base_callback: str):
    keyboard = []
    row = []
    for key, text in TIME_FILTERS_DISPLAY.items():
        row.append(InlineKeyboardButton(text, callback_data=f"{stat_category_base_callback}_{key}"))
        if len(row) == 2:  # Max 2 buttons per row for time filters
            keyboard.append(row)
            row = []
    if row:  # Add remaining buttons if any
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data=f"{STATS_PREFIX_MAIN_MENU}main")])
    return InlineKeyboardMarkup(keyboard)

async def stats_admin_panel_command_handler_v4(update: Update, context: CallbackContext):
    if not await is_admin(update, context): # Ensure is_admin is awaited if it becomes async
        await update.message.reply_text("عذراً، هذا الأمر مخصص للأدمن فقط.")
        return
    await show_main_stats_menu_v4(update, context)

async def show_main_stats_menu_v4(update: Update, context: CallbackContext, query=None):
    keyboard = [
        [InlineKeyboardButton("📊 نظرة عامة على الاستخدام", callback_data=f"{STATS_PREFIX_MAIN_MENU}usage_overview")],
        [InlineKeyboardButton("📈 أداء الاختبارات", callback_data=f"{STATS_PREFIX_MAIN_MENU}quiz_performance")],
        [InlineKeyboardButton("👥 تفاعل المستخدمين", callback_data=f"{STATS_PREFIX_MAIN_MENU}user_interaction")],
        [InlineKeyboardButton("❓ إحصائيات الأسئلة", callback_data=f"{STATS_PREFIX_MAIN_MENU}question_stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = "لوحة تحكم إحصائيات الأدمن (v4): اختر فئة لعرضها"
    if query:
        try:
            await query.edit_message_text(text=message_text, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error editing message in show_main_stats_menu_v4: {e}")
            # Fallback: send new message if edit fails (e.g., message too old)
            if update.effective_chat:
                 await context.bot.send_message(chat_id=update.effective_chat.id, text=message_text, reply_markup=reply_markup)
            else:
                logger.error("Cannot send fallback message: update.effective_chat is None")

    elif update.message:
        await update.message.reply_text(text=message_text, reply_markup=reply_markup)
    elif update.effective_chat: # If called without query or message but with chat context
        await context.bot.send_message(chat_id=update.effective_chat.id, text=message_text, reply_markup=reply_markup)

async def stats_menu_callback_handler_v4(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    if not await is_admin(update, context):
        try:
            await query.edit_message_text(text="عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط.")
        except Exception as e:
            logger.error(f"Error editing message in stats_menu_callback_handler_v4 (auth fail): {e}")
        return

    callback_data = query.data

    if callback_data == f"{STATS_PREFIX_MAIN_MENU}main":
        await show_main_stats_menu_v4(update, context, query=query)
        return

    # Example: stats_menu_v4_usage_overview -> usage_overview
    stat_category_base = callback_data.replace(STATS_PREFIX_MAIN_MENU, "") 
    fetch_base_callback = f"{STATS_PREFIX_FETCH}{stat_category_base}" # e.g. stats_fetch_v4_usage_overview

    reply_markup = get_time_filter_buttons_v4(fetch_base_callback)
    # Create a user-friendly title from stat_category_base
    stat_category_title_map = {
        "usage_overview": "نظرة عامة على الاستخدام",
        "quiz_performance": "أداء الاختبارات",
        "user_interaction": "تفاعل المستخدمين",
        "question_stats": "إحصائيات الأسئلة"
    }
    stat_category_title = stat_category_title_map.get(stat_category_base, stat_category_base.replace("_", " ").title())
    message_text_for_edit = f"اختر الفترة الزمنية لـ: {stat_category_title}"
    try:
        await query.edit_message_text(text=message_text_for_edit, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error editing message in stats_menu_callback_handler_v4: {e}")

async def stats_fetch_callback_handler_v4(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    if not await is_admin(update, context):
        try:
            await query.edit_message_text(text="عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط.")
        except Exception as e:
            logger.error(f"Error editing message in stats_fetch_callback_handler_v4 (auth fail): {e}")
        return

    # query.data format: stats_fetch_v4_{stat_category}_{time_filter_key}
    # e.g. stats_fetch_v4_usage_overview_last_7_days
    parts = query.data.split("_")
    time_filter_key = parts[-1]
    if parts[-2] in ["7", "30"] and parts[-3] == "last": # Handle cases like "last_7_days" or "last_30_days"
        time_filter_key = parts[-3] + "_" + parts[-2] + "_" + parts[-1]
        stat_category_str = "_".join(parts[3:-3]) # parts[0]=stats, parts[1]=fetch, parts[2]=v4
    else:
        stat_category_str = "_".join(parts[3:-1])

    time_filter_text = TIME_FILTERS_DISPLAY.get(time_filter_key, "كل الوقت")
    stat_category_display_title_map = {
        "usage_overview": "نظرة عامة على الاستخدام",
        "quiz_performance": "أداء الاختبارات",
        "user_interaction": "تفاعل المستخدمين",
        "question_stats": "إحصائيات الأسئلة"
    }
    stat_category_display_title = stat_category_display_title_map.get(stat_category_str, stat_category_str.replace("_", " ").title())
    
    loading_message_text = f"⏳ جاري جلب بيانات {stat_category_display_title} عن فترة: {time_filter_text}..."
    try:
        await query.edit_message_text(text=loading_message_text)
    except Exception as e:
        logger.error(f"Error editing message in stats_fetch_callback_handler_v4 (loading): {e}")
        # If edit fails, we might not be able to show loading, proceed to fetch stats

    await send_dashboard_stats_v4(update, context, stat_category_str, time_filter_key)

async def send_dashboard_stats_v4(update: Update, context: CallbackContext, stat_category: str, time_filter: str):
    query = update.callback_query
    text_response = ""
    chart_path = None

    if stat_category == "usage_overview":
        text_response, chart_path = await get_usage_overview_display(time_filter)
    elif stat_category == "quiz_performance":
        text_response, chart_path = await get_quiz_performance_display(time_filter)
    elif stat_category == "user_interaction":
        text_response, chart_path = await get_user_interaction_display(time_filter)
    elif stat_category == "question_stats":
        text_response, chart_path = await get_question_stats_display(time_filter)
    else:
        text_response = f"فئة الإحصائيات 	'{stat_category}	' غير معروفة أو لم يتم تنفيذها بعد."

    # Prepare reply markup (time filter buttons for re-selection or back to main menu)
    fetch_base_callback = f"{STATS_PREFIX_FETCH}{stat_category}"
    reply_markup = get_time_filter_buttons_v4(fetch_base_callback)

    try:
        if chart_path and os.path.exists(chart_path):
            # Send chart first, then edit the message with text and buttons
            # Or, edit message to a generic one, then send photo with caption and buttons
            # For simplicity, let's edit the original message with text, then send photo separately.
            await query.edit_message_text(text=text_response, reply_markup=reply_markup, parse_mode="Markdown")
            with open(chart_path, "rb") as photo_file:
                await context.bot.send_photo(chat_id=query.message.chat_id, photo=photo_file, caption=f"رسم بياني لـ: {stat_category.replace('_', ' ').title()}")
            # try:
            #     os.remove(chart_path) # Clean up chart file after sending
            #     logger.info(f"Deleted chart file: {chart_path}")
            # except OSError as e:
            #     logger.error(f"Error deleting chart file {chart_path}: {e}")
        else:
            if chart_path: # Path was returned but file doesn't exist
                logger.warning(f"Chart path {chart_path} was returned but file not found.")
            await query.edit_message_text(text=text_response, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error sending/editing message in send_dashboard_stats_v4: {e}")
        # Fallback if edit_message_text fails
        try:
            await context.bot.send_message(chat_id=query.message.chat_id, text=text_response, reply_markup=reply_markup, parse_mode='Markdown')
            if chart_path and os.path.exists(chart_path):
                 with open(chart_path, "rb") as photo_file:
                    await context.bot.send_photo(chat_id=query.message.chat_id, photo=photo_file, caption=f"رسم بياني لـ: {stat_category.replace('_', ' ').title()}")
        except Exception as fallback_e:
            logger.error(f"Fallback send_message also failed in send_dashboard_stats_v4: {fallback_e}")

# It's crucial to register these new handlers in your bot.py or main application file.
# Example (these would go into the file where you set up your Application):
# from handlers.admin_interface_v4 import stats_admin_panel_command_handler_v4, stats_menu_callback_handler_v4, stats_fetch_callback_handler_v4, STATS_PREFIX_MAIN_MENU, STATS_PREFIX_FETCH
#
# admin_stats_conv_handler_v4 = ConversationHandler(
# entry_points=[CommandHandler("adminstats_v4", stats_admin_panel_command_handler_v4)],
# states={
# STATS_PREFIX_MAIN_MENU: [CallbackQueryHandler(stats_menu_callback_handler_v4, pattern=f"^{STATS_PREFIX_MAIN_MENU}")],
# STATS_PREFIX_FETCH: [CallbackQueryHandler(stats_fetch_callback_handler_v4, pattern=f"^{STATS_PREFIX_FETCH}")],
#         # Potentially add more states if the conversation becomes more complex
#     },
# fallbacks=[CommandHandler("adminstats_v4", stats_admin_panel_command_handler_v4)], # Or a cancel handler
#     # name="admin_stats_conversation_v4", # Optional: for persistence if needed, but usually not for menus
#     # persistent=False # Typically False for menu-driven interactions
# )
# application.add_handler(admin_stats_conv_handler_v4)

# For non-conversation handler approach (simpler, as used in v3):
# application.add_handler(CommandHandler("adminstats_v4", stats_admin_panel_command_handler_v4))
# application.add_handler(CallbackQueryHandler(stats_menu_callback_handler_v4, pattern=f"^{STATS_PREFIX_MAIN_MENU}"))
# application.add_handler(CallbackQueryHandler(stats_fetch_callback_handler_v4, pattern=f"^{STATS_PREFIX_FETCH}"))

async def is_admin(update: Update, context: CallbackContext) -> bool:
    """Checks if the user is an admin. Placeholder, adapt to your actual admin check."""
    user = update.effective_user
    if not user:
        return False
    # Replace with your actual admin checking logic, e.g., checking a list of admin IDs
    # from config import ADMIN_USER_IDS
    # return user.id in ADMIN_USER_IDS
    # For now, using the DB_MANAGER method if available, or a placeholder
    if hasattr(DB_MANAGER, 'is_user_admin'):
        return DB_MANAGER.is_user_admin(user.id)
    logger.warning("is_admin check in admin_interface_v4.py is using a placeholder. Configure ADMIN_USER_IDS or ensure DB_MANAGER.is_user_admin is implemented.")
    # Fallback to a predefined admin ID for testing if nothing else is set up
    # return user.id == 123456789 # Example admin ID, DO NOT USE IN PRODUCTION
    return False # Default to False if no admin check is properly configured


