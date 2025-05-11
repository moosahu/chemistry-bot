# admin_interface.py (v4 - Integrated with admin_dashboard_display - DEBUG LOGGING ADDED)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputMediaPhoto
from telegram.ext import CommandHandler, CallbackQueryHandler, CallbackContext
import os # Added for file operations

from utils.admin_auth import is_admin as is_admin_original # Renamed to avoid conflict with our logging version
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

logger.info("[AdminInterfaceV4_Debug] Module loaded.")

async def is_admin(update: Update, context: CallbackContext) -> bool:
    """Checks if the user is an admin. WITH DETAILED LOGGING."""
    user = update.effective_user
    if not user:
        logger.warning("[AdminInterfaceV4_Debug] is_admin: No effective_user found in update.")
        return False
    
    user_id = user.id
    logger.info(f"[AdminInterfaceV4_Debug] is_admin: Checking admin status for user_id: {user_id}")
    
    # Replace with your actual admin checking logic, e.g., checking a list of admin IDs
    # from config import ADMIN_USER_IDS
    # admin_status = user.id in ADMIN_USER_IDS
    # logger.info(f"[AdminInterfaceV4_Debug] is_admin: Status from ADMIN_USER_IDS check: {admin_status} for user_id: {user_id}")
    # return admin_status

    # Using the DB_MANAGER method if available
    if hasattr(DB_MANAGER, 'is_user_admin'):
        logger.info(f"[AdminInterfaceV4_Debug] is_admin: Calling DB_MANAGER.is_user_admin for user_id: {user_id}")
        try:
            admin_status = DB_MANAGER.is_user_admin(user_id)
            logger.info(f"[AdminInterfaceV4_Debug] is_admin: DB_MANAGER.is_user_admin returned {admin_status} for user_id: {user_id}")
            return admin_status
        except Exception as e:
            logger.error(f"[AdminInterfaceV4_Debug] is_admin: Error calling DB_MANAGER.is_user_admin for user_id: {user_id}. Error: {e}", exc_info=True)
            return False # Default to False on error
    else:
        logger.warning("[AdminInterfaceV4_Debug] is_admin: DB_MANAGER.is_user_admin method not found. Falling back to placeholder.")

    # Fallback placeholder if DB_MANAGER.is_user_admin is not available
    # THIS IS A PLACEHOLDER AND SHOULD BE REPLACED WITH ACTUAL ADMIN LOGIC
    # For example, checking against a list of admin IDs from config.py
    # from config import ADMIN_IDS # Ensure ADMIN_IDS is defined in your config.py
    # if user_id in ADMIN_IDS:
    #     logger.info(f"[AdminInterfaceV4_Debug] is_admin: User {user_id} is in ADMIN_IDS (placeholder).")
    #     return True
    
    logger.warning(f"[AdminInterfaceV4_Debug] is_admin: No definitive admin check performed for user_id: {user_id}. Defaulting to False. PLEASE CONFIGURE ADMIN CHECK.")
    return False # Default to False if no admin check is properly configured

def get_time_filter_buttons_v4(stat_category_base_callback: str):
    logger.debug(f"[AdminInterfaceV4_Debug] get_time_filter_buttons_v4 called with base: {stat_category_base_callback}")
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
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV4_Debug] stats_admin_panel_command_handler_v4: Received command from user_id: {user_id}")
    
    is_user_admin_result = await is_admin(update, context)
    logger.info(f"[AdminInterfaceV4_Debug] stats_admin_panel_command_handler_v4: is_admin check result for user_id {user_id}: {is_user_admin_result}")

    if not is_user_admin_result:
        logger.warning(f"[AdminInterfaceV4_Debug] stats_admin_panel_command_handler_v4: User {user_id} is NOT an admin. Replying with auth error.")
        if update.message:
            await update.message.reply_text("عذراً، هذا الأمر مخصص للأدمن فقط.")
        else:
            logger.warning("[AdminInterfaceV4_Debug] stats_admin_panel_command_handler_v4: No update.message to reply to for non-admin.")
        return
    
    logger.info(f"[AdminInterfaceV4_Debug] stats_admin_panel_command_handler_v4: User {user_id} IS an admin. Proceeding to show main stats menu.")
    await show_main_stats_menu_v4(update, context)

async def show_main_stats_menu_v4(update: Update, context: CallbackContext, query=None):
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV4_Debug] show_main_stats_menu_v4: Called for user_id: {user_id}. Query present: {query is not None}")
    keyboard = [
        [InlineKeyboardButton("📊 نظرة عامة على الاستخدام", callback_data=f"{STATS_PREFIX_MAIN_MENU}usage_overview")],
        [InlineKeyboardButton("📈 أداء الاختبارات", callback_data=f"{STATS_PREFIX_MAIN_MENU}quiz_performance")],
        [InlineKeyboardButton("👥 تفاعل المستخدمين", callback_data=f"{STATS_PREFIX_MAIN_MENU}user_interaction")],
        [InlineKeyboardButton("❓ إحصائيات الأسئلة", callback_data=f"{STATS_PREFIX_MAIN_MENU}question_stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = "لوحة تحكم إحصائيات الأدمن (v4): اختر فئة لعرضها"
    
    if query:
        logger.debug(f"[AdminInterfaceV4_Debug] show_main_stats_menu_v4: Editing message for query from user_id: {user_id}")
        try:
            await query.edit_message_text(text=message_text, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"[AdminInterfaceV4_Debug] Error editing message in show_main_stats_menu_v4: {e}", exc_info=True)
            if update.effective_chat:
                 await context.bot.send_message(chat_id=update.effective_chat.id, text=message_text, reply_markup=reply_markup)
            else:
                logger.error("[AdminInterfaceV4_Debug] Cannot send fallback message: update.effective_chat is None")
    elif update.message:
        logger.debug(f"[AdminInterfaceV4_Debug] show_main_stats_menu_v4: Replying to message from user_id: {user_id}")
        await update.message.reply_text(text=message_text, reply_markup=reply_markup)
    elif update.effective_chat:
        logger.debug(f"[AdminInterfaceV4_Debug] show_main_stats_menu_v4: Sending new message to chat_id: {update.effective_chat.id} (user_id: {user_id})")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=message_text, reply_markup=reply_markup)
    else:
        logger.warning("[AdminInterfaceV4_Debug] show_main_stats_menu_v4: No query, message, or effective_chat to send to.")

async def stats_menu_callback_handler_v4(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV4_Debug] stats_menu_callback_handler_v4: Received callback: {query.data} from user_id: {user_id}")
    await query.answer()

    is_user_admin_result = await is_admin(update, context) # Check admin status again for callbacks
    logger.info(f"[AdminInterfaceV4_Debug] stats_menu_callback_handler_v4: is_admin check result for user_id {user_id}: {is_user_admin_result}")
    if not is_user_admin_result:
        logger.warning(f"[AdminInterfaceV4_Debug] stats_menu_callback_handler_v4: User {user_id} is NOT an admin. Replying with auth error.")
        try:
            await query.edit_message_text(text="عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط.")
        except Exception as e:
            logger.error(f"[AdminInterfaceV4_Debug] Error editing message in stats_menu_callback_handler_v4 (auth fail): {e}", exc_info=True)
        return

    logger.info(f"[AdminInterfaceV4_Debug] stats_menu_callback_handler_v4: User {user_id} IS an admin. Processing callback: {query.data}")
    callback_data = query.data

    if callback_data == f"{STATS_PREFIX_MAIN_MENU}main":
        logger.debug(f"[AdminInterfaceV4_Debug] stats_menu_callback_handler_v4: Navigating back to main menu for user_id: {user_id}")
        await show_main_stats_menu_v4(update, context, query=query)
        return

    stat_category_base = callback_data.replace(STATS_PREFIX_MAIN_MENU, "") 
    fetch_base_callback = f"{STATS_PREFIX_FETCH}{stat_category_base}"
    logger.debug(f"[AdminInterfaceV4_Debug] stats_menu_callback_handler_v4: Category base: {stat_category_base}, Fetch base: {fetch_base_callback} for user_id: {user_id}")

    reply_markup = get_time_filter_buttons_v4(fetch_base_callback)
    stat_category_title_map = {
        "usage_overview": "نظرة عامة على الاستخدام",
        "quiz_performance": "أداء الاختبارات",
        "user_interaction": "تفاعل المستخدمين",
        "question_stats": "إحصائيات الأسئلة"
    }
    stat_category_title = stat_category_title_map.get(stat_category_base, stat_category_base.replace("_", " ").title())
    message_text_for_edit = f"اختر الفترة الزمنية لـ: {stat_category_title}"
    logger.debug(f"[AdminInterfaceV4_Debug] stats_menu_callback_handler_v4: Editing message to show time filters for '{stat_category_title}' for user_id: {user_id}")
    try:
        await query.edit_message_text(text=message_text_for_edit, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"[AdminInterfaceV4_Debug] Error editing message in stats_menu_callback_handler_v4: {e}", exc_info=True)

async def stats_fetch_callback_handler_v4(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV4_Debug] stats_fetch_callback_handler_v4: Received callback: {query.data} from user_id: {user_id}")
    await query.answer()

    is_user_admin_result = await is_admin(update, context) # Check admin status again
    logger.info(f"[AdminInterfaceV4_Debug] stats_fetch_callback_handler_v4: is_admin check result for user_id {user_id}: {is_user_admin_result}")
    if not is_user_admin_result:
        logger.warning(f"[AdminInterfaceV4_Debug] stats_fetch_callback_handler_v4: User {user_id} is NOT an admin. Replying with auth error.")
        try:
            await query.edit_message_text(text="عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط.")
        except Exception as e:
            logger.error(f"[AdminInterfaceV4_Debug] Error editing message in stats_fetch_callback_handler_v4 (auth fail): {e}", exc_info=True)
        return

    logger.info(f"[AdminInterfaceV4_Debug] stats_fetch_callback_handler_v4: User {user_id} IS an admin. Processing callback: {query.data}")
    parts = query.data.split("_")
    time_filter_key = parts[-1]
    if parts[-2] in ["7", "30"] and parts[-3] == "last":
        time_filter_key = parts[-3] + "_" + parts[-2] + "_" + parts[-1]
        stat_category_str = "_".join(parts[3:-3])
    else:
        stat_category_str = "_".join(parts[3:-1])
    logger.debug(f"[AdminInterfaceV4_Debug] stats_fetch_callback_handler_v4: Parsed category: {stat_category_str}, time_filter: {time_filter_key} for user_id: {user_id}")

    time_filter_text = TIME_FILTERS_DISPLAY.get(time_filter_key, "كل الوقت")
    stat_category_display_title_map = {
        "usage_overview": "نظرة عامة على الاستخدام",
        "quiz_performance": "أداء الاختبارات",
        "user_interaction": "تفاعل المستخدمين",
        "question_stats": "إحصائيات الأسئلة"
    }
    stat_category_display_title = stat_category_display_title_map.get(stat_category_str, stat_category_str.replace("_", " ").title())
    
    loading_message_text = f"⏳ جاري جلب بيانات {stat_category_display_title} عن فترة: {time_filter_text}..."
    logger.debug(f"[AdminInterfaceV4_Debug] stats_fetch_callback_handler_v4: Editing message to show loading for '{stat_category_display_title}' for user_id: {user_id}")
    try:
        await query.edit_message_text(text=loading_message_text)
    except Exception as e:
        logger.error(f"[AdminInterfaceV4_Debug] Error editing message in stats_fetch_callback_handler_v4 (loading): {e}", exc_info=True)

    await send_dashboard_stats_v4(update, context, stat_category_str, time_filter_key)

async def send_dashboard_stats_v4(update: Update, context: CallbackContext, stat_category: str, time_filter: str):
    query = update.callback_query
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV4_Debug] send_dashboard_stats_v4: Called for category '{stat_category}', filter '{time_filter}' by user_id: {user_id}")
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
        logger.warning(f"[AdminInterfaceV4_Debug] send_dashboard_stats_v4: Unknown stat_category '{stat_category}' for user_id: {user_id}")
        text_response = f"فئة الإحصائيات 	'{stat_category}	' غير معروفة أو لم يتم تنفيذها بعد."

    fetch_base_callback = f"{STATS_PREFIX_FETCH}{stat_category}"
    reply_markup = get_time_filter_buttons_v4(fetch_base_callback)
    logger.debug(f"[AdminInterfaceV4_Debug] send_dashboard_stats_v4: Preparing to send/edit message for user_id: {user_id}. Chart path: {chart_path}")

    try:
        if chart_path and os.path.exists(chart_path):
            logger.info(f"[AdminInterfaceV4_Debug] send_dashboard_stats_v4: Chart found at {chart_path}. Sending photo then editing message for user_id: {user_id}.")
            await query.edit_message_text(text=text_response, reply_markup=reply_markup, parse_mode="Markdown")
            with open(chart_path, "rb") as photo_file:
                await context.bot.send_photo(chat_id=query.message.chat_id, photo=photo_file, caption=f"رسم بياني لـ: {stat_category.replace('_', ' ').title()}")
        else:
            if chart_path:
                logger.warning(f"[AdminInterfaceV4_Debug] send_dashboard_stats_v4: Chart path {chart_path} was returned but file not found for user_id: {user_id}.")
            else:
                logger.debug(f"[AdminInterfaceV4_Debug] send_dashboard_stats_v4: No chart path provided. Editing message with text only for user_id: {user_id}.")
            await query.edit_message_text(text=text_response, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"[AdminInterfaceV4_Debug] Error sending/editing message in send_dashboard_stats_v4: {e}", exc_info=True)
        try:
            logger.warning(f"[AdminInterfaceV4_Debug] send_dashboard_stats_v4: Attempting fallback send_message for user_id: {user_id}")
            await context.bot.send_message(chat_id=query.message.chat_id, text=text_response, reply_markup=reply_markup, parse_mode='Markdown')
            if chart_path and os.path.exists(chart_path):
                 with open(chart_path, "rb") as photo_file:
                    await context.bot.send_photo(chat_id=query.message.chat_id, photo=photo_file, caption=f"رسم بياني لـ: {stat_category.replace('_', ' ').title()}")
        except Exception as fallback_e:
            logger.error(f"[AdminInterfaceV4_Debug] Fallback send_message also failed in send_dashboard_stats_v4: {fallback_e}", exc_info=True)

logger.info("[AdminInterfaceV4_Debug] All function definitions complete.")

